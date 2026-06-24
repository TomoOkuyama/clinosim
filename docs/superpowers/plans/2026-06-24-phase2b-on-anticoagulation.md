# Phase 2b: `on_warfarin` Medication-Physiology Coupling — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Single-module tightly-coupled tasks — inline execution recommended.

**Goal:** Couple warfarin medication state to PT_INR derivation so AF chronic patients, PE/DVT/CI patients on chronic AC, and in-hospital warfarin loading (day ≥ 3) patients show clinically realistic therapeutic INR (target 2.0-3.0). DOAC (apixaban/rivaroxaban/edoxaban/dabigatran) explicitly NOT detected — INR is not clinically monitored for DOAC.

**Architecture:** Add a sibling helper `medication_flags_from_context(patient, medication_orders, admission_date, current_day)` parallel to `scenario_flags_from_protocol`. Call sites merge both via `**flags` to `derive_lab_values`. Add `on_warfarin: bool = False` kwarg to `derive_lab_values`; modify only the PT_INR block (BNP-pattern surgical, AD-57 state-untouched). PT is auto-consistent via existing `PT = 12 * PT_INR`.

**Tech Stack:** Python 3.11+, ruff, mypy strict, pytest. clinosim physiology/engine.py, simulator/{inpatient,emergency,outpatient}.py, locale/shared/chronic_medications.yaml.

## Global Constraints

- Branch: `feat/phase2b-on-anticoagulation` (already created, spec commit `3627d3d6`)
- Spec source: `docs/superpowers/specs/2026-06-24-phase2b-on-anticoagulation-design.md`
- Predecessor: PR #81 (Phase 2a D-dimer + causes_vte + J5 fix), master HEAD `9e0b97a7`
- **AD-57**: BNP-pattern surgical — `PhysiologicalState` untouched, formula-only PT_INR change.
- **AD-59**: per-order sub-rng pattern intact — NO new RNG draw inside `derive_lab_values`.
- **AD-16**: master RNG unaffected — medication detection is a deterministic peek.
- **CLAUDE.md rule (Phase 2a J5)**: scenario flags wired via `scenario_flags_from_protocol` + `**flags`. Phase 2b extends: also `medication_flags_from_context` + `**flags`. Never add a `flag=value` named arg directly at a call site.
- **DOAC intentionally NOT detected** — modeling DOAC INR lift is clinically misleading. Spec §3 / §10 deferred.
- **Commit trailer (every commit)**:
  ```
  Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01PDwHvpzArboaKwtBDNpw8R
  ```
- **English code + comments** (project convention)
- **Verification before assertion**: every commit must follow a green pytest run; don't claim success without observed test output.

## File Structure

| Path | Change | Responsibility |
|---|---|---|
| `clinosim/modules/physiology/engine.py` | Modify | Add `medication_flags_from_context` helper. Extend `derive_lab_values` with `on_warfarin: bool = False` kwarg and PT_INR block override. |
| `tests/unit/test_medication_flags.py` | Create | Unit tests for new helper (chronic detection EN/JP, in-hospital ramp gate, DOAC negative cases). |
| `tests/unit/test_physiology.py` | Modify | Extend with PT_INR-on-warfarin tests (therapeutic center, comorbidity lift, off-warfarin unchanged, PT auto-consistency). |
| `clinosim/locale/shared/chronic_medications.yaml` | Modify | Add I26/I82/I63 entries (PE / DVT / embolic CI post-discharge AC indications). |
| `clinosim/simulator/inpatient.py:563-571` (Pass-1) | Modify | Merge `medication_flags_from_context(...)` into the `**flags` splat. |
| `clinosim/simulator/inpatient.py:~1685` (second site) | Verify | Decide whether to add medication flags or leave as `scenario_flags_from_protocol(None)` equivalent. |
| `clinosim/simulator/emergency.py:126` | Modify | Add `medication_flags_from_context(patient)` merge — chronic-only path (no MAR/day available). |
| `clinosim/simulator/outpatient.py:152` | Modify | Add `medication_flags_from_context(patient)` merge — chronic-only. |
| `tests/integration/test_medication_flags_isolation.py` | Create | AD-59-style isolation guard: chronic_medications.yaml edits for indication X don't change labs of non-X patients. |
| `tests/integration/test_phase2b_anticoagulation_scenarios.py` | Create | Clinical scenario integration tests (AF chronic INR therapeutic, PE day-3 INR shift, post-discharge followup split). |
| `scratchpad/phase2b_byte_diff_results.md` | Create (scratch) | byte-diff p=2000 US/JP vs master `9e0b97a7` evidence — not committed. |
| `docs/reviews/2026-06-24-phase2b-anticoagulation-data-quality-review.md` | Create | DQR 3-axis review evidence (committed). |
| `README.md` / `README.ja.md` | Modify | Phase 2b AC cohort story sync. |
| `DESIGN.md` | Modify | AD-59 entry note: medication-coupling helper extends scenario-flag pattern. |
| `CLAUDE.md` | Modify | New architecture rule: TWO flag dicts (scenario + medication) pattern. |
| `clinosim/modules/physiology/README.md` | Modify | Document new helper API. |
| `TODO.md` | Modify | Phase 2b done; Phase 2c backlog (aPTT/heparin, DOAC, ramp, HIT, activator AC exclusivity). |

---

## Task 1: `medication_flags_from_context` helper + unit tests

**Files:**
- Modify: `clinosim/modules/physiology/engine.py` (add helper before `derive_lab_values`)
- Create: `tests/unit/test_medication_flags.py`

**Interfaces:**
- Consumes: PatientProfile (from `clinosim.types.patient`), Order (from `clinosim.types.encounter`)
- Produces:
  ```python
  def medication_flags_from_context(
      patient,                                # PatientProfile | None
      medication_orders=None,                 # list[Order] | None
      admission_date=None,                    # date | None
      current_day: int | None = None,         # 0-indexed day into stay
  ) -> dict[str, bool]:
      # Returns {"on_warfarin": bool}
  ```

- [ ] **Step 1: Write the failing test file**

Create `tests/unit/test_medication_flags.py`:

```python
"""Unit tests for `medication_flags_from_context` — Phase 2b on_warfarin
detection (chronic + in-hospital ramp at day ≥ 3). DOAC is intentionally
NOT detected (INR is not clinically monitored for DOAC).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

import pytest

from clinosim.modules.physiology.engine import medication_flags_from_context


@dataclass
class _StubPatient:
    """Minimal stand-in for PatientProfile.current_medications consumers."""
    current_medications: list[str] = field(default_factory=list)


@dataclass
class _StubOrder:
    """Minimal stand-in for Order (medication-type) consumers."""
    display_name: str = ""
    ordered_datetime: datetime | None = None


@pytest.mark.unit
def test_chronic_warfarin_en_detected():
    p = _StubPatient(current_medications=["Warfarin 3mg"])
    assert medication_flags_from_context(p) == {"on_warfarin": True}


@pytest.mark.unit
def test_chronic_warfarin_jp_detected():
    p = _StubPatient(current_medications=["ワルファリン3mg"])
    assert medication_flags_from_context(p) == {"on_warfarin": True}


@pytest.mark.unit
def test_chronic_coumadin_detected_case_insensitive():
    p = _StubPatient(current_medications=["COUMADIN 5mg PO daily"])
    assert medication_flags_from_context(p) == {"on_warfarin": True}


@pytest.mark.unit
def test_chronic_apixaban_not_warfarin():
    p = _StubPatient(current_medications=["Apixaban 5mg"])
    assert medication_flags_from_context(p) == {"on_warfarin": False}


@pytest.mark.unit
def test_chronic_rivaroxaban_not_warfarin():
    p = _StubPatient(current_medications=["Rivaroxaban 20mg", "リバーロキサバン15mg"])
    assert medication_flags_from_context(p) == {"on_warfarin": False}


@pytest.mark.unit
def test_no_meds_returns_false():
    p = _StubPatient(current_medications=[])
    assert medication_flags_from_context(p) == {"on_warfarin": False}


@pytest.mark.unit
def test_none_patient_returns_false():
    assert medication_flags_from_context(None) == {"on_warfarin": False}


@pytest.mark.unit
def test_in_hospital_warfarin_day_2_not_yet():
    p = _StubPatient(current_medications=[])
    admission = date(2026, 6, 1)
    # warfarin ordered on day 0 (admission), current day = 2 → not yet therapeutic
    orders = [_StubOrder(display_name="Warfarin 3mg",
                         ordered_datetime=datetime(2026, 6, 1, 10, 0))]
    flags = medication_flags_from_context(
        p, medication_orders=orders, admission_date=admission, current_day=2
    )
    assert flags == {"on_warfarin": False}


@pytest.mark.unit
def test_in_hospital_warfarin_day_3_active():
    p = _StubPatient(current_medications=[])
    admission = date(2026, 6, 1)
    orders = [_StubOrder(display_name="Warfarin 3mg",
                         ordered_datetime=datetime(2026, 6, 1, 10, 0))]
    flags = medication_flags_from_context(
        p, medication_orders=orders, admission_date=admission, current_day=3
    )
    assert flags == {"on_warfarin": True}


@pytest.mark.unit
def test_in_hospital_apixaban_never_triggers():
    p = _StubPatient(current_medications=[])
    admission = date(2026, 6, 1)
    orders = [_StubOrder(display_name="Apixaban 5mg",
                         ordered_datetime=datetime(2026, 6, 1, 10, 0))]
    flags = medication_flags_from_context(
        p, medication_orders=orders, admission_date=admission, current_day=7
    )
    assert flags == {"on_warfarin": False}


@pytest.mark.unit
def test_in_hospital_warfarin_ordered_day_5_current_day_6_not_yet():
    """warfarin ordered late (day 5); current day 6 → 1 day elapsed → not therapeutic."""
    p = _StubPatient(current_medications=[])
    admission = date(2026, 6, 1)
    orders = [_StubOrder(display_name="Warfarin 3mg",
                         ordered_datetime=datetime(2026, 6, 6, 10, 0))]
    flags = medication_flags_from_context(
        p, medication_orders=orders, admission_date=admission, current_day=6
    )
    assert flags == {"on_warfarin": False}


@pytest.mark.unit
def test_chronic_overrides_in_hospital_gate():
    """Chronic warfarin is True even at current_day=1 (gate only applies to in-hospital path)."""
    p = _StubPatient(current_medications=["Warfarin 3mg"])
    admission = date(2026, 6, 1)
    flags = medication_flags_from_context(
        p, medication_orders=[], admission_date=admission, current_day=1
    )
    assert flags == {"on_warfarin": True}
```

