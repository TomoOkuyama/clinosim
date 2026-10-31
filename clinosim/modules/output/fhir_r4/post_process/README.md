# `fhir_r4/post_process/` — bundle-level FHIR R4 post-processing pipeline

## Purpose

Post-emit resource-shape passes (PR3, folds Issue #556) applied to
every resource a `_bb_*` builder returns: datetime / instant
normalisation across timezones (JST vs UTC), JP Core / JP-CLINS /
US Core profile URI assertion + JP eCS must-support field
population, companion Specimen synthesis for lab Observations, and
two strip passes (forbidden `Observation.referenceRange` extensions;
Japanese `display` on English-only CodeSystems). The passes are
called per resource inside `_build_bundle` in
[`../builder.py`](../builder.py) (and on the facility bundle in
`convert_cif_to_fhir`), immediately after each builder yields the
resource — not as a separate pass over an assembled bundle.

## Scope

- **In scope**:
  - `datetime_normalize.py` — walks each emitted resource and
    normalises every `_DATETIME_FIELDS` (dateTime / date +
    Period.start / end + instant `issued` / `lastUpdated`) so JP
    output carries `+09:00` JST and US output carries `Z`.
  - `profile.py` — stacks JP Core / JP-CLINS (JP) or US Core (US)
    profile URIs in `meta.profile` (`_apply_jp_core_profile`,
    `_apply_jp_clins_profile`, `_apply_us_core_profile`); the URL
    registries are loaded from
    `clinosim/codes/data/fhir-profiles-{jp-core,us-core,jp-clins}.yaml`.
    Also owns `_JP_OBSERVATION_CATEGORY_SYSTEM`,
    `_JP_ECS_LAST_UPDATED_PLACEHOLDER` and resource-type
    discriminators (`_is_lab_observation`,
    `_medication_request_satisfies_ecs`). It carries an unused local
    copy of `_FHIR_ID_PATTERN`.
  - `specimen.py` — synthesises a companion `Specimen` resource per
    lab Observation (id prefix `lab-`, no builder-set `specimen`;
    microbiology carries its own Specimen) with
    `_COMPANION_SPECIMEN_ID_PREFIX = "spec-"` (opaque id via
    `lib/ids.py`) and SNOMED type codes `_SPECIMEN_SNOMED_BLOOD =
    "119297000"` / `_SPECIMEN_SNOMED_URINE = "122575003"` (displays
    resolved via `clinosim.codes`).
  - `strip.py` — `_strip_forbidden_observation_reference_range_extensions`
    (removes `Observation.referenceRange[*]` extensions that
    `JP_Observation_LabResult_eCS` locks to `max=0`) and
    `_strip_japanese_display_on_english_only_systems` (drops a
    Japanese `display` on English-only CodeSystems; the
    CodeableConcept `text` survives).
  - `populate.py` — the large populate module (~1,300 LOC) that
    fills the JP eCS + JP-CLINS extensions, MEDIS
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
    `_resolve_mhlw_usage_code(drug_text, freq, period, period_unit,
    route_text)` (Issue #817, PRs #836/#837/#838/#840/#841) cannot
    map the (drug, cadence, route) tuple to a real
    `MedicationUsage_ePrescription` code. The resolver dispatch order
    is: (1) **route filter** — non-oral routes
    (`_non_oral_route_markers()`, loaded from
    `clinosim/codes/data/mhlw-ecs-non-oral-route-markers.yaml`: 静注/皮下注/筋注/吸入/舌下/貼付/塗布/
    点眼/直腸/経腸/etc.) always return dummy because the MHLW oral CS
    has no code family for them, (2) **PRN condition codes**
    (アセトアミノフェン→発熱時、サルブタモール→喘息発作時) via
    `_DRUG_PRN_MHLW_CODE`, (3) **fixed-interval hourly** (Q3H → 1028…
    only, other hourly codes collide with meal-context) via
    `_HOURLY_CADENCE_MHLW_CODE`, (4) **daily cadence + meal-context**
    heuristic (statins→QD-就寝前, PPIs→QD-朝食前, bisphosphonates→QD-
    起床時, ワルファリン→QD-夕食後, biguanides→BID-朝夕食後,
    antibiotics→TID-朝昼夕食後 …) via `_FREQ_CONTEXT_TO_MHLW_CODE`,
    (5) **drug-implied freq** for missing timing.repeat via
    `_DRUG_IMPLIED_FREQ_{QD,BID,TID}` sets. These dispatch tables are
    yaml-backed module constants loaded from
    `clinosim/codes/data/mhlw-medication-usage-code.yaml` and
    `clinosim/codes/data/clinosim-drug-dosing-conventions.yaml`. Reaches ~85.9% real-code
    coverage (all coded records are 100% semantically correct — MHLW
    oral code is emitted **only** on `route.text=="経口"`) on the
    JP p=10000 s500 sample. The remaining ~14.1% dummy is
    MHLW-CS-unmappable routes (吸入 10,175 / 静注 3,022 / 皮下注 2,675
    / etc.) — spec-legit per JP-CLINS fixture.
    Prior wave (PR #836/#837/#838 pre-route-filter) reported ~97.6%
    coverage, but that included ~13,796 semantically-wrong records
    (IV/inhaled drugs given oral 服用 codes). The current lower
    numeric coverage is a semantic-correctness win, not a regression,
    period-of-use extension URL (`_JP_MEDICATION_DOSAGE_PERIOD_OF_USE_EXT_URL`),
    UCUM day code (`_UCUM_DAY_CODE = "d"`,
    `_UCUM_DAY_UNIT_JA = "日"`), and the JP resource-instance
    identifier system (`_JP_OBSERVATION_RESOURCE_IDENTIFIER_SYSTEM =
    "http://jpfhir.jp/fhir/core/IdSystem/resourceInstance-identifier"`,
    plus the clinosim internal `_CLINOSIM_OBSERVATION_ID_SYSTEM =
    "urn:clinosim:observation-id"`), and the JP observation
    category normaliser (`_normalize_jp_observation_category`, using
    `profile._JP_OBSERVATION_CATEGORY_SYSTEM =
    "http://jpfhir.jp/fhir/core/CodeSystem/JP_SimpleObservationCategory_CS"`),
    plus `_populate_condition_ai_mr_ecs_fields` and
    `_populate_practitioner_reference_display`.
    `_JP_ECS_LAST_UPDATED_PLACEHOLDER = "2026-01-01T00:00:00+09:00"`
    (in `profile.py`) is the fallback when a resource has no natural
    `meta.lastUpdated` anchor.
- **Out of scope**: per-resource builder logic (in the sibling
  clinical-domain subpackages); NDJSON serialisation itself (in
  [`../builder.py`](../builder.py)); the FHIR profile
  definitions themselves (they live in the
  [`../labs/coding_package.py`](../labs/coding_package.py)-loaded
  JP-CLINS + jpfhir-terminology packages).

## Public API

Every pass is called from `_build_bundle` / `convert_cif_to_fhir`
in [`../builder.py`](../builder.py). All entry points are
underscore-prefixed; `post_process/__init__.py` re-exports them
(`__all__`) as an atomic-migration facade, e.g.
`_normalize_dt_fields`, `_normalize_dt_and_fill_practitioner_display`,
`_apply_jp_core_profile`, `_apply_jp_clins_profile`,
`_apply_us_core_profile`, `_lab_observation_needs_specimen`,
`_build_companion_specimen`,
`_strip_forbidden_observation_reference_range_extensions`,
`_strip_japanese_display_on_english_only_systems`,
`_populate_observation_identifier_and_last_updated`,
`_populate_jp_medication_dosage_ecs_fields`,
`_populate_condition_ai_mr_ecs_fields`,
`_normalize_jp_observation_category`. New code should import from
the concern module directly.

## Determinism

Not applicable — every pass is a pure transformation over each
emitted resource. `_JP_ECS_LAST_UPDATED_PLACEHOLDER` is a
deterministic constant (`"2026-01-01T00:00:00+09:00"`) so cohort
byte-identity is preserved across runs.

## Dependencies

- `clinosim.modules._shared` — `is_jp`.
- `clinosim.modules.output.fhir_r4.lib.common` —
  `derive_meta_last_updated` (populate); `lib.ids` —
  `derive_opaque_id` / `structural_key_system` (specimen).
- `clinosim.codes` — LOINC / SNOMED / JP-CLINS code display lookup
  and the `codes/data/*.yaml` tables named above.
- `re`, `functools`, `pathlib` — standard library.

## Constants and configuration

- **Datetime normalisation** (`datetime_normalize.py`):
  - `_DATETIME_FIELDS` — frozenset of every FHIR dateTime / date
    field name the walker visits.
  - `_PERIOD_FIELDS = frozenset(("start", "end"))`.
  - `_PERIOD_KEYS` — frozenset of every Period-wrapping field key.
  - `_INSTANT_FIELDS = frozenset(("issued", "lastUpdated"))`.
- **Companion specimen** (`specimen.py`):
  - `_COMPANION_SPECIMEN_ID_PREFIX = "spec-"` (alias
    `SPECIMEN_ID_PREFIX`; `SPECIMEN_KEY_SYSTEM =
    structural_key_system("specimen-key")`).
  - `_SPECIMEN_SNOMED_BLOOD = "119297000"` (Blood specimen / 血液検体)
    and `_SPECIMEN_SNOMED_URINE = "122575003"` (Urine specimen /
    尿検体); displays come from `codes/data/snomed-ct.yaml`.
- **JP-CLINS + MHLW code systems** (`populate.py`, listed in Scope
  above). Every constant is imported by JP-side downstream
  builders + the `document` AD-60 audit for cross-verification.
- **`_JP_ECS_LAST_UPDATED_PLACEHOLDER = "2026-01-01T00:00:00+09:00"`**
  — deterministic anchor used only when a resource has no real
  `meta.lastUpdated` source.

## Directory contents

```
clinosim/modules/output/fhir_r4/post_process/
  __init__.py                       re-export facade (no dispatch; call order lives in ../builder.py::_build_bundle)
  datetime_normalize.py             timezone + Period + instant normalisation (+ fused Practitioner display fill)
  specimen.py                       companion Specimen synthesis (spec- prefix, blood/urine SNOMED)
  profile.py                        JP Core / JP-CLINS / US Core profile URI stacking + resource-type discriminators
  populate.py                       large JP eCS + MHLW + MEDIS + UCUM populate pass (~1,300 LOC)
  strip.py                          strip forbidden referenceRange extensions + Japanese display on English-only systems
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
