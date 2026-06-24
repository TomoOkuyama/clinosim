# PR-A — `modules/device` design (Phase 1 of device + HAI series)

**Date**: 2026-06-24
**Series**: device + HAI feature (4 phase PR plan)
**Type**: New feature (3-axis DQR gate)
**Branch**: `feat/device-module-pra`

## Background

Hospital-acquired infections (HAI) — CLABSI / CAUTI / VAP — are the next
clinical realism feature on the clinosim roadmap. Each maps to a specific
indwelling device:

- **CLABSI** ← central venous catheter (CVC)
- **CAUTI** ← indwelling urinary catheter
- **VAP** ← mechanical ventilator

HAI development requires upstream device data — line-days, device-specific
risk windows, and patient-level placement state — to make any of the
sampling, scenario flag, or cohort approaches usable. We split the
two-module feature into a four-phase PR series:

| Phase | PR | Scope |
|---|---|---|
| 1 | **PR-A (this spec)** | `modules/device` + Device + DeviceUseStatement FHIR |
| 2 | PR-B | `modules/hai` (consumes device line-days) + HAI Condition + Observation FHIR |
| 3 | PR-C (if needed) | DRY helper consolidation across both modules |
| 4 | PR-D | Comprehensive docs sync (CONTRIBUTING / MODULES / CLAUDE / README EN/JP) |

PR-A is the first sub-project. It lands the upstream data and the
cross-module dependency point that PR-B will consume.

## Goals

1. New `modules/device/` AD-55 opt-in Module emitting `DeviceRecord`s for
   ICU encounters.
2. Three Phase 1 device types: CVC, indwelling urinary catheter,
   mechanical ventilator (the three HAI source devices).
3. Placement triggered at ICU transfer with state-based indication
   filtering (not all ICU patients get all three devices).
4. New `clinosim/modules/output/_fhir_device.py` builder file emitting
   FHIR R4 `Device` + `DeviceUseStatement` resources (theme-per-file
   pattern established by PR3).
5. Cross-module dependency point: `CIFPatientRecord.extensions["device"]
   = list[DeviceRecord]` (PR-B `hai_enricher` will iterate this).
6. 3-axis DQR PASS (structural / clinical / JP language) — the project's
   true goal per CONTRIBUTING-modules.md "PR 検証ガイド".
7. Documentation sync in PR-A (no follow-up doc PR per
   `feedback_pr_merge_dqr_required`).

## Non-goals (explicit defer-list)

1. **HAI onset logic** — Phase 2 (PR-B).
2. **Peripheral IV** — every inpatient has one; HAI-irrelevant; would
   bloat extensions list. Defer to Phase 5+ only if downstream analytics
   needs it.
3. **Device sub-types** — CVC sub-types (non-tunneled / tunneled / PICC
   / port), catheter types (Foley / suprapubic), ventilator modes
   (volume / pressure control) — all collapsed to the single generic
   SNOMED code per device type. PR-A stays clinically generic.
4. **LOS-mid evolution** (dynamic placement / removal driven by daily
   physiology state). PR-A uses fixed ICU-admission-day placement +
   ICU-discharge-day removal. Defer to Phase 5+.
5. **Vasopressor-based CVC indication**. Phase 1 keeps CVC indication on
   `severity_moderate_plus` only. Vasopressor detection (norepinephrine
   in `medication_orders`) added in Phase 2 / 3 if monitoring shows
   undercount.
6. **Cross-encounter device persistence** (e.g. permanent dialysis
   catheters). PR-A scope is per-encounter only.
7. **Device → physiology state mutation** (e.g. ventilator improves
   SpO2). BNP-pattern surgical principle — state stays immutable; FHIR
   output documents the device, no physiology effect. Future work if
   downstream analytics needs it.
8. **Phase 2 HAI design**. Listed in §"Future work" only; PR-B will get
   its own brainstorming / spec / plan cycle.

## Architecture

### High level

```
PR-A scope:

  ┌─────────────────────────────────────────────────────────┐
  │ modules/device/                                         │
  │   engine.py    ─ pure: place_devices_for_encounter()    │
  │   enricher.py  ─ post_records enricher → extensions     │
  │   reference_data/devices.yaml ─ 3 device SNOMED + criteria│
  └─────────────────────────────────────────────────────────┘
              │
              │ writes CIFPatientRecord.extensions["device"]
              ▼
  ┌─────────────────────────────────────────────────────────┐
  │ Output (existing AD-56 registry)                        │
  │   _fhir_device.py — _build_device + _build_device_use   │
  │   registered via register_bundle_builder()              │
  └─────────────────────────────────────────────────────────┘
              │
              │ emits Device.ndjson + DeviceUseStatement.ndjson
              ▼
            Phase 2 (PR-B) hai_enricher will iterate
            extensions["device"], compute line-days,
            sample CLABSI / CAUTI / VAP onset.
```

