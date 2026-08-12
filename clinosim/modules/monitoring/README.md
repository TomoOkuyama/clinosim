# clinosim.modules.monitoring

Chronic-medication-driven monitoring pipeline. Reads each patient's
`current_medications` at the `POST_RECORDS` enricher stage and injects the
standard-of-care monitoring labs the medication requires, closing the
architectural gap flagged in [Issue #736](https://github.com/TomoOkuyama/clinosim/issues/736)
and captured under META [#757](https://github.com/TomoOkuyama/clinosim/issues/757).

Before this module, the simulator's lab-order sources were three:

1. Disease YAML `laboratory` blocks — per-encounter, per-disease.
2. Per-encounter admission / discharge protocol.
3. Antibiotic / procedure orders driven by the antibiotic module.

None of them consult `patient.current_medications`, so a warfarin patient
whose encounters were sepsis / MI / AF got PT-INR only when THAT disease's
YAML happened to fire the coag panel; a warfarin patient whose only
encounter was outpatient HTN follow-up got no PT-INR at all (baseline
p=500 seed 42: 6 warfarin patients, 0 PT-INR observations).

## Pipeline

`enrich_medication_monitoring` (POST_RECORDS) runs after all encounter
records exist and does, for each patient record:

1. Detect which drugs from the mapping YAML the patient is on
   (`current_medications` list, case-insensitive substring match to cover
   English + Japanese + brand-name variants — mirrors
   `physiology.engine._WARFARIN_NAMES`).
2. For each matched drug, iterate the monitoring labs it prescribes and
   inject each one via `_inject_monitoring_lab` into an eligible encounter
   (currently the first outpatient encounter of the record, else the
   first encounter — MVP scope, expanded in follow-up PRs when
   frequency-based scheduling is added).
3. Skip labs the record already has an order for (dedup against
   `record.orders` + `record.lab_results`) so disease-YAML-driven orders
   (sepsis PT-INR, PE PT-INR, etc.) do not double-count.
4. Derive the lab value from `physiology.engine.derive_lab_values` with
   the correct medication flag on (`on_warfarin=True` for warfarin), then
   apply the shared `apply_realistic_variability` noise model so the
   emitted value passes through the same physiologic-limit clamp as any
   other observation.

## RNG isolation

Randomness in this enricher (noise + micro-jitter) comes from
`np.random.default_rng(derive_sub_seed(master_seed, ENRICHER_SEED_OFFSETS["medication_monitoring"], patient_id))`,
matching the sibling enrichers (care_level, family_history, …). Master
RNG is not touched; changes to `medication_monitoring.yaml` shift only
the affected patients' records.

## Mapping YAML

`reference_data/medication_monitoring.yaml`. Schema:

```yaml
mappings:
  Warfarin:                                   # drug name (case-insensitive match against current_medications)
    aliases: ["ワルファリン", "coumadin"]      # optional additional names
    monitoring:
      - lab: PT_INR                            # internal lab-analyte name (matches observation/engine.py)
        loinc: "6301-6"                        # observation code (for the emitted Order display)
        rationale: "Anticoagulation therapeutic monitoring — INR target 2.0-3.0."
```

Adding a new drug → labs pair is a pure YAML edit; the enricher picks it
up automatically. The frequency / scheduling knobs listed in META #757
(daily vs monthly, induction vs maintenance) are intentionally NOT in
the schema yet — pass 2 (this PR) ships one-shot per-encounter injection
to close the immediate #736 gap. Follow-up PRs will add
`frequency: {induction: "1-3d", maintenance: "monthly"}` handling.

## Tests

`tests/unit/test_medication_monitoring.py` covers: mapping loader
round-trip, alias matching, no-op on non-warfarin patients, determinism
across repeated runs with the same seed, and dedup against pre-existing
PT-INR orders.

## Non-goals (per META #757)

- Modeling ALL medication monitoring guidelines (only the pairs listed
  in `medication_monitoring.yaml` — the long tail is out of scope).
- Modeling dose-titration causal loops (INR drives warfarin dose change
  → next INR). Simulator emits observations, not therapeutic feedback.
- Perfect real-world monitoring-frequency fidelity (goal is ±50%; the
  simulator is synthetic).
