# `fhir_r4/medications/` — MedicationRequest + MedicationAdministration builders

## Purpose

Emits the two medication FHIR R4 resources:
`MedicationRequest` (prescription — inpatient inflow, discharge
outflow, outpatient) and `MedicationAdministration` (MAR entry per
administered dose). JP path emits YJ code + optional MEDIS
`NOCODED` fallback per JP-CLINS Medication profile; US path emits
RxNorm. The JP `MedicationRequest.status='completed'` /
`intent='order'` pattern pin (imposed by `JP_MedicationRequest_eCS`)
is applied after the builder by
`_populate_condition_ai_mr_ecs_fields` in
[`../post_process/populate.py`](../post_process/populate.py); when
the builder-set status differs (e.g. `active`, or `stopped` for a
narrowed / discontinued
[`antibiotic`](../../../antibiotic/README.md) regimen), the original
status is preserved in the
`urn:clinosim:medicationrequest-effective-status` extension plus a
`note[]` text (no `statusReason` is emitted).

## Scope

- **In scope**: `_build_medication_request` (root prescription
  builder — inpatient / outpatient dispatch); `_build_discharge_medication_request`
  (discharge outflow with the `rxdc-` id prefix); `_build_medication_admin`
  (per-dose MAR); `_build_medication_request_meta` +
  `_build_medication_request_identifiers` (JP eCS meta +
  identifiers); `_build_category_block` + `_build_course_of_therapy_block`
  (MedicationRequest category + course-of-therapy CodeableConcepts
  using the terminology.hl7.org CodeSystems); ID prefixes:
  `DISCHARGE_RX_ID_PREFIX = "rxdc-"`, `OUTPATIENT_RX_ID_PREFIX =
  "rxopd-"`, `MEDICATION_REQUEST_KEY_SYSTEM =
  structural_key_system("medication-request-key")`; per-country
  supply-duration unit (`_SUPPLY_DURATION_UNIT_JP = "日"` /
  `_SUPPLY_DURATION_UNIT_US = "d"`, code `_SUPPLY_DURATION_CODE = "d"`);
  JP YJ + MEDIS uncoded constants (`_JP_YJ_CODE_URI`,
  `_JP_MEDICATION_CODE_NOCODED_CS`,
  `_JP_MEDICATION_CODE_NOCODED_CODE = "NOCODED"`,
  `_JP_MEDICATION_CODE_NOCODED_DISPLAY = "標準コードなし"`).
- **Out of scope**: prescription / MAR **generation**
  ([`order`](../../../order/README.md),
  [`simulator`](../../../../simulator/),
  [`antibiotic`](../../../antibiotic/README.md));
  drug code registries
  ([`clinosim/codes/data/{rxnorm,yj,hot7}.yaml`](../../../../codes/data/));
  discharge-medication reason / narrow-target dose defaults
  ([`antibiotic/_narrow_dose_defaults.py`](../../../antibiotic/_narrow_dose_defaults.py)).

### Chemotherapy cycle MR + MAR (v0.5 → v0.6.0)

For every `chemo_visit` LifeEvent, [`order`](../../../order/README.md)
emits one `MedicationRequest` plus one `MedicationAdministration` per
regimen `cycle_orders` drug — sharing the same `order_id` so this
subpackage's `_bb_medication_requests` / `_bb_medication_admins`
builders pair them cleanly at emit time. The JP path continues to
pin `MedicationRequest.status = "completed"` (see Purpose); the MAR side
carries `effectiveDateTime` = the cycle Day-1 administration
timestamp. Multi-day infusion drug expansion (e.g. FOLFOX's 46-h
5-FU) is a follow-up slice — the current MVP emits one MAR per
Day-1 drug.

## Public API

Every builder is registered with the parent facade
(`_BUNDLE_BUILDERS` in [`../builder.py`](../builder.py)) as
`_bb_medication_requests`, `_bb_discharge_medication_requests`,
and `_bb_medication_admins` — the low-level `_build_*` functions
live in `medications.py`:

```python
from clinosim.modules.output.fhir_r4.medications.medications import (
    _build_medication_request,
    _build_discharge_medication_request,
    _build_medication_admin,
    _build_medication_request_meta,
    _build_medication_request_identifiers,
    _build_category_block,
    _build_course_of_therapy_block,
    # ID prefixes + system URIs
    DISCHARGE_RX_ID_PREFIX,               # "rxdc-"
    OUTPATIENT_RX_ID_PREFIX,              # "rxopd-"
    MEDICATION_REQUEST_KEY_SYSTEM,        # structural key system URI
    MEDICATION_ADMINISTRATION_ID_PREFIX,  # "mar-"
)
```

