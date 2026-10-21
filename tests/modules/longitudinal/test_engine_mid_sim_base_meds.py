"""Phase 4b.2.δ — engine activates base chronic medications on mid-sim
chronic acquisition (cycle-2 audit finding #1737).

A chronic-onset event (e.g. i10_onset) appends the new ICD to
``person.chronic_conditions`` mid-sim. The chronic-medication activation
sampler must also be invoked for that new ICD so the base home regimen
(Amlodipine for I10, Metformin for E11.9, Levothyroxine for E03, …) is
populated — otherwise Phase 4a / 4b.1 escalation events fire on top of
nothing, producing implausible histories (HCTZ-only new-onset HTN).
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from clinosim.modules.longitudinal import engine as longitudinal_engine
from clinosim.modules.longitudinal import loader as longitudinal_loader
from clinosim.types.patient import HomeMedication
from clinosim.types.population import PersonRecord


@pytest.fixture
def i10_onset_always_fires(tmp_path, monkeypatch):
    """Minimal longitudinal yaml fixture: a single ``i10_onset`` event
    with ``base_annual_rate: 1.0`` and no age gating, so it fires on
    every advance_one_year call for an in-scope person."""
    longitudinal = tmp_path / "longitudinal"
    (longitudinal / "event").mkdir(parents=True)
    (longitudinal / "event" / "i10_onset.yaml").write_text(
        """\
attribute_id: i10_onset
pattern: event
depends_on: []
clinical_scope:
  requires_age_band: [18, 120]

event_name: i10_onset
emits_icd: I10
base_annual_rate: 1.0
one_shot: true
narrative_label: i10_onset
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(longitudinal_loader, "_LONGITUDINAL_DIR", longitudinal)
    longitudinal_loader.load_attribute_specs.cache_clear()
    yield longitudinal
    longitudinal_loader.load_attribute_specs.cache_clear()


def _make_person(person_id: str = "POP-TEST-0001") -> PersonRecord:
    return PersonRecord(
        person_id=person_id,
        household_id="HH-TEST-001",
        age=25,
        sex="M",
        date_of_birth=date(1999, 1, 1),
        chronic_conditions=[],
    )


def test_mid_sim_i10_onset_activates_amlodipine(i10_onset_always_fires):
    """RED → GREEN: a 25M with no chronic conditions acquires I10 via
    the ``i10_onset`` event; after the event fires in-engine (whether
    at ``initial_snapshot`` or ``advance_one_year``, both of which run
    the shared ``_apply_pattern`` event branch), ``person.current_medications``
    must contain Amlodipine — the chronic_medications.yaml::I10 base
    entry (implicit probability=1.0).

    Pre-fix (cycle-2 audit #1737): engine appended ``I10`` to
    ``person.chronic_conditions`` but never invoked the chronic-med
    activation sampler, leaving the home regimen empty.
    """
    person = _make_person()
    rng = np.random.default_rng(42)
    snap = longitudinal_engine.initial_snapshot(person, 2024, rng)

    assert "I10" in person.chronic_conditions
    assert "I10" in snap.new_complications
    drug_names = {hm.drug_name for hm in person.current_medications}
    assert "Amlodipine" in drug_names, (
        f"expected Amlodipine (I10 base regimen) to be activated on i10_onset fire; got {drug_names!r}"
    )


def test_mid_sim_advance_one_year_fire_activates_base_meds(i10_onset_always_fires):
    """Explicit advance_one_year path: construct a person who already
    carries I10 at base_year (so the one_shot i10_onset event is
    suppressed at ``initial_snapshot`` via Phase 4b.2.β's prior-fire
    history, and in this fixture by one_shot semantics against the base
    history list)."""
    # When the person already carries I10 at base year, the event's
    # ``emits_icd`` dedup (``if result.emits_icd not in person.chronic_conditions``)
    # won't double-append — the primary coverage for the mid-sim path is
    # the first test. This test exercises the dedup branch: if base
    # meds were already activated at base_year via the activator-style
    # path, a second fire of the engine helper must not duplicate them.
    person = _make_person(person_id="POP-TEST-0002")
    person.chronic_conditions = ["I10"]
    person.current_medications.append(HomeMedication(drug_name="Amlodipine", route="PO", dose="5mg", frequency="daily"))
    rng = np.random.default_rng(42)
    longitudinal_engine.initial_snapshot(person, 2024, rng)
    longitudinal_engine.advance_one_year(person, 2025, rng)

    amlo_count = sum(1 for hm in person.current_medications if hm.drug_name == "Amlodipine")
    assert amlo_count == 1


def test_mid_sim_base_meds_dedup_against_existing(i10_onset_always_fires):
    """A patient already carrying Amlodipine (e.g. from a prior
    discharge prescription persisted into current_medications) must not
    get a duplicate Amlodipine on mid-sim i10_onset fire."""
    person = _make_person()
    person.current_medications.append(HomeMedication(drug_name="Amlodipine", route="PO", dose="5mg", frequency="daily"))
    rng = np.random.default_rng(42)
    longitudinal_engine.initial_snapshot(person, 2024, rng)
    longitudinal_engine.advance_one_year(person, 2025, rng)

    amlo_count = sum(1 for hm in person.current_medications if hm.drug_name == "Amlodipine")
    assert amlo_count == 1
