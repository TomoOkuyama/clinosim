"""A respiratory admission's progress-note Subjective states how breathing is
going, and a bare unsourced "pain" line is not its only content (Issue #3454)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from clinosim.modules.document.narrative._progress_symptoms import progress_symptom_rules
from clinosim.modules.document.narrative.renderers._composers import compose_progress_subjective_from_state
from tests.unit.modules.document.narrative.test_progress_exam_course_3235_3247 import _ctx, _v

pytestmark = pytest.mark.unit


def _subj(
    vitals: list[dict],
    lang: str,
    disease: str = "asthma_exacerbation",
    cc_ja: str = "重度喘鳴・呼吸困難",
    cc_en: str = "Wheezing, dyspnea",
) -> str:
    ctx = _ctx(vitals, day=2, lang=lang)
    ctx.disease_protocol = SimpleNamespace(disease_id=disease)
    ctx.encounter = {**ctx.encounter, "chief_complaint_ja": cc_ja, "chief_complaint": cc_en}
    return compose_progress_subjective_from_state(ctx)


_IMPROVING = [_v(1, 9, respiratory_rate=28, spo2=89), _v(2, 8, respiratory_rate=20, spo2=96, pain_score=4)]


def test_group_diseases_exist() -> None:
    assert "asthma_exacerbation" in progress_symptom_rules().respiratory.diseases


def test_improving_dyspnea_is_stated_in_both_languages() -> None:
    assert "呼吸困難感は前日より軽減" in _subj(_IMPROVING, "ja")
    assert "Dyspnea improved since yesterday" in _subj(_IMPROVING, "en")


def test_persisting_and_worsening_follow_the_meaningful_change() -> None:
    persisting = [_v(1, 9, respiratory_rate=26, spo2=90), _v(2, 8, respiratory_rate=25, spo2=91)]
    worsening = [_v(1, 9, respiratory_rate=24, spo2=92), _v(2, 8, respiratory_rate=30, spo2=88)]
    assert "同程度に持続" in _subj(persisting, "ja")
    assert "Dyspnea worsening" in _subj(worsening, "en")


def test_values_are_those_of_the_latest_readings() -> None:
    text = _subj(_IMPROVING, "en")
    assert "RR 28 → 20" in text and "SpO2 89 → 96%" in text


def test_dyspnea_is_not_named_when_the_complaint_is_not_dyspnea() -> None:
    text = _subj(_IMPROVING, "en", disease="influenza", cc_ja="高熱・咳嗽", cc_en="High fever, cough")
    assert "yspnea" not in text and "Respiratory status improved" in text


def test_stable_breathing_is_stated() -> None:
    text = _subj([_v(1, 9, respiratory_rate=16, spo2=97), _v(2, 8, respiratory_rate=16, spo2=98)], "ja")
    assert "呼吸状態は安定" in text


def test_non_respiratory_disease_has_no_respiratory_line() -> None:
    text = _subj(_IMPROVING, "en", disease="sepsis")
    assert "yspnea" not in text and "Respiratory status" not in text


def test_pain_without_a_source_is_not_stated() -> None:
    ja = _subj(_IMPROVING, "ja")
    en = _subj(_IMPROVING, "en")
    assert "疼痛" not in ja and "NRS" not in ja and "NRS" not in en


def test_pain_with_a_disease_site_is_kept() -> None:
    vitals = [_v(1, 9, pain_score=7), _v(2, 8, pain_score=5)]
    assert "股関節部痛" in _subj(vitals, "ja", disease="hip_fracture", cc_ja="股関節痛", cc_en="Hip pain")
