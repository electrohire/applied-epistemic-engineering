#!/usr/bin/env python3
"""Install both real extensions in a disposable Spec Kit project; no inference."""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evaluator-dir", type=Path, required=True)
    parser.add_argument("--aee-dir", type=Path, default=ROOT)
    args = parser.parse_args()
    evaluator = args.evaluator_dir.resolve(strict=True)
    aee_source = args.aee_dir.resolve(strict=True)
    specify = shutil.which("specify")
    assert specify, "Activate requirements/dev.txt environment"
    env = {**os.environ, "PYTHONUTF8": "1", "NO_COLOR": "1"}
    with tempfile.TemporaryDirectory(prefix="aee-install-") as directory:
        root = Path(directory)

        def command(*parts: str, code: int = 0) -> str:
            completed = subprocess.run(
                list(parts), cwd=root, env=env, text=True, encoding="utf-8",
                capture_output=True, check=False,
            )
            assert completed.returncode == code, completed.stdout + completed.stderr
            return completed.stdout

        command(specify, "init", "--here", "--integration", "claude",
                "--ignore-agent-tools", "--non-interactive")
        command(specify, "extension", "add", "--dev", str(evaluator))
        command(specify, "extension", "add", "--dev", str(aee_source))
        listed = command(specify, "extension", "list", "--json")
        installed = {item["id"]: item for item in json.loads(listed)}
        assert installed["evaluator"]["enabled"] and installed["aee"]["enabled"]
        assert installed["aee"]["provides"]["commands"] == 9
        assert installed["aee"]["provides"]["hooks"] == 5
        commands = list((root / ".claude/commands").glob("speckit.aee.*.md"))
        commands += list((root / ".claude/skills").glob("speckit-aee-*/SKILL.md"))
        assert len(commands) == 9, commands
        for path in commands:
            assert not re.search(r"__SPECKIT_COMMAND_[A-Z_]+__", path.read_text())
        hooks = yaml.safe_load((root / ".specify/extensions.yml").read_text())["hooks"]
        assert "after_verify" in hooks
        shutil.copyfile(root / ".specify/extensions/aee/templates/aee-claims.json",
                        root / "claims.json")
        claims_path = root / "claims.json"
        claims = json.loads(claims_path.read_text())
        claims["claims"][0]["status"] = "draft"
        claims["claims"][0]["evidence"] = []
        claims_path.write_text(json.dumps(claims))
        result = command(sys.executable,
                         str(root / ".specify/extensions/aee/scripts/python/run_aee.py"),
                         "assess", "--input", "claims.json", code=1)
        paths = json.loads(result)
        assert (root / paths["assessment"]).is_file()
        assert (root / paths["evaluator_result"]).is_file()
        runner = str(root / ".specify/extensions/aee/scripts/python/run_aee.py")
        command(sys.executable, runner, "gate", "--input", paths["assessment"], code=1)
        verified = json.loads(command(sys.executable, runner, "verify"))
        assert verified["valid"] and verified["entries"] == 1
        graph = json.loads(command(sys.executable, runner, "graph", "--input", "claims.json"))
        assert (root / graph["graph"]).is_file()
        challenge = json.loads(command(sys.executable, runner, "challenge",
                                       "--input", "claims.json", code=1))
        assert (root / challenge["challenge"]).is_file()
        (root / "matrix.md").write_text(
            "| Test ID | Requirements | Layer | Gate |\n"
            "| T-API-001 | Returns 200 | integration | gate-1 |\n")
        (root / "evidence").mkdir()
        command(sys.executable, runner, "gaps", "--matrix", "matrix.md",
                "--evidence", "evidence", "--output", "GAPS.md")
        assert "**Open:** 1" in (root / "GAPS.md").read_text()
        print("PASS: initialized project, both extensions, nine rendered commands, "
              "five AEE hooks, resolved placeholders, and all six installed operations")


if __name__ == "__main__":
    main()
