#!/usr/bin/env python3
"""Engine evaluation over the program ledger (Winning Combination, Stage 3).

The engine takes the ledger's claims as input and computes verdicts
mechanically. Check classes:

  E1 expectations (verdict re-derivation): every pre-registered
     expectation in expectations.json is recomputed from its stated
     inputs. A mismatch means the record cited for the verdict does
     not produce the verdict -- the citation does not carry its
     relation (pattern Amendment 1) -- and the claim is VIOLATED.
  E2 hash agreement: content hashes cited for the same artifact (same
     evidence ref, anywhere in the ledger) must be prefix-consistent,
     and a full 64-hex hash stated in a claim's text must agree with
     the claim's own evidence hashes.
  E3 propagation: a claim whose dependency chain (depends_on,
     transitive) reaches a contradicted or superseded claim is stale
     and VIOLATED until reclassified by an appended claim. Resting on
     a draft claim is reported as a note.
  E4 derivability honesty: a claim stating a percentage with no
     pre-registered expectation has no in-ledger inputs for that
     number; it is reported NOT_DERIVABLE, never silently passed.

Verdicts per claim: VIOLATED > VERIFIED (at least one expectation
recomputed exactly) > NOT_DERIVABLE > CONSISTENT.

Usage: python3 tools/evaluate.py [--no-write]
Writes program-ledger/evaluation.json (deterministic) unless
--no-write. Exit code 1 iff any claim is VIOLATED.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
LEDGER_DIR = ROOT / "program-ledger"
sys.dont_write_bytecode = True  # check mode writes nothing, not even .pyc caches
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

_spec = importlib.util.spec_from_file_location("ledger_intake", LEDGER_DIR / "intake.py")
assert _spec is not None and _spec.loader is not None
intake = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(intake)
HEX64 = re.compile(r"\b[0-9a-f]{64}\b")
PERCENT = re.compile(r"(\d+(?:\.\d+)?\s*(?:%|percent))")


def load_claims(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def check_expectation(exp: dict[str, Any]) -> tuple[bool, str]:
    kind = exp["kind"]
    if kind == "sum_equals":
        computed = sum(exp["terms"])
        ok = computed == exp["total"]
        return ok, f"sum({'+'.join(str(t) for t in exp['terms'])})={computed} vs {exp['total']}"
    if kind == "percent_reduction":
        computed = (exp["from"] - exp["to"]) / exp["from"] * 100.0
        ok = abs(computed - exp["stated_percent"]) <= exp["tolerance_pp"]
        return ok, f"reduction={computed:.2f}% vs stated {exp['stated_percent']}%"
    if kind == "percent_of":
        computed = exp["part"] / exp["whole"] * 100.0
        ok = abs(computed - exp["stated_percent"]) <= exp["tolerance_pp"]
        return (
            ok,
            f"{exp['part']}/{exp['whole']}={computed:.2f}% vs stated {exp['stated_percent']}%",
        )
    if kind == "series_ratio":
        series = exp["series"]
        computed = sum(series) / series[-1]
        ok = abs(computed - exp["stated_ratio"]) <= exp["tolerance"]
        return ok, f"sum(series)/last={computed:.3f} vs stated {exp['stated_ratio']}"
    return False, f"unknown expectation kind {kind!r}"


def prefix_consistent(values: list[str]) -> bool:
    if not values:
        return True
    longest = max(values, key=len)
    return all(longest.startswith(v) for v in values)


def evaluate(claims: list[dict[str, Any]], expectations: list[dict[str, Any]]) -> dict[str, Any]:
    by_id = {c["id"]: c for c in claims}
    exp_by_claim: dict[str, list[dict[str, Any]]] = {}
    for exp in expectations:
        exp_by_claim.setdefault(exp["claim"], []).append(exp)

    # E2a: hash agreement per evidence ref, across the whole ledger.
    ref_hashes: dict[str, list[str]] = {}
    for claim in claims:
        for ev in claim.get("evidence", []):
            if ev.get("content_hash"):
                ref_hashes.setdefault(ev["ref"], []).append(ev["content_hash"])
    bad_refs = {ref for ref, hs in ref_hashes.items() if not prefix_consistent(hs)}

    def dependency_closure(cid: str) -> set[str]:
        seen: set[str] = set()
        stack = list(by_id.get(cid, {}).get("depends_on", []))
        while stack:
            cur = stack.pop()
            if cur in seen:
                continue
            seen.add(cur)
            stack.extend(by_id.get(cur, {}).get("depends_on", []))
        return seen

    verdicts: list[dict[str, Any]] = []
    for claim in claims:
        cid = claim["id"]
        problems: list[str] = []
        notes: list[str] = []
        verified: list[str] = []

        for ev in claim.get("evidence", []):
            if ev["ref"] in bad_refs:
                problems.append(f"E2 hash disagreement for ref {ev['ref']}")
        text_hashes = HEX64.findall(claim.get("text", ""))
        own_hashes = [
            ev["content_hash"] for ev in claim.get("evidence", []) if ev.get("content_hash")
        ]
        for th in text_hashes:
            if own_hashes and not prefix_consistent([th, *own_hashes]):
                problems.append("E2 text hash disagrees with evidence hash")

        for exp in exp_by_claim.get(cid, []):
            ok, detail = check_expectation(exp)
            if ok:
                verified.append(detail)
            else:
                problems.append(f"E1 expectation failed: {detail}")

        closure = dependency_closure(cid)
        for dep in sorted(closure):
            status = by_id.get(dep, {}).get("status")
            if status in ("contradicted", "superseded"):
                problems.append(f"E3 depends on {status} claim {dep}")
            elif status == "draft":
                notes.append(f"rests on unsettled claim {dep}")

        for ev in claim.get("evidence", []):
            if ev.get("direction") == "contradicts" and claim.get("status") == "supported":
                notes.append(f"carries contradicting evidence {ev['ref']} (weighed, disclosed)")

        if problems:
            verdict = "violated"
        elif verified:
            verdict = "verified"
        elif cid not in exp_by_claim and PERCENT.search(claim.get("text", "")):
            verdict = "not_derivable"
            notes.append("states a percentage with no in-ledger inputs")
        else:
            verdict = "consistent"
        verdicts.append(
            {
                "id": cid,
                "verdict": verdict,
                "verified": verified,
                "problems": problems,
                "notes": notes,
            }
        )

    counts: dict[str, int] = {}
    for v in verdicts:
        counts[v["verdict"]] = counts.get(v["verdict"], 0) + 1
    return {"verdicts": verdicts, "counts": counts}


def render_payload(ledger: Path, result: dict[str, Any]) -> str:
    payload = {
        "generated_from": {
            "ledger": "program-ledger/claims.jsonl",
            "ledger_sha256": intake.ledger_sha256(ledger),
            "expectations": "program-ledger/expectations.json",
            "evaluator": "tools/evaluate.py",
        },
        "counts": result["counts"],
        "verdicts": result["verdicts"],
    }
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", type=Path, default=LEDGER_DIR / "claims.jsonl")
    parser.add_argument("--expectations", type=Path, default=LEDGER_DIR / "expectations.json")
    parser.add_argument("--out", type=Path, default=LEDGER_DIR / "evaluation.json")
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument(
        "--check",
        action="store_true",
        help="compare the committed evaluation.json byte-exactly; never write",
    )
    args = parser.parse_args(argv)

    claims = load_claims(args.ledger)
    expectations = json.loads(args.expectations.read_text(encoding="utf-8"))["expectations"]
    result = evaluate(claims, expectations)
    for v in result["verdicts"]:
        detail = "; ".join(v["problems"] or v["verified"] or v["notes"])
        print(f"EVAL {v['id']} {v['verdict'].upper()} {detail}".rstrip())
    c = result["counts"]
    print(
        "EVAL_RESULT "
        f"verified={c.get('verified', 0)} consistent={c.get('consistent', 0)} "
        f"not_derivable={c.get('not_derivable', 0)} violated={c.get('violated', 0)}"
    )
    violated = 1 if c.get("violated", 0) else 0
    if args.check:
        text = render_payload(args.ledger, result)
        if not args.out.is_file() or args.out.read_bytes() != text.encode("utf-8"):
            print("EVAL_CHECK DRIFT in evaluation.json")
            return 1
        print("EVAL_CHECK OK byte-identical")
        return violated
    if not args.no_write:
        text = render_payload(args.ledger, result)
        args.out.write_text(text, encoding="utf-8", newline="\n")
        print(f"EVAL_WROTE {args.out.name}")
    return violated


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
