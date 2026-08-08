# PR2: `fhir_r4/{demographics,encounters,medications,labs,procedures,conditions,documents}/` clinical-domain builders

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans`. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the 29 remaining FHIR resource-builder and JP-CLINS lab-support files at `clinosim/modules/output/` root into 7 clinical-domain subdirectories under `fhir_r4/`, fix 2 hardcoded `Path(__file__).parents[N]` references that break silently on relocation, migrate 96 caller sites, and add a FHIR-resource ↔ domain mapping README — all byte-neutral vs `master` at PR1 tip.

**Architecture:** Clinical-domain grouping (Option B from the spec). Each domain becomes a Python subpackage with a bare `__init__.py`. No shim shortcut for the `_fhir_<resource>` paths — callers migrate atomically inside the PR because a symmetric "both paths work" shim would defeat the entire discoverability goal (per spec § "Backward compatibility contract"). File-name prefix `_fhir_` is dropped (the `fhir_r4/` subpackage boundary makes it redundant); internal symbol names are unchanged.

**Tech Stack:** Python 3.12, `git mv`, `ruff==0.16.0` (pinned to CI), `mypy` strict, `pytest`.

## Global Constraints

Copied verbatim from the design spec (`docs/superpowers/specs/2026-08-08-output-fhir_r4-subpackage-design.md`):

- Base branch: `master` after PR #605 (PR1) merges. This PR CANNOT start until PR #605 is merged, because the layout it produces is PR2's precondition.
- Byte-neutral output required. 30-patient seed 42 JP+US cohort resource-level `diff -r` must show only timestamp fields (`generated_at`, `generation_timestamp`, `transactionTime`) differing — same success criterion as PR1.
- `pytest tests/unit` must remain at **3968 pass** (session 84 wrap baseline, matched by PR1).
- `mypy clinosim/` under strict mode must remain clean.
- `ruff==0.16.0 check clinosim tests` and `ruff format --check clinosim tests` must remain clean. **Install pinned ruff locally** (`python -m pip install ruff==0.16.0`) BEFORE first `ruff check`, per memory rule `feedback_ci_local_tool_version_divergence.md` — PR1 needed a fixup commit for this exact class of drift.
- Internal symbol names (`_build_X`, `_bb_Y` etc.) are **unchanged**. Symbol renaming is Issue #545 Step 2, out of scope.
- Must not commit to `master` directly. All work happens on branch `refactor/555-fhir-r4-domain-builders-pr2`.
- Every commit uses `--signoff` (DCO check).
- **Every builder file that uses `Path(__file__).resolve().parents[N]` MUST have its `N` audited when moved and updated to the new depth.** The 2 known cases (`_fhir_medications.py:296` → `parents[2]` needs `parents[4]`; `lab_coding_package.py:545` → `parents[3]` needs `parents[5]`) are called out in Task 2. Silent breakage here is the exact class of regression that killed closed PR #604 (`_TX_SERVER_VERIFIED_YJ_CODES` went to 0 with no test caught it because the fragment loader returned `frozenset()` on `FileNotFoundError`). Task 5's direct probe verifies both.

---

## File Structure

Files created (new — 7 empty package markers):

- `clinosim/modules/output/fhir_r4/demographics/__init__.py`
- `clinosim/modules/output/fhir_r4/encounters/__init__.py`
- `clinosim/modules/output/fhir_r4/medications/__init__.py`
- `clinosim/modules/output/fhir_r4/labs/__init__.py`
- `clinosim/modules/output/fhir_r4/procedures/__init__.py`
- `clinosim/modules/output/fhir_r4/conditions/__init__.py`
- `clinosim/modules/output/fhir_r4/documents/__init__.py`
- `clinosim/modules/output/fhir_r4/README.md` — FHIR resource type → domain subdir mapping table.

Files moved (29 total) with `git mv` and file-name normalization (`_fhir_` prefix dropped, all lowercase snake_case):

### demographics/ (4 files)
| Source | Target |
|---|---|
| `_fhir_patient.py` | `fhir_r4/demographics/patient.py` |
| `_fhir_practitioner.py` | `fhir_r4/demographics/practitioner.py` |
| `_fhir_family_history.py` | `fhir_r4/demographics/family_history.py` |
| `_fhir_smoking_alcohol.py` | `fhir_r4/demographics/smoking_alcohol.py` |

### encounters/ (5 files)
| Source | Target |
|---|---|
| `_fhir_encounter.py` | `fhir_r4/encounters/encounter.py` |
| `_fhir_care_team.py` | `fhir_r4/encounters/care_team.py` |
| `_fhir_care_level.py` | `fhir_r4/encounters/care_level.py` |
| `_fhir_facility.py` | `fhir_r4/encounters/facility.py` |
| `_fhir_endpoint.py` | `fhir_r4/encounters/endpoint.py` |

### medications/ (1 file, **REQUIRES `parents[N]` FIX**)
| Source | Target | Path fix |
|---|---|---|
| `_fhir_medications.py` | `fhir_r4/medications/medications.py` | line 296: `parents[2]` → `parents[4]` |

### labs/ (7 files, **1 REQUIRES `parents[N]` FIX**)
| Source | Target | Path fix |
|---|---|---|
| `_fhir_observations.py` | `fhir_r4/labs/observations.py` | — |
| `_fhir_diagnostic_report.py` | `fhir_r4/labs/diagnostic_report.py` | — |
| `_fhir_service_request.py` | `fhir_r4/labs/service_request.py` | — |
| `_fhir_microbiology.py` | `fhir_r4/labs/microbiology.py` | — |
| `_fhir_imaging_study.py` | `fhir_r4/labs/imaging_study.py` | — |
| `lab_coding_package.py` | `fhir_r4/labs/coding_package.py` | line 545: `parents[3]` → `parents[5]` |
| `_lab_coding_strategy.py` | `fhir_r4/labs/coding_strategy.py` | — |

### procedures/ (4 files)
| Source | Target |
|---|---|
| `_fhir_procedures.py` | `fhir_r4/procedures/procedures.py` |
| `_fhir_immunization.py` | `fhir_r4/procedures/immunization.py` |
| `_fhir_device.py` | `fhir_r4/procedures/device.py` |
| `_fhir_nursing.py` | `fhir_r4/procedures/nursing.py` |

### conditions/ (5 files)
| Source | Target |
|---|---|
| `_fhir_conditions.py` | `fhir_r4/conditions/conditions.py` |
| `_fhir_allergy_intolerance.py` | `fhir_r4/conditions/allergy_intolerance.py` |
| `_fhir_clinical_impression.py` | `fhir_r4/conditions/clinical_impression.py` |
| `_fhir_hai.py` | `fhir_r4/conditions/hai.py` |
| `_fhir_code_status.py` | `fhir_r4/conditions/code_status.py` |

### documents/ (3 files)
| Source | Target |
|---|---|
| `_fhir_composition.py` | `fhir_r4/documents/composition.py` |
| `_fhir_documents.py` | `fhir_r4/documents/documents.py` |
| `_fhir_document_reference_checkup.py` | `fhir_r4/documents/document_reference_checkup.py` |

### Files that stay at `output/` root (unchanged in PR2)
- `adapter.py`, `adapters_builtin.py`, `csv_adapter.py` — format-adapter layer, not FHIR-specific
- `cif_reader.py`, `cif_writer.py` — CIF I/O
- `hospital_course_extractor.py` — CIF→LLM helper
- `_fhir_common.py` — Issue #545 deprecation shim (still emits `DeprecationWarning`, targets `fhir_r4/lib/common` since PR1)
- `fhir_r4_adapter.py` — thin re-export shim added in PR1
- `_fhir_post_process.py` — deferred to PR3 (folds #556)
- `__init__.py` — package `__init__` (may need a re-anchor if any of its re-exports move; currently only re-exports adapter registry, unlikely affected)

## Interface contract (produced by PR2)

Downstream PR3 will consume:

- All import paths for the 29 moved files use their new domain-scoped location. Example: `from clinosim.modules.output.fhir_r4.medications.medications import _build_medication_request`.
- `fhir_r4/__init__.py` (the facade promoted in PR1) already imports from `fhir_r4.lib.*` for shared helpers, and its per-builder imports are updated in PR2 Task 4 to point at the new domain paths.
- `output/_fhir_post_process.py` is the last remaining file at `output/` root with a `_fhir_` prefix — PR3 splits and moves it.

## Backward compatibility

**No shims for the moved builder modules.** Rationale (per spec § "Backward compatibility contract"): the `_fhir_<resource>` paths were private-underscore names; the 96 caller sites are all inside this repository (internal API), so atomic migration inside this PR is safer than a symmetric-shim shortcut. A shim would defeat the discoverability goal by making both paths valid indefinitely.

The two existing shims from earlier work are unchanged:
- `fhir_r4_adapter.py` (thin shim from PR1) — its internal imports need Task 4 update to point at new domain paths.
- `_fhir_common.py` (Issue #545 deprecation shim, retargeted in PR1) — unaffected by PR2 (still points at `fhir_r4/lib/common`).

## Verification protocol (each step in Task 5)

Before pushing:

1. `ruff==0.16.0 check clinosim tests` — clean.
2. `ruff format --check clinosim tests` — clean.
3. `mypy clinosim/` — clean under strict mode.
4. `pytest tests/unit` — **3968 pass** (matches master baseline).
5. **Direct probe of `_TX_SERVER_VERIFIED_YJ_CODES`** — must load **2000 codes** (PR #604 broke this to 0). This is the single most important post-move check.
6. **Direct probe of `lab_coding_package._first_existing(*sd_candidates)`** — must find the JP-CLINS SD file when `CLINOSIM_JP_CLINS_PKG_DIR` is set. If it returns None, the `parents[N]` fix is wrong.
7. `clinosim generate -p 30 -s 42 --country US --format fhir-r4 --out <SCRATCH/pr2-branch/us>` — succeeds.
8. `clinosim generate -p 30 -s 42 --country JP --format fhir-r4 --out <SCRATCH/pr2-branch/jp>` — succeeds (`CLINOSIM_JP_CLINS_PKG_DIR` env var required).
9. `diff -r <PR1-tip cohort baseline> <SCRATCH/pr2-branch>` — resource-level diff = **timestamps only** (same 12-line pattern PR1 established). PR1 tip already differs from master only in file paths and shim redirects; PR2 must preserve that byte-neutral output.
10. `git branch --show-current` = `refactor/555-fhir-r4-domain-builders-pr2`, NOT master.

---

## Task 1: Branch + subpackage skeleton + README

**Files:**
- Create: 7 domain `__init__.py` files.
- Create: `fhir_r4/README.md`.
- Commit: `docs/superpowers/plans/2026-08-08-output-fhir_r4-pr2-domain-builders.md`.

**Interfaces:**
- Consumes: PR1's `fhir_r4/` subpackage.
- Produces: 7 empty domain subpackages importable, `fhir_r4/README.md` with the resource ↔ domain mapping table.

- [ ] **Step 1: Verify PR1 merged and starting state clean.**

```bash
git fetch --prune origin
git checkout master
git pull --ff-only origin master
git log --oneline -3
```
Expected: top commit is PR #605 merge. If not, STOP — PR2 depends on PR1's layout.

```bash
git branch --show-current           # expected: master
git status --short                  # expected: (empty)
python -m pytest tests/unit --tb=no -q 2>&1 | tail -3
```
Expected: `3968 passed`. If not, STOP — surface regression before beginning PR2 work.

- [ ] **Step 2: Install pinned ruff (avoid PR1's fixup pattern).**

```bash
python -m pip install ruff==0.16.0
ruff --version                       # expected: ruff 0.16.0
```

- [ ] **Step 3: Create branch.**

```bash
git checkout -b refactor/555-fhir-r4-domain-builders-pr2
```

- [ ] **Step 4: Create the 7 domain subpackages.**

```bash
mkdir -p clinosim/modules/output/fhir_r4/{demographics,encounters,medications,labs,procedures,conditions,documents}
```

Write each `__init__.py` (7 files, identical shape):

```python
"""FHIR R4 resource builders — {DOMAIN} clinical domain (Issue #555 PR2).

Each module in this package produces FHIR fragments for one resource type
(or a tightly-scoped group). See `../README.md` for the FHIR resource →
domain mapping.
"""

