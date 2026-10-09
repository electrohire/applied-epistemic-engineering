# Contributing

Use issues and pull requests. Keep domain logic in
[applied-epistemic-engineering](https://github.com/electrohire/applied-epistemic-engineering)
and this repository a thin adapter to
[Evaluator Contract](https://github.com/electrohire/spec-kit-evaluator).
Preserve distinctions among observed, inferred, asserted, contradicted, and
unsupported evidence. Add regression tests for changed execution or path behavior.

## Reproduce CI

Use Python 3.11 or later in an activated virtual environment:

```bash
python -m pip install --require-hashes -r requirements/dev.txt
python -m ruff check scripts tests
python -m pytest -q
python scripts/python/run_aee.py --help
```

The lock includes the real AEE engine and Spec Kit manifest parser. Tests require
`aee` on PATH and fail when it is missing; integration coverage must not silently
skip because a runtime dependency was omitted. Linux CI exercises symlink tests;
Windows may skip the symlink test when the host disallows creating symlinks.
The CI matrix tests Python 3.11 and 3.13 on Linux and Python 3.12 on Windows.

For a clean install smoke, clone the Evaluator dependency at its published v1.0.0
commit `e6e86e1ca2c99c167375953ad8d682913f3de244`, then run:

```bash
python scripts/check_install.py --evaluator-dir /path/to/spec-kit-evaluator
```

This uses Spec Kit's own CLI to initialize a disposable project, installs both
extensions, checks registered commands/placeholders and hooks, and runs an
assessment through the installed adapter. It performs no model inference.
The test workflow runs it against the same pinned Evaluator commit. CodeQL and
dependency review run on PRs. OpenSSF Scorecard runs on main/schedule; its latest
main result is not a PR-head analysis.

Regenerate the hash lock after deliberately editing `requirements/dev.in`:

```bash
uv pip compile requirements/dev.in --generate-hashes --python-version 3.11 --output-file requirements/dev.txt
```

Do not commit generated assessment data, credentials, or private evidence.

## Metadata, release, and catalog corrections

Follow Spec Kit's [extension API reference](https://github.com/github/spec-kit/blob/main/extensions/EXTENSION-API-REFERENCE.md)
and [publishing guide](https://github.com/github/spec-kit/blob/main/extensions/EXTENSION-PUBLISHING-GUIDE.md).
Use documented `requires.tools` entries for Python, the `aee` executable, and the
Evaluator extension. The entries are informational; `requires.commands` is not a
supported dependency-enforcement mechanism. Keep the README dependency table and
minimum versions synchronized with commands the adapter actually invokes.

1. Make a branch and PR, bump the patch version for a compatible fix, and add an
   unreleased changelog entry. Validate the manifest with Spec Kit and run the
   locked tests and install smoke. Review all CI/security checks on the final commit.
2. After review/merge, publish the matching immutable version tag and release.
   Do not move an existing tag or advertise an unpublished archive as installable.
3. Test the public release archive, then file a **new Extension Submission issue**
   identifying it as an update to the existing `aee` entry. Include both dependency
   repository URLs, required versions, and truthful testing details.
4. For a metadata-only correction to the current release, retain its existing
   version/download URL and explain that the archive is unchanged. Reference the
   original [submission #4565](https://github.com/github/spec-kit/issues/4565).

Do not open a direct PR against Spec Kit's community catalog. Maintainers triage
submission issues; do not request labels or mark unperformed checks as complete.
The pending 1.0.1 manifest is not a released artifact until step 2 is complete.

By contributing, you agree to the MIT license.
