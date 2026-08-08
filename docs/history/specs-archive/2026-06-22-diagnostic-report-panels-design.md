# DiagnosticReport panel grouping (CBC / BMP / LFT / Lipid / Coag / UA / ABG)

**Date:** 2026-06-22
**Status:** Approved (design)
**Scope:** FHIR adapter post-hoc grouping of existing lab Observations into
`DiagnosticReport` resources, plus new reference-data file. No CIF schema
change, no observation engine change, no disease/encounter YAML change.

## Problem

`DiagnosticReport.ndjson` currently emits only microbiology reports (33 records
in US p=2000 / `dr-mb-*` ids). Chemistry and hematology lab Observations
(WBC, Hb, Plt, Na, K, Cl, BUN, Creatinine, …) are emitted as **flat scalar
`Observation` resources with no panel grouping**. Real EHRs return labs
grouped by panel (CBC, BMP, CMP, LFT, Lipid panel, Coag, UA, ABG); downstream
analytics, dashboards, and clinical-decision tools rely on the panel grouping
to express "one draw / one report". The simulator's current output forces
consumers to re-derive the grouping by `(patient, encounter, collection_time)`
heuristically.

The chosen fix is **purely additive** at FHIR emit time: existing
`Observation.ndjson` byte-identical to master, `DiagnosticReport.ndjson` grows
to include one DR per panel per draw-time per encounter.

## Why post-hoc grouping (not order-aware, not CIF schema change)

- **Order-aware grouping** would require linking `lab_results` back to the
  panel-named order (e.g. `order_code: "CBC"` → its component results). CIF
  currently has no `order_id` back-link on lab_results, so order-aware
  grouping would either need a CIF schema change (breaks the byte-diff
  invariant and golden e2e) or fragile time-window matching with noise from
  duplicate orders (q4-6h BMP in DKA, repeat CBCs).
- **CIF schema change** (adding `order_id` to `LabResult`) is the highest-
  fidelity option but is out of scope for this PR — it would touch every
  output adapter, the lab generation engine, and require golden file
  regeneration.
- **Post-hoc grouping** at FHIR emit time uses `(panel-component-membership,
  result_datetime rounded to minute)` to bucket Observations; it is purely
  additive (no NDJSON file except `DiagnosticReport.ndjson` changes) and
  matches how a downstream FHIR client would itself re-derive the grouping —
  but emitted authoritatively by the source.

## Design

### 1. Reference data

New file: `clinosim/modules/output/reference_data/lab_panel_groups.yaml`.
Locale-independent (panel composition is international). One entry per panel:

```yaml
# Lab panel groupings for FHIR DiagnosticReport.result[] assembly.
# Authoritative panel codes: LOINC. Components are the *canonical* clinosim
# analyte names (the same names that appear as lab_results.lab_name and as
# the keys in derive_lab_values output).

panels:
  CBC:
    loinc: "58410-2"
    display: "Complete blood count (hemogram) panel - Blood by Automated count"
    components: [WBC, Hb, Hct, Plt]
    min_components: 3   # at least 3 of 4 must be present at the same draw-time

  BMP:
    loinc: "51990-0"
    display: "Basic metabolic 2000 panel - Serum or Plasma"
    components: [Na, K, Cl, HCO3, BUN, Creatinine, Glucose, Ca]
    min_components: 5

  LFT:
    loinc: "24325-3"
    display: "Hepatic function 2000 panel - Serum or Plasma"
    components: [AST, ALT, ALP, T_Bil, Albumin, TP, GGT, LDH]
    min_components: 3

  Lipid:
    loinc: "57698-3"
    display: "Lipid panel with direct LDL - Serum or Plasma"
    components: [TC, LDL, HDL, TG]
    min_components: 3

  Coag:
    loinc: "24373-3"
    display: "Activated partial thromboplastin time (aPTT) and Prothrombin time (PT)/INR panel - Platelet poor plasma"
    components: [PT, PT_INR, APTT]
    min_components: 2

  UA:
    loinc: "24356-8"
    display: "Urinalysis complete panel - Urine"
    components: [Urine_pH, Urine_specific_gravity, Urine_protein, Urine_glucose, Urine_ketones, Urine_blood, Urine_nitrite, Urine_leukocyte_esterase]
    min_components: 3
    skip_if_no_components_present: true   # UA components may not exist in clinosim yet

  ABG:
    loinc: "24338-6"
    display: "Gas panel - Arterial blood"
    components: [pH, pCO2, pO2, HCO3]
    min_components: 3
```

