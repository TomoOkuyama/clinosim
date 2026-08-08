# `output/fhir_r4/` subpackage restructure design

**Date**: 2026-08-08
**Session**: 85
**Issues**: closes #555, folds #556
**Related**: #545 (fhir_common promotion) — file rename Step 1 done; symbol rename Step 2 deferred, out of scope here

## Problem

`clinosim/modules/output/` currently holds 33 flat `_fhir_*.py` files at one nesting level, mixing four unrelated roles:

- Format adapters (`adapter.py`, `csv_adapter.py`, `fhir_r4_adapter.py`)
- FHIR resource builders (25+ `_fhir_<resource>.py`)
- Shared FHIR library (`fhir_common.py`, `_fhir_localization.py`, `_fhir_reference_data.py`, `_fhir_inline_bb.py`, `_fhir_generator_metadata.py`, `opaque_ids.py`)
- Post-processing pipeline (`_fhir_post_process.py` at 1370 LOC — its own docstring lists 5 unrelated concern groups)

Result: 128 files across `clinosim/` and `tests/` import from `_fhir_*` internals directly. A new maintainer cannot tell from the file list which files are builders, which are shared library, and which are post-processing dispatch. Cross-cutting concerns (e.g. medication vocabulary, lab specimen handling) are scattered and prone to sibling drift.

## Constraints and axes

Design decisions must optimize for, in order:

