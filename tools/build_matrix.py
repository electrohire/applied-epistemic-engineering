#!/usr/bin/env python3
"""Matrix generator (Winning Combination, Stage 2).

Builds the claims x components matrix from the program ledger ONLY.
The ledger is the sole entry point: a claim that has not passed intake
is not in the matrix, and nothing else can put it there.

  python3 tools/build_matrix.py            # write matrix.json + matrix.md
  python3 tools/build_matrix.py --check    # regenerate and diff; exit 1 on drift

Generation is deterministic: the same ledger produces byte-identical
artifacts (the ledger's own SHA-256 is recorded inside the artifacts
instead of a timestamp). Downstream drift is a defect in the
downstream layer, never a reason to hand-edit the matrix.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
LEDGER_DIR = ROOT / "program-ledger"
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

_spec = importlib.util.spec_from_file_location("ledger_intake", LEDGER_DIR / "intake.py")
assert _spec is not None and _spec.loader is not None
intake = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(intake)


def build(claims_path: Path, components_path: Path) -> dict[str, Any]:
    _accepted, rejected = intake.validate(claims_path, components_path)
    if rejected:
        raise SystemExit(
            "matrix build refused: ledger does not pass intake:\n" + "\n".join(rejected)
        )
    components = json.loads(components_path.read_text(encoding="utf-8"))
    claims: list[dict[str, Any]] = []
    for raw in claims_path.read_text(encoding="utf-8").splitlines():
        if raw.strip():
            claims.append(json.loads(raw))
    ledger_sha = intake.ledger_sha256(claims_path)

    matrix: dict[str, dict[str, list[str]]] = {}
    by_status: dict[str, list[str]] = {}
    for claim in claims:
        by_status.setdefault(claim["status"], []).append(claim["id"])
        for comp in claim.get("metadata", {}).get("components", []):
            matrix.setdefault(comp, {}).setdefault(claim["status"], []).append(claim["id"])

    return {
        "generated_from": {
            "ledger": "program-ledger/claims.jsonl",
            "ledger_sha256": ledger_sha,
            "claims": len(claims),
            "generator": "tools/build_matrix.py",
        },
        "components": [{"id": c["id"], "name": c["name"], "repo": c["repo"]} for c in components],
        "claims": [
            {
                "id": c["id"],
                "kind": c["kind"],
                "status": c["status"],
                "stage": c.get("stage", "created"),
                "date": c.get("metadata", {}).get("date", ""),
                "components": c.get("metadata", {}).get("components", []),
                "depends_on": c.get("depends_on", []),
            }
            for c in claims
        ],
        "matrix": matrix,
        "counts": {
            "by_status": {k: len(v) for k, v in sorted(by_status.items())},
            "by_component": {
                comp: sum(len(ids) for ids in statuses.values())
                for comp, statuses in sorted(matrix.items())
            },
        },
    }


def render_md(data: dict[str, Any]) -> str:
    gen = data["generated_from"]
    lines = [
        "# Program matrix (generated)",
        "",
        f"Generated from {gen['ledger']} (sha256 {gen['ledger_sha256'][:16]}...), "
        f"{gen['claims']} claims, by {gen['generator']}.",
        "Do not hand-edit: regenerate with `python3 tools/build_matrix.py`.",
        "",
        "## Counts by status",
        "",
    ]
    for status, count in data["counts"]["by_status"].items():
        lines.append(f"- {status}: {count}")
    lines += ["", "## Claims x components", ""]
    comp_ids = [c["id"] for c in data["components"]]
    lines.append("| claim | status | " + " | ".join(comp_ids) + " |")
    lines.append("| --- | --- | " + " | ".join("---" for _ in comp_ids) + " |")
    for claim in data["claims"]:
        cells = ["x" if comp in claim["components"] else "" for comp in comp_ids]
        lines.append(f"| {claim['id']} | {claim['status']} | " + " | ".join(cells) + " |")
    lines += ["", "## Claims by component and status", ""]
    for comp in comp_ids:
        statuses = data["matrix"].get(comp, {})
        total = sum(len(v) for v in statuses.values())
        lines.append(f"### {comp} ({total})")
        for status in sorted(statuses):
            lines.append(f"- {status}: {', '.join(statuses[status])}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="diff instead of write")
    parser.add_argument("--ledger", type=Path, default=LEDGER_DIR / "claims.jsonl")
    parser.add_argument("--components", type=Path, default=LEDGER_DIR / "components.json")
    parser.add_argument("--out-dir", type=Path, default=LEDGER_DIR)
    args = parser.parse_args(argv)

    data = build(args.ledger, args.components)
    json_text = json.dumps(data, indent=2, sort_keys=True) + "\n"
    md_text = render_md(data)
    targets = {
        args.out_dir / "matrix.json": json_text,
        args.out_dir / "matrix.md": md_text,
    }
    gen = data["generated_from"]
    print(
        f"MATRIX claims={gen['claims']} ledger_sha256={gen['ledger_sha256'][:16]} "
        f"by_status={data['counts']['by_status']}"
    )
    if args.check:
        drift = []
        for path, text in targets.items():
            if not path.is_file() or path.read_bytes() != text.encode("utf-8"):
                drift.append(path.name)
        if drift:
            print("MATRIX_CHECK DRIFT in: " + ", ".join(sorted(drift)))
            return 1
        print("MATRIX_CHECK OK byte-identical")
        return 0
    for path, text in targets.items():
        path.write_text(text, encoding="utf-8", newline="\n")
        print(f"MATRIX_WROTE {path.name} bytes={len(text.encode('utf-8'))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
