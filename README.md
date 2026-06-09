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
- **Disk space** — ~6–8 GB for a fast GGUF; ~20–25 GB for a preprocessed deep MoE bundle
- **Do not run both targets at once** — one active large model at a time

---

## Model setup

`mac-llm` does not download models for you. Install the runtime binary, fetch or preprocess a model, then point environment variables at the on-disk path.

### Recommended models (24 GB Mac Mini)

Start with one fast model and one deep model. Do not benchmark every variant upfront.

| Target | Suggested model | Format | Typical resident RAM | Band | Notes |
|--------|-----------------|--------|-------------------|------|-------|
| `local_fast` | **Qwen3.5-9B** (or latest Qwen 9B/12B equivalent) | GGUF `Q4_K_M` | ~6–8 GB | Green | Primary everyday coding / summarization target |
| `local_fast` (later) | Mellum2, Gemma 4 QAT | GGUF / MLX | TBD by benchmark | Green–Yellow | Evaluate only after the primary fast path works |
| `local_deep_moe` | **Qwen3.5-35B-A3B** | mlx-sniper preprocessed | ~9–12 GB active | Yellow | Primary deep target for planning / review / debugging |
| `local_deep_moe` (fallback) | **Qwen3-30B-A3B** | mlx-sniper preprocessed | ~9–11 GB active | Yellow | Use if 35B is harder to fetch or preprocess |

Orange/red bands (>17 GB resident) require a recorded benchmark and explicit approval before production use. See [`docs/24GB_PROFILE_POLICY.md`](docs/24GB_PROFILE_POLICY.md).

Full candidate list and promotion rules: [`docs/RUNTIME_TARGETS.md`](docs/RUNTIME_TARGETS.md).

### 1. Install `llama-server` (`local_fast`)

Install llama.cpp so `llama-server` is on your `PATH`:

```bash
# Option A: Homebrew (simplest on macOS)
brew install llama.cpp

# Option B: build from source
git clone https://github.com/ggerganov/llama.cpp.git
cd llama.cpp
cmake -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --config Release
# add build/bin to PATH, or: ln -s "$(pwd)/build/bin/llama-server" ~/.local/bin/
```

Verify:

```bash
llama-server --version
```

### 2. Download a fast GGUF model

Use any trusted GGUF source (Hugging Face is typical). Pick a **Q4_K_M** (or similar) quant of a 9B-class instruct/coder model.

```bash
pip install huggingface_hub

# Example: download a Qwen 9B-class GGUF (check the model card for the exact file name)
huggingface-cli download \
  unsloth/Qwen2.5-Coder-7B-Instruct-GGUF \
  Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf \
  --local-dir ~/models/local_fast
```

Replace the repo and filename with the **Qwen3.5-9B Q4_K_M** (or current 9B/12B) artifact you intend to standardize on. The path must be a single `.gguf` file.

```bash
export MAC_LLM_MODEL_LOCAL_FAST=~/models/local_fast/Qwen2.5-Coder-7B-Instruct-Q4_K_M.gguf
```

### 3. Install `mlx-sniper` (`local_deep_moe`)

`mac-llm` expects the `mlx-sniper` CLI on `PATH`. The repo vendors a research copy; the packaged CLI lives under `research/expert-sniper/cli-agent/`:

```bash
cd research/expert-sniper/cli-agent
pip install -e .
```