from __future__ import annotations
```

Substitute `{DOMAIN}` per file: `demographics`, `encounters`, `medications`, `labs`, `procedures`, `conditions`, `documents`.

- [ ] **Step 5: Write `fhir_r4/README.md` with the mapping table.**

Write `clinosim/modules/output/fhir_r4/README.md`:

```markdown
# `fhir_r4/` — FHIR R4 output subsystem

Layout: shared library + 7 clinical-domain builder subpackages + post-processing.

- `lib/` — shared helpers (`common`, `localization`, `reference_data`, `inline_bb`, `generator_metadata`, `ids`).
- `demographics/`, `encounters/`, `medications/`, `labs/`, `procedures/`, `conditions/`, `documents/` — resource builders grouped by clinical domain.
- `post_process/` — bundle-level pipeline (PR3).

The subpackage's `__init__.py` is the public facade (`register_bundle_builder`, `available_builders`, `convert_cif_to_fhir`, ...). A thin shim at `../fhir_r4_adapter.py` re-exports the same surface for backward compatibility.

## FHIR resource → domain mapping

| FHIR resource | Domain module |
|---|---|
| Patient | `demographics/patient.py` |
| Practitioner | `demographics/practitioner.py` |
| FamilyMemberHistory | `demographics/family_history.py` |
| Observation (smoking / alcohol / social) | `demographics/smoking_alcohol.py` |
| Encounter | `encounters/encounter.py` |
| CareTeam | `encounters/care_team.py` |
| CareLevel (custom Observation) | `encounters/care_level.py` |
| Location + Organization | `encounters/facility.py` |
| Endpoint | `encounters/endpoint.py` |
| MedicationRequest, MedicationAdministration | `medications/medications.py` |
| Observation (lab + vitals) | `labs/observations.py` |
| DiagnosticReport | `labs/diagnostic_report.py` |
| ServiceRequest | `labs/service_request.py` |
| Observation (microbiology) | `labs/microbiology.py` |
| ImagingStudy | `labs/imaging_study.py` |
| — (JP-CLINS lab code loader) | `labs/coding_package.py` |
| — (JP-CLINS lab code dispatch) | `labs/coding_strategy.py` |
| Procedure | `procedures/procedures.py` |
| Immunization | `procedures/immunization.py` |
| Device, DeviceUseStatement | `procedures/device.py` |
| Observation (nursing flowsheet) | `procedures/nursing.py` |
| Condition | `conditions/conditions.py` |
| AllergyIntolerance | `conditions/allergy_intolerance.py` |
| ClinicalImpression | `conditions/clinical_impression.py` |
| Condition (HAI) | `conditions/hai.py` |
| CodeStatus (custom Observation) | `conditions/code_status.py` |
| Composition | `documents/composition.py` |
| DocumentReference | `documents/documents.py` |
| DocumentReference (checkup / eCheckup) | `documents/document_reference_checkup.py` |

