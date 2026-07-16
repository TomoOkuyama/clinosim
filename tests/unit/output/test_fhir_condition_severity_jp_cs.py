"""JP Condition.severity primary coding pin tests。

session 53 iris4h-ai feedback F-4:JP Core `JP_ConditionSeverity_VS` は
JP_ConditionSeverity_CS の 4 code(MI/MO/SE/UK)のみを許容するため、
SNOMED coding は VS 外 = ~5k info。JP output で JP CS を primary、SNOMED を
secondary(国際互換性のため保持)として emit する挙動を pin。

URI / code 出典:iris4h-ai/tx-server-build/.../CodeSystem-jp-conditionseverity-cs.json
(spec 直接引用、`中度` であり `中等度` ではない)。
"""

from __future__ import annotations

import pytest

JP_CS = "http://jpfhir.jp/fhir/core/CodeSystem/JP_ConditionSeverity_CS"
SNOMED = "http://snomed.info/sct"


@pytest.mark.parametrize(
    "severity,jp_code,jp_display,snomed_code",
    [
        ("mild", "MI", "軽度", "255604002"),
        ("moderate", "MO", "中度", "6736007"),
        ("severe", "SE", "重度", "24484000"),
    ],
)
def test_severity_coding_jp_primary_snomed_secondary(
    severity: str, jp_code: str, jp_display: str, snomed_code: str
) -> None:
    from clinosim.modules.output._fhir_common import _severity_coding

    result = _severity_coding(severity, country="JP")
    codings = result["coding"]
    # 2 coding、primary = JP CS、secondary = SNOMED
    assert len(codings) == 2
    assert codings[0]["system"] == JP_CS
    assert codings[0]["code"] == jp_code
    assert codings[0]["display"] == jp_display
    assert codings[1]["system"] == SNOMED
    assert codings[1]["code"] == snomed_code
    # text は JP display に固定(local charting は日本語)
    assert result["text"] == jp_display


def test_severity_coding_jp_moderate_display_pins_spec_chuudo() -> None:
    """JP CS spec は `中度`、`中等度` ではない(spec 直接引用)。"""
    from clinosim.modules.output._fhir_common import _severity_coding

    result = _severity_coding("moderate", country="JP")
    jp_coding = result["coding"][0]
    assert jp_coding["display"] == "中度"
    assert jp_coding["display"] != "中等度"


@pytest.mark.parametrize(
    "severity,snomed_code,snomed_display",
    [
        ("mild", "255604002", "Mild"),
        ("moderate", "6736007", "Moderate"),
        ("severe", "24484000", "Severe"),
    ],
)
def test_severity_coding_us_single_snomed_coding(severity: str, snomed_code: str, snomed_display: str) -> None:
    """US output は SNOMED single coding、英語 display。"""
    from clinosim.modules.output._fhir_common import _severity_coding

    result = _severity_coding(severity, country="US")
    codings = result["coding"]
    assert len(codings) == 1
    assert codings[0]["system"] == SNOMED
    assert codings[0]["code"] == snomed_code
    assert codings[0]["display"] == snomed_display


def test_severity_coding_unknown_severity_falls_back_to_moderate_jp() -> None:
    """未知の severity は moderate に fallback(既存挙動維持)。JP でも同じ。"""
    from clinosim.modules.output._fhir_common import _severity_coding

    result = _severity_coding("nonsense", country="JP")
    assert result["coding"][0]["code"] == "MO"
    assert result["coding"][1]["code"] == "6736007"


def test_severity_coding_unknown_severity_falls_back_to_moderate_us() -> None:
    from clinosim.modules.output._fhir_common import _severity_coding

    result = _severity_coding("nonsense", country="US")
    assert result["coding"][0]["code"] == "6736007"
    assert len(result["coding"]) == 1