LOINC codes verified via NLM clinicaltables.nlm.nih.gov (Regenstrief is
authoritative). Each LOINC also gets added to `clinosim/codes/data/loinc.yaml`
with at least an `en` field per the project's code-coverage rule.

Notes on panel choices:
- **No CMP**. CMP = BMP ∪ LFT. Emitting all three (CMP, BMP, LFT) for a single
  comprehensive draw would triple-report. If both BMP and LFT thresholds are
  satisfied at the same draw-time, two DRs (BMP + LFT) are emitted — a
  downstream consumer aggregates them if they want CMP semantics.
- **BMP uses 51990-0** ("Basic metabolic 2000 panel - Serum or Plasma"), the
  dedicated LOINC panel code whose component set (Na, K, Cl, CO2, Ca, BUN,
  Cr, Glucose) matches our BMP composition exactly. CMP 24323-8 is not used.
- **Coag uses 24373-3** ("aPTT and PT/INR panel"), the standard LOINC panel
  code covering both PT/INR and APTT. The single-analyte LOINC 34714-6 (INR
  in PPP) is reserved for the standalone Observation, not the panel DR.
- **HCO3 dual membership**. HCO3 is a member of both BMP (serum CO2) and ABG
  (arterial). At grouping time, if an `ABG` panel emits, its HCO3 is consumed
  by the ABG group; the BMP grouping looks for any remaining HCO3 at the same
  draw-time. In practice the analyte names disambiguate (the ABG HCO3 is
  derived from `derive_lab_values` blood-gas section; the BMP HCO3 is the
  metabolic-axis serum bicarbonate — same value mathematically, but emitted
  as part of an ABG draw vs. a BMP draw). Implementation: ABG grouping
  evaluated FIRST; BMP grouping uses only HCO3 observations not already
  consumed by an ABG group.

### 2. Grouping logic

New module: `clinosim/modules/output/_fhir_diagnostic_report.py`. Registered
as a bundle builder via `register_bundle_builder()` (AD-56). Pseudocode:

```python
def build_lab_panel_reports(ctx: BundleBuilderContext) -> list[dict]:
    reports = []
    for encounter in ctx.encounters:
        obs_by_time: dict[str, list[Observation]] = defaultdict(list)
        for obs in ctx.observations_for_encounter(encounter):
            if obs.lab_name not in ALL_PANEL_ANALYTES:
                continue
            bucket = obs.effectiveDateTime[:16]   # minute-resolution
            obs_by_time[bucket].append(obs)

        for bucket, obs_list in sorted(obs_by_time.items()):
            consumed_ids: set[str] = set()
            for panel_name in PANEL_PRIORITY_ORDER:   # ABG > CBC > BMP > LFT > Lipid > Coag > UA
                panel = PANELS[panel_name]
                matched = [o for o in obs_list
                           if o.lab_name in panel.components
                           and o.id not in consumed_ids]
                if len(matched) < panel.min_components:
                    continue
                reports.append(build_dr(encounter, panel, bucket, matched))
                consumed_ids.update(o.id for o in matched)
    return reports
```

Key design points:
- **Bucket key = minute-resolution** (`YYYY-MM-DDTHH:MM`). Real lab analyzers
  draw one tube → run multiple assays; results timestamp the same minute. If
  two CBCs are drawn at 06:00 and 06:01, they end up in separate buckets and
  emit separate DRs — correct.
- **Greedy priority order** (`ABG > CBC > BMP > LFT > Lipid > Coag > UA`)
  resolves HCO3 dual membership and other ambiguities deterministically. An
  Observation consumed by a higher-priority panel is excluded from
  lower-priority panel matching at the same bucket.