For post-processing (bundle finalization, JP-CLINS profile application, timestamp normalization, specimen synthesis), see `post_process/` (PR3, folds Issue #556).
```

- [ ] **Step 6: Verify skeleton imports.**

```bash
python -c "
import clinosim.modules.output.fhir_r4.demographics
import clinosim.modules.output.fhir_r4.encounters
import clinosim.modules.output.fhir_r4.medications
import clinosim.modules.output.fhir_r4.labs
import clinosim.modules.output.fhir_r4.procedures
import clinosim.modules.output.fhir_r4.conditions
import clinosim.modules.output.fhir_r4.documents
print('all 7 domain packages import')
"
```
Expected: `all 7 domain packages import`.

- [ ] **Step 7: Commit skeleton + docs.**

```bash
git add clinosim/modules/output/fhir_r4/{demographics,encounters,medications,labs,procedures,conditions,documents}/__init__.py \
        clinosim/modules/output/fhir_r4/README.md \
        docs/superpowers/plans/2026-08-08-output-fhir_r4-pr2-domain-builders.md
git status
git commit --signoff -m "$(cat <<'EOF'
refactor(output): create fhir_r4 domain subpackages skeleton — Issue #555 PR2 setup

Add 7 empty domain subpackages (demographics, encounters, medications,
labs, procedures, conditions, documents) with docstrings and the FHIR
resource → domain mapping README so subsequent PR2 tasks can `git mv`
files into them.

Byte-neutral: no runtime code moved yet.
EOF
)"
```

---

## Task 2: Move 29 files with `Path(__file__).parents[N]` fix

**Files:**
- Move: 29 files listed in "File Structure" section above (all via `git mv`).
- Modify: `_fhir_medications.py` → `fhir_r4/medications/medications.py` line ~296 (change `parents[2]` to `parents[4]`).
- Modify: `lab_coding_package.py` → `fhir_r4/labs/coding_package.py` line ~545 (change `parents[3]` to `parents[5]`).

**Interfaces:**
- Consumes: subpackage skeleton from Task 1.
- Produces: 29 files at their new locations, `Path(__file__).parents[N]` references correct for new depth.

- [ ] **Step 1: git mv the 29 files.**

```bash
# demographics (4)
git mv clinosim/modules/output/_fhir_patient.py           clinosim/modules/output/fhir_r4/demographics/patient.py
git mv clinosim/modules/output/_fhir_practitioner.py      clinosim/modules/output/fhir_r4/demographics/practitioner.py
git mv clinosim/modules/output/_fhir_family_history.py    clinosim/modules/output/fhir_r4/demographics/family_history.py
git mv clinosim/modules/output/_fhir_smoking_alcohol.py   clinosim/modules/output/fhir_r4/demographics/smoking_alcohol.py

# encounters (5)
git mv clinosim/modules/output/_fhir_encounter.py         clinosim/modules/output/fhir_r4/encounters/encounter.py
git mv clinosim/modules/output/_fhir_care_team.py         clinosim/modules/output/fhir_r4/encounters/care_team.py
git mv clinosim/modules/output/_fhir_care_level.py        clinosim/modules/output/fhir_r4/encounters/care_level.py
git mv clinosim/modules/output/_fhir_facility.py          clinosim/modules/output/fhir_r4/encounters/facility.py
git mv clinosim/modules/output/_fhir_endpoint.py          clinosim/modules/output/fhir_r4/encounters/endpoint.py

# medications (1) — REQUIRES parents[N] fix (Step 2)
git mv clinosim/modules/output/_fhir_medications.py       clinosim/modules/output/fhir_r4/medications/medications.py

