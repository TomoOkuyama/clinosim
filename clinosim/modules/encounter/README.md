# `clinosim.modules.encounter` — encounter condition protocols + daily-cycle timeline

## Purpose

Owns two related concerns for inpatient / ED / outpatient encounters:

1. The **encounter-condition protocol registry** — 52 YAMLs under
   [`reference_data/`](reference_data/) covering short outpatient and
   ED conditions (asthma attack, migraine, minor laceration,
   screening visits, allergic reaction, syncope, viral gastroenteritis,
   annual health screening, dialysis session, rehab outpatient, …).
   This is the sibling registry to
   [`clinosim.modules.disease`](../disease/README.md), which owns the
   heavier admission / trauma protocols.
2. The **inpatient daily-cycle timeline** — deterministic
   admission → daily cycle → discharge event ordering for a
   single inpatient encounter, plus the deterministic hash-based
   encounter-id suffix that keeps encounter ids stable across
   cursor / snapshot boundaries.

## Scope

- **In scope**: `EncounterConditionProtocol` Pydantic schema + child
  models (`OutpatientSoapTemplate`, `EdNoteTemplate`, `EdPhysicalExam`,
  `EdTriageTemplate`, `EncounterNarrativeSpec`, `SymptomOnset`,
  `ScreeningSchedule`, `ScreeningLab`, `VisitProcedure`, and the typed
  workup / treatment / prescription / scenario sections); per-protocol
  loader + full-registry loader (both `@lru_cache`);
  `screening_schedule` and `protocol_min_age` /
  `AGE_DISTRIBUTION_MIN_AGE`;
  `create_inpatient_encounter` with the F1 cross-cursor stable id
  formula; `generate_daily_cycle` (per-day event skeleton at the
  Japan medium-hospital cadence — morning vitals 06:00, morning labs
  06:30, rounds 09:00, afternoon vitals 14:00, evening vitals
  18:00, evening meds 18:30, night check 22:00); and
  `generate_encounter_timeline` (admission + daily × N + discharge,
  chronologically sorted).
- **Out of scope**: inpatient / trauma / occupational-injury
  protocols ([`clinosim.modules.disease`](../disease/README.md));
  narrative rendering
  ([`clinosim.modules.document.narrative`](../document/narrative/README.md));
  encounter simulation / stateful daily loop
  ([`clinosim.simulator`](../../simulator/)); FHIR `Encounter`
  emission ([`clinosim.modules.output`](../output/README.md)).

### Longitudinal service-line encounter shapes (v0.5 → v0.6.0)

The 52 YAML protocols above cover ED / outpatient chief-complaint
episodes. The two longitudinal service lines below emit inpatient /
outpatient encounter shapes that are NOT tied to a `reference_data/`
protocol — the shape lives directly in
[`clinosim/locale/shared/perinatal.yaml`](../../locale/shared/perinatal.yaml)
and
[`clinosim/locale/shared/chronic_followup.yaml`](../../locale/shared/chronic_followup.yaml):

- **Perinatal delivery Encounter** (mother-side, IMP admission,
  admit dx `O80`, discharge dx `Z37.0`, LOS 5 days JP / 2 days US,
  department `obstetrics_gynecology`, rolled up via `department_rollup`
  (`primary_care` in the bundled hospitals), delivery Procedure US CPT `59400`; JP has no K-code, 正常分娩 being uninsured).
- **Newborn Encounter** (IMP admission, `admit_source = "born"` — the
  `AdmitSource.BORN` value from
  [`clinosim/codes/hl7_encounter.py`](../../codes/hl7_encounter.py), stored in the
  `str`-typed `Encounter.admit_source` of
  [`clinosim/types/encounter.py`](../../types/encounter.py),
  `admit_source_encounter_id` → mother's delivery encounter →
  FHIR `Encounter.partOf` on newborn side; LOS inherited from mother;
  discharge dx `Z38.0`).
- **Postpartum outpatient encounters × 2** — `chronic_visit` events
  at ~1 wk and ~4 wk post-delivery, disease_id `Z39`, entry lives in
  `chronic_followup.yaml`.
- **Abortion outpatient day-surgery Encounter** (O03.9 spontaneous
  / O04.5 induced, age-gated 15–19 → 35–44), config in
  `perinatal.yaml::abortion`. When the abortion outcome fires no
  delivery / newborn chain is emitted.
- **Chemotherapy visit Encounter** (`chemo_visit` outpatient
  event) — one per regimen cycle, cadence from
  [`clinosim/locale/shared/chemo_regimens.yaml`](../../locale/shared/chemo_regimens.yaml).
  Encounter carries the delivery / chemo Procedure and (via
  [`order`](../order/README.md)) per-cycle MedicationRequest +
  MedicationAdministration for each Day-1 drug in the regimen's
  `cycle_orders`. Radiation therapy encounters analogous.

