"""DM complication onset event yamls — loader + schema smoke test (Phase 3 Task 3)."""

from __future__ import annotations

import pytest

from clinosim.modules.longitudinal.loader import load_attribute_specs


EXPECTED: dict[str, str] = {
    "dm_nephropathy_onset_e11_21": "E11.21",
    "dm_retinopathy_onset_e11_311": "E11.311",
    "dm_neuropathy_onset_e11_42": "E11.42",
}


@pytest.fixture(autouse=True)
def _clear_loader_cache():
    load_attribute_specs.cache_clear()
    yield
    load_attribute_specs.cache_clear()


@pytest.mark.unit
def test_dm_complication_event_yamls_load():
    specs = load_attribute_specs()
    for attr_id, icd in EXPECTED.items():
        assert attr_id in specs, f"missing {attr_id}; got keys={sorted(specs)}"
        body = specs[attr_id].body
        assert body.emits_icd == icd, (attr_id, body.emits_icd)
        assert body.one_shot is True
        assert body.base_annual_rate > 0.0
