import pytest

from aee import Claim, ClaimGraph


def test_dependency_first_order() -> None:
    graph = ClaimGraph(
        [
            Claim(id="B", text="B", depends_on=["A"]),
            Claim(id="A", text="A"),
        ]
    )
    assert graph.topological_order() == ["A", "B"]


def test_duplicate_rejected() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        ClaimGraph([Claim(id="A", text="one"), Claim(id="A", text="two")])


def test_cycle_detected() -> None:
    graph = ClaimGraph(
        [Claim(id="A", text="A", depends_on=["B"]), Claim(id="B", text="B", depends_on=["A"])]
    )
    assert graph.cycles() == [["A", "B", "A"]]
    with pytest.raises(ValueError, match="cycles"):
        graph.topological_order()


def test_missing_dependency_reported() -> None:
    graph = ClaimGraph([Claim(id="A", text="A", depends_on=["B"])])
    assert graph.missing_dependencies() == {"A": ["B"]}


def test_conflicts_deduplicated() -> None:
    graph = ClaimGraph(
        [
            Claim(id="A", text="A", conflicts_with=["B"]),
            Claim(id="B", text="B", conflicts_with=["A"]),
        ]
    )
    assert graph.conflicts() == [("A", "B")]


def test_mermaid_is_stable() -> None:
    graph = ClaimGraph([Claim(id="REQ-1", text='A "quoted" claim')])
    value = graph.to_mermaid()
    assert value.startswith("flowchart TD")
    assert "REQ-1" in value
    assert "&quot;quoted&quot;" in value


def test_mermaid_ids_do_not_collide() -> None:
    """Regression: "A-B" and "A_B" used to sanitize to the same node
    id, silently merging two claims into one rendered node."""
    graph = ClaimGraph(
        [
            Claim(id="A-B", text="dash", depends_on=["A_B"]),
            Claim(id="A_B", text="underscore"),
        ]
    )
    value = graph.to_mermaid()
    node_lines = [line for line in value.splitlines() if '["' in line]
    node_ids = [line.strip().split('["', 1)[0] for line in node_lines]
    assert len(node_ids) == 2
    assert node_ids[0] != node_ids[1]
    edge_lines = [line for line in value.splitlines() if "-->" in line]
    assert len(edge_lines) == 1
    edge_from, edge_to = (part.strip() for part in edge_lines[0].split("-->"))
    assert edge_from != edge_to
    assert {edge_from, edge_to} == set(node_ids)


def test_mermaid_label_flattens_newlines() -> None:
    graph = ClaimGraph([Claim(id="A", text="line one\nline two")])
    value = graph.to_mermaid()
    # Header + one node line; the raw newline must not split the node.
    assert len(value.rstrip("\n").splitlines()) == 2
    assert "line one line two" in value


def test_cycles_deep_chain_no_recursion_error() -> None:
    """Regression: cycles() was recursive DFS and raised
    RecursionError on chains beyond ~1,000 claims."""
    n = 3000
    claims = [
        Claim(id=f"C{i:05d}", text="x", depends_on=[f"C{i + 1:05d}"] if i + 1 < n else [])
        for i in range(n)
    ]
    graph = ClaimGraph(claims)
    assert graph.cycles() == []
    assert len(graph.topological_order()) == n


def test_cycles_deep_ring_detected() -> None:
    n = 3000
    claims = [Claim(id=f"C{i:05d}", text="x", depends_on=[f"C{(i + 1) % n:05d}"]) for i in range(n)]
    cycles = ClaimGraph(claims).cycles()
    assert len(cycles) == 1
    assert len(cycles[0]) == n + 1