## Public API

`__init__.py` is empty; consumers import directly from the two
submodules:

```python
from clinosim.modules.encounter.engine import (
    DailyCycleEvent,                 # dataclass (timestamp, event_type, data)
    create_inpatient_encounter,      # (patient_id, admission_datetime, chief_complaint="…", department_id="internal_medicine", visit_number=1) -> Encounter
    generate_daily_cycle,            # (encounter, day_number) -> list[DailyCycleEvent]
    generate_encounter_timeline,     # (encounter, total_days) -> list[DailyCycleEvent]
)

from clinosim.modules.encounter.protocol import (
    EncounterConditionProtocol,      # Pydantic BaseModel
    EncounterNarrativeSpec,          # narrative wrapper (α-min-2 Task 6)
    OutpatientSoapTemplate,          # SOAP note fields
    EdNoteTemplate,                  # ED physician note fields
    EdPhysicalExam,                  # ED physical exam sub-model
    EdTriageTemplate,                # ED triage sub-model
    load_encounter_condition,        # (condition_id) -> dict  (@lru_cache=64)
    load_all_encounter_conditions,   # () -> dict[condition_id, dict]  (@lru_cache=1)
    SymptomOnset,                    # symptom onset (unit + range)
    DEFAULT_SYMPTOM_ONSET,           # default onset (days, 1-3)
    ScreeningSchedule,               # screening interval / eligible age / uptake
    ScreeningLab,                    # tests added by age / sex / BMI
    VisitProcedure,                  # per-visit procedure (code / SNOMED / name / duration)
    AGE_DISTRIBUTION_MIN_AGE,        # age_distribution → youngest age
    protocol_min_age,                # (spec) -> int | None  (min_age, else the age_distribution floor)
    screening_schedule,              # (condition_id) -> ScreeningSchedule  (a screening protocol's schedule (ValueError if none))
    discharge_instructions_for_age,  # (protocol, age_months) -> instructions; an age-gated item yields its `younger` variant below `min_age_months` (no honey under 12 months)
)
from clinosim.modules.encounter.discharge_outcome import discharge_outcome
# (encounter, *, deceased) -> outcome key of a finished inpatient stay
# (improved / remission / unchanged / worsened / death_from_condition /
# death_other / other), the DPC 退院時転帰, derived from the course by the
# ordered rules of locale/shared/discharge_outcomes.yaml (Issue #3150).
# Each country codes it through locale/<cc>/code_mapping_discharge_disposition.yaml.
```

## Determinism

- **Encounter IDs are hash-derived, not counter-derived** (F1 fix).
  `_encounter_id_suffix(patient_id, admission_datetime, chief_complaint,
  department_id, visit_number)` folds all five inputs into a SHA-256
  digest, takes the first 6 bytes, and mods by
  `_ENCOUNTER_SUFFIX_MODULUS = 10**12` (12 decimal digits). This is
  cursor-independent: two runs differing only in `snapshot_date`
  produce the same id for the same encounter, regardless of how many
  unrelated encounters were processed upstream. The 12-digit width
  was chosen after the earlier 6-digit width was empirically
  observed to collide within a single patient at p=500.
- Daily-cycle + timeline generation is pure: no `rng` argument, and
  the cadence hours (06:00 / 06:30 / 09:00 / 14:00 / 18:00 / 18:30 /
  22:00) are fixed.
- Protocol loaders are pure. `EncounterConditionProtocol` requires
  `condition_id`, `chief_complaint`, `encounter_type`, `department` and
  exactly one of `icd10_code` and `diagnosis_variants` (weighted
  per-country codes for a diagnosis that varies per visit, Issue #3279), declares every optional section (workup, treatment,
  discharge prescriptions, narrative, ...) as a typed field, and rejects
  unknown keys (`extra="forbid"`). Every `route:` value is also checked against the shared
  route vocabulary at load time.

## Dependencies

- `pydantic` — schema (`extra="forbid"`).
- `yaml` — YAML parser.
- `clinosim.types.encounter` — `Encounter`, `EncounterStatus`,
  `EncounterType`.
- `hashlib.sha256` — encounter-id derivation.
- `clinosim.modules.output.fhir_r4.lib.reference_data.validate_yaml_route_value`
  — lazy import in the loaders for the `route:` vocabulary check.
- `clinosim.modules.observation.engine` — `canonical_lab_name`,
  `lab_panel_components` (lazy; `ScreeningLab` test-name validation).