# labs (7) — coding_package REQUIRES parents[N] fix (Step 2)
git mv clinosim/modules/output/_fhir_observations.py      clinosim/modules/output/fhir_r4/labs/observations.py
git mv clinosim/modules/output/_fhir_diagnostic_report.py clinosim/modules/output/fhir_r4/labs/diagnostic_report.py
git mv clinosim/modules/output/_fhir_service_request.py   clinosim/modules/output/fhir_r4/labs/service_request.py
git mv clinosim/modules/output/_fhir_microbiology.py      clinosim/modules/output/fhir_r4/labs/microbiology.py
git mv clinosim/modules/output/_fhir_imaging_study.py     clinosim/modules/output/fhir_r4/labs/imaging_study.py
git mv clinosim/modules/output/lab_coding_package.py      clinosim/modules/output/fhir_r4/labs/coding_package.py
git mv clinosim/modules/output/_lab_coding_strategy.py    clinosim/modules/output/fhir_r4/labs/coding_strategy.py

# procedures (4)
git mv clinosim/modules/output/_fhir_procedures.py        clinosim/modules/output/fhir_r4/procedures/procedures.py
git mv clinosim/modules/output/_fhir_immunization.py      clinosim/modules/output/fhir_r4/procedures/immunization.py
git mv clinosim/modules/output/_fhir_device.py            clinosim/modules/output/fhir_r4/procedures/device.py
git mv clinosim/modules/output/_fhir_nursing.py           clinosim/modules/output/fhir_r4/procedures/nursing.py

# conditions (5)
git mv clinosim/modules/output/_fhir_conditions.py            clinosim/modules/output/fhir_r4/conditions/conditions.py
git mv clinosim/modules/output/_fhir_allergy_intolerance.py   clinosim/modules/output/fhir_r4/conditions/allergy_intolerance.py
git mv clinosim/modules/output/_fhir_clinical_impression.py   clinosim/modules/output/fhir_r4/conditions/clinical_impression.py
git mv clinosim/modules/output/_fhir_hai.py                   clinosim/modules/output/fhir_r4/conditions/hai.py
git mv clinosim/modules/output/_fhir_code_status.py           clinosim/modules/output/fhir_r4/conditions/code_status.py

