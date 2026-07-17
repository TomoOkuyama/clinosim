"""Unit tests for FHIR R4 `Resource.id` spec compliance helper.

FHIR R4 restricts `Resource.id` to ``[A-Za-z0-9\\-\\.]{1,64}``. iris4h-ai
P0 finding (2026-07-17): 812,606 ids in a full JP p=10000 export violated
this spec. IRIS FHIR endpoint (LinuxForHealth) rejects with HTTP 400.

`_fhir_id_is_spec_valid` is the single source of truth for the pattern —
callers use it in defensive assertions and the export pipeline tallies
violations for audit.
"""

from __future__ import annotations

import pytest

from clinosim.modules.output.fhir_r4_adapter import _fhir_id_is_spec_valid

pytestmark = pytest.mark.unit


def test_valid_id_alnum_and_dash():
    assert _fhir_id_is_spec_valid("vs-ENC-POP-000001-002440-0000-heart-rate")


def test_valid_id_with_dot():
    assert _fhir_id_is_spec_valid("endpoint-2.25.10029222426503844725")


def test_valid_id_single_char():
    assert _fhir_id_is_spec_valid("a")


def test_valid_id_64_chars():
    assert _fhir_id_is_spec_valid("a" * 64)


def test_invalid_id_65_chars():
    assert not _fhir_id_is_spec_valid("a" * 65)


def test_invalid_id_underscore():
    """Underscore is the iris4h-ai P0 signature — heart_rate / piperacillin_tazobactam."""
    assert not _fhir_id_is_spec_valid("vs-ENC-heart_rate")
    assert not _fhir_id_is_spec_valid("req-abx-piperacillin_tazobactam")


def test_invalid_id_empty():
    assert not _fhir_id_is_spec_valid("")


def test_invalid_id_space():
    assert not _fhir_id_is_spec_valid("has space")


def test_invalid_id_special_chars():
    for c in ("/", "\\", ":", "(", ")", "@", "#", "%", "?"):
        assert not _fhir_id_is_spec_valid(f"pre{c}suf")


def test_invalid_id_non_ascii():
    assert not _fhir_id_is_spec_valid("pre日本suf")


def test_drug_slug_translates_underscore_to_dash():
    """Regression for piperacillin_tazobactam (iris4h-ai P0)."""
    from clinosim.modules.antibiotic.engine import _drug_slug

    slug = _drug_slug("piperacillin_tazobactam")
    assert "_" not in slug
    # The override shortens this specific name; the invariant is FHIR-id-safe.
    assert _fhir_id_is_spec_valid(slug)


def test_drug_slug_regimen_id_fits_64_chars():
    """The composed id `req-abx-{hai_id}-{slug}` must stay under 64 chars.

    Real-world hai_id shape: `hai-ENC-POP-001656-091798082424-clabsi-0` (41 chars).
    Overhead = `req-abx-` (8) + hai_id (41) + `-` (1) = 50 chars → slug budget = 14.
    """
    from clinosim.modules.antibiotic.engine import _drug_slug

    hai_id = "hai-ENC-POP-001656-091798082424-clabsi-0"
    for drug_key in ("vancomycin", "piperacillin_tazobactam", "ceftriaxone"):
        slug = _drug_slug(drug_key)
        composed = f"req-abx-{hai_id}-{slug}"
        assert _fhir_id_is_spec_valid(composed), f"composed id violates FHIR spec: {composed} (len={len(composed)})"


def test_drug_slug_no_override_falls_back_to_sanitizer():
    """A brand-new drug key not in the override map still gets normalized."""
    from clinosim.modules.antibiotic.engine import _drug_slug

    # Underscores get translated to dashes by sanitize_id_token.
    slug = _drug_slug("trimethoprim_sulfamethoxazole")
    assert "_" not in slug
    assert _fhir_id_is_spec_valid(slug)
