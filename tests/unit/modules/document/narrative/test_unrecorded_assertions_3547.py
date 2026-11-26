"""Issue #3547: an outpatient SOAP states only what the record holds.

The chronic seeds asserted a home blood-pressure log, an SMBG log, "no
hypoglycemic episodes" and symptom denials the record never holds, and every
problem-list-only condition read "no acute change this visit".
"""

from __future__ import annotations

import re

import pytest

from clinosim.locale.i18n import t
from clinosim.modules.document.narrative.renderers.section_builders.outpatient_soap import (
    build_outpatient_objective,
    build_outpatient_subjective,
)
from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator
from clinosim.modules.document.reference_data_loaders import load_document_data_yaml
from tests.unit.modules.document.narrative.test_full_problem_lists_3248 import _conds, _ctx

pytestmark = pytest.mark.unit

_ASSERTIONS = re.compile(
    "記録を持参|訴えなし|自覚症状なし|所見なし|増悪なし|増悪徴候なし|コントロール良好|手技は良好|"
    "エピソードなし|概ね一致|概ね継続|従来と同程度|圧痛なし|浮腫なし|聴取せず|雑音なし|肺音清|心音整|"
    "症状増悪なし|症状コントロール|軽減|使用なし|使用はまれ|大きな変化なし"
)


def test_seeds_assert_no_unrecorded_history_or_finding() -> None:
    reg = load_document_data_yaml("chronic_soap_templates.yaml")
    for code, entry in reg.items():
        if code == "metadata":
            continue
        for section, by_lang in entry.items():
            if section == "no_interval_event":  # backed by the encounter list
                continue
            for text in by_lang.values():
                assert not _ASSERTIONS.search(text), (code, section, text)


@pytest.mark.parametrize("code", ["I10", "E11", "E78", "N18", "I50", "I25", "J44", "J45", "K21"])
def test_rendered_visit_has_no_home_log_or_symptom_denial(code: str) -> None:
    gen = TemplateNarrativeGenerator()
    ctx = _ctx("ja", _conds([code]), visit_dx=code)
    subj, _ = build_outpatient_subjective(gen, ctx)
    obj, _ = build_outpatient_objective(gen, ctx)
    for text in (subj, obj):
        # The interval statement is backed by the encounter list (no
        # admission or emergency visit since the previous visit).
        text = text.replace("前回受診以降の増悪エピソードなし。", "")
        assert "家庭血圧" not in text and "SMBG" not in text, (code, text)
        assert not _ASSERTIONS.search(text), (code, text)


@pytest.mark.parametrize("lang", ["ja", "en"])
def test_chronic_med_continued_is_a_pure_status_line(lang: str) -> None:
    text = t("chronic_assessment.chronic_med_continued", lang, label="X", med="Y")
    assert "X" in text and "Y" in text
    assert "増悪" not in text and "no acute change" not in text and "本日" not in text and "this visit" not in text


@pytest.mark.parametrize("lang", ["ja", "en"])
def test_bp_above_target_plan_does_not_review_a_home_log(lang: str) -> None:
    text = t("outpatient_results.plan_bp_above_target", lang)
    assert "家庭" not in text and "home" not in text.lower()
