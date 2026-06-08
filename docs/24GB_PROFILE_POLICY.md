# 24 GB Profile Policy

Memory bands for the 24 GB Apple Silicon Mac Mini runtime. Expected **resident** memory (active model + runtime overhead) determines the band.

| Band | Expected resident | Rule |
|------|-------------------|------|
| **Green** | ≤ 12 GB | Safe default. Use for routine coding, summarization, and tool-operator work. |
| **Yellow** | 12–17 GB | Allowed for planning, review, and `local_deep` targets when role policy permits. |
| **Orange** | 17–20 GB | Benchmark and explicit approval required before production use. |
| **Red** | > 20 GB | Research only unless proven safe on this hardware. |

## Band rules

### Green (≤ 12 GB)

- Default operating band for `local_fast` and small tool/operator models.
- No extra gates beyond normal runtime health checks.

### Yellow (12–17 GB)

- Permitted when the active role maps to a deep target (planning, review, debugging).
- Swap-in must respect one-active-runtime policy and pass health checks.
- Monitor memory pressure and swap during benchmarks.

### Orange (17–20 GB)

- Do not promote to default role mapping without a recorded benchmark artifact.
- Requires explicit human approval after reviewing load time, TTFT, tok/s, swap delta, and orphan status.
- Fail closed if memory pressure enters unsafe range during the run.

### Red (> 20 GB)

- Not eligible for production role mapping.
- May be explored in isolated research runs with full artifact logging.
- Must not become the default path for any role until reclassified by benchmark evidence.

## Hard constraints

- Never run multiple large local models simultaneously.
- Never auto-load a deep model without policy and memory-band checks.
- If a target's expected resident places the system in orange or red, the runtime must refuse or require approval rather than silently proceeding.

See `docs/RUNTIME_TARGETS.md` for target definitions and `PROJECT.md` for milestone context.
