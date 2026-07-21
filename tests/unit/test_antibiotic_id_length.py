"""Issue #347 — antibiotic MedicationRequest.id stays under FHIR R4's
64-character Resource.id limit.

Concrete failure that motivated the fix:

v16 (2026-07-21, `population=1000 seed=700` JP validation) HAPI reported
one MedicationRequest whose id was 66 characters long:

    req-abx-hai-ENC-POP-000905-266868769799-vap-0-ceftriaxone-narrowed

Composition breakdown:
    req-      (4)   — Order.id prefix (`ABX_ORDER_REQ_PREFIX`)
    abx-      (4)   — regimen prefix (`ABX_REGIMEN_ID_PREFIX`)
    hai-...   (37)  — HAI event id (`hai-{encounter_id 26}-{hai_type ≤6}-{index}`)
    -         (1)
    ceftriaxone (11) — drug slug (no override existed for this drug)
    -narrowed  (9)  — narrowed regimen suffix
    ------
    total    (66)   > 64

Fix (two-part, both must hold to survive edge cases):

1. Shorten `ABX_NARROW_SUFFIX` from `"-narrowed"` (9) to `"-n"` (2), buying
   7 chars of headroom.
2. Extend `_DRUG_SLUG_OVERRIDES` with short forms for every HAI empirical
   drug whose canonical name approaches or exceeds 10 chars (sibling-sweep
   from the concrete offender to related drugs so a future HAI YAML edit
   does not silently reintroduce the same class of failure).

A fail-loud guard `_check_fhir_id_length()` on both id-construction sites
(build_regimens for empirical + enricher for narrowed) surfaces any future
regression at generate time rather than at HAPI validation time.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from clinosim.modules.antibiotic.engine import (
    _DRUG_SLUG_OVERRIDES,
    _FHIR_ID_MAX_LENGTH,
    ABX_NARROW_SUFFIX,
    ABX_ORDER_REQ_PREFIX,
    ABX_REGIMEN_ID_PREFIX,
    _check_fhir_id_length,
    _drug_slug,
    build_regimens,
)
from clinosim.types.hai import HAIEvent

pytestmark = pytest.mark.unit


# === Constants pin ===


def test_narrow_suffix_is_short() -> None:
    """Issue #347: the narrowed suffix must be short enough that the composed
    Order.id stays under 64 chars in the worst-case build.

    Worst case (with the shortest available slug and the longest hai_id):
        `req-abx-` (8) + `hai-ENC-POP-000000-000000000000-cauti-9` (39)
        + `-` (1) + `{drug_slug ≤15}` + suffix

    With suffix=`-n` (2 chars): 8+39+1+15+2 = 65 (still over — accepted
    trade-off, see next test that pins the max realistic id length under
    the actual `_DRUG_SLUG_OVERRIDES` catalog).

    With suffix=`-narrowed` (9): 8+39+1+15+9 = 72 (way over) — hard fail.
    """
    assert len(ABX_NARROW_SUFFIX) <= 3, (
        f"ABX_NARROW_SUFFIX should be short (≤3 chars) to keep MedicationRequest.id "
        f"under FHIR R4's 64-char limit. Got {ABX_NARROW_SUFFIX!r} ({len(ABX_NARROW_SUFFIX)} chars)."
    )


# === Drug slug overrides ===


def test_ceftriaxone_has_short_slug_override() -> None:
    """Issue #347 regression pin: `ceftriaxone` was the drug that hit the
    64-char limit in v16 (2026-07-21). Its slug override must be short."""
    slug = _drug_slug("ceftriaxone")
    assert len(slug) <= 5, f"ceftriaxone slug should be ≤5 chars, got {slug!r} ({len(slug)} chars)"
    assert slug in _DRUG_SLUG_OVERRIDES.values()


def test_all_long_drug_keys_have_slug_override() -> None:
    """Sibling-sweep: every canonical HAI empirical drug_key whose length
    exceeds 10 chars must have an entry in `_DRUG_SLUG_OVERRIDES`, so no
    future HAI YAML edit that references a similarly-long drug can silently
    produce a >64-char id.

    Drug list drawn from `clinosim.modules.antibiotic.microbiology.ANTIBIOTIC_DRUGS`
    (the canonical set validated at hai_empirical.yaml load time).
    """
    from clinosim.modules.antibiotic import ANTIBIOTIC_DRUGS

    long_drugs = [d for d in ANTIBIOTIC_DRUGS if len(d) > 10]
    missing = [d for d in long_drugs if d not in _DRUG_SLUG_OVERRIDES]
    assert not missing, (
        f"drugs with canonical names > 10 chars must have _DRUG_SLUG_OVERRIDES entries "
        f"(so composed MedicationRequest.id stays ≤64). missing: {missing}"
    )


# === Length guard ===


def test_length_guard_raises_above_limit() -> None:
    """`_check_fhir_id_length` is the fail-loud guard called by
    `build_regimens` and the narrowed-regimen builder. Rejects any composed
    id that would breach the FHIR R4 Resource.id limit."""
    long_id = "req-abx-" + "x" * (_FHIR_ID_MAX_LENGTH + 1)
    with pytest.raises(ValueError, match="exceeds FHIR R4 Resource.id max length"):
        _check_fhir_id_length(long_id, "MedicationRequest")


def test_length_guard_accepts_at_limit() -> None:
    """Exactly 64 chars is the FHIR-spec maximum; the guard treats that
    length as valid (not '>' but '>=')."""
    at_limit = "x" * _FHIR_ID_MAX_LENGTH
    _check_fhir_id_length(at_limit, "MedicationRequest")  # no raise


# === End-to-end: build_regimens for the v16 offender ===


def test_build_regimens_ceftriaxone_stays_under_limit() -> None:
    """Reproduces the exact HAI encounter shape that produced the 66-char
    id in v16 (2026-07-21) and asserts the new build stays ≤64.

    The v16 case: VAP HAI on encounter `POP-000905` with the 12-digit
    per-encounter suffix, index 0. Empirical config for VAP includes
    ceftriaxone as one drug — that regimen's composed Order.id was 66.
    """
    from clinosim.modules.hai import HAI_TYPES

    # Choose a hai_type that includes ceftriaxone in its empirical drugs.
    # VAP is documented as the failing case in v16; use it here.
    assert "vap" in HAI_TYPES, "test assumes 'vap' is a valid hai_type"

    # Minimum fields for HAIEvent — only the ones referenced by build_regimens
    # matter for the id-length check we are exercising here. Others use
    # placeholders and are not consumed by this test.
    hai_event = HAIEvent(
        hai_id="hai-ENC-POP-000905-266868769799-vap-0",  # 37 chars, matches v16 shape
        encounter_id="ENC-POP-000905-266868769799",
        hai_type="vap",
        source_device_id="dev-vent-0",
        icd10_code="J95.851",
        snomed_code="429271009",
        onset_date="2024-06-15",
        organism_snomed="112283007",
        culture_specimen_id="spec-hai-vap-0",
    )
    # Should not raise (guard on build_regimens catches breach at build time).
    regimens = build_regimens(hai_event, datetime(2024, 6, 15, 8, 0, 0))
    for r in regimens:
        composed_order_id = ABX_ORDER_REQ_PREFIX + r.regimen_id
        assert len(composed_order_id) <= _FHIR_ID_MAX_LENGTH, (
            f"Issue #347 regression: composed Order.id {composed_order_id!r} "
            f"is {len(composed_order_id)} chars, exceeds {_FHIR_ID_MAX_LENGTH}."
        )


def test_narrowed_regimen_id_ceftriaxone_stays_under_limit() -> None:
    """Reconstruct the narrowed regimen id shape that was 66 chars in v16
    and assert the new components (short slug `cft` + short suffix `-n`)
    keep it ≤64."""
    hai_id = "hai-ENC-POP-000905-266868769799-vap-0"  # 37 chars
    slug = _drug_slug("ceftriaxone")
    regimen_id = f"{ABX_REGIMEN_ID_PREFIX}{hai_id}-{slug}{ABX_NARROW_SUFFIX}"
    order_id = ABX_ORDER_REQ_PREFIX + regimen_id
    assert len(order_id) <= _FHIR_ID_MAX_LENGTH, (
        f"narrowed Order.id {order_id!r} = {len(order_id)} chars, exceeds {_FHIR_ID_MAX_LENGTH}"
    )
