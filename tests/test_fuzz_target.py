"""Exercise the same target/corpus on every official OS and Python target."""

from __future__ import annotations

import importlib.util
import random
from pathlib import Path

TARGET = Path(__file__).parents[1] / "fuzz/bundle_target.py"


def test_seed_corpus_and_deterministic_mutations() -> None:
    spec = importlib.util.spec_from_file_location("bundle_target", TARGET)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    seeds = [path.read_bytes() for path in (TARGET.parent / "corpus").iterdir()]
    rng = random.Random(20261016)
    for seed in seeds:
        module.fuzz_one(seed)
        for _ in range(50):
            candidate = bytearray(seed)
            if candidate:
                candidate[rng.randrange(len(candidate))] = rng.randrange(256)
            module.fuzz_one(bytes(candidate))
    for _ in range(100):
        module.fuzz_one(rng.randbytes(rng.randrange(128)))


def test_execution_fuzz_ingestion_never_runs_the_recorded_command(monkeypatch) -> None:
    import subprocess

    spec = importlib.util.spec_from_file_location("bundle_target_no_execution", TARGET)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    def forbidden(*args, **kwargs):
        raise AssertionError("fuzzed execution records must never launch a process")

    monkeypatch.setattr(subprocess, "Popen", forbidden)
    module.fuzz_one((TARGET.parent / "corpus/execution-json").read_bytes())
    module.fuzz_one((TARGET.parent / "corpus/test-discovery-json").read_bytes())
    module.fuzz_one((TARGET.parent / "corpus/method-approval-json").read_bytes())
