"""Nursing discharge summary at the AKI / fever deferral cap (Issue #3281
follow-up): "discharge criteria met" is stated only when the discharge gate
was met; a stay discharged home at the deferral cap with AKI still not
recovering says the creatinine recheck is arranged, a fever-only one says the
fever had not resolved."""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from clinosim.modules.document.narrative.renderers.section_builders.nursing import build_nursing_admission_status
from clinosim.types.document import DocumentType, NarrativeContext
from clinosim.types.patient import PatientProfile

pytestmark = pytest.mark.unit

_T0 = datetime(2025, 12, 4, 10, 0)


def _cr(hours: int, value: float) -> dict[str, object]:
    return {"result_datetime": _T0 + timedelta(hours=hours), "lab_name": "Creatinine", "value": value}


def _temp(hours: int, c: float) -> dict[str, object]:
    return {"timestamp": _T0 + timedelta(hours=hours), "temperature_celsius": c}


def _ctx(lang: str, labs: list[dict[str, object]], vitals: list[dict[str, object]]) -> NarrativeContext:
    encounter = SimpleNamespace(
        encounter_id="enc-3281",
        encounter_type=SimpleNamespace(value="inpatient"),
        admission_datetime=_T0,
        discharge_datetime=_T0 + timedelta(days=6),
        discharge_disposition="home",
        chief_complaint="fever",
    )
    return NarrativeContext(
        patient=PatientProfile(patient_id="pt-3281"),
        encounter=encounter,
        encounter_type=SimpleNamespace(value="inpatient"),
        disease_protocol=SimpleNamespace(disease_id="sepsis"),
        encounter_protocol=None,
        clinical_course_archetype="",
        severity="severe",
        day_index=5,
        los_days=6,
        vitals=vitals,
        lab_results=labs,
        medications=[],
        diagnoses=[],
        procedures=[],
        allergies=[],
        document_type=DocumentType.NURSING_DISCHARGE_SUMMARY,
        target_lang=lang,
        locale="jp" if lang == "ja" else "us",
    )


_MET = {"en": "Discharge criteria met", "ja": "退院基準を満たし退院となった"}
_AKI_NOT_RECOVERED = [_cr(0, 0.8), _cr(48, 1.6), _cr(120, 1.7)]
_AKI_RECOVERING = [_cr(0, 0.8), _cr(48, 1.6), _cr(120, 0.9)]


def _text(ctx: NarrativeContext) -> tuple[str, list[str]]:
    return build_nursing_admission_status(None, ctx)  # type: ignore[arg-type]


@pytest.mark.parametrize(("lang", "expected"), [("en", "creatinine recheck"), ("ja", "クレアチニンの再検査")])
def test_aki_not_recovering_at_cap_states_recheck(lang: str, expected: str) -> None:
    text, facts = _text(_ctx(lang, _AKI_NOT_RECOVERED, []))
    assert _MET[lang] not in text
    assert expected in text
    assert "ctx.lab_results" in facts


@pytest.mark.parametrize("lang", ["en", "ja"])
def test_recovering_aki_states_criteria_met(lang: str) -> None:
    text, _ = _text(_ctx(lang, _AKI_RECOVERING, []))
    assert _MET[lang] in text


@pytest.mark.parametrize(("lang", "expected"), [("en", "fever"), ("ja", "発熱")])
def test_fever_at_cap_does_not_state_criteria_met(lang: str, expected: str) -> None:
    text, facts = _text(_ctx(lang, [_cr(0, 0.8)], [_temp(100, 38.6), _temp(120, 38.4)]))
    assert _MET[lang] not in text
    assert expected in text
    assert "ctx.vitals" in facts


@pytest.mark.parametrize("lang", ["en", "ja"])
def test_no_findings_states_criteria_met(lang: str) -> None:
    text, _ = _text(_ctx(lang, [_cr(0, 0.8), _cr(120, 0.8)], [_temp(120, 36.8)]))
    assert _MET[lang] in text
