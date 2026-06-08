# Agent role workflows

This file contains operational workflow details that are intentionally kept out of `AGENTS.md`.

Read `AGENTS.md` first, then `.agents/ROLE_ASSIGNMENT.md`, then the relevant section here for your current role.

## Planning mode

Planning is controlled manually by the human with the supervisor agent, usually using Codex plus planning skills.

When asked to plan a milestone:

1. Use GrillMe to challenge the plan if available.
2. Use `to-prd` for non-trivial milestone behavior.
3. Use `to-issues` to create small implementation issues.
4. Create issues only for the current approved milestone unless explicitly told otherwise.
5. Prefer `agent:draft` by default.
6. Add `agent:ready` only when the issue should launch implementation.
7. Add exactly one worker label. Use `worker:claude` / `worker:cursor` for targeted work, or `worker:any` for work that any available implementor may claim.
8. Do not implement during planning.

Each implementation issue should include:

* goal
* acceptance criteria
* tests or commands expected
* likely files to touch
* out of scope
* stop condition
* recommended implementor
* review focus

## Supervisor mode

When the user says “start supervisor mode”, “plan the milestone”, “create PRD/issues”, or similar, act as supervisor.

The supervisor is the highest-reasoning coordination role. It plans with the human, creates PRDs/issues when asked, assigns launchable issues to the implementor, monitors high-level progress, handles escalations, and may take over failed work.

The supervisor must not implement issues directly unless taking over an escalated PR. The supervisor also does not normally run the issue queue watcher; that belongs to the implementor.

Supervisor responsibilities:

1. Work with the human on PRDs/issues using GrillMe, `to-prd`, and `to-issues` when requested.
2. Assign launchable issues by adding `agent:ready + worker:<implementor>` or `agent:ready + worker:any` for generic work.
3. Check status with:

```bash
./scripts/agent/status.sh [implementor]
```

4. Handle `agent:needs-supervisor`, `agent:worker-incomplete`, and `agent:review-loop-limit` before creating or assigning more work.
5. If taking over a PR, label it `agent:supervisor-taking-over`, work only on that PR branch/worktree, rerun the review loop, and never merge.
6. Never silently edit an implementor/issue-worker worktree unless taking over an escalated PR.

## Implementor mode

When the user says “start implementor mode”, “watch for open issues”, “claim issues assigned to you”, “work assigned issues”, or similar, act as implementor.

The implementor is the implementation harness/provider. It watches for issues assigned to it, claims/delegates each issue, creates one worktree per issue, launches issue-worker subagents, monitors them, verifies completion, and escalates to supervisor when needed.

Implementor loop:

1. Run:

```bash
./scripts/agent/implementor-next.sh [implementor]
```

Use the implementor identity as `[implementor]`, or omit it when `AGENT_IMPLEMENTOR` is set in `.agents/agent.env`. `AGENT_IMPLEMENTER` is accepted as a legacy alias.

2. The script blocks cheaply using `gh` until a matching issue is available, implementor attention is needed, or supervisor attention is needed.
3. When it exits with a delegated issue/worktree, launch an issue-worker subagent for that worktree/task file.
4. The implementor must not edit the issue-worker worktree directly unless taking over within its own harness after the worker has stopped.
5. After launching the issue-worker, immediately run `implementor-next.sh` again when concurrency allows.
6. When an issue-worker reports done, run:

```bash
./scripts/agent/verify-worker-result.sh <issue-number>
```

7. If verification fails because the worker stopped early, relaunch or steer the same worker/worktree.
8. If verification or the worker requests supervisor judgment, label/leave it as `agent:needs-supervisor` and stop touching that worktree until the supervisor decides.
9. Never merge.

Default concurrency is intentionally low. Respect `AGENT_MAX_ACTIVE_WORKERS` if set; default is `2` active non-ready PRs per implementor.

An implementor must not trust a subagent's final message by itself. The worker is only complete if `verify-worker-result.sh` confirms that a PR exists and is ready for human review, or the worker intentionally escalated.

`supervisor-next.sh` exists only as a legacy wrapper for `implementor-next.sh`; new agents should use `implementor-next.sh`.

## Issue-worker mode

