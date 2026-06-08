# Imported runtime, cache, and benchmark map

Milestone 0 orientation — runtime/backend half.

This document maps the inference, cache, and measurement surfaces of the
prototype code imported from `mac-code` (provenance: `docs/upstream/mac-code.md`).
It is the runtime/backend companion to the safety/boundary slice and is
deliberately scoped to *what exists*, not to Milestone 1 design.

Scope and method:

- Static inspection only (`rg`, `git grep`, `sed`, file reads). No imported
  module, model, server, or network/shell path was executed.
- Every material claim cites a concrete source path plus a symbol or line.
- All imported code is prototype/research material, not the `mac-llm`
  production runtime (`docs/upstream/mac-code.md`, "Prototype boundary").

There are three independent runtime families in the import, each talking to a
different backend:

1. Top-level llama.cpp HTTP clients — `agent.py`, `chat.py`.
2. MLX engine/server + KV-cache experiments — `mlx/`.
3. Expert-streaming MoE runtime — `research/expert-sniper/` (packaged
   `cli-agent/` and standalone `mlx-sniper/`).

---

## 1. Top-level llama.cpp clients (`agent.py`, `chat.py`)

Both top-level scripts are **HTTP clients**, not servers. They assume an
external OpenAI-compatible server (`llama-server`) is already running and
reachable at `SERVER = os.environ.get("LLAMA_URL", "http://localhost:8000")`
(`agent.py:21`, `chat.py:24`). Neither file loads a model itself; they only
issue `urllib.request` calls.

### 1.1 Request / streaming behavior

- Streaming uses `POST {SERVER}/v1/chat/completions` with `"stream": True`,
  parsing Server-Sent-Event `data: ` lines and `[DONE]` terminator:
  `chat.py` `stream()` (`chat.py:57`) and `agent.py` `stream_llm()`
  (`agent.py:525`). Tokens are counted by counting `delta.content` chunks,
  not by real tokenizer output (`chat.py:99-101`, `agent.py:563-566`).
- Non-streaming fallback uses the same endpoint without `stream`:
  `chat.py` `ask()` (`chat.py:110`) and `agent.py` `llm_call()`
  (`agent.py:277`). These read server-reported `timings` (e.g.
  `predicted_per_second`, `predicted_ms`) and `usage.completion_tokens`
  (`chat.py:127-129`, `agent.py:291`).
- Model identification polls `GET {SERVER}/props` and string-matches the
  `model_alias`/`model_path` for `"35B-A3B"` or `"9B"`: `chat.py` `detect()`
  (`chat.py:36`), `agent.py` `detect_model()` (`agent.py:510`),
  `get_current_model()` (`agent.py:382`).

`chat.py` is the simpler of the two: a Rich TUI chat loop (`chat.py` `main()`,
`chat.py:176`) with slash commands (`/clear`, `/stats`, `/system`, `/model`)
and no tools.

### 1.2 Tool / agent coupling (`agent.py`)

`agent.py` adds an LLM-as-router agent layer on top of the same llama.cpp
HTTP endpoint. The control flow in agent mode (`agent.py` `main()`,
`agent.py:751`, dispatch at `agent.py:1148`):

1. `classify_intent()` (`agent.py:105`) makes one low-token classification
   call returning `search` / `shell` / `chat`.
2. Routing on intent (`agent.py:1172` onward):
   - `shell` → `run_smart_tool()` (`agent.py:143`): an LLM call
     (`generate_shell_command()`, `agent.py:123`) produces a shell string
     that is executed with `subprocess.run(cmd, shell=True, ...)`
     (`agent.py:153`), then summarized by another LLM call. There is also a
     direct-Python file tool path `run_file_tool()` (`agent.py:172`) covering
     list/read/write/exec, which likewise runs `subprocess.run(..., shell=True)`
     (`agent.py:254`). These are real, unsandboxed side effects (flagged here
     only as runtime behavior; the safety inventory is out of scope).
   - `search` → `quick_search()` (`agent.py:293`): LLM rewrites the query,
     calls DuckDuckGo (`ddgs`/`duckduckgo_search`, `agent.py:296-300`),
     optionally fetches a page via the Jina reader `https://r.jina.ai/...`
     (`agent.py:357`), then an LLM call answers from the snippets.
   - `chat` → direct streaming via `stream_llm()` (`agent.py:1302`).
