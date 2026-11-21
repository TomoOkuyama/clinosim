"""The death summary describes one terminal course (Issue #3470).

The terminal-course sentence was chosen from the last vitals ("respiratory
failure") and named the discharge diagnosis, while the certificate's chain was
"acute kidney failure due to severe sepsis due to sepsis"; a full-code death
without a CPR record read "cardiopulmonary arrest during treatment" although
the record holds no code event; the family-communication section asserted the
family was at the bedside; the AKI duration ran from the logged complication
instead of the first abnormal creatinine.

Now the mechanism and the causes come from the certificate's cause chain, no
arrest is asserted without a CPR record, no bedside presence is asserted, and
the AKI onset is the first creatinine that meets the KDIGO criterion.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from clinosim.modules.document.narrative.renderers.section_builders import mortality
from clinosim.modules.document.narrative.renderers.section_builders.mortality import (
    _dc_cause_chain,
    build_dc_duration_of_immediate_cause,
    build_dc_immediate_cause,
    build_dds_cause_of_death,
    build_dds_circumstances_of_death,
    build_dds_family_communication,
    build_dds_terminal_course,
)
from clinosim.modules.document.reference_data_loaders import load_death_cause_chain
from clinosim.types.document import DocumentType, NarrativeContext
from clinosim.types.patient import PatientProfile

_ADMIT = datetime(2026, 2, 25, 10, 0)
_DEATH = datetime(2026, 3, 1, 12, 0)
_FULL_CODE = "304252001"
_DNR = "304253006"


def _comp(name: str, at: datetime) -> dict:
    return {"name": name, "onset_datetime": at.isoformat(), "source": "daily_loop"}


def _cr(at: datetime, value: float, unit: str = "mg/dL") -> dict:
    return {"lab_name": "Creatinine", "value": value, "unit": unit, "result_datetime": at.isoformat()}


def _hypoxic_vitals() -> list[dict]:
    return [
        {
            "timestamp": (_DEATH - timedelta(hours=2)).isoformat(),
            "heart_rate": 120,
            "systolic_bp": 82,
            "diastolic_bp": 50,
            "spo2": 83.0,
            "respiratory_rate": 29,
        }
    ]


def _ctx(
    lang: str = "en",
    *,
    adm: str = "A41.9",
    dis: str = "R65.20",
    comps: list[dict] | None = None,
    labs: list[dict] | None = None,
    prior_labs: list[dict] | None = None,
    code_status: str = _FULL_CODE,
    procs: list[dict] | None = None,
    icu: bool = False,
    icu_day: int = -1,
    doc: DocumentType = DocumentType.DEATH_DISCHARGE_SUMMARY,
) -> NarrativeContext:
    patient = PatientProfile(patient_id="pt-3470")
    patient.sex = "M"
    enc = SimpleNamespace(
        encounter_id="enc-3470",
        encounter_type=SimpleNamespace(value="inpatient"),
        admission_datetime=_ADMIT,
        discharge_datetime=_DEATH,
        discharge_disposition="exp",
    )
    comps = comps if comps is not None else [_comp("aki", _ADMIT + timedelta(days=3, hours=12))]
    return NarrativeContext(
        patient=patient,
        encounter=enc,
        encounter_type=enc.encounter_type,
        disease_protocol=None,
        encounter_protocol=None,
        clinical_course_archetype="deterioration",
        severity="severe",
        day_index=4,
        los_days=4,
        vitals=_hypoxic_vitals(),
        lab_results=labs or [],
        prior_lab_results=prior_labs or [],
        medications=[],
        diagnoses=[
            {
                "admission_diagnosis_code": adm,
                "admission_diagnosis_system": "icd-10-cm",
                "discharge_diagnosis_code": dis,
                "discharge_diagnosis_system": "icd-10-cm",
            }
        ],
        procedures=procs or [],
        allergies=[],
        document_type=doc,
        target_lang=lang,
        locale="jp" if lang == "ja" else "us",
        code_status=code_status,
        icu_transferred=icu,
        icu_transferred_day=icu_day,
        complications_occurred=[c["name"] for c in comps],
        complications_events=comps,
    )


def test_sepsis_aki_terminal_course_names_the_certificate_chain_not_the_vitals_mechanism() -> None:
    ctx = _ctx()
    course, _ = build_dds_terminal_course(None, ctx)
    assert "renal deterioration" in course
    assert "respiratory" not in course
    assert "(N17.9), due to " in course and "(R65.20)" in course
    assert "(A41.9)" in course
    # The vitals are still quoted as observations.
    assert "SpO2 83%" in course


def test_terminal_course_ja_names_the_chain() -> None:
    course, _ = build_dds_terminal_course(None, _ctx("ja"))
    assert "腎機能が悪化し" in course
    assert "呼吸不全" not in course
    assert "N17" in course and "A41" in course


def test_mechanism_noun_comes_from_the_one_chain_the_certificate_uses() -> None:
    ctx = _ctx()
    chain = _dc_cause_chain(ctx)
    assert chain is not None
    immediate = chain.immediate
    assert immediate.display in build_dds_terminal_course(None, ctx)[0]
    assert immediate.display in build_dds_cause_of_death(None, ctx)[0]
    assert immediate.display in build_dc_immediate_cause(None, ctx)[0]


@pytest.mark.parametrize(
    ("code", "phrase"),
    [
        ("N17.9", "renal"),
        ("J96.00", "respiratory"),
        ("J80", "respiratory"),
        ("A41.9", "septic"),
        ("R65.21", "septic"),
        ("R57.0", "cardiac"),
        ("I50.9", "cardiac"),
        ("I26.99", "pulmonary_embolism"),
        ("G93.5", "neurological"),
        ("J18.9", "pneumonia"),
        ("C34.90", None),
    ],
)
def test_terminal_mechanism_table(code: str, phrase: str | None) -> None:
    assert load_death_cause_chain().terminal_phrase(code) == phrase


def test_every_terminal_mechanism_has_a_phrase_in_both_languages() -> None:
    from clinosim.locale.i18n import t

    for entry in load_death_cause_chain().terminal_mechanisms:
        for lang in ("en", "ja"):
            text = t(f"dds_terminal_course.phrase_{entry.phrase}", lang)
            assert text and "phrase_" not in text


def test_unmapped_immediate_cause_follows_the_disease_pattern_not_the_vitals() -> None:
    ctx = _ctx(adm="C34.90", dis="C34.90", comps=[])
    course, _ = build_dds_terminal_course(None, ctx)
    assert "respiratory failure" not in course


@pytest.mark.parametrize("lang", ["en", "ja"])
def test_full_code_without_cpr_record_asserts_no_arrest(lang: str) -> None:
    text, _ = build_dds_circumstances_of_death(None, _ctx(lang))
    assert "arrest" not in text and "心肺停止" not in text
    assert "resuscitation was performed" not in text and "心肺蘇生術を施行" not in text
    assert ("No resuscitation measures are documented" if lang == "en" else "蘇生処置の記録はない") in text
    assert ("death was confirmed" if lang == "en" else "死亡確認") in text


def test_unknown_code_status_only_confirms_death() -> None:
    text, _ = build_dds_circumstances_of_death(None, _ctx(code_status=""))
    assert text == "On the ward, death was confirmed."


def test_recorded_cpr_is_still_described() -> None:
    proc = {
        "procedure_type": "cpr",
        "procedure_code": "92950",
        "procedure_code_us": "92950",
        "start_datetime": (_DEATH - timedelta(minutes=30)).isoformat(),
    }
    text, _ = build_dds_circumstances_of_death(None, _ctx(procs=[proc]))
    assert "cardiopulmonary resuscitation was performed" in text


def test_dnar_death_is_unchanged() -> None:
    text, _ = build_dds_circumstances_of_death(None, _ctx(code_status=_DNR))
    assert "palliative" in text and "was not attempted" in text


@pytest.mark.parametrize("lang", ["en", "ja"])
def test_family_communication_does_not_assert_bedside_presence(lang: str) -> None:
    for los in (0, 3, 12):
        ctx = _ctx(lang)
        ctx.los_days = los
        text, _ = build_dds_family_communication(None, ctx)
        assert "bedside" not in text and "立会" not in text
        assert text.endswith("." if lang == "en" else "。")


def test_icu_place_requires_an_icu_record() -> None:
    assert "On the ward" in build_dds_circumstances_of_death(None, _ctx(icu=True, icu_day=-1))[0]
    assert "In the intensive care unit" in build_dds_circumstances_of_death(None, _ctx(icu=True, icu_day=2))[0]
    assert "On the ward" in build_dds_circumstances_of_death(None, _ctx(icu=False, icu_day=2))[0]


def _duration(ctx: NarrativeContext) -> str:
    ctx.document_type = DocumentType.DEATH_CERTIFICATE
    return build_dc_duration_of_immediate_cause(None, ctx)[0]


def test_aki_duration_runs_from_the_first_abnormal_creatinine() -> None:
    labs = [
        _cr(_ADMIT + timedelta(hours=2), 0.9),
        _cr(_ADMIT + timedelta(days=1), 1.5),  # >= 0.3 mg/dL and >= 1.5x within 48 h
        _cr(_ADMIT + timedelta(days=3, hours=12), 3.0),
    ]
    text = _duration(_ctx(labs=labs))
    # onset on hospital day 2 (1 d 2 h after 10:00 admission +2 h draw), not the day-4 event
    assert "3 days" in text or "4 days" in text
    assert "12 hour" not in text


def test_aki_present_on_arrival_against_the_baseline_dates_to_admission() -> None:
    labs = [_cr(_ADMIT + timedelta(hours=1), 1.82), _cr(_ADMIT + timedelta(days=3), 2.4)]
    prior = [_cr(_ADMIT - timedelta(days=200), 0.87)]
    text = _duration(_ctx(labs=labs, prior_labs=prior))
    assert "4 days" in text and "12 hour" not in text


def test_aki_without_an_earlier_abnormal_creatinine_keeps_the_event_onset() -> None:
    labs = [_cr(_ADMIT + timedelta(hours=1), 1.0), _cr(_ADMIT + timedelta(days=3, hours=20), 1.1)]
    text = _duration(_ctx(labs=labs))
    assert "14 h" in text  # unchanged: from the logged event (day 4 12:00 to death)


def test_first_abnormal_onset_helper_is_the_only_onset_override() -> None:
    event = _ADMIT + timedelta(days=3)
    ctx = _ctx(labs=[_cr(_ADMIT + timedelta(hours=1), 1.0)], comps=[])
    assert mortality._first_abnormal_onset(ctx, event) == event
