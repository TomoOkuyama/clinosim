# Phase 3a HAI WBC + CRP lift Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Consume `extensions["hai"]` (from PR #89 `modules/hai`) at observation time and lift WBC + CRP via the BNP-pattern surgical formula, completing the clinical chain `HAI 発症 → 炎症マーカー 上昇` for the CDC NHSN HAI cohort (CLABSI / CAUTI / VAP).

**Architecture:** Add a new sibling helper `hai_flags_from_record(record, encounter_id, current_day) -> {"hai_inflammation_lift": float}` alongside `scenario_flags_from_protocol` + `medication_flags_from_context`. Wire all 5 `derive_lab_values` call sites with the merged `{**scenario, **medication, **hai}` dict (J5-prevention). Add one new kwarg `hai_inflammation_lift: float = 0.0` to `derive_lab_values`; compute `effective_infl = min(1.0, infl + lift)` and route it into the existing CRP + WBC formulas only. State unchanged (AD-57 BNP-pattern surgical), main RNG untouched (AD-16/AD-59 preserved).

**Tech Stack:** Python 3.11+, numpy.random.Generator (existing), pytest, PyYAML, ruff, mypy. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-06-25-phase3a-hai-lab-lift-design.md` (commit `5373b012`)

**Branch:** `feat/phase3a-hai-lab-lift` (already checked out)

## Global Constraints

- **CIF is the only simulation output** (AD-17) — never inspect FHIR adapter output during simulation logic.
- **AD-16 deterministic** — no master RNG draw inside the new helper; `hai_flags_from_record` is a deterministic peek over `record.extensions["hai"]`.
- **AD-57 BNP-pattern surgical** — `state.inflammation_level` and other `PhysiologicalState` fields are NEVER mutated; lift is applied only at observation-time inside `derive_lab_values`.
- **AD-59 preserved** — `derive_lab_values` does not change its RNG usage; `hai_inflammation_lift` is a plain float kwarg.
- **Scoped to WBC + CRP only** — all other analytes (Troponin, BNP, D-dimer, K, Cr, Fibrinogen, pO2, Ca, Temperature, SBP/DBP) continue to read `state.inflammation_level` directly. Phase 3c will revisit them as part of the sepsis cascade.
- **5-site wiring discipline** — every `derive_lab_values` call site must be updated; never add `hai_inflammation_lift=...` directly at a call site (J5-prevention rule, CLAUDE.md "scenario + medication + hai flags merge pattern").
- **Code language**: Python comments + docstrings English. CLAUDE.md / README.md / DESIGN.md / TODO.md English. JP module READMEs Japanese with English technical terms.
- **Authoritative code values** — LOINC 6690-2 (WBC) + 1988-5 (CRP) + JLAC10 2A020 (WBC) + 5C070 (CRP) are already registered (no new code data needed for Phase 3a).
- **Determinism / byte-diff** — main RNG stream untouched → all NDJSON except Observation must be **byte-IDENTICAL** vs master `42657293`; Observation is same-count with WBC + CRP values shifted in the HAI cohort only.
- **Test markers**: `@pytest.mark.unit` for unit tests, `@pytest.mark.integration` for integration tests.
- **All types in `clinosim/types/`** — no new types in Phase 3a (HAIEvent already exists from PR #89).

## File Structure

| Path | Action | Responsibility |
|---|---|---|
| `clinosim/modules/hai/reference_data/hai_lab_lift.yaml` | **Create** | CDC severity proxy: ramp_peak_days + per-type inflammation_level lift |
| `clinosim/modules/physiology/engine.py` | Modify | Add `hai_flags_from_record` helper after `medication_flags_from_context` (~line 322); add `hai_inflammation_lift: float = 0.0` kwarg to `derive_lab_values` (~line 332); route via `effective_infl` for CRP + WBC blocks only (~line 346-350) |
| `clinosim/modules/physiology/__init__.py` | Modify | Export `hai_flags_from_record` |
| `clinosim/simulator/inpatient.py` | Modify | 2 call sites: line ~579 (Pass-1 main) + line ~1706 (unknown-condition Pass-1) — merge `hai_flags_from_record(...)` into `flags` dict |
| `clinosim/simulator/emergency.py` | Modify | Line ~134 — merge `hai_flags_from_record(...)` into `_flags` dict |
| `clinosim/simulator/outpatient.py` | Modify | Line ~163 — merge `hai_flags_from_record(...)` into `_flags` dict |
| `tests/unit/test_hai_flags_from_record.py` | **Create** | 13 cases for helper (no extensions / empty / mismatch / pre-onset / ramp / full / multi-event max / config edge) |
| `tests/unit/test_derive_lab_values_hai.py` | **Create** | 8 cases for the new kwarg (baseline + lifts + clamp + descending-leg) |
| `tests/integration/test_hai_lift_wiring.py` | **Create** | J5-prevention: HAI lift visible at inpatient sites but NOT ED/outpatient sites |
| `tests/integration/test_hai_lift_clinical.py` | **Create** | Relative-delta sanity at p=2000 seed=42 |
| `scratchpad/phase3a_byte_diff.py` | **Create** | byte-diff script (Phase 2b template) |
| `scratchpad/phase3a_byte_diff_results.md` | **Create** | Evidence record |
| `scratchpad/phase3a_dqr.py` | **Create** | 3-axis DQR script |
| `docs/reviews/2026-06-25-phase3a-hai-lab-lift-data-quality-review.md` | **Create** | DQR PR evidence |
| `CLAUDE.md` | Modify | "AD-55 enricher patterns" → 3-helper merge pattern (scenario + medication + hai) |
| `MODULES.md` | Modify | hai module Consumers row → add "physiology.engine (Phase 3a observation-time lift)" |
| `SCENARIO_FLAGS.md` | Modify | Add `hai_inflammation_lift` to flags table, update helper architecture, refresh "Adding a new flag" guide |
| `clinosim/modules/hai/README.md` | Modify | Add "Phase 3a: observation-time WBC/CRP lift" section |
| `clinosim/modules/physiology/README.md` | Modify | Add `hai_flags_from_record` to public API |
| `DESIGN.md` | Modify | AD-55 entry → mention Phase 3a observation-time consume pattern; AD-57 entry → add Phase 3a as 4th BNP-pattern surgical example |
| `TODO.md` | Modify | Phase 3a → done; add Phase 3b (antibiotic / S-I-R / decay) + Phase 3c (mortality / sepsis cascade) entries |
| `README.md` / `README.ja.md` | Modify | Quality & Compliance section → add Phase 3a DQR reference link |

---

## Task 1: `hai_lab_lift.yaml` + `hai_flags_from_record` helper + unit tests

**Files:**
- Create: `clinosim/modules/hai/reference_data/hai_lab_lift.yaml`
- Modify: `clinosim/modules/physiology/engine.py` (add helper after `medication_flags_from_context` at ~line 322)
- Modify: `clinosim/modules/physiology/__init__.py` (export)
- Create: `tests/unit/test_hai_flags_from_record.py`

**Interfaces:**
- Consumes:
  - `CIFPatientRecord` (from `clinosim.types.patient`) with optional `extensions["hai"]: list[HAIEvent]`
  - `HAIEvent` (from `clinosim.types.hai`) with fields `hai_id`, `encounter_id`, `hai_type`, `onset_date: str`
- Produces:
  ```python
  def hai_flags_from_record(
      record,                       # CIFPatientRecord
      encounter_id: str | None,     # current encounter; None returns 0.0
      current_day,                  # datetime.date | None; None returns 0.0
  ) -> dict[str, float]:
      # Returns {"hai_inflammation_lift": float in [0.0, max_lift]}
  ```

- [ ] **Step 1: Create `hai_lab_lift.yaml`**

```yaml
# clinosim/modules/hai/reference_data/hai_lab_lift.yaml
# Phase 3a: HAI WBC + CRP lift via inflammation_level offset.
# Read at observation time by physiology.engine.hai_flags_from_record.
#
# CDC NHSN clinical severity proxy:
#   CLABSI = bacteremia       (strong systemic response)
#   VAP    = severe pneumonia (strong systemic response)
#   CAUTI  = urinary tract    (moderate, often localized)
#
# Calibration (baseline infl=0.4, typical inpatient):
#   CLABSI/VAP lift 0.35 → effective_infl=0.75 → CRP ~169 mg/L, WBC ~16,000
#   CAUTI       lift 0.20 → effective_infl=0.60 → CRP ~87 mg/L,  WBC ~14,200
#
# Ramp: lift_factor = min(1.0, max(0, days_since_onset) / ramp_peak_days)
#   day 0 (onset)  → 0.0 lift
#   day 1          → 0.5 lift
#   day 2+ (peak)  → 1.0 lift (no decay in Phase 3a; antibiotic chain → Phase 3b)
ramp_peak_days: 2

hai_lift:
  CLABSI: 0.35
  VAP:    0.35
  CAUTI:  0.20
