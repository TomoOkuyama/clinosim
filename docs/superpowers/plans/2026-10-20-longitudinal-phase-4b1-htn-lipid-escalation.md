# Longitudinal Phase 4b.1 — HTN + Lipid Treatment Escalation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add two new AR(1) latents (systolic blood pressure, LDL) and ship two event-pattern escalation yamls that fire when those latents stay above threshold — HTN third-agent add (Hydrochlorothiazide) when SBP > 140, lipid high-intensity switch (Rosuvastatin) when LDL > 160, with optional Ezetimibe add-on at LDL > 190. Phase 4a's `emits_meds` + `fire_marker` infrastructure is already in place; Phase 4b.1 is pure yaml authoring plus one Layer-1 anchor override for the pre-existing `PatientProfile.systolic_bp`.

**Architecture:** Two AR(1) yamls under new subdirs (`vitals/sbp_trajectory.yaml`, `labs/ldl_trajectory.yaml`) register `sbp` + `ldl` continuous latents scoped to the matching ICD families. Two or three event yamls under `longitudinal/med/` carry the clinical escalation rules — same pattern as Phase 4a. The engine's event branch (from Phase 4a) already consumes `emits_meds` + `fire_marker` + `resolve_med_name`; no code change in `engine.py` / `event.py` / `loader.py` / `med_lookup.py`. One `clinosim/modules/population/engine.py` tweak overrides `snapshot.continuous["sbp"]` with `person.systolic_bp` after `initial_snapshot` returns, mirroring the BMI continuity pattern. `chronic_medications.yaml` gains Hydrochlorothiazide (I10), Rosuvastatin + Ezetimibe (E78) entries with `probability: 0.0` so activation sampling never picks them.

**Tech Stack:** Python 3.12, pydantic 2.x, numpy, pyyaml.

