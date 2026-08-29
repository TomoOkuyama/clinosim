"""Unit tests for Issue #946 anthropometric FHIR Observation emit.

Coverage:

- Every encounter produces a height + weight + BMI Observation triple.
- BMI is internally consistent (weight / (height/100)^2) within
  0.5 kg/m² (rounding tolerance).
- Pediatric encounters (age ≤ 3 y) add a head-circumference
  Observation; adult encounters do not.
- All emitted values are inside physiologic clamps.
- Per-encounter weight noise is deterministic (SHA256-derived) — same
  patient + same encounter_id → same emitted weight across two runs
  (RNG-shape neutrality).
- The bundle-builder registration (``_bb_anthropometrics``) covers every
  encounter in ``ctx.record["encounters"]``.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from clinosim.modules.output.fhir_r4.labs.anthropometrics import (
    LOINC_BMI,
    LOINC_BODY_HEIGHT,
    LOINC_BODY_WEIGHT,
    LOINC_HEAD_CIRCUMFERENCE,
    _bb_anthropometrics,
    build_anthropometric_observations,
)


def _codes(observations):
    return [o["code"]["coding"][0]["code"] for o in observations]


def _by_code(observations):
    return {o["code"]["coding"][0]["code"]: o for o in observations}


def _adult():
    return {
        "patient_id": "pt-adult",
        "date_of_birth": "1960-05-15",
        "sex": "M",
        "height_cm": 170.0,
        "weight_kg": 65.0,
        "bmi": 22.5,
        "age": 65,
    }


def _pediatric(age_year_of_birth: int = 2023):
    # Encounter at 2025 => age 2 y
    return {
        "patient_id": "pt-ped",
        "date_of_birth": f"{age_year_of_birth}-06-01",
        "sex": "F",
        "age": 2,
    }


def _encounter(encounter_id="enc-1", admission="2025-01-15T09:00:00"):
    return {"encounter_id": encounter_id, "admission_datetime": admission}


def test_adult_encounter_emits_height_weight_bmi():
    obs = build_anthropometric_observations(_adult(), _encounter(), "US")
    codes = _codes(obs)
    assert LOINC_BODY_HEIGHT in codes
    assert LOINC_BODY_WEIGHT in codes
    assert LOINC_BMI in codes
    assert LOINC_HEAD_CIRCUMFERENCE not in codes  # adult: no head-circ


def test_pediatric_under_3_emits_head_circumference():
    obs = build_anthropometric_observations(_pediatric(2023), _encounter(admission="2025-06-15T09:00:00"), "JP")
    codes = _codes(obs)
    assert LOINC_BODY_HEIGHT in codes
    assert LOINC_BODY_WEIGHT in codes
    assert LOINC_BMI in codes
    assert LOINC_HEAD_CIRCUMFERENCE in codes


def test_school_age_no_head_circumference():
    ped = _pediatric(2015)  # age 10 at 2025 encounter
    ped["age"] = 10
    obs = build_anthropometric_observations(ped, _encounter(admission="2025-06-15T09:00:00"), "JP")
    codes = _codes(obs)
    assert LOINC_HEAD_CIRCUMFERENCE not in codes


def test_bmi_consistent_with_height_and_weight():
    obs = _by_code(build_anthropometric_observations(_adult(), _encounter(), "JP"))
    h = obs[LOINC_BODY_HEIGHT]["valueQuantity"]["value"]
    w = obs[LOINC_BODY_WEIGHT]["valueQuantity"]["value"]
    bmi = obs[LOINC_BMI]["valueQuantity"]["value"]
    expected = w / ((h / 100.0) ** 2)
    assert abs(bmi - expected) < 0.5


@pytest.mark.parametrize(
    "patient,encounter,country",
    [
        (_adult(), _encounter(), "US"),
        (_adult(), _encounter(), "JP"),
        (_pediatric(2023), _encounter(admission="2025-06-15T09:00:00"), "US"),
        (_pediatric(2023), _encounter(admission="2025-06-15T09:00:00"), "JP"),
    ],
)
def test_all_values_inside_physiologic_clamps(patient, encounter, country):
    obs = _by_code(build_anthropometric_observations(patient, encounter, country))
    h = obs[LOINC_BODY_HEIGHT]["valueQuantity"]["value"]
    w = obs[LOINC_BODY_WEIGHT]["valueQuantity"]["value"]
    bmi = obs[LOINC_BMI]["valueQuantity"]["value"]
    assert 40.0 <= h <= 210.0
    assert 2.0 <= w <= 200.0
    assert 10.0 <= bmi <= 60.0
    if LOINC_HEAD_CIRCUMFERENCE in obs:
        hc = obs[LOINC_HEAD_CIRCUMFERENCE]["valueQuantity"]["value"]
        assert 30.0 <= hc <= 60.0


def test_per_encounter_deterministic_across_runs():
    # RNG-neutral: SHA256-derived → repeat call yields byte-identical emit.
    p = _adult()
    e = _encounter("enc-abc")
    a = build_anthropometric_observations(p, e, "JP")
    b = build_anthropometric_observations(p, e, "JP")
    for x, y in zip(a, b, strict=True):
        assert x["valueQuantity"]["value"] == y["valueQuantity"]["value"]
        assert x["id"] == y["id"]


def test_per_encounter_weight_varies_across_encounters():
    # Different encounter_id should produce different SHA256-derived weight
    # so the per-encounter drift is actually functioning.
    p = _adult()
    weights = set()
    for i in range(10):
        obs = _by_code(build_anthropometric_observations(p, _encounter(f"enc-{i}"), "JP"))
        weights.add(obs[LOINC_BODY_WEIGHT]["valueQuantity"]["value"])
    assert len(weights) >= 5  # allow some coincidental duplicates


def test_adult_height_is_fixed_per_patient_across_encounters():
    # Adult height must NOT drift per encounter (height is fixed post-adulthood).
    p = _adult()
    heights = set()
    for i in range(10):
        obs = _by_code(build_anthropometric_observations(p, _encounter(f"enc-{i}"), "JP"))
        heights.add(obs[LOINC_BODY_HEIGHT]["valueQuantity"]["value"])
    assert len(heights) == 1


def test_bb_anthropometrics_iterates_all_encounters():
    ctx = SimpleNamespace(
        record={
            "encounters": [
                _encounter("enc-1", "2025-01-01T09:00:00"),
                _encounter("enc-2", "2025-02-01T09:00:00"),
                _encounter("enc-3", "2025-03-01T09:00:00"),
            ]
        },
        patient_data=_adult(),
        country="JP",
        patient_id="pt-adult",
    )
    obs = _bb_anthropometrics(ctx)
    # 3 encounters × 3 observations (adult, no head-circ) = 9
    assert len(obs) == 9
    # 3 distinct encounter references (canonical id may be opaque-mapped
    # by encounter_ref — we only check that the emit was per-encounter).
    refs = {o["encounter"]["reference"] for o in obs}
    assert len(refs) == 3


def test_jp_display_localization():
    obs = _by_code(build_anthropometric_observations(_adult(), _encounter(), "JP"))
    assert obs[LOINC_BODY_HEIGHT]["code"]["text"] == "身長"
    assert obs[LOINC_BODY_WEIGHT]["code"]["text"] == "体重"
    assert obs[LOINC_BMI]["code"]["text"] == "BMI"
    # JP Observation_Common profile stamped on meta.
    assert "JP_Observation_Common" in obs[LOINC_BODY_HEIGHT]["meta"]["profile"][0]


def test_us_display_localization():
    obs = _by_code(build_anthropometric_observations(_adult(), _encounter(), "US"))
    assert obs[LOINC_BODY_HEIGHT]["code"]["text"] == "Body height"
    assert obs[LOINC_BODY_WEIGHT]["code"]["text"] == "Body weight"
    # US emit: no JP profile stamp.
    assert "meta" not in obs[LOINC_BODY_HEIGHT]
