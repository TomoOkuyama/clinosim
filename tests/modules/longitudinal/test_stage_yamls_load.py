"""Phase 2 Markov yamls — loader + schema smoke test."""

from __future__ import annotations

import pytest

from clinosim.modules.longitudinal.loader import load_attribute_specs


# attribute_id → (icd_base, expected states list)
EXPECTED: dict[str, tuple[str, list[str]]] = {
    "ckd_stage_n18": ("N18", ["CKD G1", "CKD G2", "CKD G3a", "CKD G3b", "CKD G4", "CKD G5"]),
    "copd_stage_j44": ("J44", ["GOLD 1", "GOLD 2", "GOLD 3", "GOLD 4"]),
    "heart_failure_stage_i50": ("I50", ["NYHA I", "NYHA II", "NYHA III", "NYHA IV"]),
    "ischemic_heart_stage_i25": ("I25", ["CCS I", "CCS II", "CCS III"]),
    "dementia_stage_f00": ("F00", ["CDR 0.5", "CDR 1", "CDR 2", "CDR 3"]),
}


@pytest.fixture(autouse=True)
def _clear_loader_cache():
    """The loader memoizes; sibling tests monkeypatch _LONGITUDINAL_DIR
    so a stale cached dict here can obscure the real yaml tree."""
    load_attribute_specs.cache_clear()
    yield
    load_attribute_specs.cache_clear()


@pytest.mark.unit
def test_primary_chronic_stage_yamls_load():
    specs = load_attribute_specs()
    for attr_id, (icd, states) in EXPECTED.items():
        assert attr_id in specs, f"missing {attr_id}; got keys={sorted(specs)}"
        body = specs[attr_id].body
        assert body.icd_base == icd, (attr_id, body.icd_base)
        assert body.states == states, (attr_id, body.states)
