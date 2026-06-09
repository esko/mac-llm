"""Shared generation logic for run, chat, and serve."""
import os, sys, time, json
import numpy as np

STOP_TOKENS = {"<|im_end|>", "<|endoftext|>", "<|im_start|>"}


def ensure_gemma4_chat_template(model_dir: str) -> None:
    """Copy chat_template.jinja into the model dir when preprocess omitted it."""
    dest = os.path.join(model_dir, "chat_template.jinja")
    if os.path.exists(dest):
        return
    try:
        from huggingface_hub import hf_hub_download

        hf_hub_download(
            "google/gemma-4-26B-A4B-it",
            "chat_template.jinja",
            local_dir=model_dir,
        )
    except Exception:
        return


def load_engine(model_dir):
    """Load engine with calibration. Returns (engine, bias, model_type)."""
    os.environ["TOKENIZERS_PARALLELISM"] = "false"
    import mlx.core as mx
    from .calibrate import load_calibration, auto_size_cache, _detect_model_type

    model_type = _detect_model_type(model_dir)
    if "gemma4" in model_type:
        ensure_gemma4_chat_template(model_dir)

    cal = load_calibration(model_dir)
    if cal:
        cache_size = cal["cache_size"]
        bias = cal["routing_bias"]
    else:
        cache_size, _, _ = auto_size_cache(model_dir)
        bias = 0.0

    if "gemma4" in model_type:
        from . import engine_gemma4 as engine_mod
        engine_mod.MODEL_DIR = model_dir
        from .engine_gemma4 import MoESniperEngineGemma4 as EngineClass
    elif "qwen3_next" in model_type:
        from . import engine_next as engine_mod
        engine_mod.MODEL_DIR = model_dir
        from .engine_next import MoESniperEngineNext as EngineClass
    elif "qwen3_5" in model_type:
        from . import engine as engine_mod
        engine_mod.MODEL_DIR = model_dir
        from .engine import MoESniperEngine35B as EngineClass
    else:
        from . import engine_30b as engine_mod
        engine_mod.MODEL_DIR = model_dir
        from .engine_30b import MoESniperEngine30B as EngineClass

    eng = EngineClass(cache_size=cache_size, enable_prediction=True)
    eng.load()
    return eng, bias, model_type


