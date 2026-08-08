# Phase 2b: `on_warfarin` medication-physiology coupling for PT_INR therapeutic range

**Date**: 2026-06-24
**Author**: Tomo Okuyama (with Claude Opus 4.7)
**Status**: APPROVED — ready for plan
**Predecessor**: Phase 2a (D-dimer + `causes_vte`, PR #81)
**Successor candidates**: Phase 2c (aPTT/heparin therapeutic, DOAC INR micro-effect, warfarin linear ramp, HIT modeling)

---

## 1. Motivation

After Phase 2a (`causes_vte` flag lifts D-dimer for PE/DVT/embolic stroke), the synthetic EHR has VTE patients with positive D-dimer — but their `PT_INR` is still driven only by `coagulation_status` (DIC/fibrinolysis) and `hepatic` (cirrhosis). The cohort story is incomplete:

- **AF chronic patient on warfarin admitted for sepsis** → INR should be 2.0-3.0 (therapeutic), but currently shows ~1.0 (baseline) unless DIC kicks in.
- **PE/DVT admit day 1-2** → INR ~1.0 (correct, warfarin loading not yet effective).
- **PE/DVT admit day 3+** → INR should rise to 2.0-3.0 (warfarin therapeutic), but currently stays ~1.0.
- **PE/DVT post-discharge outpatient followup** → INR should be therapeutic if on chronic AC (3-6+ months standard), but currently baseline.

Phase 2b closes this gap by coupling **warfarin medication state** to the PT_INR derivation, completing the **admit → ramp → discharge → outpatient followup** cohort trajectory for VTE / AF / embolic-CI patients.

### Scope decisions (all from brainstorming 2026-06-24)

| Decision | Choice | Rationale |
|---|---|---|
| Architectural pattern | (d) medication-physiology coupling via new helper `medication_flags_from_context` | Establishes reusable "medication → lab change" pattern (future: steroid→glucose, diuretic→K, antibiotic→CRP). Cleanest separation: medication peeked at observation time, BNP-pattern surgical, state untouched. |
| Patient/encounter scope | B (chronic AC + in-hospital ramp) | Captures both static (AF chronic) and dynamic (PE admit ramp) cases. Real EHR shows continuous trajectory. |
| Chronic AC indications | 2 (I48 + I26 + I82 + I63) | Completes lifecycle: AF chronic + PE/DVT/embolic-stroke acute admit → discharge → outpatient followup. Matches clinical guideline AC duration. |
| Ramp curve shape | A (step day ≥ 3 = therapeutic) + DOAC unchanged | Warfarin loading 3-day rule. INR is clinically not monitored for DOAC (apixaban/rivaroxaban/edoxaban/dabigatran); modeling DOAC INR effect is YAGNI and clinically misleading. |
| Heparin / aPTT | Deferred to Phase 2c | Current focus is PT_INR. UFH IV drip is ICU-subset; LMWH (modern PE/DVT) does not affect aPTT meaningfully. |
| DOAC linear ramp / micro-effect | Deferred (YAGNI) | DOAC is not titrated by INR clinically; modeling 0.2-0.3 INR lift adds complexity for no realism gain. |

---

## 2. Architecture

```
                       patient.current_medications  +  MAR records (today)
                                       ↓
                medication_flags_from_context(patient, mar_today, day_into_stay)
                                       ↓
                                {"on_warfarin": bool}
                                       ↓
         derive_lab_values(..., **scenario_flags, **medication_flags)  ← merged dict
                                       ↓
              if on_warfarin: PT_INR therapeutic 2.5 + base perturbation × 0.5
              else:          existing formula (1.0 + (1-hepatic)*2.0 + coag*1.5)
                                       ↓
                            PT = 12 * PT_INR  (existing, auto-consistent)
```

**Invariants**:
- **State unchanged** (BNP-pattern surgical, AD-57). No new `PhysiologicalState` field.
- **AD-59 preserved** (per-order sub-rng pattern intact; no new RNG draw inside `derive_lab_values`).
- **AD-16 preserved** (no master RNG impact; medication detection is deterministic peek).
- **scenario_flags helper pattern unchanged** (Phase 2a / J5 architecture). New parallel helper for medication-driven coupling.

**New CLAUDE.md architecture rule**:

> Lab derivation now reads TWO flag dicts: `scenario_flags_from_protocol(protocol)` for disease-driven flags (`causes_vte`, `myocardial_injury`), and `medication_flags_from_context(patient, mar_today, day_into_stay)` for medication-driven flags (`on_warfarin`). Call sites merge both via `**flags` to `derive_lab_values`. NEVER add a `flag=value` named argument directly at a call site — extend the appropriate helper instead. This prevents J5-style wiring defects (one call site reads the flag, the others silently don't).

---

## 3. New helper: `medication_flags_from_context`

Location: `clinosim/modules/physiology/engine.py` (sibling of `scenario_flags_from_protocol`).

```python
def medication_flags_from_context(
    patient,                            # PatientProfile | None
    mar_today=None,                     # list[MARRecord] | None — today's administered meds
    day_into_stay: int | None = None,   # int | None — for in-hospital ramp gate
) -> dict[str, bool]:
    """Detect medication-driven lab effects from patient + MAR context.

    Centralizes the medication → lab coupling reads so a new coupling added to
    `derive_lab_values` only needs wiring in ONE place — same J5-prevention
    rationale as `scenario_flags_from_protocol`. Dict keys match
    `derive_lab_values` parameter names so callers can spread with `**flags`.

    Phase 2b: returns `{"on_warfarin": bool}` only. Extend the dict for future
    couplings (steroid → glucose, diuretic → K, antibiotic → CRP).

    Detection rules:
      (1) Chronic warfarin: `patient.current_medications` contains warfarin
          (string match on "warfarin"/"ワルファリン"/"coumadin").
      (2) In-hospital warfarin: `mar_today` contains a warfarin administration
          AND `day_into_stay >= 3` (loading-dose 3-day rule).

    DOAC (apixaban/rivaroxaban/edoxaban/dabigatran) is NOT detected — INR is
    clinically not monitored for DOAC patients (rivaroxaban has minor PT effect
    but is not used for therapeutic monitoring). Modeling DOAC INR lift would
    be clinically misleading.

    Returns `{"on_warfarin": False}` if patient is None or no matches.
    """
    if patient is None:
        return {"on_warfarin": False}

    WARFARIN_NAMES = ("warfarin", "ワルファリン", "coumadin")
    on_warfarin = False

    # (1) Chronic warfarin from home meds
    for med in (getattr(patient, "current_medications", None) or []):
        med_lower = med.lower() if isinstance(med, str) else ""
        if any(name in med_lower for name in WARFARIN_NAMES):
            on_warfarin = True
            break

    # (2) In-hospital warfarin started ≥ 3 days ago
    if (
        not on_warfarin
        and mar_today
        and day_into_stay is not None
        and day_into_stay >= 3
    ):
        for rec in mar_today:
            drug = (getattr(rec, "drug_name", "") or "").lower()
            if any(name in drug for name in WARFARIN_NAMES):
                on_warfarin = True
                break

    return {"on_warfarin": on_warfarin}
```

**Key design points**:
- Phase 2b returns single key `{"on_warfarin": bool}` — DOAC intentionally not detected (faithful to clinical practice; no INR monitoring for DOAC).
- Helper is forward-extensible: Phase 2c can add `"on_therapeutic_heparin"` etc. without touching call sites.
- ED / outpatient pass `mar_today=None` (no in-hospital ramp applies); chronic detection works.
- `current_medications` is `list[str]` (strings like "Warfarin 3mg" / "ワルファリン3mg"), so substring match handles both EN and JP forms.
- Defensive: handles `None` patient, missing attribute, non-string list entries.

---

## 4. `derive_lab_values` extension

Add `on_warfarin: bool = False` kwarg. Modify only the PT_INR block:

```python
def derive_lab_values(
    state, sex, age,
    has_diabetes=False, rng=None, hour=6,
    myocardial_injury=False,
    causes_vte=False,
    on_warfarin=False,                  # NEW
) -> dict[str, float]:
    ...
    # --- Hepatic ---
    labs["AST"] = 25 + (1 - hepatic) * 500
    labs["ALT"] = 20 + (1 - hepatic) * 400
    labs["T_Bil"] = 0.8 + (1 - hepatic) * 15

    # PT_INR: hepatic (cirrhosis factor depletion) + coagulation_status (DIC
    # consumption) drive baseline; therapeutic warfarin overrides to target
    # the 2.0-3.0 clinical band. AC + comorbidity (DIC, cirrhosis) compounds
    # bleeding risk in real practice, so base perturbation is added on top of
    # the therapeutic center at reduced gain (×0.5).
    # BNP-pattern surgical (AD-57): state untouched, formula-only change.
    base_inr = 1.0 + (1 - hepatic) * 2.0 + state.coagulation_status * 1.5
    if on_warfarin:
        labs["PT_INR"] = 2.5 + (base_inr - 1.0) * 0.5
    else:
        labs["PT_INR"] = base_inr
    ...
    # PT (derived FROM PT_INR for numerical consistency — unchanged)
    labs["PT"] = clamp(12.0 * labs["PT_INR"], 9.0, 90.0)
```

**Expected behavior**:

| Patient state | base_inr | on_warfarin | PT_INR |
|---|---|---|---|
| Healthy, no warfarin | 1.0 | F | 1.0 |
| AF chronic on warfarin, no comorbidity | 1.0 | T | 2.5 |
| DIC (coag=0.5), no warfarin | 1.75 | F | 1.75 |
| AF on warfarin + DIC (coag=0.5) | 1.75 | T | 2.875 |
| Cirrhosis (hepatic=0.4), no warfarin | 2.2 | F | 2.2 |
| AF on warfarin + cirrhosis (hepatic=0.4) | 2.2 | T | 3.1 (over-AC risk) |
| PE on Apixaban (DOAC, not warfarin) | 1.0 | F | 1.0 (DOAC unmodeled) |

**Clinical realism**:
- Warfarin-only: 2.5 (mid-therapeutic).
- Warfarin + cirrhosis: 3.1 (matches clinical reality — INR over-shoot is a known interaction; need dose reduction).
- DOAC patient: baseline INR (matches clinical reality — INR not monitored, baseline value not informative).

**PT downstream**: `PT = 12 * PT_INR` (existing line, auto-consistent — warfarin patient PT = 30s when INR = 2.5).

---

## 5. YAML data changes

### `clinosim/locale/shared/chronic_medications.yaml` — 3 new entries

```yaml
# Existing (untouched)
I48:  # Atrial fibrillation
  medications:
    - {drug: "Warfarin 3mg", drug_ja: "ワルファリン3mg", route: "PO", frequency: "daily", probability: 0.5}
    - {drug: "Apixaban 5mg", drug_ja: "アピキサバン5mg", route: "PO", frequency: "bid", probability: 0.5}
  monitoring: ...

# NEW (Phase 2b)
I26:  # Pulmonary embolism — post-discharge AC (ACCP 2020 / ESC 2019: ≥3 mo, indefinite if unprovoked)
  medications:
    - {drug: "Rivaroxaban 20mg", drug_ja: "リバーロキサバン15mg", route: "PO", frequency: "daily", probability: 0.5}
    - {drug: "Apixaban 5mg", drug_ja: "アピキサバン5mg", route: "PO", frequency: "bid", probability: 0.3}
    - {drug: "Warfarin 3mg", drug_ja: "ワルファリン3mg", route: "PO", frequency: "daily", probability: 0.2}
  monitoring:
    - {test: "PT_INR", frequency: "monthly", condition: "if on warfarin"}
    - {test: "Cr", frequency: "every 6 months", condition: "if on DOAC"}

I82:  # Deep vein thrombosis — same duration logic as I26
  medications:
    - {drug: "Rivaroxaban 20mg", drug_ja: "リバーロキサバン15mg", route: "PO", frequency: "daily", probability: 0.5}
    - {drug: "Apixaban 5mg", drug_ja: "アピキサバン5mg", route: "PO", frequency: "bid", probability: 0.3}
    - {drug: "Warfarin 3mg", drug_ja: "ワルファリン3mg", route: "PO", frequency: "daily", probability: 0.2}
  monitoring:
    - {test: "PT_INR", frequency: "monthly", condition: "if on warfarin"}

I63:  # Cerebral infarction — secondary prevention; embolic source (AF/cardiac) gets AC, others antiplatelet
  medications:
    # AC (used for embolic/AF-related strokes) — ~60% combined probability
    - {drug: "Warfarin 3mg", drug_ja: "ワルファリン3mg", route: "PO", frequency: "daily", probability: 0.3}
    - {drug: "Apixaban 5mg", drug_ja: "アピキサバン5mg", route: "PO", frequency: "bid", probability: 0.3}
    # Antiplatelet (used for non-embolic strokes) — does NOT affect INR
    - {drug: "Aspirin 100mg", drug_ja: "アスピリン100mg", route: "PO", frequency: "daily", probability: 0.7}
    - {drug: "Clopidogrel 75mg", drug_ja: "クロピドグレル75mg", route: "PO", frequency: "daily", probability: 0.3}
  monitoring:
    - {test: "PT_INR", frequency: "monthly", condition: "if on warfarin"}
```

**Probability rationale**:

- I26 / I82 (modern PE/DVT guideline-favored): DOAC 80% (rivaroxaban 50 + apixaban 30) / warfarin 20% — matches 2020+ ACCP first-line DOAC recommendation; warfarin remains for severe renal impairment, mechanical valves, cost concerns.
- I63: 60% AC (embolic-source proxy probability) + 70% antiplatelet (AC + antiplatelet co-prescription is clinically used in select cases — embolic stroke + extracranial atherosclerosis).

**Known limitation (pre-existing activator behavior, not introduced by Phase 2b)**: `_derive_home_medications` (`patient/activator.py:387`) draws each `probability` entry independently, so a patient can end up with BOTH warfarin AND apixaban (≈ 0.5 × 0.5 = 25% for AF). This is clinically unrealistic for AF (single-AC choice). For Phase 2b's purpose (warfarin **detection**), this does not cause incorrect classification — if warfarin is present, `on_warfarin = True` regardless of co-present apixaban. Fixing the activator exclusivity for AC drugs is documented in Phase 2c backlog (Section 10) as a separate cleanup.

### `helpers.py` chronic-conditions promotion (verification task)

`run_beta` promotes acute discharge diagnoses to chronic conditions for repeat-encounter consistency. The chronic_prefixes list must include `I26`, `I82`, `I63` for the new chronic_medications entries to ever resolve.

**Task** (implementation phase): grep `chronic_prefixes` in `simulator/helpers.py`. If `I26`/`I82`/`I63` are missing, add them with rationale comment. If they are missing AND the activator does not promote — file as plan task to extend.

---

## 6. Call-site wiring

Three sites pass merged `**flags` (Phase 2a established the pattern; this PR extends each line):

### `simulator/inpatient.py` (Pass-1 and dual-encounter loops)

```python
flags = {
    **scenario_flags_from_protocol(protocol),
    **medication_flags_from_context(patient, mar_today=mar_for_today, day_into_stay=day_into_stay),
}
true_labs = derive_lab_values(state, sex=patient.sex, age=patient.age,
                               has_diabetes=has_diabetes, hour=lab_hour, **flags)
```

- `mar_for_today`: gathered from the MAR records produced this day (already available in the lab loop).
- `day_into_stay`: `(current_day - admission_day).days` (already computed for other purposes; if not, add the trivial calculation).
- The second call (lagged_state) uses the same flags (consistent within day).

### `simulator/emergency.py`

```python
flags = {
    **scenario_flags_from_protocol(protocol),
    **medication_flags_from_context(patient, mar_today=None, day_into_stay=None),
}
true_labs = derive_lab_values(state, sex=patient.sex, age=patient.age,
                               has_diabetes=_has_dm, **flags)
```

ED is admit-day; no in-hospital ramp applies. Chronic warfarin detection works.

### `simulator/outpatient.py`

```python
flags = {
    **scenario_flags_from_protocol(None),
    **medication_flags_from_context(patient, mar_today=None, day_into_stay=None),
}
true_labs = derive_lab_values(state, sex=patient.sex, age=patient.age,
                               has_diabetes=_has_dm, **flags)
```

Outpatient = chronic-context lab; passing `protocol=None` to scenario_flags (existing) and only chronic medication detection applies. PE/DVT/CI post-discharge patients on chronic warfarin will show therapeutic INR.

### Sole second inpatient site (line 1685 `true_labs = derive_lab_values(...)`)

This existing site (per Phase 2a memory) calls `derive_lab_values` without any flags (relies on defaults). Phase 2b leaves it as-is (matches `scenario_flags_from_protocol(None)` semantics) UNLESS audit shows it needs warfarin awareness — verify during implementation, extend if needed.

---

## 7. AD-59 invariant + byte-diff strategy

### AD-59 isolation guard (new integration test)

`tests/integration/test_medication_flags_isolation.py`:

> Adding or removing a chronic_medications.yaml entry for any indication MUST NOT change the labs of patients who do not carry that indication.

Same rigour as `test_individual_lab_isolation.py` (per-order sub-rng), `test_panel_specimen_isolation.py` (per-parent), and Phase 2a J5 wiring guard.

Implementation: generate p=200 seeded fixed (no I26/I82/I63 chronic AC indications) → baseline labs. Add a single ephemeral chronic_medications.yaml entry for I26 → regenerate → diff labs of patients lacking I26 chronic_condition → MUST be byte-identical.

### byte-diff (US/JP p=2000 seed=42 vs master `9e0b97a7`)

| File | Expected diff | Reason |
|---|---|---|
| Patient.ndjson | sha256 IDENTICAL | No demographic change |
| Encounter.ndjson | sha256 IDENTICAL | No encounter change |
| Condition.ndjson | sha256 IDENTICAL | No diagnosis change |
| Medication*.ndjson | **may grow** | I26/I82/I63 chronic AC patients newly get home meds (legitimate, AD-59-safe via per-patient sub-rng in activator) |
| Procedure.ndjson | sha256 IDENTICAL | No procedure change |
| Imaging.ndjson | sha256 IDENTICAL | No imaging change |
| Immunization.ndjson | sha256 IDENTICAL | Independent enricher |
| FamilyHistory.ndjson | sha256 IDENTICAL | Independent enricher |
| Observation.ndjson | **strict-grow** | PT_INR / PT for warfarin patients lifts; all other observations identical |
| DiagnosticReport.ndjson | **strict-grow** | Coag panel (24373-3) carries the PT_INR/PT value change |

**Acceptance**: Patient / Encounter / Condition / Procedure / Imaging / Immunization / FamilyHistory must be sha256 IDENTICAL. Medication growth is documented and audited (probability distributions match). Observation/DR strict-grow with only PT_INR/PT changes for warfarin-detected patients.

### DQR — 3 axes (US p=10000 + JP p=5000, seed=42)

**Structural**:
- warfarin patient subset: PT_INR/PT obs count, refRange 100%, code lookup OK
- Helper detection rate matches activator-generated chronic AC patient count
- No I26/I82/I63 patient without home med (after activator)
- No non-AC patient with shifted INR

**Clinical**:
- AF chronic patient labs: p50 INR ≈ 2.5, p10 > 1.8, p90 < 3.5 (therapeutic band)
- I26/I82/I63 post-discharge outpatient followup: ~20% INR therapeutic (warfarin probability) + ~80% baseline (DOAC)
- PE/DVT inpatient day < 3: INR ≈ 1.0 (correct — pre-loading)
- PE/DVT inpatient day ≥ 3 with warfarin order: INR shifted into therapeutic
- AC + DIC compound patient: INR > 3.0 (over-AC risk visible)
- DOAC patients (apixaban/rivaroxaban): INR distribution matches baseline (no shift)

**JP language**:
- "ワルファリン3mg" / "アピキサバン5mg" / "リバーロキサバン15mg" appear in JP Medication.text
- JP Coag panel display "凝固検査パネル", PT_INR JP display intact (JLAC10 2B030)
- US: no JP characters

---

## 8. Test strategy

### Unit tests — `tests/unit/test_physiology.py` (extend)

- `test_pt_inr_on_warfarin_therapeutic`: baseline healthy + on_warfarin=True → INR 2.4-2.6
- `test_pt_inr_on_warfarin_with_dic`: coag_status=0.5 + on_warfarin=True → INR ~2.9 (comorbidity lift)
- `test_pt_inr_on_warfarin_with_cirrhosis`: hepatic=0.4 + on_warfarin=True → INR ~3.1 (over-AC)
- `test_pt_inr_off_warfarin_unchanged`: on_warfarin=False → existing formula
- `test_pt_derived_consistency_with_warfarin`: PT = 12 * PT_INR maintained when warfarin shifts INR

### Unit tests — `tests/unit/test_medication_flags.py` (new file)

- `test_chronic_warfarin_detected_en`
- `test_chronic_warfarin_detected_jp`
- `test_chronic_apixaban_not_warfarin`
- `test_chronic_rivaroxaban_not_warfarin`
- `test_in_hospital_warfarin_day_2_not_yet`
- `test_in_hospital_warfarin_day_3_active`
- `test_in_hospital_apixaban_never_triggers`
- `test_no_meds_returns_false`
- `test_none_patient_returns_false`
- `test_chronic_overrides_in_hospital_gate`: chronic warfarin → True even at day_into_stay=1

### Integration tests — `tests/integration/`

- `test_af_chronic_warfarin_inr_therapeutic`: activated AF patient labs show INR in [2.0, 3.5]
- `test_pe_inpatient_day3_inr_therapeutic`: PE inpatient day-3 labs show INR shifted
- `test_pe_post_discharge_followup_inr_split`: outpatient followup INR varies by warfarin vs DOAC
- `test_medication_flags_isolation` (AD-59 guard): adding chronic_medications entry for X does not change labs for non-X patients

### Byte-diff verification (manual scratchpad script)

`scratchpad/phase2b_byte_diff_results.md` — p=2000 US/JP seed=42 vs master `9e0b97a7`:
- Expected: 7 NDJSON identical; Medication may grow (audit distribution); Observation/DR strict-grow (PT_INR/PT only).

### DQR (manual)

`docs/reviews/2026-06-24-phase2b-anticoagulation-data-quality-review.md` — US p=10000 + JP p=5000 seed=42:
- 3-axis structured/clinical/JP, evidence per Section 7.

---

## 9. Plan task breakdown (for writing-plans)

1. **medication_flags_from_context helper + unit tests** — TDD: write test, implement helper, verify chronic/in-hospital paths
2. **derive_lab_values extension (on_warfarin kwarg) + unit tests** — TDD: extend signature, modify PT_INR block, verify formula
3. **chronic_medications.yaml: I26 / I82 / I63 entries + helpers.py chronic_prefixes verification** — add YAML entries, grep helpers.py, extend if needed
4. **Call-site wiring (inpatient/emergency/outpatient.py)** — extend each derive_lab_values call to merge medication_flags
5. **Integration tests** (AD-59 isolation + clinical scenarios)
6. **byte-diff verification** (US/JP p=2000) — write scratchpad doc
7. **DQR 3-axis** (US p=10000 + JP p=5000) — write review doc
8. **Docs sync**: README.md (EN AC story), README.ja.md (JP AC story), DESIGN.md (AD-59 entry extends note re medication-coupling helper), CLAUDE.md (new architecture rule: two flag dicts pattern), `modules/physiology/README.md` (helper API), TODO.md (Phase 2b done + Phase 2c backlog: aPTT/heparin + DOAC + warfarin ramp + HIT)

---

## 10. Deferred (Phase 2c+ backlog)

- **aPTT / heparin therapeutic monitoring** (UFH IV drip → aPTT 60-80s target)
- **DOAC INR micro-effect** (rivaroxaban 0.2-0.3 lift) — clinically not monitored, low realism gain
- **Warfarin linear ramp** (day 1 → 5 continuous instead of step at day 3) — pharmacologically more accurate but YAGNI vs step
- **HIT modeling** (heparin-induced thrombocytopenia: PLT < 50% baseline after day 4 of heparin)
- **Vitamin K reversal** (PCC / FFP infusion drops INR within hours — relevant for bleeding complications)
- **DOAC reversal agents** (idarucizumab for dabigatran, andexanet alfa for factor-Xa) — niche, defer
- **Warfarin-cirrhosis dose adjustment realism** (current formula shows correct over-AC; could add dose-reduction MAR record but YAGNI for synthetic EHR)
- **Activator AC-drug exclusivity** (currently independent probability draws per drug let a patient get warfarin AND apixaban simultaneously, clinically unrealistic for AF; not blocking for Phase 2b detection but worth fixing as a cleanup)
