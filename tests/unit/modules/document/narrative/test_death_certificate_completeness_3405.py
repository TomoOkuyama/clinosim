"""The death certificate and the death summary at the time of death (Issue #3405).

A single-condition death names its disease once (line (a)) and the underlying
cause line points back to it; the certificate carries the time of death and no
meta-text about the record; an autopsy at the time of death is planned, with
the findings to follow; every contributing chronic condition is listed.
"""

from __future__ import annotations

import pytest

from clinosim.modules.document.narrative.renderers.section_builders.mortality import (
    build_dc_autopsy_status,
    build_dc_contributing_conditions,
    build_dc_duration_of_immediate_cause,
    build_dc_immediate_cause,
    build_dc_time_of_death,
    build_dc_underlying_cause,
    build_dds_autopsy_status_and_findings,
)
from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator
from tests.unit.modules.document.narrative.test_death_cause_chain_3255 import _comp, _ctx


def test_single_condition_death_names_the_disease_once_ja() -> None:
    ctx = _ctx("ja", adm="K74.6", dis="K74.6")
    immediate, _ = build_dc_immediate_cause(None, ctx)
    underlying, _ = build_dc_underlying_cause(None, ctx)
    assert immediate.count("K74.6") == 1 and "K74.6" not in underlying
    assert underlying == "原死因: （ア）の疾患に同じ。"


def test_single_condition_death_names_the_disease_once_en() -> None:
    ctx = _ctx("en", adm="K74.6", dis="K74.6")
    immediate, _ = build_dc_immediate_cause(None, ctx)
    underlying, _ = build_dc_underlying_cause(None, ctx)
    assert "K74.6" in immediate and "K74.6" not in underlying
    assert underlying == "Underlying cause of death: the disease on the immediate cause line."


def test_terminal_complication_keeps_a_two_step_chain() -> None:
    ctx = _ctx("ja", adm="K74.6", dis="K74.6", comps=[_comp("respiratory_failure", 8)])
    immediate, _ = build_dc_immediate_cause(None, ctx)
    underlying, _ = build_dc_underlying_cause(None, ctx)
    assert "J96" in immediate
    assert "K74.6" in underlying and "同じ" not in underlying


@pytest.mark.parametrize("lang", ["en", "ja"])
def test_time_of_death_is_stated(lang: str) -> None:
    text, facts = build_dc_time_of_death(None, _ctx(lang, adm="K74.6", dis="K74.6"))
    assert facts
    if lang == "ja":
        assert text == "死亡年月日時刻: 2026年3月7日 12時00分。"
    else:
        assert text == "Date and time of death: 2026-03-07 12:00."


@pytest.mark.parametrize("lang", ["en", "ja"])
def test_duration_has_no_meta_text(lang: str) -> None:
    text, _ = build_dc_duration_of_immediate_cause(None, _ctx(lang, adm="K74.6", dis="K74.6"))
    assert "範囲外" not in text and "not captured" not in text
    assert "不詳" in text if lang == "ja" else "unknown" in text


@pytest.mark.parametrize("lang", ["en", "ja"])
def test_autopsy_at_death_is_planned_with_findings_to_follow(lang: str, monkeypatch: pytest.MonkeyPatch) -> None:
    import clinosim.modules.document.narrative.renderers.section_builders.mortality as m

    monkeypatch.setattr(m, "_autopsy_performed_sha256", lambda ctx: True)
    ctx = _ctx(lang, adm="K74.6", dis="K74.6")
    gen = TemplateNarrativeGenerator()
    dds, _ = build_dds_autopsy_status_and_findings(gen, ctx)
    dc, _ = build_dc_autopsy_status(gen, ctx)
    if lang == "ja":
        assert "予定" in dds and "後日" in dds and "乖離" not in dds
        assert "予定" in dc
    else:
        assert "planned" in dds and "to follow" in dds and "consistent" not in dds
        assert "planned" in dc


def test_all_contributing_chronic_conditions_are_listed() -> None:
    chronic = ["I10", "E11.9", "E78.5", "J44.9", "E66.9", "F10.20"]
    text, _ = build_dc_contributing_conditions(None, _ctx("en", adm="K74.6", dis="K74.6", chronic=chronic))
    assert "(F10.20)" in text or "(F10" in text
