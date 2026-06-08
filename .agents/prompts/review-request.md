# Review request prompt

Use this when preparing or auditing a configured PR reviewer request.

The active reviewer is selected by:

```bash
AGENT_REVIEWER=<codex|claude|cursor|custom>
```

Reviewer request templates live under:

```text
.agents/reviewers/<reviewer>-request.md
```

The reviewer should check the PR against:

- `AGENTS.md`
- `.agents/ROLE_WORKFLOWS.md`
- `.agents/ROLE_ASSIGNMENT.md`
- the linked issue acceptance criteria
- current milestone scope

The reviewer should focus on blocking correctness, safety, scope, test, and benchmark/artifact issues. Style comments should be non-blocking unless they affect maintainability or correctness.
