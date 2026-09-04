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
    assert "'quoted'" in value