- **Min threshold per panel** prevents spurious DR emission when only one
  analyte was ordered standalone (e.g. a stat Cr is not a "BMP" — it stays
  a solo Observation).
- **Solo Observations stay solo.** CRP, BNP, Troponin_I, CK_MB, HbA1c,
  Lactate, eGFR, PCT, etc. have no panel membership and continue to emit as
  standalone Observations with no DR wrapper.
- **No CIF read.** All grouping uses already-built FHIR Observation
  resources (the builder receives them via `ctx`). This isolates the
  grouping logic from CIF schema details.

### 3. FHIR DiagnosticReport shape

```json
{
  "resourceType": "DiagnosticReport",
  "id": "dr-cbc-ENC-POP-000002-000756-0",
  "status": "final",
  "category": [{"coding": [{"system": "http://terminology.hl7.org/CodeSystem/v2-0074", "code": "LAB", "display": "Laboratory"}]}],
  "code": {"coding": [{"system": "http://loinc.org", "code": "58410-2", "display": "Complete blood count (hemogram) panel - Blood by Automated count"}]},
  "subject": {"reference": "Patient/POP-000002"},
  "encounter": {"reference": "Encounter/ENC-POP-000002-000756"},
  "effectiveDateTime": "2026-05-12T14:28:00",
  "issued": "2026-05-12T14:28:38.618256",
  "performer": [{"reference": "Practitioner/TECH-LAB-001"}],
  "result": [
    {"reference": "Observation/lab-ENC-POP-000002-000756-WBC-0"},
    {"reference": "Observation/lab-ENC-POP-000002-000756-Hb-0"},
    {"reference": "Observation/lab-ENC-POP-000002-000756-Hct-0"},
    {"reference": "Observation/lab-ENC-POP-000002-000756-Plt-0"}
  ]
}
```

- `id` format: `dr-{panel-name-lowercased}-{encounter-id}-{seq}` where `seq`
  resets per (encounter, panel) and increments for each bucket emitting that
  panel. Globally unique within `DiagnosticReport.ndjson`.
- `status: final` (consistent with the existing microbiology DR emission).
- `category.code: LAB` (v2-0074 service category).
- `code` is the panel LOINC from the YAML; `display` is the YAML's display
  field. Single coding entry (the panel is internationally-named in LOINC).
- `subject` / `encounter` / `performer` mirror the Observation references.
  `performer` derives from the first matched Observation's `performer`
  (typically the tech, e.g. `TECH-LAB-001`).
- `effectiveDateTime` = bucket time (minute-resolution, no seconds).
- `issued` = max(`issued`) across matched Observations (latest assay
  completed defines when the report became available).
- `result[]` = `Observation/{id}` references, ordered by panel YAML's
  components list (for stable output between runs).

### 4. Invariants and byte-diff gate

| File | Before | After |
|---|---|---|
| `Patient.ndjson` | byte-identical | byte-identical |
| `Encounter.ndjson` | byte-identical | byte-identical |
| `Observation.ndjson` | byte-identical | **byte-identical** |
| `Condition.ndjson` | byte-identical | byte-identical |
| `Procedure.ndjson` | byte-identical | byte-identical |
| `MedicationRequest.ndjson` | byte-identical | byte-identical |
| `MedicationAdministration.ndjson` | byte-identical | byte-identical |
| `Immunization.ndjson` | byte-identical | byte-identical |
| `AllergyIntolerance.ndjson` | byte-identical | byte-identical |
| `FamilyMemberHistory.ndjson` | byte-identical | byte-identical |
| `Specimen.ndjson` | byte-identical | byte-identical |
| `Coverage.ndjson` (JP) | byte-identical | byte-identical |
| Location / Organization / Practitioner / PractitionerRole | byte-identical | byte-identical |
| `DiagnosticReport.ndjson` | 33 records (mb only, US p=2000) | **microbiology subset byte-identical** + N new lab-panel records |

