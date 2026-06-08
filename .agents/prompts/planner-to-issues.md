# Planner to issues prompt

Use this after the milestone PRD is approved.

Create small GitHub issues for the current milestone only.

Issue rules:

- Each issue should be one small PR.
- Each issue should be independently testable when practical.
- Each issue must have a stop condition.
- Each issue must produce at least one of:
  - command that runs locally
  - test proving pure logic
  - artifact showing real success or failure
- Default label: `agent:draft`.
- Add `agent:ready` only if the human explicitly wants implementation to launch.
- Add exactly one worker label:
  - `worker:claude` for non-trivial implementation/debugging
  - `worker:cursor` for small bounded cleanup/tests/docs
- Do not create future milestone issues unless explicitly asked.
- Do not implement.

Each issue body should include:

```text
## Goal

## Context

## Acceptance criteria

## Tests / commands

## Likely files

## Out of scope

## Stop condition

## Codex review focus
```
