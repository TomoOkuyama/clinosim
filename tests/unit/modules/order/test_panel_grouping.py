"""Unit tests for panel detection (PR1 ServiceRequest)."""

import pytest

from clinosim.modules.order.panel_grouping import (
    PANEL_PRIORITY_ORDER,
    _validate_panel_definitions,
    classify_lab_specs,
    load_panel_definitions,
)


def test_priority_order_constant():
    """PANEL_PRIORITY_ORDER matches lab_panel_groups.yaml header convention.

    Session 47 P2-13 (JP-eCheckup): "Checkup" 健診 panel added at the tail so
    checkup batteries can be grouped as one prescription without disturbing the
    canonical acute-care panel order (ABG..UA)."""
    assert PANEL_PRIORITY_ORDER == (
        "ABG",
        "CBC",
        "BMP",
        "LFT",
        "Lipid",
        "Coag",
        "UA",
        "Checkup",
    )


def test_load_panel_definitions_has_known_panels():
    """All canonical panels are loaded from YAML."""
    panels = load_panel_definitions()
    for name in PANEL_PRIORITY_ORDER:
        assert name in panels, f"{name} missing from lab_panel_groups.yaml"
        assert "components" in panels[name]
        assert "min_components" in panels[name]
        assert "loinc" in panels[name]


def test_full_cbc_4_components_groups_as_panel():
    """4 CBC components (WBC/Hb/Hct/Plt) → 1 panel_groups[CBC]."""
    panels = load_panel_definitions()
    specs = [{"test": "WBC"}, {"test": "Hb"}, {"test": "Hct"}, {"test": "Plt"}]
    panel_groups, stand_alones = classify_lab_specs(specs, panels)
    assert "CBC" in panel_groups
    assert len(panel_groups["CBC"]) == 4
    assert stand_alones == []


def test_partial_cbc_below_min_components_falls_to_standalone():
    """2 CBC components < min_components=3 → all stand-alone."""
    panels = load_panel_definitions()
    specs = [{"test": "WBC"}, {"test": "Plt"}]
    panel_groups, stand_alones = classify_lab_specs(specs, panels)
    assert panel_groups == {}
    assert len(stand_alones) == 2


def test_partial_cbc_3_components_groups_as_panel():
    """3 CBC components == min_components=3 → grouped as CBC."""
    panels = load_panel_definitions()
    specs = [{"test": "WBC"}, {"test": "Hb"}, {"test": "Plt"}]
    panel_groups, stand_alones = classify_lab_specs(specs, panels)
    assert "CBC" in panel_groups
    assert len(panel_groups["CBC"]) == 3


def test_daily_monitoring_all_standalone():
    """Daily monitoring tests (CRP/WBC/Cr) — each below any panel's min_components."""
    panels = load_panel_definitions()
    specs = [{"test": "CRP"}, {"test": "WBC"}, {"test": "Creatinine"}]
    panel_groups, stand_alones = classify_lab_specs(specs, panels)
    assert panel_groups == {}
    assert len(stand_alones) == 3


def test_hco3_dual_membership_assigned_to_abg_first():
    """HCO3 is in both ABG and BMP. With full ABG (4 components), HCO3 goes to ABG."""
    panels = load_panel_definitions()
    specs = [{"test": "pH"}, {"test": "pCO2"}, {"test": "pO2"}, {"test": "HCO3"}]
    panel_groups, stand_alones = classify_lab_specs(specs, panels)
    assert "ABG" in panel_groups
    assert len(panel_groups["ABG"]) == 4
    assert stand_alones == []


def test_hco3_with_only_partial_abg_falls_to_standalone():
    """HCO3 + 1 ABG component < min_components=3 → HCO3 stays in ABG bucket, fails
    min_components, becomes stand-alone (not BMP fallback — conservative rule)."""
    panels = load_panel_definitions()
    specs = [{"test": "pH"}, {"test": "HCO3"}]
    panel_groups, stand_alones = classify_lab_specs(specs, panels)
    assert panel_groups == {}
    assert {s["test"] for s in stand_alones} == {"pH", "HCO3"}


def test_mixed_cbc_and_standalone():
    """4 CBC + 1 troponin = CBC panel + 1 stand-alone."""
    panels = load_panel_definitions()
    specs = [{"test": "WBC"}, {"test": "Hb"}, {"test": "Hct"}, {"test": "Plt"}, {"test": "Troponin_I"}]
    panel_groups, stand_alones = classify_lab_specs(specs, panels)
    assert "CBC" in panel_groups
    assert len(panel_groups["CBC"]) == 4
    assert len(stand_alones) == 1
    assert stand_alones[0]["test"] == "Troponin_I"


def test_unknown_test_falls_to_standalone():
    """Test not in any panel definition → stand-alone."""
    panels = load_panel_definitions()
    specs = [{"test": "MadeUpTest"}]
    panel_groups, stand_alones = classify_lab_specs(specs, panels)
    assert panel_groups == {}
    assert len(stand_alones) == 1


def test_classify_empty_input_returns_empty():
    """Empty lab_specs → empty panel_groups + empty stand_alones."""
    panels = load_panel_definitions()
    panel_groups, stand_alones = classify_lab_specs([], panels)
    assert panel_groups == {}
    assert stand_alones == []


def test_validate_panel_definitions_rejects_component_typo():
    """Layer 6b: a component typo in lab_panel_groups.yaml must fail-loud.

    Simulates the scenario where lab_panel_groups.yaml has 'WBC', 'Hbx' (typo)
    while lab_panels.yaml has 'WBC', 'Hb'. The symmetric_difference gate raises
    ValueError at import time, preventing silent panel collapse.
    """
    # Build a minimal panels dict that matches PANEL_PRIORITY_ORDER but has
    # a typo in CBC's components ("Hbx" instead of "Hb").

    # Fetch real CBC LOINC + other panels from the actual loader, then inject the typo.
    real_panels = load_panel_definitions()
    typo_panels = {}
    for name in PANEL_PRIORITY_ORDER:
        p = dict(real_panels[name])
        if name == "CBC":
            # Replace "Hb" with "Hbx" to simulate the typo
            p["components"] = ["WBC", "Hbx", "Hct", "Plt"]
        typo_panels[name] = p

    # _validate_panel_definitions performs the Layer 6b cross-validation
    # against lab_panels.yaml (via lab_panel_components). A mismatch raises ValueError.
    with pytest.raises(ValueError, match="component mismatch"):
        _validate_panel_definitions(typo_panels)