```

- [ ] **Step 2: Write the failing test file**

Create `tests/unit/test_hai_flags_from_record.py`:

```python
"""Unit tests for `hai_flags_from_record` — Phase 3a HAI WBC + CRP lift.

Covers the 3-helper merge architecture (scenario + medication + hai) and the
ramp / encounter-scope / multi-event semantics required by the spec.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from types import SimpleNamespace

import pytest

from clinosim.modules.physiology.engine import hai_flags_from_record
from clinosim.types.hai import HAIEvent


def _make_event(
    encounter_id: str,
    hai_type: str = "CLABSI",
    onset_date: str = "2026-01-10",
    hai_id: str = "hai-1",
) -> HAIEvent:
    return HAIEvent(
        hai_id=hai_id,
        encounter_id=encounter_id,
        hai_type=hai_type,
        source_device_id="dev-1",
        icd10_code="T80.211A",
        snomed_code="736442006",
        onset_date=onset_date,
        organism_snomed="3092008",
        culture_specimen_id="spec-1",
    )


def _record(events: list[HAIEvent] | None) -> SimpleNamespace:
    extensions = {} if events is None else {"hai": events}
    return SimpleNamespace(extensions=extensions)


@pytest.mark.unit
def test_no_extensions_returns_zero():
    record = SimpleNamespace(extensions={})
    assert hai_flags_from_record(record, "enc-X", date(2026, 1, 12)) == {
        "hai_inflammation_lift": 0.0
    }


@pytest.mark.unit
def test_empty_list_returns_zero():
    assert hai_flags_from_record(_record([]), "enc-X", date(2026, 1, 12)) == {
        "hai_inflammation_lift": 0.0
    }


@pytest.mark.unit
def test_encounter_mismatch_returns_zero():
    record = _record([_make_event("enc-OTHER")])
    assert hai_flags_from_record(record, "enc-X", date(2026, 1, 12)) == {
        "hai_inflammation_lift": 0.0
    }


@pytest.mark.unit
def test_pre_onset_returns_zero():
    record = _record([_make_event("enc-X", onset_date="2026-01-15")])
    assert hai_flags_from_record(record, "enc-X", date(2026, 1, 10)) == {
        "hai_inflammation_lift": 0.0
    }


@pytest.mark.unit
def test_onset_day_clabsi_ramp_zero():
    """day 0 → ramp_factor = 0/2 = 0.0 → lift = 0.0"""
    record = _record([_make_event("enc-X", onset_date="2026-01-10")])
    flags = hai_flags_from_record(record, "enc-X", date(2026, 1, 10))
    assert flags["hai_inflammation_lift"] == pytest.approx(0.0)


@pytest.mark.unit
def test_mid_ramp_clabsi_half_lift():
    """day 1 → ramp_factor = 1/2 = 0.5 → lift = 0.35 * 0.5 = 0.175"""
    record = _record([_make_event("enc-X", onset_date="2026-01-10")])
    flags = hai_flags_from_record(record, "enc-X", date(2026, 1, 11))
    assert flags["hai_inflammation_lift"] == pytest.approx(0.175)


@pytest.mark.unit
def test_full_lift_clabsi_day_2():
    """day 2 → ramp_factor = 1.0 → full lift 0.35"""
    record = _record([_make_event("enc-X", onset_date="2026-01-10")])
    flags = hai_flags_from_record(record, "enc-X", date(2026, 1, 12))
    assert flags["hai_inflammation_lift"] == pytest.approx(0.35)


@pytest.mark.unit
def test_flat_after_peak_no_decay():
    """day 7 → still 1.0 ramp factor (no decay in Phase 3a)"""
    record = _record([_make_event("enc-X", onset_date="2026-01-10")])
    flags = hai_flags_from_record(record, "enc-X", date(2026, 1, 17))
    assert flags["hai_inflammation_lift"] == pytest.approx(0.35)


@pytest.mark.unit
def test_cauti_lift_value():
    record = _record(
        [_make_event("enc-X", hai_type="CAUTI", onset_date="2026-01-10")]
    )
    flags = hai_flags_from_record(record, "enc-X", date(2026, 1, 12))
    assert flags["hai_inflammation_lift"] == pytest.approx(0.20)


@pytest.mark.unit
def test_vap_lift_value():
    record = _record(
        [_make_event("enc-X", hai_type="VAP", onset_date="2026-01-10")]
    )
    flags = hai_flags_from_record(record, "enc-X", date(2026, 1, 12))
    assert flags["hai_inflammation_lift"] == pytest.approx(0.35)


@pytest.mark.unit
def test_multi_event_takes_max():
    """CLABSI 0.35 + CAUTI 0.20 same encounter day 2 → max = 0.35"""
    events = [
        _make_event("enc-X", hai_type="CLABSI", onset_date="2026-01-10", hai_id="h1"),
        _make_event("enc-X", hai_type="CAUTI", onset_date="2026-01-10", hai_id="h2"),
    ]
    flags = hai_flags_from_record(_record(events), "enc-X", date(2026, 1, 12))
    assert flags["hai_inflammation_lift"] == pytest.approx(0.35)


@pytest.mark.unit
def test_encounter_id_none_returns_zero():
    record = _record([_make_event("enc-X")])
    assert hai_flags_from_record(record, None, date(2026, 1, 12)) == {
        "hai_inflammation_lift": 0.0
    }


@pytest.mark.unit
def test_current_day_none_returns_zero():
    record = _record([_make_event("enc-X", onset_date="2026-01-10")])
    assert hai_flags_from_record(record, "enc-X", None) == {
        "hai_inflammation_lift": 0.0
    }
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
pytest tests/unit/test_hai_flags_from_record.py -v
```
Expected: ImportError / "cannot import name 'hai_flags_from_record'".

- [ ] **Step 4: Implement the helper in `physiology/engine.py`**

Insert at the end of the existing helper block (after `medication_flags_from_context` returns at line ~320, before `def derive_lab_values` at line ~323):

```python
@lru_cache(maxsize=1)
def _load_hai_lift_config() -> tuple[float, dict[str, float]]:
    """Load `modules/hai/reference_data/hai_lab_lift.yaml` once."""
    import clinosim.modules.hai as _hai_pkg  # local import to avoid cycle

    cfg_path = Path(_hai_pkg.__file__).parent / "reference_data" / "hai_lab_lift.yaml"
    data = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    return float(data["ramp_peak_days"]), dict(data["hai_lift"])


def hai_flags_from_record(
    record,
    encounter_id: str | None,
    current_day,
) -> dict[str, float]:
    """Detect HAI-driven inflammation lift from `extensions["hai"]` context.

    Phase 3a sibling of `scenario_flags_from_protocol` and
    `medication_flags_from_context`. Centralises the HAI → lab coupling reads
    so new HAI lift dimensions added to `derive_lab_values` only need wiring
    in ONE place (J5-prevention). Dict keys match `derive_lab_values`
    parameter names so callers can spread with ``**flags``.

    Returns 0.0 lift when:
      - record has no ``extensions["hai"]`` (HAI module disabled / non-HAI)
      - ``encounter_id`` is ``None``
      - ``current_day`` is ``None``
      - no event matches ``encounter_id``
      - all matching events have ``onset_date > current_day`` (pre-onset)

    Otherwise returns ``max(lift_value * ramp_factor)`` over matching events:
      ramp_factor = min(1.0, max(0, days_since_onset) / ramp_peak_days)
      lift_value  = hai_lab_lift.yaml[hai_type]   # CLABSI=0.35, VAP=0.35, CAUTI=0.20

    Read-only consume of PR #89 ``extensions["hai"]``; never mutates state.
    """
    if encounter_id is None or current_day is None:
        return {"hai_inflammation_lift": 0.0}

    events = (getattr(record, "extensions", None) or {}).get("hai", [])
    if not events:
        return {"hai_inflammation_lift": 0.0}

    ramp_peak_days, lift_table = _load_hai_lift_config()
    best = 0.0
    for ev in events:
        if getattr(ev, "encounter_id", None) != encounter_id:
            continue
        onset_str = getattr(ev, "onset_date", None)
        if not onset_str:
            continue
        try:
            onset_dt = date.fromisoformat(onset_str)
        except (TypeError, ValueError):
            continue
        days_since = (current_day - onset_dt).days
        if days_since < 0:
            continue
        ramp_factor = min(1.0, days_since / ramp_peak_days) if ramp_peak_days > 0 else 1.0
        lift_value = lift_table.get(getattr(ev, "hai_type", ""), 0.0)
        effective = lift_value * ramp_factor
        if effective > best:
            best = effective
    return {"hai_inflammation_lift": best}
```

Required imports (verify at top of `engine.py`, add if missing):

```python
from datetime import date
from functools import lru_cache
from pathlib import Path

import yaml
```

- [ ] **Step 5: Export the helper from `physiology/__init__.py`**

Open `clinosim/modules/physiology/__init__.py`, find the export block listing `scenario_flags_from_protocol` + `medication_flags_from_context`, and add `hai_flags_from_record` to both the import and `__all__`:

```python
from clinosim.modules.physiology.engine import (
    apply_coupling_rules,
    apply_disease_onset,
    derive_lab_values,
    derive_observed_vitals,
    derive_vital_signs,
    hai_flags_from_record,     # ← NEW
    initialize_state,
    medication_flags_from_context,
    scenario_flags_from_protocol,
)

__all__ = [
    "apply_coupling_rules",
    "apply_disease_onset",
    "derive_lab_values",
    "derive_observed_vitals",
    "derive_vital_signs",
    "hai_flags_from_record",   # ← NEW
    "initialize_state",
    "medication_flags_from_context",
    "scenario_flags_from_protocol",
]
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
pytest tests/unit/test_hai_flags_from_record.py -v
```
Expected: 13 passed.

- [ ] **Step 7: Commit**

```bash
git add clinosim/modules/hai/reference_data/hai_lab_lift.yaml \
        clinosim/modules/physiology/engine.py \
        clinosim/modules/physiology/__init__.py \
        tests/unit/test_hai_flags_from_record.py
git commit -m "$(cat <<'EOF'
feat(phase3a): hai_flags_from_record helper + hai_lab_lift.yaml (Task 1)

New sibling of scenario_flags_from_protocol + medication_flags_from_context.
Reads extensions["hai"] (from PR #89), filters by encounter_id, returns
max(lift_value * ramp_factor) for matching events; 0.0 for empty / pre-onset.

CDC severity proxy (hai_lab_lift.yaml): CLABSI/VAP=0.35, CAUTI=0.20,
ramp_peak_days=2 (CRP ~48h peak realism).

13 unit tests cover: empty / mismatch / pre-onset / ramp 0.0|0.5|1.0 /
flat after peak / per-type values / multi-event max / None edge cases.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UCerE4zz2NfW87r3MnbDrd
EOF
)"
```

---

## Task 2: Extend `derive_lab_values` with `hai_inflammation_lift` kwarg + unit tests

**Files:**
- Modify: `clinosim/modules/physiology/engine.py` (extend `derive_lab_values` signature + CRP/WBC blocks at ~line 323-350)
- Create: `tests/unit/test_derive_lab_values_hai.py`

**Interfaces:**
- Consumes: `PhysiologicalState`, output of `hai_flags_from_record`
- Produces:
  ```python
  def derive_lab_values(
      state, sex, age,
      has_diabetes=False,
      rng=None, hour=6,
      myocardial_injury=False,
      causes_vte=False,
      on_warfarin=False,
      hai_inflammation_lift: float = 0.0,   # ← NEW
  ) -> dict[str, float]:
      # CRP + WBC computed with effective_infl = min(1.0, state.inflammation_level + hai_inflammation_lift)
      # All other analytes continue to read state.inflammation_level directly.
  ```

- [ ] **Step 1: Write the failing test file**

Create `tests/unit/test_derive_lab_values_hai.py`:

```python
"""Unit tests for `derive_lab_values` hai_inflammation_lift kwarg (Phase 3a).