**Spec:** `docs/superpowers/specs/2026-10-20-longitudinal-state-evolution-design.md` — §4.2.1 AR(1) yaml body, §4.2.3 event yaml body, §8 Phase 3 scope (HTN/lipid treatment escalation sub-items, carved out as this plan's "Phase 4b.1").

## Global Constraints

- `pattern: ar1` latents representing lab values live under `clinosim/locale/shared/longitudinal/labs/`; vital-sign latents live under `clinosim/locale/shared/longitudinal/vitals/`. Event yamls that emit meds stay under `clinosim/locale/shared/longitudinal/med/` (Phase 4a convention).
- Every new pydantic model keeps `extra="forbid"`. Phase 4a already extended `EventSpec` with `emits_meds` + `fire_marker` + `model_post_init`; this plan ships no pydantic changes.
- `one_shot: true` dedup for med-only events uses `fire_marker` against `prev_history[*].med_additions` — exactly the Phase 4a mechanism.
- Drug-name → `HomeMedication` lookup goes through `clinosim/modules/longitudinal/med_lookup.py::resolve_med_name` — any drug the escalation yaml names must have an entry in `chronic_medications.yaml` under some ICD block (any block, since `resolve_med_name` scans every block).
- Rate modifiers use `operator: "<="` + `factor: 0.0` to gate OUT the controlled case (same as Phase 4a).
- Byte-identity across the migration is NOT required (spec §2.3 non-goal). HTN patients with sustained SBP > 140 gain Hydrochlorothiazide; dyslipidemia patients with sustained LDL > 160 gain Rosuvastatin; non-HTN / non-lipid cohorts byte-identical when they never had the triggering chronic.
- `scripts/reproduce.sh` same-seed-twice contract stays as CI gate. CI merge gate: `scripts/wait-pr-ci.sh <num>` + grep `"FAILURE"` = 0.
- No Claude attribution lines in PR body or commit messages (DCO signoff only via `git commit -s`).
- CHANGELOG + PR body entries written as a single Markdown paragraph per bullet, NOT hard-wrapped.
- Layer-1 anchor override for SBP: `PatientProfile.systolic_bp: int = 120` already exists (`clinosim/types/patient.py:90`); the longitudinal engine's `initial_snapshot` draws from the yaml `initial:` block then Layer-1 overrides, mirroring the BMI pattern (`clinosim/modules/population/engine.py` Phase 3 wiring). LDL has NO Layer-1 anchor — the yaml `initial:` draw stands.

## Review Focus

The five input classes most likely to bite a reasonable user that the task tests do not naturally exercise:

1. **HTN scope matches sub-codes** — a person carrying `I11.9` (hypertensive heart disease) must still fall in-scope for the HTN escalation yaml because `clinical_scope.requires_chronic_codes: ["I1"]` prefix-matches `I10`, `I11`, `I12`, `I13`, `I15`. If the yaml author narrows to `["I10"]` by accident, I11-I15 patients silently skip escalation. Pinned in Task 3.
2. **Lipid LDL latent initial draw does not shift cursor for non-E78 patients** — the attribute's `clinical_scope.requires_chronic_codes: ["E78"]` gate must drop LDL out of scope for non-dyslipidemia persons so the activation RNG stream stays byte-identical for them. Pinned in Task 2.
3. **Layer-1 SBP continuity after initial_snapshot** — a person entering sim with `systolic_bp=130` must have `snapshot.continuous["sbp"] == 130` at the base year, NOT the yaml `initial:` draw. If the override is wired to the wrong `person.*` attribute (e.g. `person.sbp` not `person.systolic_bp`), Layer-1 continuity breaks silently. Pinned in Task 6.
4. **Ezetimibe add-on does NOT fire when LDL ≤ 190 even if Rosuvastatin fired last year** — the ezetimibe event's `fire_marker` is distinct from the rosuvastatin event's; both must stay independent. A patient whose LDL drops to 180 after Rosuvastatin must not then pick up Ezetimibe. Pinned in Task 5.
5. **Non-HTN + non-lipid cohort stays byte-identical** — a cohort with zero I10-I15 and zero E78 patients produces byte-identical CIF before and after Phase 4b.1 (both AR(1) latents + all event yamls out of scope → zero RNG draws). Pinned in Task 7 integration.

---

## File Structure

**Create:**
- `clinosim/locale/shared/longitudinal/vitals/sbp_trajectory.yaml` — SBP AR(1) latent, I1x adults.
- `clinosim/locale/shared/longitudinal/labs/ldl_trajectory.yaml` — LDL AR(1) latent, E78 adults.
- `clinosim/locale/shared/longitudinal/med/htn_escalate_third_agent_i10.yaml` — SBP > 140 → add Hydrochlorothiazide.
- `clinosim/locale/shared/longitudinal/med/lipid_escalate_high_intensity_e78.yaml` — LDL > 160 → add Rosuvastatin.
- `clinosim/locale/shared/longitudinal/med/lipid_escalate_ezetimibe_e78.yaml` — LDL > 190 → add Ezetimibe.
- `tests/modules/longitudinal/test_sbp_ldl_latents_load.py` — new AR(1) yamls load with the expected parameters + scope.
- `tests/modules/longitudinal/test_htn_lipid_yamls_load.py` — three new event yamls load with expected `emits_meds` / `fire_marker` / `rate_modifiers`.
- `tests/modules/longitudinal/test_sbp_layer1_anchor.py` — Layer-1 `systolic_bp` overrides the yaml initial draw.
- `tests/integration/test_htn_lipid_escalation_in_cif.py` — p=200 US 5y cohort escalation correlation + non-HTN / non-lipid invariance.

**Modify:**
- `clinosim/locale/shared/chronic_medications.yaml` — under I10: `Hydrochlorothiazide` with `probability: 0.0`. Under E78: `Rosuvastatin`, `Ezetimibe` with `probability: 0.0`.
- `clinosim/modules/population/engine.py` — after `initial_snapshot` returns, set `snapshot.continuous["sbp"] = float(person.systolic_bp)` when the latent is in scope, mirroring the existing BMI override.
- `CHANGELOG.md` — one Unreleased `### Added` bullet (merge into existing block, don't create a new `### Added` — Phase 4a reviewer flagged this).

---

## Task 1: SBP AR(1) latent yaml

**Files:**
- Create: `clinosim/locale/shared/longitudinal/vitals/sbp_trajectory.yaml`
- Test: `tests/modules/longitudinal/test_sbp_ldl_latents_load.py`

**Interfaces:**
- Consumes: Phase 1 AR(1) pattern + `AttributeSpec` loader (already in `clinosim/modules/longitudinal/loader.py`).
- Produces: `AttributeSpec` under `attribute_id: sbp` loadable via `load_attribute_specs()["sbp"]` with `clinical_scope.requires_chronic_codes == ["I1"]`, `body.latent_name == "sbp"`, body phi/sigma/target per the yaml.

- [ ] **Step 1: Write failing test**

```python
# tests/modules/longitudinal/test_sbp_ldl_latents_load.py
from clinosim.modules.longitudinal.loader import load_attribute_specs


def test_sbp_latent_loads():
    load_attribute_specs.cache_clear()
    specs = load_attribute_specs()
    assert "sbp" in specs
    spec = specs["sbp"]
    assert spec.pattern == "ar1"
    assert spec.body.latent_name == "sbp"
    assert spec.body.phi == 0.80
    assert spec.body.sigma == 8.0
    assert spec.body.mean_reversion_target == 145.0
    assert spec.body.clamp == (90.0, 220.0)
    assert spec.clinical_scope.requires_chronic_codes == ["I1"]
    assert spec.clinical_scope.requires_age_band == [18, 120]
```

- [ ] **Step 2: Run test to verify failing**

Run: `pytest tests/modules/longitudinal/test_sbp_ldl_latents_load.py::test_sbp_latent_loads -v`
Expected: FAIL — `"sbp" not in specs` (yaml not yet authored).

- [ ] **Step 3: Author `clinosim/locale/shared/longitudinal/vitals/sbp_trajectory.yaml`**

Clinical calibration:
- `phi: 0.80` — annual within-individual SBP tracking. Framingham longitudinal BP tracking + ALLHAT 5y follow-up both report year-over-year correlation ≈ 0.75-0.85.
- `sigma: 8.0` mmHg — innovation SD. JNC 8 cites between-visit SBP variability ≈ 10 mmHg; subtracting measurement noise (3 mmHg) and solving stationary variance identity with phi=0.80 gives σ_innov ≈ 8.
- `mean_reversion_target: 145.0` mmHg — uncontrolled HTN cohort median (JNC 8 untreated-stage-1 ≈ 140-160; ACC-AHA 2017 raised attention to lower targets but real-world uncontrolled cohort mean sits ≈ 145).
- `clamp: [90.0, 220.0]` — SBP < 90 is hypotension, > 220 is hypertensive emergency territory.
- `clinical_scope.requires_chronic_codes: ["I1"]` — prefix matches I10, I11, I12, I13, I15 per Review Focus #1.

```yaml
attribute_id: sbp
pattern: ar1
depends_on: []
clinical_scope:
  requires_chronic_codes: ["I1"]
  requires_age_band: [18, 120]

latent_name: sbp
ar1:
  phi: 0.80
  sigma: 8.0
  mean_reversion_target: 145.0
clamp: [90.0, 220.0]
initial:
  mu: 4.976   # exp(4.976) ≈ 145 (dummy — overridden by Layer-1 in population/engine.py)
  sigma: 0.08
narrative_label:
  en: "Systolic BP trajectory"
  ja: "収縮期血圧 推移"
source:
  - "Whelton PK et al. 2017 ACC/AHA Hypertension Guideline. JACC 2018;71:e127."
  - "James PA et al. JNC 8 report. JAMA 2014;311:507."
  - "Framingham Heart Study longitudinal BP tracking + ALLHAT 5y follow-up (ALLHAT-LLT Officers, JAMA 2002;288:2998)."
```

Also pin Review Focus #2 (LDL out-of-scope for non-E78) by adding a scope-check test now (both latents are symmetric):

```python
def test_sbp_latent_out_of_scope_for_non_htn_person():
    """Review Focus #1 / #2 analog: a non-HTN person's longitudinal
    history must NOT carry an 'sbp' key — the scope gate drops the
    attribute cleanly before any RNG draw."""
    from clinosim.modules.longitudinal import engine as le
    from clinosim.types.population import PersonRecord
    from datetime import date
    import numpy as np
    load_attribute_specs.cache_clear()
    p = PersonRecord(
        person_id="PX", household_id="HX", age=45, sex="M",
        date_of_birth=date(1980, 1, 1), chronic_conditions=["E11.9"],
    )
    snap = le.initial_snapshot(p, 2024, np.random.default_rng(0))
    assert "sbp" not in snap.continuous
```

- [ ] **Step 4: Run tests to verify passing**

Run: `pytest tests/modules/longitudinal/test_sbp_ldl_latents_load.py -v`
Expected: 2/2 pass.

- [ ] **Step 5: Commit**

```bash
git add clinosim/locale/shared/longitudinal/vitals/ tests/modules/longitudinal/test_sbp_ldl_latents_load.py
git commit -s -m "feat(longitudinal): add SBP AR(1) latent for I1x adults"
```

---

## Task 2: LDL AR(1) latent yaml

**Files:**
- Create: `clinosim/locale/shared/longitudinal/labs/ldl_trajectory.yaml`
- Test: extend `tests/modules/longitudinal/test_sbp_ldl_latents_load.py`

**Interfaces:**
- Produces: `AttributeSpec` under `attribute_id: ldl`, `clinical_scope.requires_chronic_codes: ["E78"]`, body phi/sigma/target per yaml.

- [ ] **Step 1: Append failing test**

```python
def test_ldl_latent_loads():
    load_attribute_specs.cache_clear()
    specs = load_attribute_specs()
    assert "ldl" in specs
    spec = specs["ldl"]
    assert spec.pattern == "ar1"
    assert spec.body.latent_name == "ldl"
    assert spec.body.phi == 0.80
    assert spec.body.sigma == 12.0
    assert spec.body.mean_reversion_target == 165.0
    assert spec.body.clamp == (60.0, 300.0)
    assert spec.clinical_scope.requires_chronic_codes == ["E78"]
    assert spec.clinical_scope.requires_age_band == [18, 120]


def test_ldl_latent_out_of_scope_for_non_dyslipidemia_person():
    """Review Focus #2: a non-E78 person's longitudinal history must
    NOT carry an 'ldl' key — scope gate drops the attribute, zero RNG
    draw, non-E78 cohort stays byte-identical."""
    from clinosim.modules.longitudinal import engine as le
    from clinosim.types.population import PersonRecord
    from datetime import date
    import numpy as np
    load_attribute_specs.cache_clear()
    p = PersonRecord(
        person_id="PX", household_id="HX", age=45, sex="M",
        date_of_birth=date(1980, 1, 1), chronic_conditions=["E11.9"],
    )
    snap = le.initial_snapshot(p, 2024, np.random.default_rng(0))
    assert "ldl" not in snap.continuous
```

- [ ] **Step 2: Verify failing**

Run: `pytest tests/modules/longitudinal/test_sbp_ldl_latents_load.py::test_ldl_latent_loads -v`
Expected: FAIL — `"ldl" not in specs`.

- [ ] **Step 3: Author `clinosim/locale/shared/longitudinal/labs/ldl_trajectory.yaml`**

Clinical calibration:
- `phi: 0.80` — statin response plateau. STELLAR trial comparator data shows within-individual LDL year-over-year correlation ≈ 0.75-0.85 on stable statin.
- `sigma: 12.0` mg/dL — innovation SD. ACC-AHA 2018 cites within-individual LDL biological variability ≈ 10-15 mg/dL; 12 is the midpoint.
- `mean_reversion_target: 165.0` mg/dL — uncontrolled dyslipidemia cohort median under single-moderate-intensity statin (Atorvastatin 10mg typically pulls LDL to ≈ 110-170 depending on baseline; mid-range of uncontrolled trajectory).
- `clamp: [60.0, 300.0]` — LDL < 60 is below physiologic utility; > 300 is familial-hypercholesterolemia territory beyond this subsystem's scope.

```yaml
attribute_id: ldl
pattern: ar1
depends_on: []
clinical_scope:
  requires_chronic_codes: ["E78"]
  requires_age_band: [18, 120]

latent_name: ldl
ar1:
  phi: 0.80
  sigma: 12.0
  mean_reversion_target: 165.0
clamp: [60.0, 300.0]
initial:
  mu: 5.10    # exp(5.10) ≈ 164 — uncontrolled dyslipidemia entry median
  sigma: 0.12
narrative_label:
  en: "LDL trajectory"
  ja: "LDL コレステロール 推移"
source:
  - "Grundy SM et al. 2018 ACC/AHA Cholesterol Guideline. Circulation 2019;139:e1082."
  - "STELLAR Trial — Jones PH et al. Am J Cardiol 2003;92:152 (Rosuvastatin vs Atorvastatin LDL response plateau)."
  - "ACC-AHA 2018 Cholesterol Guideline supplementary data on within-individual LDL biological variability."
```

- [ ] **Step 4: Verify tests pass**

Run: `pytest tests/modules/longitudinal/test_sbp_ldl_latents_load.py -v`
Expected: 4/4 pass.

- [ ] **Step 5: Commit**

```bash
git add clinosim/locale/shared/longitudinal/labs/ tests/modules/longitudinal/test_sbp_ldl_latents_load.py
git commit -s -m "feat(longitudinal): add LDL AR(1) latent for E78 adults"
```

---

## Task 3: HTN third-agent escalation event yaml

**Files:**
- Create: `clinosim/locale/shared/longitudinal/med/htn_escalate_third_agent_i10.yaml`
- Test: `tests/modules/longitudinal/test_htn_lipid_yamls_load.py`

**Interfaces:**
- Consumes: Phase 4a `EventSpec` (`emits_meds`, `fire_marker`); Task 1 `sbp` latent.
- Produces: `AttributeSpec` under `attribute_id: htn_escalate_third_agent_i10`, `depends_on: [sbp]`, `emits_meds: ["Hydrochlorothiazide"]`, `fire_marker: "htn_escalate_third_agent_i10"`.

- [ ] **Step 1: Write failing test**

```python
# tests/modules/longitudinal/test_htn_lipid_yamls_load.py
from clinosim.modules.longitudinal.loader import load_attribute_specs


def test_htn_escalation_yaml_loads():
    load_attribute_specs.cache_clear()
    specs = load_attribute_specs()
    assert "htn_escalate_third_agent_i10" in specs
    spec = specs["htn_escalate_third_agent_i10"]
    assert spec.pattern == "event"
    assert spec.depends_on == ["sbp"]
    body = spec.body
    assert body.emits_icd == ""
    assert body.emits_meds == ["Hydrochlorothiazide"]
    assert body.fire_marker == "htn_escalate_third_agent_i10"
    assert body.base_annual_rate == 0.55
    assert body.one_shot is True
    assert spec.clinical_scope.requires_chronic_codes == ["I1"]


def test_htn_escalation_fires_at_sbp_above_140():
    """Review Focus #1 pin via step() — rate modifier gates OUT at SBP ≤ 140."""
    import numpy as np
    from clinosim.modules.longitudinal.patterns.event import step
    load_attribute_specs.cache_clear()
    spec = load_attribute_specs()["htn_escalate_third_agent_i10"].body
    rng = np.random.default_rng(0)
    # Controlled (SBP=135) — must NOT fire.
    r = step([], [], rng, spec, context={"continuous": {"sbp": 135.0}})
    assert not r.fired
    # Uncontrolled (SBP=145) — fires at base_annual_rate 0.55.
    rng2 = np.random.default_rng(0)
    r = step([], [], rng2, spec, context={"continuous": {"sbp": 145.0}})
    assert r.fired
    assert r.med_additions == ["Hydrochlorothiazide"]
```

- [ ] **Step 2: Verify failing**

Run: `pytest tests/modules/longitudinal/test_htn_lipid_yamls_load.py -v`
Expected: FAIL — `"htn_escalate_third_agent_i10" not in specs`.

- [ ] **Step 3: Author `clinosim/locale/shared/longitudinal/med/htn_escalate_third_agent_i10.yaml`**

Clinical calibration: ACC-AHA 2017 Hypertension Guideline (Whelton et al, JACC 2018) + JNC 8 (James et al, JAMA 2014). Third-agent add-on when SBP > 140 on dual therapy — thiazide diuretic is first-line third agent per both guidelines when the patient is already on a CCB + ARB (POP-000246's regimen: Amlodipine + Candesartan). `base_annual_rate: 0.55` reflects real-world uptake of a third agent within 1y of sustained uncontrolled BP (ALLHAT follow-up + NHANES BP control gap literature).

```yaml
# HTN third-agent treatment escalation — event pattern.
#
# Phase 4b.1 of the longitudinal state-evolution subsystem (Issue #1697).
# Base rate 55 %/yr under uncontrolled SBP (> 140 mmHg), gated OUT when
# SBP ≤ 140 via a factor-zero modifier.
#
# Clinical basis: ACC-AHA 2017 Hypertension Guideline + JNC 8. Thiazide
# diuretic is the preferred third agent on top of a CCB + ARB/ACEi
# regimen when BP remains uncontrolled. Phase 4b.1 emits
# Hydrochlorothiazide as the representative thiazide; chlorthalidone /
# indapamide alternatives are a Phase 4b.2 locale variant.

attribute_id: htn_escalate_third_agent_i10
pattern: event
depends_on: [sbp]
clinical_scope:
  requires_chronic_codes: ["I1"]
  requires_age_band: [18, 120]

event_name: htn_escalate_third_agent_i10
emits_icd: ""
emits_meds: ["Hydrochlorothiazide"]
fire_marker: htn_escalate_third_agent_i10
base_annual_rate: 0.55
rate_modifiers:
  - when: {attribute: sbp, operator: "<=", value: 140.0}
    factor: 0.0
one_shot: true
narrative_label:
  en: "HTN third-agent escalation"
  ja: "高血圧 第三薬剤 追加"
source:
  - "Whelton PK et al. 2017 ACC/AHA Hypertension Guideline. JACC 2018;71:e127."
  - "James PA et al. JNC 8 report. JAMA 2014;311:507."
  - "ALLHAT follow-up — real-world uptake of third antihypertensive agent at sustained SBP > 140."
```

- [ ] **Step 4: Verify tests pass**

Run: `pytest tests/modules/longitudinal/test_htn_lipid_yamls_load.py -v`
Expected: 2/2 pass.

- [ ] **Step 5: Commit**

```bash
git add clinosim/locale/shared/longitudinal/med/htn_escalate_third_agent_i10.yaml tests/modules/longitudinal/test_htn_lipid_yamls_load.py
git commit -s -m "feat(longitudinal): add HTN third-agent escalation yaml (SBP > 140 → HCTZ)"
```

---

## Task 4: Lipid high-intensity escalation event yaml

**Files:**
- Create: `clinosim/locale/shared/longitudinal/med/lipid_escalate_high_intensity_e78.yaml`
- Test: extend `tests/modules/longitudinal/test_htn_lipid_yamls_load.py`

**Interfaces:**
- Produces: `AttributeSpec` under `attribute_id: lipid_escalate_high_intensity_e78`, `depends_on: [ldl]`, `emits_meds: ["Rosuvastatin"]`, `fire_marker: "lipid_escalate_high_intensity_e78"`.

- [ ] **Step 1: Append failing test**

```python
def test_lipid_high_intensity_escalation_yaml_loads():
    load_attribute_specs.cache_clear()
    specs = load_attribute_specs()
    assert "lipid_escalate_high_intensity_e78" in specs
    spec = specs["lipid_escalate_high_intensity_e78"]
    assert spec.pattern == "event"
    assert spec.depends_on == ["ldl"]
    body = spec.body
    assert body.emits_icd == ""
    assert body.emits_meds == ["Rosuvastatin"]
    assert body.fire_marker == "lipid_escalate_high_intensity_e78"
    assert body.base_annual_rate == 0.40
    assert spec.clinical_scope.requires_chronic_codes == ["E78"]


def test_lipid_high_intensity_fires_at_ldl_above_160():
    import numpy as np
    from clinosim.modules.longitudinal.patterns.event import step
    load_attribute_specs.cache_clear()
    spec = load_attribute_specs()["lipid_escalate_high_intensity_e78"].body
    rng = np.random.default_rng(0)
    r = step([], [], rng, spec, context={"continuous": {"ldl": 155.0}})
    assert not r.fired
    rng2 = np.random.default_rng(0)
    r = step([], [], rng2, spec, context={"continuous": {"ldl": 175.0}})
    assert r.fired
    assert r.med_additions == ["Rosuvastatin"]
```

- [ ] **Step 2: Verify failing**

Run: `pytest tests/modules/longitudinal/test_htn_lipid_yamls_load.py::test_lipid_high_intensity_escalation_yaml_loads -v`
Expected: FAIL — yaml not yet authored.

- [ ] **Step 3: Author `clinosim/locale/shared/longitudinal/med/lipid_escalate_high_intensity_e78.yaml`**

Clinical calibration: ACC-AHA 2018 Cholesterol Guideline (Grundy et al, Circulation 2019). When LDL remains > 160 on moderate-intensity statin (Atorvastatin 10mg = moderate), switch to high-intensity statin (Rosuvastatin ≥ 20mg or Atorvastatin ≥ 40mg) before considering non-statin add-ons. `base_annual_rate: 0.40` — real-world uptake is slower than guideline because of statin intolerance and clinician inertia (NHANES 2017-2020 LDL control gap literature).

```yaml
# Lipid high-intensity statin switch — event pattern.
#
# Phase 4b.1 of the longitudinal state-evolution subsystem (Issue #1697).
# Base rate 40 %/yr under uncontrolled LDL (> 160 mg/dL), gated OUT when
# LDL ≤ 160 via a factor-zero modifier.
#
# Clinical basis: ACC-AHA 2018 Cholesterol Guideline, Section 4.4.1
# intensification pathway. Rosuvastatin 20mg is the representative
# high-intensity statin (equivalent to Atorvastatin 40mg).

attribute_id: lipid_escalate_high_intensity_e78
pattern: event
depends_on: [ldl]
clinical_scope:
  requires_chronic_codes: ["E78"]
  requires_age_band: [18, 120]

event_name: lipid_escalate_high_intensity_e78
emits_icd: ""
emits_meds: ["Rosuvastatin"]
fire_marker: lipid_escalate_high_intensity_e78
base_annual_rate: 0.40
rate_modifiers:
  - when: {attribute: ldl, operator: "<=", value: 160.0}
    factor: 0.0
one_shot: true
narrative_label:
  en: "Lipid high-intensity statin switch"
  ja: "脂質異常症 高強度スタチン 切替"
source:
  - "Grundy SM et al. 2018 ACC/AHA Cholesterol Guideline. Circulation 2019;139:e1082."
  - "STELLAR Trial — Jones PH et al. Am J Cardiol 2003;92:152 (Rosuvastatin equivalence tables)."
```

- [ ] **Step 4: Verify tests pass**

Run: `pytest tests/modules/longitudinal/test_htn_lipid_yamls_load.py -v`
Expected: 4/4 pass.

- [ ] **Step 5: Commit**

```bash
git add clinosim/locale/shared/longitudinal/med/lipid_escalate_high_intensity_e78.yaml tests/modules/longitudinal/test_htn_lipid_yamls_load.py
git commit -s -m "feat(longitudinal): add lipid high-intensity statin escalation yaml (LDL > 160 → Rosuvastatin)"
```

---

## Task 5: Lipid Ezetimibe add-on event yaml

**Files:**
- Create: `clinosim/locale/shared/longitudinal/med/lipid_escalate_ezetimibe_e78.yaml`
- Test: extend `tests/modules/longitudinal/test_htn_lipid_yamls_load.py`

**Interfaces:**
- Produces: `AttributeSpec` under `attribute_id: lipid_escalate_ezetimibe_e78`, `depends_on: [ldl]`, `emits_meds: ["Ezetimibe"]`, `fire_marker: "lipid_escalate_ezetimibe_e78"`. Independent of Task 4 (no `depends_on` on the high-intensity yaml) — a patient at sustained LDL > 190 accumulates both Rosuvastatin and Ezetimibe.

- [ ] **Step 1: Append failing test**

```python
def test_lipid_ezetimibe_escalation_yaml_loads():
    load_attribute_specs.cache_clear()
    specs = load_attribute_specs()
    assert "lipid_escalate_ezetimibe_e78" in specs
    spec = specs["lipid_escalate_ezetimibe_e78"]
    assert spec.pattern == "event"
    assert spec.depends_on == ["ldl"]
    body = spec.body
    assert body.emits_meds == ["Ezetimibe"]
    assert body.fire_marker == "lipid_escalate_ezetimibe_e78"
    assert body.base_annual_rate == 0.30


def test_lipid_ezetimibe_independent_of_high_intensity():
    """Review Focus #4: Ezetimibe yaml does NOT depend_on
    lipid_escalate_high_intensity_e78 — a patient at sustained LDL > 190
    accumulates both agents independently each sim window."""
    load_attribute_specs.cache_clear()
    specs = load_attribute_specs()
    ezet_deps = specs["lipid_escalate_ezetimibe_e78"].depends_on
    assert "lipid_escalate_high_intensity_e78" not in ezet_deps
    assert "ldl" in ezet_deps


def test_lipid_ezetimibe_does_not_fire_at_ldl_180():
    """Review Focus #4 pin: a patient at LDL=180 (above the > 160
    high-intensity threshold but below > 190 ezetimibe threshold)
    must NOT fire the ezetimibe event."""
    import numpy as np
    from clinosim.modules.longitudinal.patterns.event import step
    load_attribute_specs.cache_clear()
    spec = load_attribute_specs()["lipid_escalate_ezetimibe_e78"].body
    rng = np.random.default_rng(0)
    r = step([], [], rng, spec, context={"continuous": {"ldl": 180.0}})
    assert not r.fired
```

- [ ] **Step 2: Verify failing**

Run: `pytest tests/modules/longitudinal/test_htn_lipid_yamls_load.py -v`
Expected: 3 new FAILs.

- [ ] **Step 3: Author `clinosim/locale/shared/longitudinal/med/lipid_escalate_ezetimibe_e78.yaml`**

Clinical calibration: ACC-AHA 2018 — Ezetimibe is first-line non-statin add-on when LDL remains above goal on maximally tolerated statin (IMPROVE-IT trial). PCSK9i (Alirocumab / Evolocumab) is the next step but gated behind FOURIER-type criteria; Phase 4b.1 stops at Ezetimibe. Threshold 190 mg/dL = ACC-AHA severe-hypercholesterolemia cutoff.

```yaml
# Lipid Ezetimibe add-on — event pattern.
#
# Phase 4b.1 of the longitudinal state-evolution subsystem (Issue #1697).
# Base rate 30 %/yr under severe uncontrolled LDL (> 190 mg/dL), gated
# OUT when LDL ≤ 190 via a factor-zero modifier. Independent of the
# high-intensity statin escalation yaml — a patient at sustained
# LDL > 190 accumulates both agents across sim years.
#
# Clinical basis: ACC-AHA 2018 Cholesterol Guideline (Grundy et al,
# Circulation 2019) + IMPROVE-IT trial (Cannon et al, NEJM 2015).

attribute_id: lipid_escalate_ezetimibe_e78
pattern: event
depends_on: [ldl]
clinical_scope:
  requires_chronic_codes: ["E78"]
  requires_age_band: [18, 120]

event_name: lipid_escalate_ezetimibe_e78
emits_icd: ""
emits_meds: ["Ezetimibe"]
fire_marker: lipid_escalate_ezetimibe_e78
base_annual_rate: 0.30
rate_modifiers:
  - when: {attribute: ldl, operator: "<=", value: 190.0}
    factor: 0.0
one_shot: true
narrative_label:
  en: "Lipid Ezetimibe add-on"
  ja: "脂質異常症 エゼチミブ 追加"
source:
  - "Grundy SM et al. 2018 ACC/AHA Cholesterol Guideline. Circulation 2019;139:e1082."
  - "Cannon CP et al. IMPROVE-IT. NEJM 2015;372:2387 (Ezetimibe on statin, cardiovascular outcomes)."
```

- [ ] **Step 4: Verify tests pass**

Run: `pytest tests/modules/longitudinal/test_htn_lipid_yamls_load.py -v`
Expected: 7/7 pass across Tasks 3-5.

- [ ] **Step 5: Commit**

```bash
git add clinosim/locale/shared/longitudinal/med/lipid_escalate_ezetimibe_e78.yaml tests/modules/longitudinal/test_htn_lipid_yamls_load.py
git commit -s -m "feat(longitudinal): add lipid Ezetimibe add-on yaml (LDL > 190 → Ezetimibe)"
```

---

## Task 6: Layer-1 anchor override for SBP + chronic_medications.yaml additions

**Files:**
- Modify: `clinosim/modules/population/engine.py` — after `initial_snapshot` returns, override `snapshot.continuous["sbp"]` with `float(person.systolic_bp)` when `"sbp"` is in scope.
- Modify: `clinosim/locale/shared/chronic_medications.yaml` — add Hydrochlorothiazide under I10, Rosuvastatin + Ezetimibe under E78, all with `probability: 0.0`.
- Test: `tests/modules/longitudinal/test_sbp_layer1_anchor.py` + extend `tests/modules/longitudinal/test_med_lookup.py`.

**Interfaces:**
- Consumes: Task 1 SBP latent; Phase 4a `resolve_med_name` (unchanged).
- Produces: a person entering sim with `systolic_bp=130` has `snapshot.continuous["sbp"] == 130.0` at the base year (not the yaml `initial:` draw). `resolve_med_name("Hydrochlorothiazide")` / `"Rosuvastatin"` / `"Ezetimibe"` return full metadata.

- [ ] **Step 1: Write failing test**

```python
# tests/modules/longitudinal/test_sbp_layer1_anchor.py
"""Phase 4b.1 — Layer-1 systolic_bp overrides the yaml initial draw.

Mirrors tests/integration/test_bmi_drift_in_cif.py's Layer-1 anchor
test for BMI. The sim-start snapshot's sbp latent must equal the
person's Layer-1 systolic_bp, not the yaml initial lognormal draw.
"""

from datetime import date
import numpy as np

from clinosim.modules.longitudinal.loader import load_attribute_specs
from clinosim.modules.population.engine import generate_population


def test_layer1_systolic_bp_overrides_sbp_initial_draw():
    load_attribute_specs.cache_clear()
    registry = generate_population(
        size=50, country="US", rng=np.random.default_rng(42), base_year=2024,
    )
    found_htn = False
    for person in registry.persons.values():
        if not any(c.startswith("I1") for c in person.chronic_conditions):
            continue
        if person.age < 18:
            continue
        found_htn = True
        snap = person.longitudinal_history[0]
        assert "sbp" in snap.continuous
        # Layer-1 anchor override: continuous['sbp'] must equal person.systolic_bp.
        assert abs(snap.continuous["sbp"] - float(person.systolic_bp)) < 0.01
    assert found_htn, "sample has no HTN adults — bump size or seed"
```

```python
# tests/modules/longitudinal/test_med_lookup.py — appended
def test_resolve_hydrochlorothiazide_full_metadata():
    from clinosim.modules.longitudinal.med_lookup import resolve_med_name
    hm = resolve_med_name("Hydrochlorothiazide")
    assert hm.drug_name == "Hydrochlorothiazide"
    assert hm.route == "PO"
    assert hm.frequency == "daily"
    assert hm.dose == "25mg"


def test_resolve_rosuvastatin_full_metadata():
    from clinosim.modules.longitudinal.med_lookup import resolve_med_name
    hm = resolve_med_name("Rosuvastatin")
    assert hm.drug_name == "Rosuvastatin"
    assert hm.route == "PO"
    assert hm.frequency == "daily"
    assert hm.dose == "20mg"


def test_resolve_ezetimibe_full_metadata():
    from clinosim.modules.longitudinal.med_lookup import resolve_med_name
    hm = resolve_med_name("Ezetimibe")
    assert hm.drug_name == "Ezetimibe"
    assert hm.route == "PO"
    assert hm.frequency == "daily"
    assert hm.dose == "10mg"
```

- [ ] **Step 2: Verify failing**

Run: `pytest tests/modules/longitudinal/test_sbp_layer1_anchor.py tests/modules/longitudinal/test_med_lookup.py -v`
Expected: anchor test FAILS (yaml initial draw ≠ Layer-1 systolic_bp); the three lookup tests FAIL on dose (`"" != "25mg"` etc.).

- [ ] **Step 3: Wire Layer-1 SBP override in `clinosim/modules/population/engine.py`**

Find the Phase 3 BMI override block (search for `snapshot.continuous["bmi"]` after `initial_snapshot` returns in `generate_population`). Add an analogous line:

```python
# Phase 4b.1 — Layer-1 systolic_bp anchor override. Same pattern as BMI.
if "sbp" in snap.continuous:
    snap.continuous["sbp"] = float(person.systolic_bp)
```

- [ ] **Step 4: Extend `clinosim/locale/shared/chronic_medications.yaml`**

Under `I10:` (Hypertension), add after the existing medications list:

```yaml
    # Phase 4b.1 (#1697) — longitudinal escalation drug. probability: 0.0
    # keeps activation sampling from picking it; only the longitudinal
    # engine's htn_escalate_third_agent_i10 event adds it via resolve_med_name.
    - {drug: "Hydrochlorothiazide", drug_ja: "ヒドロクロロチアジド", dose: "25mg", drug_class: "thiazide", route: "PO", frequency: "daily", probability: 0.0}
```

Under `E78:` (Dyslipidemia), add after the existing medications list:

```yaml
    # Phase 4b.1 (#1697) — longitudinal escalation drugs. probability: 0.0
    # keeps activation sampling from picking them; only the longitudinal
    # engine's lipid_escalate_* event yamls add them via resolve_med_name.
    - {drug: "Rosuvastatin", drug_ja: "ロスバスタチン", dose: "20mg", drug_class: "high_intensity_statin", route: "PO", frequency: "daily", probability: 0.0}
    - {drug: "Ezetimibe", drug_ja: "エゼチミブ", dose: "10mg", drug_class: "cholesterol_absorption_inhibitor", route: "PO", frequency: "daily", probability: 0.0}
```

- [ ] **Step 5: Verify tests pass**

Run: `pytest tests/modules/longitudinal/test_sbp_layer1_anchor.py tests/modules/longitudinal/test_med_lookup.py -v`
Expected: all pass (anchor + 3 new lookups + original Phase 4a lookups still green).

- [ ] **Step 6: Commit**

```bash
git add clinosim/modules/population/engine.py clinosim/locale/shared/chronic_medications.yaml tests/modules/longitudinal/test_sbp_layer1_anchor.py tests/modules/longitudinal/test_med_lookup.py
git commit -s -m "feat(longitudinal): wire Layer-1 SBP anchor + add HCTZ/Rosuvastatin/Ezetimibe to chronic_medications.yaml"
```

---

## Task 7: Integration — HTN + lipid escalation in CIF; non-affected cohort invariance

**Files:**
- Create: `tests/integration/test_htn_lipid_escalation_in_cif.py`

**Interfaces:**
- Consumes: full longitudinal engine + Tasks 1-6.
- Produces: cohort-level check — HTN patients with sustained SBP > 140 accumulate Hydrochlorothiazide; dyslipidemia patients with sustained LDL > 160 accumulate Rosuvastatin; patients with sustained LDL > 190 accumulate Ezetimibe; non-HTN non-lipid patients produce no escalation drugs (clinical_scope invariance proof).

- [ ] **Step 1: Write failing cohort test**

```python
# tests/integration/test_htn_lipid_escalation_in_cif.py
"""Phase 4b.1 — HTN + lipid escalation cohort integration.

Mirrors tests/integration/test_dm_escalation_in_cif.py.
"""

from __future__ import annotations

import numpy as np
import pytest

from clinosim.modules.longitudinal.loader import load_attribute_specs
from clinosim.modules.population.aging import advance_population
from clinosim.modules.population.engine import generate_population


@pytest.fixture(autouse=True)
def _clear_loader() -> None:
    load_attribute_specs.cache_clear()
    yield
    load_attribute_specs.cache_clear()


@pytest.mark.integration
def test_htn_patients_may_escalate_to_third_agent_across_5y() -> None:
    registry = generate_population(size=200, country="US", rng=np.random.default_rng(42), base_year=2024)
    for year in (2025, 2026, 2027, 2028):
        advance_population(registry, year=year, locale="US")
    htn_adults = 0
    htn_adults_with_hctz = 0
    for person in registry.persons.values():
        if person.age < 18:
            continue
        if not any(c.startswith("I1") for c in person.chronic_conditions):
            continue
        htn_adults += 1
        if any(hm.drug_name == "Hydrochlorothiazide" for hm in person.current_medications):
            htn_adults_with_hctz += 1
    assert htn_adults > 0, "sample has no HTN adults — bump size or seed"
    assert htn_adults_with_hctz >= 1, (
        f"expected >= 1 HTN adult escalated to Hydrochlorothiazide in p=200 5y, "
        f"got {htn_adults_with_hctz} of {htn_adults} HTN adults"
    )


@pytest.mark.integration
def test_lipid_patients_may_escalate_to_high_intensity_across_5y() -> None:
    registry = generate_population(size=200, country="US", rng=np.random.default_rng(42), base_year=2024)
    for year in (2025, 2026, 2027, 2028):
        advance_population(registry, year=year, locale="US")
    lipid_adults = 0
    lipid_adults_with_rosuvastatin = 0
    for person in registry.persons.values():
        if person.age < 18:
            continue
        if not any(c.startswith("E78") for c in person.chronic_conditions):
            continue
        lipid_adults += 1
        if any(hm.drug_name == "Rosuvastatin" for hm in person.current_medications):
            lipid_adults_with_rosuvastatin += 1
    assert lipid_adults > 0, "sample has no dyslipidemia adults — bump size or seed"
    assert lipid_adults_with_rosuvastatin >= 1, (
        f"expected >= 1 dyslipidemia adult escalated to Rosuvastatin in p=200 5y, "
        f"got {lipid_adults_with_rosuvastatin} of {lipid_adults} dyslipidemia adults"
    )


@pytest.mark.integration
def test_non_htn_non_lipid_patients_never_gain_escalation_drugs() -> None:
    """Review Focus #5: clinical_scope invariance — a patient without I1x
    and without E78 never picks up any of the three new escalation drugs."""
    registry = generate_population(size=200, country="US", rng=np.random.default_rng(42), base_year=2024)
    for year in (2025, 2026, 2027, 2028):
        advance_population(registry, year=year, locale="US")
    forbidden = {"Hydrochlorothiazide", "Rosuvastatin", "Ezetimibe"}
    for person in registry.persons.values():
        if person.age < 18:
            continue
        has_htn = any(c.startswith("I1") for c in person.chronic_conditions)
        has_lipid = any(c.startswith("E78") for c in person.chronic_conditions)
        if has_htn or has_lipid:
            continue
        on_forbidden = [hm.drug_name for hm in person.current_medications if hm.drug_name in forbidden]
        assert not on_forbidden, (
            f"non-HTN non-lipid person {person.person_id} picked up {on_forbidden} — "
            f"clinical_scope gate broken"
        )


@pytest.mark.integration
def test_htn_and_lipid_escalation_fire_markers_dedup_across_years() -> None:
    """Fire_marker dedup end-to-end for both new yamls — each marker
    appears at most once in a person's longitudinal_history."""
    registry = generate_population(size=200, country="US", rng=np.random.default_rng(42), base_year=2024)
    for year in (2025, 2026, 2027, 2028):
        advance_population(registry, year=year, locale="US")
    for person in registry.persons.values():
        if not person.longitudinal_history:
            continue
        for marker in (
            "htn_escalate_third_agent_i10",
            "lipid_escalate_high_intensity_e78",
            "lipid_escalate_ezetimibe_e78",
        ):
            fires = sum(1 for snap in person.longitudinal_history if marker in snap.med_additions)
            assert fires <= 1, f"{person.person_id} fired {marker} {fires} times"
```

- [ ] **Step 2: Run integration tests**

Run: `pytest tests/integration/test_htn_lipid_escalation_in_cif.py -v`
Expected: 4/4 pass.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_htn_lipid_escalation_in_cif.py
git commit -s -m "test(longitudinal): HTN + lipid escalation CIF integration + non-affected invariance"
```

---

## Task 8: CHANGELOG + reproduce.sh + full regression

**Files:**
- Modify: `CHANGELOG.md` — append to the EXISTING `### Added` block under `## [Unreleased]` (do NOT create a new `### Added` heading; Phase 4a reviewer flagged this).

**Interfaces:**
- Consumes: Tasks 1-7.
- Produces: docs complete; CI gates green.

- [ ] **Step 1: Append CHANGELOG bullet to existing Unreleased ### Added block**

Single physical line, NOT hard-wrapped:

```
- **HTN patients with SBP > 140 escalate to a third antihypertensive (Hydrochlorothiazide), and dyslipidemia patients with LDL > 160 escalate to high-intensity Rosuvastatin (plus Ezetimibe at LDL > 190), instead of staying on frozen single/dual therapy for 5y** (Issue #1697 — Phase 4b.1 of the longitudinal state-evolution subsystem; follow-on to Phase 4a DM escalation). Two new AR(1) latents land: `clinosim/locale/shared/longitudinal/vitals/sbp_trajectory.yaml` (SBP, I1x adults, phi=0.80 σ=8 target=145 clamp=[90,220], Layer-1 anchor from `PatientProfile.systolic_bp`) and `clinosim/locale/shared/longitudinal/labs/ldl_trajectory.yaml` (LDL, E78 adults, phi=0.80 σ=12 target=165 clamp=[60,300]). Three new event yamls under `clinosim/locale/shared/longitudinal/med/`: `htn_escalate_third_agent_i10.yaml` (SBP > 140 → Hydrochlorothiazide, base 0.55/yr), `lipid_escalate_high_intensity_e78.yaml` (LDL > 160 → Rosuvastatin, base 0.40/yr), `lipid_escalate_ezetimibe_e78.yaml` (LDL > 190 → Ezetimibe, base 0.30/yr, independent of the high-intensity switch). Three new entries in `clinosim/locale/shared/chronic_medications.yaml` (Hydrochlorothiazide under I10, Rosuvastatin + Ezetimibe under E78) with `probability: 0.0` so activation sampling never picks them — only the longitudinal escalation path adds them. Clinical basis: ACC-AHA 2017 Hypertension Guideline + JNC 8; ACC-AHA 2018 Cholesterol Guideline + IMPROVE-IT. MINOR-track CIF change for HTN/lipid patients only; non-affected cohorts byte-identical.
```

- [ ] **Step 2: Full project test suite**

Run: `pytest -x tests/modules/longitudinal/ tests/integration/test_htn_lipid_escalation_in_cif.py tests/integration/test_dm_escalation_in_cif.py tests/integration/test_longitudinal_engine_integration.py tests/integration/test_bmi_drift_in_cif.py tests/unit/docs/`
Expected: all green.

- [ ] **Step 3: reproduce.sh gate**

Run: `scripts/reproduce.sh`
Expected: pass (same seed twice → byte-identical).

- [ ] **Step 4: Commit**

```bash
git add CHANGELOG.md
git commit -s -m "docs(changelog): Phase 4b.1 HTN + lipid treatment escalation"
```

---

## Self-review notes (plan author)

**1. Spec coverage.** Spec §8 Phase 3 lists `htn_treatment_escalation.yaml` and `lipid_treatment_escalation.yaml` under the "Phase 3 — event pattern + ..." bullet; Phase 4a shipped only the DM arm. Phase 4b.1 ships the HTN + lipid arms, closing the Phase 3 treatment-escalation surface. The `_annual_chronic_onset` adult-chronic migration (also under Phase 3 in the spec) remains deferred — Phase 4b.2.

**2. Step scan.** Each step produces exactly one artifact: a failing test, a run+expected comparison, a yaml authoring step with calibration constants from the spec/clinical anchor, or a commit. The one place a code body appears (Task 6 Step 3 Layer-1 override) names the exact field (`snapshot.continuous["sbp"]`) + exact source (`float(person.systolic_bp)`) + exact position ("after `initial_snapshot` returns") — the implementer writes nothing novel.

**3. Type consistency.** `sbp` and `ldl` are latent_names used in: Task 1/2 AR(1) yamls, Task 3/4/5 event yaml `rate_modifiers[].when.attribute` + `depends_on` lists, Task 6 Layer-1 override, Task 7 integration test cohort filters. Drug names (`Hydrochlorothiazide`, `Rosuvastatin`, `Ezetimibe`) appear verbatim in: Task 3-5 yaml `emits_meds`, Task 6 chronic_medications.yaml + test_med_lookup assertions, Task 7 integration cohort scan. Fire-marker strings match attribute_ids 1:1 (`htn_escalate_third_agent_i10`, `lipid_escalate_high_intensity_e78`, `lipid_escalate_ezetimibe_e78`) — Phase 4a convention.

**4. Review Focus.** 5 items pinned, each with its owning task listed (Task 3 / 2 / 6 / 5 / 7). None overlap with Phase 4a's Review Focus — all exercise behavior new to Phase 4b.1.

**5. Proportion.** Plan is ~18 KB; the code it specifies is ~5 yamls (~150 LOC YAML) + ~5 LOC Python (one Layer-1 override + chronic_medications edits) + ~250 LOC tests. Ratio reasonable; the plan's bulk is spec references, calibration rationale, and the explicit Review Focus pin assignments.

**Risks the plan accepts (not findings — settled):**

- **Layer-1 systolic_bp field is read from `PatientProfile` not `PersonRecord`** — the BMI override in Phase 3 handles this via the activator path. The implementer may need to adjust the override insertion point if `generate_population` sees `PersonRecord` first (before activation). The plan's Task 6 Step 3 says "after `initial_snapshot` returns" — the implementer confirms the field path at implementation time; ledger if the path differs from `person.systolic_bp`.
- **LDL has no Layer-1 anchor** — the yaml `initial:` draw (mu=5.10, sigma=0.12 → median ≈ 164 mg/dL) is the entry distribution. If a future Phase sets `PatientProfile.ldl` at Layer-1 generation, that override lands then.
- **Ezetimibe fires independently of Rosuvastatin** — Review Focus #4 pins this via depends_on. A patient at sustained LDL > 190 picks up BOTH drugs across sim years, matching ACC-AHA 2018 §4.4.2 (statin + non-statin add-on, not either/or).
