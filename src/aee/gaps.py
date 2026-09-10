"""Gap register generation from verification matrices and test evidence.

This module provides the core logic for generating and maintaining a
markdown gap register (GAPS.md) that tracks which verification matrix
entries have passing evidence and which remain open.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class GapEntry:
    """A single gap in the verification matrix."""

    id: str
    test_id: str
    requirement: str
    gate: str
    status: str  # "open" | "closed"
    evidence: str = ""
    closed_at: str | None = None

    def to_row(self, is_closed: bool) -> str:
        if is_closed:
            closed = self.closed_at or ""
            return f"| {self.id} | {self.requirement} | {self.gate} | {closed} | {self.evidence} |"
        return f"| {self.id} | {self.requirement} | {self.gate} | {self.status} | {self.evidence} |"


@dataclass(slots=True)
class GapRegister:
    """Complete gap register with open and closed entries."""

    entries: list[GapEntry] = field(default_factory=list)
    generated_at: str = ""
    source_matrix: str = ""
    source_evidence: str = ""

    @property
    def open_gaps(self) -> list[GapEntry]:
        return [e for e in self.entries if e.status != "closed"]

    @property
    def closed_gaps(self) -> list[GapEntry]:
        return [e for e in self.entries if e.status == "closed"]

    @property
    def open_count(self) -> int:
        return len(self.open_gaps)

    @property
    def closed_count(self) -> int:
        return len(self.closed_gaps)

    def to_markdown(self) -> str:
        open_rows = (
            "\n".join(e.to_row(False) for e in self.open_gaps) or "| - | - | No open gaps | - | - |"
        )
        closed_rows = (
            "\n".join(e.to_row(True) for e in self.closed_gaps)
            or "| - | - | No closed gaps | - | - |"
        )
        return (
            f"# Gap Register\n"
            f"\n"
            f"**Updated:** {self.generated_at}\n"
            f"**Source:** {self.source_matrix} + {self.source_evidence}\n"
            f"**Open:** {self.open_count} | **Closed:** {self.closed_count}\n"
            f"\n"
            f"## Open Gaps\n"
            f"\n"
            f"| ID | Requirement | Gap | Status | Evidence Needed |\n"
            f"|----|-------------|-----|--------|-----------------|\n"
            f"{open_rows}\n"
            f"\n"
            f"## Closed Gaps\n"
            f"\n"
            f"| ID | Requirement | Gap | Closed | Evidence |\n"
            f"|----|-------------|-----|--------|----------|\n"
            f"{closed_rows}\n"
            f"\n"
            f"## Notes\n"
            f"\n"
            f"- Gaps are ordered by priority (highest first)\n"
            f"- Status values: `open`, `in_progress`, `blocked`, `closed`\n"
            f'- "Evidence Needed" describes what must pass to close the gap\n'
            f"- Run `aee gaps` to regenerate this file\n"
            f"- Run `aee gaps --close GAP-XXX` to mark a gap closed\n"
        )


class GapEngine:
    """Generate and maintain a gap register from a verification matrix and evidence."""

    _MATRIX_ROW_RE = re.compile(r"\|\s*(T-[A-Z]+-\d+)\s*\|\s*([^|]+)\|\s*([^|]+)\|\s*([^|]+)\|")
    _GAP_ROW_RE = re.compile(r"^\|\s*(GAP-\d+)\s*\|")

    def generate(
        self,
        matrix_path: Path,
        evidence_dir: Path,
        existing_gaps_path: Path | None = None,
    ) -> GapRegister:
        """Generate a gap register from a verification matrix and evidence directory.

        Args:
            matrix_path: Path to the verification matrix markdown file.
            evidence_dir: Directory containing test evidence JSON files.
            existing_gaps_path: Optional path to an existing GAPS.md to preserve closed gaps.

        Returns:
            A populated GapRegister.
        """
        if not matrix_path.is_file():
            raise FileNotFoundError(f"Verification matrix not found: {matrix_path}")

        matrix_content = matrix_path.read_text(encoding="utf-8")
        test_rows = self._MATRIX_ROW_RE.findall(matrix_content)

        # Collect passing test IDs from evidence
        passing_tests = self._collect_passing_tests(evidence_dir)

        # Load existing gaps to preserve closed status
        existing_gaps = self._load_existing_gaps(existing_gaps_path)

        # Build entries
        entries: list[GapEntry] = []
        for idx, (test_id, reqs, _layer, gate) in enumerate(test_rows, start=1):
            gap_id = f"GAP-{idx:03d}"
            reqs_clean = reqs.strip()
            gate_clean = gate.strip()

            if test_id in passing_tests:
                entries.append(
                    GapEntry(
                        id=gap_id,
                        test_id=test_id,
                        requirement=reqs_clean,
                        gate=gate_clean,
                        status="closed",
                        evidence=f"{test_id} pass",
                        closed_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    )
                )
            elif gap_id in existing_gaps:
                # Preserve existing status
                existing = existing_gaps[gap_id]
                entries.append(
                    GapEntry(
                        id=gap_id,
                        test_id=test_id,
                        requirement=reqs_clean,
                        gate=gate_clean,
                        status=existing["status"],
                        evidence=existing.get("evidence", f"{test_id} pass"),
                        closed_at=existing.get("closed_at"),
                    )
                )
            else:
                entries.append(
                    GapEntry(
                        id=gap_id,
                        test_id=test_id,
                        requirement=reqs_clean,
                        gate=gate_clean,
                        status="open",
                        evidence=f"{test_id} pass",
                    )
                )

        return GapRegister(
            entries=entries,
            generated_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            source_matrix=matrix_path.name,
            source_evidence=evidence_dir.name if evidence_dir.is_dir() else "none",
        )

    def close_gap(self, register: GapRegister, gap_id: str) -> GapRegister:
        """Mark a specific gap as closed in the register.

        Args:
            register: The current gap register.
            gap_id: The gap ID to close (e.g., "GAP-001").

        Returns:
            A new GapRegister with the gap marked closed.
        """
        closed_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        new_entries = []
        for entry in register.entries:
            if entry.id == gap_id:
                new_entries.append(
                    GapEntry(
                        id=entry.id,
                        test_id=entry.test_id,
                        requirement=entry.requirement,
                        gate=entry.gate,
                        status="closed",
                        evidence=entry.evidence,
                        closed_at=closed_at,
                    )
                )
            else:
                new_entries.append(entry)

        return GapRegister(
            entries=new_entries,
            generated_at=register.generated_at,
            source_matrix=register.source_matrix,
            source_evidence=register.source_evidence,
        )

    def load_register(self, gaps_path: Path) -> GapRegister:
        """Load an existing gap register from a markdown file.

        Args:
            gaps_path: Path to the GAPS.md file.

        Returns:
            A GapRegister parsed from the file.

        Raises:
            FileNotFoundError: If the file does not exist.
        """
        if not gaps_path.is_file():
            raise FileNotFoundError(f"Gap register not found: {gaps_path}")

        content = gaps_path.read_text(encoding="utf-8")
        lines = content.splitlines()

        # Extract timestamp
        generated_at = ""
        for line in lines:
            if line.startswith("**Updated:**"):
                generated_at = line.split(":", 1)[1].strip()
                break

        # Extract source
        source_matrix = ""
        source_evidence = ""
        for line in lines:
            if line.startswith("**Source:**"):
                parts = line.split(":", 1)[1].strip()
                # Format: "matrix.md + evidence"
                if " + " in parts:
                    source_matrix, source_evidence = parts.split(" + ", 1)
                else:
                    source_matrix = parts
                break

        # Parse entries
        entries: list[GapEntry] = []
        in_closed = False
        for line in lines:
            if line.startswith("## Open Gaps"):
                in_closed = False
                continue
            if line.startswith("## Closed Gaps"):
                in_closed = True
                continue
            if (
                line.startswith("## ")
                and not line.startswith("## Open")
                and not line.startswith("## Closed")
            ):
                in_closed = False
                continue

            match = self._GAP_ROW_RE.match(line)
            if match:
                gap_id = match.group(1)
                cells = [p.strip() for p in line.split("|")]
                # cells: ['', 'ID', 'Req', 'Gap', 'Status/Closed', 'Evidence', '']
                if len(cells) >= 6:
                    status = "closed" if in_closed else "open"
                    closed_at = None
                    if in_closed:
                        closed_at = cells[4] if cells[4] and cells[4] != "-" else None
                    entries.append(
                        GapEntry(
                            id=gap_id,
                            test_id="",
                            requirement=cells[2],
                            gate=cells[3],
                            status=status,
                            evidence=cells[5] if cells[5] != "-" else "",
                            closed_at=closed_at,
                        )
                    )

        return GapRegister(
            entries=entries,
            generated_at=generated_at,
            source_matrix=source_matrix,
            source_evidence=source_evidence,
        )

    # -- Private helpers --

    def _collect_passing_tests(self, evidence_dir: Path) -> set[str]:
        """Walk the evidence directory and collect passing test IDs."""
        passing: set[str] = set()
        if not evidence_dir.is_dir():
            return passing

        for fpath in evidence_dir.rglob("*.json"):
            if not fpath.is_file():
                continue
            try:
                data = json.loads(fpath.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if not isinstance(data, dict):
                continue
            results = data.get("results", data.get("tests", []))
            if not isinstance(results, list):
                continue
            for r in results:
                if not isinstance(r, dict):
                    continue
                if r.get("status") in ("pass", "passed", "ok"):
                    tid = r.get("test_id", r.get("id", ""))
                    if tid:
                        passing.add(tid)
        return passing

    def _load_existing_gaps(self, gaps_path: Path | None) -> dict[str, dict[str, Any]]:
        """Load existing gap entries keyed by gap ID."""
        if gaps_path is None or not gaps_path.is_file():
            return {}

        try:
            register = self.load_register(gaps_path)
        except (FileNotFoundError, OSError):
            return {}

        result: dict[str, dict[str, Any]] = {}
        for entry in register.entries:
            result[entry.id] = {
                "status": entry.status,
                "evidence": entry.evidence,
                "closed_at": entry.closed_at,
            }
        return result