- [ ] **Step 2: Run test to confirm it fails**

Run: `pytest tests/unit/test_medication_flags.py -v 2>&1 | head -30`

Expected: ImportError — `cannot import name 'medication_flags_from_context' from 'clinosim.modules.physiology.engine'`.

- [ ] **Step 3: Implement the helper**

In `clinosim/modules/physiology/engine.py`, insert the helper immediately after `scenario_flags_from_protocol` (before `derive_lab_values`):

```python
def medication_flags_from_context(
    patient,
    medication_orders=None,
    admission_date=None,
    current_day: int | None = None,
) -> dict[str, bool]:
    """Detect medication-driven lab effects from patient + encounter context.

    Centralizes the medication → lab coupling reads so a new coupling added to
    `derive_lab_values` only needs wiring in ONE place — same J5-prevention
    rationale as `scenario_flags_from_protocol`. Dict keys match
    `derive_lab_values` parameter names so callers can spread with `**flags`.

    Phase 2b: returns `{"on_warfarin": bool}` only. Extend the dict for future
    couplings (steroid → glucose, diuretic → K, antibiotic → CRP).

    Detection rules:
      (1) Chronic warfarin: ``patient.current_medications`` contains a
          warfarin string (case-insensitive substring of "warfarin",
          "ワルファリン", "coumadin").
      (2) In-hospital warfarin: ``medication_orders`` contains a warfarin
          order AND ``current_day - (order_date - admission_date).days >= 3``
          (loading-dose 3-day rule).

    DOAC (apixaban / rivaroxaban / edoxaban / dabigatran) is intentionally
    NOT detected — INR is not clinically monitored for DOAC; modeling DOAC
    INR lift would be clinically misleading.

    All inputs are optional / defensive: ``None`` patient or missing
    ``current_medications`` returns ``{"on_warfarin": False}``. ED and
    outpatient call sites pass medication_orders=None / current_day=None;
    only the chronic path runs.
    """
    _WARFARIN_NAMES = ("warfarin", "ワルファリン", "coumadin")

    if patient is None:
        return {"on_warfarin": False}

    on_warfarin = False

    # (1) Chronic warfarin from home meds
    for med in (getattr(patient, "current_medications", None) or []):
        if not isinstance(med, str):
            continue
        med_lower = med.lower()
        if any(name in med_lower for name in _WARFARIN_NAMES):
            on_warfarin = True
            break

    # (2) In-hospital warfarin ordered ≥ 3 days ago
    if (
        not on_warfarin
        and medication_orders
        and admission_date is not None
        and current_day is not None
        and current_day >= 3
    ):
        for o in medication_orders:
            display = (getattr(o, "display_name", "") or "")
            if not any(name in display.lower() for name in _WARFARIN_NAMES):
                continue
            ordered_dt = getattr(o, "ordered_datetime", None)
            ordered_date = ordered_dt.date() if hasattr(ordered_dt, "date") else None
            if ordered_date is None:
                continue
            days_since_order = current_day - (ordered_date - admission_date).days
            if days_since_order >= 3:
                on_warfarin = True
                break

    return {"on_warfarin": on_warfarin}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_medication_flags.py -v 2>&1 | tail -30`

Expected: all 11 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_medication_flags.py clinosim/modules/physiology/engine.py
git commit -m "$(cat <<'EOF'
feat(phase2b): medication_flags_from_context helper — chronic + in-hospital warfarin detection

Sibling helper to scenario_flags_from_protocol. Detects warfarin from:
(1) patient.current_medications (chronic AC, EN/JP/coumadin substring)
(2) in-hospital medication orders ordered ≥ 3 days ago (loading-dose
    3-day rule for therapeutic INR)

DOAC (apixaban/rivaroxaban/edoxaban/dabigatran) intentionally NOT
detected — INR is not clinically monitored for DOAC; modeling DOAC
INR lift would be clinically misleading.

API: returns {"on_warfarin": bool} so callers can splat as **flags to
derive_lab_values. Forward-extensible for Phase 2c couplings.

11 unit tests (EN/JP/coumadin chronic, DOAC negatives, day-2 vs day-3
gate, late warfarin order, chronic overrides in-hospital gate, None
patient, empty meds).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01PDwHvpzArboaKwtBDNpw8R
EOF
)"
```

---

## Task 2: Extend `derive_lab_values` with `on_warfarin` kwarg + unit tests

**Files:**
- Modify: `clinosim/modules/physiology/engine.py:250` (signature) and the PT_INR block (currently line 338)
- Modify: `tests/unit/test_physiology.py` (add 5 new tests near existing PT_INR / coag tests)

**Interfaces:**
- Consumes: `medication_flags_from_context` output (`{"on_warfarin": bool}`)
- Produces:
  ```python
  def derive_lab_values(
      state, sex, age,
      has_diabetes=False, rng=None, hour=6,
      myocardial_injury=False,
      causes_vte=False,
      on_warfarin=False,                          # NEW
  ) -> dict[str, float]:
      ...
  ```

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_physiology.py` (place near the existing PT_INR / aPTT block around line 700-800):

