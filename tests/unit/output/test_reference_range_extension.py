"""Regression tests for Observation.referenceRange extensions.

Historical context:
- clinosim once emitted a `referenceRangeSource` extension citing the
  reference range's issuing body (e.g. JCCLS 共用基準範囲 2022).
- Sessions 51-55 iterated on the extension URL trying to satisfy HAPI
  Validator, but fhir-jp-validator report 2026-07-17 §【最優先 2】
  (31,006 errors) showed the URL is not registered anywhere in
  JP-CLINS 1.12.0 / jp-core 1.2.0 / jpfhir-terminology 2.2606.0. In
  addition, `JP_Observation_LabResult_eCS` locks
  `Observation.referenceRange.extension` (and `.low.extension` /
  `.high.extension`) to `max=0`, so no URL — spec-valid or not — can
  live there under the eCS profile.
- Fix: `_build_reference_range` no longer emits the extension, and a
  post-emit walker `_strip_forbidden_observation_reference_range_extensions`
  in `fhir_r4_adapter` scrubs any legacy or regressed extensions on
  `referenceRange` and `component[*].referenceRange`.

Issue: #202.
"""

import pytest

from clinosim.modules.output._fhir_common import _build_reference_range
from clinosim.modules.output.fhir_r4_adapter import (
    _strip_forbidden_observation_reference_range_extensions,
)

pytestmark = pytest.mark.unit


def test_build_reference_range_emits_no_extension_on_jp() -> None:
    """`_build_reference_range` は country=JP でも extension を emit しない。"""
    result = _build_reference_range(
        lab_name="WBC",
        patient_sex="M",
        country_code="JP",
    )
    assert result is not None
    assert len(result) > 0
    for rr in result:
        assert "extension" not in rr, "referenceRange must not carry an extension anymore"
        for side in ("low", "high"):
            sub = rr.get(side)
            if isinstance(sub, dict):
                assert "extension" not in sub


def test_build_reference_range_emits_no_extension_on_us() -> None:
    """US output も同様に extension は emit されない(regression pin)。"""
    result = _build_reference_range(
        lab_name="WBC",
        patient_sex="M",
        country_code="US",
    )
    if result is not None and len(result) > 0:
        for rr in result:
            assert "extension" not in rr


def test_strip_walker_removes_legacy_referencerangesource_extension() -> None:
    """Legacy CIF 由来の `referenceRangeSource` extension も walker で除去。"""
    resource: dict = {
        "resourceType": "Observation",
        "referenceRange": [
            {
                "low": {"value": 4.0},
                "high": {"value": 10.5},
                "extension": [
                    {
                        "url": ("http://jpfhir.jp/fhir/core/StructureDefinition/JP_Observation_ReferenceRangeSource"),
                        "valueString": "JCCLS 共用基準範囲 2022",
                    }
                ],
            }
        ],
    }
    _strip_forbidden_observation_reference_range_extensions(resource)
    assert "extension" not in resource["referenceRange"][0]


def test_strip_walker_removes_low_high_extensions() -> None:
    """`referenceRange.low.extension` / `.high.extension` も除去。
    LabResult_eCS はどちらも max=0 と定めている。"""
    resource: dict = {
        "resourceType": "Observation",
        "referenceRange": [
            {
                "low": {
                    "value": 4.0,
                    "extension": [{"url": "http://example.com/foo", "valueString": "x"}],
                },
                "high": {
                    "value": 10.5,
                    "extension": [{"url": "http://example.com/bar", "valueString": "y"}],
                },
            }
        ],
    }
    _strip_forbidden_observation_reference_range_extensions(resource)
    rr = resource["referenceRange"][0]
    assert "extension" not in rr["low"]
    assert "extension" not in rr["high"]


def test_strip_walker_removes_component_reference_range_extensions() -> None:
    """`component[*].referenceRange` も同じ制約(max=0)。BP profile 等の
    component-scoped referenceRange 経路もカバー。"""
    resource: dict = {
        "resourceType": "Observation",
        "component": [
            {
                "referenceRange": [
                    {
                        "low": {"value": 90},
                        "high": {"value": 130},
                        "extension": [{"url": "http://example.com/foo", "valueString": "x"}],
                        "modifierExtension": [{"url": "http://example.com/mod", "valueString": "z"}],
                    }
                ]
            }
        ],
    }
    _strip_forbidden_observation_reference_range_extensions(resource)
    rr = resource["component"][0]["referenceRange"][0]
    assert "extension" not in rr
    assert "modifierExtension" not in rr


def test_strip_walker_is_idempotent_on_clean_observation() -> None:
    """Extension を持たない Observation を通しても no-op、shape 不変。"""
    original = {
        "resourceType": "Observation",
        "referenceRange": [{"low": {"value": 4.0}, "high": {"value": 10.5}}],
    }
    resource = {**original, "referenceRange": [dict(rr) for rr in original["referenceRange"]]}
    _strip_forbidden_observation_reference_range_extensions(resource)
    assert resource == original


def test_strip_walker_skips_non_observation() -> None:
    """Observation 以外の resource には触れない。"""
    resource: dict = {
        "resourceType": "DiagnosticReport",
        "referenceRange": [{"extension": [{"url": "http://x", "valueString": "y"}]}],
    }
    _strip_forbidden_observation_reference_range_extensions(resource)
    # 未変更(この walker は Observation のみを対象とする)
    assert "extension" in resource["referenceRange"][0]


def test_reference_range_source_url_constant_is_removed() -> None:
    """旧 `_JP_OBSERVATION_REFERENCE_RANGE_SOURCE_URL` 定数が消えていること
    (regression 防衛:speculative URL の再導入禁止)。"""
    from clinosim.modules.output import _fhir_reference_data

    assert not hasattr(_fhir_reference_data, "_JP_OBSERVATION_REFERENCE_RANGE_SOURCE_URL")
