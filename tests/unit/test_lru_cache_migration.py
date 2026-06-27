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