- Model swapping: `swap_model()` (`agent.py:397`) calls
  `pkill -f llama-server` then `subprocess.Popen(["llama-server", ...])`
  with per-model flags from the `MODELS` dict (`agent.py:69`), polling
  `GET /health` until ready. So `agent.py` both *uses* and *manages* the
  llama.cpp server process.
- An alternate agent backend exists: `picoclaw_call_live()` (`agent.py:573`)
  shells out to an external `picoclaw` binary
  (`PICOCLAW = ~/Desktop/qwen/picoclaw/build/picoclaw-darwin-arm64`,
  `agent.py:65`) and streams its stdout into the `WorkingDisplay` animation
  (`agent.py:439`). This path drives `/btw`, `/search`, and `/loop`
  (`agent.py:996`, `agent.py:1067`, `agent.py:1123`).
- Built-in micro-benchmark: the `/bench` slash command (`agent.py:897`) issues
  a fixed "count to 50" prompt and reports server `predicted_per_second` and
  `prompt_per_second`. Interaction logging writes JSONL to
  `~/.mac-code/logs` via `log_interaction()` (`agent.py:27`), summarized by
  `get_failure_stats()` (`agent.py:43`) behind `/improve`.

Key interface fact: everything in `agent.py`/`chat.py` is wire-compatible with
the OpenAI chat-completions shape, which is exactly what the MLX server
(section 2) and—via a different API—the sniper server (section 3) emulate.

---

## 2. MLX engine and KV-cache experiments (`mlx/`)

`mlx/PROJECT.md` is the upstream self-description and labels everything except
`mlx_engine.py` and `kv_cache.py` as "not production-ready". This section
verifies that against the source.

### 2.1 MLX engine/server (`mlx/mlx_engine.py`)

`mlx/mlx_engine.py` is a **native MLX HTTP server** positioned as a "drop-in
replacement for llama.cpp" (`mlx/mlx_engine.py:3-4`). It is distinct from the
llama.cpp path in section 1: it loads the model in-process via `mlx_lm`
(`load_model()`, `mlx/mlx_engine.py:35`, using `from mlx_lm import load`) and
generates with `mlx_lm.generate` (`generate()`, `mlx/mlx_engine.py:55-66`).
Model registry maps `9b`/`35b` to `mlx-community/...` repos
(`mlx/mlx_engine.py:24`).

Server surface (`APIHandler`, `mlx/mlx_engine.py:167`):

- `POST /v1/chat/completions` (`_handle_chat`, `mlx/mlx_engine.py:246`) returns
  the same `choices/usage/timings` shape the section-1 clients expect
  (`mlx/mlx_engine.py:257-272`), so `agent.py`/`chat.py` can point at it
  unchanged. Prompt formatting is a hand-built Qwen chat template that injects
  an empty `<think>` block to skip reasoning (`format_chat()`,
  `mlx/mlx_engine.py:92-107`).
- `GET /health` and `GET /props` (`mlx/mlx_engine.py:189-195`) mimic
  llama.cpp's discovery endpoints used by `detect_model()`.
- KV-cache HTTP endpoints `/v1/context/{save,load,upload,download,list}`
  (`mlx/mlx_engine.py:175-197`).

Important limitation — **KV persistence is not wired into generation**:

- `generate()` calls `mlx_generate(model, tokenizer, prompt=..., max_tokens=...)`
  (`mlx/mlx_engine.py:63-66`) with **no `cache` argument**. Generation always
  reprocesses the full prompt.
