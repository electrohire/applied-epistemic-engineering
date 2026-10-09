# Tasks: Baseline — Current State of the AEE Engine (v1.4.0)

**Input**: Design documents from `specs/001-baseline-current-state/`

**Prerequisites**: plan.md (required), spec.md (required), claims.json

**Tests**: This is a baseline spec — its tasks are verification and
onboarding tasks against already-shipped behavior. The project's own
test suite (`tests/`, 118 tests) is the evidence base; no new feature
tests are written here.

**Organization**: Phase 1 is the spec-kit onboarding itself; Phases 2–4
verify the baseline claims (C-001…C-006) story by story; the final phase
records the open follow-ups honestly instead of closing them by assertion.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story / claim the task verifies (US1–US5, ONB = onboarding)
- Include exact file paths in descriptions

---

## Phase 1: Spec-Kit + AEE Onboarding (ONB)

**Purpose**: Bring the repo to the onboarding acceptance bar without
touching engine code, tests, or docs.

- [x] T001 [ONB] Record before-state: git repo on `main` @ `31f39af`, clean tree, no `.specify/`, no `specs/` (verified by `git status` + `ls`, 2026-10-08)
- [x] T002 [ONB] Create dedicated branch `chore/speckit-onboarding` from `main`
- [x] T003 [ONB] Initialize Spec Kit into the existing repo: `specify init --here --force --non-interactive --integration copilot --script sh` (specify 1.0.10 at `~/workspace/venvs/spec-kit/bin/specify`) → `.specify/` scaffold
- [x] T004 [ONB] Install AEE extension: `yes | specify extension add ~/workspace/electrohire/spec-kit-aee --dev` → `.specify/extensions/aee/` (extension v1.2.0, 9 commands) and `aee` entry in `.specify/extensions.yml`
- [x] T005 [ONB] Install evaluator extension: `yes | specify extension add ~/workspace/electrohire/spec-kit-evaluator --dev` → `.specify/extensions/evaluator/` (extension v1.0.0, 4 commands) and `evaluator` entry in `.specify/extensions.yml`
- [x] T006 [ONB] Prune the extension install copies of nested `.git/`, `.venv-hatch/`, `__pycache__/`, `.pytest_cache/`, `.ruff_cache/`, and `.hypothesis/` so `.specify/extensions/` commits as plain files, not embedded git repos (129 MB → ~464 KB total)
- [x] T007 [ONB] Write project-specific constitution at `.specify/memory/constitution.md` (v1.0.0, Principles I–VIII grounded in README.md + `docs/concepts.md` / `scoring.md` / `ledger.md` / `security.md` / `porting-from-epistemic-ledger.md` + CONTRIBUTING.md) — never the raw template
- [x] T008 [ONB] Write this baseline trio + claims at `specs/001-baseline-current-state/{spec.md,plan.md,tasks.md,claims.json}` grounded only in the repo's own README / docs / CHANGELOG / code

**Checkpoint**: `.specify/` + `specs/001-baseline-current-state/` exist on disk and satisfy the acceptance bar; no other repo files modified.

---

## Phase 2: Verify Core Assessment Loop (US1, US2 — Claims C-001, C-002, C-005, C-006)

**Goal**: Prove the assess / challenge loop and its contracts on the shipped code.

**Independent Test**: pytest suite + `aee demo` + CLI help, all runnable offline.

- [x] T009 [P] [US1] Run full suite: `PYTHONPATH=src python -m pytest -q` → **118 passed, 0 failed** (2026-10-08)
- [x] T010 [P] [US1] Run `PYTHONPATH=src python -m aee demo` → self-contained assessment, outcome `pass`, claim `REQ-DEMO-001` direct/propagated score 0.9
- [x] T011 [P] [US1] Confirm version single-sourcing: `aee --version`, `src/aee/__init__.py`, and `pyproject.toml` all report **1.4.0**
- [x] T012 [P] [US2] Confirm CLI surface in `src/aee/cli.py` / `--help`: subcommands `assess, challenge, verify-ledger, gate, graph, gaps, review, demo` (8) with the README 0/1/2 exit-code contract
- [ ] T013 [US1] Falsifier check for C-002: construct a two-claim set where the dependent's direct score exceeds its premise's, assess it, and confirm the propagated score is capped at the premise's (weakest link, `src/aee/scoring.py`); record the run output alongside this spec if the check is ever automated
- [ ] T014 [US2] Falsifier check for C-001: run the same pinned claims file twice with a fixed `as_of` and diff the assessments; any difference beyond timestamps falsifies the replayability claim

