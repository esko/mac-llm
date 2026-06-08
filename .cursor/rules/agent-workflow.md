# mac-llm agent workflow

Follow `AGENTS.md` and `.agents/ROLE_WORKFLOWS.md`.

Cursor may be used as supervisor, implementor, issue-worker, or reviewer depending on role assignment.

## Supervisor mode

The supervisor plans with the human, creates PRDs/issues when asked, and assigns implementation by labeling issues:

```text
agent:ready + worker:<implementor>
```

The supervisor does not normally run the implementor issue watcher or edit implementor worktrees.

## Implementor mode

The implementor watches issues assigned to it and manages issue-worker subagents:

```bash
./scripts/agent/implementor-next.sh [implementor]
```

When delegated a worktree, launch/manage an issue-worker subagent for that task, and instruct it to use the `/tdd` skill (red-green-refactor) for implementation. Verify completion with:

```bash
./scripts/agent/verify-worker-result.sh <issue-number>
```

## Issue-worker mode

Each issue-worker owns one issue/worktree/branch/PR lifecycle.

Use the `/tdd` skill (red-green-refactor) for implementation: write/extend tests first, watch them fail, then implement. (Pure-docs issues are exempt.)

Required finish step after implementation:

```bash
./scripts/agent/finish-pr.sh <issue-number>
```

Do not report done unless the PR exists and is `agent:ready-for-human`, or the work was escalated to supervisor.

## Reviewer mode

When acting as reviewer, review only. Do not push code unless explicitly configured for autofix by the human.

Never merge.