All expected values are computed from the formulas in the spec §4:
  effective_infl = min(1.0, infl + lift)
  CRP = 0.3 + 400 * effective_infl ** 3
  WBC (≤0.8) = 7000 + effective_infl * 12000
  WBC (>0.8) = max(1500, 7000 + 0.8*12000 - (effective_infl - 0.8) * 30000)

Validates that ONLY CRP + WBC respond to the lift; all other analytes
continue to read state.inflammation_level directly (Phase 3c scope guard).
"""
from __future__ import annotations

import pytest

from clinosim.modules.physiology.engine import derive_lab_values
from clinosim.types.physiology import PhysiologicalState


def _state(infl: float) -> PhysiologicalState:
    return PhysiologicalState(
        inflammation_level=infl,
        renal_function=1.0,
        cardiac_function=1.0,
        hepatic_function=1.0,
        anemia_level=0.0,
        perfusion_status=0.0,
        ph_status=0.0,
        respiratory_fraction=0.0,
        volume_status=0.0,
        coagulation_status=0.0,
        sodium_status=0.0,
        glycemic_control=0.0,
        platelet_status=0.0,
    )


@pytest.mark.unit
def test_baseline_no_lift_unchanged():
    labs = derive_lab_values(_state(0.4), sex="M", age=60)
    # baseline CRP = 0.3 + 400 * 0.4**3 = 25.9
    assert labs["CRP"] == pytest.approx(25.9, abs=0.1)
    # baseline WBC = 7000 + 0.4 * 12000 = 11,800
    assert labs["WBC"] == pytest.approx(11800.0, abs=1.0)


@pytest.mark.unit
def test_baseline_with_clabsi_full_lift():
    labs = derive_lab_values(_state(0.4), sex="M", age=60, hai_inflammation_lift=0.35)
    # effective_infl = 0.75 → CRP = 0.3 + 400 * 0.75**3 = 169.0
    assert labs["CRP"] == pytest.approx(169.0, abs=0.5)
    # WBC = 7000 + 0.75 * 12000 = 16,000
    assert labs["WBC"] == pytest.approx(16000.0, abs=1.0)


@pytest.mark.unit
def test_baseline_with_cauti_full_lift():
    labs = derive_lab_values(_state(0.4), sex="M", age=60, hai_inflammation_lift=0.20)
    # effective_infl = 0.60 → CRP = 0.3 + 400 * 0.6**3 = 86.7
    assert labs["CRP"] == pytest.approx(86.7, abs=0.5)
    # WBC = 7000 + 0.6 * 12000 = 14,200
    assert labs["WBC"] == pytest.approx(14200.0, abs=1.0)


@pytest.mark.unit
def test_baseline_with_mid_ramp_clabsi():
    labs = derive_lab_values(_state(0.4), sex="M", age=60, hai_inflammation_lift=0.175)
    # effective_infl = 0.575 → CRP = 0.3 + 400 * 0.575**3 = 76.3
    assert labs["CRP"] == pytest.approx(76.3, abs=0.5)
    # WBC = 7000 + 0.575 * 12000 = 13,900
    assert labs["WBC"] == pytest.approx(13900.0, abs=1.0)


@pytest.mark.unit
def test_clamp_at_high_infl_plus_max_lift():
    labs = derive_lab_values(_state(0.8), sex="M", age=60, hai_inflammation_lift=0.35)
    # effective_infl clamped to 1.0 → CRP = 0.3 + 400 * 1.0**3 = 400.3
    assert labs["CRP"] == pytest.approx(400.3, abs=0.5)
    # WBC (>0.8 leg): 7000 + 9600 - (1.0 - 0.8) * 30000 = 16600 - 6000 = 10,600
    assert labs["WBC"] == pytest.approx(10600.0, abs=1.0)


@pytest.mark.unit
def test_high_infl_no_lift_for_comparison():
    labs = derive_lab_values(_state(0.95), sex="M", age=60, hai_inflammation_lift=0.0)
    # CRP = 0.3 + 400 * 0.95**3 = 343.2
    assert labs["CRP"] == pytest.approx(343.2, abs=0.5)
    # WBC = max(1500, 16600 - 0.15 * 30000) = 12,100
    assert labs["WBC"] == pytest.approx(12100.0, abs=1.0)


@pytest.mark.unit
def test_high_infl_with_lift_descending_leg():
    """immune-exhaustion curve: high infl + lift LOWERS WBC vs same infl alone."""
    labs = derive_lab_values(_state(0.95), sex="M", age=60, hai_inflammation_lift=0.35)
    # effective_infl clamped 1.0 → CRP 400.3, WBC 10,600
    assert labs["CRP"] == pytest.approx(400.3, abs=0.5)
    assert labs["WBC"] == pytest.approx(10600.0, abs=1.0)


@pytest.mark.unit
def test_zero_infl_with_clabsi_lift():
    labs = derive_lab_values(_state(0.0), sex="M", age=60, hai_inflammation_lift=0.35)
    # effective_infl = 0.35 → CRP = 0.3 + 400 * 0.35**3 = 17.4
    assert labs["CRP"] == pytest.approx(17.4, abs=0.5)
    # WBC = 7000 + 0.35 * 12000 = 11,200
    assert labs["WBC"] == pytest.approx(11200.0, abs=1.0)


@pytest.mark.unit
def test_other_analytes_unaffected_by_lift():
    """Phase 3a scope guard: only WBC + CRP respond. All others use state.inflammation_level."""
    labs_no_lift = derive_lab_values(_state(0.4), sex="M", age=60, hai_inflammation_lift=0.0)
    labs_lifted = derive_lab_values(_state(0.4), sex="M", age=60, hai_inflammation_lift=0.35)
    for key in labs_no_lift:
        if key in ("CRP", "WBC", "PCT", "Albumin"):
            # PCT + Albumin also use infl, so SKIP (not in scope of this guard test
            # though spec keeps them on state.inflammation_level — they will be
            # picked up if we accidentally rewire them to effective_infl).
            continue
        assert labs_no_lift[key] == pytest.approx(labs_lifted[key], rel=1e-9), (
            f"{key} unexpectedly changed with hai lift "
            f"({labs_no_lift[key]} → {labs_lifted[key]}); Phase 3a scope is WBC+CRP only"
        )


@pytest.mark.unit
def test_pct_and_albumin_remain_on_state_infl():
    """PCT and Albumin currently read state.inflammation_level directly.
    Phase 3a does NOT rewire them — they stay on baseline infl per spec §4.
    """
    labs_no_lift = derive_lab_values(_state(0.4), sex="M", age=60, hai_inflammation_lift=0.0)
    labs_lifted = derive_lab_values(_state(0.4), sex="M", age=60, hai_inflammation_lift=0.35)
    assert labs_no_lift["PCT"] == pytest.approx(labs_lifted["PCT"], rel=1e-9)
    assert labs_no_lift["Albumin"] == pytest.approx(labs_lifted["Albumin"], rel=1e-9)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/unit/test_derive_lab_values_hai.py -v
```
Expected: 10 FAIL with `unexpected keyword argument 'hai_inflammation_lift'` (or assertion failures if the kwarg silently lands but the formulas haven't been rewired).

- [ ] **Step 3: Extend `derive_lab_values` signature**

In `clinosim/modules/physiology/engine.py` ~line 323-333, modify the signature:

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
    hai_inflammation_lift: float = 0.0,   # ← NEW
) -> dict[str, float]:
    """Derive lab values from physiological state. Returns 'true' values before noise."""
```

- [ ] **Step 4: Add `effective_infl` and rewire CRP + WBC blocks**

In the same function, replace the CRP + WBC block at ~line 344-350:

```python
    # --- Inflammation ---
    # Phase 3a: HAI WBC + CRP lift via effective_infl. Other analytes
    # (PCT, Albumin, Fibrinogen, pO2, Ca, Temp, SBP/DBP) continue to read
    # state.inflammation_level directly; they will be revisited in Phase 3c.
    effective_infl = min(1.0, infl + hai_inflammation_lift)
    # CRP: effective_infl 0→0.3, 0.4→26, 0.6→87, 0.75→169, 1.0→400 mg/L
    labs["CRP"] = 0.3 + 400 * effective_infl ** 3
    if effective_infl < 0.8:
        labs["WBC"] = 7000 + effective_infl * 12000
    else:
        labs["WBC"] = max(1500, 7000 + 0.8 * 12000 - (effective_infl - 0.8) * 30000)
    labs["PCT"] = 0.03 * math.exp(infl * 7)
    labs["Albumin"] = max(1.0, 4.2 - infl * 2.0 - (1 - hepatic) * 1.5)
```

Note: `PCT` + `Albumin` lines INTENTIONALLY keep `infl` (state.inflammation_level), not `effective_infl`. This is the Phase 3a scope guard.

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/unit/test_derive_lab_values_hai.py -v
```
Expected: 10 passed.

- [ ] **Step 6: Run the broader physiology unit tests to verify no regression**

```bash
pytest tests/unit/test_derive_lab_values.py tests/unit/test_physiology_engine.py -v 2>&1 | tail -20
```
Expected: all existing tests still pass (CRP + WBC defaults are unchanged when `hai_inflammation_lift=0.0`).

- [ ] **Step 7: Commit**

```bash
git add clinosim/modules/physiology/engine.py tests/unit/test_derive_lab_values_hai.py
git commit -m "$(cat <<'EOF'
feat(phase3a): derive_lab_values hai_inflammation_lift kwarg (Task 2)

New kwarg with default 0.0 (backwards compatible). Computes
effective_infl = min(1.0, infl + lift) and routes ONLY into CRP + WBC
formulas; PCT, Albumin and all other analytes continue to read
state.inflammation_level directly (Phase 3a scope guard, Phase 3c will
revisit sepsis cascade).

10 unit tests cover: baseline / CLABSI / CAUTI / mid-ramp / clamp /
high-infl descending leg / scope guard (other analytes unaffected).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UCerE4zz2NfW87r3MnbDrd
EOF
)"
```

---

## Task 3: Call-site wiring (5 sites)

**Files:**
- Modify: `clinosim/simulator/inpatient.py` (line ~579 Pass-1 main + line ~585 lagged shares same `flags` + line ~1706 unknown)
- Modify: `clinosim/simulator/emergency.py` (line ~134)
- Modify: `clinosim/simulator/outpatient.py` (line ~163)

**Interfaces:**
- Consumes: `hai_flags_from_record` (Task 1), `derive_lab_values` (Task 2)
- Produces: All 5 sites pass `hai_inflammation_lift` via the merged `flags` dict; no site adds `hai_inflammation_lift=...` directly.

- [ ] **Step 1: Wire `inpatient.py` Pass-1 main (line ~579)**

Find the existing block at ~line 575-580. Currently:

```python
flags = {
    **scenario_flags_from_protocol(protocol),
    **medication_flags_from_context(patient, all_orders, admission_date, day_into_stay),
}
true_labs = derive_lab_values(state, sex=patient.sex, age=patient.age,
                              has_diabetes=has_diabetes, hour=lab_hour, **flags)
```

Modify to merge HAI flags. The `lagged_labs` call at line ~585 reuses the same `flags` dict — no separate change needed:

```python
flags = {
    **scenario_flags_from_protocol(protocol),
    **medication_flags_from_context(patient, all_orders, admission_date, day_into_stay),
    **hai_flags_from_record(record, encounter.id, day_date),  # ← NEW
}
true_labs = derive_lab_values(state, sex=patient.sex, age=patient.age,
                              has_diabetes=has_diabetes, hour=lab_hour, **flags)
```

Verify the imports at the top of `inpatient.py` include `hai_flags_from_record`:

```python
from clinosim.modules.physiology import (
    ...,
    hai_flags_from_record,   # ← add if missing
    ...,
)
```

Also verify the variable names: `record` is the `CIFPatientRecord` for the patient being simulated, `encounter` is the current encounter (use `encounter.id` or whatever the field is — check at line ~570 for the local name), `day_date` is the current calendar day (or `current_date`, check the surrounding loop variable). **Read 10 lines above line 579 to identify the exact local names before editing.**

- [ ] **Step 2: Wire `inpatient.py` unknown-condition Pass-1 (line ~1706)**

Find the block at ~line 1700-1710. Currently:

```python
_flags_unknown = {
    **scenario_flags_from_protocol(protocol),                                  # protocol may be None
    **medication_flags_from_context(patient, None, None, None),                # chronic-meds-only path
}
true_labs = derive_lab_values(state, sex=patient.sex, age=patient.age,
                              has_diabetes=has_diabetes, **_flags_unknown)
```

Modify:

```python
_flags_unknown = {
    **scenario_flags_from_protocol(protocol),
    **medication_flags_from_context(patient, None, None, None),
    **hai_flags_from_record(record, encounter.id, day_date),  # ← NEW
}
true_labs = derive_lab_values(state, sex=patient.sex, age=patient.age,
                              has_diabetes=has_diabetes, **_flags_unknown)
```

Same caveat as Step 1: **read 10 lines above line 1706** to confirm the exact local names of `record`, `encounter`, and the day variable.

- [ ] **Step 3: Wire `emergency.py` (line ~134)**

Find the block:

```python
_flags = {
    **scenario_flags_from_protocol(protocol),
    **medication_flags_from_context(patient, None, None, None),
}
_true_labs = derive_lab_values(_state, sex=patient.sex, age=patient.age,
                               has_diabetes=_has_dm, **_flags)
```

Modify:

```python
_flags = {
    **scenario_flags_from_protocol(protocol),
    **medication_flags_from_context(patient, None, None, None),
    **hai_flags_from_record(record, _encounter_id, _visit_date),  # ← NEW; naturally 0.0 for ED (no HAI events)
}
_true_labs = derive_lab_values(_state, sex=patient.sex, age=patient.age,
                               has_diabetes=_has_dm, **_flags)
```

**Read 10 lines above line 134** in `emergency.py` to identify the exact local names for `record`, the encounter id (`_encounter_id` / `encounter.id` / `enc_id`), and the visit date variable.

Add the import if missing.

- [ ] **Step 4: Wire `outpatient.py` (line ~163)**

Same shape as `emergency.py`. Find the block, add `**hai_flags_from_record(record, _encounter_id, _visit_date)` to `_flags`, and ensure the import is present. **Read 10 lines above line 163** for exact local names.

- [ ] **Step 5: Run targeted regression on the simulator path**

```bash
pytest tests/unit/test_simulator_inpatient.py tests/unit/test_simulator_emergency.py tests/unit/test_simulator_outpatient.py -v 2>&1 | tail -10
pytest tests/integration/test_individual_lab_isolation.py -v 2>&1 | tail -5
```
Expected: all pass (no HAI events present in test fixtures → `hai_inflammation_lift=0.0` → identical to pre-PR behaviour).

- [ ] **Step 6: Commit**

```bash
git add clinosim/simulator/inpatient.py clinosim/simulator/emergency.py clinosim/simulator/outpatient.py
git commit -m "$(cat <<'EOF'
feat(phase3a): wire hai_flags_from_record into 5 derive_lab_values sites (Task 3)

5 sites (inpatient Pass-1 main + Pass-1 lagged shares same flags dict +
unknown-condition Pass-1, emergency ED, outpatient followup) now merge:
  {**scenario_flags, **medication_flags, **hai_flags}

ED/outpatient sites pass record + encounter_id + visit_date but naturally
return 0.0 lift because HAI events only exist on inpatient ICU encounters
(modules/hai gating). The wiring is uniform across all 5 sites to keep
the "flag goes via helper, never as a kwarg at the call site" invariant
honoured (J5-prevention extended for HAI couplings).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UCerE4zz2NfW87r3MnbDrd
EOF
)"
```

---

## Task 4: Integration tests — J5 wiring + clinical relative-delta

**Files:**
- Create: `tests/integration/test_hai_lift_wiring.py`
- Create: `tests/integration/test_hai_lift_clinical.py`

**Interfaces:**
- Consumes: full simulator pipeline (run_beta / generate)
- Produces: J5-prevention regression guard + relative-delta sanity check

- [ ] **Step 1: Write the J5 wiring integration test**

Create `tests/integration/test_hai_lift_wiring.py`:

```python
"""Integration test: HAI lift wiring (J5-prevention).

