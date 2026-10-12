"""Versioned lexicon data for the challenge and scoring layers.

Spec 003 FR-8.8 (RT1-15): the word lists the heuristics read used to
be hard-coded closed lists inside regexes, and the red team walked
around them with synonyms the lists did not contain ("plus",
"together with", "seamless", "world-class"). The lists now live
here, as data, under a lexicon version of their own:

- ``LEXICON_VERSION`` is recorded in the scoring documentation and
  bumps whenever a change alters challenge or scoring behaviour on
  existing bundles; a lexicon change that alters scores is a
  methodology change under FR-8.2 and rides the methodology bump.
- The regression corpus (``tests/test_fr8_lexicons.py``) holds both
  directions: evasion examples that must fire, and atomic /
  proper-noun examples that must not (FR-8.15).

These are heuristics, not semantics: a list can be extended, and an
adversary can always find a synonym outside it. What the data
discipline buys is that the lists are inspectable, diffable, and
versioned — the recall hole becomes a data edit with a record, not
a code change buried in a regex.
"""

from __future__ import annotations

LEXICON_VERSION = "1.0"

# Compound connectives (FR-8.8): phrases that join propositions.
# Multi-word entries match as phrases. The original closed list was
# {and, or, while, unless, except}; the RT1 evasion corpus added
# "plus", "together with", and "as well as".
COMPOUND_CONNECTIVES: tuple[str, ...] = (
    "and",
    "or",
    "while",
    "unless",
    "except",
    "plus",
    "together with",
    "as well as",
)

# Vague terms (FR-8.8): undefined or non-measurable quality words.
# The original list plus the RT1 evasion corpus (seamless,
# intuitive, optimal, world-class, effortlessly, magical, blazing).
VAGUE_TERMS: tuple[str, ...] = (
    "appropriate",
    "best",
    "easy",
    "efficient",
    "effortlessly",
    "fast",
    "good",
    "high-quality",
    "intuitive",
    "magical",
    "blazing",
    "normal",
    "optimal",
    "reasonable",
    "robust",
    "scalable",
    "seamless",
    "secure",
    "significant",
    "simple",
    "soon",
    "user-friendly",
    "world-class",
)

# Falsifiability lexicon (FR-8.7 criterion iii): observation/action
# terms that make a falsification test state a checkable condition.
# A numeric bound or a comparator also satisfies the criterion; this
# list is the third route.
FALSIFIABILITY_TERMS: tuple[str, ...] = (
    "observe",
    "observed",
    "observing",
    "measure",
    "measured",
    "measuring",
    "measurement",
    "detect",
    "detected",
    "repeat",
    "rerun",
    "reproduce",
    "reproduced",
    "verify",
    "verified",
    "check",
    "checked",
    "count",
    "counts",
    "equals",
    "equal",
    "exceeds",
    "exceed",
    "falls",
    "fall",
    "rises",
    "rise",
    "drops",
    "drop",
    "fails",
    "fail",
    "returns",
    "responds",
    "shows",
    "show",
)

# Comparator phrases (FR-8.7 criterion iii, second route). Symbols
# (<, >, =, !=, <=, >=) are matched separately in scoring.
COMPARATOR_PHRASES: tuple[str, ...] = (
    "less than",
    "more than",
    "greater than",
    "at least",
    "at most",
    "no more than",
    "below",
    "above",
    "under",
    "over",
    "within",
)

# Boundary scope lexicon (FR-8.7 boundary criterion ii): terms that
# name a scope or a limit. A numeric bound also satisfies it.
BOUNDARY_SCOPE_TERMS: tuple[str, ...] = (
    "only",
    "except",
    "within",
    "limited to",
    "limits",
    "excludes",
    "excluding",
    "up to",
    "at most",
    "in production",
    "in staging",
    "under load",
    "deployments",
    "deployment",
    "environments",
    "environment",
    "scope",
)

# Placeholder tokens (FR-8.7 criterion ii): an entry that is a
# single one of these, a single token generally, or a repeated
# single character earns no full credit.
PLACEHOLDER_TOKENS: frozenset[str] = frozenset(
    {"x", "y", "z", "todo", "tbd", "test", "n/a", "na", "none", "...", "?", "f"}
)

# Synonym normalisation for the negation-conflict detector
# (FR-8.9): token -> canonical token. Applied to content tokens
# before overlap counting, so near-paraphrases sharing a subject
# still register. Cross-subject paraphrase remains a documented
# residual limit of the detector (see challenge.py).
TOKEN_SYNONYMS: dict[str, str] = {
    "passwords": "password",
    "credentials": "password",
    "credential": "password",
    "stores": "store",
    "stored": "store",
    "storing": "store",
    "persists": "store",
    "persisted": "store",
    "saves": "store",
    "saved": "store",
    "unencrypted": "plaintext",
    "cleartext": "plaintext",
    "logs": "log",
    "logged": "log",
    "encrypts": "encrypt",
    "encrypted": "encrypt",
    "encryption": "encrypt",
}