- `save_context()` / `load_context()` (`mlx/mlx_engine.py:110`, `:145`) operate
  on a freshly created `make_prompt_cache(model)` (`mlx/mlx_engine.py:121`),
  not the live conversation cache, and `load_context()` returns the cache to
  the handler but never attaches it to the model for the next `generate()`.
- The CLI `--load-context` path is broken: `main()` calls the undefined symbol
  `set_kv_cache(tensors)` (`mlx/mlx_engine.py:314`). `git grep set_kv_cache`
  finds only this call site and no definition anywhere in `mlx/`. The file
  also imports `from kv_cache import load_kv_cache` (`mlx/mlx_engine.py:311`)
  with a bare module name that assumes execution from inside `mlx/`.

So the "persistent context enabled" banner (`mlx/mlx_engine.py:321`) overstates
the working state: save/load helpers exist and are individually exercised by
the benchmarks (section 4), but no serving path resumes from a saved cache.

### 2.2 Disk KV-cache helpers (`mlx/kv_cache.py`)

`mlx/kv_cache.py` is a free-standing save/load/compress utility over MLX (or
NumPy fallback) tensors, writing to `~/.mac-code/kv-cache/<name>/`:
`save_kv_cache()` (`mlx/kv_cache.py:18`), `load_kv_cache()` (`mlx/kv_cache.py:71`),
`compress_kv_cache()`/`decompress_kv_cache()` gzip helpers
(`mlx/kv_cache.py:97`, `:121`), plus `list_cached_contexts()`/`delete_*`
(`mlx/kv_cache.py:136`, `:153`). It is referenced only by the broken
`--load-context` path above (`git grep load_kv_cache`); nothing consumes the
tensors it returns during generation.

### 2.3 Cache experiments (not wired into generation)

These match `mlx/PROJECT.md`'s "Experiments (not production-ready)" list and
are **not imported by any serving path**. Cross-reference:
`git grep` for `PagedInference`, `TieredKVCache`, and `turboquant` finds
references only in the experiments themselves, the benchmarks (`mlx/benchmark.py`,
`mlx/agent_benchmark.py`), and `mlx/PROJECT.md` — never in `mlx/mlx_engine.py`,
`agent.py`, or `chat.py`.

- `mlx/turboquant.py` — KV-cache compression (PolarQuant + group quantization
  at 2/3/4-bit). Entry symbols `compress_kv_cache()` (`mlx/turboquant.py:118`),
  `decompress_kv_cache()` (`:163`), `measure_quality()` (`:175`, cosine
  similarity), `serialize_compressed()`/`load_compressed()` (`:208`, `:248`).
  `mlx/PROJECT.md:14` states it is "Not benchmarked against baseline quality".
  Used only by the section-4 benchmarks.
- `mlx/paged_inference.py` — checkpoint/resume paging of KV chunks to SSD via
  `class PagedInference` (`mlx/paged_inference.py:47`),
  `process_long_context()` (`:81`), `generate()` (`:148`). Its own docstring
  is explicit: "This is a checkpoint/resume system, not true virtual-memory
  paging" (`mlx/paged_inference.py:18-20`). Imported once, in
  `mlx/agent_benchmark.py:139`, but **not actually exercised** there (the
  benchmark uses `make_prompt_cache` directly, `mlx/agent_benchmark.py:153`).
- `mlx/tiered_cache.py` — GPU→SSD→R2 block tiering via `class TieredKVCache`
  (`mlx/tiered_cache.py:50`) with eviction/prefetch helpers
  (`_evict_to_ssd`/`_evict_to_r2`/`_load_from_ssd`, `:134`, `:203`, `:174`).
  Header claims "256K+ context on 16GB RAM" (`mlx/tiered_cache.py:19-22`).
  No other file imports `TieredKVCache` — it is entirely standalone and
  untested by the benchmarks.
