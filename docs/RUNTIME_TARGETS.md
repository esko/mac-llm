# Runtime Targets

Initial local targets for the 24 GB Mac Mini runtime. One active target at a time.

## Initial targets

| Target ID | Role | Runtime | Purpose |
|-----------|------|---------|---------|
| `local_fast` | Default for coding, summarization, tool operator | llama.cpp or MLX (TBD by benchmark) | Fast everyday agent work |
| `local_deep_moe` | Deep target for planning, review, debugging | mlx-sniper | Higher-leverage reasoning on MoE weights |

Do not add multiple deep models until one works end-to-end.

## Model candidates

Do not evaluate every model upfront. Start with these candidates from the implementation plan:

### `local_fast`

- **Primary:** Qwen3.5-9B Q4_K_M (or currently available 9B/12B equivalent)
- **Alternative (benchmark):** Gemma 4-12B-it Q4_K_M GGUF
- **Later:** newer Qwen 9B/12B variants, Mellum2

### `local_deep_moe`

- **Primary:** Qwen3.5-35B-A3B via mlx-sniper
- **Fallback:** Qwen3-30B-A3B via mlx-sniper
- **Alternative (benchmark):** Gemma 4-26B-A4B via `mlx-sniper download gemma4-26b` (experimental)

Whichever deep candidate is easiest to run first wins; do not maintain parallel deep targets until the first swap benchmark passes.

## Deferred (research only)

Not initial production candidates:

```text
dense Flash Streaming
1-bit fallback
BeeLlama
KVarN
DFlash
huge model zoo
Spark-like traffic-shaped expert placement
```

## Promotion discipline

A candidate becomes a configured target only after:

1. Command rendering works (`render_start_command`)
2. Start/stop/health/orphan checks pass
3. Benchmark artifact records load time, TTFT, tok/s, memory band, and swap delta
4. Expected resident memory fits the band rules in `docs/24GB_PROFILE_POLICY.md`

Full milestone sequence and role mapping live in `PROJECT.md`.

## Manual runtime lifecycle

Use the managed lifecycle commands after confirming the target command is available on the host and required environment variables are set.

Dry-run the rendered command first:

```bash
mac-llm runtime render local_fast
```

Start the managed runtime:

```bash
export MAC_LLM_MODEL_LOCAL_FAST=/path/to/model.gguf
mac-llm runtime start local_fast
```

Check persisted state:

```bash
mac-llm runtime status local_fast
```

Probe health:

```bash
mac-llm runtime health local_fast
```

Check for leftover processes or stale state:

```bash
mac-llm runtime orphan-check local_fast
```

Stop the managed runtime (targeted PID only; no `pkill`):

```bash
mac-llm runtime stop local_fast
```

Run an OpenAI-compatible smoke request and write a benchmark artifact under `benchmarks/runs/<timestamp>/`:

```bash
export MAC_LLM_MODEL_LOCAL_DEEP_MOE=/path/to/model
mac-llm runtime start local_deep_moe
mac-llm runtime smoke local_deep_moe
```

The smoke command records `runtime_type`, load time, TTFT, tok/s, memory pressure, and orphan status. When the server or model is unavailable, it exits non-zero and still writes a failure artifact with the captured fields.

State is written under the target `state_path` from the render output (for `local_fast`, `~/.mac-llm/state/local_fast.json`). Logs append to the target `log_path`.
