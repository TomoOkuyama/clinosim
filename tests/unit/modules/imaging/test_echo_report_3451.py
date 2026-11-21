"""Issue #3451: a heart-failure admission's echocardiogram reads abnormal, and
the echo procedure and its imaging study share one time."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from clinosim.locale.i18n import t
from clinosim.modules.imaging.engine import imaging_enricher
from clinosim.simulator.encounter_setup import align_echo_procedures_to_imaging
from clinosim.types.encounter import Order, OrderStatus, OrderType
from clinosim.types.procedure import ProcedureRecord

pytestmark = pytest.mark.unit

_ADMIT = datetime(2024, 4, 1, 20, 0)
_NORMAL = (
    t("imaging_report.generic_negative_impression", "ja"),
    t("imaging_report.generic_negative_impression", "en"),
)


def _order(name: str, enc: str = "enc1", when: datetime = _ADMIT) -> Order:
    return Order(
        order_id=f"ORD-{enc}-I01",
        encounter_id=enc,
        patient_id="pt1",
        order_type=OrderType.IMAGING,
        display_name=name,
        urgency="urgent",
        ordered_datetime=when,
        status=OrderStatus.PLACED,
    )


def _report(disease: str, enc: str = "enc1", name: str = "Echocardiogram"):
    record = SimpleNamespace(
        patient=SimpleNamespace(patient_id="pt1", chronic_conditions=[]),
        orders=[_order(name, enc)],
        extensions={"_disease_id": disease},
        severity="moderate",
        encounters=[SimpleNamespace(encounter_id=enc, admission_datetime=_ADMIT)],
        clinical_diagnosis=SimpleNamespace(admission_diagnosis_code="I50.9", discharge_diagnosis_code="I50.9"),
        vital_signs=[],
    )
    imaging_enricher(SimpleNamespace(master_seed=42, records=[record], config=SimpleNamespace()))
    return record.extensions["imaging"][0].report


def _lvef(text: str) -> int:
    m = re.search(r"(\d+)\s*%", text)
    assert m
    return int(m.group(1))


def test_heart_failure_echo_is_never_the_generic_normal_report() -> None:
    for i in range(40):
        rep = _report("heart_failure_exacerbation", f"enc{i}")
        assert rep.impression_text not in _NORMAL and rep.impression_text_ja not in _NORMAL
        assert "LVEF" in rep.findings_text and "LVEF" in rep.findings_text_ja


def test_phenotypes_follow_the_guideline_ef_classes() -> None:
    seen = set()
    for i in range(200):
        rep = _report("heart_failure_exacerbation", f"enc{i}")
        ef = _lvef(rep.findings_text)
        seen.add("hfref" if ef <= 40 else "hfmref" if ef <= 49 else "hfpef")
        if ef >= 50:
            assert "preserved" in rep.impression_text.lower()
        elif ef <= 40:
            assert "reduced" in rep.impression_text.lower() and "mildly" not in rep.impression_text.lower()
    assert seen == {"hfref", "hfmref", "hfpef"}


def test_the_report_is_stable_per_encounter_and_localized() -> None:
    a, b = _report("heart_failure_exacerbation", "encX"), _report("heart_failure_exacerbation", "encX")
    assert a.findings_text == b.findings_text
    assert re.search(r"[ぁ-ん]", a.findings_text_ja) and not re.search(r"[ぁ-ん]", a.findings_text)


def test_a_non_heart_failure_echo_is_unchanged() -> None:
    rep = _report("pulmonary_embolism")
    assert "LVEF" not in rep.findings_text


def test_echo_procedure_takes_the_imaging_study_time() -> None:
    proc = ProcedureRecord(
        procedure_id="P1",
        patient_id="pt1",
        encounter_id="enc1",
        procedure_type="echocardiography",
        procedure_code="x",
        start_datetime=_ADMIT + timedelta(hours=26),
        end_datetime=_ADMIT + timedelta(hours=26, minutes=30),
        duration_minutes=30,
    )
    other = _order("Chest_Xray_PA", when=_ADMIT + timedelta(hours=2))
    echo = _order("Echocardiogram", when=_ADMIT + timedelta(hours=9))
    align_echo_procedures_to_imaging([proc], [other, echo])
    assert proc.start_datetime == echo.ordered_datetime
    assert proc.end_datetime - proc.start_datetime == timedelta(minutes=30)