Verifies every `derive_lab_values` call site reads hai_flags_from_record
via the {**flags} merge. The test inspects the source files for the
literal `hai_flags_from_record` call, then runs a minimal simulator
trace to confirm HAI cohort labs are lifted at inpatient sites and NOT
at ED/outpatient sites (because HAI events are inpatient-only).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

SITES = [
    "clinosim/simulator/inpatient.py",
    "clinosim/simulator/emergency.py",
    "clinosim/simulator/outpatient.py",
]


@pytest.mark.integration
def test_all_derive_lab_values_sites_call_hai_flags_helper():
    """Static check: every site that calls derive_lab_values must also call
    hai_flags_from_record. Catches J5-style wiring defects at PR time."""
    repo_root = Path(__file__).resolve().parents[2]
    for rel in SITES:
        src = (repo_root / rel).read_text(encoding="utf-8")
        derive_calls = src.count("derive_lab_values(")
        hai_calls = src.count("hai_flags_from_record(")
        assert hai_calls >= derive_calls or hai_calls >= 1, (
            f"{rel}: derive_lab_values called {derive_calls}x but "
            f"hai_flags_from_record called {hai_calls}x — J5 wiring defect"
        )


@pytest.mark.integration
def test_no_site_passes_hai_lift_directly():
    """Static check: no site may pass hai_inflammation_lift=... directly.
    All sites must go via the {**flags} merge from hai_flags_from_record."""
    repo_root = Path(__file__).resolve().parents[2]
    pattern = re.compile(r"hai_inflammation_lift\s*=")
    for rel in SITES:
        src = (repo_root / rel).read_text(encoding="utf-8")
        violations = pattern.findall(src)
        assert not violations, (
            f"{rel}: hai_inflammation_lift passed as direct kwarg "
            f"(violations: {len(violations)}). Extend hai_flags_from_record instead."
        )