The issue-worker is the implementor-managed subagent that owns the actual task. An issue-worker owns exactly one issue, one worktree, one branch, and one PR lifecycle.

Required issue-worker lifecycle:

1. `cd` into the assigned worktree.
2. Read `.agents/state/current-task.md`.
3. Read `AGENTS.md`.
4. Read the linked GitHub issue.
5. Restate the acceptance criteria.
6. Identify the smallest testable change.
7. Use TDD where practical.
8. Implement only that issue.
9. Do not pull in future milestone work.
10. Run relevant tests.
11. Commit working increments.
12. Run the mandatory finish gate:

```bash
./scripts/agent/finish-pr.sh <issue-number>
```

13. `finish-pr.sh` pushes the branch, opens or finds the PR, and runs the review loop.
14. If it exits `20` or `21`, inspect `.agents/state/`, fix only reviewer feedback and directly related test gaps, commit, and rerun `finish-pr.sh`.
15. Repeat until `finish-pr.sh` exits `0` or escalation is required.
16. Final response to the implementor must include the PR number and the result of `finish-pr.sh`. If no PR exists, the issue-worker is not done.
17. Stop. Never merge.

No two agents may work in the same worktree.

## Worker completion verifier

`./scripts/agent/verify-worker-result.sh <issue-number>` is the implementor-side guardrail. Run it whenever an issue-worker says an issue is done.

It checks the expected issue branch and exits with:

* `0`: PR exists and is labeled `agent:ready-for-human`.
* `22`: no PR exists for the issue branch; worker stopped too early.
* `23`: PR exists but is incomplete; worker likely skipped or failed the finish/review loop.
* `30`: PR intentionally needs supervisor attention.

If verification exits `22` or `23`, relaunch/steer the issue-worker in the same worktree with instructions to run:

```bash
./scripts/agent/finish-pr.sh <issue-number>
```

If verification exits `30`, do not keep grinding. The implementor should surface the escalation for the supervisor to decide whether to advise, relaunch, take over, replan, or ask the human.

## Review loop

Implementation PRs must go through the configured reviewer before human review. The reviewer is selected with `AGENT_REVIEWER` and configured under `.agents/reviewers/`.

`./scripts/agent/finish-pr.sh <issue-number>` is the preferred issue-worker entrypoint after implementation. It creates/finds the PR and then calls `review-loop.sh`.

`./scripts/agent/review-loop.sh <pr-number>`:

* requests review with a unique request id
* waits without a script-level timeout
* detects configured reviewer PR comments, PR reviews, and inline review comments
* writes feedback under `.agents/state/review-pr-<pr>/`
* labels the PR according to the result
* exits with one of:
  * `0`: reviewer appears clean; PR marked `agent:ready-for-human`.
  * `20`: blocking feedback found; fix and rerun the loop.
  * `21`: ambiguous feedback; inspect, fix if needed, then rerun or escalate.
  * `40`: review loop limit reached; supervisor escalation created.

Issue-workers must not bypass this loop. In normal issue-worker flow, they should run `finish-pr.sh` rather than calling `gh pr create` and `review-loop.sh` as separate manual steps.

### GitHub comment safety

Scripts must post multi-line GitHub comments with literal body files, not inline `--body` strings or command substitution. Use `gh pr comment --body-file <file>` so Markdown backticks, code fences, and shell-looking text are not reinterpreted by the shell.

## Supervisor escalation

Issue-workers should not loop forever.

Escalate to supervisor if:

* implementation is stuck after 2 serious attempts
* CI remains failing after 2 fix attempts
* reviewer still has blocking findings after 3 review loops
* reviewer feedback is ambiguous more than once
* the issue requires broader scope than allowed
* acceptance criteria conflict
* required runtime/tooling is unavailable

To escalate, run:

```bash
./scripts/agent/escalate-to-supervisor.sh <pr-number> "<reason>"
```

Then stop.

After escalation, the issue-worker must not continue editing that worktree or PR branch.

The supervisor may:

* give targeted instructions and return the PR to the implementor/worker
* take over the PR branch/worktree
* close/replan the PR
* ask the human for a decision

If the supervisor takes over, it must label the PR `agent:supervisor-taking-over`, work only on that PR branch/worktree, rerun the review loop, and still never merge.
