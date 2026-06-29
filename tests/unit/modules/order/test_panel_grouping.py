"""Unit tests for panel detection (PR1 ServiceRequest)."""

from clinosim.modules.order.panel_grouping import (
    PANEL_PRIORITY_ORDER,
    classify_lab_specs,
    load_panel_definitions,
)


def test_priority_order_constant():
    """PANEL_PRIORITY_ORDER matches lab_panel_groups.yaml header convention."""
    assert PANEL_PRIORITY_ORDER == ("ABG", "CBC", "BMP", "LFT", "Lipid", "Coag", "UA")


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
    specs = [{"test": "WBC"}, {"test": "Hb"}, {"test": "Hct"}, {"test": "Plt"},
             {"test": "Troponin_I"}]
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