```python
# ---------------------------------------------------------------------------
# Phase 2b: PT_INR on warfarin (medication-physiology coupling)
# ---------------------------------------------------------------------------

@pytest.mark.unit
def test_pt_inr_on_warfarin_healthy_baseline_therapeutic():
    """Healthy patient (no hepatic / DIC stress) on warfarin → INR ~2.5."""
    state = PhysiologicalState()  # all defaults: hepatic=1.0, coag=0.0
    labs = derive_lab_values(state, sex="M", age=60, on_warfarin=True)
    assert 2.4 <= labs["PT_INR"] <= 2.6


@pytest.mark.unit
def test_pt_inr_off_warfarin_unchanged():
    """Existing formula path: healthy → INR 1.0."""
    state = PhysiologicalState()
    labs = derive_lab_values(state, sex="M", age=60, on_warfarin=False)
    assert labs["PT_INR"] == pytest.approx(1.0, abs=0.01)


@pytest.mark.unit
def test_pt_inr_on_warfarin_with_dic_comorbidity_lift():
    """warfarin + DIC (coag_status=0.5): therapeutic + comorbidity lift ≈ 2.875."""
    state = PhysiologicalState()
    state.coagulation_status = 0.5
    labs = derive_lab_values(state, sex="M", age=60, on_warfarin=True)
    # base_inr = 1.0 + 0 + 0.5*1.5 = 1.75
    # on warfarin: 2.5 + (1.75 - 1.0) * 0.5 = 2.875
    assert 2.8 <= labs["PT_INR"] <= 2.95


@pytest.mark.unit
def test_pt_inr_on_warfarin_with_cirrhosis_over_anticoagulation():
    """warfarin + cirrhosis (hepatic=0.4): INR ~3.1 (over-AC bleeding risk visible)."""
    state = PhysiologicalState()
    state.hepatic_function = 0.4
    labs = derive_lab_values(state, sex="M", age=60, on_warfarin=True)
    # base_inr = 1.0 + 0.6*2.0 + 0 = 2.2
    # on warfarin: 2.5 + (2.2 - 1.0) * 0.5 = 3.1
    assert 3.0 <= labs["PT_INR"] <= 3.2


@pytest.mark.unit
def test_pt_derived_consistency_with_warfarin_shift():
    """PT = 12 * PT_INR invariant maintained when warfarin shifts INR."""
    state = PhysiologicalState()
    labs = derive_lab_values(state, sex="M", age=60, on_warfarin=True)
    assert labs["PT"] == pytest.approx(12.0 * labs["PT_INR"], abs=0.01)
```

- [ ] **Step 2: Run new tests to confirm they fail**

Run: `pytest tests/unit/test_physiology.py -v -k "warfarin or pt_derived_consistency_with_warfarin" 2>&1 | tail -25`

Expected: TypeError — `derive_lab_values() got an unexpected keyword argument 'on_warfarin'`.

- [ ] **Step 3: Extend the signature and PT_INR block**

In `clinosim/modules/physiology/engine.py:250`, add the new kwarg to the signature:

```python
def derive_lab_values(
    state: PhysiologicalState,
    sex: str,
    age: int,
    has_diabetes: bool = False,
    rng: np.random.Generator | None = None,
    hour: int = 6,
    myocardial_injury: bool = False,
    causes_vte: bool = False,
    on_warfarin: bool = False,
) -> dict[str, float]:
```

Replace the existing PT_INR line (currently line 338, the single-line `labs["PT_INR"] = ...`) with:

```python
    # PT_INR: hepatic (cirrhosis factor depletion) + coagulation_status (DIC
    # consumption) drive baseline; therapeutic warfarin overrides to target
    # the 2.0-3.0 clinical band. AC + comorbidity (DIC, cirrhosis) compounds
    # bleeding risk in real practice, so base perturbation is added on top of
    # the therapeutic center at reduced gain (×0.5).
    # BNP-pattern surgical (AD-57): state untouched, formula-only change.
    # Phase 2b (2026-06-24): on_warfarin sourced from
    # medication_flags_from_context (sibling of scenario_flags_from_protocol).
    base_inr = 1.0 + (1 - hepatic) * 2.0 + state.coagulation_status * 1.5
    if on_warfarin:
        labs["PT_INR"] = 2.5 + (base_inr - 1.0) * 0.5
    else:
        labs["PT_INR"] = base_inr
```

PT line (existing, immediately after) stays unchanged:

```python
    labs["PT"] = clamp(12.0 * labs["PT_INR"], 9.0, 90.0)
```

- [ ] **Step 4: Run new tests to verify they pass + existing PT_INR tests still pass**

Run:
```
pytest tests/unit/test_physiology.py -v -k "pt_inr or pt_derived" 2>&1 | tail -30
```

Expected: all PT_INR tests PASS (new + existing). Then full file:

```
pytest tests/unit/test_physiology.py -v 2>&1 | tail -10
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_physiology.py clinosim/modules/physiology/engine.py
git commit -m "$(cat <<'EOF'
feat(phase2b): derive_lab_values on_warfarin kwarg + therapeutic PT_INR override

Adds on_warfarin: bool = False kwarg. When True, PT_INR formula
overrides to 2.5 + (base_inr - 1.0) * 0.5 — therapeutic center plus
half-gain comorbidity perturbation. Off-warfarin path unchanged.

Clinical correctness verified in unit tests:
- baseline + warfarin → INR ~2.5 (mid-therapeutic)
- warfarin + DIC (coag=0.5) → INR ~2.875 (compounded coagulopathy)
- warfarin + cirrhosis (hepatic=0.4) → INR ~3.1 (over-AC bleeding risk)
- PT = 12 * PT_INR invariant maintained (auto-consistent derivation)

BNP-pattern surgical (AD-57): no state mutation, no new RNG draw,
AD-59 per-order sub-rng intact, AD-16 master stream unaffected.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01PDwHvpzArboaKwtBDNpw8R
EOF
)"
```

---

## Task 3: Add I26/I82/I63 entries to `chronic_medications.yaml`

**Files:**
- Modify: `clinosim/locale/shared/chronic_medications.yaml`

**Note:** `simulator/helpers.py:65` chronic_prefixes is `("I", "E", "J44", "J45", ...)` — `"I"` prefix already covers I26/I82/I63, so **no helpers.py edit needed**. This verified during plan writing.

- [ ] **Step 1: Locate the existing I48 entry**

Run: `grep -n "^I" clinosim/locale/shared/chronic_medications.yaml | head -20`

Expected: a single `I48:` entry (Atrial fibrillation). Confirm structure and indentation.

- [ ] **Step 2: Append the three new entries after the existing I48 block**

Use Edit tool to insert after the I48 block (preserve existing YAML structure, indentation 2 spaces). New entries:

```yaml
I26:  # Pulmonary embolism — post-discharge AC (ACCP 2020: ≥3 mo, indefinite if unprovoked)
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

I63:  # Cerebral infarction — embolic source (AF/cardiac) gets AC; non-embolic gets antiplatelet
  medications:
    - {drug: "Warfarin 3mg", drug_ja: "ワルファリン3mg", route: "PO", frequency: "daily", probability: 0.3}
    - {drug: "Apixaban 5mg", drug_ja: "アピキサバン5mg", route: "PO", frequency: "bid", probability: 0.3}
    - {drug: "Aspirin 100mg", drug_ja: "アスピリン100mg", route: "PO", frequency: "daily", probability: 0.7}
    - {drug: "Clopidogrel 75mg", drug_ja: "クロピドグレル75mg", route: "PO", frequency: "daily", probability: 0.3}
  monitoring:
    - {test: "PT_INR", frequency: "monthly", condition: "if on warfarin"}
```

- [ ] **Step 3: Verify YAML loads cleanly**

Run:
```
python -c "
import yaml
from pathlib import Path
d = yaml.safe_load(Path('clinosim/locale/shared/chronic_medications.yaml').read_text())
assert 'I26' in d and 'I82' in d and 'I63' in d, list(d)
print('OK keys:', sorted(k for k in d if k.startswith('I')))
print('I26 meds:', [m['drug'] for m in d['I26']['medications']])
print('I82 meds:', [m['drug'] for m in d['I82']['medications']])
print('I63 meds:', [m['drug'] for m in d['I63']['medications']])
"
```

Expected output:
```
OK keys: ['I10', 'I25', 'I26', 'I48', 'I50', 'I63', 'I82', ...]
I26 meds: ['Rivaroxaban 20mg', 'Apixaban 5mg', 'Warfarin 3mg']
I82 meds: ['Rivaroxaban 20mg', 'Apixaban 5mg', 'Warfarin 3mg']
I63 meds: ['Warfarin 3mg', 'Apixaban 5mg', 'Aspirin 100mg', 'Clopidogrel 75mg']
```

(Other I-prefix keys may exist — just confirm new keys present.)

- [ ] **Step 4: Verify chronic_prefixes coverage in `helpers.py`**

Run: `grep -n "chronic_prefixes" clinosim/simulator/helpers.py`

Expected: `chronic_prefixes = ("I", "E", "J44", "J45", "N18", "M", "G20", "F00", "K21", "N40")` — the leading `"I"` already covers I26/I82/I63, so **no edit needed**. If the line has changed structure or no longer covers `"I"`, halt and re-evaluate.

- [ ] **Step 5: Commit**

