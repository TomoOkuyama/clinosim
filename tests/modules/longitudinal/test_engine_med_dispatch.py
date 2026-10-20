"""Phase 4a Task 4 — engine wiring for med-emitting events.

A med-only event firing in the engine must:
1. Append the fire_marker (not drug names) to snapshot.med_additions
   so Task 2's dedup via prior-year snapshots works.
2. Resolve each drug name via resolve_med_name and append to
   person.current_medications, deduped against existing drug_name.
3. Not duplicate a drug already present in current_medications
   (Review Focus #3).
4. Be idempotent across years — a one_shot event with fire_marker set
   fires exactly once across the sim window.
"""

from __future__ import annotations

import numpy as np
import pytest

from clinosim.modules.longitudinal import engine as longitudinal_engine
from clinosim.modules.longitudinal import loader as longitudinal_loader
from clinosim.types.patient import HomeMedication


@pytest.fixture
def phase4a_yaml_dir(tmp_path, monkeypatch):
    """Build a two-attribute minimal fixture: hba1c AR(1) locked at 10.0
    (deterministic — phi=1.0, sigma=0, mean_reversion_target=10.0) and
    one SGLT2i escalation event that always fires at HbA1c > 9."""
    longitudinal = tmp_path / "longitudinal"
    (longitudinal / "lab").mkdir(parents=True)
    (longitudinal / "med").mkdir(parents=True)
    (longitudinal / "lab" / "hba1c.yaml").write_text(
        """\
attribute_id: hba1c
pattern: ar1
depends_on: []
clinical_scope:
  requires_chronic_codes: ["E11"]
  requires_age_band: [18, 120]

latent_name: hba1c
ar1:
  phi: 1.0
  sigma: 0.0
  mean_reversion_target: 10.0
clamp: [4.0, 20.0]
initial:
  mu: 2.3025851
  sigma: 0.0
  clamp: [4.0, 20.0]
""",
        encoding="utf-8",
    )
    (longitudinal / "med" / "dm_escalate_sglt2i_e11.yaml").write_text(
        """\
attribute_id: dm_escalate_sglt2i_e11
pattern: event
depends_on: [hba1c]
clinical_scope:
  requires_chronic_codes: ["E11"]
  requires_age_band: [18, 120]

event_name: dm_escalate_sglt2i_e11
emits_icd: ""
emits_meds: ["Empagliflozin"]
fire_marker: dm_escalate_sglt2i_e11
base_annual_rate: 1.0
rate_modifiers:
  - when: {attribute: hba1c, operator: "<=", value: 9.0}
    factor: 0.0
one_shot: true
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(longitudinal_loader, "_LONGITUDINAL_DIR", longitudinal)
    longitudinal_loader.load_attribute_specs.cache_clear()
    yield longitudinal
    longitudinal_loader.load_attribute_specs.cache_clear()


def _make_person(dob_year=1970, chronic=None):
    from datetime import date

    from clinosim.types.population import PersonRecord

    return PersonRecord(
        person_id="PERSON-TEST-001",
        household_id="HH-TEST-001",
        age=55,
        sex="M",
        date_of_birth=date(dob_year, 1, 1),
        chronic_conditions=list(chronic or []),
    )


def test_engine_mutates_current_medications_on_fire(phase4a_yaml_dir):
    """Fire SGLT2i escalation event at initial_snapshot (base rate 1.0,
    HbA1c=10). person.current_medications gains Empagliflozin as a
    HomeMedication, the 2024 snapshot carries the fire_marker in
    med_additions, and the Empagliflozin HomeMedication has yaml-sourced
    dose/route/frequency (not the lookup fallback — but under the test
    fixture this falls back to the default since the fixture yaml dir
    only has the two attribute yamls, not chronic_medications.yaml).
    """
    person = _make_person(chronic=["E11.9"])
    rng = np.random.default_rng(42)
    initial_snap = longitudinal_engine.initial_snapshot(person, 2024, rng)

    assert any(hm.drug_name == "Empagliflozin" for hm in person.current_medications)
    assert "dm_escalate_sglt2i_e11" in initial_snap.med_additions


def test_engine_dedups_fire_marker_across_years(phase4a_yaml_dir):
    """A one_shot med event fires exactly once across the sim window."""
    person = _make_person(chronic=["E11.9"])
    rng = np.random.default_rng(42)
    longitudinal_engine.initial_snapshot(person, 2024, rng)
    snap_2025 = longitudinal_engine.advance_one_year(person, 2025, rng)
    snap_2026 = longitudinal_engine.advance_one_year(person, 2026, rng)

    emp_count = sum(1 for hm in person.current_medications if hm.drug_name == "Empagliflozin")
    assert emp_count == 1
    # fire_marker only in the initial snapshot (2024); 2025+2026 skip via dedup.
    assert "dm_escalate_sglt2i_e11" not in snap_2025.med_additions
    assert "dm_escalate_sglt2i_e11" not in snap_2026.med_additions


def test_engine_does_not_duplicate_existing_drug(phase4a_yaml_dir):
    """Review Focus #3: a person already carrying Empagliflozin in
    current_medications must not get a duplicate on fire."""
    person = _make_person(chronic=["E11.9"])
    person.current_medications.append(
        HomeMedication(drug_name="Empagliflozin", route="PO", dose="10mg", frequency="daily")
    )
    rng = np.random.default_rng(42)
    longitudinal_engine.initial_snapshot(person, 2024, rng)
    longitudinal_engine.advance_one_year(person, 2025, rng)

    emp_count = sum(1 for hm in person.current_medications if hm.drug_name == "Empagliflozin")
    assert emp_count == 1
