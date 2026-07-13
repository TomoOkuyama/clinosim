"""Determinism: shared sub-seed derivation (AD-16, DET-2/EXT-4).

`derive_sub_seed` replaced three byte-identical copies in the immunization, nursing,
and microbiology enrichers. These tests pin the formula (so the extraction cannot
silently shift any RNG stream / golden output) and guard that every module's offset
stays distinct (so two enrichers never collide on the same sub-stream).
"""

import numpy as np
import pytest

from clinosim.simulator.seeding import (
    ENRICHER_SEED_OFFSETS,
    PHASE_ED_VISIT,
    PHASE_INPATIENT_SIM,
    PHASE_LIFE_EVENT,
    PHASE_OUTPATIENT_CAL,
    PHASE_READMISSION,
    _PHASE_OFFSETS,
    derive_phase_rng,
    derive_sub_seed,
    panel_specimen_seed,
)

# Local aliases preserve pre-existing test body unchanged.
# (Modules previously exported these constants; PR1 refactor centralized
# them in ENRICHER_SEED_OFFSETS — numerical values are identical, so all
# precomputed-literal pins below continue to hold.)
_IMM_SEED_OFFSET = ENRICHER_SEED_OFFSETS["immunization"]
_MICRO_SEED_OFFSET = ENRICHER_SEED_OFFSETS["microbiology"]
_NURSING_SEED_OFFSET = ENRICHER_SEED_OFFSETS["nursing"]


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


def test_phase_seed_offsets_unique():
    """AD-16: phase offset の衝突は 2 phase の RNG stream を共有させる silent-no-op。"""
    values = list(_PHASE_OFFSETS.values())
    assert len(set(values)) == len(values), f"duplicate phase offsets: {_PHASE_OFFSETS!r}"


def test_phase_seed_constants_registered():
    """新規 phase 定数を _PHASE_OFFSETS に登録し忘れると silent-no-op になる。"""
    assert PHASE_LIFE_EVENT in _PHASE_OFFSETS.values()
    assert PHASE_INPATIENT_SIM in _PHASE_OFFSETS.values()
    assert PHASE_READMISSION in _PHASE_OFFSETS.values()
    assert PHASE_OUTPATIENT_CAL in _PHASE_OFFSETS.values()
    assert PHASE_ED_VISIT in _PHASE_OFFSETS.values()


def test_derive_phase_rng_returns_generator():
    """determinism: 同 (master, phase, key) → 同 stream。"""
    a = derive_phase_rng(42, PHASE_INPATIENT_SIM, "event-1")
    b = derive_phase_rng(42, PHASE_INPATIENT_SIM, "event-1")
    assert list(a.integers(0, 100, 10)) == list(b.integers(0, 100, 10))


def test_derive_phase_rng_key_independent():
    """determinism: 同 (master, phase) でも key が違えば独立 stream。"""
    a = derive_phase_rng(42, PHASE_INPATIENT_SIM, "event-1")
    b = derive_phase_rng(42, PHASE_INPATIENT_SIM, "event-2")
    assert list(a.integers(0, 1000, 20)) != list(b.integers(0, 1000, 20))