Or install the published package from [Hugging Face — mlx-expert-sniper](https://huggingface.co/waltgrace/mlx-expert-sniper) if you prefer not to use the vendored tree.

Verify:

```bash
mlx-sniper --help
```

### 4. Preprocess a deep MoE model

MoE models must be **preprocessed once** before serving. This splits expert weights for SSD streaming and takes significant disk space.

```bash
mkdir -p ~/models

# Primary candidate (pick one to start)
mlx-sniper preprocess mlx-community/Qwen3.5-35B-A3B-4bit -o ~/models/qwen35-35b-a3b

# Fallback if the above is unavailable or too heavy
# mlx-sniper preprocess mlx-community/Qwen3-30B-A3B-4bit -o ~/models/qwen3-30b-a3b
```

Preprocessing downloads weights from Hugging Face and writes a local directory (~20–25 GB free disk recommended for 35B-class models).

Point `mac-llm` at the **preprocessed directory**, not the raw HF snapshot:

```bash
export MAC_LLM_MODEL_LOCAL_DEEP_MOE=~/models/qwen35-35b-a3b
```

### 5. Smoke-test both targets

```bash
# Fast path
mac-llm runtime render local_fast
mac-llm runtime start local_fast
mac-llm runtime health local_fast
mac-llm runtime stop local_fast

# Deep path (stop local_fast first)
mac-llm runtime render local_deep_moe
mac-llm runtime start local_deep_moe
mac-llm runtime smoke local_deep_moe
mac-llm runtime stop local_deep_moe
```

Persist the variables in your shell profile (`~/.zshrc`, `~/.bashrc`, or fish `config.fish`) so managed starts survive new terminals.

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

### Start a local model

Complete [Model setup](#model-setup) first, then:

```bash
# assumes MAC_LLM_MODEL_LOCAL_FAST is already exported
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

See [Benchmarking](#benchmarking) for the full proof sequence, artifact format, and how to interpret results.

---

## Environment variables

| Variable | Used by | Purpose |
|----------|---------|---------|
| `MAC_LLM_MODEL_LOCAL_FAST` | `local_fast` | Path to a single `.gguf` file for `llama-server` |
| `MAC_LLM_MODEL_LOCAL_DEEP_MOE` | `local_deep_moe` | Path to a **preprocessed** mlx-sniper model directory |

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

Each run writes `benchmarks/runs/<timestamp>/run.jsonl` + `summary.md`. Details: [Benchmarking](#benchmarking).

---

## Runtime targets

| Target ID | Runtime | Port | Typical use |
|-----------|---------|------|-------------|
| `local_fast` | llama.cpp (`llama-server`) | 8080 | Everyday coding, summarization |
| `local_deep_moe` | mlx-sniper | 8081 | Planning, review, debugging (MoE) |

Model candidates and promotion rules: [`docs/RUNTIME_TARGETS.md`](docs/RUNTIME_TARGETS.md).

Memory bands (green ≤12 GB … red >20 GB): [`docs/24GB_PROFILE_POLICY.md`](docs/24GB_PROFILE_POLICY.md).

---

## Benchmarking

Benchmarks are how `mac-llm` proves the 24 GB runtime hypothesis: **one active model, safe swaps, measurable artifacts, no orphan processes**. Every benchmark writes structured output under `benchmarks/runs/<timestamp>/` in the repo (or `--artifact-root` for smoke).

`mac-llm` is not a model leaderboard. Run benchmarks to validate **your** models on **your** Mac Mini before promoting them to default role mappings.

### What gets measured

| Signal | Where recorded | Used for |
|--------|----------------|----------|
| Load / start time | swap, swap-sequence, smoke | Swap latency, cold-start cost |
| TTFT, tok/s | swap cycles, smoke, kv | Inference quality of service |
| Memory pressure | system metric probes | Green/yellow/orange/red band checks |
| Swap delta | system metric probes | Detect swap thrashing during swaps |
| Orphan status | orphan-check per cycle | Prove clean teardown |
| Cache save/load, helped verdict | `bench kv` | Prompt-cache ROI |
| Per-step target metadata | swap-sequence | fast→deep→fast proof |

Failures are first-class: benchmarks exit non-zero **and** write a failure artifact with the captured fields so you can debug without re-running blindly.

### Artifact layout

Each run creates:

```text
benchmarks/runs/20260609T120000Z/
  run.jsonl     # append-only JSON lines (schema_version, run_id, event, status, metadata)
  summary.md    # human-readable event list derived from run.jsonl
```

Example `run.jsonl` events:

```json
{"schema_version": 1, "run_id": "20260609T120000Z", "event": "bench.swap.start", "status": "ok", "metadata": {"from": "local_fast", "to": "local_fast"}}
{"schema_version": 1, "run_id": "20260609T120000Z", "event": "bench.swap.system_metrics", "status": "ok", "metadata": {"metrics": {"memory_pressure": {"status": "ok"}, "swap_delta": {"status": "ok"}}}}
```

Inspect the latest run:

```bash
ls -lt benchmarks/runs/ | head
cat benchmarks/runs/<timestamp>/summary.md
tail benchmarks/runs/<timestamp>/run.jsonl
```

### Recommended benchmark sequence

Run from the repo root with [models installed](#model-setup). **Stop each target before starting the next** — only one active large runtime at a time.

#### Step 1 — Per-target smoke

Confirms the OpenAI-compatible API, records load time, TTFT, tok/s, memory, and orphan fields:

```bash
mac-llm runtime start local_fast
mac-llm runtime smoke local_fast
mac-llm runtime stop local_fast

mac-llm runtime start local_deep_moe
mac-llm runtime smoke local_deep_moe
mac-llm runtime stop local_deep_moe
```

#### Step 2 — Fast→fast swap (lifecycle proof)

Runs two full start→prompt→stop cycles on `local_fast`. Verifies managed lifecycle + artifact writer + **no orphan** after success or failure:

```bash
mac-llm bench swap --from local_fast --to local_fast
```

Currently requires `local_fast` for both `--from` and `--to`. This is the minimum bar before multi-target swaps.

#### Step 3 — Fast→deep→fast swap-sequence (primary runtime proof)

The north-star scenario from [`docs/NORTH_STAR.md`](docs/NORTH_STAR.md):

```bash
mac-llm bench swap-sequence local_fast local_deep_moe local_fast
```

Each step: ensure inactive → start → fixed prompt → stop. Review per-step timings and orphan checks in `summary.md`.

#### Step 4 — Prompt-cache benchmark (optional)

Compares cold vs warm/restored KV cache for a named prefix:

```bash
mac-llm bench kv --target local_deep_moe --prefix repo-review
```

Requires KV runtime integration; fails clearly with an artifact when the runtime layer is unavailable.

### Example: full local proof session

```bash
cd mac-llm
source .venv/bin/activate

# 1. Smoke both targets
mac-llm runtime start local_fast && mac-llm runtime smoke local_fast && mac-llm runtime stop local_fast
mac-llm runtime start local_deep_moe && mac-llm runtime smoke local_deep_moe && mac-llm runtime stop local_deep_moe

# 2. Swap proofs
mac-llm bench swap --from local_fast --to local_fast
mac-llm bench swap-sequence local_fast local_deep_moe local_fast

# 3. Review artifacts
latest=$(ls -t benchmarks/runs | head -1)
cat "benchmarks/runs/$latest/summary.md"
```

### Interpreting results

Before promoting a model or target, check:

1. **Orphan check** — `runtime orphan-check <target>` returns clean after every benchmark; swap benchmarks assert this in artifacts.
2. **Memory band** — resident memory fits [`docs/24GB_PROFILE_POLICY.md`](docs/24GB_PROFILE_POLICY.md) for the intended role (green for `local_fast`, yellow for `local_deep_moe`).
3. **Swap delta** — swap usage should not spike uncontrollably during fast→deep→fast sequences.
4. **TTFT / tok/s** — acceptable for the role (coding vs review); record numbers in the artifact for comparison across model candidates.
5. **Orange/red** — if resident memory exceeds 17 GB, do not promote without explicit human approval and a saved benchmark artifact.

A target graduates from “candidate” to “configured default” only after: render works, lifecycle passes, benchmarks record the fields above, and memory band rules are satisfied. See [`docs/RUNTIME_TARGETS.md`](docs/RUNTIME_TARGETS.md#promotion-discipline).

### Benchmark commands (quick reference)

| Command | Milestone | Purpose |
|---------|-----------|---------|
| `mac-llm runtime smoke <target>` | Per-target health | API + inference smoke + artifact |
| `mac-llm bench swap --from local_fast --to local_fast` | M3 | Managed swap + orphan guarantee |
| `mac-llm bench swap-sequence local_fast local_deep_moe local_fast` | M5 | Primary fast→deep→fast proof |
| `mac-llm bench kv --target local_deep_moe --prefix <name>` | M6 | Cold vs warm cache comparison |

All commands are also listed under [Benchmark commands](#benchmark-commands) in the command reference.

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
- **Host binaries required** — `llama-server` and `mlx-sniper` must be installed and on `PATH`; see [Model setup](#model-setup).
- **Models are manual** — download GGUF or preprocess MoE weights yourself; `mac-llm` only references paths via env vars.

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
