"""Issue #3020: ECG and coronary angiography reports are worded as such.

An ECG report states rhythm, rate, axis, intervals and ST-T findings from the
patient's state (the acute-MI territory, atrial fibrillation, the heart rate
at the recording); a coronary angiography report names the culprit lesion.
Neither uses the radiology "no acute findings in the imaged field" wording,
and neither is signed by a radiologist.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from clinosim.locale.i18n import t
from clinosim.modules.imaging.engine import imaging_enricher
from clinosim.types.encounter import Order, OrderStatus, OrderType, VitalSignRecord

pytestmark = pytest.mark.unit

_ADMIT = datetime(2024, 4, 1, 20, 0)


def _order(name: str, when: datetime, idx: int = 1) -> Order:
    return Order(
        order_id=f"ORD-enc1-I{idx:02d}",
        encounter_id="enc1",
        patient_id="pt1",
        order_type=OrderType.IMAGING,
        display_name=name,
        urgency="stat",
        ordered_datetime=when,
        status=OrderStatus.PLACED,
    )


def _reports(icd: str, disease: str, orders: list[Order], hr: int = 88, chronic: tuple[str, ...] = ()) -> list:
    record = SimpleNamespace(
        patient=SimpleNamespace(patient_id="pt1", chronic_conditions=[SimpleNamespace(code=c) for c in chronic]),
        orders=orders,
        extensions={"_disease_id": disease},
        severity="moderate",
        encounters=[SimpleNamespace(encounter_id="enc1", admission_datetime=_ADMIT)],
        clinical_diagnosis=SimpleNamespace(admission_diagnosis_code=icd, discharge_diagnosis_code=icd),
        vital_signs=[VitalSignRecord(timestamp=_ADMIT, heart_rate=hr, systolic_bp=150, diastolic_bp=90)],
    )
    imaging_enricher(SimpleNamespace(master_seed=42, records=[record], config=SimpleNamespace()))
    return [s.report for s in record.extensions["imaging"]]


_IMAGING_NEGATIVE = (
    t("imaging_report.generic_negative_impression", "ja"),
    t("imaging_report.generic_negative_impression", "en"),
)


def test_an_acute_mi_ecg_report_mentions_st_elevation() -> None:
    [rep] = _reports("I21.0", "acute_mi", [_order("ECG_12lead", _ADMIT)])
    assert "ST 上昇" in rep.findings_text_ja and "V1-V4" in rep.findings_text_ja
    assert "ST elevation" in rep.findings_text
    assert "HR 88" in rep.findings_text_ja
    assert rep.impression_text_ja not in _IMAGING_NEGATIVE


def test_an_inferior_mi_angiography_names_the_right_coronary_artery() -> None:
    [ecg, cag] = _reports(
        "I21.1", "acute_mi", [_order("ECG_12lead", _ADMIT), _order("Coronary_angiography", _ADMIT, 2)]
    )
    assert "II・III・aVF" in ecg.findings_text_ja
    assert "右冠動脈" in cag.findings_text_ja
    assert "Right coronary artery" in cag.findings_text or "right coronary artery" in cag.findings_text


def test_an_nstemi_ecg_shows_st_depression_not_elevation() -> None:
    [rep] = _reports("I21.4", "acute_mi", [_order("ECG_12lead", _ADMIT)])
    assert "ST 低下" in rep.findings_text_ja and "ST 上昇" not in rep.findings_text_ja


def test_atrial_fibrillation_with_rapid_rate() -> None:
    [rep] = _reports("I48.91", "atrial_fibrillation_rvr", [_order("ECG_12lead", _ADMIT)], hr=142)
    assert "心房細動" in rep.findings_text_ja and "HR 142" in rep.findings_text_ja
    assert "PR" not in rep.findings_text_ja


def test_a_patient_without_cardiac_disease_has_a_normal_ecg() -> None:
    [rep] = _reports("N39.0", "urinary_tract_infection", [_order("ECG_12lead", _ADMIT)], hr=76)
    assert "洞調律" in rep.findings_text_ja and "ST-T 変化なし" in rep.findings_text_ja
    assert rep.impression_text_ja == t("cardiac_report.ecg_impression_normal", "ja")
    for r in (rep.findings_text_ja, rep.impression_text_ja, rep.findings_text, rep.impression_text):
        assert "撮像" not in r and "imaged" not in r


def test_ecg_is_not_signed_by_a_radiologist() -> None:
    from clinosim.modules.output.fhir_r4.labs.diagnostic_report import RADIOLOGY_DR_ID_PREFIX, _bb_diagnostic_reports

    [rep] = _reports("I21.0", "acute_mi", [_order("ECG_12lead", _ADMIT)])
    study = SimpleNamespace(
        study_id="imgst-enc1-1",
        encounter_id="enc1",
        patient_id="pt1",
        order_id="ORD-enc1-I01",
        modality_code="ECG",
        body_site_snomed="51185008",
        started_datetime=_ADMIT,
        report=rep,
        views=["12-lead"],
    )
    ctx = SimpleNamespace(
        record={
            "extensions": {"imaging": [study]},
            "orders": [],
            "encounters": [{"encounter_id": "enc1", "attending_physician_id": "DR-IM-001"}],
        },
        country="JP",
        patient_id="pt1",
        primary_enc_id="enc1",
        roster_map={"DR-RAD-001": {"role": "radiologist"}, "DR-IM-001": {"role": "physician"}},
    )
    [dr] = [r for r in _bb_diagnostic_reports(ctx) if r["id"].startswith(RADIOLOGY_DR_ID_PREFIX)]
    assert dr["resultsInterpreter"] == [{"reference": "Practitioner/DR-IM-001"}]