- `mlx/r2_store.py` — Cloudflare R2 upload/download for persistent caches:
  `get_r2_client()` (`mlx/r2_store.py:40`), `is_configured()` (`:65`),
  `upload_context`/`download_context` (`:109`, `:161`), `share_context()`
  presigned URLs (`:260`). Requires R2 credentials; `mlx/PROJECT.md:17` marks
  it "Not tested in production". Guarded everywhere by `is_configured()` so
  unconfigured runs skip the cloud path.

Net: the only cache code on a real generation path is the (non-functional)
hook in `mlx_engine.py`; every other cache module is exercised only through
benchmarks or not at all.

---

## 3. Expert-sniper MoE runtime (`research/expert-sniper/`)

This subtree implements "expert sniping" — running an MoE model larger than RAM
by pinning attention/router/shared weights and streaming only the active
experts from SSD per token. It exists in two forms.

### 3.1 `cli-agent/` vs `mlx-sniper/` — the distinction

- `research/expert-sniper/cli-agent/` is the **packaged, installable** version:
  a `pyproject.toml` (`research/expert-sniper/cli-agent/pyproject.toml`) defines
  the distribution `mlx-expert-sniper` with console entry point
  `mlx-sniper = "mlx_expert_sniper.cli:main"`
  (`research/expert-sniper/cli-agent/pyproject.toml:19-20`). All logic lives
  under `src/mlx_expert_sniper/` as an importable package with relative imports
  (e.g. `from .expert_io import MoEExpertReader`,
  `research/expert-sniper/cli-agent/src/mlx_expert_sniper/engine.py:8`).
- `research/expert-sniper/mlx-sniper/` is the **standalone research scripts**
  the package was distilled from. Its `README.md` says so directly: "The files
  in this directory are the core research implementations. The production CLI
  wraps these into the `mlx-sniper` command."
  (`research/expert-sniper/mlx-sniper/README.md:110`). These are flat scripts
  (`moe_agent_35b.py`, `flash_moe.py`, etc.) with `sys.path.insert`-style
  imports, multiple per-model variants, and one-off benchmarks/splitters.

The two share concepts and even docstrings (e.g. the `expert_io.py` header is
near-identical in both), but `cli-agent/` is the consolidated, dispatchable
runtime while `mlx-sniper/` is the per-model experiment pile.

### 3.2 cli-agent control flow (engine / server / generation)

CLI entry `main()` (`research/expert-sniper/cli-agent/src/mlx_expert_sniper/cli.py:173`)
registers subcommands `download`, `serve`, `calibrate`, `run`, `chat`
(`.../cli.py:181-209`).

- **Engine selection** is centralized in `load_engine()`
  (`.../generate.py:8`): it reads calibration, detects model type via
  `_detect_model_type`, and dispatches to one of four engine classes —
  `engine.py:MoESniperEngine35B` (qwen3_5), `engine_30b.py:MoESniperEngine30B`,
  `engine_gemma4.py:MoESniperEngineGemma4`, `engine_next.py:MoESniperEngineNext`
  (`.../generate.py:23-38`). Files: `.../engine.py`, `.../engine_30b.py`,
  `.../engine_gemma4.py`, `.../engine_next.py`.
- **Engine internals** (`.../engine.py`, `MoESniperEngine35B`, `:45`):
  `load()` (`.../engine.py:56`) builds the `mlx_lm` Qwen3.5 `TextModel`,
  quantizes 4-bit/group-64 with a `should_quantize` predicate
  (`.../engine.py:90-97`), loads only `pinned.safetensors` into RAM
  (`.../engine.py:102-104`), and constructs the SSD reader
  `MoEExpertReader(expert_dir, ...)` (`.../engine.py:111`) plus a
  `CoActivationTracker` (`.../engine.py:112`). The per-layer `forward()`
  (`.../engine.py:121`) computes router gates, selects top-k experts,
  prefetches next-layer experts, reads active experts, and runs
  `run_expert_ffn()` (`.../engine.py:15`) via fused `mx.gather_qmm`.
