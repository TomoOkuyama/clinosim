"""The admitted patient's ED note is written from ED-time data (Issue #3242).

For a via-ED admission the ED note is rendered on the stay's record, whose
orders include the continued home medications, ward-care orders written with
the admission and the following days' treatment, and whose first vital signs
are the first ward reading. The ED workup lists only the initial order set
(``Order.order_set``) and the "On arrival" vitals are a reading taken by the
admission time, or are left out.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from clinosim.modules._shared import ORDER_SET_ADMISSION_CARE, ORDER_SET_ADMISSION_INITIAL
from clinosim.modules.document.narrative.renderers.section_builders.ed_note import (
    build_ed_physical_exam,
    build_ed_workup,
)
from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator
from clinosim.types.document import DocumentType, NarrativeContext
from clinosim.types.patient import PatientProfile

pytestmark = pytest.mark.unit

_ADMIT = datetime(2025, 11, 20, 18, 35)


def _encounter(enc_type: str) -> SimpleNamespace:
    return SimpleNamespace(
        encounter_id="ENC-1",
        encounter_type=SimpleNamespace(value=enc_type),
        admission_datetime=_ADMIT,
        chief_complaint="Chest pain",
        chief_complaint_ja="胸痛",
        severity="moderate",
        discharge_disposition="home",
    )


def _order(name: str, when: datetime, order_set: str = "", otype: str = "medication") -> dict:
    return {
        "order_id": f"ORD-{name}",
        "encounter_id": "ENC-1",
        "order_type": otype,
        "display_name": name,
        "ordered_datetime": when.isoformat(),
        "order_set": order_set,
    }


_ORDERS = [
    _order("Troponin_I", datetime(2025, 11, 20, 18, 40), ORDER_SET_ADMISSION_INITIAL, "lab"),
    _order("Aspirin", datetime(2025, 11, 20, 18, 50), ORDER_SET_ADMISSION_INITIAL),
    _order("Heparin", datetime(2025, 11, 20, 19, 0), ORDER_SET_ADMISSION_INITIAL),
    # Continued home medications.
    _order("Amlodipine", datetime(2025, 11, 20, 19, 35)),
    _order("Atorvastatin", datetime(2025, 11, 20, 19, 35)),
    # Ward VTE prophylaxis and the next day's treatment.
    _order("Enoxaparin", datetime(2025, 11, 21, 0, 35)),
    _order("Patiromer", datetime(2025, 11, 21, 17, 57)),
    # Ward care written with the admission.
    _order(
        "urinary_catheter: Foley catheter for perioperative period",
        datetime(2025, 11, 20, 19, 0),
        ORDER_SET_ADMISSION_CARE,
        "procedure",
    ),
]


def _ctx(enc_type: str, lang: str, orders: list, vitals: list | None = None) -> NarrativeContext:
    return NarrativeContext(
        patient=PatientProfile(patient_id="PT-1"),
        encounter=_encounter(enc_type),
        encounter_type=SimpleNamespace(value=enc_type),
        disease_protocol=None,
        encounter_protocol=None,
        clinical_course_archetype="uncomplicated_improvement",
        severity="moderate",
        day_index=0,
        los_days=3,
        vitals=vitals or [],
        lab_results=[],
        medications=[],
        diagnoses=[],
        procedures=[],
        allergies=[],
        document_type=DocumentType.ED_NOTE,
        target_lang=lang,
        locale="jp" if lang == "ja" else "us",
        orders=orders,
    )


def _vital(when: datetime, hr: int) -> dict:
    return {
        "timestamp": when.isoformat(),
        "systolic_bp": 115,
        "diastolic_bp": 78,
        "heart_rate": hr,
        "respiratory_rate": 18,
        "spo2": 97.0,
        "temperature_celsius": 37.2,
    }


def test_admitted_ed_workup_lists_only_the_initial_order_set() -> None:
    text, _ = build_ed_workup(TemplateNarrativeGenerator(), _ctx("inpatient", "en", _ORDERS))
    assert "Aspirin" in text and "Heparin" in text
    for later in ("Amlodipine", "Atorvastatin", "Enoxaparin", "Patiromer", "catheter"):
        assert later not in text, (later, text)


def test_admitted_ed_workup_ja_leaves_home_medications_out_of_the_medication_line() -> None:
    text, _ = build_ed_workup(TemplateNarrativeGenerator(), _ctx("inpatient", "ja", _ORDERS))
    assert "投薬: " in text, text
    meds = text.split("投薬: ", 1)[1]
    assert "アスピリン" in meds
    for home in ("アムロジピン", "アトルバスタチン", "エノキサパリン"):
        assert home not in meds, (home, text)
    assert "カテーテル" not in text


def test_ed_visit_sent_home_keeps_every_ed_order() -> None:
    """The ED-only visit's orders carry no admission order set; all are listed."""
    orders = [
        _order("Ibuprofen", datetime(2025, 11, 20, 18, 40)),
        _order("Ondansetron", datetime(2025, 11, 20, 18, 45)),
    ]
    text, _ = build_ed_workup(TemplateNarrativeGenerator(), _ctx("emergency", "en", orders))
    assert "Ibuprofen" in text and "Ondansetron" in text


def test_admitted_arrival_vitals_omitted_when_every_reading_is_on_the_ward() -> None:
    ward = [_vital(datetime(2025, 11, 21, 0, 2), 83)]
    text, facts = build_ed_physical_exam(TemplateNarrativeGenerator(), _ctx("inpatient", "en", [], ward))
    assert "HR 83" not in text, text
    assert text == "Examination on arrival: not recorded"
    assert "ctx.vitals[0]" not in facts


def test_admitted_arrival_exam_not_recorded_ja() -> None:
    ward = [_vital(datetime(2025, 11, 21, 0, 2), 83)]
    text, _ = build_ed_physical_exam(TemplateNarrativeGenerator(), _ctx("inpatient", "ja", [], ward))
    assert text == "来院時の身体所見: 記載なし"


def test_admitted_arrival_vitals_use_a_reading_from_the_ed_period() -> None:
    vitals = [_vital(datetime(2025, 11, 20, 15, 10), 121), _vital(datetime(2025, 11, 21, 0, 2), 83)]
    text, _ = build_ed_physical_exam(TemplateNarrativeGenerator(), _ctx("inpatient", "en", [], vitals))
    assert "HR 121" in text and "HR 83" not in text, text


def test_admitted_arrival_vitals_ed_reading_is_picked_even_when_listed_after_ward_readings() -> None:
    vitals = [_vital(datetime(2025, 11, 21, 0, 2), 83), _vital(datetime(2025, 11, 20, 15, 10), 121)]
    text, _ = build_ed_physical_exam(TemplateNarrativeGenerator(), _ctx("inpatient", "en", [], vitals))
    assert "HR 121" in text and "HR 83" not in text, text


def test_ed_visit_sent_home_keeps_its_arrival_vitals() -> None:
    vitals = [_vital(datetime(2025, 11, 20, 18, 40), 95)]
    text, _ = build_ed_physical_exam(TemplateNarrativeGenerator(), _ctx("emergency", "en", [], vitals))
    assert "On arrival" in text and "HR 95" in text, text
