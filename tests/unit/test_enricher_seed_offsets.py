"""Unit tests for ENRICHER_SEED_OFFSETS central registry (PR1 G1 refactor).

The registry is the single source of truth for AD-55 enricher sub-seed
offsets. These tests pin three properties:
1. No duplicate offsets (would silently merge two modules' RNG streams)
2. All current modules registered (regression guard against accidental removal)
3. Grandfathered legacy decimals preserved (preserving byte-identical
   identity / microbiology output for the 2026-06-24 master)
4. New entries follow 16-bit hex ASCII convention (range < 0x10000)
"""
from __future__ import annotations

import pytest

from clinosim.simulator.seeding import ENRICHER_SEED_OFFSETS


@pytest.mark.unit
def test_no_duplicate_offsets():
    """Two modules with the same offset would collide on the same RNG
    sub-stream — silent determinism bug. The module-level assert in
    seeding.py also guards this at import time; this test pins the
    contract at unit-test layer."""
    values = list(ENRICHER_SEED_OFFSETS.values())
    assert len(set(values)) == len(values), \
        f"duplicate ENRICHER_SEED_OFFSETS: {ENRICHER_SEED_OFFSETS!r}"


@pytest.mark.unit
def test_all_modules_registered():
    expected = {"identity", "microbiology", "immunization", "code_status",
                "family_history", "care_level", "nursing"}
    assert set(ENRICHER_SEED_OFFSETS.keys()) >= expected, \
        f"missing keys: {expected - set(ENRICHER_SEED_OFFSETS.keys())}"


@pytest.mark.unit
def test_grandfathered_identity_value():
    """Identity offset is grandfathered at its legacy decimal to preserve
    byte-identical JP identity / Coverage output. Changing this value
    shifts every JP patient's identifier numbers."""
    assert ENRICHER_SEED_OFFSETS["identity"] == 540_054


@pytest.mark.unit
def test_grandfathered_microbiology_value():
    """Microbiology offset is similarly grandfathered."""
    assert ENRICHER_SEED_OFFSETS["microbiology"] == 770_077


@pytest.mark.unit
def test_hex_ascii_convention_new_modules():
    """All non-grandfathered modules follow 16-bit hex ASCII convention
    (offset < 0x10000). This pins the convention for future contributors
    (CLAUDE.md + CONTRIBUTING-modules.md docs)."""
    grandfathered = {"identity", "microbiology"}
    for name, offset in ENRICHER_SEED_OFFSETS.items():
        if name in grandfathered:
            continue
        assert offset < 0x10000, \
            f"{name} offset {offset:#x} exceeds 16-bit hex ASCII range"


@pytest.mark.unit
def test_hex_ascii_values_match_module_names():
    """The hex-ASCII offsets should spell sensible 2-letter abbreviations
    of their module names — readable convention for future additions."""
    expected_ascii = {
        "immunization":   0x494D,  # "IM"
        "code_status":    0x4353,  # "CS"
        "family_history": 0x4648,  # "FH"
        "care_level":     0x434C,  # "CL"
        "nursing":        0x4E55,  # "NU"
    }
    for name, expected in expected_ascii.items():
        assert ENRICHER_SEED_OFFSETS[name] == expected, \
            f"{name}: {ENRICHER_SEED_OFFSETS[name]:#x} != {expected:#x}"
