Closes #13

## What changed

- Added `RuntimeTarget` dataclass with target id, runtime type, command, port, health URL, log path, state path, stop timeout, and model config reference.
- Added pure `render_start_command(target)` returning command plus metadata.
- Added `mac-llm runtime render <target>` CLI dry-run that prints metadata without starting a process.
- Unknown targets fail closed with a non-zero exit code.

## How to test

```bash
pytest tests/test_runtime_render.py
python3 -m mac_llm.cli runtime render local_fast
python3 -m mac_llm.cli runtime render missing_target  # expect exit 1
```

## Benchmark/artifact path

N/A — dry-run only, no process management.

## Known limitations

- Only `local_fast` is configured; start/stop/health/orphan logic is out of scope (next issue).
- Runtime backend choice for `local_fast` is placeholder (`llama.cpp`) pending benchmark.

## Next smallest step

- Managed runtime start/stop/health checks for `local_fast`.

## Agent checklist

- [x] Tests added/updated
- [x] No shell=True, pkill, or hardcoded machine model paths
- [x] Fail-closed on unknown target
