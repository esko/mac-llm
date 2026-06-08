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
- **Later:** newer Qwen 9B/12B variants, Mellum2, Gemma 4 QAT

### `local_deep_moe`

- **Primary:** Qwen3.5-35B-A3B via mlx-sniper
- **Fallback:** Qwen3-30B-A3B via mlx-sniper

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
