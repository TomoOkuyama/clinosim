"""The death certificate states a causal sequence (Issue #3255).

The certificate filled the immediate and the underlying cause from the same
discharge diagnosis, printed the underlying code cut to three characters,
reported R65.x (severe sepsis / septic shock) as the underlying cause, listed
the first five chronic conditions as contributing (cataract included) and, in
Japanese, closed the contributing sentence twice.

Now the immediate cause is the latest in-hospital complication that can cause
death (``death_cause_chain.yaml``), the underlying cause is the disease that
started the sequence with its full code (R65.x points to the admission
infection), contributing conditions are filtered by relevance, and the
closing sentence appears once.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from clinosim.codes.icd10 import icd10_display
from clinosim.locale.loader import load_narrative_complications
from clinosim.modules.document.narrative.renderers._shared_helpers import chronic_condition_code
from clinosim.modules.document.narrative.renderers.section_builders.mortality import (
    build_dc_contributing_conditions,
    build_dc_duration_of_immediate_cause,
    build_dc_immediate_cause,
    build_dc_underlying_cause,
    build_dds_cause_of_death,
)
from clinosim.modules.document.reference_data_loaders import load_death_cause_chain
from clinosim.types.document import DocumentType, NarrativeContext
from clinosim.types.patient import ChronicCondition, PatientProfile

_ADMIT = datetime(2026, 2, 25, 10, 0)
_DEATH = datetime(2026, 3, 7, 12, 0)


def _comp(name: str, day: int) -> dict:
    return {
        "name": name,
        "onset_day": day,
        "onset_datetime": (datetime(2026, 2, 25, 12, 0) + timedelta(days=day)).isoformat(),
        "source": "daily_loop",
    }


def _ctx(
    lang: str,
    *,
    adm: str,
    dis: str,
    comps: list[dict] | None = None,
    chronic: list[str] | None = None,
) -> NarrativeContext:
    patient = PatientProfile(patient_id="pt-3255")
    patient.sex = "M"
    patient.chronic_conditions = [ChronicCondition(code=c) for c in chronic or []]
    enc = SimpleNamespace(
        encounter_id="enc-3255",
        encounter_type=SimpleNamespace(value="inpatient"),
        admission_datetime=_ADMIT,
        discharge_datetime=_DEATH,
        discharge_disposition="exp",
    )
    comps = comps or []
    return NarrativeContext(
        patient=patient,
        encounter=enc,
        encounter_type=enc.encounter_type,
        disease_protocol=None,
        encounter_protocol=None,
        clinical_course_archetype="deterioration",
        severity="severe",
        day_index=10,
        los_days=10,
        vitals=[],
        lab_results=[],
        medications=[],
        diagnoses=[
            {
                "admission_diagnosis_code": adm,
                "admission_diagnosis_system": "icd-10-cm",
                "discharge_diagnosis_code": dis,
                "discharge_diagnosis_system": "icd-10-cm",
            }
        ],
        procedures=[],
        allergies=[],
        document_type=DocumentType.DEATH_CERTIFICATE,
        target_lang=lang,
        locale="jp" if lang == "ja" else "us",
        complications_occurred=[c["name"] for c in comps],
        complications_events=comps,
    )


def test_latest_terminal_complication_is_the_immediate_cause_and_the_disease_underlies_it() -> None:
    ctx = _ctx(
        "en", adm="I21.9", dis="I21.9", comps=[_comp("mechanical_complication", 5), _comp("acute_heart_failure", 6)]
    )
    immediate, _ = build_dc_immediate_cause(None, ctx)
    underlying, _ = build_dc_underlying_cause(None, ctx)
    assert immediate == "Immediate cause of death: Heart failure, unspecified (I50.9)."
    assert underlying == "Underlying cause of death: Acute myocardial infarction, unspecified (I21.9)."


def test_underlying_code_is_the_full_code() -> None:
    underlying, _ = build_dc_underlying_cause(None, _ctx("ja", adm="I63.9", dis="I63.9"))
    assert "（I63.9）" in underlying
    assert "（I63）" not in underlying


def test_septic_shock_points_to_the_infection_as_underlying_cause() -> None:
    ctx = _ctx("en", adm="A41.9", dis="R65.21")
    immediate, _ = build_dc_immediate_cause(None, ctx)
    underlying, _ = build_dc_underlying_cause(None, ctx)
    assert immediate == "Immediate cause of death: Severe sepsis with septic shock (R65.21)."
    assert underlying == "Underlying cause of death: Sepsis, unspecified organism (A41.9)."


def test_organ_failure_on_septic_shock_states_the_shock_between_them() -> None:
    ctx = _ctx(
        "en",
        adm="A41.9",
        dis="R65.21",
        comps=[_comp("disseminated_intravascular_coagulation", 1), _comp("acute_kidney_injury", 2)],
    )
    immediate, _ = build_dc_immediate_cause(None, ctx)
    underlying, _ = build_dc_underlying_cause(None, ctx)
    assert immediate == (
        "Immediate cause of death: Acute kidney failure, unspecified (N17.9). "
        "Due to (or as a consequence of): Severe sepsis with septic shock (R65.21)."
    )
    assert "(A41.9)" in underlying and "R65" not in underlying


def test_japanese_certificate_uses_the_jp_codes() -> None:
    ctx = _ctx("ja", adm="A41.9", dis="R65.21", comps=[_comp("disseminated_intravascular_coagulation", 1)])
    immediate, _ = build_dc_immediate_cause(None, ctx)
    underlying, _ = build_dc_underlying_cause(None, ctx)
    assert immediate.startswith("直接死因: 播種性血管内凝固症候群")
    assert "（D65）" in immediate and "（ア）の原因: " in immediate and "（R65.1）" in immediate
    assert underlying == "原死因: 敗血症，詳細不明（A41.9）。"


def test_complication_without_a_code_is_named_without_one() -> None:
    ctx = _ctx("ja", adm="I21.9", dis="I21.9", comps=[_comp("mechanical_complication", 5)])
    immediate, _ = build_dc_immediate_cause(None, ctx)
    assert immediate == "直接死因: 心筋梗塞の機械的合併症。"


def test_non_terminal_complication_is_not_a_cause_line() -> None:
    ctx = _ctx("en", adm="I63.9", dis="I63.9", comps=[_comp("delirium", 3)])
    immediate, _ = build_dc_immediate_cause(None, ctx)
    assert "(I63.9)" in immediate


def test_complication_after_death_is_ignored() -> None:
    late = {
        "name": "acute_heart_failure",
        "onset_day": 20,
        "onset_datetime": "2026-03-20T12:00:00",
        "source": "daily_loop",
    }
    ctx = _ctx("en", adm="I21.9", dis="I21.9", comps=[late])
    immediate, _ = build_dc_immediate_cause(None, ctx)
    assert "(I21.9)" in immediate


def test_death_summary_cause_matches_the_certificate_immediate_cause() -> None:
    ctx = _ctx("en", adm="I21.9", dis="I21.9", comps=[_comp("cardiogenic_shock", 4)])
    cause, _ = build_dds_cause_of_death(None, ctx)
    assert cause == "Cause of death: Cardiogenic shock (R57.0)."


def test_duration_runs_from_the_onset_of_the_immediate_cause() -> None:
    ctx = _ctx("en", adm="I21.9", dis="I21.9", comps=[_comp("acute_heart_failure", 6)])
    text, _ = build_dc_duration_of_immediate_cause(None, ctx)
    assert "4 days" in text and "Heart failure, unspecified" in text
    assert "admission" not in text
    text_ja, _ = build_dc_duration_of_immediate_cause(
        None, _ctx("ja", adm="I21.9", dis="I21.9", comps=[_comp("acute_heart_failure", 6)])
    )
    assert "約4日" in text_ja and "入院より" not in text_ja


@pytest.mark.parametrize("lang", ["en", "ja"])
def test_contributing_conditions_leave_out_unrelated_ones_and_close_once(lang: str) -> None:
    ctx = _ctx(
        lang,
        adm="I63.9",
        dis="I63.9",
        comps=[_comp("delirium", 3)],
        chronic=["I10", "E11.9", "H26.9", "M17", "K21"],
    )
    text, _ = build_dc_contributing_conditions(None, ctx)
    assert "H26" not in text and "M17" not in text and "K21" not in text
    assert "(I10)" in text or "（I10）" in text
    if lang == "ja":
        assert text.count("臨床経過に影響") == 1, text
        assert "せん妄" in text
    else:
        assert text.count("contributed") == 1, text
        assert "delirium" in text


def test_contributing_conditions_leave_out_the_cause_lines() -> None:
    ctx = _ctx(
        "en",
        adm="I21.9",
        dis="I21.9",
        comps=[_comp("acute_heart_failure", 6), _comp("delirium", 7)],
        chronic=["I50", "I10"],
    )
    text, _ = build_dc_contributing_conditions(None, ctx)
    assert "I50" not in text and "acute heart failure" not in text
    assert "(I10)" in text


def test_only_unrelated_chronic_conditions_read_as_none() -> None:
    ctx = _ctx("en", adm="I63.9", dis="I63.9", chronic=["H26.9", "M17"])
    text, _ = build_dc_contributing_conditions(None, ctx)
    assert text == "Contributing conditions: none documented."


def test_every_chain_complication_has_a_label_and_a_resolvable_code() -> None:
    chain = load_death_cause_chain()
    labels = load_narrative_complications()
    for name, code in chain.immediate_cause_complications.items():
        assert name in labels, name
        if code:
            for country in ("US", "JP"):
                emitted = chronic_condition_code(code, country)
                assert icd10_display(emitted, country, "en"), (name, country, emitted)
                assert icd10_display(emitted, country, "ja"), (name, country, emitted)