# documents (3)
git mv clinosim/modules/output/_fhir_composition.py                clinosim/modules/output/fhir_r4/documents/composition.py
git mv clinosim/modules/output/_fhir_documents.py                  clinosim/modules/output/fhir_r4/documents/documents.py
git mv clinosim/modules/output/_fhir_document_reference_checkup.py clinosim/modules/output/fhir_r4/documents/document_reference_checkup.py
```

Verify:

```bash
git status --short | grep -c "^R "        # expected: 29
ls clinosim/modules/output/*.py 2>&1 | wc -l  # expected: 8 (adapter, adapters_builtin, csv_adapter, cif_reader, cif_writer, hospital_course_extractor, _fhir_common, fhir_r4_adapter, __init__ = 9; -1 for __init__ line NOT starting with _ = still counts. So actually expect 9)
```

Correct expectation: `output/*.py` includes `adapter.py`, `adapters_builtin.py`, `csv_adapter.py`, `cif_reader.py`, `cif_writer.py`, `hospital_course_extractor.py`, `_fhir_common.py`, `fhir_r4_adapter.py`, `_fhir_post_process.py`, `__init__.py` = **10** items.

- [ ] **Step 2: FIX `Path(__file__).parents[N]` in the 2 relocated files.**

**medications.py** — line ~296. Before Task 2 Step 1 the reference was `parents[2]` counting up to `clinosim/` (the sibling of `codes/`). After the mv the file is 2 layers deeper (`fhir_r4/medications/`), so `parents[4]` reaches the same `clinosim/`.

```bash
grep -n "parents\[" clinosim/modules/output/fhir_r4/medications/medications.py
```
Expected: exactly one match, at approximately line 296.

Apply the fix:

```bash
sed -i '' 's|_Path(__file__)\.resolve()\.parents\[2\] / "codes"|_Path(__file__).resolve().parents[4] / "codes"|g' \
  clinosim/modules/output/fhir_r4/medications/medications.py

# Verify by rendering the substitution
grep -n "parents\[" clinosim/modules/output/fhir_r4/medications/medications.py
```
Expected: `parents[4]` (not `parents[2]`).

**coding_package.py** — line ~545. Before: `parents[3]` counted up to the workspace root (2 levels above `clinosim/`). After deeper move: `parents[5]`.

```bash
grep -n "parents\[" clinosim/modules/output/fhir_r4/labs/coding_package.py
```
Expected: exactly one match, near line 545.

Apply the fix:

```bash
sed -i '' 's|Path(__file__)\.resolve()\.parents\[3\]|Path(__file__).resolve().parents[5]|g' \
  clinosim/modules/output/fhir_r4/labs/coding_package.py

grep -n "parents\[" clinosim/modules/output/fhir_r4/labs/coding_package.py
```
Expected: `parents[5]`.

- [ ] **Step 3: Audit ALL relocated files for OTHER `__file__` uses.**

`Path(__file__).parents[N]` is the known-broken pattern, but other `__file__` idioms (e.g. `Path(__file__).parent / "data"` walks a single level, or `os.path.dirname(__file__)`) may also break.

```bash
grep -n "__file__" clinosim/modules/output/fhir_r4/**/*.py 2>&1
```

Expected: only matches in `medications/medications.py` (now `parents[4]`), `labs/coding_package.py` (now `parents[5]`), plus `lib/generator_metadata.py` line 143 (the `.git` walk-up, relocation-safe from PR1).

If any OTHER `__file__` reference appears, examine each and adjust the parent depth if it walks up a fixed number of layers.

- [ ] **Step 4: Verify the YJ fragment loader still finds its JSON.**

The critical probe. If this returns 0, the `parents[4]` fix is wrong.

```bash
PYTHONPATH=. python -c "
from clinosim.modules.output.fhir_r4.medications.medications import _TX_SERVER_VERIFIED_YJ_CODES
print(f'YJ verified codes: {len(_TX_SERVER_VERIFIED_YJ_CODES)} (expected 2000)')
assert len(_TX_SERVER_VERIFIED_YJ_CODES) == 2000, 'REGRESSION — same bug that killed PR #604'
"
```
Expected: `YJ verified codes: 2000 (expected 2000)`.

If this fails, the `parents[N]` fix in Step 2 is wrong — recompute the correct N (count layers from the new file location up to `clinosim/`) and re-apply.

- [ ] **Step 5: Verify the JP-CLINS SD loader still finds its package.**

```bash
export CLINOSIM_JP_CLINS_PKG_DIR='/Users/tokuyama/workspace/fhir-jp-validator/tx-server-build/terminology/fhir-server/clinical-information-sharing#1.12.0/package'
PYTHONPATH=. python -c "
from clinosim.modules.output.fhir_r4.labs.coding_package import load_lab_coding_package
pkg = load_lab_coding_package()
assert pkg is not None, 'coding_package returned None — parents[N] fix wrong OR env var not set'
print(f'coding_package loaded: {type(pkg).__name__}, non-empty={bool(pkg)}')
"
```
Expected: `coding_package loaded: ...`. If None or exception, the `parents[5]` fix is wrong; recompute.

---

## Task 3: Update internal cross-references among the 29 moved files

**Files:**
- Modify: all 29 moved files (they import each other and from `_fhir_common`/`fhir_r4/lib/*`).

**Interfaces:**
- Consumes: files at new locations from Task 2.
- Produces: internal imports point at new paths; no residual `_fhir_<resource>` or `lab_coding_package`/`_lab_coding_strategy` references inside the moved files.

- [ ] **Step 1: Build the substitution map for internal cross-refs.**

The 29 moved files import each other. Build a sed-substitution map covering all 29 old → new paths. Note file-name changes (drop `_fhir_` and `_` prefixes).

```bash
cat > /tmp/pr2-substitutions.sed <<'EOF'
s|from clinosim\.modules\.output\._fhir_allergy_intolerance import|from clinosim.modules.output.fhir_r4.conditions.allergy_intolerance import|g
s|from clinosim\.modules\.output\._fhir_care_level import|from clinosim.modules.output.fhir_r4.encounters.care_level import|g
s|from clinosim\.modules\.output\._fhir_care_team import|from clinosim.modules.output.fhir_r4.encounters.care_team import|g
s|from clinosim\.modules\.output\._fhir_clinical_impression import|from clinosim.modules.output.fhir_r4.conditions.clinical_impression import|g
s|from clinosim\.modules\.output\._fhir_code_status import|from clinosim.modules.output.fhir_r4.conditions.code_status import|g
s|from clinosim\.modules\.output\._fhir_composition import|from clinosim.modules.output.fhir_r4.documents.composition import|g
s|from clinosim\.modules\.output\._fhir_conditions import|from clinosim.modules.output.fhir_r4.conditions.conditions import|g
s|from clinosim\.modules\.output\._fhir_device import|from clinosim.modules.output.fhir_r4.procedures.device import|g
s|from clinosim\.modules\.output\._fhir_diagnostic_report import|from clinosim.modules.output.fhir_r4.labs.diagnostic_report import|g
s|from clinosim\.modules\.output\._fhir_document_reference_checkup import|from clinosim.modules.output.fhir_r4.documents.document_reference_checkup import|g
s|from clinosim\.modules\.output\._fhir_documents import|from clinosim.modules.output.fhir_r4.documents.documents import|g
s|from clinosim\.modules\.output\._fhir_encounter import|from clinosim.modules.output.fhir_r4.encounters.encounter import|g
s|from clinosim\.modules\.output\._fhir_endpoint import|from clinosim.modules.output.fhir_r4.encounters.endpoint import|g
s|from clinosim\.modules\.output\._fhir_facility import|from clinosim.modules.output.fhir_r4.encounters.facility import|g
s|from clinosim\.modules\.output\._fhir_family_history import|from clinosim.modules.output.fhir_r4.demographics.family_history import|g
s|from clinosim\.modules\.output\._fhir_hai import|from clinosim.modules.output.fhir_r4.conditions.hai import|g
s|from clinosim\.modules\.output\._fhir_imaging_study import|from clinosim.modules.output.fhir_r4.labs.imaging_study import|g
s|from clinosim\.modules\.output\._fhir_immunization import|from clinosim.modules.output.fhir_r4.procedures.immunization import|g
s|from clinosim\.modules\.output\._fhir_medications import|from clinosim.modules.output.fhir_r4.medications.medications import|g
s|from clinosim\.modules\.output\._fhir_microbiology import|from clinosim.modules.output.fhir_r4.labs.microbiology import|g
s|from clinosim\.modules\.output\._fhir_nursing import|from clinosim.modules.output.fhir_r4.procedures.nursing import|g
s|from clinosim\.modules\.output\._fhir_observations import|from clinosim.modules.output.fhir_r4.labs.observations import|g
s|from clinosim\.modules\.output\._fhir_patient import|from clinosim.modules.output.fhir_r4.demographics.patient import|g
s|from clinosim\.modules\.output\._fhir_practitioner import|from clinosim.modules.output.fhir_r4.demographics.practitioner import|g
s|from clinosim\.modules\.output\._fhir_procedures import|from clinosim.modules.output.fhir_r4.procedures.procedures import|g
s|from clinosim\.modules\.output\._fhir_service_request import|from clinosim.modules.output.fhir_r4.labs.service_request import|g
s|from clinosim\.modules\.output\._fhir_smoking_alcohol import|from clinosim.modules.output.fhir_r4.demographics.smoking_alcohol import|g
s|from clinosim\.modules\.output\.lab_coding_package import|from clinosim.modules.output.fhir_r4.labs.coding_package import|g
s|from clinosim\.modules\.output\._lab_coding_strategy import|from clinosim.modules.output.fhir_r4.labs.coding_strategy import|g
EOF
wc -l /tmp/pr2-substitutions.sed          # expected: 29
```

- [ ] **Step 2: Apply substitutions across the 29 moved files.**

```bash
find clinosim/modules/output/fhir_r4/{demographics,encounters,medications,labs,procedures,conditions,documents} -name '*.py' | while IFS= read -r f; do
  sed -i '' -f /tmp/pr2-substitutions.sed "$f"
done
```

- [ ] **Step 3: Verify no residual old-path references inside the moved files.**

```bash
grep -rn "output\._fhir_\|output\.lab_coding_package\|output\._lab_coding_strategy" \
  clinosim/modules/output/fhir_r4/{demographics,encounters,medications,labs,procedures,conditions,documents} 2>&1
```
Expected: no matches. If any residual appears (multi-line import forms are the usual culprit), rewrite by hand.

---

## Task 4: Update `fhir_r4/__init__.py` facade + `fhir_r4/lib/*` + all 96 external callers

**Files:**
- Modify: `clinosim/modules/output/fhir_r4/__init__.py` (facade — imports from every `_fhir_<resource>` today).
- Modify: `clinosim/modules/output/fhir_r4/lib/*.py` (some may reference moved files).
- Modify: `clinosim/modules/output/_fhir_post_process.py` (imports from other `_fhir_<resource>` files; deferred to PR3 for the split but its imports still need updating for PR2).
- Modify: 96 caller files across `clinosim/` and `tests/`.

**Interfaces:**
- Consumes: substitution map from Task 3 Step 1.
- Produces: green tree with all imports pointing at new paths.

- [ ] **Step 1: Enumerate PR2 caller files.**

```bash
grep -rl \
  -e "from clinosim\.modules\.output\._fhir_allergy_intolerance" \
  -e "from clinosim\.modules\.output\._fhir_care_" \
  -e "from clinosim\.modules\.output\._fhir_clinical_impression" \
  -e "from clinosim\.modules\.output\._fhir_code_status" \
  -e "from clinosim\.modules\.output\._fhir_composition" \
  -e "from clinosim\.modules\.output\._fhir_conditions" \
  -e "from clinosim\.modules\.output\._fhir_device" \
  -e "from clinosim\.modules\.output\._fhir_diagnostic_report" \
  -e "from clinosim\.modules\.output\._fhir_document" \
  -e "from clinosim\.modules\.output\._fhir_encounter" \
  -e "from clinosim\.modules\.output\._fhir_endpoint" \
  -e "from clinosim\.modules\.output\._fhir_facility" \
  -e "from clinosim\.modules\.output\._fhir_family_history" \
  -e "from clinosim\.modules\.output\._fhir_hai" \
  -e "from clinosim\.modules\.output\._fhir_imaging_study" \
  -e "from clinosim\.modules\.output\._fhir_immunization" \
  -e "from clinosim\.modules\.output\._fhir_medications" \
  -e "from clinosim\.modules\.output\._fhir_microbiology" \
  -e "from clinosim\.modules\.output\._fhir_nursing" \
  -e "from clinosim\.modules\.output\._fhir_observations" \
  -e "from clinosim\.modules\.output\._fhir_patient" \
  -e "from clinosim\.modules\.output\._fhir_practitioner" \
  -e "from clinosim\.modules\.output\._fhir_procedures" \
  -e "from clinosim\.modules\.output\._fhir_service_request" \
  -e "from clinosim\.modules\.output\._fhir_smoking_alcohol" \
  -e "from clinosim\.modules\.output\.lab_coding_package" \
  -e "from clinosim\.modules\.output\._lab_coding_strategy" \
  clinosim/ tests/ 2>/dev/null | sort -u > /tmp/pr2-callers.txt
wc -l /tmp/pr2-callers.txt                # expected: ~96 (verified pre-PR2 count)
```

- [ ] **Step 2: Apply the substitution map to every caller.**

```bash
while IFS= read -r f; do
  sed -i '' -f /tmp/pr2-substitutions.sed "$f"
done < /tmp/pr2-callers.txt
```

- [ ] **Step 3: Verify no residual old-path references anywhere (except the `_fhir_post_process.py` file itself and shims).**

```bash
grep -rn "output\._fhir_\|output\.lab_coding_package\|output\._lab_coding_strategy" clinosim/ tests/ 2>/dev/null | \
  grep -v "clinosim/modules/output/_fhir_common.py" | \
  grep -v "clinosim/modules/output/_fhir_post_process.py"  # excluded: still at output/ root (PR3 scope) but its imports were updated in Step 2
```

If matches remain, they are likely:
- **Docstring references** — cosmetic. Leave for follow-up unless it's a `mock.patch("clinosim.modules.output._fhir_X")` string in a test (mock string references are functional, not cosmetic — must update).
- **Multi-line `from X import (` forms with a line break inside** — sed's line-by-line match failed. Rewrite by hand.
- **`import clinosim.modules.output._fhir_X as Y`** — different pattern. Update to `import clinosim.modules.output.fhir_r4.<domain>.<name> as Y`.

Address each residual before proceeding.

- [ ] **Step 4: Update mock-patch string references.**

Tests sometimes reference modules by string (`mock.patch("clinosim.modules.output._fhir_X.Y")`). These are NOT caught by `from ... import` grep patterns. Sweep for them:

```bash
grep -rn "\"clinosim\.modules\.output\._fhir_\|'clinosim\.modules\.output\._fhir_" tests/ 2>/dev/null
```

For each match, rewrite the string to the new path. Example:
- `"clinosim.modules.output._fhir_medications._resolve_jp_drug_system_uri"` → `"clinosim.modules.output.fhir_r4.medications.medications._resolve_jp_drug_system_uri"`

---

## Task 5: Verification (real, not proxy)

**Files:** none modified. Pure verification per memory rules `feedback_measure_with_the_real_operation.md` and `feedback_verify_beyond_unit_tests.md`.

**Interfaces:**
- Consumes: state at end of Task 4.
- Produces: verified proof that PR2 is byte-neutral, passing, and clean.

- [ ] **Step 1: Run `ruff` gates with pinned version.**

```bash
ruff --version                           # confirm: ruff 0.16.0
ruff check clinosim tests
ruff format --check clinosim tests
```
Expected: both clean. If format complains, run `ruff format clinosim tests` and re-check.

- [ ] **Step 2: `mypy` strict.**

```bash
mypy clinosim/
```
Expected: `Success: no issues found in 247 source files` (matches PR1 baseline).

- [ ] **Step 3: Full unit test suite.**

```bash
python -m pytest tests/unit 2>&1 | tee /tmp/pr2-unit.log | tail -3
```
Expected last line: `3968 passed, 1 warning in <NNs>`. Anything less is a blocker.

If failures appear, common patterns:
- `ImportError: cannot import name X from Y` — a caller was missed by Task 4 Step 2, or a `mock.patch` string was missed by Step 4.
- `FileNotFoundError` on paths like `_fhir_encounter.py` — test that reads source by hardcoded path.
- `AttributeError: module ... has no attribute ...` — test does `from output import _fhir_X` and X is now a moved module.

- [ ] **Step 4: Direct probe of the two `Path(__file__).parents[N]` fixes.**

The critical single-most-important gate — this is exactly what killed PR #604.

```bash
python -c "
from clinosim.modules.output.fhir_r4.medications.medications import _TX_SERVER_VERIFIED_YJ_CODES
assert len(_TX_SERVER_VERIFIED_YJ_CODES) == 2000, f'REGRESSION: got {len(_TX_SERVER_VERIFIED_YJ_CODES)} codes, expected 2000'
print(f'medications YJ fragment: {len(_TX_SERVER_VERIFIED_YJ_CODES)} codes OK')
"

export CLINOSIM_JP_CLINS_PKG_DIR='/Users/tokuyama/workspace/fhir-jp-validator/tx-server-build/terminology/fhir-server/clinical-information-sharing#1.12.0/package'
python -c "
from clinosim.modules.output.fhir_r4.labs.coding_package import load_lab_coding_package
pkg = load_lab_coding_package()
assert pkg is not None, 'coding_package returned None — parents[5] fix wrong'
print(f'lab_coding_package OK: {type(pkg).__name__}')
"
```

- [ ] **Step 5: Byte-neutral 30-patient JP+US cohort diff vs `master` (which is now PR1 tip).**

```bash
SCRATCH=/private/tmp/claude-818441110/-Users-tokuyama-workspace-clinosim/60788cf6-b37b-4bd0-8b7d-f75d17351ae9/scratchpad
mkdir -p "$SCRATCH/pr2-baseline" "$SCRATCH/pr2-branch"

CURRENT=$(git branch --show-current)
git checkout master
clinosim generate -p 30 -s 42 --country US --format fhir-r4 --out "$SCRATCH/pr2-baseline/us"
export CLINOSIM_JP_CLINS_PKG_DIR='/Users/tokuyama/workspace/fhir-jp-validator/tx-server-build/terminology/fhir-server/clinical-information-sharing#1.12.0/package'
clinosim generate -p 30 -s 42 --country JP --format fhir-r4 --out "$SCRATCH/pr2-baseline/jp"
git checkout "$CURRENT"

clinosim generate -p 30 -s 42 --country US --format fhir-r4 --out "$SCRATCH/pr2-branch/us"
clinosim generate -p 30 -s 42 --country JP --format fhir-r4 --out "$SCRATCH/pr2-branch/jp"

diff -r "$SCRATCH/pr2-baseline/us/fhir_r4" "$SCRATCH/pr2-branch/us/fhir_r4" 2>&1 | \
  grep -vE "manifest\.json|_generator_metadata\.json|^diff -r" > "$SCRATCH/pr2-us-resources.diff"
diff -r "$SCRATCH/pr2-baseline/jp/fhir_r4" "$SCRATCH/pr2-branch/jp/fhir_r4" 2>&1 | \
  grep -vE "manifest\.json|_generator_metadata\.json|^diff -r" > "$SCRATCH/pr2-jp-resources.diff"

wc -l "$SCRATCH/pr2-us-resources.diff" "$SCRATCH/pr2-jp-resources.diff"
```

Expected: each file **12 lines** — 3 timestamp-field pairs (`generated_at` / `generation_timestamp` / `transactionTime`) × 2 sides × 2 (change marker + separator).

If either file has MORE than 12 lines, filter for non-timestamp content:

```bash
grep -E "^<|^>" "$SCRATCH/pr2-us-resources.diff" | \
  grep -vE "generated_at|generation_timestamp|transactionTime" | head -20
```

If any non-timestamp line surfaces, PR2 is NOT byte-neutral. Root-cause before pushing. The most likely culprits, given the class of change:

- A `_fhir_medications` internal import was missed in Task 3, causing an ImportError caught by a defensive try/except that silently degrades output.
- A `mock.patch` string reference to the old path in an integration test lets the test pass but changes the fixture surface for downstream tests.
- The `Path(__file__).parents[N]` fix is off by one — cohort output shows `MedicationCodeNocoded_CS` where master shows YJ code URIs.

---

## Task 6: Commit + push + PR

- [ ] **Step 1: Stage all changes.**

```bash
git status
git add -A
git status | head -30
```

Guard: if any file outside `clinosim/modules/output/`, `clinosim/**/*.py`, `tests/**/*.py`, or `docs/superpowers/{specs,plans}/` shows in status, stop and audit.

- [ ] **Step 2: Commit.**

```bash
git commit --signoff -m "$(cat <<'EOF'
refactor(output): move 29 builder files into clinical-domain subdirs — Issue #555 PR2

