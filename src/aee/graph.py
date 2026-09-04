"""Dependency and contradiction graph for epistemic claims."""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Iterable
from dataclasses import dataclass, field

from aee.model import Claim


@dataclass(slots=True)
class GraphReport:
    missing_dependencies: dict[str, list[str]] = field(default_factory=dict)
    cycles: list[list[str]] = field(default_factory=list)
    conflicts: list[tuple[str, str]] = field(default_factory=list)

    @property
    def healthy(self) -> bool:
        return not self.missing_dependencies and not self.cycles and not self.conflicts


class ClaimGraph:
    """Directed graph where an edge ``A -> B`` means A depends on B."""

    def __init__(self, claims: Iterable[Claim] = ()) -> None:
        self.claims: dict[str, Claim] = {}
        for claim in claims:
            self.add(claim)

    def add(self, claim: Claim) -> None:
        if claim.id in self.claims:
            raise ValueError(f"duplicate claim id: {claim.id}")
        self.claims[claim.id] = claim

    def dependencies(self, claim_id: str) -> list[Claim]:
        claim = self.claims[claim_id]
        return [self.claims[item] for item in claim.depends_on if item in self.claims]

    def dependents(self, claim_id: str) -> list[Claim]:
        return [claim for claim in self.claims.values() if claim_id in claim.depends_on]

    def missing_dependencies(self) -> dict[str, list[str]]:
        return {
            claim.id: [item for item in claim.depends_on if item not in self.claims]
            for claim in self.claims.values()
            if any(item not in self.claims for item in claim.depends_on)
        }

    def conflicts(self) -> list[tuple[str, str]]:
        pairs: set[tuple[str, str]] = set()
        for claim in self.claims.values():
            for other in claim.conflicts_with:
                if other in self.claims and other != claim.id:
                    left, right = sorted((claim.id, other))
                    pairs.add((left, right))
        return sorted(pairs)

    def cycles(self) -> list[list[str]]:
        """Return dependency cycles, each normalized to a stable representation."""
        color: dict[str, int] = defaultdict(int)
        stack: list[str] = []
        found: set[tuple[str, ...]] = set()

        def normalize(cycle: list[str]) -> tuple[str, ...]:
            body = cycle[:-1]
            rotations = [tuple(body[index:] + body[:index]) for index in range(len(body))]
            chosen = min(rotations)
            return (*chosen, chosen[0])

        def visit(node: str) -> None:
            color[node] = 1
            stack.append(node)
            for dep in self.claims[node].depends_on:
                if dep not in self.claims:
                    continue
                if color[dep] == 0:
                    visit(dep)
                elif color[dep] == 1:
                    start = stack.index(dep)
                    found.add(normalize([*stack[start:], dep]))
            stack.pop()
            color[node] = 2

        for claim_id in sorted(self.claims):
            if color[claim_id] == 0:
                visit(claim_id)
        return [list(item) for item in sorted(found)]

    def topological_order(self) -> list[str]:
        """Return dependency-first order; raise when the graph contains a cycle."""
        cycles = self.cycles()
        if cycles:
            raise ValueError(f"claim dependency graph contains cycles: {cycles}")
        indegree = {claim_id: 0 for claim_id in self.claims}
        reverse: dict[str, list[str]] = defaultdict(list)
        for claim in self.claims.values():
            for dep in claim.depends_on:
                if dep in self.claims:
                    indegree[claim.id] += 1
                    reverse[dep].append(claim.id)
        ready = deque(sorted(key for key, value in indegree.items() if value == 0))
        ordered: list[str] = []
        while ready:
            current = ready.popleft()
            ordered.append(current)
            for dependent in sorted(reverse[current]):
                indegree[dependent] -= 1
                if indegree[dependent] == 0:
                    ready.append(dependent)
        return ordered

    def report(self) -> GraphReport:
        return GraphReport(
            missing_dependencies=self.missing_dependencies(),
            cycles=self.cycles(),
            conflicts=self.conflicts(),
        )

    def to_mermaid(self) -> str:
        lines = ["flowchart TD"]
        for claim_id in sorted(self.claims):
            safe = _safe_id(claim_id)
            label = self.claims[claim_id].text.replace('"', "'")[:80]
            lines.append(f'    {safe}["{claim_id}: {label}"]')
        for claim in self.claims.values():
            for dep in claim.depends_on:
                if dep in self.claims:
                    lines.append(f"    {_safe_id(claim.id)} --> {_safe_id(dep)}")
            for other in claim.conflicts_with:
                if other in self.claims and claim.id < other:
                    lines.append(f"    {_safe_id(claim.id)} -. conflicts .-> {_safe_id(other)}")
        return "\n".join(lines) + "\n"


def _safe_id(value: str) -> str:
    return "C_" + "".join(char if char.isalnum() else "_" for char in value)
