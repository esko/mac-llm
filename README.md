# mac-llm

A **24 GB Apple Silicon Mac Mini** local-agent runtime. `mac-llm` manages one active local model at a time, swaps between fast and deep targets safely, records benchmark artifacts, and gates tool access for agents.

It is **not** a model zoo, a generic chat UI, or a platform that runs multiple large models at once. The goal is to prove—and then operate—a disciplined runtime on fixed hardware.

```text
request → structured artifacts → role/target decision → local model → logged outcome
```

For architecture and milestones, see [`PROJECT.md`](PROJECT.md). For scope and non-goals, see [`docs/NORTH_STAR.md`](docs/NORTH_STAR.md).

---

## Features

### Runtime management

- **Configured targets** — `local_fast` (llama.cpp) and `local_deep_moe` (mlx-sniper)
- **Dry-run rendering** — inspect start commands and paths without launching a process
- **Managed lifecycle** — start, stop, status, health check, orphan detection
- **One active runtime** — targeted PID stop only (no broad `pkill`)
- **State persistence** — PID, port, timestamps, and errors under `~/.mac-llm/`

### Role-based routing

- **Role → target mapping** — coding, planning, review, debugging, summarization, tool operator
- **Fail-closed selection** — unknown roles, targets, or policy violations raise clear errors
- **Manual ask CLI** — `mac-llm ask --role` for coding/planning/review without an automatic router
- **Heuristic router** (library) — strict-JSON `RouteDecision` schema with policy gates (deep target, external agents)

### Benchmarks & artifacts

- **Structured run logs** — `benchmarks/runs/<timestamp>/run.jsonl` + `summary.md`
- **Swap benchmark** — fast→fast lifecycle proof with orphan guarantee
- **Swap-sequence benchmark** — ordered multi-target runs (e.g. fast→deep→fast)
- **KV / prompt-cache benchmark** — cold vs warm comparison with cache-helped verdict
- **Smoke requests** — OpenAI-compatible probe with TTFT, tok/s, memory, orphan fields
- **System metric probes** — memory pressure, swap delta, orphan status (JSON-serializable)

### Safety & policy

- **24 GB memory bands** — green / yellow / orange / red resident-memory policy ([`docs/24GB_PROFILE_POLICY.md`](docs/24GB_PROFILE_POLICY.md))
- **Tool broker** — JSON tool-call schema, path sandboxing, read-only tools, approval-gated writes
- **External agents** — disabled by default; dry-run consultation briefs, redaction, cost ledger
- **KV cache** — save/load with fail-closed compatibility checks (model, runtime, prompt hash)

### Structured artifacts

Nine JSON-serializable artifact types (user task summary, git diff summary, tool results, etc.) for logging agent runs without dumping full repos.

---

## Requirements

- **macOS** on Apple Silicon (designed for a 24 GB Mac Mini)
- **Python 3.11+**
- Host tools for the targets you use:
  - `local_fast` — `llama-server` (llama.cpp) on port **8080**
  - `local_deep_moe` — `mlx-sniper` on port **8081**

---

## Quick start

### Install

```bash
git clone https://github.com/esko/mac-llm.git
cd mac-llm

python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Verify the CLI:

```bash
mac-llm --version
mac-llm --help
```

### Run tests

```bash
pytest
```

### First runtime dry-run

Inspect what would be started for the fast target (no process launched):

```bash
mac-llm runtime render local_fast
```

### Start a local model (when installed)

```bash
export MAC_LLM_MODEL_LOCAL_FAST=/path/to/your-model.gguf

mac-llm runtime start local_fast
mac-llm runtime status local_fast
mac-llm runtime health local_fast
```

### Ask with a role

After the runtime is up and healthy:

```bash
mac-llm ask --role coding "Summarize the purpose of mac_llm/runtime/manager.py"
```

### Run a swap benchmark

Proves start→prompt→stop twice with artifact output:

```bash
mac-llm bench swap --from local_fast --to local_fast
```

Artifacts land in `benchmarks/runs/<timestamp>/`.

---

## Environment variables

| Variable | Used by | Purpose |
|----------|---------|---------|
| `MAC_LLM_MODEL_LOCAL_FAST` | `local_fast` | Path to the GGUF model for llama-server |
| `MAC_LLM_MODEL_LOCAL_DEEP_MOE` | `local_deep_moe` | Path to the mlx-sniper model bundle |

State and logs default to `~/.mac-llm/state/` and `~/.mac-llm/logs/`.

---

## Command reference

### Global

```bash
mac-llm --version
mac-llm --help
```

### Role commands

Resolve which runtime target a role should use:

```bash
# JSON: target_id, deep_escalation, cache_strategy
mac-llm role select review
mac-llm role select planning --difficulty high
```

Difficulty choices: `low`, `medium`, `high`, `very_high`.

Run a prompt with manual role selection (starts runtime if needed, writes artifact on failure):

```bash
mac-llm ask --role coding "Explain this function"
mac-llm ask --role planning "Outline a refactor plan for the bench module"
mac-llm ask --role review "Review the changes in the last commit"
```

Roles for `ask`: `coding`, `planning`, `review`.

### Runtime commands

| Command | Description |
|---------|-------------|
| `mac-llm runtime render <target>` | Print start command, port, health URL, log/state paths (dry-run) |
| `mac-llm runtime start <target>` | Start the managed runtime |
| `mac-llm runtime stop <target>` | Stop via persisted PID |
| `mac-llm runtime status <target>` | JSON state (or `stopped`) |
| `mac-llm runtime health <target>` | Probe health URL |
| `mac-llm runtime orphan-check <target>` | Detect leftover processes / stale state |
| `mac-llm runtime smoke <target>` | OpenAI-compatible smoke request + artifact |

**Targets:** `local_fast`, `local_deep_moe`

```bash
# Dry-run
mac-llm runtime render local_deep_moe