The "microbiology subset byte-identical" sub-invariant matters: the new
emitter must NOT reorder, restructure, or modify the existing microbiology DR
records. The recommended implementation is to emit lab-panel DRs as a
SEPARATE list appended AFTER the existing microbiology DR list (preserving
record order in the NDJSON stream).

### 5. Determinism (AD-16)

No new RNG draws. The grouping is a pure function of the already-emitted
Observation set. Same seed → same Observations → same DR groups → byte-
identical `DiagnosticReport.ndjson` across runs.

## Verification

### Unit tests

- `tests/unit/test_diagnostic_report_panels.py` (new):
  - YAML loads; each panel has loinc + components + min_components fields.
  - Each panel LOINC resolves to a non-empty `en` display via
    `clinosim.codes.lookup("loinc", code, "en")`.
  - Grouping: a hand-built Observation list at the same minute with WBC + Hb
    + Plt → 1 CBC DR with 3 result references. With only WBC + Hb → 0 DRs
    (below min threshold of 3).
  - Time bucketing: WBC at 06:00:01 + Hb at 06:00:59 → same bucket
    (06:00); WBC at 06:00:01 + Hb at 06:01:00 → separate buckets.
  - Priority: same bucket with HCO3 + pH + pCO2 + Na + K + Cl + BUN + Cr +
    Glucose + Ca → 1 ABG DR (HCO3, pH, pCO2) and 1 BMP DR (Na, K, Cl, BUN,
    Cr, Glucose, Ca — but NOT HCO3, consumed by ABG).
  - Solo lab pass-through: CRP, BNP, Troponin_I, HbA1c never appear in
    DR.result[].
  - Reference integrity: every `result[].reference` resolves to an emitted
    Observation id (asserted against a captured Observation id set).

### Byte-diff invariant (US p=2000 / JP p=2000, seed 42)

Same gate as PR #69:
- Every NDJSON except `DiagnosticReport.ndjson` byte-identical to master.
- `DiagnosticReport.ndjson`: the existing microbiology DR records appear in
  byte-identical form; additional lab-panel DR records are appended.

If any non-DR NDJSON differs, STOP — the implementation leaked state.

### Audit (US p=8000, JP p=4000)

Sample observed DR counts and panel coverage to confirm the grouping picks up
the major panels:

- Expected: CBC DR count >> 0 (most encounters with workup get CBC).
- Expected: ABG DR count = positive (encounters with `disease.acid_base_type
  != none`, COPD/pneumonia/asthma/DKA cohorts).
- Expected: Coag DR count > 0 (pre-op encounters, DVT/PE / anticoag patients).
- Expected: UA DR count = 0 unless / until urinalysis analytes are added to
  the simulator. The `skip_if_no_components_present: true` flag in the YAML
  prevents spurious empty-panel reports.

## Out of scope

- **Order → result back-linking**. A future CIF schema change could attach
  `order_id` to `LabResult`, replacing post-hoc time-bucket inference with an
  exact order-grouped emission. Out of scope here.
- **DR `basedOn` → ServiceRequest reference**. Real EHRs link DR back to the
  order (`ServiceRequest`). clinosim does not emit `ServiceRequest` for labs
  (orders live in CIF, not in the FHIR export); no `basedOn` is emitted.
- **CMP panel emission**. See §1 design note.
- **Microbiology DR refactor**. The existing `dr-mb-*` emission stays
  untouched; only chemistry/hematology panels are added.
- **Trended / serial-draw aggregation** (e.g. trending CBC over 5 days as a
  single DR). Each draw-time emits its own DR.

## Authoritative sources

- LOINC panel codes verified at <https://clinicaltables.nlm.nih.gov/api/loinc_items/v3/search?terms=24323-8>
  (NLM Regenstrief; primary source for LOINC).
- Panel component composition follows the Regenstrief LOINC panel hierarchy
  for each code.
- FHIR R4 `DiagnosticReport` shape per <https://hl7.org/fhir/R4/diagnosticreport.html>.
- FHIR R4 `DiagnosticReport.category` value set
  <http://terminology.hl7.org/CodeSystem/v2-0074>.
