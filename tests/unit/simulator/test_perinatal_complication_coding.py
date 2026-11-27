"""The complication codes of a delivery agree with the birth the record
describes (Issue #3661): O80 / O82 only for an uncomplicated delivery (the
complication is the principal diagnosis otherwise), a preterm-delivery code
only below 37 weeks, an obstructed-labor code only for a cesarean."""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pytest

from clinosim.locale.loader import load_perinatal_config
from clinosim.modules.staff.engine import StaffRoster
from clinosim.simulator.perinatal import simulate_delivery_encounter
from clinosim.types.patient import PatientProfile, TemporalStatePeriod

pytestmark = pytest.mark.unit

_DELIVERY = datetime(2024, 7, 15, 10, 0)
# Patient ids whose cesarean sub-RNG roll lands vaginal / cesarean in both
# countries (checked by ``test_the_fixture_ids_roll_the_expected_mode``).
_VAGINAL = "POP-000001"
_CESAREAN = "POP-000003"


def _deliver(pid: str, complications: list[str], ga_days: int = 280, country: str = "US"):
    patient = PatientProfile(patient_id=pid, sex="F", age=28)
    lmp = _DELIVERY.date() - timedelta(days=ga_days)
    patient.state_periods = [
        TemporalStatePeriod(
            state_type="pregnancy",
            start_date=lmp,
            end_date=None,
            outcome="",
            metadata={
                "lmp": lmp,
                "edd": lmp + timedelta(days=280),
                "planned_delivery_date": _DELIVERY.date(),
                "complications": complications,
            },
            period_seq=0,
        )
    ]
    records = simulate_delivery_encounter(
        patient=patient,
        visit_date=_DELIVERY,
        roster=StaffRoster(),
        rng=np.random.default_rng(42),
        country=country,
        hospital_ops={},
    )
    return records[0]


def test_the_fixture_ids_roll_the_expected_mode() -> None:
    for country in ("US", "JP"):
        assert _deliver(_VAGINAL, [], country=country).extensions["delivery"]["mode"] == "vaginal"
        assert _deliver(_CESAREAN, [], country=country).extensions["delivery"]["mode"] == "cesarean"


def _working(rec) -> list[str]:
    return [d["disease_id"] for d in rec.clinical_diagnosis.working_diagnoses]


@pytest.mark.parametrize(("pid", "uncomplicated"), [(_VAGINAL, "O80"), (_CESAREAN, "O82")])
def test_uncomplicated_delivery_keeps_the_mode_code(pid: str, uncomplicated: str) -> None:
    rec = _deliver(pid, [])
    assert rec.clinical_diagnosis.admission_diagnosis_code == uncomplicated
    assert _working(rec) == []
    assert rec.clinical_diagnosis.discharge_diagnosis_code == uncomplicated  # Issue #3913
    assert rec.condition_event.ground_truth_diseases == ["Z37.0"]


@pytest.mark.parametrize("pid", [_VAGINAL, _CESAREAN])
@pytest.mark.parametrize("country", ["US", "JP"])
def test_complicated_delivery_is_not_admitted_as_uncomplicated(pid: str, country: str) -> None:
    rec = _deliver(pid, ["O24.9", "O14.9"], country=country)
    assert rec.clinical_diagnosis.admission_diagnosis_code == "O24.9"
    assert _working(rec) == ["O14.9"]
    assert rec.clinical_diagnosis.discharge_diagnosis_code == "O24.9"  # Issue #3913: Z37.0 is secondary
    assert rec.clinical_diagnosis.secondary_diagnosis_codes == ["Z37.0"]
    assert rec.condition_event.ground_truth_diseases == ["Z37.0", "O24.9", "O14.9"]
    assert rec.condition_event.condition_type == "mixed"
    # the chief complaint still names the mode of delivery
    cc = (rec.encounters[0].chief_complaint or "").lower()
    assert ("cesarean" in cc) == (pid == _CESAREAN)


def test_preterm_delivery_code_is_dropped_at_term() -> None:
    for ga in (273, 280, 287):
        rec = _deliver(_VAGINAL, ["O60.1", "O14.9"], ga_days=ga)
        assert "O60.1" not in {rec.clinical_diagnosis.admission_diagnosis_code, *_working(rec)}
        assert rec.clinical_diagnosis.admission_diagnosis_code == "O14.9"


def test_preterm_delivery_code_is_kept_below_37_weeks() -> None:
    rec = _deliver(_VAGINAL, ["O60.1"], ga_days=250)
    assert rec.clinical_diagnosis.admission_diagnosis_code == "O60.1"


def test_term_delivery_with_only_a_preterm_code_is_uncomplicated() -> None:
    rec = _deliver(_VAGINAL, ["O60.1"])
    assert rec.clinical_diagnosis.admission_diagnosis_code == "O80"
    assert rec.condition_event.condition_type == "perinatal_delivery"
    assert rec.extensions["delivery"]["complication_codes"] == []


def test_obstructed_labor_is_dropped_on_a_vaginal_delivery_and_kept_on_a_cesarean() -> None:
    vaginal = _deliver(_VAGINAL, ["O64.9"])
    assert vaginal.clinical_diagnosis.admission_diagnosis_code == "O80"
    cesarean = _deliver(_CESAREAN, ["O64.9"])
    assert cesarean.clinical_diagnosis.admission_diagnosis_code == "O64.9"


def test_delivery_extension_records_mode_age_and_complications() -> None:
    vaginal = _deliver(_VAGINAL, ["O14.9", "O60.1"], ga_days=277)
    ext = dict(vaginal.extensions["delivery"])
    ext.pop("estimated_blood_loss_ml")  # tested with the delivery blood loss
    assert ext == {
        "mode": "vaginal",
        "gestational_age_days": 277,
        "complication_codes": ["O14.9"],
    }
    cesarean = _deliver(_CESAREAN, [], ga_days=280)
    assert cesarean.extensions["delivery"]["mode"] == "cesarean"
    assert cesarean.extensions["delivery"]["complication_codes"] == []


def test_complication_rows_are_well_formed() -> None:
    rows = load_perinatal_config()["complications"]["bernoulli_draws"]
    allowed = {"code", "probability", "gestational_weeks_below", "modes"}
    for row in rows:
        assert set(row) <= allowed, row
        assert row["code"] and 0 <= float(row["probability"]) <= 1
        if "gestational_weeks_below" in row:
            assert float(row["gestational_weeks_below"]) > 0
        if "modes" in row:
            assert row["modes"] and set(row["modes"]) <= {"vaginal", "cesarean"}
    by_code = {r["code"]: r for r in rows}
    assert by_code["O60.1"]["gestational_weeks_below"] == 37
    assert by_code["O64.9"]["modes"] == ["cesarean"]
