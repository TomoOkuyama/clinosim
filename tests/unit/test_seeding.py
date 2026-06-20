"""Determinism: shared sub-seed derivation (AD-16, DET-2/EXT-4).

`derive_sub_seed` replaced three byte-identical copies in the immunization, nursing,
and microbiology enrichers. These tests pin the formula (so the extraction cannot
silently shift any RNG stream / golden output) and guard that every module's offset
stays distinct (so two enrichers never collide on the same sub-stream).
"""

import pytest

from clinosim.modules.immunization.enricher import _IMM_SEED_OFFSET
from clinosim.modules.observation.microbiology import _MICRO_SEED_OFFSET
from clinosim.modules.observation.nursing_enricher import _NURSING_SEED_OFFSET
from clinosim.simulator.seeding import derive_sub_seed


@pytest.mark.unit
class TestDeriveSubSeed:
    def test_formula_is_pinned(self):
        # Precomputed literals — if these change, every derived RNG stream (and golden
        # output) shifts. They must match the pre-extraction per-module implementations.
        assert derive_sub_seed(42, _NURSING_SEED_OFFSET, "POP-000001") == 914786652
        assert derive_sub_seed(42, _IMM_SEED_OFFSET, "POP-000001") == 914785364
        assert derive_sub_seed(7, _MICRO_SEED_OFFSET, "ENC-1") == 2694613518

    def test_deterministic_and_in_range(self):
        a = derive_sub_seed(42, _IMM_SEED_OFFSET, "POP-000001")
        b = derive_sub_seed(42, _IMM_SEED_OFFSET, "POP-000001")
        assert a == b
        assert 0 <= a < 2**32

    def test_key_sensitivity(self):
        a = derive_sub_seed(42, _IMM_SEED_OFFSET, "POP-000001")
        b = derive_sub_seed(42, _IMM_SEED_OFFSET, "POP-000002")
        assert a != b

    def test_module_offsets_are_distinct(self):
        offsets = [_IMM_SEED_OFFSET, _NURSING_SEED_OFFSET, _MICRO_SEED_OFFSET]
        assert len(set(offsets)) == len(offsets), f"sub-seed offset collision: {offsets}"