### Cross-module dependency point

PR-A's contract with PR-B is `extensions["device"]: list[DeviceRecord]`.
PR-B reads it; PR-A never reads PR-B output. One-way dependency =
foundational AD-55 Module precedent for any future
device-consuming module (not just HAI).

### AD-55 Module classification

- **Opt-in Module** (not Base). Toggled by
  `SimulatorConfig.modules["device"]: bool` (default `true`); when
  disabled the enricher skips, `extensions["device"]` absent, FHIR
  builders emit `[]`.
- post_records enricher (AD-56), runs after CIF construction; main RNG
  untouched.
- Sub-seed: `ENRICHER_SEED_OFFSETS["device"] = 0x4445` ("DE") — 16-bit
  hex-ASCII convention per CLAUDE.md "AD-55 enricher patterns".

## Components

### `clinosim/types/device.py` (new shared type)

```python
"""Device use records (AD-55 Module: device)."""
from __future__ import annotations
from dataclasses import dataclass


@dataclass
class DeviceRecord:
    """One device placement during a patient encounter.

    Stored as list[DeviceRecord] under CIFPatientRecord.extensions["device"].
    Phase 2 hai enricher consumes this to compute line-days for
    CLABSI/CAUTI/VAP onset sampling.
    """
    device_id: str             # "dev-{encounter_id}-{device_type}-{i}"
    encounter_id: str
    device_type: str           # "cvc" | "indwelling_catheter" | "mechanical_ventilator"
    snomed_code: str           # see reference_data/devices.yaml
    placement_date: str        # ISO YYYY-MM-DD
    removal_date: str | None   # None = still in use at snapshot (AD-32)
    placement_indication: str  # comma-joined indication tokens, audit-only
```

The dataclass lives in `clinosim/types/device.py` per CLAUDE.md "All
types in `clinosim/types/`". Exported from `clinosim/types/__init__.py`
under `__all__`.

### `clinosim/modules/device/`

```
__init__.py            ─ public API re-exports
engine.py              ─ pure: place_devices_for_encounter, _evaluate_indications, _indications_met
enricher.py            ─ post_records Enricher (see §"Enricher signature")
reference_data/
  devices.yaml         ─ 3 device SNOMED + placement_criteria
README.md              ─ AD-55 Module README (TEMPLATE_MODULE_README.md)
```

### `reference_data/devices.yaml`

```yaml
# AD-55 Module: device — SNOMED CT codes + placement criteria
# Source: SNOMED CT International, verified via tx.fhir.org $lookup at
# implementation time (memory `reference_tx_fhir_terminology`).
devices:
  cvc:
    snomed_code: "52124006"     # TODO: verify via tx.fhir.org $lookup at impl
    snomed_display_en: "Central venous catheter"
    snomed_display_ja: "中心静脈カテーテル"
    placement_criteria:
      - any: ["severity_moderate_plus"]
  indwelling_catheter:
    snomed_code: "467021000"    # TODO: verify
    snomed_display_en: "Indwelling urinary catheter"
    snomed_display_ja: "膀胱留置カテーテル"
    placement_criteria:
      - any: ["severity_moderate_plus", "altered_consciousness"]
  mechanical_ventilator:
    snomed_code: "706172005"    # TODO: verify
    snomed_display_en: "Mechanical ventilator"
    snomed_display_ja: "人工呼吸器"
    placement_criteria:
      - any: ["hypoxia", "high_respiratory_demand"]
```

