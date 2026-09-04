"""Convenience session facade for incremental AEE use."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from aee.engine import AEEEngine, Assessment
from aee.ledger import HashChainLedger
from aee.model import Claim, ClaimKind, Evidence


class AEESession:
    def __init__(
        self,
        project: str,
        *,
        phase: str = "after_plan",
        threshold: float = 0.70,
        state_file: str | Path | None = None,
        ledger_file: str | Path | None = None,
    ) -> None:
        self.project = project
        self.phase = phase
        self.engine = AEEEngine(threshold)
        self.state_file = Path(state_file) if state_file else None
        self.ledger = HashChainLedger(ledger_file) if ledger_file else None
        self.claims: dict[str, Claim] = {}

    def add_claim(
        self,
        claim_id: str,
        text: str,
        *,
        kind: ClaimKind = ClaimKind.ASSUMPTION,
        boundary: list[str] | None = None,
        depends_on: list[str] | None = None,
        source_ref: str = "",
    ) -> Claim:
        if claim_id in self.claims:
            raise ValueError(f"duplicate claim id: {claim_id}")
        claim = Claim(
            id=claim_id,
            text=text,
            kind=kind,
            boundary=boundary or [],
            depends_on=depends_on or [],
            source_ref=source_ref,
        )
        self.claims[claim_id] = claim
        return claim

    def add_evidence(self, claim_id: str, evidence: Evidence) -> None:
        self.claims[claim_id].add_evidence(evidence)

    def assess(self, *, seal: bool = True, metadata: dict[str, Any] | None = None) -> Assessment:
        result = self.engine.assess(
            self.claims.values(), project=self.project, phase=self.phase, metadata=metadata
        )
        if seal and self.ledger is not None:
            self.ledger.append_assessment(result)
        return result

    def save(self) -> None:
        if self.state_file is None:
            raise ValueError("state_file is not configured")
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        value = {
            "schema_version": "1.0",
            "project": self.project,
            "phase": self.phase,
            "claims": [claim.to_dict() for claim in self.claims.values()],
        }
        self.state_file.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")

    def load(self) -> int:
        if self.state_file is None or not self.state_file.exists():
            return 0
        value = json.loads(self.state_file.read_text(encoding="utf-8"))
        self.project = str(value.get("project", self.project))
        self.phase = str(value.get("phase", self.phase))
        self.claims = {claim.id: claim for claim in map(Claim.from_dict, value.get("claims", []))}
        return len(self.claims)
