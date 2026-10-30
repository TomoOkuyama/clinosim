"""Strict ED-occupation gate.

Workplace-specific ED chief complaints (`chemical_exposure`,
`crush_injury_hand`, `industrial_burn_severe`, `fall_from_height`,
`electrical_injury`, `eye_foreign_body`) in
``clinosim/modules/encounter/reference_data/*.yaml`` carry
"at workplace" / "work-related" text and are only coherent on
occupations whose workplace exposes the person to the hazard. The ED
dispatcher at ``clinosim/simulator/phases/_ed_slot.py::EDSlotSampler``
multiplies each candidate's base probability by an
``occupation_risk_multipliers`` entry from the locale's
``demographics.yaml`` and falls back to
:data:`ED_OCCUPATION_MISMATCH_FALLBACK` when the occupation is not
listed.

Audit s103 flagged pre-fix behaviour: fallback was 0.05 (5 % residual
rate) so an office / student / retired patient's ED slot could still
pick a workplace-exposure CC. Issue #1702. Fix sets the fallback to
0.0 — the occupation whitelist in demographics.yaml becomes
authoritative.
"""

from __future__ import annotations

import pytest

from clinosim.locale.loader import load_demographics
from clinosim.simulator._scheduling_thresholds import ED_OCCUPATION_MISMATCH_FALLBACK

_WORKPLACE_SPECIFIC_CCS = (
    "chemical_exposure",
    "crush_injury_hand",
    "industrial_burn_severe",
    "fall_from_height",
    "electrical_injury",
    "eye_foreign_body",
)


@pytest.mark.unit
def test_fallback_constant_is_zero() -> None:
    """Scope-pin: the strict-gate contract depends on this literal
    being 0.0. Any future bump pulls workplace-exposure CCs back
    onto office / student / retired patients and reopens #1702."""
    assert ED_OCCUPATION_MISMATCH_FALLBACK == 0.0


@pytest.mark.unit
@pytest.mark.parametrize(
    "cc_name",
    _WORKPLACE_SPECIFIC_CCS,
)
def test_us_workplace_cc_declares_occupation_whitelist(cc_name: str) -> None:
    """Every workplace-specific ED CC must appear in
    ``demographics.yaml::occupation_risk_multipliers`` so the strict
    gate has a non-empty whitelist for it. Without an entry, the
    engine's ``occ_mults`` is empty → ``occ_mod = 1.0`` for every
    occupation (no gate at all). The paired check keeps the two
    sources of truth aligned."""
    demo = load_demographics("US")
    occ_mults = demo.get("occupation_risk_multipliers", {})
    assert cc_name in occ_mults, (
        f"ED CC {cc_name!r} is workplace-specific but has no "
        f"occupation_risk_multipliers entry in US demographics.yaml — "
        f"strict gate falls through for every occupation."
    )
    whitelist = occ_mults[cc_name]
    assert whitelist, f"occupation_risk_multipliers[{cc_name!r}] in US is empty — gate rejects every occupation."
    for occ, mult in whitelist.items():
        assert mult > 0, (
            f"occupation_risk_multipliers[{cc_name!r}][{occ!r}] = {mult} — "
            f"zero-rate occupations should be ABSENT from the whitelist, "
            f"not present with zero, so the fallback 0.0 handles them."
        )


@pytest.mark.unit
def test_us_chemical_exposure_whitelist_covers_realistic_occupations() -> None:
    """Positive case: the US ``chemical_exposure`` whitelist must
    cover the occupations the real-world distribution of workplace
    chemical exposure concentrates in — regression guard against a
    future audit retune accidentally removing manufacturing /
    agriculture / healthcare."""
    demo = load_demographics("US")
    whitelist = demo["occupation_risk_multipliers"]["chemical_exposure"]
    for required in ("manufacturing", "agriculture", "healthcare"):
        assert required in whitelist, (
            f"chemical_exposure whitelist missing {required!r} — "
            f"occupation has well-documented workplace chemical exposure risk."
        )


@pytest.mark.unit
@pytest.mark.parametrize(
    "office_like",
    ["office", "student", "retired", "unemployed", "homemaker"],
)
def test_office_like_occupations_excluded_from_workplace_cc_whitelists(office_like: str) -> None:
    """Pre-fix audit evidence: an ``occupation=office`` patient
    carried ``chief_complaint="Chemical exposure at workplace"`` on
    an ED visit. Office / student / retired / unemployed / homemaker
    occupations have no workplace that exposes to industrial
    hazards, so they must be ABSENT from every workplace-specific CC
    whitelist. With the strict gate (fallback = 0.0), absence yields
    occ_mod = 0.0 and the CC never fires for these occupations."""
    demo = load_demographics("US")
    occ_mults = demo.get("occupation_risk_multipliers", {})
    for cc_name in _WORKPLACE_SPECIFIC_CCS:
        whitelist = occ_mults.get(cc_name, {})
        assert office_like not in whitelist, (
            f"occupation {office_like!r} appears in {cc_name!r} whitelist — "
            f"strict gate expects office-like occupations to be absent so "
            f"the fallback (0.0) suppresses them."
        )


@pytest.mark.unit
def test_jp_workplace_cc_whitelists_also_strict() -> None:
    """JP locale carries the same workplace-specific CC catalog
    (shared yaml). Verify JP demographics.yaml also respects the
    strict-gate contract."""
    demo = load_demographics("JP")
    occ_mults = demo.get("occupation_risk_multipliers", {})
    # Not every locale needs to populate every workplace CC — but any
    # entry it does carry should respect the office-like absence rule.
    for cc_name in _WORKPLACE_SPECIFIC_CCS:
        whitelist = occ_mults.get(cc_name, {})
        for office_like in ("office", "student", "retired", "unemployed", "homemaker"):
            assert office_like not in whitelist, (
                f"JP occupation_risk_multipliers[{cc_name!r}] carries {office_like!r} — strict-gate contract violated."
            )
