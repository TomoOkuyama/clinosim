"""Verify global mutable _cache → @lru_cache(maxsize=1) migration.

Covers the 3 loaders enumerated in
docs/superpowers/specs/2026-06-27-pr-b1-lru-cache-migration-design.md
Section 2.1. Each test confirms the loader exposes the lru_cache API
(cache_info / cache_clear) and that subsequent calls return cached results.
"""
from __future__ import annotations

import pytest


# ---------- L1: encounter/protocol.py load_all_encounter_conditions ----------

def test_l1_load_all_encounter_conditions_uses_lru_cache():
    from clinosim.modules.encounter.protocol import load_all_encounter_conditions
    load_all_encounter_conditions.cache_clear()
    info0 = load_all_encounter_conditions.cache_info()
    assert info0.hits == 0
    data1 = load_all_encounter_conditions()
    data2 = load_all_encounter_conditions()
    info1 = load_all_encounter_conditions.cache_info()
    assert info1.hits >= 1
    assert data1 is data2  # cached object identity


# ---------- L2: simulator/helpers.py _load_all_disease_protocols ----------

def test_l2_load_all_disease_protocols_uses_lru_cache():
    from clinosim.simulator.helpers import _load_all_disease_protocols
    _load_all_disease_protocols.cache_clear()
    info0 = _load_all_disease_protocols.cache_info()
    assert info0.hits == 0
    data1 = _load_all_disease_protocols()
    data2 = _load_all_disease_protocols()
    info1 = _load_all_disease_protocols.cache_info()
    assert info1.hits >= 1
    assert data1 is data2


# ---------- L3: output/_fhir_diagnostic_report.py load_panel_groups ----------

def test_l3_load_panel_groups_uses_lru_cache():
    from clinosim.modules.output._fhir_diagnostic_report import load_panel_groups
    load_panel_groups.cache_clear()
    info0 = load_panel_groups.cache_info()
    assert info0.hits == 0
    data1 = load_panel_groups()
    data2 = load_panel_groups()
    info1 = load_panel_groups.cache_info()
    assert info1.hits >= 1
    assert data1 is data2


# ---------- Regression: module-level _cache variable removed ----------

def test_no_module_level_cache_in_encounter_protocol():
    """Module-level `_cache: ... | None = None` must be removed (replaced by @lru_cache)."""
    import clinosim.modules.encounter.protocol as mod
    assert not hasattr(mod, "_cache"), "module-level _cache should be gone after migration"


def test_no_module_level_cache_in_helpers():
    """Module-level `_protocol_cache: ... | None = None` must be removed."""
    import clinosim.simulator.helpers as mod
    assert not hasattr(mod, "_protocol_cache"), "module-level _protocol_cache should be gone"


def test_no_module_level_cache_in_fhir_diagnostic_report():
    """Module-level `_PANELS_CACHE: ... | None = None` must be removed."""
    import clinosim.modules.output._fhir_diagnostic_report as mod
    assert not hasattr(mod, "_PANELS_CACHE"), "module-level _PANELS_CACHE should be gone"


# ---------- L4-L6: _fhir_localization.py 3 sibling loaders (Fix PR-1) ----------

def test_l4_load_med_terms_ja_uses_lru_cache():
    from clinosim.modules.output._fhir_localization import _load_med_terms_ja
    _load_med_terms_ja.cache_clear()
    info0 = _load_med_terms_ja.cache_info()
    assert info0.hits == 0
    data1 = _load_med_terms_ja()
    data2 = _load_med_terms_ja()
    info1 = _load_med_terms_ja.cache_info()
    assert info1.hits >= 1
    assert data1 is data2


def test_l5_load_drug_names_ja_uses_lru_cache():
    from clinosim.modules.output._fhir_localization import _load_drug_names_ja
    _load_drug_names_ja.cache_clear()
    info0 = _load_drug_names_ja.cache_info()
    assert info0.hits == 0
    data1 = _load_drug_names_ja()
    data2 = _load_drug_names_ja()
    info1 = _load_drug_names_ja.cache_info()
    assert info1.hits >= 1
    assert data1 is data2


