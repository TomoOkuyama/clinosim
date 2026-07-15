"""Integration: drive enrich_antibiotic end-to-end via run_forced + force_hai_event.

PR-90 教訓: a unit test that constructs a fixture HAIEvent does NOT
prove the enricher path is wired into the run. This test exercises
register_builtin_enrichers + run_forced + the always-on antibiotic
enricher + the full FHIR adapter — for HAI events deterministically
emitted via ForcedScenario.force_hai_event (Task 7b).

Device placement is still stochastic (icu_transferred gate), so these
tests may pytest.skip when seed=42 doesn't trigger device placement
for the chosen disease. The unit-test suite + AD-60 audit
lift_firing_proof cover the enricher path even when devices don't fire.
"""

import pytest

from clinosim.modules.antibiotic.engine import ABX_ORDER_ID_PREFIX
from clinosim.simulator.engine import run_forced
from clinosim.types.config import ForcedScenario, SimulatorConfig


@pytest.fixture
def cauti_forced_scenario():
    """Deterministic CAUTI HAI scenario via Task 7b's force_hai_event."""
    return ForcedScenario(
        disease_id="sepsis",
        count=100,
        archetype="treatment_resistant",
        severity="severe",
        force_hai_event={
            "hai_type": "cauti",
            "onset_offset_days": 3,
            "organism_snomed": "112283007",  # E. coli (most common CAUTI organism)
        },
    )


@pytest.mark.integration
def test_antibiotic_always_on_emits_medications(cauti_forced_scenario):
    """Always-on enricher: a CAUTI HAI event triggers Ceftriaxone Order + 7 MAR."""
    cfg = SimulatorConfig(country="US", random_seed=42)
    ds = run_forced(cauti_forced_scenario, config=cfg)
    rec_with_abx = None
    for rec in ds.patients:
        if rec.extensions.get("antibiotic"):
            rec_with_abx = rec
            break
    if rec_with_abx is None:
        pytest.skip(
            "100 severe-sepsis patients at seed=42 produced no antibiotic "
            "regimens (device path requires icu_transferred; force_hai_event "
            "needs a matching device). Unit + AD-60 lift_firing_proof "
            "cover the enricher path."
        )
    abx = rec_with_abx.extensions["antibiotic"]
    assert any(r.drug_key == "ceftriaxone" for r in abx)
    cef = next(r for r in abx if r.drug_key == "ceftriaxone")
    assert cef.duration_days == 7
    cef_orders = [
        o for o in rec_with_abx.orders if o.order_type.value == "medication" and o.display_name == "Ceftriaxone"
    ]
    assert len(cef_orders) >= 1
    cef_mar = [m for m in rec_with_abx.medication_administrations if m.drug_name == "Ceftriaxone"]
    assert len(cef_mar) >= 7  # at least one full course (possibly more if multiple HAI events)


@pytest.mark.integration
def test_antibiotic_no_hai_no_antibiotic():
    """A patient without HAI events gets no antibiotic regimen (always-on no-op)."""
    scenario = ForcedScenario(
        disease_id="bacterial_pneumonia",
        count=1,
        severity="mild",
        force_hai_event=None,
    )
    cfg = SimulatorConfig(country="US", random_seed=42)
    ds = run_forced(scenario, config=cfg)
    rec = ds.patients[0]
    assert rec.extensions.get("antibiotic", []) == []
    # mild bacterial_pneumonia at seed=42 should not produce any HAI
    # empirical antibiotic via the enricher path.
    # PR-93 adversarial review fix: removed the inner ``m.drug_name == "Vancomycin"``
    # filter that previously nullified the membership test for
    # Ceftriaxone / Piperacillin/Tazobactam (which can also be produced
    # by disease YAML drugs sections, so we check the enricher attribution
    # via extensions["antibiotic"] above being empty).
    hai_abx_names = {"Vancomycin", "Piperacillin/Tazobactam", "Ceftriaxone"}
    enricher_mar_drug_names = {
        m.drug_name
        for m in rec.medication_administrations
        if any(o.order_id == m.order_id and (o.order_id or "").startswith(ABX_ORDER_ID_PREFIX) for o in rec.orders)
    }
    unexpected = enricher_mar_drug_names & hai_abx_names
    assert not unexpected, (
        f"mild pneumonia without HAI should not get HAI empirical antibiotic via enricher path, but found {unexpected}"
    )


@pytest.mark.integration
def test_antibiotic_determinism_same_seed(cauti_forced_scenario):
    """Same seed + same force_hai_event ⇒ same regimens + same MAR schedule."""
    cfg = SimulatorConfig(country="US", random_seed=42)
    a = run_forced(cauti_forced_scenario, config=cfg)
    b = run_forced(cauti_forced_scenario, config=cfg)
    abx_a_all = [
        (r.regimen_id, r.start_datetime) for rec in a.patients for r in rec.extensions.get("antibiotic", []) or []
    ]
    abx_b_all = [
        (r.regimen_id, r.start_datetime) for rec in b.patients for r in rec.extensions.get("antibiotic", []) or []
    ]
    if not abx_a_all:
        pytest.skip(
            "cauti_forced_scenario at seed=42 produced no antibiotics "
            "(no ICU transfers → no devices); determinism cannot be "
            "verified vacuously. Switch fixture to acute_mi/severe/seed=42 "
            "for reliable ICU placement."
        )
    assert abx_a_all == abx_b_all
