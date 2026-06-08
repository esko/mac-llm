# Safety audit and Milestone 1 boundary

Milestone 0 orientation report (Cursor slice). Parent: [#3](https://github.com/esko/mac-llm/issues/3).

This document inventories unsafe behavior in the pinned `mac-code` import and defines the narrow first-party surface allowed in Milestone 1. It is independent from the runtime/cache/benchmark map in `docs/orientation/runtime-map.md` (Claude slice, issue #4).

## Methodology

**Observed:** claims verified by static search and file reads only. No Python modules were imported or executed; no models, servers, shell commands, or network requests were run.

**Imported scope** (from `docs/upstream/mac-code.md`):

- `agent.py`
- `chat.py`
- `mlx/`
- `research/expert-sniper/cli-agent/`
- `research/expert-sniper/mlx-sniper/`

**Inferred / recommended:** scope boundaries and production guidance derived from issue #3 and repository workflow docs, not from prototype source.

## Risk legend

| Level | Meaning |
|-------|---------|
| **Critical** | Can terminate unrelated processes, execute arbitrary shell, or write outside an explicit user path |
| **High** | Starts long-lived runtimes, loads models, or performs cloud/network I/O on import or main |
| **Medium** | Writes under home-directory cache paths or mutates model artifacts |
| **Low** | Read-only or bounded local inspection (e.g. `sysctl`) |

---

## 1. Process termination (`pkill`)

Every `pkill` occurrence in imported scope:

| Location | Command | Consequence (observed) |
|----------|---------|------------------------|
| `agent.py:404` | `pkill -f llama-server` | During `swap_model()`, kills **all** processes whose command line matches `llama-server`, not only the agent's own server. Other users' or services' llama.cpp instances on the same host can be terminated. |
| `mlx/benchmark.py:56` | `pkill -f llama-server` | Before starting llama.cpp for benchmark run 1; same broad pattern match risk. |
| `mlx/benchmark.py:57` | `pkill -f mlx_engine` | Kills processes matching `mlx_engine` (including `mlx_engine.py` servers) before llama benchmark. |
| `mlx/benchmark.py:70` | `pkill -f llama-server` | Before starting MLX engine for benchmark run 2. |
| `mlx/benchmark.py:71` | `pkill -f mlx_engine` | Same as above, before MLX start. |
| `mlx/agent_benchmark.py:23` | `pkill -f llama-server` | Same pattern in agent benchmark backend swap. |
| `mlx/agent_benchmark.py:24` | `pkill -f mlx_engine` | Same. |
| `mlx/agent_benchmark.py:37` | `pkill -f llama-server` | Before MLX backend start. |
| `mlx/agent_benchmark.py:38` | `pkill -f mlx_engine` | Before MLX backend start. |

**Risk:** Critical. Pattern-based kill is not scoped to a PID file or parent process.

**Recommendation (inferred):** Milestone 1 must not call `pkill` or adopt prototype runtime swapping.

---

## 2. Shell invocation (`shell=True`)

Every `shell=True` occurrence in imported scope:

| Location | Call site | Consequence (observed) |
|----------|-----------|------------------------|
| `agent.py:153` | `run_smart_tool()` → `sp.run(cmd, shell=True, ...)` | `cmd` is LLM-generated text from `generate_shell_command()`. Full shell interpretation; injection and arbitrary command execution are possible. Timeout 30s; cwd is `work_dir`. |
| `agent.py:254` | `run_file_tool()` → `sp.run(cmd, shell=True, ...)` | User text after `execute`/`run` prefixes is passed directly to the shell. Same injection surface. |
| `research/expert-sniper/mlx-sniper/moe_agent_macbook.py:338` | `run_shell()` → `subprocess.run(cmd, shell=True, ...)` | `cmd` is LLM output from `engine.quick_call()`. Same arbitrary-shell risk during MoE agent shell tasks. |

**Risk:** Critical. All three sites trust model-generated or user-supplied strings as shell programs.

**Recommendation (inferred):** Production CLI must not expose `shell=True` tool paths from `agent.py` or mlx-sniper agents.

---

## 3. Other subprocess and process control

| Location | API / command | Role | Consequence (observed) | Risk |
|----------|---------------|------|------------------------|------|
| `agent.py:415` | `subprocess.Popen(cmd_list, ...)` | `swap_model()` | Starts `llama-server` with hardcoded model path and flags; stdout/stderr discarded. | High |
| `agent.py:580` | `subprocess.Popen([PICOCLAW, "agent", ...])` | `picoclaw_call_live()` | Runs external binary at `~/Desktop/qwen/picoclaw/build/picoclaw-darwin-arm64`; streams stdout for UI. Agent tools (search, exec, files) run inside picoclaw, not audited here. | High |
| `mlx/benchmark.py:59–66` | `subprocess.Popen([...])` | `start_llama_9b()` | Starts `llama-server` on port 8000 after pkill. | High |
| `mlx/benchmark.py:73–76` | `subprocess.Popen([sys.executable, "mlx_engine.py", ...], cwd=~/Desktop/mac-code-mlx)` | `start_mlx_9b()` | Starts MLX HTTP engine from **external** directory not in this repo. | High |
| `mlx/agent_benchmark.py:26–33` | `subprocess.Popen` | `start_llama_9b()` | Same llama-server launch pattern. | High |
| `mlx/agent_benchmark.py:40–43` | `subprocess.Popen` | `start_mlx_9b()` | Same MLX launch from `~/Desktop/mac-code-mlx`. | High |
| `mlx/agent_benchmark.py:47–48` | `sys.path.insert` + `from agent import ...` | Module import at script run | Pulls in `agent.py` side effects (logging dir creation, tool functions) when benchmark script runs. | High |
| `research/expert-sniper/mlx-sniper/flash_moe.py:309` | `subprocess.run(["sudo", "purge"], ...)` | Memory purge before bench | Requires elevated privileges; fails or prompts on non-macOS / locked-down systems. | High |
| `research/expert-sniper/mlx-sniper/benchmark_fallback.py:123` | `os.system("sudo purge 2>/dev/null")` | Bench setup | Same sudo purge pattern via shell. | High |
| `research/expert-sniper/mlx-sniper/bench_quick.py:96` | `os.system("sudo purge 2>/dev/null")` | Bench setup | Same. | High |
| `research/expert-sniper/mlx-sniper/bench_mixed.py:134` | `os.system("sudo purge 2>/dev/null")` | Bench setup | Same. | High |
| `research/expert-sniper/cli-agent/.../calibrate.py:32` | `subprocess.run(["sysctl", "-n", "hw.memsize"], ...)` | RAM detection | Read-only hardware query (macOS). | Low |
| `research/expert-sniper/mlx-sniper/calibrate.py:32` | Same `sysctl` call | RAM detection | Same. | Low |
| `mlx/mlx_engine.py:292+` | `HTTPServer(...).serve_forever()` | `main()` | Binds HTTP server (default port 8000); loads MLX model in-process before serving. | High |
| `research/expert-sniper/cli-agent/.../server.py:233–236` | `HTTPServer` + `serve_forever()` | `run_server()` | Ollama-compatible API; pre-loads engine via `_get_engine()`. | High |

**Inspect-only note:** `agent.py:137` documents `lsof -i :8000` as an **example** in an LLM system prompt for `generate_shell_command()`; it is not executed unless the model emits that command and `run_smart_tool()` runs it.

---

## 4. Hardcoded machine, model, and output paths

Paths below are **literals or expanduser defaults** in source (observed). They assume a specific developer machine layout.

### Top-level agent and chat

| Symbol / usage | Path pattern | File |
|----------------|--------------|------|
| `LOGS_DIR` | `~/.mac-code/logs` | `agent.py:24` |
| `PICOCLAW` | `~/Desktop/qwen/picoclaw/build/picoclaw-darwin-arm64` | `agent.py:65` |
| `MODELS["9b"].path` | `~/models/Qwen3.5-9B-Q4_K_M.gguf` | `agent.py:71` |
| `MODELS["35b"].path` | `~/models/Qwen3.5-35B-A3B-UD-IQ2_M.gguf` | `agent.py:79` |
| `SERVER` | `http://localhost:8000` (override: `LLAMA_URL`) | `agent.py:21`, `chat.py:24` |

### MLX stack

| Symbol / usage | Path pattern | File |
|----------------|--------------|------|
| `CACHE_DIR` / cache roots | `~/.mac-code/kv-cache` (+ `blocks/`, `paged/` subdirs) | `mlx/kv_cache.py:14`, `mlx/tiered_cache.py:33`, `mlx/paged_inference.py:32`, `mlx/r2_store.py:36` |
| `CONFIG_PATH` | `~/.mac-code/r2-config.json` | `mlx/r2_store.py:35` |
| Benchmark cwd | `~/Desktop/mac-code-mlx` | `mlx/benchmark.py:76`, `mlx/agent_benchmark.py:43` |
| Extra sys.path | `~/Desktop/pico-mini` | `mlx/agent_benchmark.py:47` |
| HuggingFace model IDs | `mlx-community/Qwen3.5-9B-MLX-4bit`, etc. | `mlx/mlx_engine.py:25–26`, `mlx/benchmark.py:152` |
| GGUF model | `~/models/Qwen3.5-9B-Q4_K_M.gguf` | `mlx/benchmark.py:61`, `mlx/agent_benchmark.py:28` |

### mlx-sniper research scripts (representative)

| Path | Files |
|------|-------|
| `/Volumes/USB DISK/qwen35-35b-moe-stream` | `moe_agent_macbook.py:28`, `split_mlx_model_macbook.py:19–20` |
| `/Volumes/USB DISK/expert_fallback_*.bin` | `benchmark_fallback.py:31`, `bench_quick.py:17`, `bench_mixed.py:18`, `flash_moe.py:222` |
| `/Users/bigneek/models/...` | `split_35b_v2.py:7–8`, `split_30b.py:7–8`, `moe_agent_35b.py:11`, `moe_agent_30b.py:11` |

### cli-agent package (hardcoded defaults in engines)

| Symbol | Path | Files |
|--------|------|-------|
| `MODEL_DIR` | `/Users/bigneek/models/qwen35-35b-stream` | `engine.py:11`, `engine_next.py:11` |
| `MODEL_DIR` | `/Users/bigneek/models/qwen3-30b-stream` | `engine_30b.py:11` |
| `MLX_MODEL_DIR` / `OUTPUT_DIR` | `/Users/bigneek/models/qwen35-35b-mlx-4bit` → stream dir | `preprocess.py:7–8` |

**Recommendation (inferred):** Milestone 1 artifact writer must use the approved repo-relative layout (`benchmarks/runs/<timestamp>/`)—not prototype home-directory or machine-specific literals.

---

## 5. Direct filesystem writes

### Import-time and module-level writes (observed)

| Location | Behavior |
|----------|----------|
| `agent.py:25` | `LOGS_DIR.mkdir(parents=True, exist_ok=True)` runs at **import** |
| `mlx/kv_cache.py:15` | Creates `~/.mac-code/kv-cache` at import |
| `mlx/tiered_cache.py:34` | Creates `~/.mac-code/kv-cache/blocks` at import |
| `mlx/paged_inference.py:33` | Creates `~/.mac-code/kv-cache/paged` at import |
| `mlx/r2_store.py:37` | Creates `~/.mac-code/kv-cache` at import |

Importing these modules mutates the user's home directory without an explicit user action.

### Runtime write sites (selected, observed)

| Area | Examples | Risk |
|------|----------|------|
| Agent logging | `agent.py:39–41` append JSONL to `~/.mac-code/logs/` | Medium |
| Agent user tools | `agent.py:240–241` write file from LLM content; `1047–1054` `/save` conversation JSON | Medium–High |
| MLX KV / cache | `mlx/kv_cache.py`, `turboquant.py`, `tiered_cache.py`, `paged_inference.py` — safetensors, gzip, manifests under `~/.mac-code/kv-cache` | Medium |
| R2 local staging | `mlx/r2_store.py` compress/upload/delete under cache dir | Medium–High |
| Benchmarks | `mlx/benchmark.py:196`, `mlx/agent_benchmark.py:189` — `Path.unlink()` on cache files | Medium |
| mlx-sniper preprocess/split | Large binary expert shards under `OUTPUT_DIR` (e.g. `split_*.py`, `split_mlx_model_macbook.py`) | Medium |
| Calibration | `calibrate.py` writes `sniper_config.json`, `sniper_calibration.npz` into model dir (mlx-sniper and cli-agent copies) | Medium |
| cli-agent download | `download.py` — `snapshot_download`, preprocess writes, `config.json` | High (network + disk) |

---

## 6. Network, model loading, and execution side effects

### HTTP clients (observed)

| Module | Targets | Purpose |
|--------|---------|---------|
| `agent.py` | `{SERVER}/v1/chat/completions`, `/props`, `/health`; DuckDuckGo via `DDGS`; `https://r.jina.ai/{url}` | LLM calls, model detection, web search, page fetch |
| `chat.py` | Same llama-server OpenAI-compatible API | Streaming chat only |
| `mlx/benchmark.py`, `mlx/agent_benchmark.py` | `localhost:8000` health and completions | Benchmark driving |
| `mlx/r2_store.py` | Cloudflare R2 via `boto3` S3 API | Remote KV cache upload/download |

### In-process model loading (observed)

| Entry | Mechanism |
|-------|-----------|
| `mlx/mlx_engine.py:35–48` | `mlx_lm.load(model_id)` — downloads/loads from HuggingFace IDs in `MODELS` |
| `mlx/benchmark.py`, `mlx/agent_benchmark.py` | `mlx_lm.load('mlx-community/Qwen3.5-9B-MLX-4bit')` during benchmark section |
| `research/expert-sniper/cli-agent/.../engine*.py`, `generate.py`, `server.py` | Custom MoE engines; `engine.load()` reads hardcoded `MODEL_DIR` |
| `research/expert-sniper/mlx-sniper/moe_agent_*.py`, `flash_moe.py`, etc. | Same pattern with research paths |
| `cli-agent/.../download.py:120–121` | `huggingface_hub.snapshot_download` |

### HTTP servers (observed)

- `mlx/mlx_engine.py` — llama.cpp-compatible JSON API on configurable port (default 8000).
- `research/expert-sniper/cli-agent/.../server.py` — Ollama-compatible server; loads full model before `serve_forever()`.

### Third-party side effects on use (observed)

- `agent.py:296–330` — DuckDuckGo search libraries perform external HTTP when `quick_search()` runs.
- `agent.py:573–634` — picoclaw subprocess may perform network and shell tools internally.
- `rich` / terminal UI — clears screen, no security boundary (`agent.py:753`, `chat.py:180`).

**Recommendation (inferred):** Milestone 1 artifact writer must be model-independent: append-only schema-versioned events to `run.jsonl` plus a derived `summary.md`, with injectable clock/run ID for tests. No `mlx_lm`, `llama-server`, or outbound HTTP.

---

## 7. `agent.py` — coupled responsibilities (prototype-only)

`agent.py` (~1,388 lines) combines unrelated production concerns in one module (observed structure):

| Responsibility | Key symbols |
|----------------|-------------|
| Terminal UI | `rich` banner, `WorkingDisplay`, slash menu, streaming output |
| LLM transport | `llm_call()`, `stream_llm()`, `detect_model()`, `get_current_model()` |
| Model lifecycle | `MODELS`, `swap_model()` — pkill + spawn `llama-server` |
| Intent routing | `classify_intent()`, keyword lists, auto 9B/35B routing |
| Shell tools | `generate_shell_command()`, `run_smart_tool()`, `run_file_tool()` — **shell=True** |
| Web search | `quick_search()` — DDGS + Jina fetch |
| External agent | `picoclaw_call_live()` — subprocess to hardcoded binary |
| Filesystem logging | `log_interaction()`, `get_failure_stats()` — writes `~/.mac-code/logs` |
| Session commands | `/loop`, `/save`, `/add-dir` (includes `os.chdir`), `/bench`, grading |
| Main REPL | `main()` — orchestrates all of the above |

**Why prototype-only (inferred):** There is no separation between UI, policy, tool execution, and runtime management. Any reuse of `agent.py` as a library (as `mlx/agent_benchmark.py` does via `from agent import ...`) inherits import-time log directory creation and exposes shell/network/tool surfaces. None of this matches the fail-closed, typed, model-independent foundation described in `AGENTS.md`.

**Observed fact:** `docs/upstream/mac-code.md` already marks all imported paths as prototype-only and not the production CLI.

---

## 8. Milestone 1 allowed boundary

Source for scope: issue #3 implementation decisions and out-of-scope list (approved Milestone 0 PRD). Exact first-party paths below are **inferred** from that plan; they do not exist in the repo yet.

### Allowed first-party surfaces (inferred)

| Surface | Intended paths / artifacts | Purpose |
|---------|---------------------------|---------|
| Packaging | `pyproject.toml`, `src/mac_llm/` (or equivalent layout), package `__init__.py` | Installable `mac-llm` distribution without importing prototype roots |
| Console entry point | `[project.scripts]` → stub CLI module (e.g. `mac_llm/cli.py` or `__main__.py`) | `--help`, version, placeholder subcommands only; **no** model or server startup |
| Required docs | `docs/upstream/`, `docs/orientation/`, README updates tied to M1 | Provenance and orientation completed in M0; M1 adds only packaging/usage docs |
| Benchmark artifact writer | e.g. `mac_llm/artifacts.py` + tests | Model-independent writer that creates `benchmarks/runs/<timestamp>/run.jsonl` and `summary.md` per run; **no** inference, subprocess, or network |
| Tests | `tests/` for packaging, CLI `--help`, artifact writer | Prove install entry point and artifact contract without hardware |

#### Benchmark artifact writer contract (inferred from approved implementation plan)

The artifact writer is the only Milestone 1 surface that performs filesystem writes beyond packaging metadata. Its contract is narrower than the prototype write sites inventoried above:

| Requirement | Detail |
|-------------|--------|
| Output layout | Each run writes under `benchmarks/runs/<timestamp>/` with exactly two artifacts: `run.jsonl` (event log) and `summary.md` (human-readable rollup). |
| Event log | `run.jsonl` is **append-only**. Each line is one schema-versioned JSON event. Events are never rewritten or truncated in place. |
| Schema | Events carry an explicit schema version field so downstream readers can evolve without silent breakage. |
| Summary | `summary.md` is derived from the completed `run.jsonl` for the same run directory. |
| Determinism / testability | Run directory name (`<timestamp>`) and run ID must be **injectable** (clock and ID providers) so tests can assert exact paths and contents without wall-clock dependence or model hardware. |
| Independence | Writer accepts structured in-memory events only. It does not load models, spawn subprocesses, open network connections, or import prototype modules. |

**Observed contrast:** Prototype benchmarks (e.g. `mlx/benchmark.py`, `mlx/agent_benchmark.py`) print results to stdout and delete cache files; they do not emit schema-versioned run artifacts under a repo-relative tree.

### Explicitly excluded from Milestone 1 (from issue #3)

Do **not** implement in M1 (inferred plan boundary):

- Runtime manager, health probes, model swapping, cache restoration
- llama.cpp / MLX engine integration (`llama-server`, `mlx_engine.py`, mlx-sniper engines)
- Routing, roles, tool broker, shell/file/web tools
- External agents (picoclaw), DuckDuckGo/Jina/R2 clients
- UI beyond minimal CLI help text
- Copying or wrapping `agent.py`, `chat.py`, or imported `mlx/` / `research/` modules as production code

### Prototype paths — read-only reference

All paths listed in `docs/upstream/mac-code.md` remain **audit/reference only** through Milestone 1. New code must live outside those trees.

---

## 9. Verification notes

Static searches performed (observed):

- `pkill` — 9 matches, all catalogued above
- `shell=True` — 3 matches, all catalogued above
- `subprocess`, `os.system`, `Popen`, `HTTPServer`, `urllib`, `boto3`, `snapshot_download`, `mlx_lm.load`, `Path.home`, `expanduser`, `.mkdir`, `.write`

Cited files and line numbers exist in the worktree at commit under review. No Python module from imported scope was executed during this audit.

---

## 10. Related documents

- Import provenance: `docs/upstream/mac-code.md`
- Runtime map (separate PR): `docs/orientation/runtime-map.md` (issue #4)
- Parent PRD: issue #3