# Lifecycle
export MAC_LLM_MODEL_LOCAL_DEEP_MOE=/path/to/qwen-sniper
mac-llm runtime start local_deep_moe
mac-llm runtime status local_deep_moe
mac-llm runtime health local_deep_moe
mac-llm runtime orphan-check local_deep_moe
mac-llm runtime stop local_deep_moe

# Smoke test (writes benchmarks/runs/<timestamp>/)
mac-llm runtime smoke local_deep_moe
mac-llm runtime smoke local_fast --artifact-root /tmp/bench
```

### Benchmark commands

| Command | Description |
|---------|-------------|
| `mac-llm bench swap --from <t> --to <t>` | Two-cycle swap benchmark with artifacts |
| `mac-llm bench swap-sequence <t1> <t2> ...` | Ordered multi-target sequence |
| `mac-llm bench kv --target <t> --prefix <name>` | Cold vs warm prompt-cache benchmark |

```bash
# Fast → fast swap proof
mac-llm bench swap --from local_fast --to local_fast

# Primary runtime proof: fast → deep → fast
mac-llm bench swap-sequence local_fast local_deep_moe local_fast

# Prompt-cache comparison (requires KV runtime integration)
mac-llm bench kv --target local_deep_moe --prefix repo-review
```

On success or failure, benchmarks write under:

```text
benchmarks/runs/<timestamp>/
  run.jsonl    # append-only event log
  summary.md   # human-readable summary
```

---

## Runtime targets

| Target ID | Runtime | Port | Typical use |
|-----------|---------|------|-------------|
| `local_fast` | llama.cpp (`llama-server`) | 8080 | Everyday coding, summarization |
| `local_deep_moe` | mlx-sniper | 8081 | Planning, review, debugging (MoE) |

Model candidates and promotion rules: [`docs/RUNTIME_TARGETS.md`](docs/RUNTIME_TARGETS.md).

Memory bands (green ≤12 GB … red >20 GB): [`docs/24GB_PROFILE_POLICY.md`](docs/24GB_PROFILE_POLICY.md).

---

## Tool broker (library)

External agents and future router integrations use the tool broker API—not exposed as CLI commands yet.

**Read-only tools** (no approval): `read_file_range`, `search_text`, `git_status`, `git_diff`, `list_files`

**Approval-gated tools**: `replace_block_hash_checked`, `propose_patch`, `run_test_command` (pytest only; no raw shell)

Paths are resolved against the repo root. Sensitive paths (`.env`, `.ssh`, `.gnupg`, etc.) fail closed.

```python
from pathlib import Path
from mac_llm.tools.broker import ToolBroker

broker = ToolBroker(repo_root=Path.cwd())
result = broker.dispatch(
    role="coding",
    requester_target="local_fast",
    tool_name="read_file_range",
    args={"path": "mac_llm/cli.py", "start_line": 1, "end_line": 20},
)
```

---

## Project layout

```text
mac_llm/
  cli.py           # Console entry point
  runtime/         # Targets, manager, probes, smoke, completion client
  roles/           # Role-target config and ask CLI
  router/          # RouteDecision schema and heuristic router
  bench/           # Swap, swap-sequence, KV benchmarks; artifact writer
  cache/           # KV / prompt-cache save-load
  tools/           # Tool broker, operator, read-only and edit tools
  external/        # External-agent policy, briefs, redaction, cost ledger
  artifacts/       # Structured artifact schemas
docs/              # North star, memory policy, runtime targets
benchmarks/runs/   # Benchmark output (created at runtime)
tests/             # Pytest suite
```

---

## Current limitations

- **One active large model at a time** — by design; do not run both targets simultaneously.
- **Router not wired to CLI** — use `mac-llm ask --role` or `mac-llm role select` for now; automatic routing is library-only.
- **External agents disabled by default** — consultation paths are dry-run / policy-gated until explicitly enabled in config.
- **KV bench CLI** — requires full KV runtime runner integration; fails clearly with an artifact when the runtime layer is unavailable.
- **Host binaries required** — `llama-server` and `mlx-sniper` must be installed and on `PATH`; `mac-llm` does not download models.

---

## Documentation

| Doc | Contents |
|-----|----------|
| [`docs/NORTH_STAR.md`](docs/NORTH_STAR.md) | Product north star and non-goals |
| [`docs/24GB_PROFILE_POLICY.md`](docs/24GB_PROFILE_POLICY.md) | Memory bands and approval rules |
| [`docs/RUNTIME_TARGETS.md`](docs/RUNTIME_TARGETS.md) | Target definitions and lifecycle |
| [`PROJECT.md`](PROJECT.md) | Full implementation plan and milestones |
| [`AGENTS.md`](AGENTS.md) | Agent/workflow conventions (for contributors) |

---

## License

See repository license file if present. Imported research code under `research/` and `mlx/` may carry separate upstream terms—see [`docs/upstream/mac-code.md`](docs/upstream/mac-code.md).