Second PR of the 3-PR restructure (spec: docs/superpowers/specs/
2026-08-08-output-fhir_r4-subpackage-design.md). PR1 laid the fhir_r4/
subpackage with shared lib/. PR2 moves the 29 remaining FHIR
resource-builder and JP-CLINS lab-support files into 7 clinical-domain
subpackages so sibling drift is visible in a single dir listing and OSS
contributors reason by domain, not by FHIR resource type. PR3 splits
_fhir_post_process.py by concern (folds Issue #556).

Scope (byte-neutral):
  - Create 7 domain subpackages: demographics/, encounters/,
    medications/, labs/, procedures/, conditions/, documents/.
  - git mv 29 files with _fhir_ prefix dropped:
      demographics/ (4): patient, practitioner, family_history,
                        smoking_alcohol
      encounters/   (5): encounter, care_team, care_level, facility,
                        endpoint
      medications/  (1): medications (+ Path(__file__).parents[2] →
                        parents[4] fix, restoring the yj_tx_valid_codes
                        JSON path that PR #604 silently broke)
      labs/         (7): observations, diagnostic_report,
                        service_request, microbiology, imaging_study,
                        coding_package (+ Path(__file__).parents[3] →
                        parents[5] for JP-CLINS package lookup),
                        coding_strategy
      procedures/   (4): procedures, immunization, device, nursing
      conditions/   (5): conditions, allergy_intolerance,
                        clinical_impression, hai, code_status
      documents/    (3): composition, documents,
                        document_reference_checkup
  - Update all internal cross-references among the 29 moved files.
  - Update 96 external caller files across clinosim/ and tests/.
  - Update mock.patch string references in tests.
  - Add fhir_r4/README.md with FHIR resource → domain mapping table.

Verification (per memory rules feedback_measure_with_the_real_operation
+ feedback_verify_beyond_unit_tests + feedback_ci_local_tool_version_
divergence):
  - Direct probe: _TX_SERVER_VERIFIED_YJ_CODES = 2000 codes (the same
    counter that PR #604 regressed to 0; this proves the parents[N]
    fix in medications.py is correct)
  - Direct probe: load_lab_coding_package() returns non-None (proves
    the parents[N] fix in coding_package.py is correct)
  - pytest tests/unit: 3968 passed (matches PR1 baseline exactly)
  - mypy clinosim/ strict: clean (247 files)
  - ruff==0.16.0 check + format --check: clean (ran with pinned CI
    version to avoid PR1's 0.16.1-vs-0.16.0 sort-order fixup)
  - 30-patient seed 42 JP+US FHIR cohort diff -r vs master (=PR1 tip):
      resource-level diff = 12 lines each (only timestamp fields)
      resource content byte-identical

No functional change. No FHIR output change. No public API name
change. Internal symbol names unchanged.

Related: closes-partial #555 (PR2 of 3). PR3 splits
_fhir_post_process.py and closes #556.
EOF
)"
```

- [ ] **Step 3: Push branch.**

```bash
git push -u origin refactor/555-fhir-r4-domain-builders-pr2
```

If pre-push hook (`ruff format --check`) refuses, run `ruff format clinosim tests` and amend.

- [ ] **Step 4: Create the PR.**

```bash
gh pr create \
  --base master \
  --head refactor/555-fhir-r4-domain-builders-pr2 \
  --title "refactor(output): move 29 builder files into clinical-domain subdirs — Issue #555 PR2 of 3" \
  --body "$(cat <<'EOF'
## Summary

Second PR of the 3-PR restructure for Issue #555. Moves the 29 remaining FHIR resource-builder and JP-CLINS lab-support files at \`clinosim/modules/output/\` root into 7 clinical-domain subpackages (\`demographics/\`, \`encounters/\`, \`medications/\`, \`labs/\`, \`procedures/\`, \`conditions/\`, \`documents/\`), migrates 96 caller sites, and adds a FHIR resource → domain mapping README.

## Design context

Full spec: \`docs/superpowers/specs/2026-08-08-output-fhir_r4-subpackage-design.md\`. Layout is clinical-domain (Option B), not role-based (Option A that closed PR #604 attempted).

## Scope

- \`git mv\` 29 files with \`_fhir_\` prefix dropped, into 7 domain subdirs.
- **Fix 2 hardcoded \`Path(__file__).parents[N]\` references** that would otherwise silently regress after deeper file placement — the exact class of bug that killed PR #604 (\`_TX_SERVER_VERIFIED_YJ_CODES\` went to 0 → every JP YJ code silently downgraded to \`MedicationCodeNocoded_CS\`):
  - \`medications.py\` line 296: \`parents[2]\` → \`parents[4]\`
  - \`labs/coding_package.py\` line 545: \`parents[3]\` → \`parents[5]\`
- Update all internal cross-references among the 29 moved files (29 substitution patterns).
- Update 96 external caller files across \`clinosim/\` and \`tests/\`.
- Update \`mock.patch\` string references in tests.
- Add \`fhir_r4/README.md\` with FHIR resource → domain mapping table.

## Verification

Per memory rules \`feedback_measure_with_the_real_operation.md\` and \`feedback_verify_beyond_unit_tests.md\` — reject silent regressions, measure the real operation.

- **Direct probe: \`_TX_SERVER_VERIFIED_YJ_CODES\` = 2000 codes** (proves the \`parents[4]\` fix in \`medications.py\` restores the fragment loader; PR #604 regressed this to 0).
- **Direct probe: \`load_lab_coding_package()\` returns non-None** (proves the \`parents[5]\` fix in \`coding_package.py\` finds the JP-CLINS SD/CS package).
- \`pytest tests/unit\`: **3968 passed** (matches PR1 baseline).
- \`mypy clinosim/\` strict: clean (247 source files).
- \`ruff==0.16.0 check + format --check\`: clean.
- 30-patient seed 42 JP+US FHIR cohort \`diff -r\` vs \`master\` (= PR1 tip): resource content byte-identical (only timestamp fields differ).

## Related

- Second of 3 PRs closing #555.
- Follows: #605 (PR1 — \`fhir_r4/lib/\` foundation, merged).
- Next: PR3 will split \`_fhir_post_process.py\` (1370 LOC) into 5 files under \`fhir_r4/post_process/\` and close #556.
- Supersedes closed PR #604 (see [regression analysis](https://github.com/TomoOkuyama/clinosim/pull/604#issuecomment-5224346643)).

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_01PCD9UxAv9Rpz2HVt2hGE75
EOF
)"
```

- [ ] **Step 5: Verify PR opened and monitor CI.**

```bash
gh pr view --json url,state -q '{state, url}'
gh pr checks $(gh pr view --json number -q .number) 2>&1 | head -20
```

Return the PR URL. Wait for CI green before merging.

---

## Rollback plan

If verification fails at Task 5 and root-causing isn't quick:

```bash
git checkout master
git branch -D refactor/555-fhir-r4-domain-builders-pr2
# (if pushed): gh pr close <N> && git push origin --delete refactor/555-fhir-r4-domain-builders-pr2
```

`master` (PR1 tip) is untouched throughout.

## Post-merge follow-up

- PR3 planning: read `_fhir_post_process.py`'s own docstring, verify the 5 concern groupings (datetime_normalize, jp_ecs, strip, specimen, profile), enumerate the ~30 caller sites, and confirm no hidden `Path(__file__)` references before beginning.

## Self-review notes

1. **Placeholder scan**: no TBD/TODO in the plan body. All 29 substitution pairs are enumerated verbatim in Task 3 Step 1's sed file. All 29 `git mv` commands are enumerated in Task 2 Step 1.
2. **Type consistency**: substitution map in Task 3 Step 1 is reused verbatim in Task 4 Step 2. No pattern divergence.
3. **Spec coverage**: PR2 scope in spec (§ "PR sequence → PR2") is fully covered by Tasks 1–6. The `parents[N]` fixes for `medications.py` and `coding_package.py` (called out in spec § "PR2 → Audit") are anchored in Task 2 Step 2 with concrete substitution commands + Task 5 Step 4 direct probes.
4. **Ambiguity check**: file-name transformation `_fhir_medications.py` → `medications/medications.py` (retaining the sub-file `medications.py`) could look odd but is consistent — each domain has one canonical file named after the primary resource. Documented in the mapping table in `fhir_r4/README.md` (Task 1 Step 5).
5. **Risk highlights**: (a) the `parents[N]` fixes are the single highest-risk step — Task 2 Step 2 spells out the exact `sed` command and the exact expected `grep` result, and Task 5 Step 4 asserts equality with the pre-move value; (b) `mock.patch` string references (Task 4 Step 4) are easy to miss because they don't match `from X import` grep patterns.
