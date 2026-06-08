# AGENTS.md

## Project rule

`mac-llm` is a 24 GB Apple Silicon Mac Mini local-agent runtime. Optimize for small, tested, benchmarkable steps. Do not expand scope into a model zoo, frontend, generic agent platform, or broad research playground.

The high-level product architecture belongs in the project plan. This file is the compact root contract for agents working in this repo.

Detailed workflow roles live in:

```text
.agents/ROLE_WORKFLOWS.md
```

Agents must read that file before entering planning, supervisor, issue-worker, Codex review-loop, or escalation mode.

## Core workflow

* Work from a GitHub issue.
* Use one dedicated worktree per issue/PR.
* Keep changes atomic: one concern per branch/PR.
* Use TDD: write or update tests before implementation when practical.
* Use concise PRDs for non-trivial behavior changes.
* Use available Matt Pocock/TDD skills when helpful.
* Push branches and open/update PRs automatically.
* Request Codex review before human review.
* Do not merge PRs automatically. Human approval is required.
* Prefer small PRs that can be reviewed quickly.

## Launch and role docs

Planning is manual/high-control with Codex plus GrillMe, `to-prd`, and `to-issues`.

Implementation is label-driven:

```text
agent:ready + worker:claude
agent:ready + worker:cursor
```

When the user says “start supervisor mode”, “watch for open issues”, “claim issues and work them”, or similar, follow `.agents/ROLE_WORKFLOWS.md` and start the supervisor loop.

The supervisor must delegate implementation to issue-worker subagents. It must not implement directly unless taking over an escalated PR.

## Labels

Issue launch labels:

* `agent:draft` — planned but not launchable yet.
* `agent:ready` — ready for a worker to claim.
* `worker:claude` — intended for Claude issue-workers.
* `worker:cursor` — intended for Cursor issue-workers.
* `worker:codex` — intended for Codex planning/review work, not default implementation.

Lifecycle labels:

* `agent:claimed`
* `agent:delegated`
* `agent:implementing`
* `agent:codex-loop`
* `agent:needs-supervisor`
* `agent:worker-stalled`
* `agent:review-loop-limit`
* `agent:takeover-requested`
* `agent:supervisor-taking-over`
* `agent:ready-for-human`

Agents must not invent unlabeled work. Claim only open issues labeled `agent:ready` and the worker label matching the current supervisor.

## Required scripts

Agent workflow scripts live in:

```text
scripts/agent/
```

Important entrypoints:

```bash
./scripts/agent/supervisor-next.sh <worker>
./scripts/agent/codex-loop.sh <pr-number>
./scripts/agent/escalate-to-supervisor.sh <pr-number> "<reason>"
./scripts/agent/mark-ready-for-human.sh <pr-number>
```

Do not bypass these scripts unless explicitly instructed by the human.

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
