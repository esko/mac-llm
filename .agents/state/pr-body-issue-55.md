Closes #55

## What changed

- Added dry-run consultation brief rendering (`render_dry_run_consultation_brief`, `ExternalConsultationDryRun`) with no network I/O under default policy.
- Added fail-closed redaction for sensitive paths and full-repo dump context refs before brief construction.
- Added brokered-tools-only enforcement for external agents against M10 `KNOWN_TOOLS` and per-target allowlists.
- Added `ExternalCostLedger.record_dry_run` for dry-run cost-ledger entries with full schema fields.
- Added `validate_consultation_shape` on `ExternalAgentsGate` so render-only paths validate structure without policy send checks.

## How to test

```bash
pytest tests/test_external_brief.py
pytest
```

## Benchmark/artifact path

N/A — pure logic, no network I/O.

## Known limitations

- Redaction is denylist-based; no content scanning of brokered tool output yet.
- Dry-run ledger is in-memory only; no persistence.

## Next smallest step

- Milestone 12 router may consume dry-run briefs and ledger entries when external consultation is policy-enabled.

## Agent checklist

- [x] TDD: tests for brief render, brokered-only, redaction, ledger, no-network send block
- [x] `pytest` passes (216 tests)
- [x] No real external API calls
