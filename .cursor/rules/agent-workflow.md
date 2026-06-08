# mac-llm agent workflow

Read `AGENTS.md` first.

When asked to watch issues, claim issues, or work autonomously, act as a supervisor unless explicitly assigned to a single issue/worktree.

Supervisor mode:

1. Run:

```bash
./scripts/agent/supervisor-next.sh cursor
```

2. When the script exits with a delegated issue/worktree, start a separate issue-worker/agent session for that worktree.
3. Do not implement directly in the supervisor context.
4. Immediately resume watching for more work.
5. Monitor `agent:needs-supervisor` and `agent:ready-for-human` labels.

Issue-worker mode:

1. Work only in the assigned worktree.
2. Read `.agents/state/current-task.md`.
3. Implement only that issue.
4. Use TDD where practical.
5. Open/update PR.
6. Run `./scripts/agent/codex-loop.sh <pr-number>`.
7. Fix Codex blocking feedback and rerun until ready for human review.
8. Never merge.

No two agents may work in the same worktree.
