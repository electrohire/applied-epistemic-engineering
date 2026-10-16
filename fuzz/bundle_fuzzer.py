"""Atheris entry point; production modules are imported under instrumentation."""

import sys

import atheris

with atheris.instrument_imports():
    from bundle_target import fuzz_one

if __name__ == "__main__":
    atheris.Setup(sys.argv, fuzz_one)
    atheris.Fuzz()
