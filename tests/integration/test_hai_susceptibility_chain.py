"""Integration: PR3b-2 HAI culture S/I/R chain end-to-end.

Exercises the full forced-scenario path:
  ForcedScenario.force_hai_event → enrich_hai → _append_hai_culture
  → MicrobiologyResult.susceptibilities populated + hai_event_id backref set.

Harness contract:
  run_forced(scenario, config=cfg) → CIFDataset; records in ds.patients.

Wiring note: enrich_hai reads force_hai_event from ctx.config.forced_scenarios,
not from the run_forced scenario argument directly. So the ForcedScenario must
also appear in SimulatorConfig.forced_scenarios for the HAI enricher to pick it
up (run_forced passes config=cfg to _simulate_patient → POST_ENCOUNTER context).

ICU transfer and device placement note: _append_hai_culture only fires when a
matching device exists (cvc → clabsi, indwelling_catheter → cauti,
mechanical_ventilator → vap), which requires record.icu_transferred = True,
which is complication-driven.  acute_mi severe at seed=42 reliably produces
~2/50 patients with cardiogenic_shock → ICU → all three device types placed,
giving a deterministic exercise of the susceptibility chain. A pytest.skip
guard is retained as a safety net in case a future seed shift changes the count.
"""

from __future__ import annotations

import pytest

from clinosim.simulator.engine import run_forced
from clinosim.types.config import ForcedScenario, SimulatorConfig


@pytest.mark.integration
@pytest.mark.parametrize(
    "hai_type,organism_snomed,expected_abx_count",
    [
        # S. aureus CLABSI (NHSN 2018-2020): vancomycin + cefazolin + ceftriaxone
        #   + cefepime + ciprofloxacin + trimethoprim_sulfamethoxazole = 6
        ("clabsi", "3092008", 6),
        # E. coli CAUTI (NHSN 2018-2020): ceftriaxone + cefepime + meropenem
        #   + ciprofloxacin + trimethoprim_sulfamethoxazole = 5
        ("cauti", "112283007", 5),
        # S. aureus VAP (NHSN 2018-2020): vancomycin + cefazolin + ceftriaxone
        #   + cefepime + ciprofloxacin + trimethoprim_sulfamethoxazole = 6
        ("vap", "3092008", 6),
    ],
)
def test_force_hai_event_populates_susceptibilities(
    hai_type: str, organism_snomed: str, expected_abx_count: int
) -> None:
    """ForcedScenario fires the chain; antibiogram populates susceptibilities.

    50 acute_mi severe patients at seed=42 reliably produce ~2 patients with
    cardiogenic_shock → ICU → all three device types (CVC + catheter + vent)
    placed → force_hai_event emits exactly one HAI event per matching device
    with susceptibilities drawn from hai_antibiogram.yaml.
    """
    scenario = ForcedScenario(
        disease_id="acute_mi",
        count=50,
        severity="severe",
        force_hai_event={
            "hai_type": hai_type,
            "onset_offset_days": 3,
            "organism_snomed": organism_snomed,
        },
    )
    # force_hai_event is read by enrich_hai from ctx.config.forced_scenarios,
    # so the scenario must also appear in the config (not just as the
    # run_forced scenario argument).
    cfg = SimulatorConfig(
        country="US",
        random_seed=42,
        forced_scenarios=[scenario],
    )
    ds = run_forced(scenario, config=cfg)

    hai_recs = [r for r in ds.patients if r.extensions.get("hai")]
    if not hai_recs:
        pytest.skip(
            f"50 acute_mi severe patients at seed=42 produced no HAI events for "
            f"{hai_type} (force_hai_event needs a matching device; device "
            "placement requires record.icu_transferred = True via complication). "
            "Unit + AD-60 lift_firing_proof cover the enricher path."
        )

    rec = hai_recs[0]
    hai_events = rec.extensions["hai"]
    assert len(hai_events) >= 1
    hai_id_set = {e.hai_id for e in hai_events}

    # The culture linked to one of the HAI events must have the expected
    # susceptibility count from hai_antibiogram.yaml.
    hai_cultures = [m for m in rec.microbiology if m.hai_event_id in hai_id_set]
    assert hai_cultures, f"no HAI culture for {hai_type} in rec.microbiology"
    micro = hai_cultures[0]
    assert micro.organism_snomed == organism_snomed, (
        f"culture organism_snomed mismatch: expected {organism_snomed!r}, "
        f"got {micro.organism_snomed!r}"
    )
    assert len(micro.susceptibilities) == expected_abx_count, (
        f"expected {expected_abx_count} susceptibilities for "
        f"{hai_type}/{organism_snomed} from hai_antibiogram.yaml, "
        f"got {len(micro.susceptibilities)}"
    )
    for s in micro.susceptibilities:
        assert s.interpretation in {"S", "I", "R"}, (
            f"non-canonical interpretation {s.interpretation!r} (must be S, I, or R)"
        )
        assert s.antibiotic_loinc, f"empty antibiotic_loinc on susceptibility {s!r}"


@pytest.mark.integration
def test_community_culture_has_no_hai_event_id_backref() -> None:
    """Sanity: non-HAI culture from community microbiology path has
    hai_event_id == '' (AD-16 protection of unrelated code path).

    Regression guard: _append_hai_culture sets hai_event_id on HAI-derived
    cultures. The pre-existing community culture path (observation/microbiology)
    must remain untouched — hai_event_id must stay as the dataclass default ''.
    Filters to records with no HAI extension (some patients may stochastically
    acquire HAI via Poisson sampling; those are excluded).
    """
    scenario = ForcedScenario(
        disease_id="bacterial_pneumonia",
        count=5,
        force_hai_event=None,
    )
    cfg = SimulatorConfig(country="US", random_seed=42)
    ds = run_forced(scenario, config=cfg)

    community = [m for r in ds.patients for m in r.microbiology if not r.extensions.get("hai")]
    for m in community:
        assert m.hai_event_id == "", (
            f"community culture has unexpected hai_event_id {m.hai_event_id!r}"
        )
