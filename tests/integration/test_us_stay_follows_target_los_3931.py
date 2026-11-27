"""A US inpatient stay follows ``target_los.us`` as a Japanese one follows ``target_los.japan`` (Issue #3931).

The disease courses are authored on the Japanese stay length, so a US patient was still febrile or
hypoperfused at the end of the sampled stay and the discharge gates held him for days beyond the protocol's
maximum. The courses are pinned to a recovering archetype: a deteriorating one may stay longer by design.
"""

from __future__ import annotations

import statistics

import pytest

from clinosim.modules.disease.protocol import load_disease_protocol
from clinosim.simulator import run_forced
from clinosim.types.config import ForcedScenario, SimulatorConfig

COMMON = (
    "bacterial_pneumonia",
    "heart_failure_exacerbation",
    "copd_exacerbation",
    "acute_mi",
    "urinary_tract_infection",
)


def _stays(disease_id: str, country: str, severity: str = "moderate", count: int = 10) -> list[int]:
    scenario = ForcedScenario(disease_id=disease_id, count=count, severity=severity, archetype="smooth_recovery")
    dataset = run_forced(scenario, SimulatorConfig(random_seed=3931, country=country))
    return [len(r.physiological_states) - 1 for r in dataset.patients]


@pytest.mark.parametrize("disease_id", COMMON)
def test_us_stays_stay_within_the_target_maximum_and_do_not_average_past_its_mean(disease_id: str) -> None:
    target = load_disease_protocol(disease_id).target_los["us"]["moderate"]
    los = _stays(disease_id, "US")
    assert los
    assert max(los) <= target["max"], los
    assert statistics.mean(los) <= target["mean"], los


def test_japanese_stable_stays_are_kept_to_their_sampled_target() -> None:
    """The faster course does not shorten a Japanese stay: a stable patient stays until the sampled target
    (Japanese practice), so the mean stays within a day of the target mean (10.1 without the practice rule)."""
    target = load_disease_protocol("copd_exacerbation").target_los["japan"]["moderate"]
    los = _stays("copd_exacerbation", "JP", count=30)
    assert statistics.mean(los) >= target["mean"] - 1, los
