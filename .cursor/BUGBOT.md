# Cursor Bugbot rules for mac-llm

Focus on serious issues only.

Flag as blocking:

- milestone scope leakage
- missing tests for new behavior
- unsafe shell/file behavior
- uncontrolled external calls
- runtime process leaks
- benchmark artifacts that can silently pass despite failure
- changes that violate `AGENTS.md`

Do not nitpick formatting. Do not request broad refactors unless required for correctness or safety.
