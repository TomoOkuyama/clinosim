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
`order` and `patient` modules.

## 2. Scope

**In scope**:
- Rule engine: class × class contraindication lookup with severity-graded
  verdicts (allowed / minor / moderate / major / contraindicated).
- Alternative substitution: revives Issue #437 dead-data `alternative_*`
  blocks in disease YAML + new `locale/shared/drug_substitution.yaml`
  generic pool.
- CIF trace via `PatientProfile.safety_skip_log` (per-patient list of
  `SafetySkipEntry` records).
- Narrative surfacing (all 4 layers): NarrativeContext + template
  fallback + production LLM prompt + reserved-prompt sync notes.
- MedicationRequest.note passthrough for moderate DDI cautions.
- AD-60-style audit plug-in (post-hoc missed-gate detector).

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
  site. This is a documented cohort-scale change per
  `feedback_rng_shift_patient_cache_cascade`. Version bump = MINOR.
- **Cross-platform bit-reproducibility**: safe under the
  `_DeterministicRngProxy` regime — only dict lookups + string
  comparisons.

## 5. Dependencies

- `clinosim.locale/` (reads `locale/shared/drug_substitution.yaml`)
- `clinosim.modules.disease.protocol` (lazy import for
  `alternatives_by_indication` — only when disease_ctx is passed)
- Third-party: `PyYAML` only.
- **No cross-clinosim runtime deps beyond the above.**

## 6. Constants and configuration

Three YAML files:

- `reference_data/drug_classes.yaml` — drug → class[] taxonomy
  (~40 drugs across anticoagulants, antiplatelets, NSAIDs,
  β-blockers, CCBs, ACEi/ARB, statins, misc rule targets).
- `reference_data/contraindications.yaml` — class × class rules
  (8 rules covering warfarin+antiplatelet, anticoagulant+NSAID,
  BB+non-DHP CCB, ACEi/ARB+K, statin+CYP3A4, allopurinol+thiopurine,
  SSRI+MAOI, and ACEi/ARB+K-sparing).
- `locale/shared/drug_substitution.yaml` — generic indication →
  alternative pool (pain_management → Acetaminophen;
  hypertension_or_rate_control → Amlodipine / Candesartan).

Also lifts the Issue #437 dead-data `alternative_*` blocks in 15
disease YAMLs via `_indication_tag` markers.

## 7. Directory contents

```
clinosim/modules/drug_safety/
├── __init__.py            # public API re-export
├── verdict.py             # SafetyVerdict + SafetySkipEntry + Severity + SEVERITY_RANK
├── classifier.py          # drug-name → class[] resolver
├── engine.py              # check_pair / check_candidate_against_active / suggest_alternative
├── audit.py               # audit_drug_safety(patients) → list[AuditFinding]
├── reference_data/
│   ├── drug_classes.yaml
│   ├── contraindications.yaml
│   └── README.md          # schema for both YAMLs (+ drug_substitution.yaml)
├── README.md              # this file
└── README.ja.md
```

## 8. Enricher wiring

**None** — this is a library, not an enricher. Invoked synchronously by:

- `clinosim.simulator.medication_pipeline.apply_drug_safety_gate_to_admission_orders`
  — post-hoc filter on the merged admission_orders list in
  `simulator/inpatient.py::_simulate_patient`.
- `clinosim.modules.patient.activator._derive_home_medications`
  — chronic-med selection loop; skip-only, no substitution.

## 9. Output surfaces

- **FHIR MedicationRequest.note[]**: moderate DDI cautions attached
  with `authorReference.display = "clinosim drug_safety v1"`. Empty
  otherwise. NO DetectedIssue resource emitted.
- **CIF `PatientProfile.safety_skip_log`**: internal / audit trace.
  Never emitted to FHIR structured resources — matches real EHR where
  a rejected CPOE order leaves no chart artifact.
- **Narrative (Layer 2)**: `template_generator._render_safety_skips_line`
  appends deterministic bullet text to A&P / Plan section.
- **Narrative (Layer 3)**: `narrative_seed_bundle.yaml` v14 gains a
  `considered_but_not_prescribed` context key with Rule 2 REQUIRED
  INCLUSION.
- **Narrative (Layer 4)**: 6 reserved individual prompts carry a sync
  note for future promotion.

## 10. Testing

- `tests/modules/drug_safety/test_verdict.py` — SafetyVerdict + severity
  ranking + default_action mapping (8 tests).
- `tests/modules/drug_safety/test_classifier.py` — alias / case / JA /
  dose-suffix / class taxonomy (13 tests).
- `tests/modules/drug_safety/test_engine_check_pair.py` — rule hits +
  order-independence + RNG-neutrality gate (13 tests).
- `tests/modules/drug_safety/test_engine_suggest_alternative.py` — shared
  pool + disease_ctx branch + JP country (10 tests).
- `tests/modules/drug_safety/test_cif_field_flow.py` — dataclass fields
  + narrative context filter (4 tests).
- `tests/modules/drug_safety/test_audit.py` — AD-60 audit plug-in (5
  tests).
- `tests/integration/test_drug_safety_order_hook.py` — order module
  gate + substitution (6 tests).
- `tests/integration/test_drug_safety_patient_hook.py` — activator
  gate skip-only (3 tests).
- `tests/integration/test_drug_safety_fhir_emit.py` — MR.note
  passthrough (3 tests).
- `tests/integration/test_narrative_avoidance_template.py` — Layer 2
  renderer (5 tests).
- `tests/integration/test_narrative_avoidance_consistency.py` —
  CIF↔narrative name traceability (2 tests).
- `tests/integration/test_llm_prompt_seed_bundle.py` — Layer 3 prompt
  version + rule + `_build_extra_context` (8 tests).

Cohort verification runs through `scripts/verify_medical_stats.py`
which reports `contraindicated_pair_count` (target: 0).

## 11. Ownership

- Session 99 (2026-09-03) — initial implementation.
- Spec: `docs/superpowers/specs/2026-09-03-drug-safety-module-design.md`.
- Plan: `docs/superpowers/plans/2026-09-03-drug-safety-module.md`.
- Issue: #1066.
