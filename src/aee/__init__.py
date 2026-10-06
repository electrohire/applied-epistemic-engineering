"""Applied Epistemic Engineering primitives and workflow engine.

Copyright (c) 2026 ElectroHire Inc.
"""

from aee.adapters.evaluator import EvaluatorAdapter
from aee.challenge import StressTester
from aee.engine import AEEEngine, Assessment
from aee.gaps import GapEngine, GapEntry, GapRegister
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
from aee.policy import AssessmentPolicy, ClaimVerdict, Verdict
from aee.recovery import RecoveryOperator, RecoveryProposal, RecoveryStrategy
from aee.reliability import ReliabilityTable, SourceRecord
from aee.scoring import ClaimScore, ScoringEngine
from aee.session import AEESession

__version__ = "1.2.0"

__all__ = [
    "AEEEngine",
    "AEESession",
    "Assessment",
    "AssessmentPolicy",
    "Claim",
    "ClaimGraph",
    "ClaimKind",
    "ClaimScore",
    "ClaimStatus",
    "ClaimVerdict",
    "ConfidenceBand",
    "EvaluatorAdapter",
    "Evidence",
    "EvidenceDirection",
    "EvidenceKind",
    "FailureMode",
    "GapEngine",
    "GapEntry",
    "GapRegister",
    "HashChainLedger",
    "LedgerVerification",
    "RecoveryOperator",
    "RecoveryProposal",
    "RecoveryStrategy",
    "ReliabilityTable",
    "ScoringEngine",
    "Severity",
    "SourceQuality",
    "SourceRecord",
    "StressTester",
    "Uncertainty",
    "Verdict",
]
