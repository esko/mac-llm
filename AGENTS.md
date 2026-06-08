# AGENTS.md

## Project rule

`mac-llm` is a 24 GB Apple Silicon Mac Mini local-agent runtime. Optimize for small, tested, benchmarkable steps. Do not expand scope into a model zoo, frontend, generic agent platform, or broad research playground.

The high-level product architecture belongs in the project plan. This file is the compact root contract for agents working in this repo.

Detailed role and workflow docs live in:

```text
.agents/ROLE_ASSIGNMENT.md
.agents/ROLE_WORKFLOWS.md
```

Agents must read those files before entering planning, supervisor, implementor, issue-worker, review-loop, or escalation mode.

## Roles

`mac-llm` uses three configurable top-level roles plus implementor-managed subagents:

* **Supervisor** — highest-reasoning coordinating role. Plans with the human, uses GrillMe / `to-prd` / `to-issues` when asked, creates or refines PRDs/issues manually with human input, assigns ready issues to an implementor, monitors high-level progress, and handles escalation/takeover.
* **Implementor** — implementation harness/provider. Watches for issues assigned to it, claims/delegates those issues, creates worktrees, launches and monitors its own issue-worker subagents, verifies worker results, and owns implementation PRs until ready for human review or supervisor escalation.
* **Issue-worker** — implementor-managed subagent. Owns exactly one issue, one worktree, one branch, and one PR lifecycle. It implements the change, runs the finish/review loop, fixes reviewer feedback, and escalates if stuck.
* **Reviewer** — independent PR review provider. Reviews implementation PRs before human review. Default is Codex, but Claude/Cursor/custom reviewers may be configured.

Do not confuse implementor with issue-worker. The implementor manages issue-workers; issue-workers do the actual one-worktree implementation.

## Core workflow

* Work from a GitHub issue.
* Use one dedicated worktree per issue/PR.
* Keep changes atomic: one concern per branch/PR.
* Use TDD: write or update tests before implementation when practical.
* Use concise PRDs for non-trivial behavior changes.
* Use available Matt Pocock/TDD skills when helpful.
* Push branches and open/update PRs automatically.
* Request configured reviewer review before human review.
* Do not merge PRs automatically. Human approval is required.
* Prefer small PRs that can be reviewed quickly.

## Planning and launch

Planning is manual/high-control with the human plus the supervisor, usually Codex, GrillMe, `to-prd`, and `to-issues`.

The supervisor may create or refine PRDs and GitHub issues when explicitly asked. It should usually create `agent:draft` issues first. Launchable implementation issues have:

```text
agent:ready + worker:<implementor>
```

Use `worker:any` for issues that any available implementor may claim. Implementors prefer their explicit queue first, then fall back to `worker:any` unless `AGENT_ALLOW_WORKER_ANY=0`.

Common examples:

```text
agent:ready + worker:claude
agent:ready + worker:cursor
agent:ready + worker:any
```

When the user says “start supervisor mode”, the supervisor should plan/assign/monitor and use `.agents/ROLE_WORKFLOWS.md`.

When the user says “start implementor mode”, “watch for open issues”, “claim issues assigned to you”, or similar, the implementor should run the implementor loop from `.agents/ROLE_WORKFLOWS.md`.

The supervisor must not run the implementor queue unless the human explicitly asks it to act as implementor. The implementor must not do planning unless explicitly asked.

## Labels

Issue launch labels:

* `agent:draft` — planned but not launchable yet.
* `agent:ready` — ready for an implementor to claim.
* `worker:any` — open to any available implementor. Implementors claim their own queue first, then `worker:any`.
* `worker:claude` — assigned to Claude implementor.
* `worker:cursor` — assigned to Cursor implementor.
* `worker:codex` — assigned to Codex for planning/review-style work, not default implementation.

Lifecycle labels:

* `agent:claimed`
* `agent:delegated`
* `agent:implementing`
* `agent:review-loop`
* `agent:needs-supervisor`
* `agent:worker-stalled`
* `agent:worker-incomplete`
* `agent:review-loop-limit`
* `agent:takeover-requested`
* `agent:supervisor-taking-over`
* `agent:ready-for-human`

