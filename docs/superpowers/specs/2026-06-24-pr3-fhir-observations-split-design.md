# PR3 (G3) — `_fhir_observations.py` split design

**Date**: 2026-06-24
**Series**: AD-55 Module Foundation Refactor (final structural piece)
**Type**: Pure mechanical refactor (byte-identical guarantee)
**Branch**: `refactor/pr3-fhir-observations-split`

## Background

`clinosim/modules/output/_fhir_observations.py` is currently 727 lines / 31 KB and mixes **four unrelated Observation-family builders** plus one helper:

| Symbol | Lines | Role |
|---|---|---|
| `_SUSCEPTIBILITY_DISPLAY` | 4 | microbiology-only constant |
| `_bb_microbiology(ctx)` | 88 (l39-127) | microbiology Specimen + Observation + DiagnosticReport |
| `_build_nursing_observations(ctx)` | 193 (l129-322) | nursing flowsheets (NEWS2/GCS/Braden/Morse/ADL/I&O) |
| `_build_immunizations(ctx)` | 50 (l324-374) | CVX vaccine Immunization (note: resource type, not Observation) |
| `_build_lab_observation(...)` | 123 (l376-499) | per-order lab Observation helper |
| `_build_vital_observations(ctx)` | 226 (l501-727) | vital-sign Observation builder |

This is the **final structural piece** of the AD-55 Module Foundation Refactor series:

- PR1 (#83): `_shared.py` + `ENRICHER_SEED_OFFSETS` central registry
- PR2 (#84): `modules/sdoh/` data-only variant + `_fhir_sdoh.py` 88-line split
- **PR3 (this)**: `_fhir_observations.py` 727-line theme-by-theme split

PR3 is intentionally scheduled **before** device + HAI feature work because new
DeviceUseStatement and CLABSI/CAUTI/VAP Observation builders would otherwise
land in an already-bloated multi-theme file, multiplying the split cost.

## Goals

1. Decompose `_fhir_observations.py` so each AD-55 Base theme owns its own
   builder file, matching the precedent set by `_fhir_smoking_alcohol.py` /
   `_fhir_care_level.py` / `_fhir_family_history.py` / `_fhir_code_status.py`
   etc.
2. Preserve all output byte-for-byte (refactor PR gate per CONTRIBUTING-modules.md
   "PR 検証ガイド").
3. Keep down-stream caller surface unchanged via `noqa: F401` re-exports in
   `fhir_r4_adapter.py`.
4. Do NOT promote new shared helpers to `_fhir_common.py` — current exports
   already cover all four builders' needs (PR2 promoted `_social_category` /
   `_value` exactly because that was the moment they became reused; PR3 has
   no equivalent newly-shared symbols).

## Non-goals

- **Splitting lab + vital further** (would make `_fhir_observations.py` empty
  / rename to `_fhir_labs_vitals.py`). Deferred — current file becomes
  cohesive (Observation/numeric-result family) after the AD-55 themes leave.
  Future device + HAI builder gets its own `_fhir_device.py` / `_fhir_hai.py`
  regardless, so the residual lab + vital file does not impede that work.
- **Renaming `_fhir_observations.py`** to `_fhir_labs_vitals.py`. Rejected
  because (a) it broadens the diff to every adapter import + test grep
  without behavior change, (b) the name `_fhir_observations.py` still reads
  correctly as "Observation resource builders" — lab and vital observations
  *are* the canonical numeric Observation use case.
- **Touching `register_builtin_builders()` order**. Builder registration
  order must remain bit-identical to preserve byte-diff invariant. The four
  symbols continue to be referenced by the same names from the adapter.
- **Refactoring `_build_lab_observation` or `_build_vital_observations`**.
  No behavior change; only the surrounding themes move out.

## Design

### File layout after PR3

```
clinosim/modules/output/
  _fhir_observations.py    ← shrunk to ~570 lines (lab helper + vital builder only)
    └─ no longer hosts micro / nursing / immunization

  _fhir_microbiology.py    ← NEW (~95 lines = 88 + module docstring + imports)
    ├─ _SUSCEPTIBILITY_DISPLAY  (moved verbatim, micro-only)
    └─ _bb_microbiology(ctx)

  _fhir_nursing.py         ← NEW (~200 lines = 193 + module docstring + imports)
    └─ _build_nursing_observations(ctx)

  _fhir_immunization.py    ← NEW (~60 lines = 50 + module docstring + imports)
    └─ _build_immunizations(ctx)

  fhir_r4_adapter.py       ← import block update (one symbol still from
                             _fhir_observations, three new file imports)
```

### Imports in each new file

All three new files import **only from `_fhir_common.py` and `_fhir_localization.py`**
(plus `clinosim.codes` / `clinosim.locale.loader`), never back through the
adapter — preserving the "no import cycle" property already established by
FA-1 split (`output/README.md` "Extensibility").

Sample header (microbiology):

```python
"""FHIR R4 microbiology builder (Specimen + Observation + DiagnosticReport).

Extracted from _fhir_observations.py in PR3 (AD-55 Module Foundation Refactor
final piece). The ctx-taking builder imports the shared BundleContext from
_fhir_common, so this module never imports back through the adapter.
"""

from __future__ import annotations

from typing import Any

from clinosim.codes import get_system_uri
from clinosim.codes import lookup as code_lookup
from clinosim.locale.loader import load_code_mapping
from clinosim.modules.output._fhir_common import (
    BundleContext,
    _entry,
    _micro_coding,
)
from clinosim.modules.output._fhir_localization import _localize_display
```

Each new file imports **only what it uses** (verified by grep on the
current `_fhir_observations.py` slice). Headers for nursing / immunization
are analogous.

### `fhir_r4_adapter.py` import-block change

Current block (around line 80):

```python
from clinosim.modules.output._fhir_observations import (  # noqa: F401
    _bb_microbiology,
    _build_immunizations,
    _build_lab_observation,
    _build_nursing_observations,
    _build_vital_observations,
)
```

After PR3:

```python
from clinosim.modules.output._fhir_immunization import _build_immunizations  # noqa: F401
from clinosim.modules.output._fhir_microbiology import _bb_microbiology  # noqa: F401
from clinosim.modules.output._fhir_nursing import _build_nursing_observations  # noqa: F401
from clinosim.modules.output._fhir_observations import (  # noqa: F401
    _build_lab_observation,
    _build_vital_observations,
)
```

Alphabetical block order is preserved (`_fhir_immunization` <
`_fhir_microbiology` < `_fhir_nursing` < `_fhir_observations`).

### `_fhir_common.py` promotion review

Reviewed the four builders' helper usage:

| Helper | Current owner | Used by |
|---|---|---|
| `BundleContext` | `_fhir_common` | all 4 |
| `_entry` | `_fhir_common` | all 4 |
| `_loinc_coding` | `_fhir_common` | lab + vital + nursing |
| `_micro_coding` | `_fhir_common` | microbiology |
| `_survey_category` | `_fhir_common` | nursing + immunization |
| `_build_reference_range` | `_fhir_common` | lab + vital |
| `_localize_display` / `_localize_interp` | `_fhir_localization` | lab + vital + micro |

**Conclusion: no new promotion required.** All shared helpers are already in
`_fhir_common.py` from prior FA-1 phases / PR2.

`_SUSCEPTIBILITY_DISPLAY` is microbiology-only and moves with `_bb_microbiology`
to `_fhir_microbiology.py` — it does NOT become a public helper.

### Down-stream caller compatibility

The `noqa: F401` re-exports in `fhir_r4_adapter.py` mean any caller doing
`from clinosim.modules.output.fhir_r4_adapter import _bb_microbiology` keeps
working. The pattern is established by FA-1 / PR1 / PR2 — preserves the
public-surface contract while letting the internal file layout evolve.

Direct callers of the **private file path** `from
clinosim.modules.output._fhir_observations import _bb_microbiology` would
break, but this is internal API. A repo-wide grep confirms `_bb_microbiology`
and `_build_nursing_observations` are referenced **only** from
`fhir_r4_adapter.py` and `_fhir_observations.py` itself. `_build_immunizations`
likewise. (Verified via `grep -rn` during implementation.)

## Verification

### byte-diff (refactor PR gate)

Per `docs/CONTRIBUTING-modules.md` "byte-diff の実施手順":

1. master HEAD (`0ed65f86`):
   `python -m clinosim.simulator.cli generate -p 2000 -s 42 --country US --format fhir-r4 -o scratchpad/pr3_byte_diff/master/us`
   (and `--country JP -o scratchpad/pr3_byte_diff/master/jp`)
2. branch HEAD: same commands → `scratchpad/pr3_byte_diff/branch/{us,jp}`
3. sha256 compare across all 11 NDJSON files (Patient, Encounter, Condition,
   MedicationRequest, MedicationAdministration, Procedure, Observation,
   DiagnosticReport, Immunization, FamilyMemberHistory, Coverage)
4. Gate: **all 11 IDENTICAL for both US and JP**
5. Record results in `scratchpad/pr3_byte_diff_results.md`, commit and link
   from the PR body

### regression test

- `pytest -m "unit or integration"` → 704 green (no new tests; mechanical
  refactor)
- `pytest -m e2e` → 39 green (golden files unchanged by byte-diff invariant)

### no new tests authored

Pure file movement with no logic change. The byte-diff invariant + existing
e2e golden coverage already prove that no functional regression slipped in.

## Documentation sync (in this PR)

Per `feedback_pr_merge_dqr_required`, all docs touched by the refactor are
updated in the same PR (no follow-up doc PR):

| Doc | Update |
|---|---|
| `CLAUDE.md` | "Key directories" → output sub-section: bump per-theme `_fhir_*` builder mention (no path change) |
| `clinosim/modules/output/README.md` | "拡張方法 (Extensibility) 総合ガイド" → list now includes `_fhir_microbiology.py` / `_fhir_nursing.py` / `_fhir_immunization.py` as concrete examples of per-theme split |
| `DESIGN.md` | FA-1 entry continuation: PR3 dissolved the final Observation-multi-theme blob |
| `MODULES.md` | `output/` row description nudge (no inventory count change — module list unchanged) |
| `docs/CONTRIBUTING-modules.md` | **no update** — PR2 already documented theme-by-theme split as canonical pattern |
| `TODO.md` | mark PR3 (G3) complete; note "AD-55 Module Foundation Refactor series complete" |
| `README.md` / `README.ja.md` | **no update** — user-facing interface unchanged |

## 4-axis evaluation recap

| Axis | Score | Reasoning |
|---|---|---|
| データ品質 | △ | byte-identical → no data delta (the no-regression gate) |
| 臨床整合性 | △ | same as above |
| メンテ性 (責任分解クリア) | ◎ | each AD-55 theme owns its file; device + HAI builder addition becomes a single concern, not "where in the 31 KB blob does this go?" |
| コンセプト適切性 | ◎ | identical pattern to PR2 SDOH split — vindicates the AD-55 theme-per-file principle |

## Risk register

| Risk | Mitigation |
|---|---|
| Accidentally drop / re-order a helper import → builder breaks at runtime | byte-diff fails fast; if a single NDJSON diverges, revert and re-do the move |
| Adapter import block typo (wrong path) → `ImportError` at simulator import | `pytest -m unit` covers adapter import in the first second; CI catches this immediately |
| `_SUSCEPTIBILITY_DISPLAY` referenced from elsewhere | grep verified: only used inside `_bb_microbiology`; safe to move with it |
| Builder registration order changes by accident | `_BUNDLE_BUILDERS` list literal in adapter is **not** touched; only the import block changes |

## Out of scope (explicit defer-list, for downstream work)

- Lab + vital further split (`_fhir_labs.py` + `_fhir_vitals.py`). Defer
  until / unless either grows or a third theme needs to join.
- `_fhir_observations.py` rename. Defer; current name is still accurate
  after PR3 (lab + vital = Observation core use case).
- device + HAI builders. Next feature work; will land as new
  `_fhir_device.py` / `_fhir_hai.py` files following PR3's pattern.

## Related links

- PR1 (#83) spec: `docs/superpowers/specs/2026-06-24-ad55-foundation-refactor-pr1-design.md`
- PR2 (#84) spec: `docs/superpowers/specs/2026-06-24-ad55-foundation-refactor-pr2-design.md`
- AD-56 builder registry: `DESIGN.md` AD-56
- FA-1 phased split history: `DESIGN.md` FA-1 entry
- PR verification guide: `docs/CONTRIBUTING-modules.md` "PR 検証ガイド: byte-diff vs 3-axis DQR"
