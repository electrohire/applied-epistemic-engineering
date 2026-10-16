# Version policy

Spec 002 FR-4 exists because installed engines diverged in the field
(1.0.2 in one environment, 1.4.0 in another) while assessments carried
no record of which engine produced them. This policy keeps the three
versioned surfaces — the engine, the spec-kit-aee extension, and the
upstream spec-kit catalog entry — coherent.

## The engine version is the source of truth

- The engine's version is `aee.__version__`, defined exactly once in
  `src/aee/_version.py`. The `version` field in `pyproject.toml` is
  kept in lockstep with it at release time; if the two ever disagree,
  `aee.__version__` is what the code stamps and reports.
- `aee --version` prints that string, and every assessment stamps it
  as `metadata.engine_version` (FR-4.1). The stamp is applied by the
  engine after caller metadata, so it cannot be overridden or
  fabricated by a caller. A test asserts the `--version` output and
  the stamp cannot drift (FR-4.4).
- `methodology_version` is a **distinct, separately-versioned** field
  on the assessment. It changes only when the assessment methodology
  itself changes (for example, scoring-semantics changes), on its own
  schedule — never merely because the package version moved.

## The extension's `requires` floor is the compatibility contract

- [`spec-kit-aee`](https://github.com/electrohire/spec-kit-aee) declares the engine versions it works
  with in its `extension.yml` (`requires.tools` entry for `aee`,
  currently `>=1.5.0,<2`). That floor — not any one machine's installed
  copy — is the compatibility contract between the two repos.
- The extension runner enforces the floor at startup and records its
  own version in assessments it produces as
  `metadata.extension_version` (FR-4.2). Assessments produced by the
  bare CLI omit that key rather than fabricating it.
- An extension release that raises the engine floor must name the
  engine release that satisfies it, and vice versa: an engine release
  that breaks the extension's declared range must be coordinated with
  an extension release that updates the range.
- The extension runner installs the latest engine in that range
  automatically when its Python lacks one, so an engine patch or minor
  release within the range reaches Spec Kit users without an extension
  release.

## The catalog entry follows every extension release

- After each extension release is published and its exact public
  archive is tested, the upstream spec-kit catalog entry is updated
  through a **new Extension Submission issue** marked as an update to
  the existing entry. Spec Kit does not accept direct pull requests to
  its catalog; a maintainer's triage starts validation, which opens the
  catalog pull request. A catalog entry lagging the released extension
  (as the 1.0.1 entry lagged the 1.2.0 release) should be resubmitted
  promptly.
- The submission uses the current upstream form unchanged, with the
  download URL pinned to the release tag being submitted (see the
  extension's CONTRIBUTING.md release checklist).

## Releases

Publishing remains owner-gated: version bumps, tags, PyPI releases,
and catalog submissions each happen only on the owner's say-so. This
policy governs how the versions relate when a release does happen; it
does not authorize one.
