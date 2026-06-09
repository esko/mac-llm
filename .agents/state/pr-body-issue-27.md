Closes #27

## What changed

- Added `mac_llm/runtime/smoke.py` with an OpenAI-compatible smoke client for managed runtime targets.
- Added `SmokeBenchmarkRecord` in `mac_llm/bench/records.py` recording `runtime_type`, load time, TTFT, tok/s, memory pressure, and orphan status.
- Smoke runs always write `benchmarks/runs/<timestamp>/run.jsonl` + `summary.md`, including on failure when the server/model is unavailable.
- Added `mac-llm runtime smoke <target>` CLI command and documented manual smoke for `local_deep_moe`.

## How to test

- `pytest`
- `mac-llm runtime smoke local_deep_moe` (requires a running mlx-sniper server; may fail-clear without hardware)

## Benchmark/artifact path

- `benchmarks/runs/<timestamp>/run.jsonl`
- `benchmarks/runs/<timestamp>/summary.md`

## Known limitations

- Non-streaming completion only; TTFT comes from server `timings.prompt_ms` when present.
- Memory probe uses the injectable metric source; defaults to unavailable when not configured on the host.

## Next smallest step

- Milestone 5 swap-sequence benchmark composing smoke + lifecycle steps.

## Agent checklist

- [x] Scope is limited to the linked issue
- [x] TDD used where practical
- [x] Relevant tests/commands run where available
- [ ] Review loop completed
- [x] No automatic merge
