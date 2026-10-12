"""Deterministic adversarial checks for claim systems."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable

from aee.graph import ClaimGraph
from aee.lexicons import (
    BOUNDARY_SCOPE_TERMS,
    COMPOUND_CONNECTIVES,
    TOKEN_SYNONYMS,
    VAGUE_TERMS,
)
from aee.model import (
    Claim,
    ClaimKind,
    ClaimStatus,
    DispositionKind,
    EvidenceDirection,
    EvidenceKind,
    FailureMode,
    Severity,
    SourceQuality,
)


def _phrase_pattern(phrases: tuple[str, ...]) -> re.Pattern[str]:
    parts = sorted((re.escape(phrase) for phrase in phrases), key=len, reverse=True)
    return re.compile(r"\b(" + "|".join(parts) + r")\b", re.IGNORECASE)


# Spec 003 FR-8.8: the lexicons are versioned data (aee.lexicons),
# not hard-coded lists - the RT1 evasion corpus ("plus", "together
# with", "as well as"; "seamless", "intuitive", "optimal",
# "world-class") is covered by the data, and extending recall is a
# data edit under the lexicon version, not a regex change.
def _vague_pattern() -> re.Pattern[str]:
    # Hyphenated terms match with a hyphen or a space ("world-class"
    # / "world class"); re.escape first, then widen the hyphen.
    parts = sorted(
        (re.escape(term).replace(r"\-", "[- ]") for term in VAGUE_TERMS),
        key=len,
        reverse=True,
    )
    return re.compile(r"\b(" + "|".join(parts) + r")\b", re.IGNORECASE)


_VAGUE = _vague_pattern()
_COMPOUND_CONNECTIVE = _phrase_pattern(COMPOUND_CONNECTIVES)
_COMPOUND_PUNCTUATION = re.compile(r"[,;]")
_ABSOLUTE = re.compile(r"\b(always|never|all|none|guarantee[sd]?|impossible)\b", re.IGNORECASE)
# FR-8.15 atomic-precision guards: patterns inside a single
# proposition that must not read as compound structure - version
# lists ("version 1, 2"), unit alternatives ("degrees Celsius or
# Fahrenheit"), and range idioms ("65 and older").
_ATOMIC_PATTERNS = (
    re.compile(r"\bversions?\s+[\d][\d\s.,]*(?:(?:and|or)\s+[\d.]+)?", re.IGNORECASE),
    re.compile(r"\b\d+(?:\s*,\s*\d+)+\b"),
    re.compile(
        r"\b(?:degrees?\s+)?(celsius|fahrenheit|kelvin)\s+(or|and)\s+(celsius|fahrenheit|kelvin)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\band\s+(older|above|over|beyond|upwards)\b", re.IGNORECASE),
)


class StressTester:
    """Apply transparent checks; it does not pretend to establish truth."""

    def run(self, claims: Iterable[Claim]) -> list[FailureMode]:
        """Run every challenge against the claims.

        Contract — mutation: each claim's ``failures`` list is
        REPLACED with the failures this run produced for it (an
        empty list when it passes). Failures a claim carried in —
        loaded from a file or produced by an earlier run — are not
        merged or preserved. Snapshot ``claim.failures`` before
        calling if you need them.

        Dispositions (FR-5.2): after regeneration, a failure whose
        ``category`` matches a stored disposition on its claim is
        marked ``resolved`` with the disposition attached — the
        challenge stays on the record (it was raised), answered rather
        than erased. A ``split`` disposition naming successor claims
        that do not exist in the bundle (or naming none) draws a
        warning failure, generated after disposition matching so it
        cannot itself be dispositioned away in the same run.
        """
        items = list(claims)
        graph = ClaimGraph()
        failures: list[FailureMode] = []
        seen: Counter[str] = Counter(claim.id for claim in items)

        for claim_id, count in sorted(seen.items()):
            if count > 1:
                failures.append(
                    self._failure(
                        claim_id,
                        "Duplicate identity challenge",
                        f"{count} claims share the same identifier",
                        Severity.CRITICAL,
                        "contradiction",
                        "Assign stable, unique claim identifiers.",
                    )
                )
        for claim in items:
            if claim.id not in graph.claims:
                graph.add(claim)
            failures.extend(self._test_claim(claim))

        report = graph.report()
        for claim_id, missing in sorted(report.missing_dependencies.items()):
            failures.append(
                self._failure(
                    claim_id,
                    "Dependency existence challenge",
                    f"Referenced dependencies do not exist: {', '.join(missing)}",
                    Severity.HIGH,
                    "provenance_gap",
                    "Add the missing claims or remove the invalid dependency links.",
                )
            )
        for cycle in report.cycles:
            failures.append(
                self._failure(
                    cycle[0],
                    "Circular inference challenge",
                    "Dependency cycle: " + " -> ".join(cycle),
                    Severity.HIGH,
                    "contradiction",
                    "Break the cycle with independently observed evidence.",
                )
            )
        for left, right in report.conflicts:
            failures.append(
                self._failure(
                    left,
                    "Declared contradiction challenge",
                    f"{left} conflicts with {right}",
                    Severity.HIGH,
                    "contradiction",
                    "Preserve both claims and obtain discriminating evidence.",
                )
            )
        failures.extend(self._implicit_negation_conflicts(items))

        # Failure IDs must identify one failure instance. The ID is
        # built from claim + challenge name, so the same challenge
        # firing against several peers (e.g. three declared conflicts)
        # produced identical IDs, and recovery proposals / evaluator
        # findings keyed by ID collided. Suffix repeats in encounter
        # order; the first instance keeps the bare ID.
        counts: Counter[str] = Counter()
        for failure in failures:
            counts[failure.id] += 1
            if counts[failure.id] > 1:
                failure.id = f"{failure.id}-{counts[failure.id]}"

        by_claim: dict[str, list[FailureMode]] = {}
        for failure in failures:
            by_claim.setdefault(failure.claim_id, []).append(failure)
        for claim in items:
            claim.failures = by_claim.get(claim.id, [])

        # FR-5.2: honor stored dispositions. Matching keys on
        # (claim, failure.category == disposition.challenge_category).
        for claim in items:
            for failure in claim.failures:
                disposition = claim.disposition_for(failure.category)
                if disposition is not None:
                    failure.resolved = True
                    failure.disposition = disposition

        # FR-5.3: a split disposition must name successor claims that
        # exist in this bundle. One aggregated warning per claim,
        # appended after matching (see the run() contract).
        known_ids = {claim.id for claim in items}
        for claim in items:
            problems: list[str] = []
            for disposition in claim.dispositions:
                if disposition.kind != DispositionKind.SPLIT:
                    continue
                if not disposition.successors:
                    problems.append(
                        f"split disposition for '{disposition.challenge_category}' "
                        "names no successor claims"
                    )
                else:
                    missing = [s for s in disposition.successors if s not in known_ids]
                    if missing:
                        problems.append(
                            f"split disposition for '{disposition.challenge_category}' "
                            f"names successor(s) not in this bundle: {', '.join(missing)}"
                        )
            if problems:
                warning = self._failure(
                    claim.id,
                    "Disposition successor challenge",
                    "; ".join(problems),
                    Severity.MEDIUM,
                    "provenance_gap",
                    "Name the claims the split produced, or correct the disposition.",
                )
                claim.failures.append(warning)
                failures.append(warning)
        return failures

    def _test_claim(self, claim: Claim) -> list[FailureMode]:
        failures: list[FailureMode] = []
        if not claim.text.strip():
            failures.append(
                self._failure(
                    claim.id,
                    "Observability challenge",
                    "Claim has no inspectable proposition",
                    Severity.CRITICAL,
                    "missing_claim",
                    "Write one atomic proposition.",
                )
            )
            return failures
        if not claim.boundary:
            failures.append(
                self._failure(
                    claim.id,
                    "Boundary challenge",
                    "Scope and operating assumptions are not explicit",
                    Severity.HIGH,
                    "assumption_unvalidated",
                    "Declare where, when, and under which assumptions the claim holds.",
                )
            )
        if self._vague_hit(claim.text):
            failures.append(
                self._failure(
                    claim.id,
                    "Precision challenge",
                    "Claim contains an undefined or non-measurable term",
                    Severity.MEDIUM,
                    "ambiguous_requirement",
                    "Replace vague language with a threshold, observable, or decision rule.",
                )
            )
        if self._compound_signal(claim):
            failures.append(
                self._failure(
                    claim.id,
                    "Irreducibility challenge",
                    "Claim may contain multiple independently falsifiable propositions",
                    Severity.MEDIUM,
                    "coverage_gap",
                    "Split the claim into atomic propositions and link them explicitly.",
                )
            )
        if _ABSOLUTE.search(claim.text) and not self._has_relevant_boundary(claim):
            failures.append(
                self._failure(
                    claim.id,
                    "Counterexample challenge",
                    "Absolute language is used without a bounded domain",
                    Severity.HIGH,
                    "assumption_unvalidated",
                    "Narrow the claim or document evidence covering the entire domain.",
                )
            )
        if not claim.falsification_tests and claim.status != ClaimStatus.DRAFT:
            failures.append(
                self._failure(
                    claim.id,
                    "Falsifiability challenge",
                    "Non-draft claim has no stated falsification test",
                    Severity.HIGH,
                    "missing_evidence",
                    "Define an observation that would show the claim is wrong.",
                )
            )
        supporting = [
            item for item in claim.evidence if item.direction == EvidenceDirection.SUPPORTS
        ]
        observed_support = [item for item in supporting if item.kind == EvidenceKind.OBSERVED]
        if (
            claim.status in {ClaimStatus.SUPPORTED, ClaimStatus.PARTIALLY_SUPPORTED}
            and not observed_support
        ):
            failures.append(
                self._failure(
                    claim.id,
                    "Evidence-grounding challenge",
                    "Claim is labeled supported without observed supporting evidence",
                    Severity.HIGH,
                    "unsupported_claim",
                    "Attach independently inspectable evidence or downgrade the status.",
                )
            )
        if supporting and all(item.is_model_self_attestation for item in supporting):
            failures.append(
                self._failure(
                    claim.id,
                    "Independent-evidence challenge",
                    "Only model self-attestation supports the claim",
                    Severity.HIGH,
                    "unverified_assertion",
                    "Obtain evidence from a test, artifact, primary source, or human observation.",
                )
            )
        if claim.kind == ClaimKind.COMPLIANCE and not any(
            item.source_quality in {SourceQuality.PRIMARY, SourceQuality.TEST}
            and item.kind == EvidenceKind.OBSERVED
            for item in supporting
        ):
            failures.append(
                self._failure(
                    claim.id,
                    "Authority challenge",
                    "Compliance claim lacks observed primary-authority or test evidence",
                    Severity.HIGH,
                    "missing_evidence",
                    "Cite the controlling text and attach assessment evidence.",
                )
            )
        if any(item.direction == EvidenceDirection.CONTRADICTS for item in claim.evidence):
            failures.append(
                self._failure(
                    claim.id,
                    "Counterevidence challenge",
                    "Recorded evidence contradicts the claim",
                    Severity.HIGH,
                    "contradiction",
                    "Resolve, narrow, or supersede the claim without deleting counterevidence.",
                )
            )
        failures.extend(self._polarity_failures(claim))
        return failures

    def _polarity_failures(self, claim: Claim) -> list[FailureMode]:
        """Polarity coherence (Spec 003 FR-2.2, RT1-03).

        An item's ``direction`` is the only routing signal scoring,
        challenge, and policy read — so a refutation relabelled
        ``direction: context`` used to vanish from all three at once
        (score 0.25/clarify became 1.0/pass with zero failures). Kind
        and direction must now cohere:

        The incoherence is one-directional by design: ``kind`` says
        what an item IS (``contradicted`` = its content is a
        refutation) while ``direction`` says how it is routed. A
        refutation (kind ``contradicted``) routed as anything but
        ``contradicts`` is hidden — HIGH, category ``contradiction``,
        the same routing as honest counterevidence, so laundering
        cannot produce a cleaner outcome than honesty would. The
        reverse combination is NOT incoherent: an observed or inferred
        item routed ``contradicts`` is ordinary honest
        counter-evidence (a measurement that refutes), and flagging it
        would punish the honest labelling this check exists to protect.
        """
        failures: list[FailureMode] = []
        hidden = [
            item
            for item in claim.evidence
            if item.kind == EvidenceKind.CONTRADICTED
            and item.direction != EvidenceDirection.CONTRADICTS
        ]
        if hidden:
            refs = ", ".join(sorted({item.ref for item in hidden}))
            failures.append(
                self._failure(
                    claim.id,
                    "Polarity coherence challenge",
                    f"Contradicted-kind evidence is routed as "
                    f"{hidden[0].direction.value} instead of contradiction "
                    f"(ref(s): {refs}); kind and direction must cohere, "
                    "a refutation cannot be relabelled into invisibility",
                    Severity.HIGH,
                    "contradiction",
                    (
                        "Route refutations with direction 'contradicts', or "
                        "correct the kind if the item is not a refutation."
                    ),
                )
            )
        return failures

    @staticmethod
    def _vague_hit(text: str) -> bool:
        """Precision signal with the FR-8.15 proper-noun guard.

        A listed vague word inside a multi-word Capitalized proper
        noun ("Secure Boot", "World Class" as a product name) is a
        name, not a quality claim, and does not fire: when the match
        is capitalised mid-text and an adjacent word is also
        capitalised, the match is treated as part of a proper noun.
        Sentence-initial capitalisation is not a proper noun.
        """
        for match in _VAGUE.finditer(text):
            start, end = match.span()
            before = text[:start].rstrip()
            after = text[end:].lstrip()
            at_sentence_start = not before or before.endswith((".", "!", "?"))
            if at_sentence_start:
                return True  # sentence-initial capital is ordinary usage
            prev_word = before.split()[-1] if before.split() else ""
            next_word = after.split()[0] if after.split() else ""
            matched = match.group(0)
            proper_noun = matched[0].isupper() and (
                (prev_word and prev_word[0].isupper()) or (next_word and next_word[0].isupper())
            )
            if not proper_noun:
                return True
        return False

    @staticmethod
    def _compound_signal(claim: Claim) -> bool:
        """Whether the claim text signals multiple propositions (FR-5.5).

        A connective word signals compound structure. Punctuation
        alone signals it only when the claim does not carry exactly
        one falsification test — one test is the observable
        signature of a single proposition, so comma-bearing atomic
        prose ("The valve opens at 4 bar, measured at the inlet") no
        longer draws a MEDIUM irreducibility challenge.

        FR-8.15: noun-phrase-internal patterns are stripped before
        the connective test — version lists, comma-separated numeric
        lists, unit alternatives, and range idioms live inside one
        proposition and never made a claim compound.
        """
        text = claim.text
        for pattern in _ATOMIC_PATTERNS:
            text = pattern.sub(" ", text)
        if _COMPOUND_CONNECTIVE.search(text):
            return True
        if _COMPOUND_PUNCTUATION.search(text):
            return len(claim.falsification_tests) != 1
        return False

    @staticmethod
    def _has_relevant_boundary(claim: Claim) -> bool:
        """FR-8.10 (RT1-17): only a RELEVANT boundary suppresses the
        absolute-language counterexample challenge.

        The old rule let ANY boundary string suppress it — an
        unrelated note disarmed the challenge completely. A boundary
        is relevant when it shares content tokens with the claim
        (it is about the claim's subject) or names a scope/limit
        from the boundary lexicon (deployments, environments,
        "only", "within", ...): it scopes the dimension the
        absolute term ranges over.
        """
        if not claim.boundary:
            return False
        claim_tokens = StressTester._tokens(claim.text)
        for entry in claim.boundary:
            lowered = entry.lower()
            if any(term in lowered for term in BOUNDARY_SCOPE_TERMS):
                return True
            if StressTester._tokens(entry) & claim_tokens:
                return True
        return False

    def _implicit_negation_conflicts(self, claims: list[Claim]) -> list[FailureMode]:
        """Negation-conflict detection (FR-8.9, RT1-16).

        Two requirements, both needed: the claims share a SUBJECT
        (their leading content token, synonym-normalised) and at
        least three normalised content tokens, and exactly one of
        them is negated. The old rule needed only the token overlap,
        so different subjects sharing vocabulary ("the audit service
        does not log credit card numbers" / "the billing service
        logs credit card numbers") false-fired.

        Residual limit, stated plainly: this is a heuristic
        challenge, not a semantic contradiction proof. A paraphrase
        that changes the subject's surface form AND the vocabulary
        ("the database stores passwords in plaintext" / "credentials
        are never persisted unencrypted") is NOT detected — synonym
        normalisation covers inflections and near-synonyms within a
        shared subject, not full rewording. Such pairs remain
        possible and are a documented limit, not a silent one.
        """
        failures: list[FailureMode] = []
        for index, left in enumerate(claims):
            left_tokens = self._tokens(left.text)
            left_subject = self._subject(left.text)
            for right in claims[index + 1 :]:
                if left_subject is None or left_subject != self._subject(right.text):
                    continue
                right_tokens = self._tokens(right.text)
                if len(left_tokens & right_tokens) < 3:
                    continue
                left_neg = bool(re.search(r"\b(not|never|no|must not|cannot)\b", left.text, re.I))
                right_neg = bool(re.search(r"\b(not|never|no|must not|cannot)\b", right.text, re.I))
                if left_neg != right_neg:
                    failures.append(
                        self._failure(
                            left.id,
                            "Negation conflict challenge",
                            f"{left.id} may contradict {right.id}",
                            Severity.MEDIUM,
                            "contradiction",
                            (
                                "Confirm whether the claims share a boundary and preserve both "
                                "pending review."
                            ),
                        )
                    )
        return failures

    @staticmethod
    def _subject(text: str) -> str | None:
        """The claim's subject: its first content token, normalised.

        Leading determiners are skipped ("The database stores..." ->
        "database"). This is the binding FR-8.9 requires: crude, and
        deliberately so - it errs toward silence between different
        subjects rather than noise across them.
        """
        tokens: list[str] = [
            token
            for token in re.findall(r"[a-z0-9]+", text.lower())
            if token not in {"the", "a", "an"}
        ]
        if not tokens:
            return None
        return TOKEN_SYNONYMS.get(tokens[0], tokens[0])

    @staticmethod
    def _tokens(text: str) -> set[str]:
        stop = {"a", "an", "and", "be", "is", "must", "not", "of", "or", "the", "to"}
        return {
            TOKEN_SYNONYMS.get(token, token)
            for token in re.findall(r"[a-z0-9]+", text.lower())
            if token not in stop
        }

    @staticmethod
    def _failure(
        claim_id: str,
        challenge: str,
        breakpoint: str,
        severity: Severity,
        category: str,
        recovery_hint: str,
    ) -> FailureMode:
        slug = re.sub(r"[^A-Z0-9]+", "-", challenge.upper()).strip("-")[:24]
        return FailureMode(
            id=f"AEE-{claim_id}-{slug}",
            claim_id=claim_id,
            challenge=challenge,
            breakpoint=breakpoint,
            severity=severity,
            category=category,
            recovery_hint=recovery_hint,
        )
