# `clinosim.modules.drug_safety`

Class-based contraindication gate + alternative-drug substitution.

## 1. Purpose

Prevents contraindicated medication co-prescriptions from appearing in
generated CIF/FHIR records, matching how a real EHR CPOE
(Computerized Physician Order Entry) system suppresses them at
order-entry time. Where the pre-fix cohort emits ~150 contraindicated
pairs per 10 000 US patients (warfarin+aspirin, warfarin+NSAID,
β-blocker + non-DHP CCB, ACEi/ARB + K supplement), the gate reduces
that count to zero via a class-based rule engine invoked from the
simulator's order-entry paths (admission / daily-loop / ED / discharge
Rx / prophylaxis) and the `patient` activator. Three companion gates
cover drug-vs-disease-state (`check_candidate_against_disease_state`),
drug-vs-age/sex (`check_demographic_gate`) and drug-vs-recorded-allergy
(`check_candidate_against_allergies`, Issue #2924) contraindications.

## 2. Scope

**In scope**:
- Rule engine: class × class contraindication lookup with severity-graded
  verdicts (allowed / minor / moderate / major / contraindicated).
- Drug-class × chronic-disease-state rules (`disease_contraindications.yaml`,
  Issue #1392 / #1350, staged `stage_in` predicate Issue #1769).
- Demographic (age / sex) gate (`demographic_gates.yaml`, Issues
  #1316 / #1328) with ICD-prefix `exception_indications` bypass.
- Drug-class × recorded-allergy rules (`allergy_contraindications.yaml`,
  Issue #2924): each medication allergen of
  `modules/allergy/reference_data/allergens.yaml` maps to the classes it
  rules out (block) or flags (caution), with cross-reactivity per current
  evidence.
- Inpatient hyperkalemia response (`hyperkalemia.py`,
  `hyperkalemia_response.yaml`, Issue #2981): a resulted potassium
  >= 6.0 mmol/L holds every ACE inhibitor, ARB and potassium-sparing
  diuretic dose scheduled from that result to discharge (MAR status
  `held`, reason `K <value> mmol/L`, shown as `Held: ...` / `休薬: ...` in
  the progress-note plan) and places the country's treatment order set
  (calcium gluconate, regular insulin with 50% dextrose, a potassium
  binder) as one-time doses on the first day a result reaches the
  threshold; while it stays there on consecutive days only the binder is
  ordered again.
  Called by the inpatient daily loop; no RNG.
- Alternative substitution: revives Issue #437 dead-data `alternative_*`
  blocks in disease YAML + new `modules/drug_safety/reference_data/drug_substitution.yaml`
  generic pool.
- CIF trace via `PatientProfile.safety_skip_log` (per-patient list of
  `SafetySkipEntry` records).
- Narrative surfacing (all 4 layers): NarrativeContext + template
  fallback + production LLM prompt + reserved-prompt sync notes.
- MedicationRequest.note passthrough for moderate DDI cautions.
- AD-60-style audit function (post-hoc missed-gate detector,
  stand-alone; not registered with the audit registry).

**Out of scope (post-MVP)**:
- `DetectedIssue` FHIR resource emission (real CPOE has no chart trace
  for blocked orders; DetectedIssue is a pharmacist-review artifact).
- `allow_if_indication` whitelist (post-PCI+AF, mechanical valve
  exceptions).
- `antibiotic` module integration (narrow-ladder path).
- Chronic-med substitution (activator emits skip-only).
- LLM production evaluation (H100 clinician-eye review).

## 3. Public API

```python
from clinosim.modules import drug_safety

# Pair check — order-independent, RNG-neutral
verdict = drug_safety.check_pair("Warfarin", "Aspirin")
# → SafetyVerdict(severity="contraindicated", rule_id="vka-plus-antiplatelet", ...)

# Multi-active check — used by caller loops
verdicts = drug_safety.check_candidate_against_active(
    "Ibuprofen", ["Warfarin", "Amlodipine"],
)  # → [SafetyVerdict(...)] (one per non-allowed pair)

# Alternative pick — disease_ctx first, shared pool second
alt = drug_safety.suggest_alternative(
    "Ibuprofen", "pain_management",
    active_meds=["Warfarin"], disease_ctx=protocol, country="us",
    allergen_codes=codes,  # an alternative the patient is allergic to is skipped
)  # → AlternativeDrug(drug="Acetaminophen", ...)

# Drug-vs-chronic-disease-state — entries are ICD strings or (code, stage) tuples
verdicts = drug_safety.check_candidate_against_disease_state(
    "Ibuprofen", ["I50.9"],
)  # → [SafetyVerdict(rule_id="nsaid-in-heart-failure", ...)]

# Drug-vs-recorded-allergy — entries are the allergen codes of the
# patient's active allergy records (NKA, resolved and refuted left out)
codes = drug_safety.allergy_entries(patient.allergies)   # → ["764146007"]
verdicts = drug_safety.check_candidate_against_allergies("Amoxicillin", codes)
# → [SafetyVerdict(rule_id="penicillin-allergy-penicillins", severity="contraindicated", ...)]
drug_safety.allergy_skip_verdict("Ibuprofen", patient.allergies)  # blocking verdict or None
drug_safety.conflict_display(verdict)  # → ("Penicillin allergy", "ペニシリンアレルギー")

# Demographic (age / sex) gate
dv = drug_safety.check_demographic_gate(
    "Aspirin 325mg", patient_age=8, patient_sex="M", indication_codes=None,
)  # → DemographicVerdict(severity="contraindicated", rule_id="aspirin-pediatric-reyes", ...)

# Rule ids the discharge prescription reconciles (contraindications.yaml)
drug_safety.discharge_reconciliation_rules()  # → frozenset[str]

# Utility
drug_safety.resolve_classes("warfarin")   # → ["anticoagulant.vka", "anticoagulant"]
drug_safety.canonical_name("ワルファリン")  # → "Warfarin"
drug_safety.japanese_display("Aspirin")   # → "アスピリン"
```

The full `__all__`: functions `check_pair`,
`check_candidate_against_active`,
`check_candidate_against_disease_state`, `check_demographic_gate`,
`check_candidate_against_allergies`, `allergy_entries`,
`allergy_skip_verdict`, `conflict_display`, `condition_entries`,
`suggest_alternative`, `discharge_reconciliation_rules`,
`resolve_classes`, `canonical_name`, `japanese_display`,
`rule_kind` (allergy / disease / interaction kind of a verdict's
`rule_id`); types
`SafetyVerdict`, `SafetySkipEntry`, `Severity`, `SEVERITY_RANK`
(re-exported from `clinosim.types.drug_safety` via `verdict.py`),
`AlternativeDrug` (`engine.py`) and `DemographicVerdict`
(`demographic.py`).

## 4. Determinism

- **Verdicts are pure YAML lookups** — no RNG consumption, no
  transcendental math, no libm calls.
- **Substitution picks the first conflict-free alternative in YAML
  order** — deterministic across seeds. Reorder the YAML to change
  substitution selection.
- **RNG shape shift**: a skipped candidate does not consume the RNG
  its normal MR emit would have; a substitute emits at a different
  site. This is a documented cohort-scale change (RNG streams of the
  affected patients shift). Version bump = MINOR.
- **Cross-platform bit-reproducibility**: safe under the
  `_DeterministicRngProxy` regime — only dict lookups + string
  comparisons.

## 5. Dependencies

- `clinosim.codes.drugs` — drug catalog (`drug_classes`,
  `drug_display`, `identify_drug`, `resolve_drug`; `_models.py` also
  checks classes / drug ids against `all_drug_ids` / `get_drug`).
- `clinosim.datafiles` — `load_validated_yaml` (every reference YAML is
  loaded through a Pydantic model in `_models.py`).
- `clinosim.locale.localized` — `language_slot`.
- `clinosim.types.drug_safety` — `SafetyVerdict`, `SafetySkipEntry`,
  `Severity`, `SEVERITY_RANK`, `EventType` (re-exported by
  `verdict.py`).
- `clinosim.modules.disease.protocol` (lazy import for
  `alternatives_by_indication` — only when disease_ctx is passed).
- Third-party: `pydantic` (YAML schema validation).
- **No other cross-clinosim runtime deps.**

## 6. Constants and configuration

Six YAML files plus the drug catalog:

- Drug classes and aliases: the drug catalog
  (`clinosim/codes/data/drugs.yaml`, read through `clinosim.codes.drugs`).
- `reference_data/contraindications.yaml` — class × class rules
  (18 rules: VKA+antiplatelet, DOAC+P2Y12, anticoagulant+NSAID,
  BB+non-DHP CCB, P2Y12+P2Y12, statin+statin, DOAC+VKA, ACEi+ARB,
  ACEi/ARB+K, ACEi/ARB+K-sparing, statin+strong CYP3A4 inhibitor,
  allopurinol+thiopurine, SSRI+MAOI, SSRI+SNRI, NSAID stacking,
  lithium+diuretic, lithium+ACEi/ARB, lithium+NSAID), plus the
  `discharge_reconciliation_rules` list and the
  `triple_therapy_after_acs` antithrombotic plan.
- `reference_data/disease_contraindications.yaml` — drug class ×
  chronic-disease rules (7 rules: NSAID in heart failure / cirrhosis /
  CKD stage 4-5 by ICD prefix / CKD stage 4-5 by stage, metformin in
  CKD stage 3b-5, sulfonamide and nitrofurantoin in G6PD deficiency).
  Applied when chronic medications are sampled and, since Issue #2855,
  on every new order (`apply_drug_safety_gate_to_orders`) and every ED
  order or take-home prescription.
- `reference_data/demographic_gates.yaml` — age / sex rules (3 rules:
  aspirin pediatric (Reye's), nitroglycerin adult-only, tamsulosin
  adult male).
- `reference_data/allergy_contraindications.yaml` — drug class ×
  recorded-allergy rules (7 rules, Issue #2924). Penicillin allergy
  blocks every penicillin (aminopenicillins included) and only cautions
  cephalosporins; carbapenems carry no rule (AAAAI/ACAAI drug allergy
  practice parameter 2022). Aspirin allergy blocks non-selective and
  preferential COX-2 NSAIDs (substitute: `pain_management`) and aspirin
  itself (no analgesic substitute), and cautions selective COX-2
  inhibitors (EAACI/ENDA NSAID hypersensitivity classification).
  Sulfonamide allergy blocks sulfonamide antibiotics and only cautions
  thiazide / loop diuretics and celecoxib (Strom, NEJM 2003).
- `modules/drug_safety/reference_data/drug_substitution.yaml` — generic indication →
  alternative pool keyed by catalog `drug_id` (pain_management →
  acetaminophen; hypertension_or_rate_control → amlodipine /
  candesartan).
- `reference_data/hyperkalemia_response.yaml` — the potassium treatment
  threshold (6.0 mmol/L; KDIGO 2024 CKD, 2022 AHA/ACC/HFSA heart failure
  and UK Kidney Association 2020 acute hyperkalaemia guidelines), the
  held classes (`acei`, `arb`, `diuretic.k_sparing`) and the US / JP
  treatment order sets (Issue #2981). The order-timing offset lives in
  `_hyperkalemia_thresholds.py`.

Each file is validated at load by an `extra="forbid"` Pydantic model
in `_models.py` (`ContraindicationsFile`,
`DiseaseContraindicationsFile`, `DemographicGatesFile`,
`DrugSubstitutionFile`, `AllergyContraindicationsFile`,
`HyperkalemiaResponseFile`); drug classes /
drug ids are checked against the catalog, rule ids must be unique, the
reconciliation list must name existing rules, and an allergy rule's
`allergen_code` must be a medication allergen of `allergens.yaml`.

Also lifts the Issue #437 dead-data `alternative_*` blocks in 15
disease YAMLs via `_indication_tag` markers.

## 7. Directory contents

```
clinosim/modules/drug_safety/
├── __init__.py            # public API re-export
├── verdict.py             # SafetyVerdict + SafetySkipEntry + Severity + SEVERITY_RANK
├── classifier.py          # drug-name → class[] resolver
├── engine.py              # check_pair / check_candidate_against_active / check_candidate_against_disease_state / check_candidate_against_allergies / suggest_alternative / discharge_reconciliation_rules
├── demographic.py         # check_demographic_gate + DemographicVerdict
├── hyperkalemia.py        # potassium hold + hyperkalemia order set (Issue #2981)
├── _hyperkalemia_thresholds.py  # order-timing offset
├── _models.py             # Pydantic models of the six reference YAMLs
├── audit.py               # audit_drug_safety(patients) → list[AuditFinding]
├── reference_data/
│   ├── contraindications.yaml
│   ├── disease_contraindications.yaml
│   ├── demographic_gates.yaml
│   ├── allergy_contraindications.yaml
│   ├── drug_substitution.yaml
│   ├── hyperkalemia_response.yaml
│   ├── README.md          # YAML schemas
│   └── README.ja.md
├── README.md              # this file
└── README.ja.md
```

## 8. Enricher wiring

**None** — this is a library, not an enricher. Invoked synchronously by:

- `clinosim.simulator.medication_pipeline.apply_drug_safety_gate_to_orders`
  — DDI + disease-state + allergy gate + substitution; called on the
  merged admission orders from `simulator/inpatient.py` (via the
  `apply_drug_safety_gate_to_admission_orders` wrapper) and on newly
  placed daily-loop orders from `simulator/daily_loop.py`. Its
  `allergy_blocked` / `log_allergy_skip` helpers gate prescriptions that
  have no alternative to offer (outpatient renewal, the postpartum
  take-home bundle and C-section analgesic in `simulator/perinatal.py`).
- `clinosim.modules.patient.activator._derive_home_medications`
  — chronic-med selection loop (DDI + disease-state + allergy gates);
  skip-only, no substitution. The activator also stops a carried-over
  home medication the person is now allergic to.
- `clinosim.simulator.emergency` — ED order dispatch and take-home
  prescriptions (`check_demographic_gate` +
  `check_candidate_against_active` + disease-state + allergy rules).
- `clinosim.simulator.discharge_rx` — `check_pair` against active meds;
  allergy check (with substitution) on protocol and continued items.
- `clinosim.modules.prophylaxis.engine` — VTE prophylaxis candidate
  vs active meds.
- `clinosim.modules.longitudinal.engine` — reconciles carried-over
  home meds (`discharge_reconciliation_rules` +
  `check_candidate_against_active`) and skips additions a recorded
  allergy rules out.
- `clinosim.simulator.outpatient` and
  `clinosim.modules.order.discontinue_flip` — import the verdict types
  to record safety-skip entries.

## 9. Output surfaces

- **FHIR MedicationRequest.note[]**: moderate DDI cautions attached
  with `authorReference.display` = the localized `order_intent.interaction_check_author` ("Prescription safety check", Issue #3025). Empty
  otherwise. NO DetectedIssue resource emitted.
- **CIF `PatientProfile.safety_skip_log`**: internal / audit trace.
  Never emitted to FHIR structured resources — matches real EHR where
  a rejected CPOE order leaves no chart artifact.
- **Narrative (Layer 2)**:
  `clinosim/modules/document/narrative/_template_helpers.py::_render_safety_skips_line`
  appends deterministic bullet text to A&P / Plan section.
- **Narrative (Layer 3)**: `narrative_seed_bundle.yaml` (since v14)
  carries a `considered_but_not_prescribed` context key (built by
  `document/narrative/_extra_context_builder.py::_build_extra_context`)
  with a REQUIRED INCLUSION rule.
- **Narrative (Layer 4)**: 6 reserved individual prompts carry a sync
  note for future promotion.

## 10. Testing

- `tests/modules/drug_safety/test_verdict.py` — SafetyVerdict + severity
  ranking + default_action mapping (8 tests).
- `tests/modules/drug_safety/test_classifier.py` — alias / case / JA /
  dose-suffix / class taxonomy (13 tests).
- `tests/modules/drug_safety/test_ssri_snri_serotonin_gate.py` —
  SSRI+SNRI / SSRI+MAOI serotonin gate (28 tests).
- `tests/modules/drug_safety/test_engine_check_pair.py` — rule hits +
  order-independence + RNG-neutrality gate (13 tests).
- `tests/modules/drug_safety/test_engine_suggest_alternative.py` — shared
  pool + disease_ctx branch + JP country (10 tests).
- `tests/modules/drug_safety/test_cif_field_flow.py` — dataclass fields
  + narrative context filter (5 tests).
- `tests/modules/drug_safety/test_audit.py` — AD-60 audit plug-in (5
  tests).
- `tests/integration/test_drug_safety_order_hook.py` — order module
  gate + substitution (6 tests).
- `tests/integration/test_drug_safety_patient_hook.py` — activator
  gate skip-only (3 tests).
- `tests/integration/test_drug_safety_gate_post_admission.py` —
  daily-loop order gate (5 tests).
- `tests/integration/test_drug_safety_fhir_emit.py` — MR.note
  passthrough (3 tests).
- `tests/integration/test_narrative_avoidance_template.py` — Layer 2
  renderer (5 tests).
- `tests/integration/test_narrative_avoidance_consistency.py` —
  CIF↔narrative name traceability (2 tests).
- `tests/integration/test_llm_prompt_seed_bundle.py` — Layer 3 prompt
  version + rule + `_build_extra_context` (13 tests).
- Disease-state / demographic gates and caller wiring:
  `tests/unit/test_drug_safety_disease_state_1350.py`,
  `tests/unit/drug_safety/test_metformin_ckd_contraindication_1769.py`,
  `tests/unit/modules/drug_safety/test_demographic_gate.py`,
  `tests/unit/test_ed_order_drug_safety_1347.py`,
  `tests/unit/test_discharge_rx_drug_safety_1334.py`.
- Allergy gate: `tests/unit/modules/drug_safety/test_allergy_gate_2924.py`
  (rules, NKA / unrelated allergies, order / ED / discharge / activator
  wiring, YAML model).

Cohort verification runs through `scripts/verify_medical_stats.py`
which reports `contraindicated_pair_count` (target: 0).

## 11. Ownership

- 2026-09-03 — initial implementation.
- Spec: `docs/superpowers/specs/2026-09-03-drug-safety-module-design.md`.
- Plan: `docs/superpowers/plans/2026-09-03-drug-safety-module.md`.
- Issue: #1066.
