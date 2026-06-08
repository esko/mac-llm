# Agent role assignment

`mac-llm` separates three configurable top-level roles and one implementor-managed subagent role.

```text
supervisor
  Highest-reasoning coordination/planning role. Works with the human on planning, PRDs, and issue creation; assigns ready issues to an implementor; monitors high-level progress; handles escalation and takeover.

implementor
  Implementation harness/provider. Watches for issues assigned to it, claims/delegates them, creates worktrees, launches and monitors its own issue-worker subagents, verifies their results, and owns implementation PRs until ready or escalated.

issue-worker
  Implementor-managed subagent. Owns one issue/worktree/branch/PR lifecycle. Implements the issue, runs the finish/review loop, fixes reviewer feedback, and escalates if stuck.

reviewer
  Independent PR review provider. Reviews implementation PRs before human review. Does not mutate the PR branch unless explicitly configured by the human.
```

Do not configure issue-workers as a separate top-level provider role. They belong to the implementor harness.

These roles are independent. The same provider may fill more than one role, but it does not have to.

## Examples

```bash
# Claude supervises, Cursor implementor manages issue-workers, Codex reviews
export AGENT_SUPERVISOR=claude
export AGENT_IMPLEMENTOR=cursor
export AGENT_REVIEWER=codex

# Claude supervises/reviews, Cursor implements
export AGENT_SUPERVISOR=claude
export AGENT_IMPLEMENTOR=cursor
export AGENT_REVIEWER=claude

# Codex helps plan/supervise, Claude implements, Cursor/Bugbot reviews
export AGENT_SUPERVISOR=codex
export AGENT_IMPLEMENTOR=claude
export AGENT_REVIEWER=cursor
```

## Configuration file

Optional local role configuration may live at:

```text
.agents/agent.env
```

Use `.agents/agent.env.example` as a template.

Scripts source `.agents/agent.env` automatically when present. Shell environment variables should be treated as overrides. New docs/scripts use `AGENT_IMPLEMENTOR`; `AGENT_IMPLEMENTER` remains a legacy alias.

## Core variables

```bash
AGENT_SUPERVISOR=claude
AGENT_IMPLEMENTOR=cursor
AGENT_REVIEWER=codex
AGENT_BASE_BRANCH=main
AGENT_WATCH_POLL_SECONDS=300
AGENT_MAX_ACTIVE_WORKERS=2
AGENT_MAX_REVIEW_LOOPS=3
AGENT_MAX_AMBIGUOUS_REVIEWS=1
AGENT_ALLOW_WORKER_ANY=1
```

`AGENT_IMPLEMENTOR` maps to GitHub issue labels:

```text
worker:<agent>
```

Generic issues may use:

```text
worker:any
```

Implementors claim explicit `worker:<AGENT_IMPLEMENTOR>` issues first. If none are available and `AGENT_ALLOW_WORKER_ANY=1` (default), they may claim `worker:any` issues. When a generic issue is claimed, the script adds the concrete `worker:<implementor>` label and removes `worker:any`.

A Cursor implementor session watches Cursor-assigned issues by running:

```bash
AGENT_IMPLEMENTOR=cursor ./scripts/agent/implementor-next.sh
```

or explicitly:

```bash
./scripts/agent/implementor-next.sh cursor
```

The supervisor assigns work by creating or labeling issues with `agent:ready + worker:<implementor>`. It may use `agent:ready + worker:any` for work that any available implementor may claim. It does not have to be the same provider as the implementor.

## Reviewer providers

Reviewer behavior is configured by files under:

```text
.agents/reviewers/
```

Each reviewer has:

```text
<reviewer>.env
<reviewer>-request.md
```

The `.env` file defines:

```bash
REVIEWER_DISPLAY_NAME="Codex"
REVIEWER_AUTHOR_REGEX='codex|openai'
REVIEWER_LABEL='review:codex'
REVIEWER_TRIGGER_LABEL='review:requested'
REVIEWER_REQUEST_TEMPLATE='.agents/reviewers/codex-request.md'
```

The request template is posted as a GitHub PR comment by `review-loop.sh`.

Built-in reviewers:

```text
codex
claude
cursor
```

To add another reviewer, create a new pair of files and set:

```bash
AGENT_REVIEWER=<name>
```

## Role separation rules

* A supervisor must not implement unless taking over an escalated PR.
* An implementor monitors and manages its own issue-worker subagents; it should not do supervisor planning unless explicitly asked.
* An issue-worker must not claim a second issue or edit another worker's worktree.
* An implementor must not review its own PR as the final review gate.
* A reviewer must not mutate the PR branch unless explicitly configured as an autofix reviewer by the human.
* If a provider is out of tokens or unavailable, switch only the affected role. Example: if Codex review is unavailable, set `AGENT_REVIEWER=claude`; do not automatically make Claude an implementor.
* Human merge approval is always required.
