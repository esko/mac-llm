"""
Ollama-compatible HTTP server for Expert Sniper.

Implements /api/tags, /api/chat, /api/generate, /api/version.
Compatible with Open WebUI, Continue.dev, and any Ollama client.
"""
from http.server import HTTPServer, BaseHTTPRequestHandler
import json, sys, os, time

STOP_TOKENS = {"<|im_end|>", "<|endoftext|>", "<|im_start|>"}

_engine = None
_bias = 0.0
_model_dir = None
_model_name = "mlx-sniper"
_model_type = "unknown"


def _get_engine():
    global _engine, _bias, _model_name, _model_type
    if _engine is not None:
        return _engine

    print("Loading model...", flush=True)
    from .generate import load_engine
    from .calibrate import _detect_model_type

    _engine, _bias, _model_type = load_engine(_model_dir)
    _model_name = os.path.basename(os.path.normpath(_model_dir)) or _detect_model_type(_model_dir)
    print(f"  Model loaded ({_model_type}).", flush=True)
    return _engine


def _chat_stream(engine, prompt, max_tokens=200):
    """Generator yielding token strings for one user prompt."""
    from .generate import generate_stream

    messages = [{"role": "user", "content": prompt}]
    yield from generate_stream(engine, messages, bias=_bias, max_tokens=max_tokens)


class OllamaHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api/tags":
            self._json_response({
                "models": [{
                    "name": _model_name,
                    "model": _model_name,
                    "size": 0,
                    "details": {"family": _model_type, "parameter_size": "MoE",
                                "quantization_level": "sniper"},
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
            prompt = body["messages"][-1]["content"]
        else:
            prompt = body.get("prompt", "hello")

        stream = body.get("stream", True)
        max_tokens = body.get("options", {}).get("num_predict", 200)

        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.end_headers()

        engine = _get_engine()
        t0 = time.time()
        total_tokens = 0
        full_response = ""

        for token_text in _chat_stream(engine, prompt, max_tokens=max_tokens):
            total_tokens += 1
            full_response += token_text
            if stream:
                self._ndjson({"model": _model_name,
                              "message": {"role": "assistant", "content": token_text},
                              "done": False})

        elapsed = time.time() - t0
        done = {
            "model": _model_name,
            "message": {"role": "assistant", "content": "" if stream else full_response},
            "done": True,
            "total_duration": int(elapsed * 1e9),
            "eval_count": total_tokens,
            "eval_duration": int(elapsed * 1e9),
        }
        self._ndjson(done)
        tps = total_tokens / elapsed if elapsed > 0 else 0
        print(f"  [{total_tokens} tok, {tps:.1f} tok/s, {elapsed:.1f}s] {prompt[:40]}")

    def _json_response(self, data):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def _ndjson(self, data):
        self.wfile.write((json.dumps(data) + "\n").encode())
        self.wfile.flush()

    def log_message(self, format, *args):
        pass


def run_server(model_dir, host="127.0.0.1", port=11434):
    global _model_dir
    _model_dir = model_dir

    print(f"mlx-sniper serve")
    print(f"  Model:  {model_dir}")
    print(f"  Listen: http://{host}:{port}")
    print(f"  API:    Ollama-compatible (/api/tags, /api/chat, /api/generate)")
    print()

    _get_engine()  # Pre-load

    print(f"\nReady. Listening on http://{host}:{port}")
    print(f"  Test: curl http://localhost:{port}/api/tags")
    print(f"  Chat: curl http://localhost:{port}/api/chat -d '{{\"model\":\"qwen3.5-35b\",\"messages\":[{{\"role\":\"user\",\"content\":\"hello\"}}]}}'")
    print()

    import socket
    HTTPServer.allow_reuse_address = True
    server = HTTPServer((host, port), OllamaHandler)
    server.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
        server.shutdown()
