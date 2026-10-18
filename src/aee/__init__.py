"""Applied Epistemic Engineering primitives and workflow engine.

Copyright (c) 2026 ElectroHire Inc.
"""

from aee._version import __version__ as __version__
from aee.adapters.evaluator import EvaluatorAdapter, validate_evaluator_result
from aee.challenge import StressTester
from aee.context_handoff import ContextBudgetExceeded, build_context
from aee.engine import AEEEngine, Assessment
from aee.evidence_check import EvidenceFinding, EvidenceReport, check_evidence
from aee.execution_evidence import (
    ExecutionRecord,
    append_execution_record,
    capture_execution,
    check_execution_applicability,
)
from aee.execution_reports import verify_test_report
from aee.execution_scope import FreshnessReport, ScopeSnapshot, check_freshness, snapshot_scope
from aee.gaps import GapEngine, GapEntry, GapRegister
from aee.graph import ClaimGraph
from aee.ledger import (
    DEFAULT_LEDGER_PATH,
    HashChainLedger,
    LedgerAnchor,
    LedgerVerification,
    assessment_content_digest,
)
from aee.model import (
    BundleValidationError,
    Claim,
    ClaimKind,
    ClaimStage,
    ClaimStatus,
    ConfidenceBand,
    Disposition,
    DispositionKind,
    Evidence,
    EvidenceDirection,
    EvidenceKind,
    FailureMode,
    IdentityEntry,
    IdentityKind,
    IdentityRegistry,
    Severity,
    SourceQuality,
    StageEvent,
    StageEventKind,
    Uncertainty,
    normalize_claim_id,
)
from aee.policy import AssessmentPolicy, ClaimVerdict, Verdict, verdict_ceiling
from aee.recovery import RecoveryOperator, RecoveryProposal, RecoveryStrategy
from aee.reliability import ProvenanceAnchor, ReliabilityTable, SourceRecord
from aee.review import ReviewItem, ReviewQueue, VerdictChange, build_review_queue
from aee.scoring import ClaimScore, ScoringEngine, canonical_evidence_identity
from aee.session import AEESession
from aee.sources import normalize_source_identity, source_identity
from aee.verification_approval import (
    VerificationMethodApproval,
    append_method_approval,
    check_method_approval,
)
from aee.verification_links import (
    TestDiscovery,
    capture_test_discovery,
    check_verification_links,
    verify_test_discovery,
)

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
    "ClaimStage",
    "ClaimStatus",
    "ClaimVerdict",
    "ConfidenceBand",
    "ContextBudgetExceeded",
    "Disposition",
    "DispositionKind",
    "EvaluatorAdapter",
    "Evidence",
    "EvidenceDirection",
    "EvidenceFinding",
    "EvidenceKind",
    "EvidenceReport",
    "ExecutionRecord",
    "FailureMode",
    "FreshnessReport",
    "GapEngine",
    "GapEntry",
    "GapRegister",
    "HashChainLedger",
    "IdentityEntry",
    "IdentityKind",
    "IdentityRegistry",
    "LedgerAnchor",
    "LedgerVerification",
    "ProvenanceAnchor",
    "RecoveryOperator",
    "RecoveryProposal",
    "RecoveryStrategy",
    "ReliabilityTable",
    "ReviewItem",
    "ReviewQueue",
    "ScopeSnapshot",
    "ScoringEngine",
    "Severity",
    "SourceQuality",
    "SourceRecord",
    "StageEvent",
    "StageEventKind",
    "StressTester",
    "TestDiscovery",
    "Uncertainty",
    "Verdict",
    "VerdictChange",
    "VerificationMethodApproval",
    "append_execution_record",
    "append_method_approval",
    "assessment_content_digest",
    "build_context",
    "build_review_queue",
    "canonical_evidence_identity",
    "capture_execution",
    "capture_test_discovery",
    "check_evidence",
    "check_execution_applicability",
    "check_freshness",
    "check_method_approval",
    "check_verification_links",
    "normalize_claim_id",
    "normalize_source_identity",
    "snapshot_scope",
    "source_identity",
    "validate_evaluator_result",
    "verdict_ceiling",
    "verify_test_discovery",
    "verify_test_report",
]
