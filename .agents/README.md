# Agent workflow files

This directory contains repo-local agent coordination docs and state.

The active protocol is:

```text
manual supervisor agent session
  → supervisor-next.sh waits for ready issue
  → supervisor delegates issue-worker subagent
  → issue-worker owns one worktree/PR lifecycle
  → codex-loop.sh blocks through Codex review/fix cycles
  → PR marked ready-for-human
  → human merges
```

Planning is manual with Codex plus GrillMe / `to-prd` / `to-issues`.

Execution is label-driven:

- `agent:ready` + `worker:claude`
- `agent:ready` + `worker:cursor`

State files are written under `.agents/state/`. They are operational artifacts, not product docs.

Role-specific workflow details are in:

```text
.agents/ROLE_WORKFLOWS.md
```