- **Generation** is shared by `run`/`chat`/`serve` through `generate_stream()`
  (`.../generate.py:45`): it applies the chat template, runs an inlined copy of
  the layer loop (`forward`, `.../generate.py:72`) with optional cache-bias
  routing (`.../generate.py:98-103`) and co-activation prefetch
  (`.../generate.py:115-123`), then greedily decodes (`mx.argmax`) until an EOS
  id or stop token (`.../generate.py:150-161`). A separate Gemma-4 path
  `_generate_stream_gemma4()` (`.../generate.py:164`) delegates to the engine's
  own `forward`.
- **Server** (`.../server.py`, `run_server()`, `:214`) is an **Ollama-compatible**
  HTTP server (`/api/tags`, `/api/chat`, `/api/generate`, `/api/version`,
  `.../server.py:1-6`, `OllamaHandler`, `:135`) — note this is a *different*
  API shape from the OpenAI `/v1/chat/completions` used in sections 1–2. It
  lazily builds a single global 35B engine (`_get_engine()`, `.../server.py:18`)
  and streams ND-JSON via its own inlined `_generate_stream()`
  (`.../server.py:45`). The 256-expert count and EOS ids `{248044, 248045}` are
  hard-coded here (`.../server.py:79`, `:124`), i.e. the server is effectively
  35B-specific even though `load_engine` is generic.

### 3.3 SSD expert streaming and prediction

- `MoEExpertReader` (`.../expert_io.py`) is the I/O core: read only active
  experts from SSD with `F_NOCACHE` + `pread`, 8 worker threads, an LRU expert
  cache, and a mixed-precision `DownProjFallback` (ternary/1-bit `mmap` buffer)
  to serve cache misses while SSD backfills
  (`.../expert_io.py:1-13`, `DownProjFallback`, `:28`). Per-expert/per-token
  byte math is documented in the header (`.../expert_io.py:4-8`).
- `CoActivationTracker` (`.../coactivation.py`, `:5`) records which experts
  fire together across adjacent layers (`record_layer`, `:20`) and predicts the
  next layer's experts (`predict_next_layer`, `:35`) to drive prefetch. It is
  shared by engine and generation paths.
- `calibrate()` (`.../calibrate.py`) is a one-time pass that, per its header,
  writes `sniper_config.json` (cache size, routing bias) and
  `sniper_calibration.npz` (REAP scores, dead-expert mask, co-activation matrix)
  (`.../calibrate.py:3-8`); `auto_size_cache()` (`.../calibrate.py:29`) sizes
  the LRU from `hw.memsize`. `download.py` and `preprocess.py` cover model
  fetch/conversion (`.../download.py`, `.../preprocess.py`).

### 3.4 mlx-sniper standalone variants

The standalone scripts under `research/expert-sniper/mlx-sniper/` are the
per-model / per-experiment ancestors of the package:

- Per-model agents: `moe_agent_35b.py`, `moe_agent_30b.py`,
  `moe_agent_gemma4.py` (Qwen3.5-35B / Qwen3-30B / Gemma-4 variants of the same
  engine), and `moe_agent_macbook.py` — an 8 GB MacBook variant that, per its
  own docstring, is "Modeled after agent.py: intent classification → tool
  routing → LLM response" (`research/expert-sniper/mlx-sniper/moe_agent_macbook.py:4`),
  with its own `classify_intent`/`quick_search`/`run_shell`
  (`.../moe_agent_macbook.py:286`, `:294`, `:328`) and `main()` loop (`:393`).
  This is the bridge between the section-1 agent UX and the sniper backend.
- Streaming-engine experiments: `flash_moe.py` ("Flash MoE", `:1-6`),
  `batched_moe.py` (union-of-experts batched decode, `:1-6`), `expert_io.py`,
  and `direct_io.py` (16 KB-aligned direct reads bypassing the UBC, `:1-6`).
- Model splitters/preprocessors: `split_35b_v2.py`, `split_30b.py`,
  `split_mlx_model_macbook.py` — split a converted MLX model into
  `pinned` + per-expert streaming files.
