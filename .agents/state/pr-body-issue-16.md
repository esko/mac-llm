Closes #16

## What changed

- Added `mac_llm/bench/swap.py` orchestrating fast→fast swap: ensure inactive → start → prompt → stop ×2 with injectable runtime, prompt runner, and metric probes.
- Wired `mac-llm bench swap --from local_fast --to local_fast` in the CLI.
- Records cold load, health, TTFT, decode/prompt tok/s, stop time, and system metrics into `run.jsonl` + `summary.md`.
- Failure path writes a failure artifact and attempts cleanup so no managed runtime is left running.

## How to test

- `python3 -m pytest tests/test_bench_swap.py`
- `python3 -m pytest`
- Manual (may fail-clear without a model): `mac-llm bench swap --from local_fast --to local_fast`

## Benchmark/artifact path

- `benchmarks/runs/<timestamp>/run.jsonl`
- `benchmarks/runs/<timestamp>/summary.md`

## Known limitations

- Milestone 3 scope only supports `local_fast → local_fast`.
- System metric probes degrade to unavailable when sources are missing.

## Next smallest step

- Milestone 4: add `local_deep_moe` target and deep swap benchmarks.

## Agent checklist

- [x] Scope is limited to the linked issue
- [x] TDD used where practical
- [x] Relevant tests/commands run where available
- [ ] Review loop completed
- [x] No automatic merge
