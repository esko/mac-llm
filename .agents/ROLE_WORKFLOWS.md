# Agent role workflows

This file contains the operational workflow details that are intentionally kept out of `AGENTS.md`.

Read `AGENTS.md` first. Then read the relevant section here for your current role.

## Planning mode

Planning is controlled manually by the human with Codex and planning skills.

When asked to plan a milestone:

1. Use GrillMe to challenge the plan if available.
2. Use `to-prd` for non-trivial milestone behavior.
3. Use `to-issues` to create small implementation issues.
4. Create issues only for the current approved milestone unless explicitly told otherwise.
5. Prefer `agent:draft` by default.
6. Add `agent:ready` only when the issue should launch implementation.
7. Add exactly one implementation worker label: `worker:claude` or `worker:cursor`.
8. Do not implement during planning.

Each implementation issue should include:

* goal
* acceptance criteria
* tests or commands expected
* likely files to touch
* out of scope
* stop condition
* recommended worker
* Codex review focus

## Supervisor mode

When the user says “start supervisor mode”, “watch for open issues”, “claim issues and work them”, or similar, act as a supervisor.

The supervisor must not implement issues directly unless taking over an escalated PR.

Supervisor loop:

1. Run:

```bash
./scripts/agent/supervisor-next.sh <worker>
```

Use the current supervisor identity as `<worker>`, usually `claude`, `cursor`, or `codex`.

2. The script blocks cheaply using `gh` until a matching issue is available or supervisor attention is needed.
3. When it exits with a delegated issue/worktree, launch an issue-worker subagent for that task.
4. The issue-worker owns that issue, worktree, branch, PR, and Codex review loop.
5. The supervisor must not edit the issue-worker's worktree.
6. After launching the issue-worker, immediately run `supervisor-next.sh` again to watch for more work.
7. Monitor active workers from GitHub labels, PR status, and `.agents/state/` summaries.
8. Steer only if a worker reports `agent:needs-supervisor`, stalls, or asks for a decision.
9. Never merge.

Default concurrency is intentionally low. Respect `AGENT_MAX_ACTIVE_WORKERS` if set; default is `2` active non-ready PRs per worker.

## Issue-worker mode

An issue-worker owns exactly one issue, one worktree, one branch, and one PR lifecycle.

Required lifecycle:

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
12. Push the branch.
13. Open or update a PR.
14. Run:

```bash
./scripts/agent/codex-loop.sh <pr-number>
```

15. If Codex reports blocking findings, fix only blocking findings and directly related test gaps, push, and rerun the loop.
16. Repeat until the PR is marked `agent:ready-for-human` or escalation is required.
17. Stop. Never merge.

No two agents may work in the same worktree.

## Codex review loop

Implementation PRs must go through Codex before human review.

`./scripts/agent/codex-loop.sh <pr-number>`:

* requests Codex review with a unique request id
* waits without a script-level timeout
* detects Codex PR comments, PR reviews, and inline review comments
* writes feedback under `.agents/state/codex-pr-<pr>/`
* labels the PR according to the result
* exits with one of:
  * `0`: Codex appears clean; PR marked `agent:ready-for-human`.
  * `20`: blocking feedback found; fix and rerun the loop.
  * `21`: ambiguous feedback; inspect, fix if needed, then rerun or escalate.
  * `40`: review loop limit reached; supervisor escalation created.

Issue-workers must not bypass this loop.

## Supervisor escalation

Issue-workers should not loop forever.

Escalate to supervisor if:

* implementation is stuck after 2 serious attempts
* CI remains failing after 2 fix attempts
* Codex still has blocking findings after 3 review loops
* Codex feedback is ambiguous more than once
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

* give targeted instructions and return the PR to the worker
* take over the PR branch/worktree
* close/replan the PR
* ask the human for a decision

If the supervisor takes over, it must label the PR `agent:supervisor-taking-over`, work only on that PR branch/worktree, rerun the Codex loop, and still never merge.