- Calibration/coactivation duplicates: `calibrate.py`, `coactivation.py`.

`README.md` documents the intended CLI (`preprocess`/`chat`/`server`/`profile`,
`research/expert-sniper/mlx-sniper/README.md:13-25`) and reports headline
numbers (e.g. 5.37 tok/s on Qwen3.5-35B-A3B, 92% cache hit, 2.9 s TTFT, 8.7 GB
RAM on an M4 16 GB; `README.md:33-37`). These are upstream-reported results, not
reproduced here.

---

## 4. Benchmark entry points and collected metrics

### 4.1 MLX-vs-llama.cpp backend benchmarks (`mlx/`)

- `mlx/benchmark.py` — "Triple benchmark: llama.cpp vs MLX vs MLX+TurboQuant+R2"
  (`mlx/benchmark.py:2-4`). It is a top-level script (runs on import). It starts
  each backend itself: `start_llama_9b()` (`mlx/benchmark.py:55`,
  `Popen(["llama-server", ...])`) and `start_mlx_9b()` (`:69`,
  `Popen([sys.executable, "mlx_engine.py", ...])`), waiting on `/health`
  (`wait_for_server()`, `:44`). `llm_call()` (`:12`) records per-test:
  token count, wall `elapsed`, server `predicted_per_second`, and a
  wall-clock `wall_speed` (`mlx/benchmark.py:36-42`). A fixed `TESTS` list
  (`:79`) covers math/reasoning/short-gen/long-gen/classification. The third
  phase measures cache persistence: prefill time, TurboQuant
  compress+save time and compression ratio, uncompressed save size, optional
  R2 upload/download times, and disk/TurboQuant load times, then prints "Nx
  faster" resume ratios (`mlx/benchmark.py:159-226`). Final summary picks a
  per-test winner and speed delta (`:234-244`). Note this phase imports
  `turboquant`/`r2_store` with bare names (`:145-146`), assuming execution from
  inside `mlx/`.
- `mlx/agent_benchmark.py` — "Agent benchmark: mac-code (llama.cpp) vs
  mac-code-mlx" (`mlx/agent_benchmark.py:2-4`). Imports the real agent
  functions `classify_intent, quick_search, run_smart_tool, llm_call` from
  `agent.py` (`mlx/agent_benchmark.py:47-48`, via a hard-coded
  `~/Desktop/pico-mini` `sys.path` insert) and times agent tasks end to end.
  Per `AGENT_TESTS` (`:50`) it records `elapsed` per task plus classification
  result or tok/s for search/shell/chat (`:87-128`). A context-persistence
  phase reports prefill vs SSD-load vs R2-resume timings and TurboQuant size
  (`:152-209`); the final table sums per-backend task time and picks a winner
  (`:217-236`). It imports `PagedInference` (`:139`) but does not invoke it.

Both `mlx/` benchmarks are wall-clock + server-`timings` harnesses; neither
writes a persisted artifact file — results are printed to stdout only.

### 4.2 Expert-streaming micro-benchmarks (`mlx-sniper/`)

These target the SSD/fallback I/O path rather than end-to-end chat:

- `research/expert-sniper/mlx-sniper/bench_quick.py` — "SSD pread vs 1-bit mmap
  fallback" over 5 tokens × N layers × 8 experts (`:1-6`). Prints per-run
  tok/s, TTFT (ms), per-token ms, and reader counters
  `reads`/`cache_hits`/LRU/fallback stats (`bench_quick.py:118-131`).
- `research/expert-sniper/mlx-sniper/bench_mixed.py` — mixed-precision fallback
  comparison (3 SSD preads/miss vs 2 preads + 1-bit down), reporting Config A
  vs B tok/s and speedup ratio (`bench_mixed.py:1-6`, `:189-191`).
- `research/expert-sniper/mlx-sniper/benchmark_fallback.py` — exercises "the
  exact code paths in expert_io.py and flash_moe.py" for cache-miss serving
  (`benchmark_fallback.py:1-6`).

