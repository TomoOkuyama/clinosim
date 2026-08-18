"""JA context localization helpers (session-88j Phase B).

These helpers translate CIF enum-style tokens (mild/moderate/severe,
nasal_cannula, walk_in, low_risk, barthel_full, Creatinine, …) into
natural Japanese so they never leak into the LLM prompt as raw English
under target_language=ja.

The v14 review (seed=300 vLLM FP8 narrate) found 165 unique EN tokens
in the JA output — the largest offenders were severity labels (mild
634, moderate 442) and device names (nasal_cannula 155). Every case
below is anchored on one of those observed leaks.
"""

from __future__ import annotations

import pytest

from clinosim.modules.document.narrative.replacement_strategy import (
    _localize_arrival_mode_ja,
    _localize_barthel_band_ja,
    _localize_lab_name_ja,
    _localize_oxygen_device_ja,
    _localize_risk_level_ja,
    _localize_severity_ja,
    _render_abnormal_labs,
    _render_chronic_list,
    _render_supplemental_oxygen_today,
)


@pytest.mark.unit
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("mild", "軽度"),
        ("moderate", "中等度"),
        ("severe", "重度"),
        ("very severe", "最重度"),
        ("very_severe", "最重度"),
        ("critical", "重篤"),
        ("MILD", "軽度"),  # case-insensitive
        ("Moderate", "中等度"),
    ],
)
def test_severity_ja_mapping(raw, expected):
    assert _localize_severity_ja(raw) == expected


@pytest.mark.unit
def test_severity_ja_unknown_returns_input():
    # Safe fallback: an unmapped severity token must not disappear.
    assert _localize_severity_ja("mild-to-moderate") == "mild-to-moderate"


@pytest.mark.unit
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("nasal_cannula", "経鼻カニューレ"),
        ("oxygen_mask", "酸素マスク"),
        ("non_rebreather", "リザーバーマスク"),
        ("high_flow_nc", "ハイフローネーザル"),
        ("room_air", "大気吸入"),
        ("mechanical_ventilation", "人工呼吸器"),
        ("CPAP", "CPAP"),  # kept as-is (JA standard)
        ("BiPAP", "BiPAP"),
    ],
)
def test_oxygen_device_ja_mapping(raw, expected):
    assert _localize_oxygen_device_ja(raw) == expected


@pytest.mark.unit
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("walk_in", "独歩来院"),
        ("walk-in", "独歩来院"),
        ("Walk-in", "独歩来院"),
        ("ambulance", "救急車搬送"),
        ("helicopter", "ヘリ搬送"),
        ("transfer", "転院搬送"),
    ],
)
def test_arrival_mode_ja_mapping(raw, expected):
    assert _localize_arrival_mode_ja(raw) == expected


@pytest.mark.unit
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("low_risk", "低リスク"),
        ("moderate_risk", "中等度リスク"),
        ("high_risk", "高リスク"),
        ("very_high_risk", "非常に高リスク"),
    ],
)
def test_risk_level_ja_mapping(raw, expected):
    assert _localize_risk_level_ja(raw) == expected


@pytest.mark.unit
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("barthel_full", "Barthel 自立"),
        ("barthel_moderate", "Barthel 部分介助"),
        ("barthel_dependent", "Barthel 全介助"),
    ],
)
def test_barthel_band_ja_mapping(raw, expected):
    assert _localize_barthel_band_ja(raw) == expected


@pytest.mark.unit
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Creatinine", "クレアチニン"),
        ("Glucose", "血糖"),
        ("Lactate", "乳酸"),
        ("Albumin", "アルブミン"),
        ("Sodium", "ナトリウム"),
        ("Potassium", "カリウム"),
        ("creatinine", "クレアチニン"),
        # Kept as-is: standard abbreviations used in JA medical practice.
        ("BUN", "BUN"),
        ("CRP", "CRP"),
        ("BNP", "BNP"),
        ("WBC", "WBC"),
        ("HbA1c", "HbA1c"),
        ("eGFR", "eGFR"),
        ("Cr", "Cr"),
        ("Na", "Na"),
        ("K", "K"),
        ("PT-INR", "PT-INR"),
        ("PT_INR", "PT_INR"),
    ],
)
def test_lab_name_ja_mapping(raw, expected):
    assert _localize_lab_name_ja(raw) == expected


