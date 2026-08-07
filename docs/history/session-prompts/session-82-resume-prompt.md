# Session 82 wrap — resume prompt (cold-start for session 83+)

## ⚠️ Verify state before trusting this file

```bash
cd /Users/tokuyama/workspace/clinosim
git fetch --prune origin
git log --oneline -6 origin/master
git rev-parse --abbrev-ref HEAD       # should be `master`
git status --short                    # ideally clean
git worktree list                     # primary only
gh pr list --state open               # should be 0
gh issue list --state open            # should be 0
```

**Session 82 wrap state (2026-08-07)**:

```
origin/master  f0402c0498  chore(ci): Tier C — nightly audit + cohort byte-diff vs yesterday (#538)
               ec4e55bd25  refactor(fhir): extract post-emit helpers → _fhir_post_process.py (1808 → 689) (#537)
               b035e5ed9a  docs(changelog): session 82 — 16 PR / 4 Issue / repo hygiene / CI + file splits (#536)
               25f3e93e55  refactor(fhir): extract inline _bb_* builders → _fhir_inline_bb.py (2382 → 1808) (#535)
               f6b250abe5  refactor(cli): split cli.py by subcommand family — 1845 → 780 lines (#534)
               fbf85cc1a3  chore(ci,docs): coverage report + publishing-to-pypi runbook (#533)
open PR    = 0
open Issue = 0
```

If your measurement differs, someone (autonomous CC in the shared worktree, or a person) has moved things since the wrap.

---

## 1. Session 82 was a **massive housekeeping session** — 19 PRs merged