### 4.3 In-app benchmark hooks

- `agent.py` `/bench` (`agent.py:897`) — a fixed-prompt latency probe reporting
  generation and prompt `tok/s` from server `timings`.
- cli-agent `run --verbose` (`.../cli.py:60`, `:95-99`) — prints token count,
  tok/s, TTFT, total time, reader cache stats, and Metal memory.
- cli-agent server done-frame (`.../server.py:188-198`) — emits Ollama-style
  `total_duration`, `eval_count`, `eval_duration`, and logs tok/s per request.

---

## 5. Cross-cutting limitations (source-verified)

- **Three incompatible API surfaces.** OpenAI `/v1/chat/completions`
  (`agent.py`, `chat.py`, `mlx/mlx_engine.py`) vs Ollama `/api/*`
  (`research/expert-sniper/cli-agent/src/mlx_expert_sniper/server.py`). Clients
  and servers are not interchangeable across families without an adapter.
- **KV persistence is aspirational, not wired.** No generation path in `mlx/`
  consumes a saved cache; the server `--load-context` path calls an undefined
  `set_kv_cache` (`mlx/mlx_engine.py:314`) and `generate()` passes no cache
  (`mlx/mlx_engine.py:63-66`).
- **Cache experiments are largely unreferenced.** `TieredKVCache` is imported by
  nothing; `PagedInference` is imported but unused; TurboQuant/R2 run only
  inside benchmarks and behind `is_configured()` guards.
- **Hard-coded local assumptions.** Bare-name imports that assume a CWD
  (`mlx/mlx_engine.py:311`, `mlx/benchmark.py:145-146`), absolute home paths
  (`agent.py:65`, `mlx/agent_benchmark.py:47`), and an absolute upstream
  `MODEL_DIR` default (`.../engine.py:11`).
- **Server is model-specific despite a generic loader.** cli-agent `serve`
  hard-codes 256 experts and Qwen 35B EOS ids
  (`.../server.py:79`, `:124`), so the Ollama server effectively serves 35B
  only even though `load_engine` (`.../generate.py:8`) dispatches four engines.
- **Reported performance numbers are upstream-provided.** All tok/s, cache-hit,
  TTFT, and RAM figures (`research/expert-sniper/mlx-sniper/README.md:27-62`)
  come from the import; nothing here was executed to confirm them.

---

## Source index

Top-level llama.cpp clients: `agent.py`, `chat.py`.
MLX engine + cache: `mlx/mlx_engine.py`, `mlx/kv_cache.py`, `mlx/turboquant.py`,
`mlx/paged_inference.py`, `mlx/tiered_cache.py`, `mlx/r2_store.py`,
`mlx/PROJECT.md`.
MLX benchmarks: `mlx/benchmark.py`, `mlx/agent_benchmark.py`.
Sniper package: `research/expert-sniper/cli-agent/pyproject.toml`,
`research/expert-sniper/cli-agent/src/mlx_expert_sniper/cli.py`,
`.../generate.py`, `.../engine.py`, `.../engine_30b.py`, `.../engine_gemma4.py`,
`.../engine_next.py`, `.../server.py`, `.../expert_io.py`, `.../coactivation.py`,
`.../calibrate.py`, `.../download.py`, `.../preprocess.py`.
Sniper standalone: `research/expert-sniper/mlx-sniper/README.md`,
`.../moe_agent_35b.py`, `.../moe_agent_30b.py`, `.../moe_agent_gemma4.py`,
`.../moe_agent_macbook.py`, `.../flash_moe.py`, `.../batched_moe.py`,
`.../expert_io.py`, `.../direct_io.py`, `.../bench_quick.py`,
`.../bench_mixed.py`, `.../benchmark_fallback.py`, `.../calibrate.py`,
`.../split_35b_v2.py`, `.../split_30b.py`, `.../split_mlx_model_macbook.py`.
Provenance: `docs/upstream/mac-code.md`.
