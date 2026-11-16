"""The death summary states where and how the patient died (Issue #3256).

The circumstances of death were one fixed sentence ("On the ward ... palliative
bedside care" / 「病棟にて…看取り」) for every death, whether the patient died in
the ICU, had a do-not-resuscitate order or was full code; the code status was
never stated; the treatment course gave only counts ("4 procedure(s) were
performed", "1 additional working diagnosis/es") and the death certificate
read "approximately 2 week(s) (11 d)".

Now the circumstances follow the record: the place (ICU after an ICU
transfer), the code status, the life support running in the last hours and a
recorded CPR. Palliative / 看取り wording is used only for a DNR death without
life support, and then the treatment course does not say treatment was
continued. Procedures, drugs and new diagnoses are named, and durations under
four weeks are written in days.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from clinosim.modules.document.narrative.renderers.section_builders.mortality import (
    build_dc_duration_of_immediate_cause,
    build_dds_circumstances_of_death,
    build_dds_treatment_course,
)
from clinosim.types.document import DocumentType, NarrativeContext
from clinosim.types.patient import PatientProfile

_ADMIT = datetime(2026, 2, 24, 20, 0)
_DEATH = datetime(2026, 3, 7, 6, 0)  # hospital day 11
_FULL_CODE = "304252001"
_DNR = "304253006"


def _proc(ptype: str, us: str, jp: str) -> dict:
    return {
        "procedure_type": ptype,
        "procedure_code": us,
        "procedure_code_us": us,
        "procedure_code_jp": jp,
        "start_datetime": (_ADMIT + timedelta(hours=2)).isoformat(),
    }


def _mar(drug_id: str, name: str, at: datetime, status: str = "given") -> dict:
    return {"drug_id": drug_id, "drug_name": name, "actual_datetime": at.isoformat(), "status": status}


def _vitals(at: datetime, device: str = "") -> dict:
    return {
        "timestamp": at.isoformat(),
        "heart_rate": 120,
        "systolic_bp": 82,
        "diastolic_bp": 50,
        "spo2": 88.0,
        "respiratory_rate": 28,
        "on_supplemental_oxygen": bool(device),
        "oxygen_delivery_device": device,
    }


def _ctx(
    lang: str,
    *,
    code_status: str = "",
    icu: bool = False,
    meds: list[dict] | None = None,
    vitals: list[dict] | None = None,
    procs: list[dict] | None = None,
    working: list[dict] | None = None,
    los: int = 11,
    doc: DocumentType = DocumentType.DEATH_DISCHARGE_SUMMARY,
) -> NarrativeContext:
    patient = PatientProfile(patient_id="pt-3256")
    patient.sex = "M"
    enc = SimpleNamespace(
        encounter_id="enc-3256",
        encounter_type=SimpleNamespace(value="inpatient"),
        admission_datetime=_ADMIT,
        discharge_datetime=_DEATH,
        discharge_disposition="exp",
    )
    return NarrativeContext(
        patient=patient,
        encounter=enc,
        encounter_type=enc.encounter_type,
        disease_protocol=None,
        encounter_protocol=None,
        clinical_course_archetype="deterioration",
        severity="severe",
        day_index=los,
        los_days=los,
        vitals=vitals or [],
        lab_results=[],
        medications=meds or [],
        diagnoses=[
            {
                "admission_diagnosis_code": "I21.9",
                "admission_diagnosis_system": "icd-10-cm",
                "discharge_diagnosis_code": "I21.9",
                "discharge_diagnosis_system": "icd-10-cm",
                "working_diagnoses": working or [],
            }
        ],
        procedures=procs or [],
        allergies=[],
        document_type=doc,
        target_lang=lang,
        locale="jp" if lang == "ja" else "us",
        working_diagnoses=working or [],
        code_status=code_status,
        icu_transferred=icu,
        icu_transferred_day=5 if icu else -1,
    )


def _circumstances(ctx: NarrativeContext) -> str:
    return build_dds_circumstances_of_death(None, ctx)[0]


def _course(ctx: NarrativeContext) -> str:
    return build_dds_treatment_course(None, ctx)[0]


_NOREPI_LAST_HOURS = [_mar("norepinephrine", "Norepinephrine 0.1 mcg/kg/min IV", _DEATH - timedelta(hours=3))]


@pytest.mark.parametrize(("lang", "place"), [("en", "In the intensive care unit"), ("ja", "集中治療室")])
def test_icu_death_is_placed_in_the_icu(lang: str, place: str) -> None:
    text = _circumstances(_ctx(lang, code_status=_DNR, icu=True, meds=_NOREPI_LAST_HOURS))
    assert place in text
    assert "ward" not in text and "病棟" not in text


@pytest.mark.parametrize(("lang", "place"), [("en", "On the ward"), ("ja", "病棟にて")])
def test_ward_death_is_placed_on_the_ward(lang: str, place: str) -> None:
    assert place in _circumstances(_ctx(lang, code_status=_DNR))


@pytest.mark.parametrize("lang", ["en", "ja"])
def test_full_code_death_has_no_palliative_wording_and_states_the_code_status(lang: str) -> None:
    ctx = _ctx(lang, code_status=_FULL_CODE, icu=True, meds=_NOREPI_LAST_HOURS)
    text = _circumstances(ctx)
    assert "palliative" not in text and "看取り" not in text
    assert ("For resuscitation" if lang == "en" else "蘇生処置を行う") in text


@pytest.mark.parametrize("lang", ["en", "ja"])
def test_dnr_death_states_the_code_status(lang: str) -> None:
    for icu, meds in ((False, []), (True, _NOREPI_LAST_HOURS)):
        text = _circumstances(_ctx(lang, code_status=_DNR, icu=icu, meds=meds))
        assert ("Not for resuscitation" if lang == "en" else "DNAR") in text


def test_dnr_without_life_support_is_a_palliative_death_and_the_course_is_not_continued_treatment() -> None:
    ctx = _ctx("en", code_status=_DNR)
    assert "palliative" in _circumstances(ctx)
    assert "continued" not in _course(ctx)
    ctx_ja = _ctx("ja", code_status=_DNR)
    assert "看取り" in _circumstances(ctx_ja)
    assert "継続" not in _course(ctx_ja)


@pytest.mark.parametrize("lang", ["en", "ja"])
def test_dnr_on_vasopressors_names_the_support_and_no_palliative_wording(lang: str) -> None:
    ctx = _ctx(lang, code_status=_DNR, icu=True, meds=_NOREPI_LAST_HOURS)
    text = _circumstances(ctx)
    assert "palliative" not in text and "看取り" not in text
    assert ("vasopressor" if lang == "en" else "昇圧薬") in text
    # CPR withheld under the order, not performed.
    assert "resuscitation was performed" not in text


def test_vasopressor_given_before_the_last_day_is_not_life_support_at_death() -> None:
    early = [_mar("norepinephrine", "Norepinephrine IV", _DEATH - timedelta(days=3))]
    text = _circumstances(_ctx("en", code_status=_DNR, meds=early))
    assert "vasopressor" not in text
    held = [_mar("norepinephrine", "Norepinephrine IV", _DEATH - timedelta(hours=2), status="held")]
    assert "vasopressor" not in _circumstances(_ctx("en", code_status=_DNR, meds=held))


@pytest.mark.parametrize(("lang", "word"), [("en", "mechanical ventilation"), ("ja", "人工呼吸")])
def test_ventilator_in_the_last_vitals_is_life_support(lang: str, word: str) -> None:
    vitals = [_vitals(_DEATH - timedelta(hours=2), device="ventilator")]
    text = _circumstances(_ctx(lang, code_status=_FULL_CODE, icu=True, vitals=vitals))
    assert word in text


@pytest.mark.parametrize("lang", ["en", "ja"])
def test_unknown_code_status_is_neither_palliative_nor_resuscitation(lang: str) -> None:
    text = _circumstances(_ctx(lang))
    assert "palliative" not in text and "看取り" not in text
    assert "resuscitation was performed" not in text


@pytest.mark.parametrize(
    ("lang", "names"),
    [
        ("en", ["Urinary catheter insertion", "Arterial line insertion", "Percutaneous coronary intervention"]),
        ("ja", ["尿道カテーテル挿入", "動脈ライン挿入", "経皮的冠動脈形成術"]),
    ],
)
def test_treatment_course_names_the_procedures(lang: str, names: list[str]) -> None:
    procs = [
        _proc("urinary_catheter", "51702", "J063"),
        _proc("arterial_line", "36620", "D225"),
        _proc("coronary_pci", "92920", "K546"),
    ]
    text = _course(_ctx(lang, procs=procs))
    for name in names:
        assert name in text
    assert "procedure(s)" not in text and "処置3件" not in text


@pytest.mark.parametrize(
    ("lang", "name", "day"),
    [("en", "Acute kidney failure", "hospital day 11"), ("ja", "急性腎不全", "入院11日目")],
)
def test_treatment_course_names_the_new_diagnoses_with_their_day(lang: str, name: str, day: str) -> None:
    # onset_day is 0-indexed from admission; the admission day is hospital day 1.
    working = [{"disease_id": "N17.9", "onset_day": 10, "source": "lab_derived_aki_kdigo_stage3"}]
    text = _course(_ctx(lang, working=working))
    assert f"{name}" in text and day in text
    assert "diagnosis/es" not in text and "1件の" not in text


@pytest.mark.parametrize(
    ("lang", "expected"),
    [("en", "intensive care unit on hospital day 6"), ("ja", "入院6日目に集中治療室（ICU）に入室")],
)
def test_treatment_course_states_the_icu_transfer_day(lang: str, expected: str) -> None:
    assert expected in _course(_ctx(lang, icu=True))


@pytest.mark.parametrize(("lang", "name"), [("en", "Norepinephrine"), ("ja", "ノルアドレナリン")])
def test_treatment_course_names_the_drugs_not_the_administration_count(lang: str, name: str) -> None:
    meds = [_mar("norepinephrine", "Norepinephrine IV", _ADMIT + timedelta(days=d)) for d in range(5)]
    text = _course(_ctx(lang, meds=meds))
    assert name in text
    assert "medication order(s)" not in text and "薬剤5件" not in text


@pytest.mark.parametrize(("lang", "expected"), [("en", "11 days"), ("ja", "約11日")])
def test_eleven_day_duration_reads_in_days(lang: str, expected: str) -> None:
    text, _ = build_dc_duration_of_immediate_cause(None, _ctx(lang, doc=DocumentType.DEATH_CERTIFICATE))
    assert expected in text
    assert not re.search(r"week|週間", text)


HOME = ("atorvastatin", "amlodipine", "sertraline")


def test_life_support_and_acute_drugs_are_named_before_home_medications() -> None:
    # Home medications first given on admission, acute drugs later.
    meds = [_mar(drug, drug, _ADMIT + timedelta(hours=1 + i)) for i, drug in enumerate(HOME)]
    meds += [_mar("heparin", "Heparin IV", _ADMIT + timedelta(days=1))]
    meds += [_mar("norepinephrine", "Norepinephrine IV", _ADMIT + timedelta(days=5))]
    text = _course(_ctx("en", meds=meds))
    named = text.split("Drugs given included ")[1].split(".")[0].split(", ")
    assert named[:2] == ["Norepinephrine", "Heparin"]
    assert named[2:] == ["Atorvastatin", "Amlodipine", "Sertraline"]
