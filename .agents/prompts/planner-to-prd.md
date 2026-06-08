# Planner to PRD prompt

Use this when converting an approved milestone idea into a concise PRD.

Rules:

- Use GrillMe first if available to challenge assumptions and scope.
- Keep the PRD focused on the current milestone only.
- Do not add future milestone implementation details unless they affect current boundaries.
- Preserve the project rule: `mac-llm` is a 24 GB Apple Silicon Mac Mini local-agent runtime, not a model zoo, frontend, or generic agent platform.
- Define success in terms of command/test/artifact proof.
- Include out-of-scope items.
- Do not implement.

Output:

```text
Title
Context
Goal
Non-goals
Acceptance criteria
Test/artifact expectations
Risks / stop conditions
```