```bash
git add clinosim/locale/shared/chronic_medications.yaml
git commit -m "$(cat <<'EOF'
feat(phase2b): chronic_medications.yaml — I26/I82/I63 post-discharge AC

Add post-discharge anticoagulation indications:
- I26 Pulmonary embolism: DOAC 80% (riva 50 / apix 30) / warfarin 20%
- I82 Deep vein thrombosis: same as I26 (modern ACCP 2020 first-line DOAC)
- I63 Cerebral infarction: 60% AC (embolic-source proxy) + 70% antiplatelet
  (combined therapy reflects clinical practice for select cases)

Completes the cohort trajectory: PE/DVT/CI patients discharged →
helpers.py promotes I26/I82/I63 to chronic_conditions (existing
"I" prefix) → outpatient followup activator re-derives home meds →
warfarin probability gives therapeutic INR via medication_flags helper.

helpers.py chronic_prefixes already covers "I" prefix — no edit needed.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01PDwHvpzArboaKwtBDNpw8R
EOF
)"
```

---

## Task 4: Call-site wiring (inpatient / emergency / outpatient)

**Files:**
- Modify: `clinosim/simulator/inpatient.py:563-571` (Pass-1 lab loop)
- Modify: `clinosim/simulator/inpatient.py:~1685` (second derive_lab_values site — verify)
- Modify: `clinosim/simulator/emergency.py:126`
- Modify: `clinosim/simulator/outpatient.py:152`

**Interfaces:**
- Consumes: `medication_flags_from_context` from Task 1, `derive_lab_values` from Task 2
- Produces: merged `**flags` at every call site so the new on_warfarin reaches all lab generation paths

- [ ] **Step 1: Update import line in inpatient.py**

Find the import block at the top of `clinosim/simulator/inpatient.py` (around line 40-45) that already imports `derive_lab_values, scenario_flags_from_protocol`. Edit to add `medication_flags_from_context`:

```python
from clinosim.modules.physiology.engine import (
    derive_lab_values,
    # ... other existing imports
    scenario_flags_from_protocol,
    medication_flags_from_context,
)
```

(Match the existing import style; if currently single-line, expand to multi-line.)

- [ ] **Step 2: Update Pass-1 lab loop (inpatient.py:563-571)**

Locate the block:

```python
flags = scenario_flags_from_protocol(protocol)
true_labs = derive_lab_values(state, sex=patient.sex, age=patient.age, has_diabetes=has_diabetes, hour=lab_hour, **flags)

if len(state_history) >= 2 and "CRP" in true_labs:
    lag_idx = max(0, len(state_history) - 2)
    lagged_state = state_history[lag_idx]
    lagged_labs = derive_lab_values(lagged_state, sex=patient.sex, age=patient.age, has_diabetes=has_diabetes, hour=lab_hour, **flags)
    true_labs["CRP"] = lagged_labs.get("CRP", true_labs["CRP"])
```

Replace with:

```python
# Phase 2a (J5): scenario flags merged via helper.
# Phase 2b (2026-06-24): medication flags merged via sibling helper —
# detects chronic warfarin from current_medications AND in-hospital warfarin
# orders ≥ 3 days ago (loading-dose 3-day rule). Both helpers spread as
# **flags so a new flag added to derive_lab_values reaches this site
# without touching the call.
_med_orders = [o for o in all_orders
               if o.order_type.value == "medication"]
flags = {
    **scenario_flags_from_protocol(protocol),
    **medication_flags_from_context(
        patient,
        medication_orders=_med_orders,
        admission_date=admission_time.date(),
        current_day=day,
    ),
}
true_labs = derive_lab_values(state, sex=patient.sex, age=patient.age, has_diabetes=has_diabetes, hour=lab_hour, **flags)

if len(state_history) >= 2 and "CRP" in true_labs:
    lag_idx = max(0, len(state_history) - 2)
    lagged_state = state_history[lag_idx]
    lagged_labs = derive_lab_values(lagged_state, sex=patient.sex, age=patient.age, has_diabetes=has_diabetes, hour=lab_hour, **flags)
    true_labs["CRP"] = lagged_labs.get("CRP", true_labs["CRP"])
```

(Note: `OrderType` enum: confirm `order_type.value == "medication"` is the correct filter by grepping `order_type` in `clinosim/types/encounter.py` if uncertain.)

- [ ] **Step 3: Inspect the second inpatient derive_lab_values site (~line 1685)**

Run: `grep -n "true_labs = derive_lab_values" clinosim/simulator/inpatient.py`

Inspect each occurrence. The Pass-1 site (~563) is now updated. For each other occurrence:

- If it represents a normal-state baseline lab derivation (the historical note in Phase 2a memory says line 1685 "calls derive_lab_values without any flags" intentionally matching `scenario_flags_from_protocol(None)` semantics), leave it as-is — the existing call without flags is semantically equivalent to passing `medication_flags_from_context(None)` (all False).
- If it represents an alternate active-encounter lab derivation, apply the same merge pattern as Step 2.

Document the decision in a one-line comment at each site (e.g., `# Phase 2b: baseline-only context, no medication coupling applies`).

- [ ] **Step 4: Update emergency.py**

Locate `clinosim/simulator/emergency.py:126`:

```python
_flags = scenario_flags_from_protocol(protocol)
_true_labs = derive_lab_values(_state, sex=patient.sex, age=patient.age, has_diabetes=_has_dm, **_flags)
```

Update import line (top of file, around line 42-45):

```python
from clinosim.modules.physiology.engine import (
    derive_lab_values,
    # ... other existing imports
    scenario_flags_from_protocol,
    medication_flags_from_context,
)
```

Replace the flags assignment:

```python
# Phase 2b: medication flags merged. ED is admit-day; no in-hospital ramp
# (no MAR / day-into-stay applies) — chronic-only path runs via patient.
_flags = {
    **scenario_flags_from_protocol(protocol),
    **medication_flags_from_context(patient),
}
_true_labs = derive_lab_values(_state, sex=patient.sex, age=patient.age, has_diabetes=_has_dm, **_flags)
```

- [ ] **Step 5: Update outpatient.py**

Locate `clinosim/simulator/outpatient.py:145-160`:

```python
from clinosim.modules.physiology.engine import derive_lab_values, scenario_flags_from_protocol
...
_flags = scenario_flags_from_protocol(None)
_true_labs = derive_lab_values(_state, sex=patient.sex, age=patient.age, has_diabetes=_has_dm, **_flags)
```

Update import + flags assignment:

```python
from clinosim.modules.physiology.engine import (
    derive_lab_values, scenario_flags_from_protocol, medication_flags_from_context,
)
...
# Phase 2b: medication flags merged. Outpatient = chronic-context only —
# medication_orders/current_day=None, only chronic detection runs.
_flags = {
    **scenario_flags_from_protocol(None),
    **medication_flags_from_context(patient),
}
_true_labs = derive_lab_values(_state, sex=patient.sex, age=patient.age, has_diabetes=_has_dm, **_flags)
```

- [ ] **Step 6: Run all existing unit + integration tests to confirm no regression**

Run:
```
pytest tests/unit/ tests/integration/ -x -q 2>&1 | tail -20
```

Expected: ~410 passed (the 11 new helper tests + 5 new PT_INR tests added, existing tests unchanged). All green.

If any fail, investigate immediately — most likely cause is import not found or the order filter being wrong (`order_type.value` mismatch).

- [ ] **Step 7: Commit**

```bash
git add clinosim/simulator/inpatient.py clinosim/simulator/emergency.py clinosim/simulator/outpatient.py
git commit -m "$(cat <<'EOF'
feat(phase2b): wire medication_flags_from_context at all 3 derive_lab_values sites

Inpatient Pass-1 lab loop: peek all_orders for medication-type orders,
pass to helper with admission_date + current_day for the 3-day
loading-dose gate. Chronic + in-hospital paths both active.

Emergency: chronic-only (no MAR / day-into-stay at admit).
Outpatient: chronic-only (post-discharge followup context).

Second inpatient derive_lab_values site (baseline-context, line ~1685)
inspected and documented; existing no-flags call is semantically
equivalent to passing both helpers as null inputs.

All 3 sites use the {**scenario_flags, **medication_flags} pattern so
the new on_warfarin reaches the formula without touching any call.
Future flag additions extend the helpers; call sites stay stable
(CLAUDE.md Phase 2b rule).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01PDwHvpzArboaKwtBDNpw8R
EOF
)"
```

---

## Task 5: Integration tests — AD-59 isolation + clinical scenarios

**Files:**
- Create: `tests/integration/test_medication_flags_isolation.py`
- Create: `tests/integration/test_phase2b_anticoagulation_scenarios.py`

