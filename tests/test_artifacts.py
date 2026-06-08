"""Tests for benchmark artifact writer (no real model)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mac_llm.bench.artifacts import BenchmarkArtifactWriter, RunRecord


def test_creates_timestamped_run_directory(tmp_path: Path) -> None:
    writer = BenchmarkArtifactWriter(tmp_path, timestamp="20260109T120000Z")
    run_dir = writer.ensure_run_dir()

    assert run_dir == tmp_path / "benchmarks" / "runs" / "20260109T120000Z"
    assert run_dir.is_dir()


def test_append_writes_jsonl_with_required_fields(tmp_path: Path) -> None:
    writer = BenchmarkArtifactWriter(
        tmp_path,
        timestamp="20260109T120000Z",
        run_id="run-test-1",
    )
    writer.ensure_run_dir()
    writer.append(
        RunRecord(event="bench.start", status="ok", message="starting benchmark")
    )
    writer.append(
        RunRecord(event="bench.complete", status="ok", message="done")
    )

    jsonl_path = writer.run_dir / "run.jsonl"
    assert jsonl_path.is_file()

    lines = jsonl_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2

    first = json.loads(lines[0])
    assert first["schema_version"] == 1
    assert first["run_id"] == "run-test-1"
    assert first["event"] == "bench.start"
    assert first["status"] == "ok"
    assert first["message"] == "starting benchmark"


def test_summary_renders_from_appended_records(tmp_path: Path) -> None:
    writer = BenchmarkArtifactWriter(
        tmp_path,
        timestamp="20260109T120000Z",
        run_id="run-test-2",
    )
    writer.append(RunRecord(event="bench.start", status="ok", message="go"))
    writer.append(RunRecord(event="bench.complete", status="ok", message="finished"))

    summary_path = writer.write_summary()

    assert summary_path == writer.run_dir / "summary.md"
    summary = summary_path.read_text(encoding="utf-8")
    assert "# Benchmark run run-test-2" in summary
    assert "bench.start" in summary
    assert "bench.complete" in summary
    assert "finished" in summary


def test_jsonl_is_append_only(tmp_path: Path) -> None:
    writer = BenchmarkArtifactWriter(tmp_path, timestamp="20260109T120000Z")
    writer.ensure_run_dir()
    writer.append(RunRecord(event="first", status="ok"))
    writer.append(RunRecord(event="second", status="ok"))

    jsonl_path = writer.run_dir / "run.jsonl"
    events = [json.loads(line) for line in jsonl_path.read_text().splitlines()]
    assert [e["event"] for e in events] == ["first", "second"]