def generate_stream(engine, messages, bias=0.0, max_tokens=200):
    """Generator yielding token strings. Handles Qwen + Gemma 4 architectures."""
    import mlx.core as mx
    from mlx_lm.models.base import create_attention_mask

    # Detect model type — Gemma 4 uses its own forward pass
    is_gemma4 = hasattr(engine, 'per_expert_scales')  # Gemma 4 engine has this
    if is_gemma4:
        return _generate_stream_gemma4(engine, messages, bias=bias, max_tokens=max_tokens)

    from .engine import run_expert_ffn
    has_ssm = hasattr(engine.model.model, 'fa_idx')
    num_experts = 256 if has_ssm else 128

    engine.reset_cache()
    tok = engine.tokenizer
    try:
        text = tok.apply_chat_template(messages, tokenize=False,
                                        add_generation_prompt=True, enable_thinking=False)
    except Exception:
        try:
            text = tok.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        except Exception:
            text = messages[-1]["content"]
    tokens = tok.encode(text)
    input_ids = mx.array([tokens])

    def forward(inp):
        h = engine.model.model.embed_tokens(inp)
        if has_ssm:
            from mlx_lm.models.base import create_ssm_mask
            fa_mask = create_attention_mask(h, engine.cache[engine.model.model.fa_idx])
            ssm_mask = create_ssm_mask(h, engine.cache[engine.model.model.ssm_idx])
        else:
            fa_mask = create_attention_mask(h, engine.cache[0])
            ssm_mask = None

        for i in range(engine.num_layers):
            layer = engine.model.model.layers[i]
            if has_ssm:
                mask = ssm_mask if layer.is_linear else fa_mask
            else:
                mask = fa_mask
            normed = layer.input_layernorm(h)
            if has_ssm and layer.is_linear:
                attn_out = layer.linear_attn(normed, mask=mask, cache=engine.cache[i])
            else:
                attn_out = layer.self_attn(normed, mask=mask, cache=engine.cache[i])
            h = h + attn_out
            mx.eval(h)

            normed = layer.post_attention_layernorm(h)
            raw_logits = layer.mlp.gate(normed)
            if bias > 0 and engine.reader.lru is not None:
                cached_mask = np.zeros(num_experts, dtype=np.float32)
                for eid in range(num_experts):
                    if engine.reader.lru.get(i, eid) is not None:
                        cached_mask[eid] = bias
                raw_logits = raw_logits + mx.array(cached_mask).reshape(1, -1)

            gates = mx.softmax(raw_logits, axis=-1, precise=True)
            k = layer.mlp.top_k
            inds = mx.argpartition(gates, kth=-k, axis=-1)[..., -k:]
            scores = mx.take_along_axis(gates, inds, axis=-1)
            if layer.mlp.norm_topk_prob:
                scores = scores / scores.sum(axis=-1, keepdims=True)
            mx.eval(inds, scores)

            active_ids = list(set(int(e) for e in np.array(inds).flatten()))
            engine.coact.record_layer(i, active_ids)
            if engine.coact.ready and i + 1 < engine.num_layers:
                predicted = engine.coact.predict_next_layer(i, active_ids, top_k=6)
                if predicted:
                    to_fetch = [eid for eid in predicted
                                if engine.reader.lru and engine.reader.lru.get(i+1, eid) is None]
                    if to_fetch:
                        engine.reader.prefetch_experts(i+1, to_fetch)
            if i + 1 < engine.num_layers:
                engine.reader.prefetch_experts(i+1, active_ids)

            expert_data = engine.reader.get_experts(i, active_ids)
            expert_out = run_expert_ffn(normed, expert_data, inds, scores)

            if hasattr(layer.mlp, 'shared_expert'):
                shared_out = layer.mlp.shared_expert(normed)
                shared_gate = mx.sigmoid(layer.mlp.shared_expert_gate(normed))
                if shared_gate.ndim < shared_out.ndim:
                    shared_gate = shared_gate[..., None]
                expert_out = expert_out + shared_gate * shared_out

            h = h + expert_out
            mx.eval(h)
            del expert_data, expert_out, normed, attn_out
            mx.clear_cache()

        engine.coact.end_token()
        h = engine.model.model.norm(h)
        return engine.model.lm_head(h)

    logits = forward(input_ids)
    mx.eval(logits)

    eos_ids = {248044, 248045}
    tok_obj = engine.tokenizer

    for _ in range(max_tokens):
        token = mx.argmax(logits[:, -1, :], axis=-1)
        mx.eval(token)
        tid = token.item()
        if tid in eos_ids:
            break
        chunk = tok_obj.decode([tid])
        if any(st in chunk for st in STOP_TOKENS):
            break
        yield chunk
        logits = forward(token.reshape(1, 1))
        mx.eval(logits)


_GEMMA4_CHANNEL_CLOSE = "<|channel|>"
_GEMMA4_GENERATION_PRIME = (
    f"<|turn>model\n<|channel>thought\n{_GEMMA4_CHANNEL_CLOSE}\n"
)
_GEMMA4_CONTROL_MARKERS = (
    "<|channel>",
    "<channel|>",
    "<|channel>thought",
    "<|turn>",
    "<|think|>",
    "<|tool",
    "<bos>",
    "<eos>",
)


def _gemma4_finalize_generation_prompt(text: str) -> str:
    """Close the empty-thinking block in the prompt so the model answers immediately."""
    if "<|channel>thought" not in text:
        return text
    if _GEMMA4_CHANNEL_CLOSE in text or "<channel|>" in text:
        return text
    return text.rstrip() + f"\n{_GEMMA4_CHANNEL_CLOSE}\n"


def _gemma4_decode_token(tok, tid: int) -> str:
    try:
        return tok.decode([tid], skip_special_tokens=True)
    except TypeError:
        return tok.decode([tid])


def _gemma4_should_yield(chunk: str) -> bool:
    """Return False for Gemma 4 structural/control tokens that are not user text."""
    if not chunk:
        return False
    stripped = chunk.strip()
    if not stripped:
        return False
    for marker in _GEMMA4_CONTROL_MARKERS:
        if marker in chunk or stripped == marker:
            return False
    return True


def _gemma4_encode_text(tok, text: str) -> list[int]:
    """Encode a fully formatted Gemma 4 prompt string."""
    try:
        enc = tok.encode(text, add_special_tokens=False)
    except TypeError:
        enc = tok.encode(text)
    if hasattr(enc, "ids"):
        return list(enc.ids)
    return list(enc)


