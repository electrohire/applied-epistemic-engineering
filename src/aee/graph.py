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
        """Return dependency cycles, each normalized to a stable representation.

        Iterative DFS: the previous recursive implementation raised
        RecursionError on dependency chains beyond ~1,000 claims,
        crashing assess() instead of reporting the graph.
        """
        color: dict[str, int] = defaultdict(int)
        found: set[tuple[str, ...]] = set()

        def normalize(cycle: list[str]) -> tuple[str, ...]:
            body = cycle[:-1]
            rotations = [tuple(body[index:] + body[:index]) for index in range(len(body))]
            chosen = min(rotations)
            return (*chosen, chosen[0])

        for root in sorted(self.claims):
            if color[root] != 0:
                continue
            color[root] = 1
            path: list[str] = [root]
            frames = [(root, iter(self.claims[root].depends_on))]
            while frames:
                node, deps_iter = frames[-1]
                descended = False
                for dep in deps_iter:
                    if dep not in self.claims:
                        continue
                    if color[dep] == 0:
                        color[dep] = 1
                        path.append(dep)
                        frames.append((dep, iter(self.claims[dep].depends_on)))
                        descended = True
                        break
                    if color[dep] == 1:
                        start = path.index(dep)
                        found.add(normalize([*path[start:], dep]))
                if not descended:
                    frames.pop()
                    path.pop()
                    color[node] = 2
        return [list(item) for item in sorted(found)]

    def strongly_connected_components(self) -> list[list[str]]:
        """Strongly connected components (iterative Tarjan).

        Spec 003 FR-8.3: propagation failure must be scoped to the
        cyclic component, so scoring needs the components themselves,
        not only the cycle paths `cycles()` reports. A component is
        cyclic when it has more than one member, or its single
        member depends on itself. Components are returned with
        members sorted, ordered by first member, for determinism.
        """
        index_counter = [0]
        indices: dict[str, int] = {}
        lowlink: dict[str, int] = {}
        stack: list[str] = []
        on_stack: set[str] = set()
        components: list[list[str]] = []

        for root in sorted(self.claims):
            if root in indices:
                continue
            work: list[tuple[str, int]] = [(root, 0)]
            while work:
                node, child_i = work[-1]
                if child_i == 0:
                    indices[node] = index_counter[0]
                    lowlink[node] = index_counter[0]
                    index_counter[0] += 1
                    stack.append(node)
                    on_stack.add(node)
                deps = [
                    dep
                    for dep in self.claims[node].depends_on
                    if dep in self.claims
                ]
                descended = False
                for i in range(child_i, len(deps)):
                    dep = deps[i]
                    if dep not in indices:
                        work[-1] = (node, i + 1)
                        work.append((dep, 0))
                        descended = True
                        break
                    if dep in on_stack:
                        lowlink[node] = min(lowlink[node], indices[dep])
                if descended:
                    continue
                work.pop()
                if work:
                    parent = work[-1][0]
                    lowlink[parent] = min(lowlink[parent], lowlink[node])
                if lowlink[node] == indices[node]:
                    component = []
                    while True:
                        member = stack.pop()
                        on_stack.discard(member)
                        component.append(member)
                        if member == node:
                            break
                    components.append(sorted(component))
        components.sort(key=lambda component: component[0])
        return components

    def cyclic_components(self) -> list[list[str]]:
        """The components that contain a cycle (FR-8.3): size > 1,
        or a single member with a self-dependency."""
        cyclic = []
        for component in self.strongly_connected_components():
            if len(component) > 1 or component[0] in self.claims[component[0]].depends_on:
                cyclic.append(component)
        return cyclic

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
            label = _mermaid_label(f"{claim_id}: {self.claims[claim_id].text}")
            lines.append(f'    {safe}["{label}"]')
        for claim in self.claims.values():
            for dep in claim.depends_on:
                if dep in self.claims:
                    lines.append(f"    {_safe_id(claim.id)} --> {_safe_id(dep)}")
            for other in claim.conflicts_with:
                if other in self.claims and claim.id < other:
                    lines.append(f"    {_safe_id(claim.id)} -. conflicts .-> {_safe_id(other)}")
        return "\n".join(lines) + "\n"


def _safe_id(value: str) -> str:
    """Map a claim id to a mermaid node id, injectively.

    The previous scheme replaced every non-alphanumeric character
    with "_", so distinct ids collided ("A-B" and "A_B" both became
    "C_A_B") and their nodes silently merged in the rendered graph.
    Here ASCII alphanumerics pass through, a literal "_" doubles,
    and any other character is escaped as "_x<hex>_" — because a
    single "_" only ever begins an escape or a doubled pair, the
    encoding is reversible and collision-free.
    """
    parts = ["C_"]
    for char in value:
        if char.isascii() and char.isalnum():
            parts.append(char)
        elif char == "_":
            parts.append("__")
        else:
            parts.append(f"_x{ord(char):x}_")
    return "".join(parts)


def _mermaid_label(value: str) -> str:
    """Escape free text for a quoted mermaid node label.

    Double quotes would terminate the label early (the old code
    rewrote them to apostrophes in the text but interpolated the
    claim id unescaped), and raw newlines break the line-based
    syntax. Quotes become &quot; entities and line breaks collapse
    to spaces; the label truncates at 80 characters as before.
    """
    flattened = value.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
    return flattened[:80].replace('"', "&quot;")