The `_bb_*` registered names live in
[`../lib/inline_bb.py`](../lib/inline_bb.py)
(`_bb_medication_requests`, `_bb_discharge_medication_requests`,
`_bb_medication_admins`) — the split into a dedicated
`medications/` subpackage kept the fragment builders, not the
`_bb_*` registrations, per the FA-1 phased refactor.

## Determinism

Not applicable — pure builders over CIF orders + MAR records.

## Dependencies

- `clinosim.modules._shared` — `is_jp`, `resolve_lang`,
  `get_attr_or_key`.
- `clinosim.modules.output.fhir_r4.lib.common` — `build_ucum_quantity`,
  dosage / route / status helpers.
- `clinosim.modules.output.fhir_r4.lib.ids` — `derive_opaque_id` +
  `structural_key_system`.
- `clinosim.modules.output.fhir_r4.conditions.primary_ref` —
  `primary_condition_ref_from_codes` for
  `MedicationRequest.reasonReference` /
  `MedicationAdministration.reasonReference` (lazy import).
- `..demographics.patient.patient_ref`,
  `..encounters.encounter.encounter_ref`.
- `clinosim.codes` — RxNorm / YJ / HOT display lookup;
  `clinosim.locale.loader.load_code_mapping`.
- Orders / MAR records are read as CIF dicts; no `clinosim.types`
  classes are imported.

## Constants and configuration

- **ID prefixes**: order-derived MedicationRequest ids are opaque
  `mr-{sha256(order_id)[:12]}` (`_resolve_mr_id`, Issue #853; the
  structural key survives in `identifier[]`); discharge outflow uses
  `DISCHARGE_RX_ID_PREFIX = "rxdc-"`; outpatient uses
  `OUTPATIENT_RX_ID_PREFIX = "rxopd-"`; MedicationAdministration
  uses `MEDICATION_ADMINISTRATION_ID_PREFIX = "mar-"`. The
  [`antibiotic`](../../../antibiotic/README.md) module additionally
  emits its regimens under `ABX_ORDER_REQ_PREFIX` /
  `ABX_NARROW_SUFFIX` — those live in
  [`antibiotic/engine.py`](../../../antibiotic/engine.py).
- **Terminology systems** (HL7 CodeSystem for `MedicationRequest`
  metadata):
  - `_MR_CATEGORY_SYSTEM = "http://terminology.hl7.org/CodeSystem/medicationrequest-category"`.
  - `_MR_COURSE_OF_THERAPY_SYSTEM = "http://terminology.hl7.org/CodeSystem/medicationrequest-course-of-therapy"`.
  - Two courses used: `_COURSE_CONTINUOUS =
    ("continuous", "Continuous long term therapy")` and
    `_COURSE_ACUTE = ("acute", "Short course (acute) therapy")`.
- **Supply-duration units**: JP emits `"日"` display,
  US emits `"d"` display, both with UCUM code `"d"`.
- **JP YJ code system**: `_JP_YJ_CODE_URI =
  "http://capstandard.jp/iyaku.info/CodeSystem/YJ-code"`. When a
  drug has no YJ mapping, the builder emits the JP eCS
  Medication_Common `NOCODED` fallback
  (`_JP_MEDICATION_CODE_NOCODED_CS`, `_JP_MEDICATION_CODE_NOCODED_CODE
  = "NOCODED"`, display `"標準コードなし"`).
- **JP `MedicationRequest.status = "completed"`** — pinned on JP
  output by `post_process/populate.py`
  (`_populate_condition_ai_mr_ecs_fields`) per
  `JP_MedicationRequest_eCS`; a differing builder status (`active`,
  `stopped`, …) is kept in the
  `urn:clinosim:medicationrequest-effective-status` extension
  (`valueCode`) and a Japanese `note[]` text. The builder itself
  sets `stopped` for stop orders (`MED_STOP_ORDER_ID_MARKER`).

## Directory contents

```
clinosim/modules/output/fhir_r4/medications/
  __init__.py                        namespace stub (builders imported by ../builder.py / ../lib/inline_bb.py)
  medications.py                     _build_medication_request + _build_discharge_medication_request + _build_medication_admin + JP eCS fragments
```

## Testing

```bash
pytest tests/unit -k "medication_request or medication_admin or discharge_rx or fhir_medications" -q
pytest tests/integration -k "antibiotic or servicerequest_chain" -q
```

The `antibiotic` AD-60 audit plug-in
([`../../../antibiotic/audit.py`](../../../antibiotic/audit.py))
cross-verifies emit invariants on `_build_medication_request` +
`_build_medication_admin` through its `lift_firing_proof`.

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
