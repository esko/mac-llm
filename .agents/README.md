# Agent workflow docs

This directory contains repo-local workflow support for `mac-llm` agents.

Start here:

```text
AGENTS.md
.agents/ROLE_ASSIGNMENT.md
.agents/ROLE_WORKFLOWS.md
```

Role split:

```text
supervisor
  highest-reasoning coordinator; plans with the human, creates PRDs/issues when asked, assigns work, handles escalation/takeover

implementor
  implementation harness; watches issues assigned to it, creates worktrees, launches/monitors issue-worker subagents, verifies completion

issue-worker
  implementor-managed subagent; does one issue/worktree/branch/PR lifecycle

reviewer
  independent PR review provider selected by AGENT_REVIEWER
```

Typical flow:

```text
human + supervisor + planning skills
  → PRD / issues
  → agent:ready + worker:<implementor>
  → or agent:ready + worker:any for generic implementor work
  → implementor-next.sh claims issue + creates worktree/task
  → implementor launches issue-worker subagent
  → issue-worker implements and runs finish-pr.sh
  → review-loop.sh waits for configured reviewer
  → ready-for-human or needs-supervisor
```

State files are written under `.agents/state/` and should generally not be committed except `.gitkeep`.