Session 82 opened at `99fc94b593` (session 81 wrap) with 4 open Issues (#460 / #440 / #439 / #433) and ended at `f0402c0498` with all Issues closed + a comprehensive OSS-structure overhaul.

### Issue implementations (4 PR)

| PR | Issue | Change |
|----|-------|--------|
| #521 | #460 | escalation `type: "procedure"` signal — 6 latent misclassify entries now emit as `Procedure` |
| #522 | #439 | sub-RNG isolation for drug selection (AD-16 pattern, sibling of `panel_specimen_seed`) |
| #523 | #433 | `baseline_chronic_medications` immutable field for renal-hold restart |
| c7f0c31071 | #440 | `drug_name_ja` threading through `discharge_prescription.items[]` (autonomous CC direct-push to master — workflow anomaly, noted) |

### Repo hygiene (6 PR A-F, series #524-#529)

- **A #524**: `.tar.gz` maintainer artifacts (3 files) untracked, `.gitignore` unified
- **D #525**: 13 `docs/session-*.md` → `docs/history/session-prompts/`
- **B #526**: 30 `scratchpad/` audit artifacts → `docs/history/scratchpad-archive/`, root `scratchpad/` gitignored
- **E #527**: `CLAUDE.md` → `AGENTS.md` (agentmd.dev convention, pointer preserved)
- **F #528**: historical `spec.md` (2026-04) + `DES_MIGRATION.md` → `docs/history/` with index README
- **C #529**: `test_data/` (5392 files / 200MB accumulated LLM eval outputs) untracked

### CI simplification (G #530)

- PR gate: **13 → 9 checks** (drop `integration_serial`, drop Py 3.11 from unit matrix, merge `lint`+`typecheck` → `quality`, move `reproducibility` to nightly, add `paths` filter to JP-CLINS gate)
- New `.github/workflows/nightly.yml` (rate-of-change gates: reproducibility + Py 3.11 + [added later in Tier C] audit + cohort byte-diff)

### Tier B — file splits (H/I/J/K/L, 5 PR)

| PR | file | before | after | reduction |
|----|------|--------|-------|-----------|
| #531 | module README | 30/31 | 31/31 + durable CI gate | — |
| #532 | `simulator/inpatient.py` | 2560 | 2338 (`discharge_rx.py` extracted) | -222 |
| #533 | CI + docs | — | coverage report in CI + PyPI publish runbook | — |
| #534 | `simulator/cli.py` | 1845 | 780 (7 sibling modules) | -1065 |
| #535 | `modules/output/fhir_r4_adapter.py` | 2382 | 1808 (`_fhir_inline_bb.py` extracted) | -574 |
| #537 | `modules/output/fhir_r4_adapter.py` | 1808 | **689** (`_fhir_post_process.py` extracted) | -1119 |

`fhir_r4_adapter.py`: **2382 → 689 (-1693 lines total across PR L+N)**.

### Wrap docs / infrastructure (M/O, 2 PR)

- **M #536**: CHANGELOG updated with all session-82 changes
- **O #538**: Tier C — nightly `clinosim audit run` (US+JP p=100) + cohort byte-diff vs yesterday's baseline

## 2. Determinism verification (byte-diff protocol established)

All 3 large-file refactors (I / K / L+N) verified **byte-neutral** via pre/post cohort byte-diff:

```
US p=30 seed=42:  24/24 FHIR NDJSON files identical
CIF content:      identical (only generation_timestamp differs, wall-clock)
```

New protocol (memory: `feedback_verify_beyond_unit_tests.md`) — refactor completion claim now requires:
1. `pytest tests/unit` — 3871 pass
2. `clinosim generate -p 30 -s 42 --format fhir-r4` — E2E produces valid FHIR
3. `cmp -s` NDJSON vs pre-refactor baseline (git worktree of prior commit)

## 3. New CI structure (post-session 82)

**Per-PR (9 checks)**:
- Unit tests (Py 3.12)
- Integration tests × 3 shards (pytest-split + xdist)
- Quality (ruff check + format + mypy, informational)
- Build sdist + wheel
- Docs build
- DCO signoff
- JP-CLINS gate (paths-filtered — skips docs-only PRs)

**Nightly (`.github/workflows/nightly.yml`)**:
- `reproducibility` — `scripts/reproduce.sh` (SemVer determinism)
- `unit-py311` — compat floor
- `audit` — `clinosim audit run` on US + JP p=100 seed=42 cohorts
- `cohort-byte-diff-vs-master` — today's cohort vs yesterday's cached baseline

## 4. Known follow-ups (session 83+ candidates)

### Immediate value (documented, not blocking)

- **PyPI initial publish** — release.yml + runbook (`docs/development/publishing-to-pypi.md`) ready; user needs to (1) register `clinosim` on PyPI, (2) add Trusted Publisher, (3) uncomment 2 blocks in release.yml, (4) `git tag v0.3.0`. Step-by-step in the runbook.
- **First nightly run of Tier C** will populate the cohort-byte-diff baseline; from day 2 onward it becomes a real gate.
- **Codecov integration** — pyproject dev extras + CI XML upload ready; user adds `CODECOV_TOKEN` secret + uncomments the step in `ci.yml::unit` to activate.

### Backlog structural work

- `fhir_r4_adapter.py` is now 689 lines — down from 2382. If further split is desired (e.g. extract `convert_cif_to_fhir` orchestration into a `bundle_orchestrator.py`), it's small scope now.
- Test suites still import from `fhir_r4_adapter.py` for names now living in `_fhir_inline_bb.py` / `_fhir_post_process.py` (via back-compat re-exports). Migrate test imports to canonical modules → drop the re-export blocks (small PR per test file).
- Discharge chain test import migration: `_build_discharge_rx` → `build_discharge_rx` from `discharge_rx.py`.

### Larger-scope work

- **Tier D** (naming, undocumented): further `test_data/` and root cleanup if additional accumulated artifacts appear
- **Version bump path**: session 82 introduced no cohort-visible schema changes (byte-diff neutral), so the next version bump can be PATCH. First cohort-visible change → MINOR bump per SemVer + CHANGELOG.

## 5. Session-82-specific lessons (memory)

Added to `~/.claude/projects/-Users-tokuyama-workspace-clinosim/memory/`:

- `feedback_verify_beyond_unit_tests.md` (★★★★★) — refactor claim requires unit + E2E + byte-diff
- `feedback_pyenv_shim_use_correct_worktree.md` (★★★★) — `cd worktree && PYTHONPATH=. clinosim ...` — both needed
- `feedback_worktree_only_for_shared_interference.md` (★★★★, added earlier in session) — isolated worktree only when concurrent CC detected

## 6. Session-82 first commands

```bash
cd /Users/tokuyama/workspace/clinosim
git fetch --prune origin
git log --oneline -3 origin/master        # verify wrap state (see top of this doc)
git branch --show-current                 # must be master
git status --short                        # clean
git worktree list                         # primary only
gh pr list --state open                   # 0
gh issue list --state open                # 0

# If everything matches, you're ready to start session 83.
# First look at what got merged since session 82 wrap:
git log --oneline f0402c0498..origin/master

# The nightly ran overnight — check its result:
gh run list --workflow=nightly.yml --limit 1

# If autonomous CC has been active, `git branch -a` will show extra branches.
```

## 7. Where to find things

| Content | Location |
|---------|----------|
| Project concept + pipeline | `docs/design-guides/project-concept-and-design.md` |
| Implementation invariants | `docs/design-guides/implementation-rules.md` |
| Live backlog | `gh issue list --state open` (TODO.md gitignored since session 80) |
| Session 82 PR record | #521-#538 (16 code + 3 wrap PRs — see §1 above) |
| Personal memory | `~/.claude/projects/-Users-tokuyama-workspace-clinosim/memory/MEMORY.md` |
| Vault (cross-project knowledge) | `~/workspace/obsidian/` (start with `INDEX.md`) |
| AGENTS.md (canonical agent instructions) | root `AGENTS.md` |
| PyPI publish runbook | `docs/development/publishing-to-pypi.md` |
