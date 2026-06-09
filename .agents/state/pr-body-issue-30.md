Closes #30

## What changed

- Added `mac_llm/bench/kv.py` orchestrating cold prompt → cache save → cache load → warm prompt with injectable cache store and inference runner seams.
- Records cache id, model id, runtime id, tokenizer/prompt hash, prefix tokens, save/load times, cold/warm TTFT, disk size, compatibility, and cache-helped verdict.
- Incompatible cache load fails closed (no warm success path); failure still writes `run.jsonl` + `summary.md`.
- Wired `mac-llm bench kv --target <id> --prefix <name>` CLI; fails clearly with artifact when runtime/cache integration is unavailable.

## How to test

- `python3 -m pytest tests/test_bench_kv.py tests/test_cli.py -v`
- `python3 -m pytest` (full suite)
- Manual (may fail-clear without hardware/integration): `mac-llm bench kv --target local_deep_moe --prefix repo-review`

## Benchmark/artifact path

- `benchmarks/runs/<timestamp>/run.jsonl`
- `benchmarks/runs/<timestamp>/summary.md`

## Known limitations

- CLI uses `mac_llm.cache.KvPromptCacheStore` (from #29); `KvRuntimeRunner` is not wired yet, so manual runs fail-clear with artifact until runtime integration lands.
- No router dependence on cache (per issue scope).

## Next smallest step

- Add `mac_llm.cache.runtime.KvRuntimeRunner` and rerun manual benchmark on `local_deep_moe`.

## Agent checklist

- [x] Issue scope only
- [x] Tests with fakes (no real model)
- [x] Fail-closed incompatible cache
- [x] Artifact on success and failure