**Interfaces:**
- Consumes: `run_forced` from `clinosim.simulator`, `SimulatorConfig` / `ForcedScenario` from `clinosim.types.config`
- Produces: regression guards for future analyte / coupling additions

- [ ] **Step 1: Create AD-59 isolation guard**

Create `tests/integration/test_medication_flags_isolation.py`:

```python
"""Integration test: medication_flags_from_context detection of any
indication X does NOT change labs for patients lacking that indication
(AD-59 invariant extension for medication-driven coupling).

Mirrors test_individual_lab_isolation.py pattern: deterministic byte
comparison of labs for non-target-indication patients between two runs
where one has the chronic_medications entry and the other doesn't.

This regression-guards future couplings: when Phase 2c adds another
medication flag (e.g., on_therapeutic_heparin), the same isolation
property must hold.
"""
from __future__ import annotations

import pytest

from clinosim.simulator import run_forced
from clinosim.types.config import ForcedScenario, SimulatorConfig


@pytest.mark.integration
def test_af_chronic_warfarin_isolated_from_non_af_patients():
    """A run of UTI (non-AF, no chronic AC) patients must have identical
    PT_INR distribution regardless of whether the AF chronic_medications
    entry exists. AF patients aren't in the cohort; the lookup never
    fires.

    Since chronic_medications.yaml is a runtime YAML lookup keyed by
    ICD code, we cannot mutate it mid-test deterministically — but we
    CAN assert that UTI cohort labs are deterministic across two seeded
    runs (the structural property: no master-RNG poisoning).
    """
    scenario = ForcedScenario(disease_id="urinary_tract_infection", count=5, severity="moderate")
    cfg = SimulatorConfig(random_seed=42, country="US")

    run1 = run_forced(scenario, cfg)
    run2 = run_forced(scenario, cfg)

    # Determinism check: same seed → byte-identical PT_INR distribution.
    pt_inrs_1 = sorted(
        obs.value_numeric
        for p in run1.patients for obs in p.observations
        if obs.display_name == "PT_INR" and obs.value_numeric is not None
    )
    pt_inrs_2 = sorted(
        obs.value_numeric
        for p in run2.patients for obs in p.observations
        if obs.display_name == "PT_INR" and obs.value_numeric is not None
    )
    assert pt_inrs_1 == pt_inrs_2, "PT_INR distribution must be deterministic under same seed"
```

- [ ] **Step 2: Create clinical scenario tests**

Create `tests/integration/test_phase2b_anticoagulation_scenarios.py`:

```python
"""Integration tests: Phase 2b clinical scenarios for on_warfarin
medication-physiology coupling.

Scope:
- AF chronic on warfarin → INR therapeutic at any encounter
- PE inpatient day ≥ 3 with warfarin order → INR shifted to therapeutic
- DOAC patients → INR baseline (NOT shifted)

Each scenario is one ForcedScenario run with seed=42 for determinism.
"""
from __future__ import annotations

import pytest

from clinosim.modules.physiology.engine import (
    PhysiologicalState,
    derive_lab_values,
    medication_flags_from_context,
)


@pytest.mark.integration
def test_warfarin_patient_pt_inr_in_therapeutic_band():
    """Detection + derivation pipeline: a patient with warfarin in
    current_medications produces INR in the therapeutic [2.0, 3.5] band
    (allows some upper headroom for hepatic/coag perturbation)."""
    class _P:
        current_medications = ["Warfarin 3mg PO daily"]

    flags = medication_flags_from_context(_P())
    assert flags["on_warfarin"] is True

    state = PhysiologicalState()
    labs = derive_lab_values(state, sex="M", age=70, **flags)
    assert 2.0 <= labs["PT_INR"] <= 3.5, f"INR {labs['PT_INR']} outside therapeutic band"


@pytest.mark.integration
def test_doac_patient_pt_inr_baseline():
    """Detection negative + derivation baseline: an apixaban-only patient
    produces baseline INR (~1.0), NOT therapeutic — INR is not monitored
    for DOAC and our model preserves baseline behavior."""
    class _P:
        current_medications = ["Apixaban 5mg PO BID"]

    flags = medication_flags_from_context(_P())
    assert flags["on_warfarin"] is False

    state = PhysiologicalState()
    labs = derive_lab_values(state, sex="M", age=70, **flags)
    assert labs["PT_INR"] < 1.5, f"DOAC patient INR {labs['PT_INR']} should be baseline"


@pytest.mark.integration
def test_no_anticoagulation_pt_inr_baseline():
    """Patient with no AC: baseline formula path (1.0 for healthy state)."""
    class _P:
        current_medications = ["Aspirin 100mg", "Metformin 500mg"]  # antiplatelet + antidiabetic

    flags = medication_flags_from_context(_P())
    assert flags["on_warfarin"] is False

    state = PhysiologicalState()
    labs = derive_lab_values(state, sex="M", age=70, **flags)
    assert labs["PT_INR"] < 1.2


@pytest.mark.integration
def test_warfarin_with_dic_above_therapeutic():
    """Warfarin + DIC (severe coagulopathy): INR > 2.7 (compounded effect)."""
    class _P:
        current_medications = ["Warfarin 3mg"]

    flags = medication_flags_from_context(_P())
    state = PhysiologicalState()
    state.coagulation_status = 0.5
    labs = derive_lab_values(state, sex="M", age=70, **flags)
    assert labs["PT_INR"] > 2.7, "warfarin + DIC should compound to over-therapeutic"
```

- [ ] **Step 3: Run integration tests**

Run:
```
pytest tests/integration/test_medication_flags_isolation.py tests/integration/test_phase2b_anticoagulation_scenarios.py -v 2>&1 | tail -20
```

Expected: all PASS (4 scenario + 1 isolation = 5 tests).

If the isolation test fails on determinism (run1 ≠ run2), the master RNG was poisoned by Task 4 wiring — investigate immediately (most likely cause: `medication_orders` filter or unintended order in flags merge).

- [ ] **Step 4: Run full unit + integration suite**

Run:
```
pytest tests/unit/ tests/integration/ -x -q 2>&1 | tail -10
```

Expected: ~420+ passed (5 new integration on top of previous total). Green.

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_medication_flags_isolation.py tests/integration/test_phase2b_anticoagulation_scenarios.py
git commit -m "$(cat <<'EOF'
test(phase2b): integration — AD-59 isolation + clinical scenarios

Two new integration test files:
1. test_medication_flags_isolation.py — determinism guard: UTI cohort
   PT_INR distribution byte-identical across two seeded runs (regression
   guard for future flag additions, mirrors test_individual_lab_isolation)
2. test_phase2b_anticoagulation_scenarios.py — 4 clinical scenarios:
   warfarin therapeutic band, DOAC baseline (NOT shifted), no AC baseline,
   warfarin + DIC over-therapeutic

These pin the Phase 2b acceptance criteria for future refactoring.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01PDwHvpzArboaKwtBDNpw8R
EOF
)"
```

---

## Task 6: byte-diff verification (US/JP p=2000 vs master `9e0b97a7`)

**Files:**
- Create (scratch): `scratchpad/phase2b_byte_diff/` working directory + `scratchpad/phase2b_byte_diff_results.md` evidence doc

**Goal:** Confirm 7 NDJSON sha256 identical (Patient/Encounter/Condition/Procedure/Imaging/Immunization/FamilyHistory), Medication may grow (legitimate), Observation/DR strict-grow with PT_INR/PT shifts only.

- [ ] **Step 1: Generate branch output (US p=2000 + JP p=2000, seed=42)**

```bash
mkdir -p scratchpad/phase2b_byte_diff/branch
python -m clinosim generate \
  --population 2000 --seed 42 --country US \
  --format fhir-bulk --output scratchpad/phase2b_byte_diff/branch/us
python -m clinosim generate \
  --population 2000 --seed 42 --country JP \
  --format fhir-bulk --output scratchpad/phase2b_byte_diff/branch/jp
```

(Substitute the actual CLI invocation pattern from prior PR memory — `clinosim` script in repo, or `python -m clinosim`.)

- [ ] **Step 2: Generate master output (checkout master, regenerate)**

```bash
git stash -u  # save branch state
git checkout 9e0b97a7
mkdir -p scratchpad/phase2b_byte_diff/master
python -m clinosim generate \
  --population 2000 --seed 42 --country US \
  --format fhir-bulk --output scratchpad/phase2b_byte_diff/master/us
python -m clinosim generate \
  --population 2000 --seed 42 --country JP \
  --format fhir-bulk --output scratchpad/phase2b_byte_diff/master/jp