Agents must not invent unlabeled work. Implementors claim only open issues labeled `agent:ready` and either `worker:<implementor>` or `worker:any`. Explicit `worker:<implementor>` issues take priority over `worker:any`.

## Role configuration

Supervisor, implementor, and reviewer are independent roles. Configure them with environment variables or `.agents/agent.env` as described in `.agents/ROLE_ASSIGNMENT.md`.

Common examples:

```bash
# Claude supervises, Cursor implements, Codex reviews
AGENT_SUPERVISOR=claude AGENT_IMPLEMENTOR=cursor AGENT_REVIEWER=codex

# Claude supervises/reviews, Cursor implements
AGENT_SUPERVISOR=claude AGENT_IMPLEMENTOR=cursor AGENT_REVIEWER=claude
```

`AGENT_IMPLEMENTER` is accepted as a legacy alias for `AGENT_IMPLEMENTOR`, but new docs/scripts should use `AGENT_IMPLEMENTOR`.

If one provider is unavailable or out of tokens, switch only that role. Do not implicitly make the reviewer an implementor.

## Required scripts

Agent workflow scripts live in:

```text
scripts/agent/
```

Important entrypoints:

```bash
./scripts/agent/implementor-next.sh [implementor]
./scripts/agent/finish-pr.sh <issue-number>
./scripts/agent/verify-worker-result.sh <issue-number>
./scripts/agent/review-loop.sh <pr-number>
./scripts/agent/escalate-to-supervisor.sh <pr-number> "<reason>"
./scripts/agent/mark-ready-for-human.sh <pr-number>
```

`supervisor-next.sh` is a legacy compatibility wrapper for `implementor-next.sh`. New docs and agents should use `implementor-next.sh`.

Do not bypass these scripts unless explicitly instructed by the human.

## PR completion gate

Issue-workers must not create a PR and stop manually. After implementation and commits, they must run:

```bash
./scripts/agent/finish-pr.sh <issue-number>
```

`finish-pr.sh` pushes the branch, creates or finds the PR, labels it, and runs the blocking review loop. The issue-worker is not done until this script exits `0` or the work is escalated to supervisor.

## Worker completion verification

When an issue-worker reports that it is done, the implementor must verify the result before accepting completion or delegating replacement work:

```bash
./scripts/agent/verify-worker-result.sh <issue-number>
```

The verifier fails if no PR exists for the issue branch, or if a PR exists but is not `agent:ready-for-human` and has not intentionally escalated to supervisor. A worker is not done merely because it says it is done.

If verification needs judgment, the implementor should label/leave the work for supervisor attention rather than silently taking over beyond its role.

## Commits and PRs

* Use conventional commits: `feat:`, `fix:`, `test:`, `docs:`, `refactor:`, `chore:`.
* Commit working increments. Avoid giant end-of-task commits.
* PR description must include:
  * linked issue
  * what changed
  * how to test
  * benchmark/artifact path if relevant
  * known limitations
  * next smallest step

## Coding standards

* Keep code boring, typed where practical, and easy to test.
* Prefer deterministic logic over model calls.
* Fail closed on unknown role, target, tool, path, or policy.
* Avoid broad refactors unless needed for the current issue.
* Keep docs concise; do not duplicate the implementation plan.
* Use bash for repo automation scripts.
* Use fish-compatible commands only when writing user-facing terminal instructions for the human.

## Safety

* No raw shell/file access for external agents.
* No direct writes without policy/approval when implementing tool broker paths.
* Use hash-checked edits for file modification paths where applicable.
* Do not expose secrets or private files in external briefs.
* Log tool calls, runtime decisions, benchmark results, and external-cost estimates where relevant.
* Never expose `.env`, private keys, tokens, credentials, `.ssh`, `.gnupg`, `.netrc`, or large private dumps.
* When scripts post multi-line GitHub comments, use literal body files (`--body-file`) rather than inline shell strings.
