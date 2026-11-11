#!/usr/bin/env python3
"""Classify whether a path is hand-written source for lifecycle survival.

Exclusions win first. That ordering is intentional: generated Python is not
hand-written merely because it ends in .py, and a JSON or Markdown record is
not source merely because a person edited it. The rules are a reviewed data
file beside this module, not buried constants.
"""

from __future__ import annotations

import json
from pathlib import Path, PurePosixPath

HERE = Path(__file__).resolve().parent
RULES_PATH = HERE / "classifier_rules.json"


def load_rules(path: Path = RULES_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def is_handwritten_source(path: str, rules: dict | None = None) -> bool:
    rules = rules or load_rules()
    normalized = path.replace("\\", "/")
    pure = PurePosixPath(normalized)
    name = pure.name.casefold()
    parts = {part.casefold() for part in pure.parts}
    suffixes = [suffix.casefold() for suffix in pure.suffixes]

    if name in {str(v).casefold() for v in rules["excluded_file_names"]}:
        return False
    if parts & {str(v).casefold() for v in rules["excluded_components"]}:
        return False
    if any(name.endswith(str(v).casefold()) for v in rules["excluded_suffixes"]):
        return False
    if suffixes and suffixes[-1] in {str(v).casefold() for v in rules["excluded_extensions"]}:
        return False
    return bool(
        suffixes and suffixes[-1] in {str(v).casefold() for v in rules["source_extensions"]}
    )


def classify_paths(paths: list[str], rules: dict | None = None) -> dict[str, bool]:
    rules = rules or load_rules()
    return {path: is_handwritten_source(path, rules) for path in paths}


def main() -> int:
    import sys

    for path in sys.argv[1:]:
        print(f"{path}\t{'handwritten' if is_handwritten_source(path) else 'excluded'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
