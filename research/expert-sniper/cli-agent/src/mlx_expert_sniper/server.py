"""
Ollama-compatible HTTP server for Expert Sniper.

Implements /api/tags, /api/chat, /api/generate, /api/version.
Compatible with Open WebUI, Continue.dev, and any Ollama client.
"""
from http.server import HTTPServer, BaseHTTPRequestHandler
import json, os, sys, threading, time

STOP_TOKENS = {"<|im_end|>", "<|endoftext|>", "<|im_start|>"}

_engine = None
_bias = 0.0
_model_dir = None
_model_name = "mlx-sniper"
_model_type = "unknown"
_load_lock = threading.Lock()
_load_error: str | None = None


def _init_model_metadata() -> None:
    """Set display metadata without loading weights."""
    global _model_name, _model_type
    from .calibrate import _detect_model_type

    _model_type = _detect_model_type(_model_dir)
    _model_name = os.path.basename(os.path.normpath(_model_dir)) or _model_type


def _get_engine():
    global _engine, _bias, _model_name, _model_type, _load_error
    if _engine is not None:
        return _engine
    if _load_error is not None:
        raise RuntimeError(_load_error)

    with _load_lock:
        if _engine is not None:
            return _engine
        if _load_error is not None:
            raise RuntimeError(_load_error)

        print("Loading model...", flush=True)
        from .generate import load_engine

        try:
            _engine, _bias, loaded_type = load_engine(_model_dir)
            _model_type = loaded_type
            _model_name = os.path.basename(os.path.normpath(_model_dir)) or loaded_type
        except Exception as exc:
            _load_error = str(exc)
            print(f"  Model load failed: {_load_error}", flush=True, file=sys.stderr)
            raise RuntimeError(_load_error) from exc

        print(f"  Model loaded ({_model_type}).", flush=True)
        return _engine


def _chat_stream(engine, messages, max_tokens=200):
    """Generator yielding token strings for a chat message list."""
    from .generate import generate_stream

    yield from generate_stream(engine, messages, bias=_bias, max_tokens=max_tokens)


class OllamaHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api/tags":
            status = "ready" if _engine is not None else "loading"
            if _load_error is not None:
                status = "error"
            self._json_response({
                "models": [{
                    "name": _model_name,
                    "model": _model_name,
                    "size": 0,
                    "details": {
                        "family": _model_type,
                        "parameter_size": "MoE",
                        "quantization_level": "sniper",
                        "status": status,
                        "load_error": _load_error,
                    },
                }]
            })
        elif self.path in ("/api/version", "/"):
            self._json_response({"version": "0.2.0-sniper"})
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path not in ("/api/chat", "/api/generate"):
            self.send_response(404)
            self.end_headers()
            return

        content_len = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(content_len))

        if "messages" in body:
            messages = body["messages"]
            prompt_preview = messages[-1].get("content", "")
        else:
            prompt_preview = body.get("prompt", "hello")
            messages = [{"role": "user", "content": prompt_preview}]

        stream = body.get("stream", True)
        max_tokens = body.get("options", {}).get("num_predict", 200)

        try:
            engine = _get_engine()
        except RuntimeError as exc:
            self._json_response({"error": str(exc)}, status=503)
            return

        if stream:
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.end_headers()

        t0 = time.time()
        total_tokens = 0
        full_response = ""

        for token_text in _chat_stream(engine, messages, max_tokens=max_tokens):
            total_tokens += 1
            full_response += token_text
            if stream:
                self._ndjson({
                    "model": _model_name,
                    "message": {"role": "assistant", "content": token_text},
                    "done": False,
                })

        elapsed = time.time() - t0
        done = {
            "model": _model_name,
            "message": {
                "role": "assistant",
                "content": "" if stream else full_response,
            },
            "done": True,
            "total_duration": int(elapsed * 1e9),
            "eval_count": total_tokens,
            "eval_duration": int(elapsed * 1e9),
        }

        if stream:
            self._ndjson(done)
        else:
            self._json_response(done)

        tps = total_tokens / elapsed if elapsed > 0 else 0
        print(f"  [{total_tokens} tok, {tps:.1f} tok/s, {elapsed:.1f}s] {prompt_preview[:40]}")

    def _json_response(self, data, *, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def _ndjson(self, data):
        self.wfile.write((json.dumps(data) + "\n").encode())
        self.wfile.flush()

    def log_message(self, format, *args):
        pass


def _preload_engine() -> None:
    """Warm model weights in the background so /api/tags can respond immediately."""
    try:
        _get_engine()
        print("  Model ready for chat.", flush=True)
    except RuntimeError as exc:
        print(f"  Model preload failed: {exc}", flush=True, file=sys.stderr)


def run_server(model_dir, host="127.0.0.1", port=11434):
    global _model_dir
    _model_dir = model_dir
    _init_model_metadata()

    print("mlx-sniper serve")
    print(f"  Model:  {model_dir}")
    print(f"  Listen: http://{host}:{port}")
    print("  API:    Ollama-compatible (/api/tags, /api/chat, /api/generate)")
    print()

    import socket

    HTTPServer.allow_reuse_address = True
    server = HTTPServer((host, port), OllamaHandler)
    server.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    print(f"Listening on http://{host}:{port}")
    print("  Loading model in background (curl /api/tags works immediately)...")
    print(f"  Test: curl http://localhost:{port}/api/tags")
    print(
        f"  Chat: curl http://localhost:{port}/api/chat -d "
        f"'{{\"model\":\"{_model_name}\",\"messages\":[{{\"role\":\"user\",\"content\":\"hello\"}}]}}'"
    )
    print()

    threading.Thread(target=_preload_engine, daemon=True).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.shutdown()
