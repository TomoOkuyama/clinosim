# `fhir_r4/post_process/` — bundle-level FHIR R4 post-processing pipeline

## Purpose

Bundle-level pipeline (PR3, folds Issue #556) that runs the final
transformations over an already-emitted per-patient FHIR Bundle:
datetime / instant normalisation across timezones (JST vs UTC),
JP-CLINS profile URI assertion + must-support slot population,
companion Specimen synthesis for lab / microbiology Observations,
and the strip pass that drops empty extension / narrative / cardinality
`0` fields the spec forbids emitting. Runs after every per-resource
builder has fired, so it sees the assembled bundle at once and can
apply cross-resource fixups that a single builder cannot.

## Scope

- **In scope**:
  - `datetime_normalize.py` — walks the assembled bundle and
    normalises every `_DATETIME_FIELDS` (dateTime / date +
    Period.start / end + instant `issued` / `lastUpdated`) so JP
    output carries `+09:00` JST and US output carries `Z`.
  - `profile.py` — asserts JP-CLINS profile URIs on every
    Observation / Composition / MedicationRequest / etc., populates
    the JP eCS `JP_CLINS_ObsLabResult_*` must-support slots
    (uncoded / localcode fallback when a JLAC10 mapping is
    missing), and enforces the JP `_FHIR_ID_PATTERN` (defined
    locally: `[A-Za-z0-9\-\.]{1,64}`).
  - `specimen.py` — synthesises a companion `Specimen` resource per
    lab / microbiology Observation (`_COMPANION_SPECIMEN_ID_PREFIX =
    "spec-"`, `_SPECIMEN_TYPE_BLOOD` / `_SPECIMEN_TYPE_URINE`
    SNOMED tuples with EN + JA display).
  - `strip.py` — drops empty extension / narrative / cardinality
    `0` fields.
  - `populate.py` — the large per-JP-profile populate pass
    (~825 LOC) that fills the JP eCS + JP-CLINS extensions, MEDIS
    disease keynumber (`_MEDIS_DISEASE_KEYNUMBER_SYSTEM =
    "http://medis.or.jp/CodeSystem/master-disease-keyNumber"` with
    `_MEDIS_UNCODED_DISEASE_CODE = "99999999"` +
    `_MEDIS_UNCODED_DISEASE_DISPLAY = "未コード化傷病名"`),
    JP MHLW ingredient-strength type (`_JP_MHLW_MEDICATION_INGREDIENT_STRENGTH_TYPE_CS`
    with `_JP_MHLW_STRENGTH_TYPE_PHARMACEUTICAL_CODE = "1"` +
    display `"製剤量"`), medication usage ePrescription
    (`_JP_MHLW_MEDICATION_USAGE_EPRESCRIPTION_CS`), MedicationUsage
    uncoded fallback (`_JP_CLINS_MEDICATION_USAGE_UNCODED_CS` with
    code `"0X0XXXXXXXXX0000"`, display `"用法未指定"`) — used only when
    `_resolve_mhlw_usage_code(drug_text, freq, period, period_unit)`
    (Issue #817, PRs #836/#837/#838) cannot map the (drug, cadence)
    tuple to a real `MedicationUsage_ePrescription` code; that
    resolver applies a drug-class + frequency heuristic (statins→QD-
    就寝前, PPIs→QD-朝食前, bisphosphonates→QD-起床時, ワルファリン
    →QD-夕食後, biguanides→BID-朝夕食後, antibiotics→TID-朝昼夕食後
    …) plus PRN condition codes (アセトアミノフェン→発熱時、
    サルブタモール→喘息発作時), giving ~97.6% real-code coverage on
    the JP p=10000 s500 sample; the remaining ~2.4% dummy is
    hourly cadence (Q6H / Q8H — MHLW CS has no pure-hourly code) +
    IV parenteral drugs (生理食塩液 etc.),
    period-of-use extension URL (`_JP_MEDICATION_DOSAGE_PERIOD_OF_USE_EXT_URL`),
    UCUM day code (`_UCUM_SYSTEM_URI`, `_UCUM_DAY_CODE = "d"`,
    `_UCUM_DAY_UNIT_JA = "日"`), and the JP resource-instance
    identifier system (`_JP_OBSERVATION_RESOURCE_IDENTIFIER_SYSTEM =
    "http://jpfhir.jp/fhir/core/IdSystem/resourceInstance-identifier"`,
    plus the clinosim internal `_CLINOSIM_OBSERVATION_ID_SYSTEM =
    "urn:clinosim:observation-id"`), and the JP observation
    category (`_JP_OBSERVATION_CATEGORY_SYSTEM =
    "http://jpfhir.jp/fhir/core/CodeSystem/JP_SimpleObservationCategory_CS"`);
    also owns `_JP_ECS_LAST_UPDATED_PLACEHOLDER =
    "2026-01-01T00:00:00+09:00"` used when a resource has no
    natural `meta.lastUpdated` anchor.
- **Out of scope**: per-resource builder logic (in the sibling
  clinical-domain subpackages); NDJSON serialisation itself (in
  [`../__init__.py`](../__init__.py)); the FHIR profile
  definitions themselves (they live in the
  [`../labs/coding_package.py`](../labs/coding_package.py)-loaded
  JP-CLINS + jpfhir-terminology packages).

## Public API

Every pass is called from `convert_cif_to_fhir` in
[`../__init__.py`](../__init__.py); outside callers do not import
these files directly. The `__all__` in each file names the
externally-callable entry (e.g. `normalise_datetimes`,
`synthesise_specimens`, `apply_jp_clins_profile`, `strip_empties`,
`populate_jp_extensions`).

## Determinism

Not applicable — every pass is a pure transformation over the
already-assembled bundle. `_JP_ECS_LAST_UPDATED_PLACEHOLDER` is a
deterministic constant (`"2026-01-01T00:00:00+09:00"`) so cohort
byte-identity is preserved across runs.

## Dependencies

- `clinosim.modules._shared` — `is_jp`, `resolve_lang`.
- `clinosim.modules.output.fhir_r4.lib.common` — `BundleContext`
  + `_FHIR_ID_PATTERN` (imported and re-defined locally in
  `populate.py` for the JP-side ID check).
- `clinosim.codes` — LOINC / SNOMED / JP-CLINS code display lookup.
- `re`, `datetime` — standard library for datetime + regex passes.

## Constants and configuration

- **Datetime normalisation** (`datetime_normalize.py`):
  - `_DATETIME_FIELDS` — frozenset of every FHIR dateTime / date
    field name the walker visits.
  - `_PERIOD_FIELDS = frozenset(("start", "end"))`.
  - `_PERIOD_KEYS` — frozenset of every Period-wrapping field key.
  - `_INSTANT_FIELDS = frozenset(("issued", "lastUpdated"))`.
- **Companion specimen** (`specimen.py`):
  - `_COMPANION_SPECIMEN_ID_PREFIX = "spec-"`.
  - `_SPECIMEN_TYPE_BLOOD = {"code": "119297000", "display_en":
    "Blood specimen", "display_ja": "血液検体"}`.
  - `_SPECIMEN_TYPE_URINE = {"code": "122575003", "display_en":
    "Urine specimen", "display_ja": "尿検体"}`.
- **JP-CLINS + MHLW code systems** (`populate.py`, exhaustive list
  in Scope above). Every constant is imported by JP-side downstream
  builders + the `document` AD-60 audit for cross-verification.
- **`_JP_ECS_LAST_UPDATED_PLACEHOLDER = "2026-01-01T00:00:00+09:00"`**
  — deterministic anchor used only when a resource has no real
  `meta.lastUpdated` source.

## Directory contents

```
clinosim/modules/output/fhir_r4/post_process/
  __init__.py                       pipeline entry (dispatches datetime → specimen → profile → populate → strip)
  datetime_normalize.py             timezone + Period + instant normalisation
  specimen.py                       companion Specimen synthesis (spec- prefix, blood/urine SNOMED)
  profile.py                        JP-CLINS profile URI assertion + JLAC10 must-support slot population
  populate.py                       large JP eCS + MHLW + MEDIS + UCUM populate pass (~825 LOC)
  strip.py                          drop empty extension / narrative / cardinality-0 fields
```

## Testing

```bash
pytest tests/unit -k "post_process or datetime_normalize or profile or specimen or strip or populate" -q
pytest tests/integration -k "jp_clins or document_chain" -q
```

Cross-verification: the `document` AD-60 audit plug-in
([`../../../document/audit.py`](../../../document/audit.py))
exercises many post-process invariants through its 49-check
`lift_firing_proof` (JP-CLINS profile URIs, JP eCS extensions,
MEDIS uncoded fallback presence). The JP-CLINS package loader
([`../labs/coding_package.py`](../labs/coding_package.py)) supplies
the profile URIs that `profile.py` asserts against.

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
