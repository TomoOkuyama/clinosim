"""Final-review Important: T1DM scope mismatch.

The 3 Phase 3 DM complication yamls emit T2DM codes (E11.21 / E11.311 /
E11.42). Their requires_chronic_codes used to include "E10" (T1DM), so a
T1DM-only patient (chronic E10.9) would have T2DM-coded complications
appended to chronic_conditions — clinically incoherent (T1DM carries
E10.21, not E11.21). Phase 3 ships T2DM complications only; T1DM
complications are deferred to Phase 4 companion yamls.
"""

from __future__ import annotations

import pytest

from clinosim.modules.longitudinal.loader import load_attribute_specs


@pytest.fixture(autouse=True)
def _clear_loader_cache():
    load_attribute_specs.cache_clear()
    yield
    load_attribute_specs.cache_clear()


@pytest.mark.unit
def test_dm_complication_yamls_scope_t2dm_only():
    """Each of the three Phase 3 DM complication yamls scopes to E11 only.
    Scoping to E10 as well would route T2DM codes onto T1DM patients."""
    specs = load_attribute_specs()
    for attr_id in (
        "dm_nephropathy_onset_e11_21",
        "dm_retinopathy_onset_e11_311",
        "dm_neuropathy_onset_e11_42",
    ):
        assert attr_id in specs, f"missing {attr_id}"
        scope = specs[attr_id].clinical_scope.requires_chronic_codes
        assert scope == ["E11"], (
            f"{attr_id} scope={scope!r} — T2DM-coded event ({specs[attr_id].body.emits_icd}) "
            f"must not scope to T1DM (E10). Phase 4 will add E10-specific companion yamls."
        )
