"""In-memory external cost ledger for dry-run and future live interactions."""

from __future__ import annotations

from dataclasses import dataclass, field

from mac_llm.external.schemas import ExternalCostLedgerEntry


@dataclass
class ExternalCostLedger:
    """Append-only ledger of external-agent interaction costs."""

    entries: list[ExternalCostLedgerEntry] = field(default_factory=list)

    def record_dry_run(
        self,
        *,
        timestamp: str,
        role: str,
        external_target: str,
        mode: str,
        reason: str,
        fallback_chain_step: int = 0,
        input_tokens: int = 0,
        output_tokens: int = 0,
        estimated_cost_usd: float = 0.0,
        tool_round_trips: int = 0,
        brokered_tools_used: tuple[str, ...] = (),
        helpfulness: str = "unknown",
        result: str = "dry_run_rendered",
    ) -> ExternalCostLedgerEntry:
        """Record one dry-run consultation brief render with no network I/O."""
        entry = ExternalCostLedgerEntry(
            timestamp=timestamp,
            role=role,
            external_target=external_target,
            mode=mode,
            reason=reason,
            fallback_chain_step=fallback_chain_step,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost_usd=estimated_cost_usd,
            tool_round_trips=tool_round_trips,
            brokered_tools_used=brokered_tools_used,
            helpfulness=helpfulness,
            result=result,
        )
        self.entries.append(entry)
        return entry