**Checkpoint**: US1/US2 claims are evidence-backed by a green suite and live CLI runs; the two manual falsifier checks remain open and are stated as such.

---

## Phase 3: Verify Ledger, Ported Mechanisms, and Gaps (US3, US4, US5 — Claims C-003, C-004)

**Goal**: Prove the ledger limits and the opt-in 1.1.0–1.4.0 mechanisms hold as documented.

- [x] T015 [P] [US3] Confirm ledger test coverage passes in `tests/test_ledger.py` (chain verification, append lock, corruption `ValueError`, O(1)-append cache) as part of the T009 suite run
- [x] T016 [P] [US4] Confirm ported-mechanism coverage passes in `tests/test_policy.py`, `tests/test_reliability.py`, `tests/test_review.py`, and `tests/test_cli_policy.py` as part of the T009 suite run
- [x] T017 [P] [US5] Confirm gap-register coverage passes in `tests/test_gaps.py` (stable `test_id` preservation, documented statuses, close-nonexistent error) as part of the T009 suite run
- [ ] T018 [US3] Falsifier check for C-003: append to a scratch ledger in /tmp, edit a middle line, and confirm `aee verify-ledger` fails; confirm no ledger-facing text in `docs/ledger.md` / CLI output claims truth, authorship, or trusted time
- [ ] T019 [US4] Falsifier check for C-004: assess a fixed claims file with and without `--policy` / `--reliability` and confirm scores (not verdicts) are unchanged, per `docs/porting-from-epistemic-ledger.md`

**Checkpoint**: US3–US5 are covered by the passing suite; the two scratch falsifier runs remain open follow-ups.

---

## Phase 4: Commit and Hand Off (ONB)

- [x] T020 [ONB] Verify `git status` shows only onboarding paths (`.specify/`, `specs/`) as committable; engine source, tests, and docs untouched
- [ ] T021 [ONB] Commit ONLY `.specify/` and `specs/` on `chore/speckit-onboarding` with repo-local git identity if needed (`tbitcs <tbitcs@users.noreply.github.com>`)
- [ ] T022 [ONB] Decide with the owner whether a PR is opened from `chore/speckit-onboarding` — the repo's flow is PR-based, but this onboarding pass does not push or merge; left for the parent/owner

---

## Phase 5: Open Follow-Ups (recorded, not silently closed)

- [ ] T023 [ONB] Resolve the `.github/skills/` question with the owner: `specify init` + extension installs generated `.github/skills/` (Copilot skills; the aee/evaluator entries are symlinks into `.specify/extensions/*/.specify-dev/extension-skills/`). Left **untracked** by this pass — committing broken-or-fragile symlinks has previously broken deployments in sibling projects, and the onboarding commit scope is `.specify/` + `specs/` only. Verification condition: owner decision recorded and the chosen state (committed with targets present, or ignored in `.gitignore`) visible in `git status`
- [x] T024 [ONB] Run the AEE engine against this baseline's claims: `PYTHONPATH=src python -m aee assess --input specs/001-baseline-current-state/claims.json --phase after_specify --output specs/001-baseline-current-state/assessment.json` → outcome **iterate**, 6 claims assessed, all propagated scores ≥ 0.99 (0 below the 0.70 threshold), 7 failure modes recorded in the filed assessment — 6 irreducibility challenges (the C-001…C-006 summary claims are compound; their atomic form is FR-001…FR-014 in spec.md) and 1 negation-conflict flag between C-004 and C-005 (heuristic flag, preserved for review per Constitution III, not averaged away). Note: the first assess run correctly rejected an invalid `SourceQuality` value (`documentation` → corrected to the valid enum value `artifact`) with exit 2 and a clean message — live evidence for the FR-012 error contract

---

## Dependencies & Execution Order

- Phase 1 (T001–T008) blocks everything: the constitution and baseline
  are the artifacts the later phases verify against.
- Phase 2 and Phase 3 verification tasks marked [P] are independent and
  were run against the same checkout; T013/T014/T018/T019 are manual
  falsifier checks that can run any time after Phase 1.
- Phase 4 depends on Phases 1–3 checkpoints. T021 is the commit step for
  this pass; T022 (PR) is an owner/parent decision, not part of it.
- Phase 5 items are deliberately open: they need an owner decision
  (T023) or are optional extras (T024).

## Notes

- [P] tasks = different files / read-only checks, no dependencies.
- Every checked task above was executed on this checkout on 2026-10-08
  and its result is stated with the task; unchecked tasks are open by
  design, not by omission.
- The system interpreter on the verification machine has no installed
  `aee` distribution, so Python commands run with `PYTHONPATH=src`;
  that is an environment fact, not a product defect.
