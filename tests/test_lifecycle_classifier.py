"""The hand-written-source classifier must agree with its labeled fixtures."""

import importlib.util
import json
from pathlib import Path
from types import ModuleType

ROOT = Path(__file__).resolve().parents[1]
CLASSIFIER_PATH = ROOT / "lifecycle" / "classifier.py"
FIXTURES = ROOT / "lifecycle" / "classifier_fixtures.jsonl"


def load_classifier() -> ModuleType:
    spec = importlib.util.spec_from_file_location("lifecycle_classifier_test", CLASSIFIER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


classifier = load_classifier()


def test_classifier_agreement_at_least_95_percent() -> None:
    rows = [json.loads(line) for line in FIXTURES.read_text(encoding="utf-8").splitlines()]
    assert len(rows) >= 40
    matches = sum(
        1 for row in rows if classifier.is_handwritten_source(row["path"]) == row["handwritten"]
    )
    agreement = matches / len(rows)
    assert agreement >= 0.95, f"agreement={agreement:.3f} ({matches}/{len(rows)})"


def test_classifier_exclusions_win_over_source_extensions() -> None:
    assert classifier.is_handwritten_source("src/generated/client.py") is False
    assert classifier.is_handwritten_source("src/client.py") is True
    assert classifier.is_handwritten_source("program-ledger/matrix.json") is False