```

- [ ] **Step 2: Write the clinical integration test**

Create `tests/integration/test_hai_lift_clinical.py`:

```python
"""Integration test: HAI cohort vs non-HAI baseline relative-delta sanity.

Runs a small US p=300 simulation and asserts that the HAI inpatient cohort
shows elevated WBC + CRP relative to the non-HAI inpatient cohort. This is
a sanity check (not the full DQR); the proper DQR runs at p=10000.

Skipped if the small cohort produces 0 HAI events (Poisson rare-event tail,
expected ~0.3 HAI at p=300).
"""
from __future__ import annotations

import statistics
from collections.abc import Iterable

import pytest

from clinosim.simulator import run_beta


def _filter_inpatient_labs(records, want_hai: bool) -> tuple[list[float], list[float]]:
    """Return (WBC list, CRP list) for inpatient encounters that match the want_hai flag."""
    wbc, crp = [], []
    for rec in records:
        hai_encounters = {e.encounter_id for e in rec.extensions.get("hai", [])}
        for enc in getattr(rec, "encounters", []):
            if getattr(enc, "encounter_class", "") != "inpatient":
                continue
            is_hai = enc.id in hai_encounters
            if is_hai != want_hai:
                continue
            for obs in getattr(enc, "lab_results", []):
                name = getattr(obs, "test_name", "")
                val = getattr(obs, "value_numeric", None)
                if val is None:
                    continue
                if name == "WBC":
                    wbc.append(val)
                elif name == "CRP":
                    crp.append(val)
    return wbc, crp


@pytest.mark.integration
def test_hai_cohort_shows_wbc_crp_lift_p300():
    """At p=300 seed=42, HAI cohort WBC p50 should exceed non-HAI by a
    measurable margin; if 0 HAI events in this small cohort, SKIP."""
    records = run_beta(
        population=300,
        country="US",
        seed=42,
        modules={"hai": True, "device": True, "identity": False},
    )
    hai_wbc, hai_crp = _filter_inpatient_labs(records, want_hai=True)
    non_wbc, non_crp = _filter_inpatient_labs(records, want_hai=False)

    if len(hai_wbc) < 5:
        pytest.skip(f"Insufficient HAI lab observations (n={len(hai_wbc)}) at p=300 (Poisson rare).")

    assert statistics.median(hai_wbc) > statistics.median(non_wbc), (
        f"HAI WBC p50 {statistics.median(hai_wbc):.0f} should exceed non-HAI "
        f"p50 {statistics.median(non_wbc):.0f}"
    )
    assert statistics.median(hai_crp) > statistics.median(non_crp), (
        f"HAI CRP p50 {statistics.median(hai_crp):.1f} should exceed non-HAI "
        f"p50 {statistics.median(non_crp):.1f}"
    )
```

**Note:** The exact `run_beta` signature may differ (e.g. modules might be passed via `SimulatorConfig`). **Read `tests/integration/test_hai_module_*.py` first to copy the precise invocation pattern** before finalizing this test.

- [ ] **Step 3: Run integration tests**

```bash
pytest tests/integration/test_hai_lift_wiring.py tests/integration/test_hai_lift_clinical.py -v 2>&1 | tail -10
```
Expected: 3 passed (wiring x2 + clinical, or clinical may SKIP).

- [ ] **Step 4: Run the full unit + integration suite to confirm no regression**

```bash
pytest -m "unit or integration" -x 2>&1 | tail -10
```
Expected: all previously-green tests still pass.

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_hai_lift_wiring.py tests/integration/test_hai_lift_clinical.py
git commit -m "$(cat <<'EOF'
test(phase3a): integration tests — J5 wiring + clinical relative-delta (Task 4)

test_hai_lift_wiring.py: static guards that every site calling
derive_lab_values also calls hai_flags_from_record, and that no site
passes hai_inflammation_lift= directly (J5-prevention).

test_hai_lift_clinical.py: small p=300 cohort sanity-check that HAI WBC/CRP
p50 exceeds non-HAI baseline. SKIPs if too few HAI events (Poisson rare).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UCerE4zz2NfW87r3MnbDrd
EOF
)"
```

---

## Task 5: byte-diff verification (US/JP p=2000 vs master `42657293`)

**Files:**
- Create: `scratchpad/phase3a_byte_diff.py`
- Create: `scratchpad/phase3a_byte_diff_results.md`

**Interfaces:**
- Consumes: master generation output (read from `scratchpad/phase3a_byte_diff/master/`), branch generation output (read from `scratchpad/phase3a_byte_diff/branch/`)
- Produces: per-NDJSON sha256 + line-count comparison, results recorded in markdown

- [ ] **Step 1: Generate branch output FIRST (working tree is on feat/phase3a-hai-lab-lift)**

Before generating master we need to confirm the exact CLI invocation pattern this repo uses. **Read `clinosim/simulator/cli.py`** to identify the actual flag names — the snippet below assumes `python -m clinosim generate ...` with `--population --seed --country --format fhir-bulk --output --modules`; adjust if the repo's CLI differs.

```bash
mkdir -p scratchpad/phase3a_byte_diff/branch
python -m clinosim generate \
    --population 2000 --seed 42 --country US \
    --format fhir-bulk --modules hai,device \
    --output scratchpad/phase3a_byte_diff/branch/us
python -m clinosim generate \
    --population 2000 --seed 42 --country JP \
    --format fhir-bulk --modules hai,device,identity \
    --output scratchpad/phase3a_byte_diff/branch/jp
```

- [ ] **Step 2: Switch to master and regenerate (Phase 2b pattern)**

```bash
git stash -u  # save any local edits (should be none after the last task commit)
git checkout 42657293
mkdir -p scratchpad/phase3a_byte_diff/master
python -m clinosim generate \
    --population 2000 --seed 42 --country US \
    --format fhir-bulk --modules hai,device \
    --output scratchpad/phase3a_byte_diff/master/us
python -m clinosim generate \
    --population 2000 --seed 42 --country JP \
    --format fhir-bulk --modules hai,device,identity \
    --output scratchpad/phase3a_byte_diff/master/jp
git checkout feat/phase3a-hai-lab-lift
git stash pop  # only if step 1 stashed anything
```

If `git stash pop` reports "No stash entries found", that's fine (it means there was nothing to stash, and the previous Task 7 commit left the tree clean).

- [ ] **Step 3: Write the byte-diff script**

Create `scratchpad/phase3a_byte_diff.py`:

```python
"""Phase 3a byte-diff: compare master vs branch NDJSON files.

Expected (per spec §8):
- All NDJSON except Observation: byte-IDENTICAL
- Observation: same line count (HAI cohort WBC + CRP values shifted)
"""
from __future__ import annotations

import hashlib
from pathlib import Path

ROOT = Path(__file__).parent / "phase3a_byte_diff"
MASTER = ROOT / "master"
BRANCH = ROOT / "branch"


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def line_count(path: Path) -> int:
    return sum(1 for _ in path.open("rb"))


def report(country: str) -> None:
    print(f"\n## {country.upper()}\n")
    print("| NDJSON | master sha256 | branch sha256 | master lines | branch lines | verdict |")
    print("|---|---|---|---|---|---|")
    master_dir = MASTER / country
    branch_dir = BRANCH / country
    for path in sorted(master_dir.glob("*.ndjson")):
        m_hash = sha256_of(path)
        b_path = branch_dir / path.name
        if not b_path.exists():
            print(f"| {path.name} | {m_hash[:12]}... | MISSING | {line_count(path)} | — | ❌ |")
            continue
        b_hash = sha256_of(b_path)
        m_lines, b_lines = line_count(path), line_count(b_path)
        if m_hash == b_hash:
            verdict = "✅ IDENTICAL"
        elif m_lines == b_lines:
            verdict = "🟡 same-count shift"
        else:
            verdict = "❌ count diff"
        print(
            f"| {path.name} | {m_hash[:12]}... | {b_hash[:12]}... | "
            f"{m_lines} | {b_lines} | {verdict} |"
        )


if __name__ == "__main__":
    for country in ("us", "jp"):
        report(country)
```

- [ ] **Step 4: Run the byte-diff script and capture results**

```bash
python scratchpad/phase3a_byte_diff.py | tee scratchpad/phase3a_byte_diff_results.md
```

Verify:
- All non-Observation NDJSON → ✅ IDENTICAL (Patient / Encounter / Condition / MedReq / MedAdmin / Procedure / ImagingStudy / Immunization / FamilyMemberHistory / Device / DeviceUseStatement / Specimen / DiagnosticReport)
- Observation.ndjson → 🟡 same-count shift (only WBC + CRP values changed in HAI cohort rows)

If any non-Observation file is NOT IDENTICAL, STOP — that indicates main-RNG contamination. Investigate before proceeding.

- [ ] **Step 5: Edit `phase3a_byte_diff_results.md` to add interpretation header**

Add the section above the auto-generated tables:

```markdown
# Phase 3a byte-diff results

**Date:** 2026-06-25
**Master:** 42657293 (PR #89 merged)
**Branch:** feat/phase3a-hai-lab-lift
**Cohort:** US p=2000 + JP p=2000, seed=42

## Summary

| Country | Expected | Actual |
|---|---|---|
| US | 13/14 IDENTICAL + Observation same-count | (fill in after run) |
| JP | 14/15 IDENTICAL + Observation same-count | (fill in after run) |

## Interpretation

- All non-Observation NDJSON IDENTICAL → confirms main RNG untouched
  (AD-16 preserved), and PR #88/89 cohort selection is byte-stable.
- Observation same-count shift → confirms WBC + CRP are the only Observation
  fields affected (Phase 3a scope guard upheld).
- DiagnosticReport IDENTICAL → DR references Observation IDs but does not
  embed values (Phase 2b PT_INR pattern, repeated here).
```

- [ ] **Step 6: Commit**

```bash
git add scratchpad/phase3a_byte_diff.py scratchpad/phase3a_byte_diff_results.md
git commit -m "$(cat <<'EOF'
test(phase3a): byte-diff vs master 42657293 — Observation-only shift (Task 5)

Cohort US/JP p=2000 seed=42. All non-Observation NDJSON byte-IDENTICAL,
Observation same-count with HAI-cohort WBC + CRP shifted. Confirms main
RNG untouched (AD-16) and scope guard holds (no other analyte changed).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UCerE4zz2NfW87r3MnbDrd
EOF
)"
```

---

## Task 6: 3-axis DQR (US p=10000 + JP p=5000, seed=42)

**Files:**
- Create: `scratchpad/phase3a_dqr.py`
- Create: `docs/reviews/2026-06-25-phase3a-hai-lab-lift-data-quality-review.md`

**Interfaces:**
- Consumes: branch generation at p=10000 / 5000
- Produces: per-axis PASS/FAIL evidence in markdown review

- [ ] **Step 1: Generate DQR cohort**

```bash
mkdir -p scratchpad/phase3a_dqr_output
python -m clinosim generate \
    --country US --population 10000 --seed 42 \
    --modules hai,device \
    --format fhir-r4 --format csv \
    --output scratchpad/phase3a_dqr_output/us/
python -m clinosim generate \
    --country JP --population 5000 --seed 42 \
    --modules hai,device,identity \
    --format fhir-r4 --format csv \
    --output scratchpad/phase3a_dqr_output/jp/
```

- [ ] **Step 2: Write the DQR script**

Create `scratchpad/phase3a_dqr.py`:

```python
"""Phase 3a 3-axis DQR: structural / clinical / JP-language.

Axis 1 (structural):
  - WBC + CRP refRange + interpretation 100%
  - LOINC 6690-2 (WBC) + 1988-5 (CRP) + JLAC10 2A020 (WBC) + 5C070 (CRP)
  - display != code
  - reference integrity

Axis 2 (clinical relative-delta, baseline calibration from spec §7.2):
  - CLABSI/VAP cohort: WBC delta p50 ≥ +3,000, CRP delta p50 ≥ +50 mg/L
  - CAUTI cohort:     WBC delta p50 ≥ +1,500, CRP delta p50 ≥ +25 mg/L
  - Rare-event acceptance: if cohort size < 5, N/A (Poisson tail)

Axis 3 (JP language):
  - US output 日本語混入 0
  - JP WBC/CRP display localised
  - JP CM-granular ICD leak 0 (existing guard, smoke test only)
"""
from __future__ import annotations

import json
import statistics
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).parent
OUT = ROOT / "phase3a_dqr_output"


def read_ndjson(path: Path):
    with path.open() as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def structural_check_obs(country: str) -> list[str]:
    issues: list[str] = []
    obs_path = OUT / country / "Observation.ndjson"
    wbc_total = wbc_with_range = wbc_with_interp = 0
    crp_total = crp_with_range = crp_with_interp = 0
    for r in read_ndjson(obs_path):
        codes = [c.get("code") for c in r.get("code", {}).get("coding", [])]
        if "6690-2" in codes or "2A020" in codes:
            wbc_total += 1
            if r.get("referenceRange"):
                wbc_with_range += 1
            if r.get("interpretation"):
                wbc_with_interp += 1
        if "1988-5" in codes or "5C070" in codes:
            crp_total += 1
            if r.get("referenceRange"):
                crp_with_range += 1
            if r.get("interpretation"):
                crp_with_interp += 1
    if wbc_total and wbc_with_range != wbc_total:
        issues.append(f"{country}: WBC refRange {wbc_with_range}/{wbc_total}")
    if wbc_total and wbc_with_interp != wbc_total:
        issues.append(f"{country}: WBC interp {wbc_with_interp}/{wbc_total}")
    if crp_total and crp_with_range != crp_total:
        issues.append(f"{country}: CRP refRange {crp_with_range}/{crp_total}")
    if crp_total and crp_with_interp != crp_total:
        issues.append(f"{country}: CRP interp {crp_with_interp}/{crp_total}")
    print(f"{country}: WBC n={wbc_total}, CRP n={crp_total}, refRange/interp 100% = "
          f"{wbc_with_range == wbc_total and wbc_with_interp == wbc_total and crp_with_range == crp_total and crp_with_interp == crp_total}")
    return issues


def clinical_delta(country: str) -> dict[str, dict[str, float]]:
    """Returns {hai_type or 'baseline': {WBC: p50, CRP: p50}}."""
    # Build encounter_id -> hai_type map
    hai_types: dict[str, str] = {}
    cond_path = OUT / country / "Condition.ndjson"
    for c in read_ndjson(cond_path):
        codes = [coding.get("code") for coding in c.get("code", {}).get("coding", [])]
        # Map ICD-10-CM codes to hai_type
        if "T80.211A" in codes:
            hai_type = "CLABSI"
        elif "T83.511A" in codes:
            hai_type = "CAUTI"
        elif "J95.851" in codes:
            hai_type = "VAP"
        else:
            continue
        enc_ref = c.get("encounter", {}).get("reference", "")
        enc_id = enc_ref.split("/")[-1] if enc_ref else None
        if enc_id:
            hai_types[enc_id] = hai_type

    # Collect WBC + CRP per cohort
    cohorts: dict[str, dict[str, list[float]]] = defaultdict(
        lambda: {"WBC": [], "CRP": []}
    )
    obs_path = OUT / country / "Observation.ndjson"
    for r in read_ndjson(obs_path):
        codes = [c.get("code") for c in r.get("code", {}).get("coding", [])]
        is_wbc = "6690-2" in codes or "2A020" in codes
        is_crp = "1988-5" in codes or "5C070" in codes
        if not (is_wbc or is_crp):
            continue
        enc_ref = r.get("encounter", {}).get("reference", "")
        enc_id = enc_ref.split("/")[-1] if enc_ref else ""
        if not enc_id:
            continue
        val = r.get("valueQuantity", {}).get("value")
        if val is None:
            continue
        cohort = hai_types.get(enc_id, "baseline")
        key = "WBC" if is_wbc else "CRP"
        cohorts[cohort][key].append(val)

    out = {}
    for cohort, labs in cohorts.items():
        out[cohort] = {
            "WBC_n": len(labs["WBC"]),
            "WBC_p50": statistics.median(labs["WBC"]) if labs["WBC"] else None,
            "CRP_n": len(labs["CRP"]),
            "CRP_p50": statistics.median(labs["CRP"]) if labs["CRP"] else None,
        }
    return out


def jp_language_check() -> list[str]:
    issues: list[str] = []
    # US output: 日本語混入 0
    us_obs = OUT / "us" / "Observation.ndjson"
    for r in read_ndjson(us_obs):
        for coding in r.get("code", {}).get("coding", []):
            disp = coding.get("display", "")
            if any(ord(c) > 127 and not c.isascii() for c in disp):
                issues.append(f"US Observation: non-ASCII display '{disp}'")
                break
    # JP output: WBC/CRP display is JP
    jp_obs = OUT / "jp" / "Observation.ndjson"
    jp_wbc_ja = jp_crp_ja = 0
    for r in read_ndjson(jp_obs):
        for coding in r.get("code", {}).get("coding", []):
            disp = coding.get("display", "")
            code = coding.get("code", "")
            if code in ("6690-2", "2A020") and any(ord(c) > 127 for c in disp):
                jp_wbc_ja += 1
                break
            if code in ("1988-5", "5C070") and any(ord(c) > 127 for c in disp):
                jp_crp_ja += 1
                break
    print(f"JP: WBC ja display n={jp_wbc_ja}, CRP ja display n={jp_crp_ja}")
    if not jp_wbc_ja:
        issues.append("JP: WBC display not localised")
    if not jp_crp_ja:
        issues.append("JP: CRP display not localised")
    return issues


if __name__ == "__main__":
    print("\n=== Axis 1: Structural ===")
    issues = structural_check_obs("us") + structural_check_obs("jp")
    print("structural issues:", issues or "NONE")

    print("\n=== Axis 2: Clinical relative-delta ===")
    for country in ("us", "jp"):
        print(f"\n{country.upper()}:")
        deltas = clinical_delta(country)
        baseline_wbc = deltas.get("baseline", {}).get("WBC_p50")
        baseline_crp = deltas.get("baseline", {}).get("CRP_p50")
        for cohort, vals in deltas.items():
            print(f"  {cohort}: n_WBC={vals['WBC_n']} p50={vals['WBC_p50']} | "
                  f"n_CRP={vals['CRP_n']} p50={vals['CRP_p50']}")
            if cohort != "baseline" and vals["WBC_p50"] and baseline_wbc:
                wbc_delta = vals["WBC_p50"] - baseline_wbc
                crp_delta = (vals["CRP_p50"] or 0) - (baseline_crp or 0)
                expected = {"CLABSI": (3000, 50), "VAP": (3000, 50), "CAUTI": (1500, 25)}.get(cohort, (0, 0))
                ok_wbc = wbc_delta >= expected[0]
                ok_crp = crp_delta >= expected[1]
                print(f"    delta_WBC={wbc_delta:+.0f} (need ≥{expected[0]}) {'PASS' if ok_wbc else 'FAIL'}")
                print(f"    delta_CRP={crp_delta:+.1f} (need ≥{expected[1]}) {'PASS' if ok_crp else 'FAIL'}")

    print("\n=== Axis 3: JP language ===")
    issues = jp_language_check()
    print("JP language issues:", issues or "NONE")
```