def _gemma4_normalize_messages(messages: list[dict]) -> list[dict]:
    """Fold system prompts into the next user turn (Gemma 4 has no system role)."""
    normalized: list[dict] = []
    pending_system: str | None = None
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "") or ""
        if role == "system":
            pending_system = (
                f"{pending_system}\n\n{content}" if pending_system else content
            )
            continue
        if role == "user" and pending_system:
            content = f"{pending_system}\n\n{content}"
            pending_system = None
        normalized.append({"role": role, "content": content})
    if pending_system and not normalized:
        normalized.append({"role": "user", "content": pending_system})
    return normalized


def _gemma4_manual_chat_text(tok, messages: list[dict]) -> str:
    """Build Gemma 4 chat text matching the official template (thinking off)."""
    bos = getattr(tok, "bos_token", None) or "<bos>"
    parts = [bos]
    for msg in messages:
        role = "model" if msg["role"] == "assistant" else msg["role"]
        parts.append(f"<|turn>{role}\n{msg['content']} \n")
    parts.append(_GEMMA4_GENERATION_PRIME)
    return "".join(parts)


def _gemma4_chat_tokens(tok, messages: list[dict]) -> list[int]:
    """Tokenize Gemma 4 chat input with the official empty-thinking prime."""
    normalized = _gemma4_normalize_messages(messages)

    if getattr(tok, "chat_template", None):
        try:
            text = tok.apply_chat_template(
                normalized,
                tokenize=False,
                add_generation_prompt=True,
                enable_thinking=False,
            )
            text = _gemma4_finalize_generation_prompt(text)
            return _gemma4_encode_text(tok, text)
        except Exception:
            pass

    return _gemma4_encode_text(tok, _gemma4_manual_chat_text(tok, normalized))


def _gemma4_generation_stop_ids(tok) -> set[int]:
    """Stop tokens during Gemma 4 generation."""
    from .calibrate import _gemma4_eos_ids

    return _gemma4_eos_ids(tok)


def _gemma4_forward(engine, input_ids, bias: float = 0.0):
    """Gemma 4 forward with optional calibrated routing bias."""
    import mlx.core as mx
    from mlx_lm.models.base import create_attention_mask
    from .calibrate import _gemma4_route
    from .engine_gemma4 import run_expert_ffn_gemma4

    args = engine.model.args
    num_experts = args.num_experts
    first_global = next(
        (i for i, lt in enumerate(args.layer_types) if lt == "full_attention"), 0
    )
    first_sliding = next(
        (i for i, lt in enumerate(args.layer_types) if lt == "sliding_attention"), 0
    )

    h = engine.model.model.embed_tokens(input_ids)
    h = h * mx.array(args.hidden_size ** 0.5, dtype=h.dtype)
    global_mask = create_attention_mask(h, engine.cache[first_global])
    sliding_mask = create_attention_mask(
        h, engine.cache[first_sliding], window_size=args.sliding_window
    )

    for i in range(engine.num_layers):
        layer = engine.model.model.layers[i]
        mask = global_mask if args.layer_types[i] == "full_attention" else sliding_mask

        residual = h
        h = layer.input_layernorm(h)
        h = layer.self_attn(h, mask, engine.cache[i])
        h = layer.post_attention_layernorm(h)
        h = residual + h
        mx.eval(h)

        residual = h
        h = layer.pre_feedforward_layernorm(h)
        dense_out = layer.mlp(h)

        if layer.enable_moe_block:
            h_dense = layer.post_feedforward_layernorm_1(dense_out)
            B, L, D = residual.shape
            residual_flat = residual.reshape(-1, D)
            router_weights, router_indices = _gemma4_route(
                layer,
                residual_flat,
                layer_idx=i,
                reader=engine.reader,
                num_experts=num_experts,
                bias=bias,
            )
            mx.eval(router_weights, router_indices)
            active_ids = list(set(int(e) for e in np.array(router_indices).flatten()))
            engine.coact.record_layer(i, active_ids)
            if engine.coact.ready and i + 1 < engine.num_layers:
                predicted = engine.coact.predict_next_layer(i, active_ids, top_k=6)
                if predicted:
                    to_fetch = [
                        eid
                        for eid in predicted
                        if engine.reader.lru and engine.reader.lru.get(i + 1, eid) is None
                    ]
                    if to_fetch:
                        engine.reader.prefetch_experts(i + 1, to_fetch)
            if i + 1 < engine.num_layers:
                engine.reader.prefetch_experts(i + 1, active_ids)
            expert_data = engine.reader.get_experts(i, active_ids)
            moe_input = layer.pre_feedforward_layernorm_2(residual_flat)
            expert_out = run_expert_ffn_gemma4(
                moe_input.reshape(B, L, D),
                expert_data,
                router_indices.reshape(B, L, -1),
                router_weights.reshape(B, L, -1),
                per_expert_scale=engine.per_expert_scales.get(i),
            )
            h_moe = layer.post_feedforward_layernorm_2(expert_out)
            h = h_dense + h_moe
            h = layer.post_feedforward_layernorm(h)
            del expert_data, expert_out
        else:
            h = layer.post_feedforward_layernorm(dense_out)

        h = residual + h
        h = h * layer.layer_scalar
        mx.eval(h)
        mx.clear_cache()

    engine.coact.end_token()
    h = engine.model.model.norm(h)
    return engine._apply_lm_head(h)


