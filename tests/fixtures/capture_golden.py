"""Phase 0 (T002): capture the OLD (pre-FR-1) load behavior on the FR-1
fixtures as golden files. Run BEFORE the strict-loading changes; the
goldens record the defective behavior the new tests invert."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from aee.extract import load_claims  # noqa: E402

FIXTURES = Path(__file__).resolve().parent
GOLDEN = FIXTURES / "golden"

CASES = {
    "fr1-renamed-field": "fr1-renamed-field.json",
    "fr1-bad-enum": "fr1-bad-enum.json",
    "fr1-legacy-tekmerion-001": "fr1-legacy-tekmerion-001.json",
}


def main() -> None:
    GOLDEN.mkdir(parents=True, exist_ok=True)
    for name, filename in CASES.items():
        path = FIXTURES / filename
        try:
            claims = load_claims(path)
            record = {
                "fixture": filename,
                "behavior": "loaded",
                "claim_count": len(claims),
                "claims": [
                    {
                        "id": c.id,
                        "text": c.text,
                        "kind": c.kind.value,
                        "status": c.status.value,
                        "evidence_refs": [e.ref for e in c.evidence],
                        "falsification_tests": list(c.falsification_tests),
                    }
                    for c in claims
                ],
            }
        except Exception as exc:  # golden captures whatever the old code did
            record = {
                "fixture": filename,
                "behavior": "raised",
                "error_type": type(exc).__name__,
                "error": str(exc),
            }
        out = GOLDEN / f"{name}.old-behavior.json"
        out.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
        print(f"{name}: {record['behavior']}")


if __name__ == "__main__":
    main()
