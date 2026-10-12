"""Canonical source identity for evidence items (Spec 003 FR-2).

One definition, shared by scoring (independence) and policy
(corroboration), so the two gates can never drift apart on what counts
as "the same source" — at red-team time they each counted raw distinct
strings, and same-origin variants (``./study.pdf``, ``Study.PDF``,
``https://x.org/s/``, ``s.pdf `` with a trailing space) minted full
independence in scoring AND satisfied the policy corroboration gate
simultaneously (RT1-14).
"""

from __future__ import annotations

from aee.model import Evidence


def normalize_source_identity(raw: str) -> str:
    """Canonical form of one source identity string.

    Rules, in order: strip surrounding whitespace; lowercase; for
    URL-shaped values strip ONE trailing slash; for path-shaped values
    strip leading ``./`` segments and one trailing slash. Deliberately
    conservative — full URL canonicalisation (scheme/host folding,
    dot-segment resolution) is out of scope; this kills the observed
    string-variant tricks without pretending to resolve identity in
    general.
    """
    value = raw.strip().lower()
    if "://" in value:
        return value[:-1] if value.endswith("/") else value
    while value.startswith("./"):
        value = value[2:]
    return value[:-1] if value.endswith("/") else value


def source_identity(item: Evidence) -> str:
    """The normalised source an evidence item traces to.

    ``source_id`` wins over ``ref`` (the declared identity over the raw
    reference string); an item with neither has no identity ("").
    """
    return normalize_source_identity(item.source_id or item.ref)