1. **Code structure simplicity** — new maintainers should navigate by intent, not by file-name prefix guessing.
2. **Responsibility decomposition** — one directory ↔ one responsibility; unrelated files must not share a level.
3. **Clinical alignment** — files that belong to the same clinical domain (medications, labs, encounters, …) cluster physically so sibling drift is detectable in diff.
4. **Data quality** — layout must not silently change bundle output. Byte-neutral verification required at each PR boundary.
5. **Backward compatibility** — 128 caller sites must keep working. `_fhir_common.py` shim (from #545) stays. `fhir_r4_adapter.py` becomes a thin re-export shim so its 4+ callers keep the same import path.

## Target layout

```
clinosim/modules/output/
├── __init__.py                     — public re-exports (surface unchanged)
├── adapter.py                      — format registry (unchanged)
├── adapters_builtin.py             — CSV + FHIR adapter registration (unchanged)
├── csv_adapter.py                  — CSV format adapter (unchanged)
├── cif_reader.py                   — CIF reader (unchanged)
├── cif_writer.py                   — CIF writer (unchanged)
├── hospital_course_extractor.py    — CIF→LLM helper, not FHIR (unchanged)
├── _fhir_common.py                 — deprecated shim from #545 (unchanged)
├── fhir_r4_adapter.py              — new thin shim: `from clinosim.modules.output.fhir_r4 import *`
└── fhir_r4/                        — new: FHIR R4 output subsystem
    ├── __init__.py                 — facade (registrar + assembler; was fhir_r4_adapter.py content)
    ├── lib/                        — shared FHIR helpers (6 files)
    │   ├── __init__.py
    │   ├── common.py               ← output/fhir_common.py             (45938 bytes)
    │   ├── localization.py         ← output/_fhir_localization.py      (18263 bytes)
    │   ├── reference_data.py       ← output/_fhir_reference_data.py    (11666 bytes)
    │   ├── inline_bb.py            ← output/_fhir_inline_bb.py         (36660 bytes)
    │   ├── generator_metadata.py   ← output/_fhir_generator_metadata.py ( 7215 bytes)
    │   └── ids.py                  ← output/opaque_ids.py              ( 5913 bytes)
    ├── demographics/               — patient, practitioner, family_history, smoking_alcohol (4 files)
    ├── encounters/                 — encounter, care_team, care_level, facility, endpoint (5 files)
    ├── medications/                — medications (1 file, 60k)
    ├── labs/                       — observations, diagnostic_report, service_request, microbiology, imaging_study, coding_package, coding_strategy (7 files)
    ├── procedures/                 — procedures, immunization, device, nursing (4 files)
    ├── conditions/                 — conditions, allergy_intolerance, clinical_impression, hai, code_status (5 files)
    ├── documents/                  — composition, documents, document_reference_checkup (3 files)
    └── post_process/               — datetime_normalize, jp_ecs, strip, specimen, profile (5 files, from _fhir_post_process.py split — folds #556)
        └── __init__.py             — dispatch entry
```

### File placement rationale

- **CIF layer** stays at `output/` root: CIF is a distinct format peer to FHIR, not a FHIR concern.
- **Format adapter registry** (`adapter.py`, `adapters_builtin.py`, `csv_adapter.py`) stays at `output/` root: they are the format-selection layer, above any single format's internals.
- **`hospital_course_extractor.py`** stays at `output/` root: it extracts deterministic facts from CIF for LLM prompts, not FHIR-specific.
- **`fhir_r4_adapter.py`** becomes a thin shim at `output/` root: 128 caller sites won't break; the real facade lives inside `fhir_r4/__init__.py`.
- **FHIR support files** move under `fhir_r4/lib/`:
  - `opaque_ids.py` → `fhir_r4/lib/ids.py` (Resource.id is a FHIR construct, used only by FHIR builders)
  - `lab_coding_package.py` and `_lab_coding_strategy.py` → `fhir_r4/labs/coding_package.py` and `fhir_r4/labs/coding_strategy.py` (JP-CLINS lab-specific, only labs/ code uses them)
- **`_fhir_common.py`** deprecated shim from #545 stays as-is; still emits `DeprecationWarning`. Removing it is a separate deprecation-cycle decision outside this Issue.

### Clinical domain grouping — the "why"

FHIR is resource-oriented, so the naive layout is one file per resource type. But clinicians and OSS maintainers reason by domain: "I'm working on medications" means MedicationRequest + MedicationAdministration + course-of-therapy helpers, not "a resource type called Medication". Physically grouping domain files means:

- Sibling drift shows up in the same directory listing (e.g. two lab code helpers with divergent JP mapping become adjacent files).
- New contributors can find the right file by clinical knowledge alone.
- A `README.md` inside `fhir_r4/` provides the FHIR-resource → domain mapping table so spec-oriented readers find their way too.

## Naming convention

- **File names** drop the `_fhir_` prefix (redundant inside `fhir_r4/`) and the underscore prefix at file level: `_fhir_patient.py` → `fhir_r4/demographics/patient.py`.
- **Internal symbol names** (`_build_patient`, `_bb_immunizations` etc.) are unchanged. Symbol renaming is Issue #545 Step 2, out of scope here.
- **Rationale for file-level prefix drop**: the subpackage boundary (`fhir_r4/`) is the visibility marker; per-file `_` prefix is redundant. Consistent with `clinosim/modules/<X>/engine.py` (no underscore) elsewhere in the codebase.

## Backward compatibility contract

| Import surface | Behavior |
|---|---|
| `from clinosim.modules.output import register_output_adapter, register_bundle_builder, available_builders` | Unchanged (existing `__init__.py`). |
| `from clinosim.modules.output.fhir_r4_adapter import <anything>` | Continues to work via thin shim `from clinosim.modules.output.fhir_r4 import *`. |
| `from clinosim.modules.output._fhir_common import <anything>` | Continues to work via existing #545 shim (with `DeprecationWarning`). |
| `from clinosim.modules.output._fhir_<resource> import <anything>` | **Migrated** — all 128 caller sites updated in-PR. No shim provided (would defeat the restructure by making both paths work). Existing PR test suite catches any missed migration. |
| `from clinosim.modules.output.fhir_common import <anything>` (post-#545 canonical path) | Migrated to `from clinosim.modules.output.fhir_r4.lib.common import <anything>` in PR1. |

No public API symbol is renamed. No behavior change. Byte-identical bundle output.

## Verification protocol (each PR)

Before pushing every PR:

1. `pytest tests/unit` — must remain green at 3968 pass (session 84 wrap baseline).
2. `mypy clinosim/` — strict mode clean.
3. `ruff check clinosim tests` — clean.
4. `ruff format --check clinosim tests` — clean (pre-push hook will refuse otherwise per session 82 setup).
5. `clinosim generate -p 30 -s 42 --country US --format fhir-r4 --out $SCRATCH/pr<N>-us` — succeeds.
6. `clinosim generate -p 30 -s 42 --country JP --format fhir-r4 --out $SCRATCH/pr<N>-jp` — succeeds. Requires `CLINOSIM_JP_CLINS_PKG_DIR` env var.
7. `diff -r origin/master-cohort $SCRATCH/pr<N>-*` — **structural JSON diff must be 0 lines**. Refactor is byte-neutral.
8. `git branch --show-current` — must be the PR's topic branch, NOT `master` (per memory rule `feedback_no_direct_commit_to_master.md`).

If any of the above fails, do NOT push. Fix locally first.

## PR sequence

Strict order (no parallelism — each PR rebases from the previous). All three PRs land in session 85 if verification stays clean; otherwise stop and reassess.

### PR1: foundation + shared library

**Scope**:
- Create `fhir_r4/` and `fhir_r4/lib/` package directories with `__init__.py`.
- `git mv` 6 shared library files into `fhir_r4/lib/` with rename to non-underscore names.
- Move `fhir_r4_adapter.py` content into `fhir_r4/__init__.py`. Leave `fhir_r4_adapter.py` as a thin shim: `from clinosim.modules.output.fhir_r4 import *  # noqa: F401,F403` plus explicit re-imports for non-`__all__` names to preserve current caller behavior.
- Update all `clinosim/` and `tests/` callers importing from the 6 moved files (~50 sites).
- Update `_fhir_common.py` (the #545 shim) to re-export from `fhir_r4.lib.common` (its current target `fhir_common` is being moved).
- Update `fhir_r4/__init__.py` internal imports to point at `fhir_r4/lib/` and (for now) the remaining `output/_fhir_*.py` builders that PR2 will move.

**Expected diff**: ~6 file mv + 1 facade move + shims + ~50 caller updates. Medium.

**Verification**: full protocol above.

### PR2: clinical domain builders

**Scope**:
- Create 7 domain package directories under `fhir_r4/`: `demographics/`, `encounters/`, `medications/`, `labs/`, `procedures/`, `conditions/`, `documents/`.
- `git mv` 25 builder files + 2 JP-CLINS lab support files (`lab_coding_package.py`, `_lab_coding_strategy.py`) into the appropriate domain.
- File-name mapping applied (drop `_fhir_` prefix and underscore).
- Update all `clinosim/` and `tests/` callers (~80 sites).
- Update `fhir_r4/__init__.py` internal imports to point at new domain paths.
- Update `fhir_r4/lib/common.py` internal imports (if it references `_fhir_<resource>` builders) to point at new domain paths.
- Add `fhir_r4/README.md` with a FHIR resource → domain mapping table (single reference table for spec-oriented readers).

**Expected diff**: 27 file mv + ~80 caller updates + 1 README. Large but fully mechanical.

**Verification**: full protocol above. Special attention to `git mv` preserving history.

### PR3: post_process split (folds #556)

**Scope**:
- Create `fhir_r4/post_process/` package directory with `__init__.py`.
- Split `_fhir_post_process.py` (1370 LOC) into 5 files matching its docstring groupings:
  - `datetime_normalize.py` — `_normalize_jp_observation_category` / `_normalize_dt_*` helpers.
  - `jp_ecs.py` — `_apply_jp_clins_profile`, `_populate_*_ecs_fields`.
  - `strip.py` — `_strip_japanese_display_on_english_only_systems` and other strip helpers.
  - `specimen.py` — `_build_companion_specimen`, `_pick_specimen_type_*`.
  - `profile.py` — `_apply_jp_core_profile` and other profile-application dispatch.
- `post_process/__init__.py` re-exports the previous public surface (whatever the 30 caller sites currently import from `_fhir_post_process`).
- Delete `output/_fhir_post_process.py`.
- Update ~30 caller sites: `from clinosim.modules.output._fhir_post_process import X` → `from clinosim.modules.output.fhir_r4.post_process import X`.

**Expected diff**: 1 file deleted, 6 new files (5 + `__init__.py`), ~30 caller updates. Medium.

**Verification**: full protocol above.

## Rejected alternatives

### Layout A: role-based (Issue #555's original proposal)

`fhir_r4/builders/*.py` (25+ files) + `fhir_r4/post_process/` + `fhir_r4/*.py` shared library.

Rejected because: `builders/` becomes another flat directory of 25 files. Clinical domain grouping is stronger on all 5 stated axes.

### Layout C: 2-tier functional (`lib/` + `resource/` + `pipeline/`)

Rejected because: `resource/` still flat with 25+ files; no clinical grouping benefit.

### One giant PR

Rejected because: 33 file mv + 128 caller updates + post_process split = large review surface. Merge-conflict recovery cost is high if any other work touches `output/`.

### 10-PR split (one PR per domain subdir)

Rejected because: 10 PR overhead (rebase, verify, review) outweighs the granularity benefit when each domain move is < 10 files.

## Out of scope

- **Symbol renaming** (`_build_X` → `build_X`) — Issue #545 Step 2, deferred.
- **Removing `_fhir_common.py` shim** — separate deprecation-cycle decision.
- **Refactoring individual builder files** — this Issue is purely file/directory relocation. Any per-file cleanup is a follow-up Issue.
- **`hospital_course_extractor.py` migration** — not FHIR-specific; belongs in a separate LLM-support module Issue if warranted.

## Success criteria

- All 3 PRs merged.
- 30-patient seed 42 (JP + US) FHIR bundle output byte-identical to `master` at PR3 completion.
- `pytest tests/unit` remains at 3968 pass across the sequence.
- `output/` root shows ≤ 10 items (was 48).
- `fhir_r4/` subpackage clearly decomposed by clinical domain + shared library + post-process.
- Issue #555 closed. Issue #556 closed (folded into PR3).