- `clinosim.codes.code_exists` (lazy; `VisitProcedure` code
  validation), `clinosim.locale.loader.load_code_mapping` (lazy),
  `clinosim.age_bands.parse_closed_age_band` (lazy),
  `clinosim.datafiles.load_data_yaml`.

## Constants and configuration

- **Encounter-condition YAML registry**: [`reference_data/`](reference_data/)
  — 52 files (one per condition id; filename = condition_id +
  `.yaml`). Covers outpatient chronic follow-up, ED short-stay,
  screening (mammography / colonoscopy / diabetic retinopathy /
  annual health screening), rehab, dialysis, cardiac rehab,
  smoking-cessation, and mental-health follow-up condition classes.
  Each entry carries chief-complaint, physical-exam templates,
  narrative sections (SOAP / ED-note / triage), and clinical
  metadata.
- **Per-birth neonatal ED condition** (Issue #3063): `neonatal_fever.yaml`
  is not drawn from the ED visit mix (`probability: 0`). Each infant
  presents at most once, with probability `incidence_per_1000_births`
  (US 4.56; JP none, no source), on a day of life in `min_age_days`-
  `max_age_days`, hashed from the person id
  (`phases/_ed_slot.py::neonatal_ed_onsets`). An infant within that period
  gets no other ED condition (`neonate_excluded`). The visit performs the
  serious-bacterial-infection workup, `procedures_by_age_days` (lumbar
  puncture at 8-21 days), the first weight-based antibiotic doses, and the
  `transfer_pediatric` disposition (HL7 `other-hcf`); a hospital with a
  pediatric inpatient ward gets no such ED visits
  (`admitted_with_inpatient_unit`).
- **ED note content** (Issues #3244, #3251): `ed_note_template.physical_exam` is a per-system, problem-focused exam (`general`, `heent`, `cardiovascular`, `respiratory`, `abdominal`, `skin`, `musculoskeletal`, `neurological`, `psychiatric`); the note renders the arrival vitals (with the pain score) before it in every locale, and the triage note states them. A template states findings, never instructions ("reviewed", "を確認。"). Findings that differ by visit (burn site and mechanism, ankle side) are `ed_note_template.variants`: parallel language lists, referenced as `{<name>_<lang>}`, the entry picked by a hash of the encounter id so the HPI and the exam agree (names sharing a `group__` prefix pick the same index). A group listed in `ed_note_template.variants_by_diagnosis` is keyed to the protocol's `diagnosis_variants` instead: entry i of each of its lists belongs to diagnosis variant i (list lengths are validated at load), and the visit states the entry of the variant its diagnosis code was drawn from (a burn's site agrees with the coded site; where the code does not tell variants apart, such as a JP burn code without a side, the per-encounter hash picks among the matching ones; with no recorded diagnosis the plain per-encounter draw applies). Every placeholder of an HPI or exam text must resolve (guard test `test_ed_note_content_3244.py`). The note's workup lists labs with their values, imaging with the impression of its report (one entry per study name) and the disposition lists the take-home prescription (drug, dose, frequency and number of days; the narrative context carries `rx_frequency` / `rx_duration_days`), and the triage details and triage note state the allergies.
- **Take-home prescription dose** (Issue #3594): every `discharge_prescriptions[]` entry states the amount per administration, as a `dose` (a quantity such as `10mL`, `2 puffs`, `0.3mg`, or the strength written in the drug name) or, for drops and creams, as a sig text (`1 drop in the affected eye`). `locale_dose` overrides it per country (like `locale_name`), and `min_age_years` withholds a product below its labelled age. The protocol model rejects an entry that resolves to neither in any country (`prescription_dose`), the MedicationRequest carries `doseAndRate.doseQuantity` for a quantity and `dosageInstruction.text` (localized, via the `dose_phrases` table for a sig) for both; guard test `test_ed_take_home_rx_dose_3594.py`.
- **ED imaging country and abnormal rate** (Issue #3294): a `workup.imaging` entry with `countries` is ordered only in those countries (`protocol.py::study_in_country`, applied after the draws so the visit stream is unchanged). Its `abnormal_rate_by_severity` rides on the order to the imaging enricher, which reads the study with the report templates of the visit's condition when `impression_templates.yaml` has them (wrist fracture and shoulder dislocation do: the film shows the visit diagnosis); Sourced rates: migraine head CT 3.7% (intracranial pathology, Serinken et al., West J Emerg Med 2026), older-adult fall head CT 4.4% (significant acute traumatic haemorrhage, Dubucs et al., PLOS Med 2026), ankle film 10.9% (fracture, Schiper et al., Acta Ortop Bras 2023) and renal-colic CT 64% (stone, Alnazari et al., Urol Ann 2024); each is cited beside the entry. other conditions keep the generic negative report.
- **ED imaging red flags** (Issue #3238): a `workup.imaging` entry may list
  `required_if` red flags; one met orders the study even when its
  `probability` draw skips it (`protocol.py::imaging_red_flag`, read by the
  ED visit). Within one red flag every criterion must hold: `min_age`,
  `conditions` / `without_conditions` (value-set groups of
  `codes/data/valuesets.yaml`) and `medication_classes` (drug-catalog
  classes of a home medication); groups and classes are checked at load.
  Migraine orders head CT for onset after 50 without a known primary
  headache disorder, immunocompromise or cancer (ACR Appropriateness
  Criteria Headache, variant 7); concussion and the older-adult fall order it
  for a patient on an anticoagulant (NICE NG232 1.5.13). The forced order's
  time is a stream-free draw, so no other draw of the visit moves.
- **Encounter-id shape** (`engine.py`):
  - `_ENCOUNTER_SUFFIX_MODULUS = 10**12` — 12-digit suffix modulus.
  - Encounter id format: `ENC-{patient_id}-{suffix:012d}`.
  - Episode id format: `EP-{patient_id}-{suffix:012d}`.
  - Disease-event id format: `DE-{patient_id}-001`.
- **Daily cycle cadence** (`generate_daily_cycle`, hard-coded):
  06:00 morning vitals · 06:30 morning labs · 09:00 rounds ·
  14:00 afternoon vitals · 18:00 evening vitals ·
  18:30 evening meds · 22:00 night check. Applies to
  "Japan, medium hospital"; other cadences would be a per-country
  extension.

## Directory contents

```
clinosim/modules/encounter/
  __init__.py                     empty
  engine.py                       inpatient encounter creation + daily-cycle timeline
  protocol.py                     EncounterConditionProtocol + child models + loaders
  discharge_outcome.py            discharge_outcome — the DPC discharge outcome of a finished stay (rules of locale/shared/discharge_outcomes.yaml, Issue #3150)
  reference_data/
    <condition_id>.yaml           52 files (one per outpatient / ED / screening condition)
  SPEC.md                         extended design reference (not runtime)
```

The module has **no `enricher.py`, no `audit.py`**.

## Enricher wiring

Not applicable — this module is a data + primitives layer, not an
enricher. It is not registered with `register_builtin_enrichers` and
has no seed offset in `ENRICHER_SEED_OFFSETS`. The simulator imports
what it needs directly.

## Output surfaces (consumers)

| Consumer | Where | Role |
|---|---|---|
| Simulator boot + all encounter simulators | [`clinosim/simulator/{inpatient,outpatient,emergency,perinatal,unknown_condition,enumerate,cli_test_encounter,cli}.py`](../../simulator/), [`clinosim/simulator/phases/_ed_slot.py`](../../simulator/phases/_ed_slot.py) | Import `create_inpatient_encounter` + the condition-protocol loaders. |
| Triage | [`clinosim/modules/triage/engine.py`](../triage/engine.py) | Reads `load_all_encounter_conditions`. |
| Narrative | [`clinosim/modules/document/narrative/passes.py`](../document/narrative/passes.py) | Reads `EncounterConditionProtocol.narrative` for the outpatient / ED template flow. |
| Encounter-type FHIR mapping | [`clinosim/modules/output/fhir_r4/encounters/`](../output/fhir_r4/encounters/) | Consumes the encounter class + type strings the protocol carries. |

## Testing

```bash
pytest tests/unit -k encounter -q
```

Individual files:

- [`tests/unit/test_encounter_protocol_validation.py`](../../../tests/unit/test_encounter_protocol_validation.py)
  — Pydantic schema validation across all 52 YAMLs (required fields, unknown keys rejected).
- [`tests/unit/test_encounter_archetype_severity.py`](../../../tests/unit/test_encounter_archetype_severity.py)
  — archetype × severity coverage.
- [`tests/unit/test_encounter_features.py`](../../../tests/unit/test_encounter_features.py)
  — expected feature keys per condition.
- [`tests/unit/test_cli_test_encounter_format.py`](../../../tests/unit/test_cli_test_encounter_format.py)
  — CLI encounter-id format guard (F1 stability).
- [`tests/unit/output/test_fhir_encounter_*`](../../../tests/unit/output/)
  — FHIR-side integration guards (encounter reason code JP, ED
  delegation, type codes YAML).
- [`tests/unit/modules/encounter/`](../../../tests/unit/modules/encounter/)
  — module-scoped unit tests.

## Ownership

`maintainers@` — see [`CONTRIBUTING.md`](../../../CONTRIBUTING.md).

Japanese counterpart: [`README.ja.md`](README.ja.md).