@pytest.mark.unit
def test_render_chronic_list_ja_localizes_severity():
    """Severity in chronic list must be JA when lang='ja'."""
    chronic = [
        {"code": "本態性高血圧", "stage": "Stage 1", "severity": "mild"},
        {"code": "心不全", "stage": "NYHA III", "severity": "moderate"},
        {"code": "COPD", "stage": "GOLD 3", "severity": "severe"},
    ]
    ja = _render_chronic_list(chronic, lang="ja")
    assert "軽度" in ja
    assert "中等度" in ja
    assert "重度" in ja
    # Ensure the severity ENGLISH tokens are gone
    assert "mild" not in ja
    assert "moderate" not in ja
    assert "severe" not in ja
    # Ensure stage tokens are preserved as-is
    assert "Stage 1" in ja
    assert "NYHA III" in ja
    assert "GOLD 3" in ja


@pytest.mark.unit
def test_render_chronic_list_en_leaves_severity_untranslated():
    chronic = [{"code": "essential HTN", "severity": "mild"}]
    en = _render_chronic_list(chronic, lang="en")
    assert "mild" in en
    assert "軽度" not in en


@pytest.mark.unit
def test_render_supplemental_oxygen_today_ja_localizes_device():
    vitals = [
        {
            "day": 2,
            "on_supplemental_oxygen": True,
            "oxygen_delivery_device": "nasal_cannula",
            "oxygen_flow_rate_lpm": 2.5,
        }
    ]
    ja = _render_supplemental_oxygen_today(vitals, day_index=2, encounter=None, lang="ja")
    assert "経鼻カニューレ" in ja
    assert "nasal_cannula" not in ja
    assert "2.5 L/min" in ja


@pytest.mark.unit
def test_render_supplemental_oxygen_today_en_keeps_snake_case():
    vitals = [
        {
            "day": 2,
            "on_supplemental_oxygen": True,
            "oxygen_delivery_device": "nasal_cannula",
            "oxygen_flow_rate_lpm": 2.5,
        }
    ]
    en = _render_supplemental_oxygen_today(vitals, day_index=2, encounter=None, lang="en")
    assert "nasal_cannula" in en
    assert "経鼻カニューレ" not in en


@pytest.mark.unit
def test_render_abnormal_labs_ja_localizes_full_english_names():
    labs = [
        {"day": 0, "lab_name": "Creatinine", "value": 1.42, "unit": "mg/dL", "flag": "H"},
        {"day": 0, "lab_name": "Glucose", "value": 214.0, "unit": "mg/dL", "flag": "H"},
        {"day": 0, "lab_name": "Sodium", "value": 130.0, "unit": "mmol/L", "flag": "L"},
        # Standard abbreviations must be kept as-is (JA medical convention).
        {"day": 0, "lab_name": "BUN", "value": 45, "unit": "mg/dL", "flag": "H"},
        {"day": 0, "lab_name": "CRP", "value": 12.4, "unit": "mg/L", "flag": "H"},
    ]
    ja = _render_abnormal_labs(labs, day_index=0, lang="ja")
    assert "クレアチニン" in ja
    assert "血糖" in ja
    assert "ナトリウム" in ja
    # No English full-word leak
    assert "Creatinine" not in ja
    assert "Glucose" not in ja
    assert "Sodium" not in ja
    # Kept-as-is checks
    assert "BUN" in ja
    assert "CRP" in ja
    # Numeric values + flags preserved verbatim
    assert "1.42" in ja
    assert "214.0" in ja
    assert "[H]" in ja
    assert "[L]" in ja


@pytest.mark.unit
def test_render_abnormal_labs_en_unchanged():
    labs = [{"day": 0, "lab_name": "Creatinine", "value": 1.42, "unit": "mg/dL", "flag": "H"}]
    en = _render_abnormal_labs(labs, day_index=0, lang="en")
    assert "Creatinine" in en
    assert "クレアチニン" not in en
