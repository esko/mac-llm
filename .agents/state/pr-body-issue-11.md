Closes #11

## What changed

- Added `pyproject.toml` with the `mac_llm` package and `mac-llm` console entry point
- Added CLI skeleton with `--version` and `--help`
- Added `BenchmarkArtifactWriter` that creates `benchmarks/runs/<timestamp>/run.jsonl` and `summary.md`
- Added tests for timestamped-dir creation, JSONL append, summary rendering, and CLI entry point

## How to test

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest
.venv/bin/mac-llm --version
.venv/bin/mac-llm --help
```

## Benchmark/artifact path

`benchmarks/runs/<timestamp>/run.jsonl` + `summary.md` via `mac_llm.bench.artifacts.BenchmarkArtifactWriter`

## Known limitations

- CLI is a skeleton only (no subcommands yet)
- No runtime manager or model integration

## Next smallest step

- Milestone 1 scope docs (separate issue)

## Agent checklist

- [x] Scope is limited to the linked issue
- [x] TDD used where practical
- [x] Relevant tests/commands run where available
- [ ] Review loop completed
- [x] No automatic merge
