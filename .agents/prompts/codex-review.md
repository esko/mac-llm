# Codex reviewer prompt

Compatibility prompt for Codex-specific review requests.

Prefer the generic reviewer system:

```bash
AGENT_REVIEWER=codex ./scripts/agent/review-loop.sh <pr-number>
```

Reviewer request templates live under:

```text
.agents/reviewers/
```
