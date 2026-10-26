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
