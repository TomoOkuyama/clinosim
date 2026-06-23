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
from clinosim.simulator.seeding import derive_sub_seed, panel_specimen_seed


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


@pytest.mark.unit
class TestPanelSpecimenSeed:
    """Pin the panel-children RNG isolation seed (AD-16, CBC/BMP refactor)."""

    def test_formula_is_pinned(self):
        # Precomputed literal — if this changes, every panel-children Observation
        # (specimen-rejection / hemolysis outcomes) shifts. The parent order_id
        # itself is derived deterministically from the master seed by the
        # simulator, so this is a complete determinism gate for the
        # panel-children pass.
        assert (
            panel_specimen_seed("ORD-POP-000001-D01-L00-CBC") == 1509557560
        )

    def test_deterministic_and_in_range(self):
        a = panel_specimen_seed("ORD-POP-000001-D01-L00-CBC")
        b = panel_specimen_seed("ORD-POP-000001-D01-L00-CBC")
        assert a == b
        assert 0 <= a < 2**32

    def test_key_sensitivity(self):
        # Different parent order_id → different seed (no collision between
        # adjacent CBC orders on the same patient/day).
        a = panel_specimen_seed("ORD-POP-000001-D01-L00-CBC")
        b = panel_specimen_seed("ORD-POP-000001-D01-L00-BMP")
        c = panel_specimen_seed("ORD-POP-000001-D02-L00-CBC")
        assert a != b
        assert a != c
        assert b != c

    def test_isolated_from_derive_sub_seed(self):
        # panel_specimen_seed must not collide with any derive_sub_seed value
        # for a plausible master_seed/key combination (sanity check — they use
        # different salts/formulas and operate on different key spaces).
        for ms in (0, 1, 42, 7919):
            for offset in (_IMM_SEED_OFFSET, _NURSING_SEED_OFFSET, _MICRO_SEED_OFFSET):
                for key in ("POP-000001", "ENC-1", "ORD-POP-000001-D01-L00-CBC"):
                    assert (
                        panel_specimen_seed(key) != derive_sub_seed(ms, offset, key)
                    )