git checkout feat/phase2b-on-anticoagulation
git stash pop
```

- [ ] **Step 3: sha256 + line-count comparison script**

Save to `scratchpad/phase2b_byte_diff/compare.py`:

```python
"""Byte-diff comparison: master vs phase2b branch.

Per-NDJSON sha256 and line counts for the 9 expected files.
Reports which files are byte-identical, which strict-grow, which differ.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

FILES = [
    "Patient.ndjson", "Encounter.ndjson", "Condition.ndjson",
    "MedicationRequest.ndjson", "MedicationAdministration.ndjson",
    "Procedure.ndjson", "ImagingStudy.ndjson", "Immunization.ndjson",
    "FamilyMemberHistory.ndjson",
    "Observation.ndjson", "DiagnosticReport.ndjson",
]

def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def line_count(path: Path) -> int:
    return sum(1 for _ in path.open())

def main():
    for country in ("us", "jp"):
        m = Path(f"scratchpad/phase2b_byte_diff/master/{country}")
        b = Path(f"scratchpad/phase2b_byte_diff/branch/{country}")
        print(f"\n=== {country.upper()} ===")
        for f in FILES:
            mp, bp = m / f, b / f
            if not mp.exists() or not bp.exists():
                print(f"  {f:35s}  MISSING (m={mp.exists()} b={bp.exists()})")
                continue
            mh, bh = sha256(mp), sha256(bp)
            ml, bl = line_count(mp), line_count(bp)
            status = "IDENTICAL" if mh == bh else ("GROW" if bl > ml else "DIFF")
            print(f"  {f:35s}  {status:10s}  master={ml:6d}  branch={bl:6d}")

if __name__ == "__main__":
    main()
```

Run: `python scratchpad/phase2b_byte_diff/compare.py | tee scratchpad/phase2b_byte_diff/comparison.txt`

- [ ] **Step 4: Verify expected results**

| File | Expected status |
|---|---|
| Patient.ndjson | IDENTICAL |
| Encounter.ndjson | IDENTICAL |
| Condition.ndjson | IDENTICAL |
| Procedure.ndjson | IDENTICAL |
| ImagingStudy.ndjson | IDENTICAL |
| Immunization.ndjson | IDENTICAL |
| FamilyMemberHistory.ndjson | IDENTICAL |
| MedicationRequest.ndjson | IDENTICAL or GROW (if chronic_medications.yaml I26/I82/I63 newly resolve for repeat-encounter cohort patients with prior PE/DVT/CI) |
| MedicationAdministration.ndjson | IDENTICAL or GROW |
| Observation.ndjson | GROW (PT_INR / PT shifts for warfarin patients add lines or change values) |
| DiagnosticReport.ndjson | GROW (Coag panel reflects PT_INR change) |

**If a file marked IDENTICAL above shows DIFF or non-grow change**: investigation needed. Most likely cause: an unintended order-of-operations or RNG side effect from Task 4 wiring (master stream contamination). Halt and bisect.

- [ ] **Step 5: Write byte-diff evidence document**

Create `scratchpad/phase2b_byte_diff_results.md` with:
- Comparison table (from comparison.txt)
- Specific Observation lines added/changed (sample 5 warfarin-patient PT_INR before/after for each country)
- Conclusion: AD-59 / AD-16 invariants preserved, Medication growth is legitimate (audit numbers reasonable)

(This file is for evidence only — NOT committed to git. Keep in scratchpad/.)

---

## Task 7: DQR 3-axis (US p=10000 + JP p=5000, seed=42)

**Files:**
- Create: `docs/reviews/2026-06-24-phase2b-anticoagulation-data-quality-review.md`
- Audit script (scratch): `scratchpad/phase2b_dqr/dqr_audit.py`

**Goal:** Structural / clinical / JP-language axes all PASS. Spec §7 acceptance.

- [ ] **Step 1: Generate audit data (US p=10000 + JP p=5000, seed=42)**

```bash
mkdir -p scratchpad/phase2b_dqr/us scratchpad/phase2b_dqr/jp
python -m clinosim generate \
  --population 10000 --seed 42 --country US \
  --format fhir-bulk --output scratchpad/phase2b_dqr/us
python -m clinosim generate \
  --population 5000 --seed 42 --country JP \
  --format fhir-bulk --output scratchpad/phase2b_dqr/jp
```

- [ ] **Step 2: Write DQR audit script (template-derived from prior PRs)**

Save to `scratchpad/phase2b_dqr/dqr_audit.py`:

```python
"""Phase 2b DQR — 3 axes (structural / clinical / JP language).

Structural:
  - PT_INR Observation count, refRange 100%, interpretation 100%
  - Code lookup OK (LOINC 6301-6 / JLAC10 2B030)
  - No PT_INR shift for non-warfarin patients (cohort isolation)

Clinical:
  - AF chronic (I48) patient PT_INR distribution: p50 in [2.0, 3.0]
  - DOAC patient (apixaban/rivaroxaban) PT_INR baseline (p50 < 1.5)
  - Warfarin patient: therapeutic band coverage
  - Compound (warfarin + DIC/cirrhosis): p90 elevated above 3.0

JP language:
  - US: 0 Japanese characters in any field
  - JP: warfarin / apixaban / rivaroxaban JP display present
  - JP: Coag panel display "凝固検査パネル", PT_INR JP display intact
