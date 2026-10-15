"""Discharge-time stroke-sequela promotion (helpers.py).

Verifies that ``_promote_stroke_sequela_at_discharge`` immediately
appends the correct I69.3 / I69.1 chronic condition and samples an
initial mRS stage on survival-at-discharge from a stroke encounter.
Mirrors the aging-pass promotion test coverage in
``test_aging_hook_1564`` but exercises the earlier (dispatch-path)
promotion.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from clinosim.simulator.helpers import (
    _promote_stroke_sequela_at_discharge,
    _sha_weighted_choice,
)
from clinosim.types.population import HospitalizationSummary, PersonRecord


def _alive(pid: str = "PT-STROKE") -> PersonRecord:
    return PersonRecord(
        person_id=pid,
        household_id="HH-1",
        age=70,
        sex="M",
        date_of_birth=date(1956, 1, 1),
    )


@dataclass
class _FakeRecord:
    deceased: bool = False


def _summary(disease_id: str, encounter_id: str = "ENC-A") -> HospitalizationSummary:
    return HospitalizationSummary(
        encounter_id=encounter_id,
        disease_id=disease_id,
        admission_date=date(2025, 3, 1),
        discharge_date=date(2025, 3, 10),
        los_days=9,
        outcome="discharged",
    )


def test_sha_weighted_choice_deterministic() -> None:
    """Same salt → same choice across calls (byte-reproducible)."""
    choices = ("mRS 0", "mRS 1", "mRS 2", "mRS 3", "mRS 4", "mRS 5")
    weights = (0.10, 0.20, 0.25, 0.20, 0.15, 0.10)
    a = _sha_weighted_choice("PT-X|stroke_mrs|ENC-X|v1", choices, weights)
    b = _sha_weighted_choice("PT-X|stroke_mrs|ENC-X|v1", choices, weights)
    assert a == b


def test_sha_weighted_choice_different_salts_can_differ() -> None:
    """Different salts → generally different choices (spot-check)."""
    choices = ("mRS 0", "mRS 1", "mRS 2", "mRS 3", "mRS 4", "mRS 5")
    weights = (0.10, 0.20, 0.25, 0.20, 0.15, 0.10)
    seen = {_sha_weighted_choice(f"PT-{i}|stroke_mrs|ENC-A|v1", choices, weights) for i in range(50)}
    # 50 distinct salts should produce at least 2 different stage draws.
    assert len(seen) >= 2


def test_promote_adds_i69_3_from_cerebral_infarction_survivor() -> None:
    p = _alive("PT-ISC")
    _promote_stroke_sequela_at_discharge(
        p, "cerebral_infarction", _FakeRecord(deceased=False), _summary("cerebral_infarction")
    )
    assert "I69.3" in p.chronic_conditions
    assert p.disease_stages.get("I69") in {"mRS 0", "mRS 1", "mRS 2", "mRS 3", "mRS 4", "mRS 5"}
    # disease_stage_history also populated keyed by discharge year.
    assert 2025 in (p.disease_stage_history.get("I69") or {})


def test_promote_adds_i69_1_from_hemorrhagic_survivor() -> None:
    p = _alive("PT-HEM")
    _promote_stroke_sequela_at_discharge(
        p, "hemorrhagic_stroke", _FakeRecord(deceased=False), _summary("hemorrhagic_stroke")
    )
    assert "I69.1" in p.chronic_conditions
    assert p.disease_stages.get("I69") in {"mRS 0", "mRS 1", "mRS 2", "mRS 3", "mRS 4", "mRS 5"}


def test_promote_skips_on_deceased() -> None:
    """A deceased stroke patient MUST NOT be promoted to a chronic
    sequela — mRS 6 is death, handled by reactive mortality, and
    appending a chronic condition to a dead patient would corrupt
    downstream reporting."""
    p = _alive("PT-DEAD")
    _promote_stroke_sequela_at_discharge(
        p, "cerebral_infarction", _FakeRecord(deceased=True), _summary("cerebral_infarction")
    )
    assert "I69.3" not in p.chronic_conditions


def test_promote_idempotent_on_repeat_discharge() -> None:
    """A second stroke discharge (e.g. recurrent infarction) must
    not re-append the sequela ICD nor re-sample the mRS stage —
    the chronic condition is already tracked."""
    p = _alive("PT-REPEAT")
    _promote_stroke_sequela_at_discharge(
        p, "cerebral_infarction", _FakeRecord(deceased=False), _summary("cerebral_infarction", "ENC-FIRST")
    )
    first_stage = p.disease_stages["I69"]
    _promote_stroke_sequela_at_discharge(
        p, "cerebral_infarction", _FakeRecord(deceased=False), _summary("cerebral_infarction", "ENC-SECOND")
    )
    assert p.chronic_conditions.count("I69.3") == 1
    assert p.disease_stages["I69"] == first_stage


def test_promote_noop_for_non_stroke_disease_id() -> None:
    """Non-stroke encounters MUST NOT promote any sequela."""
    p = _alive("PT-UTI")
    _promote_stroke_sequela_at_discharge(
        p, "urinary_tract_infection", _FakeRecord(deceased=False), _summary("urinary_tract_infection")
    )
    assert "I69.3" not in p.chronic_conditions
    assert "I69.1" not in p.chronic_conditions


def test_promote_uses_per_sub_code_mrs_distribution() -> None:
    """Monte-Carlo spot-check: hemorrhagic I69.1 cohort has mean mRS
    index strictly above ischemic I69.3 cohort (same salt scheme,
    different weight vectors)."""
    stage_idx = {"mRS 0": 0, "mRS 1": 1, "mRS 2": 2, "mRS 3": 3, "mRS 4": 4, "mRS 5": 5}

    def _mean(disease_id: str) -> float:
        total = 0.0
        for i in range(500):
            p = _alive(f"PT-{disease_id}-{i:04d}")
            _promote_stroke_sequela_at_discharge(
                p,
                disease_id,
                _FakeRecord(deceased=False),
                _summary(disease_id, f"ENC-{i}"),
            )
            total += stage_idx[p.disease_stages["I69"]]
        return total / 500

    ischemic_mean = _mean("cerebral_infarction")
    hemorrhagic_mean = _mean("hemorrhagic_stroke")
    assert hemorrhagic_mean > ischemic_mean + 0.3, (
        f"hemorrhagic mean mRS ({hemorrhagic_mean:.2f}) should exceed "
        f"ischemic mean ({ischemic_mean:.2f}) by ≥ 0.3 — weight routing may be broken"
    )