- [ ] **Step 3: Run the DQR and capture output**

```bash
python scratchpad/phase3a_dqr.py 2>&1 | tee scratchpad/phase3a_dqr_raw.log
```

Verify:
- Axis 1: structural issues = NONE
- Axis 2: CLABSI/VAP delta_WBC ≥ +3,000 and delta_CRP ≥ +50 mg/L; CAUTI delta_WBC ≥ +1,500 and delta_CRP ≥ +25
- Axis 3: JP language issues = NONE
- Cohort sizes follow Poisson expectation (US: ~6-12 HAI total; JP: 0-5)

For rare cohorts (< 5 events) the relative-delta is N/A — record as such, don't fail.

- [ ] **Step 4: Write the DQR review document**

Create `docs/reviews/2026-06-25-phase3a-hai-lab-lift-data-quality-review.md`:

```markdown
# Phase 3a HAI WBC + CRP lift — 3-axis Data Quality Review

**Date:** 2026-06-25
**Branch:** feat/phase3a-hai-lab-lift
**Master baseline:** 42657293 (PR #89 merged)
**Cohort:** US p=10,000 + JP p=5,000, seed=42
**Tool:** scratchpad/phase3a_dqr.py + scratchpad/phase3a_byte_diff.py

## Summary

| Axis | Verdict |
|---|---|
| 1. Structural quality | (PASS / FAIL) |
| 2. Clinical relative-delta | (PASS / FAIL) |
| 3. JP language quality | (PASS / FAIL) |
| byte-diff | (13/14 IDENTICAL — Phase 2b parity) |

## Axis 1: Structural quality

(paste from phase3a_dqr_raw.log)

## Axis 2: Clinical relative-delta

(paste from phase3a_dqr_raw.log, include cohort n + p50 + delta for each HAI type)

## Axis 3: JP language quality

(paste from phase3a_dqr_raw.log)

## byte-diff

(reference `scratchpad/phase3a_byte_diff_results.md`)

## Conclusion

(PR-ready / requires-fix)
```

Fill in the captured numbers from `scratchpad/phase3a_dqr_raw.log`.

- [ ] **Step 5: Commit**

```bash
git add scratchpad/phase3a_dqr.py docs/reviews/2026-06-25-phase3a-hai-lab-lift-data-quality-review.md
git commit -m "$(cat <<'EOF'
test(phase3a): 3-axis DQR — structural / clinical / JP language (Task 6)

US p=10,000 + JP p=5,000, seed=42. Structural axis: WBC + CRP refRange +
interpretation 100%, LOINC + JLAC10 codes intact. Clinical axis: CLABSI/VAP
delta vs non-HAI baseline meets calibration (CRP +50 mg/L, WBC +3,000).
JP language axis: US English-only, JP labs localised.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UCerE4zz2NfW87r3MnbDrd
EOF
)"
```

---

## Task 7: Docs sync (CLAUDE / MODULES / SCENARIO_FLAGS / module READMEs / DESIGN / TODO / README)

**Files:**
- Modify: `CLAUDE.md`
- Modify: `MODULES.md`
- Modify: `SCENARIO_FLAGS.md`
- Modify: `clinosim/modules/hai/README.md`
- Modify: `clinosim/modules/physiology/README.md`
- Modify: `DESIGN.md`
- Modify: `TODO.md`
- Modify: `README.md`
- Modify: `README.ja.md`

- [ ] **Step 1: Update `CLAUDE.md` "AD-55 enricher patterns" section**

Find the "AD-55 enricher patterns" section. Locate the rule about merge-pattern call sites. Extend to include the third helper.

Before:
> `derive_lab_values` の TWO flag dicts: `{**scenario_flags_from_protocol(p), **medication_flags_from_context(...)}` で `**flags` splat ...

After:
> `derive_lab_values` の THREE flag dicts: `{**scenario_flags_from_protocol(p), **medication_flags_from_context(...), **hai_flags_from_record(record, encounter_id, current_day)}` で `**flags` splat、call site で `flag=value` 直接渡し禁止(J5 prevention extended for HAI couplings)
>
> Phase 3a `hai_flags_from_record` reads `record.extensions["hai"]` populated by PR #89 modules/hai and returns `{"hai_inflammation_lift": float}` (0.0..0.35, ramped over 2 days from onset_date). `derive_lab_values` routes the lift only into the CRP + WBC formulas via `effective_infl = min(1.0, infl + lift)`; all other analytes continue to read `state.inflammation_level` directly (Phase 3c will revisit the sepsis cascade).

- [ ] **Step 2: Update `MODULES.md` hai row**

Find the hai row in the Module Inventory table (Tier "optional"). Update the Consumers column:

Before: `simulator/enrichers.py, output (_fhir_hai.py + reuses _fhir_microbiology.py)`

After: `simulator/enrichers.py, output (_fhir_hai.py + reuses _fhir_microbiology.py), physiology.engine (Phase 3a observation-time lift via hai_flags_from_record)`

- [ ] **Step 3: Update `SCENARIO_FLAGS.md`**

Add `hai_inflammation_lift` to the "All current flags" table:

```markdown
| `hai_inflammation_lift` | float (0.0..0.35) | `hai_flags_from_record(record, encounter_id, current_day)` | Phase 3a — CDC NHSN HAI (CLABSI / CAUTI / VAP) → lifts effective inflammation for WBC + CRP only; ramped over 2 days from onset_date; YAML-driven per HAI type via `modules/hai/reference_data/hai_lab_lift.yaml` |
```

Update the "Helper architecture" section to list 3 helpers (scenario / medication / hai) and the "Adding a new flag" 5-step guide to mention the third helper as an option ("Is your flag disease-driven? scenario_flag. Medication-driven? medication_flag. HAI / enrichment-driven? hai_flag. Otherwise: add a new sibling helper.")

- [ ] **Step 4: Update `clinosim/modules/hai/README.md`**

Add a new section after the existing "概要 / 役割" section:

```markdown
## Phase 3a: 観測時 WBC + CRP lift (cross-module consume, PR2026-06-25)

`extensions["hai"]` を立てた本モジュールに対し、physiology layer が観測時に
ラボ値を底上げする読み取り消費を Phase 3a で確立。詳細は
`docs/superpowers/specs/2026-06-25-phase3a-hai-lab-lift-design.md` 参照。

- 新 helper: `physiology.engine.hai_flags_from_record(record, encounter_id, current_day) -> {"hai_inflammation_lift": float}`
- 新 config: `modules/hai/reference_data/hai_lab_lift.yaml`(CLABSI/VAP=0.35, CAUTI=0.20, ramp 2 日)
- `derive_lab_values` は `effective_infl = min(1.0, infl + lift)` を CRP + WBC formula のみに渡す
- main RNG 不動、state 不変(AD-57 BNP-pattern surgical)、byte-diff cohort effect は Observation の WBC + CRP のみ

**out of scope** (Phase 3b/c に保留): antibiotic empirical → narrow, S/I/R, WBC/CRP decay, mortality coupling, Lactate / Plt / 体温 / SBP sepsis cascade。
```

- [ ] **Step 5: Update `clinosim/modules/physiology/README.md`**

Add `hai_flags_from_record` to the public API section alongside `scenario_flags_from_protocol` and `medication_flags_from_context`:

```markdown
### `hai_flags_from_record(record, encounter_id, current_day) -> dict[str, float]`

Phase 3a sibling of `scenario_flags_from_protocol` + `medication_flags_from_context`. Reads `record.extensions["hai"]` (populated by `modules/hai` enricher) and returns `{"hai_inflammation_lift": float}` to be merged into the `derive_lab_values` flags dict. Returns 0.0 for non-HAI patients / pre-onset / cross-encounter mismatch / `None` arguments.
```

- [ ] **Step 6: Update `DESIGN.md`**

In the AD-55 entry's "Recent additions" or equivalent section, add:

> **2026-06-25 (Phase 3a)** — cross-module observation-time consume pattern established: `physiology.engine.hai_flags_from_record` reads `extensions["hai"]` (PR #89) and supplies `hai_inflammation_lift` to `derive_lab_values`. Lifts WBC + CRP only; state unchanged (AD-57 BNP-pattern surgical). 4th example of the BNP-pattern surgical / observation-time formula approach (after BNP, D-dimer Phase 2a, PT_INR Phase 2b).

- [ ] **Step 7: Update `TODO.md`**

Find the Phase 3 backlog section. Mark Phase 3a as complete and add Phase 3b/3c as new entries:

```markdown
### Phase 3a: HAI WBC + CRP lift ✅ (2026-06-25)
- `hai_flags_from_record` helper + `hai_inflammation_lift` kwarg
- 5-site wiring + byte-diff + 3-axis DQR PASS
- See `docs/superpowers/specs/2026-06-25-phase3a-hai-lab-lift-design.md`

### Phase 3b: antibiotic empirical → narrow + S/I/R + WBC/CRP decay
- Empirical antibiotic order at HAI onset (Vancomycin / Cefazolin / Pip-Tazo)
- Culture-driven narrowing (organism → susceptibility matrix YAML)
- WBC + CRP decay phase coupled with antibiotic-day count

### Phase 3c: HAI mortality + sepsis cascade
- HAI → outcome_benchmarks mortality coupling
- Lactate / Platelets / Temperature / SBP / DBP cascade for HAI cohort
```

- [ ] **Step 8: Update `README.md` + `README.ja.md`**

In the "Quality & Compliance" / 「データ品質と適合性」 section, add a link to the new DQR:

```markdown
- 2026-06-25 — Phase 3a HAI WBC + CRP lift: [docs/reviews/2026-06-25-phase3a-hai-lab-lift-data-quality-review.md](docs/reviews/2026-06-25-phase3a-hai-lab-lift-data-quality-review.md)
```

- [ ] **Step 9: Run a final regression**

```bash
pytest -m "unit or integration" -x 2>&1 | tail -5
```
Expected: all green.

- [ ] **Step 10: Commit**

```bash
git add CLAUDE.md MODULES.md SCENARIO_FLAGS.md \
        clinosim/modules/hai/README.md clinosim/modules/physiology/README.md \
        DESIGN.md TODO.md README.md README.ja.md
git commit -m "$(cat <<'EOF'
docs(phase3a): sync CLAUDE / MODULES / SCENARIO_FLAGS / READMEs / DESIGN / TODO (Task 7)

- CLAUDE.md "AD-55 enricher patterns": now THREE flag dicts (scenario +
  medication + hai), J5-prevention extended to HAI couplings.
- MODULES.md: hai row Consumers += physiology.engine (Phase 3a).
- SCENARIO_FLAGS.md: hai_inflammation_lift added; 3-helper architecture.
- clinosim/modules/hai/README.md: "Phase 3a observation-time lift" section.
- clinosim/modules/physiology/README.md: hai_flags_from_record API.
- DESIGN.md: AD-55 entry + AD-57 4th BNP-pattern surgical example.
- TODO.md: Phase 3a ✅, Phase 3b/c added.
- README.md / README.ja.md: Quality section links DQR.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UCerE4zz2NfW87r3MnbDrd
EOF
)"
```

---

## Task 8: ruff + mypy lint pass

**Files:** All modified files in Tasks 1-7.

- [ ] **Step 1: Run ruff auto-fix**

```bash
ruff check --fix clinosim/ tests/
ruff format clinosim/ tests/
```

- [ ] **Step 2: Run mypy on modified modules**

```bash
mypy clinosim/modules/physiology/ clinosim/simulator/inpatient.py clinosim/simulator/emergency.py clinosim/simulator/outpatient.py 2>&1 | tail -20
```
Expected: no new errors (existing ~241 baseline errors are non-regression).

- [ ] **Step 3: Commit if changes made**

```bash
git status
# only commit if ruff or mypy fixes produced changes:
git add -u
git commit -m "$(cat <<'EOF'
lint(phase3a): ruff auto-fix + mypy clean for Phase 3a files (Task 8)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01UCerE4zz2NfW87r3MnbDrd
EOF
)"
```

If no changes were produced, skip the commit.

---

## Final: Push + PR

- [ ] **Step 1: Push the branch**

```bash
git push -u origin feat/phase3a-hai-lab-lift
```

- [ ] **Step 2: Create the PR**

```bash
gh pr create --title "Phase 3a: HAI WBC + CRP lift via hai_flags_from_record" --body "$(cat <<'EOF'
## Summary

- New `physiology.engine.hai_flags_from_record(record, encounter_id, current_day)` sibling of `scenario_flags_from_protocol` + `medication_flags_from_context` — reads PR #89 `extensions["hai"]`, returns `{"hai_inflammation_lift": float}`.
- New kwarg `derive_lab_values(..., hai_inflammation_lift: float = 0.0)` — computes `effective_infl = min(1.0, infl + lift)` and routes ONLY into CRP + WBC formulas.
- 5-site wiring (inpatient Pass-1 main + lagged + unknown + ED + outpatient) merges `{**scenario_flags, **medication_flags, **hai_flags}`.
- New YAML `modules/hai/reference_data/hai_lab_lift.yaml`: CDC severity proxy CLABSI/VAP=0.35, CAUTI=0.20, ramp 2 days.

## Verification

- **byte-diff** vs master `42657293` at US/JP p=2000 seed=42: all non-Observation NDJSON byte-IDENTICAL; Observation same-count with HAI cohort WBC + CRP shifted (clean Phase 2b parity). See `scratchpad/phase3a_byte_diff_results.md`.
- **3-axis DQR** at US p=10,000 + JP p=5,000 seed=42: structural / clinical / JP language all PASS. See `docs/reviews/2026-06-25-phase3a-hai-lab-lift-data-quality-review.md`.

## Test plan

- [x] unit: `tests/unit/test_hai_flags_from_record.py` (13 cases)
- [x] unit: `tests/unit/test_derive_lab_values_hai.py` (10 cases)
- [x] integration: `tests/integration/test_hai_lift_wiring.py` (J5-prevention)
- [x] integration: `tests/integration/test_hai_lift_clinical.py` (relative-delta)
- [x] byte-diff: 13/14 IDENTICAL + Observation same-count shift
- [x] 3-axis DQR: all PASS

## Out of scope (Phase 3b/c)

- antibiotic empirical → narrow + S/I/R + WBC/CRP decay (Phase 3b)
- HAI mortality coupling + Lactate / Plt / 体温 / SBP sepsis cascade (Phase 3c)

## Docs

- CLAUDE.md "AD-55 enricher patterns" — 3-helper merge pattern
- MODULES.md hai row Consumers += physiology.engine
- SCENARIO_FLAGS.md — hai_inflammation_lift + 3-helper architecture
- clinosim/modules/hai/README.md — "Phase 3a observation-time lift"
- clinosim/modules/physiology/README.md — hai_flags_from_record API
- DESIGN.md — AD-55 / AD-57 entries refreshed
- TODO.md — Phase 3a ✅, Phase 3b/c added
- README.md / README.ja.md — Quality section links

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

- [ ] **Step 3: Verify PR URL is returned and accessible**

If `gh pr create` returns a PR URL, success. Pass the URL to the user.

---

## Summary

Phase 3a closes the `HAI 発症 → 炎症マーカー上昇` clinical chain established by PR #88 (modules/device) + PR #89 (modules/hai). It applies the BNP-pattern surgical formula technique (state unchanged, lift only at observation time) and follows the J5-prevention 3-helper merge pattern established by Phase 2a (D-dimer) and Phase 2b (PT_INR). No new types, no new code-system codes, no RNG changes.

## Evidence

- byte-diff: `scratchpad/phase3a_byte_diff_results.md`
- 3-axis DQR: `docs/reviews/2026-06-25-phase3a-hai-lab-lift-data-quality-review.md`
- spec: `docs/superpowers/specs/2026-06-25-phase3a-hai-lab-lift-design.md`

## Test plan

- 13 unit tests for `hai_flags_from_record` (Task 1)
- 10 unit tests for `derive_lab_values` HAI extension (Task 2)
- 2 integration tests for wiring (Task 4)
- 1 integration test for clinical relative-delta sanity (Task 4)
- byte-diff verification (Task 5)
- 3-axis DQR at p=10,000 / 5,000 (Task 6)

## Deferred (Phase 3b/c backlog)

| Item | Phase | Reason |
|---|---|---|
| antibiotic empirical → narrow | 3b | CDC/IDSA empirical selection logic + culture-driven narrowing is large scope |
| susceptibility S/I/R matrix YAML | 3b | organism × antibiotic full matrix |
| WBC/CRP decay phase | 3b | coupled to antibiotic-day count, must implement with empirical chain |
| HAI mortality coupling | 3c | outcome_benchmarks modification is sensitive |
| Lactate / Plt / 体温 / SBP sepsis cascade | 3c | multi-analyte BNP-pattern surgical batch |
| LOS extension by HAI | 3c+ | clinical_course YAML structural change |

## Self-Review Notes (writer's checklist — preserved for reviewer)

- **Spec coverage:** every section of the spec (§2-§11) maps to a Task. §2 architecture → T1+T2+T3 / §3 helper → T1 / §4 derive_lab_values → T2 / §5 YAML → T1 / §6 wiring → T3 / §7 tests → T1+T2+T4 / §8 byte-diff → T5 / §9 DQR → T6 / §10 docs → T7 / §11 out-of-scope → mentioned in T7 + Final PR body.
- **Placeholder scan:** no TBD / TODO / vague directives remain. Code blocks in every code step. Exact file paths everywhere.
- **Type consistency:** `hai_flags_from_record` signature is identical across T1 implementation, T2 docstring reference, T3 wiring, T7 docs. The kwarg name `hai_inflammation_lift` is identical across spec, T2 (signature + tests), and T3 (wiring).
- **Line-number caveat:** Tasks 1, 2, 3 cite line numbers as approximate (`~579`, `~1706`, `~134`, `~163`) because they will shift as files change. Each task includes a "read 10 lines above" caveat to ground the engineer in the correct local variable names before editing.
- **CLI flags caveat:** Tasks 5/6 use `python -m clinosim generate --modules hai,device ...`; the actual flag may differ. Task 5 Step 1 includes the instruction to read `clinosim/simulator/cli.py` first.
