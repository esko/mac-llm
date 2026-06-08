# CLAUDE.md

Read `AGENTS.md` first. It is the source of truth for repository workflow.

When the user asks to “watch issues”, “claim issues”, or “start supervisor mode”, act as a supervisor:

```bash
./scripts/agent/supervisor-next.sh claude
```

When `supervisor-next.sh` exits with a delegated worktree, launch the `issue-worker` subagent with the issue number, worktree, branch, and task file it printed. Do not implement in the supervisor context unless taking over an escalated PR.

The issue-worker owns the full lifecycle for one issue:

```text
issue → worktree → implementation → PR → Codex loop → ready-for-human
```

Never merge.
