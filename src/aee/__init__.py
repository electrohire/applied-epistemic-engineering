"""Applied Epistemic Engineering primitives and workflow engine.

Copyright (c) 2026 ElectroHire Inc.
"""

from aee.adapters.evaluator import EvaluatorAdapter
from aee.challenge import StressTester
from aee.engine import AEEEngine, Assessment
from aee.graph import ClaimGraph
from aee.ledger import HashChainLedger, LedgerVerification
from aee.model import (
    Claim,
    ClaimKind,
    ClaimStatus,
    ConfidenceBand,
    Evidence,
    EvidenceDirection,
    EvidenceKind,
    FailureMode,
    Severity,
    SourceQuality,
    Uncertainty,
)
from aee.recovery import RecoveryOperator, RecoveryProposal, RecoveryStrategy
from aee.scoring import ClaimScore, ScoringEngine
from aee.session import AEESession

__version__ = "1.0.0"

__all__ = [
    "AEEEngine",
    "AEESession",
    "Assessment",
    "Claim",
    "ClaimGraph",
    "ClaimKind",
    "ClaimScore",
    "ClaimStatus",
    "ConfidenceBand",
    "EvaluatorAdapter",
    "Evidence",
    "EvidenceDirection",
    "EvidenceKind",
    "FailureMode",
    "HashChainLedger",
    "LedgerVerification",
    "RecoveryOperator",
    "RecoveryProposal",
    "RecoveryStrategy",
    "ScoringEngine",
    "Severity",
    "SourceQuality",
    "StressTester",
    "Uncertainty",
]
