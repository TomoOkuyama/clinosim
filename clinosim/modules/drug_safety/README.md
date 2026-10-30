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
Rx / prophylaxis) and the `patient` activator. Two companion gates
cover drug-vs-disease-state (`check_candidate_against_disease_state`)
and drug-vs-age/sex (`check_demographic_gate`) contraindications.

## 2. Scope

**In scope**:
- Rule engine: class × class contraindication lookup with severity-graded
  verdicts (allowed / minor / moderate / major / contraindicated).
- Drug-class × chronic-disease-state rules (`disease_contraindications.yaml`,
  Issue #1392 / #1350, staged `stage_in` predicate Issue #1769).
- Demographic (age / sex) gate (`demographic_gates.yaml`, Issues
  #1316 / #1328) with ICD-prefix `exception_indications` bypass.
- Alternative substitution: revives Issue #437 dead-data `alternative_*`
  blocks in disease YAML + new `locale/shared/drug_substitution.yaml`
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
)  # → AlternativeDrug(drug="Acetaminophen", ...)

# Drug-vs-chronic-disease-state — entries are ICD strings or (code, stage) tuples
verdicts = drug_safety.check_candidate_against_disease_state(
    "Ibuprofen", ["I50.9"],
)  # → [SafetyVerdict(rule_id="nsaid-in-heart-failure", ...)]

# Demographic (age / sex) gate
dv = drug_safety.check_demographic_gate(
    "Aspirin 325mg", patient_age=8, patient_sex="M", indication_codes=None,
)  # → DemographicVerdict(severity="contraindicated", rule_id="aspirin-pediatric-reyes", ...)

# Utility
drug_safety.resolve_classes("warfarin")   # → ["anticoagulant.vka", "anticoagulant"]
drug_safety.canonical_name("ワルファリン")  # → "Warfarin"
drug_safety.japanese_display("Aspirin")   # → "アスピリン"
```

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

- `clinosim.locale/` (reads `locale/shared/drug_substitution.yaml`)
- `clinosim.codes` drug catalog (`classifier._catalog_en_to_drug_id`
  resolves `drug_id` entries to display names)
- `clinosim.modules.disease.protocol` (lazy import for
  `alternatives_by_indication` — only when disease_ctx is passed)
- Third-party: `PyYAML` only.
- **No other cross-clinosim runtime deps.**

## 6. Constants and configuration

Five YAML files:

- `reference_data/drug_classes.yaml` — drug → class[] taxonomy
  (52 drugs across anticoagulants, antiplatelets, NSAIDs,
  β-blockers, CCBs, ACEi/ARB, statins, SSRI/SNRI, misc rule targets).
- `reference_data/contraindications.yaml` — class × class rules
  (11 rules: VKA+antiplatelet, DOAC+P2Y12, anticoagulant+NSAID,
  BB+non-DHP CCB, ACEi/ARB+K, ACEi/ARB+K-sparing, statin+strong
  CYP3A4 inhibitor, allopurinol+thiopurine, SSRI+MAOI, SSRI+SNRI,
  NSAID stacking).
- `reference_data/disease_contraindications.yaml` — drug class ×
  chronic-disease rules (4 rules: NSAID in heart failure / cirrhosis /
  CKD stage 4-5, metformin in CKD stage 3b-5).
- `reference_data/demographic_gates.yaml` — age / sex rules (3 rules:
  aspirin pediatric (Reye's), nitroglycerin adult-only, tamsulosin
  adult male).
- `locale/shared/drug_substitution.yaml` — generic indication →
  alternative pool keyed by catalog `drug_id` (pain_management →
  acetaminophen; hypertension_or_rate_control → amlodipine /
  candesartan).

Also lifts the Issue #437 dead-data `alternative_*` blocks in 15
disease YAMLs via `_indication_tag` markers.

## 7. Directory contents

```
clinosim/modules/drug_safety/
├── __init__.py            # public API re-export
├── verdict.py             # SafetyVerdict + SafetySkipEntry + Severity + SEVERITY_RANK
├── classifier.py          # drug-name → class[] resolver
├── engine.py              # check_pair / check_candidate_against_active / check_candidate_against_disease_state / suggest_alternative
├── demographic.py         # check_demographic_gate + DemographicVerdict
├── audit.py               # audit_drug_safety(patients) → list[AuditFinding]
├── reference_data/
│   ├── drug_classes.yaml
│   ├── contraindications.yaml
│   ├── disease_contraindications.yaml
│   ├── demographic_gates.yaml
│   └── README.md          # YAML schemas
├── README.md              # this file
└── README.ja.md
```

## 8. Enricher wiring

**None** — this is a library, not an enricher. Invoked synchronously by:

- `clinosim.simulator.medication_pipeline.apply_drug_safety_gate_to_orders`
  — DDI gate + substitution; called on the merged admission orders
  from `simulator/inpatient.py` (via the
  `apply_drug_safety_gate_to_admission_orders` wrapper) and on newly
  placed daily-loop orders from `simulator/daily_loop.py`.
- `clinosim.modules.patient.activator._derive_home_medications`
  — chronic-med selection loop (DDI + disease-state gates); skip-only,
  no substitution.
- `clinosim.simulator.emergency` — ED order dispatch
  (`check_demographic_gate` + `check_candidate_against_active`).
- `clinosim.simulator.discharge_rx` — `check_pair` against active meds.
- `clinosim.modules.prophylaxis.engine` — VTE prophylaxis candidate
  vs active meds.

## 9. Output surfaces

- **FHIR MedicationRequest.note[]**: moderate DDI cautions attached
  with `authorReference.display = "clinosim drug_safety v1"`. Empty
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

Cohort verification runs through `scripts/verify_medical_stats.py`
which reports `contraindicated_pair_count` (target: 0).

## 11. Ownership

- Session 99 (2026-09-03) — initial implementation.
- Spec: `docs/superpowers/specs/2026-09-03-drug-safety-module-design.md`.
- Plan: `docs/superpowers/plans/2026-09-03-drug-safety-module.md`.
- Issue: #1066.
