"""Applied Epistemic Engineering primitives and workflow engine.

Copyright (c) 2026 ElectroHire Inc.
"""

from aee._version import __version__ as __version__
from aee.adapters.evaluator import EvaluatorAdapter
from aee.challenge import StressTester
from aee.engine import AEEEngine, Assessment
from aee.evidence_check import EvidenceFinding, EvidenceReport, check_evidence
from aee.gaps import GapEngine, GapEntry, GapRegister
from aee.graph import ClaimGraph
from aee.ledger import (
    DEFAULT_LEDGER_PATH,
    HashChainLedger,
    LedgerAnchor,
    LedgerVerification,
)
from aee.model import (
    BundleValidationError,
    Claim,
    ClaimKind,
    ClaimStatus,
    ConfidenceBand,
    Disposition,
    DispositionKind,
    Evidence,
    EvidenceDirection,
    EvidenceKind,
    FailureMode,
    Severity,
    SourceQuality,
    Uncertainty,
    normalize_claim_id,
)
from aee.policy import AssessmentPolicy, ClaimVerdict, Verdict
from aee.recovery import RecoveryOperator, RecoveryProposal, RecoveryStrategy
from aee.reliability import ReliabilityTable, SourceRecord
from aee.review import ReviewItem, ReviewQueue, VerdictChange, build_review_queue
from aee.scoring import ClaimScore, ScoringEngine, canonical_evidence_identity
from aee.session import AEESession
from aee.sources import normalize_source_identity, source_identity

__all__ = [
    "DEFAULT_LEDGER_PATH",
    "AEEEngine",
    "AEESession",
    "Assessment",
    "AssessmentPolicy",
    "BundleValidationError",
    "Claim",
    "ClaimGraph",
    "ClaimKind",
    "ClaimScore",
    "ClaimStatus",
    "ClaimVerdict",
    "ConfidenceBand",
    "Disposition",
    "DispositionKind",
    "EvaluatorAdapter",
    "Evidence",
    "EvidenceDirection",
    "EvidenceFinding",
    "EvidenceKind",
    "EvidenceReport",
    "FailureMode",
    "GapEngine",
    "GapEntry",
    "GapRegister",
    "HashChainLedger",
    "LedgerAnchor",
    "LedgerVerification",
    "RecoveryOperator",
    "RecoveryProposal",
    "RecoveryStrategy",
    "ReliabilityTable",
    "ReviewItem",
    "ReviewQueue",
    "ScoringEngine",
    "Severity",
    "SourceQuality",
    "SourceRecord",
    "StressTester",
    "Uncertainty",
    "Verdict",
    "VerdictChange",
    "build_review_queue",
    "canonical_evidence_identity",
    "check_evidence",
    "normalize_claim_id",
    "normalize_source_identity",
    "source_identity",
]