def _generate_stream_gemma4(engine, messages, bias=0.0, max_tokens=200):
    """Generator for Gemma 4 with official chat formatting and routing bias."""
    import mlx.core as mx

    engine.reset_cache()
    tok = engine.tokenizer
    tokens = _gemma4_chat_tokens(tok, messages)
    input_ids = mx.array([tokens])

    logits = _gemma4_forward(engine, input_ids, bias=bias)
    mx.eval(logits)

    eos_ids = _gemma4_generation_stop_ids(tok)

    for _ in range(max_tokens):
        token = mx.argmax(logits[:, -1, :], axis=-1)
        mx.eval(token)
        tid = token.item()
        if tid in eos_ids:
            break
        chunk = _gemma4_decode_token(tok, tid)
        if any(st in chunk for st in STOP_TOKENS):
            break
        if _gemma4_should_yield(chunk):
            yield chunk
        logits = _gemma4_forward(engine, token.reshape(1, 1), bias=bias)
        mx.eval(logits)


def _gemma4_sample_tokens(
    engine,
    messages,
    *,
    bias: float = 0.0,
    max_tokens: int = 24,
) -> list[dict]:
    """Generate a short token trace for diagnostics."""
    import mlx.core as mx

    tok = engine.tokenizer
    tokens = _gemma4_chat_tokens(tok, messages)
    eos_ids = _gemma4_generation_stop_ids(tok)

    engine.reset_cache()
    logits = _gemma4_forward(engine, mx.array([tokens]), bias=bias)
    mx.eval(logits)

    trace: list[dict] = []
    for _ in range(max_tokens):
        tid = int(mx.argmax(logits[:, -1, :], axis=-1).item())
        decoded = _gemma4_decode_token(tok, tid)
        trace.append({
            "id": tid,
            "text": decoded,
            "is_stop": tid in eos_ids,
            "yielded": _gemma4_should_yield(decoded),
        })
        if tid in eos_ids:
            break
        logits = _gemma4_forward(engine, mx.array([[tid]]), bias=bias)
        mx.eval(logits)
    return trace


def probe_gemma4_generation(engine, messages, *, bias: float = 0.0) -> dict:
    """Return prompt/first-token diagnostics for Gemma 4 generation."""
    import mlx.core as mx

    tok = engine.tokenizer
    normalized = _gemma4_normalize_messages(messages)
    tokens = _gemma4_chat_tokens(tok, messages)
    eos_ids = _gemma4_generation_stop_ids(tok)

    engine.reset_cache()
    logits = _gemma4_forward(engine, mx.array([tokens]), bias=bias)
    mx.eval(logits)
    first_tid = int(mx.argmax(logits[:, -1, :], axis=-1).item())
    first_decoded = _gemma4_decode_token(tok, first_tid)

    trace = _gemma4_sample_tokens(engine, messages, bias=bias)
    visible = "".join(entry["text"] for entry in trace if entry["yielded"])

    return {
        "chat_template_set": bool(getattr(tok, "chat_template", None)),
        "prompt_tokens": len(tokens),
        "prompt_tail_ids": tokens[-12:],
        "prompt_tail_text": _gemma4_manual_chat_text(tok, normalized)[-120:],
        "first_token_id": first_tid,
        "first_token_text": first_decoded,
        "first_token_is_stop": first_tid in eos_ids,
        "first_token_yielded": _gemma4_should_yield(first_decoded),
        "stop_ids": sorted(eos_ids),
        "sample_tokens": trace,
        "visible_text": visible,
    }
