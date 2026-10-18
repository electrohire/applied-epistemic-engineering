# Contributing

1. Open an issue describing the change and its epistemic impact.
2. Add or update tests for every behavior change.
3. Run `ruff format --check .`, `ruff check .`, `mypy src/aee`, and `pytest`.
4. Keep deterministic checks separate from model-generated judgments.
5. Never upgrade an assertion to observed evidence without an independently inspectable source.

By contributing, you agree that your contribution is licensed under the MIT License.

## Fuzz testing

`pytest tests/test_fuzz_target.py` exercises the shared input-boundary target,
seed corpus, and reproducible mutations on all supported operating systems.
The ClusterFuzzLite workflow additionally runs coverage-guided Atheris fuzzing
in its official Linux container on pull requests and main pushes. This container
is supplemental testing; Linux, macOS, and Windows remain equally supported.

Input bytes0/1 select claim JSON/Markdown;2 selects strict execution-record JSON
and3 selects bounded JUnit parsing. Selector4 ingests test-discovery records.
Other bytes retain even/odd claim routing.
Execution fuzzing only ingests data and never runs the recorded command. The
remaining bytes are the selected document. Invalid input may be rejected, but accepted input must be
assessable without an unexpected exception or mutation of the original file.
Preserve minimized crash inputs as regression tests when fixing a fuzz finding.

Changes should receive independent human review before merging. Automated
checks and agent self-review do not count as an independent approval.
