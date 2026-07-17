"""Regression tests for the consolidated BP-panel Observation (#210).

Blood-pressure previously emitted as two separate Observations (LOINC
8480-6 systolic + 8462-4 diastolic). The FHIR base "bp" profile — auto-
applied by HAPI on any Observation with a BP LOINC code — requires:

- `code` = LOINC 85354-9 (Blood pressure panel)
- `component[]` with a systolic slice (LOINC 8480-6) and a diastolic
  slice (LOINC 8462-4)
- both components with `valueQuantity` in `mm[Hg]`

The pre-#210 shape emitted 8480-6 / 8462-4 on the *top-level* code
field with no `component[]`, producing ~14.5k
``component:SystolicBP min=1`` / ``component:DiastolicBP min=1`` /
``BPCode: magic LOINC code 85354-9 required`` errors on the
fhir-jp-validator 2026-07-17 report (§【最優先 7】).
"""

from __future__ import annotations

from typing import Any

import pytest

from clinosim.modules.output._fhir_observations import _build_vital_observations

pytestmark = pytest.mark.unit


def _build_vitals(country: str, sbp: float | None, dbp: float | None) -> list[dict[str, Any]]:
    vs: dict[str, Any] = {
        "timestamp": "2026-06-01T10:00:00",
    }
    if sbp is not None:
        vs["systolic_bp"] = sbp
    if dbp is not None:
        vs["diastolic_bp"] = dbp
    # Include a non-BP vital so the loop path is exercised too.
    vs["heart_rate"] = 72
    entries = _build_vital_observations(vs, patient_id="pt1", index=1, country=country, encounter_id="enc1")
    return [e["resource"] for e in entries]


def _find_by_code(resources: list[dict], loinc: str) -> dict | None:
    for r in resources:
        for c in r.get("code", {}).get("coding", []) or []:
            if c.get("system") == "http://loinc.org" and c.get("code") == loinc:
                return r
    return None


def test_bp_panel_emitted_with_both_components() -> None:
    """Systolic + diastolic collapse into one Observation with code 85354-9
    and two component[] entries (8480-6 systolic, 8462-4 diastolic)."""
    resources = _build_vitals("JP", sbp=144, dbp=82)
    panel = _find_by_code(resources, "85354-9")
    assert panel is not None, "BP panel Observation missing"

    component_codes = [c["code"]["coding"][0]["code"] for c in panel.get("component") or []]
    assert component_codes == ["8480-6", "8462-4"]

    # component values match the input
    assert panel["component"][0]["valueQuantity"]["value"] == 144
    assert panel["component"][0]["valueQuantity"]["code"] == "mm[Hg]"
    assert panel["component"][1]["valueQuantity"]["value"] == 82
    assert panel["component"][1]["valueQuantity"]["code"] == "mm[Hg]"


def test_bp_panel_is_not_split_into_two_top_level_observations() -> None:
    """Verify pre-#210 shape (two top-level Observations 8480-6 / 8462-4)
    is gone. Regression pin — bringing back the old shape reintroduces
    the ~14k HAPI validator errors."""
    resources = _build_vitals("JP", sbp=144, dbp=82)
    assert _find_by_code(resources, "8480-6") is None
    assert _find_by_code(resources, "8462-4") is None


def test_bp_panel_omitted_when_only_systolic_present() -> None:
    """A partial BP reading (systolic-only) does not emit the panel —
    the missing diastolic makes the reading clinically meaningless,
    and the base `bp` profile requires both slices."""
    resources = _build_vitals("JP", sbp=144, dbp=None)
    assert _find_by_code(resources, "85354-9") is None


def test_bp_panel_omitted_when_only_diastolic_present() -> None:
    resources = _build_vitals("JP", sbp=None, dbp=82)
    assert _find_by_code(resources, "85354-9") is None


def test_bp_panel_category_and_profile_match_jp_vital_signs_on_jp() -> None:
    """JP output: `category` = vital-signs coding, `meta.profile` =
    JP_Observation_Common (JP Core VitalSigns picked up via profile
    inheritance)."""
    resources = _build_vitals("JP", sbp=120, dbp=80)
    panel = _find_by_code(resources, "85354-9")
    assert panel is not None
    cat_codes = [c.get("code") for c in panel["category"][0].get("coding") or []]
    assert "vital-signs" in cat_codes
    assert "http://jpfhir.jp/fhir/core/StructureDefinition/JP_Observation_Common" in (
        panel.get("meta", {}).get("profile", []) or []
    )


def test_bp_panel_component_carries_referencerange_and_interpretation() -> None:
    """Each component keeps referenceRange (normal + critical) and derived
    interpretation flag — the same clinical signal as the pre-#210
    top-level Observations, just moved to the component level."""
    resources = _build_vitals("JP", sbp=210, dbp=125)  # both in critical-high range
    panel = _find_by_code(resources, "85354-9")
    assert panel is not None
    sys_comp = panel["component"][0]
    dia_comp = panel["component"][1]
    for comp in (sys_comp, dia_comp):
        assert comp.get("referenceRange"), "component referenceRange missing"
        assert comp.get("interpretation"), "component interpretation missing"
        assert len(comp["referenceRange"]) == 2  # normal + critical
    # sbp=210 → HH (>= crit_high 200), dbp=125 → HH (>= crit_high 120)
    assert sys_comp["interpretation"][0]["coding"][0]["code"] == "HH"
    assert dia_comp["interpretation"][0]["coding"][0]["code"] == "HH"


def test_bp_panel_normal_interpretation_within_range() -> None:
    """When both values are inside the normal band, interpretation is N."""
    resources = _build_vitals("US", sbp=120, dbp=80)
    panel = _find_by_code(resources, "85354-9")
    assert panel is not None
    assert panel["component"][0]["interpretation"][0]["coding"][0]["code"] == "N"
    assert panel["component"][1]["interpretation"][0]["coding"][0]["code"] == "N"


def test_bp_panel_us_display_english() -> None:
    """US output uses English displays on `code` and both components."""
    resources = _build_vitals("US", sbp=120, dbp=80)
    panel = _find_by_code(resources, "85354-9")
    assert panel is not None
    assert panel["code"]["coding"][0]["display"] == "Blood pressure panel"
    assert panel["component"][0]["code"]["coding"][0]["display"] == "Systolic blood pressure"
    assert panel["component"][1]["code"]["coding"][0]["display"] == "Diastolic blood pressure"