def test_l6_load_department_display_uses_lru_cache():
    from clinosim.modules.output._fhir_localization import _load_department_display
    _load_department_display.cache_clear()
    info0 = _load_department_display.cache_info()
    assert info0.hits == 0
    data1 = _load_department_display()
    data2 = _load_department_display()
    info1 = _load_department_display.cache_info()
    assert info1.hits >= 1
    assert data1 is data2


def test_no_module_level_cache_in_fhir_localization():
    """Module-level `_med_terms_ja` / `_drug_names_ja` / `_department_display`
    sentinel variables must be removed (replaced by @lru_cache)."""
    import clinosim.modules.output._fhir_localization as mod
    assert not hasattr(mod, "_med_terms_ja"), "module-level _med_terms_ja should be gone"
    assert not hasattr(mod, "_drug_names_ja"), "module-level _drug_names_ja should be gone"
    assert not hasattr(mod, "_department_display"), "module-level _department_display should be gone"


# ---------- Optional-file fallback paths (Fix PR-2 = Agent 5 Important) ----------
# Each _fhir_localization loader has an `if yaml_path.exists()` branch with a
# fallback empty structure. Verify the fallback path returns the documented
# shape so production never crashes if a locale file is missing.


def test_load_med_terms_ja_fallback_when_yaml_missing(monkeypatch):
    """When the optional med_terms_ja.yaml is missing, return the empty
    `{categories: {}, terms: {}}` shape."""
    from pathlib import Path

    from clinosim.modules.output import _fhir_localization
    _fhir_localization._load_med_terms_ja.cache_clear()
    monkeypatch.setattr(Path, "exists", lambda self: False)
    data = _fhir_localization._load_med_terms_ja()
    assert data == {"categories": {}, "terms": {}}
    _fhir_localization._load_med_terms_ja.cache_clear()  # leave clean for sibling tests


def test_load_drug_names_ja_fallback_when_yaml_missing(monkeypatch):
    """When the optional drug_names_ja.yaml is missing, return an empty dict."""
    from pathlib import Path

    from clinosim.modules.output import _fhir_localization
    _fhir_localization._load_drug_names_ja.cache_clear()
    monkeypatch.setattr(Path, "exists", lambda self: False)
    data = _fhir_localization._load_drug_names_ja()
    assert data == {}
    _fhir_localization._load_drug_names_ja.cache_clear()


def test_load_department_display_fallback_when_yaml_missing(monkeypatch):
    """When the optional department_display.yaml is missing, return an empty dict."""
    from pathlib import Path

    from clinosim.modules.output import _fhir_localization
    _fhir_localization._load_department_display.cache_clear()
    monkeypatch.setattr(Path, "exists", lambda self: False)
    data = _fhir_localization._load_department_display()
    assert data == {}
    _fhir_localization._load_department_display.cache_clear()


# ---------- Silent skip removal: invalid YAML must raise ----------

def test_load_all_disease_protocols_raises_on_invalid_yaml(monkeypatch):
    """After silent-skip removal: invalid YAML must propagate the error
    instead of being silently dropped (PR-A silent-no-op defense pattern)."""
    from clinosim.modules.disease import protocol as disease_protocol
    from clinosim.simulator import helpers

    helpers._load_all_disease_protocols.cache_clear()

    def fake_loader(disease_id: str):
        if disease_id == "sepsis":
            raise ValueError("synthetic invalid YAML")
        return disease_protocol.load_disease_protocol(disease_id)

    monkeypatch.setattr(helpers, "load_disease_protocol", fake_loader)
    with pytest.raises(ValueError, match="synthetic invalid YAML"):
        helpers._load_all_disease_protocols()
