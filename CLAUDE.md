# CLAUDE.md

Follow `AGENTS.md` first.

Claude may be used as supervisor, implementor, reviewer, or more than one role, depending on `.agents/agent.env` / environment variables.

## Supervisor mode

When acting as supervisor, do not implement directly unless taking over an escalated PR. Plan with the human, create PRDs/issues when asked, and assign work by labeling issues:

```text
agent:ready + worker:<implementor>
```

Use status checks rather than editing implementor worktrees:

```bash
./scripts/agent/status.sh [implementor]
```

Handle `agent:needs-supervisor`, `agent:worker-incomplete`, and `agent:review-loop-limit`.

## Implementor mode

When acting as implementor, watch issues assigned to your implementor identity and manage issue-worker subagents:

```bash
./scripts/agent/implementor-next.sh [implementor]
```

When `implementor-next.sh` exits with a delegated worktree, launch an `issue-worker` subagent with the issue number, worktree, branch, and task file it printed.

Do not edit the issue-worker worktree while it is active. When the worker reports done, verify it:

```bash
./scripts/agent/verify-worker-result.sh <issue-number>
```

If verification fails, relaunch or steer the same issue-worker/worktree. If supervisor attention is requested, stop and surface it to the supervisor.

## Issue-worker mode

When acting as issue-worker, own exactly one issue/worktree/branch/PR lifecycle and run:

```bash
./scripts/agent/finish-pr.sh <issue-number>
```

before reporting done.

## Reviewer mode

When acting as reviewer, review only. Do not push commits or mutate the PR branch unless the human explicitly asks for reviewer autofix.

Never merge.
