"""Issue #3274 (part b): an "AF with RVR" admission has a rapid ventricular rate.

The heart rate was derived from the sinus baseline plus the physiology terms
only, so an admission coded and written as atrial fibrillation with rapid
ventricular response showed 77-90/min throughout. The AF protocol now declares
its ventricular rate (``ventricular_rate``): a presenting rate above 110/min by
severity until the first rate-control dose, falling to a controlled rate below
100/min over the archetype's time to control. The recorded heart rate is the
higher of that rate and the physiology-derived one. All values are hash draws
keyed on the encounter (no stream draw).
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from clinosim.modules.disease.protocol import VentricularRateSpec, load_disease_protocol
from clinosim.modules.physiology.engine import derive_vital_signs
from clinosim.simulator.ventricular_rate import (
    VentricularRateCourse,
    first_rate_control_dose,
    presenting_ventricular_rate,
)
from clinosim.types.clinical import PhysiologicalState
from clinosim.types.encounter import MedicationAdministration
from clinosim.types.patient import BaselineVitals

pytestmark = pytest.mark.unit

_T0 = datetime(2026, 3, 1, 10, 0)
_RVR_ABOVE = 110  # 2023 ACC/AHA/ACCP/HRS 7.1: resting target < 100-110 bpm
_CONTROLLED_BELOW = 100


def _spec() -> VentricularRateSpec:
    spec = load_disease_protocol("atrial_fibrillation_rvr").ventricular_rate
    assert spec is not None
    return spec


def _baseline() -> BaselineVitals:
    return BaselineVitals(
        temperature=36.6, heart_rate=72, systolic_bp=122, diastolic_bp=76, respiratory_rate=14, spo2=98.0
    )


@pytest.mark.parametrize("severity", ["mild", "moderate", "severe"])
def test_the_presenting_rate_is_rapid_at_every_severity(severity: str) -> None:
    spec = _spec()
    rates = [presenting_ventricular_rate(spec, severity, f"ENC-{i}") for i in range(200)]
    assert min(rates) > _RVR_ABOVE
    band = spec.presenting_bpm[severity]
    assert band.min <= min(rates) and max(rates) <= band.max
    assert len(set(rates)) > 50  # varies by encounter


def test_severity_orders_the_presenting_rate() -> None:
    spec = _spec()
    assert spec.presenting_bpm["mild"].max < spec.presenting_bpm["moderate"].min
    assert spec.presenting_bpm["moderate"].max < spec.presenting_bpm["severe"].min


def test_the_rate_is_deterministic_per_encounter() -> None:
    spec = _spec()
    assert presenting_ventricular_rate(spec, "moderate", "ENC-X") == presenting_ventricular_rate(
        spec, "moderate", "ENC-X"
    )


def test_the_controlled_rate_is_below_100() -> None:
    spec = _spec()
    assert spec.discharge_below_bpm == _CONTROLLED_BELOW
    for i in range(200):
        course = VentricularRateCourse.build(spec, "moderate", "smooth_recovery", f"ENC-{i}", _T0)
        assert course.controlled < _CONTROLLED_BELOW


def test_the_rate_falls_from_the_first_rate_control_dose() -> None:
    spec = _spec()
    course = VentricularRateCourse.build(spec, "moderate", "smooth_recovery", "ENC-1", _T0)
    hours = spec.hours_to_control_for("smooth_recovery")
    assert course.at(_T0 - timedelta(hours=1)) == course.presenting
    assert course.at(_T0) == course.presenting
    mid = course.at(_T0 + timedelta(hours=hours / 2))
    assert course.controlled < mid < course.presenting
    assert course.at(_T0 + timedelta(hours=hours)) == course.controlled
    assert course.at(_T0 + timedelta(days=5)) == course.controlled


def test_without_rate_control_the_rate_stays_rapid() -> None:
    course = VentricularRateCourse.build(_spec(), "mild", "smooth_recovery", "ENC-1", None)
    assert course.at(_T0 + timedelta(days=3)) == course.presenting


def test_a_refractory_archetype_takes_longer_to_control() -> None:
    spec = _spec()
    assert spec.hours_to_control_for("plateau_then_recovery") > spec.hours_to_control_for("smooth_recovery")
    assert spec.hours_to_control_for("treatment_resistant") > spec.hours_to_control_for("smooth_recovery")
    assert spec.hours_to_control_for("not_an_archetype") == spec.hours_to_control.default


def _mar(drug: str, hour: int, status: str = "given") -> MedicationAdministration:
    at = _T0 + timedelta(hours=hour)
    return MedicationAdministration(
        drug_name=drug, scheduled_datetime=at, actual_datetime=at if status == "given" else None, status=status
    )


def test_the_first_rate_control_dose_is_the_earliest_given_one() -> None:
    mars = [
        _mar("Apixaban", 0),
        _mar("Metoprolol", 1, status="held"),
        _mar("Digoxin", 3),
        _mar("Diltiazem", 2),
    ]
    assert first_rate_control_dose(_spec(), mars) == _T0 + timedelta(hours=2)


def test_no_rate_control_dose_gives_none() -> None:
    assert first_rate_control_dose(_spec(), [_mar("Apixaban", 0), _mar("Heparin", 1)]) is None


@pytest.mark.parametrize("drug", ["Metoprolol", "Landiolol hydrochloride", "Diltiazem", "Digoxin", "Amiodarone"])
def test_every_af_rate_control_agent_counts(drug: str) -> None:
    assert first_rate_control_dose(_spec(), [_mar(drug, 0)]) == _T0


def test_the_ventricular_rate_sets_the_heart_rate() -> None:
    calm = PhysiologicalState()
    assert derive_vital_signs(calm, _baseline(), _T0, ventricular_rate=138.0)["heart_rate"] == 138
    assert derive_vital_signs(calm, _baseline(), _T0, ventricular_rate=None) == derive_vital_signs(
        calm, _baseline(), _T0
    )


def test_a_faster_physiology_rate_is_not_lowered() -> None:
    shocked = PhysiologicalState(perfusion_status=0.3, volume_status=-0.5, sympathetic_activation=0.8)
    sinus = derive_vital_signs(shocked, _baseline(), _T0)["heart_rate"]
    assert derive_vital_signs(shocked, _baseline(), _T0, ventricular_rate=90.0)["heart_rate"] == sinus


def test_the_spec_rejects_an_unknown_rate_control_class() -> None:
    data = _spec().model_dump()
    data["rate_control_classes"] = ["not_a_class"]
    with pytest.raises(ValueError, match="not_a_class"):
        VentricularRateSpec.model_validate(data)


def test_the_dead_admission_heart_rate_distribution_is_gone() -> None:
    evd = load_disease_protocol("atrial_fibrillation_rvr").expected_vital_distributions
    assert "heart_rate" not in (evd.get("admission") or {})


def test_af_admissions_record_rvr_then_rate_control() -> None:
    from clinosim.simulator.engine import run_forced
    from clinosim.types.config import ForcedScenario, SimulatorConfig

    spec = _spec()
    for country in ("US", "JP"):
        scenario = ForcedScenario(
            disease_id="atrial_fibrillation_rvr", count=4, patient_overrides={"age": 74, "sex": "M"}
        )
        dataset = run_forced(scenario, SimulatorConfig(random_seed=11, country=country))
        stays = [r for r in dataset.patients if r.encounters and r.vital_signs]
        assert stays
        for r in stays:
            enc = r.encounters[0]
            first_dose = first_rate_control_dose(spec, r.medication_administrations)
            assert first_dose is not None, (country, enc.encounter_id)
            hrs = sorted((v for v in r.vital_signs if v.heart_rate is not None), key=lambda v: v.timestamp)
            before = [v for v in hrs if v.timestamp <= first_dose]
            assert before, (country, enc.encounter_id)  # at least the ED arrival set
            assert all(v.heart_rate > _RVR_ABOVE for v in before), (country, enc.encounter_id)
            assert hrs[-1].heart_rate < _RVR_ABOVE, (country, enc.encounter_id)
            # Not discharged before the rate is controlled (below the cap).
            course = VentricularRateCourse.build(
                spec, enc.severity, enc.clinical_course_archetype, enc.encounter_id, first_dose
            )
            assert course.at(enc.discharge_datetime) < spec.discharge_below_bpm, (country, enc.encounter_id)