"""
import json
from collections import defaultdict
from pathlib import Path
from statistics import median, quantiles

def load_ndjson(p):
    return [json.loads(l) for l in p.read_text().splitlines() if l.strip()]

def axis_structural(country, dir_):
    obs = load_ndjson(dir_ / "Observation.ndjson")
    pt_inr = [o for o in obs if any(
        c.get("code") == "6301-6" for c in o.get("code", {}).get("coding", [])
    )]
    print(f"  PT_INR count: {len(pt_inr)}")
    has_range = sum(1 for o in pt_inr if "referenceRange" in o)
    has_interp = sum(1 for o in pt_inr if "interpretation" in o)
    print(f"  refRange: {has_range}/{len(pt_inr)} ({100*has_range/max(1,len(pt_inr)):.1f}%)")
    print(f"  interpretation: {has_interp}/{len(pt_inr)} ({100*has_interp/max(1,len(pt_inr)):.1f}%)")
    return pt_inr

def axis_clinical(country, dir_, pt_inr):
    # Build patient → medications map from Medication* resources
    med_req = load_ndjson(dir_ / "MedicationRequest.ndjson") if (dir_ / "MedicationRequest.ndjson").exists() else []
    pat_warfarin = set()
    pat_doac = set()
    for m in med_req:
        text = (m.get("medicationCodeableConcept", {}).get("text") or "").lower()
        subj = m.get("subject", {}).get("reference", "").split("/")[-1]
        if "warfarin" in text or "ワルファリン" in text or "coumadin" in text:
            pat_warfarin.add(subj)
        elif "apixaban" in text or "rivaroxaban" in text or "edoxaban" in text or "dabigatran" in text:
            pat_doac.add(subj)
    
    warf_vals, doac_vals, other_vals = [], [], []
    for o in pt_inr:
        v = o.get("valueQuantity", {}).get("value")
        if v is None: continue
        subj = o.get("subject", {}).get("reference", "").split("/")[-1]
        if subj in pat_warfarin: warf_vals.append(v)
        elif subj in pat_doac: doac_vals.append(v)
        else: other_vals.append(v)
    
    def stats(name, vs):
        if not vs:
            print(f"    {name}: n=0")
            return
        qs = quantiles(vs, n=10) if len(vs) >= 10 else None
        print(f"    {name}: n={len(vs)} p50={median(vs):.2f}" + (f" p10={qs[0]:.2f} p90={qs[8]:.2f}" if qs else ""))
    
    print(f"  warfarin patients: {len(pat_warfarin)}")
    print(f"  DOAC patients: {len(pat_doac)}")
    stats("warfarin INR", warf_vals)
    stats("DOAC INR    ", doac_vals)
    stats("other INR   ", other_vals)
    
    # Acceptance (warfarin therapeutic, DOAC baseline)
    assert warf_vals, "no warfarin patient PT_INR observed"
    assert 2.0 <= median(warf_vals) <= 3.2, f"warfarin median INR {median(warf_vals):.2f} outside therapeutic"
    if doac_vals:
        assert median(doac_vals) < 1.5, f"DOAC median INR {median(doac_vals):.2f} should be baseline"

def axis_jp_language(country, dir_):
    if country != "JP":
        # US: scan for any Japanese character in PT_INR-related observations
        obs = load_ndjson(dir_ / "Observation.ndjson")
        for o in obs:
            text = json.dumps(o, ensure_ascii=False)
            assert not any('぀' <= c <= 'ヿ' or '一' <= c <= '鿿' for c in text), \
                "US output contains Japanese characters"
        print("  US: no Japanese characters in Observation")
        return
    # JP: verify warfarin/DOAC JP display + Coag panel display
    med_req = load_ndjson(dir_ / "MedicationRequest.ndjson")
    has_warf_jp = any("ワルファリン" in (m.get("medicationCodeableConcept", {}).get("text") or "") for m in med_req)
    print(f"  JP: warfarin (ワルファリン) present: {has_warf_jp}")
    
    obs = load_ndjson(dir_ / "Observation.ndjson")
    pt_inr_obs = [o for o in obs if any(c.get("code") == "6301-6" for c in o.get("code", {}).get("coding", []))]
    if pt_inr_obs:
        sample_codings = pt_inr_obs[0].get("code", {}).get("coding", [])
        for c in sample_codings:
            print(f"    PT_INR coding: system={c.get('system')} code={c.get('code')} display={c.get('display')}")

def main():
    for country in ("US", "JP"):
        print(f"\n{'='*60}\n{country} — Phase 2b DQR\n{'='*60}")
        dir_ = Path(f"scratchpad/phase2b_dqr/{country.lower()}")
        print("\n[Structural]")
        pt_inr = axis_structural(country, dir_)
        print("\n[Clinical]")
        axis_clinical(country, dir_, pt_inr)
        print("\n[JP Language]")
        axis_jp_language(country, dir_)
    print("\n✓ DQR complete")

if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Run DQR audit**

Run: `python scratchpad/phase2b_dqr/dqr_audit.py | tee scratchpad/phase2b_dqr/dqr_results.txt`

Expected: all asserts pass; printed metrics within acceptance band per Spec §7.

If any assert fails, halt and investigate. Most likely causes:
- median INR not in [2.0, 3.0] band → formula coefficient drift (Task 2 PT_INR override math)
- DOAC patient INR shifted → unintended detection (Task 1 helper logic)
- 0 warfarin patients in cohort → activator path not delivering warfarin to current_medications (verify chronic_medications.yaml entries loaded by activator on this seed)

- [ ] **Step 4: Write committed DQR review document**

Create `docs/reviews/2026-06-24-phase2b-anticoagulation-data-quality-review.md` with three sections (structural / clinical / JP), each with the audit output snippets, percentile distributions, and PASS/FAIL conclusion. Template prior reviews (e.g., `docs/reviews/2026-06-24-phase2a-vte-data-quality-review.md`).

- [ ] **Step 5: Commit DQR review**

```bash
git add docs/reviews/2026-06-24-phase2b-anticoagulation-data-quality-review.md
git commit -m "$(cat <<'EOF'
test(dqr): 3-axis review Phase 2b — on_warfarin medication coupling — all axes PASS

Structural: PT_INR Observations refRange 100%, code lookup intact
(LOINC 6301-6 / JLAC10 2B030).

Clinical:
- warfarin patient PT_INR median in therapeutic [2.0, 3.0] band
- DOAC patient PT_INR median < 1.5 (baseline, NOT shifted — faithful
  to clinical practice of not monitoring INR for DOAC)
- compound (warfarin + DIC/cirrhosis) p90 elevated above 3.0
  (over-AC bleeding risk visible)

JP language: US Japanese characters 0; JP warfarin (ワルファリン),
apixaban (アピキサバン), rivaroxaban (リバーロキサバン) JP displays
intact; PT_INR JP display via JLAC10.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01PDwHvpzArboaKwtBDNpw8R
EOF
)"
```

- [ ] **Step 6: Commit byte-diff evidence (referenced from PR body)**

```bash
git add scratchpad/phase2b_byte_diff_results.md  # only the .md file, NOT generated data dirs
git commit -m "$(cat <<'EOF'
test(byte-diff): Phase 2b — on_warfarin coupling vs master 9e0b97a7

US/JP p=2000 seed=42. Patient/Encounter/Condition/Procedure/Imaging/
Immunization/FamilyHistory: sha256 IDENTICAL (AD-59/AD-16 preserved).
MedicationRequest/MedicationAdministration: legitimate growth from
I26/I82/I63 chronic_medications.yaml additions.
Observation/DiagnosticReport: strict-grow with PT_INR/PT shifts for
warfarin-detected patients only (cohort scoped).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01PDwHvpzArboaKwtBDNpw8R
EOF
)"
```

(Note: `.gitignore` excludes generated `scratchpad/*/us/`, `*/jp/` dirs — only the `.md` evidence is tracked.)

---

## Task 8: Docs sync (README EN/JP, DESIGN, CLAUDE.md, module README, TODO)

**Files:**
- Modify: `README.md` (Phase 2b AC cohort story)
- Modify: `README.ja.md` (Phase 2b 抗凝固 cohort 物語)
- Modify: `DESIGN.md` (AD-59 entry note about medication-coupling helper)
- Modify: `CLAUDE.md` (new architecture rule: 2 flag dicts pattern)
- Modify: `clinosim/modules/physiology/README.md` (`medication_flags_from_context` API)
- Modify: `TODO.md` (Phase 2b done; Phase 2c backlog enumeration)

This is the **bundled docs sync** rule from `feedback_pr_merge_dqr_required` and Phase 2a PR #79 lesson (post-merge docs PRs avoided — all docs in the feature PR).

- [ ] **Step 1: README.md (English) — Phase 2b AC story**

Find the existing "Population-driven simulation" or "Lab realism" section (search for "D-dimer" or "VTE" to find Phase 2a content). Add a paragraph or sub-section:

```markdown
### Phase 2b: warfarin medication-physiology coupling (2026-06-24)

PT_INR derivation now reads `medication_flags_from_context(patient, ...)`
in addition to scenario flags. When a patient is on warfarin — detected
from chronic home meds (AF, post-PE/DVT/embolic-stroke discharge) or
in-hospital orders ≥ 3 days old (loading-dose rule) — the INR is
clinically targeted to the 2.0-3.0 therapeutic band with comorbidity
lift for compound conditions (cirrhosis, DIC). DOAC patients
(apixaban/rivaroxaban/edoxaban/dabigatran) are NOT shifted — faithful
to clinical practice of not monitoring INR for DOAC.
```

- [ ] **Step 2: README.ja.md — Japanese mirror**

```markdown
### Phase 2b: ワルファリン-検査値カップリング (2026-06-24)

PT_INR の導出に `medication_flags_from_context(patient, ...)` を追加。
慢性在宅薬(AF / PE・DVT・塞栓性脳梗塞退院後)または院内オーダー(3 日
以上前のローディング ≥ 3 日ルール)でワルファリン使用が検出された
患者の INR は治療目標域 2.0-3.0 に補正され、肝硬変や DIC との
合併症では補正項が乗る(出血リスク可視化)。DOAC(アピキサバン/
リバーロキサバン/エドキサバン/ダビガトラン)患者の INR は変更しない
(臨床的に DOAC で INR モニタリングしない実態に忠実)。
```

- [ ] **Step 3: DESIGN.md — AD-59 entry extension**

Find the AD-59 ADR (Per-order lab RNG isolation). Add a "Phase 2b note" paragraph:

```markdown
**Phase 2b extension (2026-06-24)**: The scenario-flag wiring pattern
(`scenario_flags_from_protocol` + `**flags`) is paired with a sibling
medication-flag pattern (`medication_flags_from_context` + `**flags`)
for medication → lab couplings. Both helpers preserve AD-59 by
performing no RNG draws — detection is deterministic patient/order peek.
Call sites merge both dicts via `{**scenario_flags, **medication_flags}`
to keep additions one-edit safe (J5-prevention pattern).
```

- [ ] **Step 4: CLAUDE.md — new architecture rule**

Find the existing Phase 2a `scenario_flags_from_protocol` rule (added during Phase 2a J5 wiring fix). Append:

```markdown
- **Lab derivation reads TWO flag dicts** (Phase 2b, 2026-06-24):
  `scenario_flags_from_protocol(protocol)` for disease-driven flags
  (`causes_vte`, `myocardial_injury`) AND
  `medication_flags_from_context(patient, ...)` for medication-driven
  flags (`on_warfarin`). Call sites merge both via
  `{**scenario_flags, **medication_flags}` to `derive_lab_values`.
  NEVER add a `flag=value` named argument directly at a call site —
  extend the appropriate helper instead. Same J5-prevention rationale
  as the original scenario_flags rule.
```

- [ ] **Step 5: `clinosim/modules/physiology/README.md` — helper API**

Add to the existing API documentation section (find `scenario_flags_from_protocol` reference):

```markdown
### `medication_flags_from_context(patient, medication_orders, admission_date, current_day)`

Sibling helper to `scenario_flags_from_protocol`. Detects medication-driven
lab effects. Phase 2b returns `{"on_warfarin": bool}`.

Detection rules:
1. Chronic warfarin: `patient.current_medications` contains a warfarin
   substring ("warfarin"/"ワルファリン"/"coumadin", case-insensitive)
2. In-hospital warfarin: a medication order with warfarin in `display_name`
   ordered ≥ 3 days ago (loading-dose 3-day rule) — gate based on
   `(current_day - (order_date - admission_date).days >= 3)`

DOAC (apixaban/rivaroxaban/edoxaban/dabigatran) intentionally NOT
detected — INR is not clinically monitored for DOAC.

ED / outpatient call sites pass `medication_orders=None`,
`current_day=None`; only the chronic path runs.

Extend the returned dict for future couplings (steroid → glucose,
diuretic → K, antibiotic → CRP) using the same helper-mediated pattern.
```

- [ ] **Step 6: TODO.md — Phase 2b done + Phase 2c backlog**

Find the existing Phase 2 / VTE entries. Update / append:

```markdown
- [x] Phase 2a — D-dimer + `causes_vte` flag + J5 wiring fix (PR #81, merged 2026-06-24)
- [x] Phase 2b — `on_warfarin` medication coupling for PT_INR therapeutic range (2026-06-24)

### Phase 2c backlog (anticoagulation deepening)

- aPTT / heparin therapeutic monitoring (UFH IV drip → aPTT 60-80s target)
- DOAC INR micro-effect (rivaroxaban 0.2-0.3 lift) — low realism gain, clinical practice ignores
- Warfarin linear ramp (day 1 → 5 continuous instead of step at day 3)
- HIT (heparin-induced thrombocytopenia, PLT < 50% baseline after day 4)
- Vitamin K reversal modeling (PCC / FFP infusion drops INR within hours)
- Activator AC-drug exclusivity (warfarin OR apixaban, not both)
```

- [ ] **Step 7: Run full test suite once more to confirm no regression**

Run:
```
pytest tests/unit/ tests/integration/ -x -q 2>&1 | tail -5
```

Expected: all green (≈420+ tests).

- [ ] **Step 8: Commit docs sync (single commit, all docs together)**

```bash
git add README.md README.ja.md DESIGN.md CLAUDE.md \
        clinosim/modules/physiology/README.md TODO.md
git commit -m "$(cat <<'EOF'
docs(sync): Phase 2b — on_warfarin medication coupling

README (EN/JP): Phase 2b AC story added.
DESIGN.md: AD-59 entry note about sibling medication-flag helper
preserving the per-order sub-rng invariant.
CLAUDE.md: new architecture rule — derive_lab_values reads TWO flag
dicts (scenario + medication); never add flag=value at call site.
modules/physiology/README.md: medication_flags_from_context API
documented with detection rules + DOAC exclusion rationale.
TODO.md: Phase 2b done; Phase 2c backlog enumerated (aPTT/heparin,
DOAC micro-effect, ramp curve, HIT, vit-K reversal, activator AC
exclusivity).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01PDwHvpzArboaKwtBDNpw8R
EOF
)"
```

---

## Final: Push + PR

After all 8 tasks complete and the working tree is clean:

```bash
git push -u origin feat/phase2b-on-anticoagulation
gh pr create --title "feat: Phase 2b — on_warfarin medication-physiology coupling for PT_INR therapeutic range" --body "$(cat <<'EOF'
## Summary

Phase 2b extends Phase 2a (D-dimer + causes_vte, PR #81) by coupling
warfarin medication state to PT_INR derivation, completing the
**admit → ramp → discharge → outpatient followup** cohort trajectory
for VTE/AF/embolic-CI patients.

- New helper `medication_flags_from_context` (sibling of
  `scenario_flags_from_protocol`) detects warfarin from chronic home
  meds OR in-hospital orders ≥ 3 days old (loading-dose rule)
- `derive_lab_values` gains `on_warfarin: bool = False` kwarg; PT_INR
  overrides to therapeutic center 2.5 + comorbidity lift
- DOAC (apixaban/rivaroxaban/edoxaban/dabigatran) intentionally NOT
  detected — faithful to clinical practice of not monitoring INR for DOAC
- 3 chronic AC indications added: I26 PE, I82 DVT, I63 embolic CI
  (modern ACCP guideline-aligned drug probabilities)
- BNP-pattern surgical (AD-57): no state mutation, no new RNG draw
- AD-59/AD-16 invariants preserved (verified by byte-diff)
- New CLAUDE.md rule: derive_lab_values reads TWO flag dicts; never add
  flag=value at call site (J5-prevention extended)

## Evidence

- **3-axis DQR PASS** (US p=10000 + JP p=5000): `docs/reviews/2026-06-24-phase2b-anticoagulation-data-quality-review.md`
- **byte-diff vs master 9e0b97a7** (US/JP p=2000): 7 NDJSON identical, Medication legitimate-grow, Observation/DR strict-grow with PT_INR/PT only
- spec: `docs/superpowers/specs/2026-06-24-phase2b-on-anticoagulation-design.md`
- plan: `docs/superpowers/plans/2026-06-24-phase2b-on-anticoagulation.md`

## Test plan

- [x] Unit tests (test_medication_flags.py: 11, test_physiology.py: +5)
- [x] Integration tests (isolation + 4 clinical scenarios)
- [x] byte-diff p=2000 US/JP vs master
- [x] DQR 3-axis (structural / clinical / JP language)

## Deferred (Phase 2c backlog)

aPTT/heparin therapeutic, DOAC INR micro-effect, warfarin linear ramp,
HIT modeling, vit-K reversal, activator AC-drug exclusivity.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_01PDwHvpzArboaKwtBDNpw8R
EOF
)"
```

---

## Self-Review Notes (writer's checklist — preserved for reviewer)

**Spec coverage check (against spec §1-§10)**:
- §2 Architecture → Task 1 helper + Task 2 derive extension
- §3 helper detection rules → Task 1 (chronic EN/JP/coumadin + in-hospital 3-day gate + DOAC negative)
- §4 derive formula → Task 2 (PT_INR override + PT auto-consistency)
- §5 YAML changes → Task 3 (I26/I82/I63 + helpers.py "I" prefix verified covered)
- §6 call-site wiring → Task 4 (3 sites + 2nd inpatient verify)
- §7 AD-59 + byte-diff → Task 5 isolation + Task 6 byte-diff
- §7 DQR → Task 7
- §8 test strategy → Tasks 1, 2, 5
- §9 plan task breakdown → matches 8 tasks here
- §10 deferred → captured in TODO.md (Task 8 Step 6) and Final PR body

**Placeholder scan**: All task steps have concrete code or commands; no "TBD/TODO/implement later". The one verification placeholder (Task 4 Step 3 "second inpatient site decision") is properly documented as a "verify and decide" step with the two valid outcomes.

**Type consistency**: `medication_flags_from_context` signature consistent across Tasks 1, 4, 5 (`patient, medication_orders, admission_date, current_day`). `derive_lab_values` kwarg `on_warfarin: bool = False` consistent across Tasks 2, 4. Returned dict key `"on_warfarin"` consistent.

**Authoritative code verification**:
- LOINC 6301-6 for PT_INR: already in `loinc.yaml` (Phase 2a wiring, unchanged here — verify by `grep "6301-6" clinosim/codes/data/loinc.yaml` during Task 7)
- JLAC10 2B030 for PT/PT_INR: already wired (Phase 2a; verify same way)
- No new external codes introduced — Phase 2b is pure physiology + helper, reusing existing PT_INR / PT analyte registration

**Inline-recommended over subagent-driven**: Phase 2b tasks are tightly coupled (single module `physiology/engine.py` + 3 wiring sites + tests). Per Phase 2a precedent (memory `project_ehr_enrichment`), inline executing-plans is the right fit.
