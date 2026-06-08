# North Star

`mac-llm` is a **24 GB Apple Silicon Mac Mini local-agent runtime** that maximizes useful coding-agent performance on fixed hardware.

## What we build

A runtime that:

- runs **one active local model/runtime at a time**
- swaps models safely via fast SSD-backed loading
- reuses KV / prompt cache where practical
- selects targets by **role** (coding, planning, review, debugging, summarization, tool operator)
- uses a **local fast model** for common work and a **local deep/MoE model** for high-leverage planning, review, and debugging
- uses a small local tool/operator model for narrow structured tool calls
- escalates to role-specific external targets only when policy allows
- brokers tool access for external agents
- chains fallbacks for context, token, budget, and provider exhaustion
- logs cost so frontier-model use stays measurable and controlled

Execution shape:

```text
raw request / repo / diff / tests / tool output
→ structured artifacts
→ role and target decision
→ compact context
→ local model / tool operator / external target
→ validation
→ logged outcome
```

## Core hypothesis

Before advanced routing, many roles, or many models, prove:

```text
Can a 24 GB Mac Mini safely and usefully switch:
local_fast → local_deep_moe → local_fast
while measuring load time, TTFT, tok/s, memory pressure, swap, orphan status, and cache behavior?
```

If this cannot be proven, the rest is premature.

## Non-goals

`mac-llm` is **not**:

- a generic model manager or model zoo
- a model leaderboard or Hugging Face discovery engine
- a frontend/UI project (Odysseus, Pi, PicoClaw, editor UI)
- a broad research playground
- a platform that runs multiple large local models simultaneously
- a system that auto-loads deep models without policy/memory checks
- a system that makes external API calls by default

## Definition of success

The pivot succeeds when a benchmark report shows:

```text
On the 24 GB Mac Mini, mac-llm can safely run a fast local model,
swap to a local deep/MoE model,
run a role-appropriate task,
swap back,
optionally reuse cache,
use brokered local tools safely,
and leave no orphaned processes or swap disaster behind.
```

Full milestone and architecture detail lives in `PROJECT.md` at the repo root.
