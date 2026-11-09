"""JP radiology reports and series views are written in Japanese (Issue #3030)."""

from __future__ import annotations

import re
from dataclasses import replace

import pytest

from clinosim.locale.loader import imaging_exam_display
from clinosim.modules.imaging.engine import load_impression_templates, load_modalities, series_view_display
from clinosim.modules.output.fhir_r4.labs.imaging_study import _build_series
from tests.unit.output.test_fhir_radiology_dr import _make_ctx, _rad_drs, _sample_study

pytestmark = pytest.mark.unit

# Latin script a Japanese radiology report normally writes as is.
_ALLOWED_LATIN = {
    "CT",
    "MRI",
    "MR",
    "DVT",
    "BI-RADS",
    "CC",
    "MLO",
    "mm",
    "cm",
    "Grade",
    "Murphy",
    "Kerley",
    "B",
    "S",
    "VF",
    "III",
    "C",
    "L",
    "T",
}  # + vertebral levels (L1, C6-C7)


def _jp_study():
    study = _sample_study()
    report = replace(
        study.report,
        findings_text_ja="右下葉に浸潤影を認める。",
        impression_text_ja="右下葉肺炎像。",
    )
    return replace(study, report=report)


def test_a_jp_chest_xray_report_div_uses_japanese_headings() -> None:
    (dr,) = _rad_drs(_make_ctx([_jp_study()], country="JP"))
    div = dr["text"]["div"]
    assert "所見" in div and "印象" in div
    assert "Findings" not in div and "Impression" not in div


def test_a_us_report_div_keeps_english_headings() -> None:
    (dr,) = _rad_drs(_make_ctx([_sample_study()], country="US"))
    assert "<h5>Findings</h5>" in dr["text"]["div"] and "<h5>Impression</h5>" in dr["text"]["div"]


def test_a_jp_series_has_a_japanese_view_name() -> None:
    series = _build_series(_sample_study().series[0], "ja")
    assert series["description"] == "正面像 (PA)"
    assert _build_series(_sample_study().series[0], "en")["description"] == "PA view"


def _all_views() -> set[str]:
    return {
        v
        for mod in load_modalities().values()
        for vs in (mod.get("default_views_by_body_site") or {}).values()
        for v in vs
    }


@pytest.mark.parametrize("suffix", ["view", "acquisition"])
def test_every_default_view_has_a_japanese_label(suffix: str) -> None:
    for view in _all_views():
        ja = series_view_display(f"{view} {suffix}", "ja")
        assert not re.search(r"[a-z]{3,}", ja), (view, ja)


def test_echo_views_read_as_words_in_english() -> None:
    assert series_view_display("parasternal_long_axis view", "en") == "parasternal long-axis view"
    assert series_view_display("apical_4_chamber view", "en") == "apical 4-chamber view"
    assert "_" not in "".join(series_view_display(f"{v} view", "en") for v in _all_views())


def test_japanese_report_templates_use_japanese_finding_terms() -> None:
    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "ja" and isinstance(value, str):
                    yield value
                else:
                    yield from walk(value)

    for text in walk(load_impression_templates()):
        words = set(re.findall(r"[A-Za-z][A-Za-z\-]*", text))
        assert words <= _ALLOWED_LATIN, (words - _ALLOWED_LATIN, text)


def test_the_swallowing_study_has_a_japanese_name() -> None:
    assert imaging_exam_display("Video_fluoroscopic_swallowing_study", "ja") == "嚥下造影検査 (VF)"
