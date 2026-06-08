"""Tests for local_deep_moe OpenAI-compatible smoke request + benchmark fields."""

from __future__ import annotations

import json
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from typing import Any

import pytest

from mac_llm.bench.metrics import SystemMetricProbes
from mac_llm.runtime.probes import OrphanCheckResult
from mac_llm.runtime.smoke import run_smoke
from mac_llm.runtime.target import get_target
from tests.test_metrics import FakeMetricSource


@dataclass
class FakeServerState:
    completion_status: int = 200
    completion_body: dict[str, Any] | None = None
    health_status: int = 200
    health_body: dict[str, Any] | None = None
    requests: list[tuple[str, str]] | None = None

    def __post_init__(self) -> None:
        if self.completion_body is None:
            self.completion_body = {
                "choices": [{"message": {"content": "pong"}}],
                "usage": {"completion_tokens": 4},
                "timings": {
                    "load_time": 1.25,
                    "prompt_ms": 120,
                    "predicted_per_second": 18.5,
                },
            }
        if self.health_body is None:
            self.health_body = {"models": []}
        if self.requests is None:
            self.requests = []


class _FakeOpenAIServer(BaseHTTPRequestHandler):
    state: FakeServerState

    def log_message(self, format: str, *args: object) -> None:
        return

    def _read_body(self) -> str:
        length = int(self.headers.get("Content-Length", "0"))
        return self.rfile.read(length).decode("utf-8") if length else ""

    def do_GET(self) -> None:
        self.state.requests.append(("GET", self.path))
        if self.path == "/api/tags":
            body = json.dumps(self.state.health_body).encode("utf-8")
            self.send_response(self.state.health_status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self) -> None:
        payload = self._read_body()
        self.state.requests.append(("POST", self.path))
        if self.path != "/v1/chat/completions":
            self.send_response(404)
            self.end_headers()
            return

        request = json.loads(payload)
        assert request["messages"][0]["content"] == "ping"
        body = json.dumps(self.state.completion_body).encode("utf-8")
        self.send_response(self.state.completion_status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def fake_openai_server() -> tuple[str, FakeServerState, ThreadingHTTPServer]:
    state = FakeServerState()
    _FakeOpenAIServer.state = state
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeOpenAIServer)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    yield f"http://{host}:{port}", state, server
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


def test_smoke_records_runtime_typed_benchmark_fields(
    tmp_path: Path,
    fake_openai_server: tuple[str, FakeServerState, ThreadingHTTPServer],
) -> None:
    base_url, state, _server = fake_openai_server
    target = get_target("local_deep_moe")
    target = target.__class__(
        **{
            **target.__dict__,
            "health_url": f"{base_url}/api/tags",
            "port": int(base_url.rsplit(":", 1)[-1]),
        }
    )
    metric_source = FakeMetricSource(
        memory_pressure={"level": "normal", "score": 3.0},
        swap_used_bytes=5_000,
        orphan_processes=[],
    )
    probes = SystemMetricProbes(metric_source, swap_baseline_bytes=4_000)

    result = run_smoke(
        target,
        artifact_root=tmp_path,
        base_url=base_url,
        metric_probes=probes,
        orphan_check_fn=lambda: OrphanCheckResult(
            has_orphan=False,
            port_occupied=False,
            occupying_pid=None,
            stale_state_pid=None,
            message="no orphan detected",
        ),
        timestamp="20260609T120000Z",
    )

    assert result.record.status == "ok"
    assert result.record.target_id == "local_deep_moe"
    assert result.record.runtime_type == "mlx_sniper"
    assert result.record.load_time_s == 1.25
    assert result.record.ttft_s == 0.12
    assert result.record.tokens_per_second == 18.5
    assert result.record.memory == {
        "status": "ok",
        "level": "normal",
        "score": 3.0,
    }
    assert result.record.orphan_status == {
        "status": "ok",
        "orphaned": False,
        "count": 0,
        "processes": [],
    }

    jsonl_path = result.artifact_dir / "run.jsonl"
    events = [json.loads(line) for line in jsonl_path.read_text().splitlines()]
    smoke_events = [event for event in events if event["event"].startswith("smoke.")]
    assert smoke_events[-1]["status"] == "ok"
    assert smoke_events[-1]["metadata"]["benchmark"]["runtime_type"] == "mlx_sniper"


def test_smoke_fails_clearly_and_writes_failure_artifact_when_server_unavailable(
    tmp_path: Path,
) -> None:
    target = get_target("local_deep_moe")
    target = target.__class__(
        **{
            **target.__dict__,
            "health_url": "http://127.0.0.1:1/api/tags",
            "port": 1,
        }
    )
    metric_source = FakeMetricSource(
        memory_pressure={"level": "warn", "score": 80.0},
        swap_used_bytes=9_000,
        orphan_processes=["mlx-sniper"],
    )
    probes = SystemMetricProbes(metric_source, swap_baseline_bytes=8_000)

    result = run_smoke(
        target,
        artifact_root=tmp_path,
        base_url="http://127.0.0.1:1",
        metric_probes=probes,
        orphan_check_fn=lambda: OrphanCheckResult(
            has_orphan=True,
            port_occupied=True,
            occupying_pid=404,
            stale_state_pid=None,
            message="orphan detected: port 1 held by pid 404",
        ),
        timestamp="20260609T120001Z",
    )

    assert result.record.status == "failed"
    assert result.record.runtime_type == "mlx_sniper"
    assert result.record.message is not None
    assert "unreachable" in result.record.message.lower() or "unavailable" in result.record.message.lower()
    assert result.record.load_time_s is None
    assert result.record.ttft_s is None
    assert result.record.tokens_per_second is None
    assert result.record.memory["status"] == "ok"
    assert result.record.orphan_status["orphaned"] is True

    jsonl_path = result.artifact_dir / "run.jsonl"
    summary_path = result.artifact_dir / "summary.md"
    assert jsonl_path.is_file()
    assert summary_path.is_file()

    events = [json.loads(line) for line in jsonl_path.read_text().splitlines()]
    assert events[-1]["event"] == "smoke.failed"
    assert events[-1]["status"] == "failed"
    assert "benchmark" in events[-1]["metadata"]
