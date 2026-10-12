"""Convenience session facade for incremental AEE use."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from aee.engine import AEEEngine, Assessment
from aee.extract import duplicate_key_hook
from aee.ledger import HashChainLedger
from aee.model import Claim, ClaimKind, Evidence, normalize_claim_id


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
        # FR-5.7: the session facade applies the same single id rule
        # as the loaders, so a claim added as "clm-1" IS "CLM-1" —
        # the duplicate check, the stored key, and later lookups all
        # see the one canonical identity.
        normalised_id = normalize_claim_id(claim_id)
        if normalised_id in self.claims:
            raise ValueError(f"duplicate claim id: {normalised_id}")
        claim = Claim(
            id=normalised_id,
            text=text,
            kind=kind,
            boundary=boundary or [],
            depends_on=[normalize_claim_id(ref) for ref in depends_on or []],
            source_ref=source_ref,
        )
        self.claims[normalised_id] = claim
        return claim

    def add_evidence(self, claim_id: str, evidence: Evidence) -> None:
        self.claims[normalize_claim_id(claim_id)].add_evidence(evidence)

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
        self.state_file.write_text(
            json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8"
        )

    def load(self) -> int:
        if self.state_file is None or not self.state_file.exists():
            return 0
        # FR-5.4: the state file is a claims bundle on disk, so it
        # loads under the bundle rules — duplicate JSON keys refused
        # (never last-wins) and bare NaN/Infinity refused (FR-3.3).
        state_file = self.state_file

        def _reject_constant(name: str) -> None:
            raise ValueError(
                f"session state file {state_file.as_posix()}: non-finite "
                f"number {name!r} is not allowed (Spec 003 FR-3.3)"
            )

        value = json.loads(
            state_file.read_text(encoding="utf-8"),
            parse_constant=_reject_constant,
            object_pairs_hook=duplicate_key_hook(f"session state file {state_file.as_posix()}"),
        )
        self.project = str(value.get("project", self.project))
        self.phase = str(value.get("phase", self.phase))
        loaded = list(map(Claim.from_dict, value.get("claims", [])))
        # Spec 003 FR-1.3 (RT2-M4): duplicate ids in a state file are
        # refused with the same rule add_claim/assess apply — the old
        # dict comprehension silently merged them last-wins, dropping
        # claims without a trace.
        claims: dict[str, Claim] = {}
        for claim in loaded:
            if claim.id in claims:
                raise ValueError(f"duplicate claim id: {claim.id}")
            claims[claim.id] = claim
        self.claims = claims
        return len(self.claims)