**SNOMED codes are tentative until tx.fhir.org `$lookup` verifies them
at implementation time** (memory `feedback_verify_before_asserting`,
PR #80 Coag panel lesson with JLAC10 `2B010` fabrication). The plan's
Task 1 explicitly executes the `$lookup` curl as the first step before
code data lands.

### `engine.py` — placement algorithm

```python
def _evaluate_indications(
    state: PhysiologicalState,
    severity: str,
    altered_consciousness: bool,
) -> set[str]:
    """Return the set of indication tokens met at ICU transfer time."""
    indications: set[str] = set()
    if severity in ("moderate", "severe", "critical"):
        indications.add("severity_moderate_plus")
    if altered_consciousness:
        indications.add("altered_consciousness")
    if state.spo2_baseline < 0.88 or state.respiratory_status < 0.4:
        indications.add("hypoxia")
    if state.respiratory_fraction > 0.7:
        indications.add("high_respiratory_demand")
    return indications


def _indications_met(criteria: list[dict], met: set[str]) -> bool:
    """Evaluate a criteria list (currently only 'any:' supported)."""
    for clause in criteria:
        if "any" in clause and any(tok in met for tok in clause["any"]):
            return True
        # 'all:' / 'not:' deferred; YAGNI for PR-A
    return False


def place_devices_for_encounter(
    record: CIFPatientRecord,
    encounter: Encounter,
    rng: np.random.Generator,
    devices_config: dict,
) -> list[DeviceRecord]:
    """Return DeviceRecord list for a single encounter.

    Returns [] when:
    - encounter has no ICU admission (no icu_admission_date)
    - no device's placement_criteria are met by the patient state
    """
    if not encounter.icu_admission_date:
        return []
    severity = _severity_for_encounter(record, encounter)
    altered = _altered_consciousness_for_encounter(record, encounter)
    state = _peak_state_for_encounter(record, encounter)
    indications = _evaluate_indications(state, severity, altered)
    out: list[DeviceRecord] = []
    for device_type, cfg in devices_config["devices"].items():
        if not _indications_met(cfg["placement_criteria"], indications):
            continue
        out.append(DeviceRecord(
            device_id=f"dev-{encounter.id}-{device_type}-{len(out)}",
            encounter_id=encounter.id,
            device_type=device_type,
            snomed_code=cfg["snomed_code"],
            placement_date=encounter.icu_admission_date,
            removal_date=encounter.icu_discharge_date,
            placement_indication=",".join(sorted(indications)),
        ))
    return out
```

`rng` is taken but not currently used — reserved for future stochastic
adoption rate within indication-positive patients. YAGNI removes
randomness in Phase 1 (deterministic adoption given indication).

### `enricher.py` — post_records pass

```python
from clinosim.simulator.seeding import ENRICHER_SEED_OFFSETS, derive_sub_seed
from clinosim.modules.device.engine import place_devices_for_encounter
from clinosim.modules.device.engine import load_devices_config


def device_enricher(cif: CIFDataset, master_seed: int, country: str) -> None:
    """post_records enricher: walks every CIFPatientRecord, appends to
    extensions['device'] when ICU + indications met. Main RNG untouched."""
    cfg = load_devices_config()  # @lru_cache
    for record in cif.patients:
        sub_seed = derive_sub_seed(
            master_seed,
            ENRICHER_SEED_OFFSETS["device"],
            record.patient.person_id,
        )
        rng = np.random.default_rng(sub_seed)
        devices: list[DeviceRecord] = []
        for encounter in record.encounters:
            devices.extend(place_devices_for_encounter(record, encounter, rng, cfg))
        if devices:
            record.extensions["device"] = devices
```

Registered in `simulator/enrichers.py:register_builtin_enrichers()`
after the existing enrichers. Order is fixed (determinism).

### FHIR builder `_fhir_device.py`

Two builders, one file (theme = "device"). See Section 4 of the
brainstorming for full bodies. Both register via
`register_bundle_builder()` inside the module — order: Device first,
then DeviceUseStatement.

Display localisation: SNOMED CT `code_lookup` already accepts `lang=ja`;
the `codes/data/snomed-ct.yaml` entry gains `ja:` fields for the three
devices.

```python
def _build_device(ctx: BundleContext) -> list[dict]: ...
def _build_device_use(ctx: BundleContext) -> list[dict]: ...
```

Both consume `ctx.record.extensions.get("device", [])`; both return `[]`
when device is empty (no patient ID emitted, no Device.ndjson noise).

Module imports: `BundleContext`, `_entry` from `_fhir_common`;
`code_lookup`, `get_system_uri` from `clinosim.codes`;
`get_attr_or_key` from `clinosim.modules._shared` (DRY pattern PR1
established).

### `clinosim/codes/data/snomed-ct.yaml`

Three new entries:

```yaml
52124006:
  en: "Central venous catheter"
  ja: "中心静脈カテーテル"
467021000:
  en: "Indwelling urinary catheter"
  ja: "膀胱留置カテーテル"
706172005:
  en: "Mechanical ventilator"
  ja: "人工呼吸器"
```

All three pending tx.fhir.org `$lookup` verification at implementation
time.

### `clinosim/simulator/seeding.py:ENRICHER_SEED_OFFSETS`

```python
ENRICHER_SEED_OFFSETS = {
    "identity": 540_054,
    "microbiology": 770_077,
    "immunization": 0x494D,    # "IM"
    "code_status": 0x4353,     # "CS"
    "family_history": 0x4648,  # "FH"
    "care_level": 0x434C,      # "CL"
    "nursing": 0x4E55,         # "NU"
    "device": 0x4445,          # "DE" — PR-A new
}
```

Module-level assert catches duplicates (no collision: `0x4445 = 17477`
is distinct from all current offsets).

### `clinosim/types/config.py:SimulatorConfig.modules`

```python
modules: dict[str, bool] = {
    ...,
    "device": True,   # PR-A: default-on (AD-55 Module opt-in but
                      # production default enables it)
}
```

The default-on choice mirrors immunization / family_history / code_status
(other AD-55 Modules that ship enabled by default). Tests / Phase 2
opt-out via `SimulatorConfig(modules={..., "device": False})`.

## Data flow

```
run_beta()
  ├─ population → patients
  ├─ activate_patient (Layer 2)
  ├─ inpatient/ED/outpatient simulation → CIFPatientRecord
  └─ register_builtin_enrichers() → post_records phase:
      ├─ immunization_enricher
      ├─ family_history_enricher
      ├─ code_status_enricher
      ├─ care_level_enricher
      ├─ nursing_enricher
      └─ device_enricher          ← PR-A new
          ├─ derive_sub_seed(master, 0x4445, person_id)
          ├─ for each encounter:
          │   ├─ skip if not ICU
          │   └─ for each device_type:
          │       ├─ check placement_criteria
          │       └─ append DeviceRecord
          └─ record.extensions["device"] = list

  ↓ output adapter
  fhir_r4_adapter._BUNDLE_BUILDERS
    ├─ ... (existing)
    ├─ _build_device              ← PR-A new
    └─ _build_device_use          ← PR-A new

  → Device.ndjson, DeviceUseStatement.ndjson
```

## Verification — 3-axis DQR (new feature PR gate)

Per CONTRIBUTING-modules.md "PR 検証ガイド": new feature ⇒ 3-axis DQR is
the goal-achievement gate; byte-diff is informative only.

### byte-diff (informational)

Master `89969152` vs branch HEAD at US p=2000 + JP p=2000 seed=42:

- **All 11 / pre-existing NDJSON byte-identical** (Patient / Encounter /
  Condition / MedicationRequest / MedicationAdministration / Procedure /
  Observation / DiagnosticReport / Immunization / FamilyMemberHistory /
  Coverage / Practitioner / ...). The post_records enricher pattern +
  independent sub-seed guarantees main RNG untouched (AD-16 / AD-56 /
  PR3 pattern).
- **New NDJSON 2 files**: `Device.ndjson` + `DeviceUseStatement.ndjson`.
  These are intentional additions, not regressions.

If any pre-existing NDJSON differs: the enricher leaked into main RNG —
stop and fix.

### 3-axis DQR

US p=10000 seed=42 + JP p=5000 seed=42. Results recorded in
`docs/reviews/2026-06-24-device-module-data-quality-review.md`.

#### Axis 1 — structural

- Device.id uniqueness within Device.ndjson = 100% (per-encounter scope:
  `dev-{encounter_id}-{device_type}-{i}` collisions impossible)
- DeviceUseStatement.id uniqueness = 100%
- Every DeviceUseStatement.device.reference resolves to a Device.id
  present in Device.ndjson (referential integrity = 100%)
- Every DeviceUseStatement.context.reference resolves to an Encounter.id
  (referential integrity = 100%)
- Device.type.coding[].display never equals coding[].code (display ≠
  code = 100%)
- DeviceUseStatement.status field present on every resource (`active` |
  `completed`)
- DeviceUseStatement.timingPeriod.start present on every resource (no
  unbounded periods)

#### Axis 2 — clinical coherence

- **ICU subset**: ≥ 99% of devices belong to encounters with an
  `icu_admission_date`. Non-ICU device count ≈ 0 (rounding floor for
  legacy data only).
- **CVC adoption**: ≥ 80% of severe-sepsis / cardiogenic-shock / MI ICU
  patients receive a CVC.
- **CVC adoption (mild ICU)**: < 30% for post-op observation /
  uncomplicated DKA ICU encounters.
- **Ventilator adoption**: ≥ 70% in COPD-severe-exacerbation +
  respiratory-failure pneumonia subsets; < 20% in observation-only ICU.
- **Catheter adoption**: ≥ 60% across moderate+ ICU; ≥ 90% in altered
  consciousness sepsis.
- **Line-days p50 / p90**:
  - CVC line-days p50 = 5-15, p90 ≤ 30
  - Catheter line-days p50 = 4-12, p90 ≤ 25
  - Ventilator line-days p50 = 3-10, p90 ≤ 20
- **Snapshot in-progress**: ≤ 5% of devices have `removal_date=null`
  (matches AD-32 in-progress encounter rate baseline).

#### Axis 3 — JP language quality

- US Device + DeviceUseStatement output: zero Japanese characters
  (`grep -P '[\\p{Han}\\p{Hiragana}\\p{Katakana}]' Device.ndjson` =
  empty).
- JP Device.type.coding[].display: 100% Japanese ("中心静脈カテーテル"
  / "膀胱留置カテーテル" / "人工呼吸器").
- JP Device.type.text: 100% Japanese.
- No CM-granular SNOMED leak (SNOMED is international; this axis is a
  no-op for SNOMED but the audit script confirms presence of valid
  codes from `snomed-ct.yaml`).

### audit script

`scratchpad/device_dqr/dqr_audit.py` — template from PR3's PR3 byte-diff
script + DQR loop. Reusable in PR-B for HAI 3-axis DQR.

## Tests

### Unit

- `tests/unit/test_device_engine.py`
  - `_evaluate_indications`: deterministic given identical state; each
    boolean lever flips one and only one indication token
  - `_indications_met`: `any:` clause evaluation correctness; empty
    criteria → False; mixed clauses unsupported (`all:` raises or
    returns False — pick one)
  - `place_devices_for_encounter`: non-ICU encounter → `[]`; ICU
    encounter with no indications met → `[]`; ICU encounter with all 3
    indications met → 3 DeviceRecords; device_id format
- `tests/unit/test_device_enricher.py`
  - Sub-seed isolation: two runs with different `device_enricher`
    seeds produce different `extensions["device"]` but the master RNG
    stream (verified via `test_seeding.py` precomputed literals) is
    untouched
  - Empty / non-ICU patient population → all `extensions["device"]` empty
  - Module-disabled (`SimulatorConfig.modules["device"] = False`)
    skips enrichment

### Integration

- `tests/integration/test_device_extension_persistence.py`
  - CIF JSON round-trip preserves `extensions["device"]` as
    `list[DeviceRecord]` (or dict, via `_shared.get_attr_or_key`)
- `tests/integration/test_device_fhir_output.py`
  - Generate a small p=20 ICU-heavy cohort; verify Device + DUS NDJSON
    contain ≥ 1 device per ICU encounter where indication met; integrity
    checks (refs resolve, ids unique)

### e2e

No new e2e tests authored; existing golden snapshot updates expected for
runs that ship FHIR Device output. Note: the e2e suite covers
representative runs and golden files will need a refresh in the same PR.

### Code coverage of new SNOMED codes

`tests/unit/test_diagnosis_code_coverage.py` is ICD-only (deliberately
out of scope). A new tiny test
`tests/unit/test_device_snomed_coverage.py` confirms the 3 SNOMED codes
in `devices.yaml` resolve via `code_lookup("snomed-ct", code, "en")`
and `code_lookup(..., "ja")` to non-empty, non-code strings — a smoke
guard that the `codes/data/snomed-ct.yaml` additions landed.

## Documentation sync (in this PR)

| Doc | Update |
|---|---|
| `clinosim/modules/device/README.md` | New; TEMPLATE_MODULE_README.md skeleton; Dependencies (types/codes); Consumers (`simulator/enrichers.py`, `output/_fhir_device.py`); データ構造 (DeviceRecord); API (`place_devices_for_encounter`) |
| `MODULES.md` | Inventory: new `device` row (enrichment layer, Tier: optional, Dependencies: types/codes, Consumers: simulator/enrichers + output) |
| `DESIGN.md` AD-56 entry | Append continuation: "**PR-A device module 2026-06-24** added `modules/device/` (post_records enricher emitting CVC + catheter + ventilator for ICU patients), `_fhir_device.py` builder file (Device + DeviceUseStatement), and `ENRICHER_SEED_OFFSETS["device"] = 0x4445`. Phase 1 of the device + HAI 4-PR series; PR-B will add `modules/hai` consuming `extensions["device"]`." |
| `CLAUDE.md` "Key directories" | Add `device/  <- ★ ICU device placement (CVC/catheter/ventilator, AD-55 Module)` line |
| `CLAUDE.md` "AD-55 enricher patterns" | Add device offset to the convention example list |
| `clinosim/modules/output/README.md` | Extensibility table: add `_fhir_device.py` row |
| `clinosim/simulator/seeding.py:ENRICHER_SEED_OFFSETS` | Add `"device": 0x4445` |
| `TODO.md` | New PR-A done entry; Phase 2-4 backlog explicit |
| `README.md` / `README.ja.md` | "Quality & Compliance" module list mention device; "v0.2" feature blurb gain device line |
| `SCENARIO_FLAGS.md` | No change (device is an enricher, not a flag) |
| `docs/CONTRIBUTING-modules.md` | No change (pattern reuse) |

## 4-axis evaluation

| Axis | Score | Reasoning |
|---|---|---|
| データ品質 | ○ | Two new FHIR resources; SNOMED authoritative; ICU-realistic distribution; line-days clinically plausible |
| 臨床整合性 | ◎ | State-based placement criteria (severity / consciousness / SpO2 / respiratory_fraction); per-device line-days verified in DQR |
| メンテ性 (責任分解クリア) | ◎ | AD-55 Module + PR3 theme-per-file; clean cross-module dependency point for PR-B |
| コンセプト適切性 | ◎ | enricher + extensions / cross-module consume pattern established for the rest of the 4-PR series |

## Risk register

| Risk | Mitigation |
|---|---|
| SNOMED codes fabricated (PR #80 lesson) | Task 1 of the plan runs tx.fhir.org `$lookup` curl before any code data lands. # TODO: verify markers in YAML mean spec is non-binding until verified. |
| device enricher leaks into main RNG → byte-diff regression | independent sub-seed (PR1 pattern). byte-diff invariant catches it. |
| ICU adoption rate clinically wrong | Axis 2 DQR with explicit per-subset thresholds catches it; YAML criteria adjustable. |
| extensions["device"] forgotten in CIF JSON dump | integration test `test_device_extension_persistence.py` covers round-trip. |
| Phase 2 PR-B blocked because PR-A contract unclear | This spec's §"Cross-module dependency point" + §"Future work" plus PR-B brainstorming in its own session. |

## Future work (Phase 2 PR-B preview, non-binding)

- `modules/hai/` enricher reads `extensions["device"]`, computes
  line-days, samples CLABSI / CAUTI / VAP onset (mechanism TBD —
  scenario flag vs sampling vs medication-coupling will be
  brainstormed in PR-B's own session).
- New FHIR resources: `Condition` (HAI ICD-10), `Observation`
  (microbiology + identification + susceptibility — already covered by
  PR3-extracted `_fhir_microbiology.py`), `Procedure` (treatment).
- New `_fhir_hai.py` builder file (Condition emission only; reuses
  existing microbiology builder for cultures).
- New SNOMED + ICD codes for the three HAI conditions; tx.fhir.org +
  NLM API verification.

## Related links

- PR3 (#87) theme-per-file split: `docs/superpowers/specs/2026-06-24-pr3-fhir-observations-split-design.md`
- PR2 (#84) SDOH integrity: `docs/superpowers/specs/2026-06-24-ad55-foundation-refactor-pr2-design.md`
- PR1 (#83) foundation refactor: `docs/superpowers/specs/2026-06-24-ad55-foundation-refactor-pr1-design.md`
- AD-55 Base vs Module decision: `docs/CONTRIBUTING-modules.md` "判断: Base か Module か"
- AD-56 builder + enricher registry: `DESIGN.md` AD-56
- ENRICHER_SEED_OFFSETS convention: `CLAUDE.md` "AD-55 enricher patterns"
- PR verification gate: `docs/CONTRIBUTING-modules.md` "PR 検証ガイド"
- Reference terminology server for SNOMED `$lookup`: memory `reference_tx_fhir_terminology` (tx.fhir.org)
