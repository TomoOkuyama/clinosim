"""Issue #349 Phase 1 foundation: opaque id derivation + identifier round-trip.

Pins the behavior of :mod:`clinosim.modules.output.opaque_ids` before any id
build site is refactored to use it. Later PRs (Phase 1b / 2 / 3) will
exercise the helpers in production emitter code; this test file guards the
helpers themselves so subsequent regressions are localized.

Concrete failure the module addresses:

v16 (2026-07-21, ``population=1000 seed=700`` JP validation) HAPI reported
a 66-char antibiotic ``MedicationRequest.id`` — five distinct pieces of
structural metadata packed into a compound key. PR #348 shortened one
suffix mechanically; Issue #349 replaces the compound-id-as-key pattern
with opaque short ids + ``Identifier`` round-trip.
"""

from __future__ import annotations

import hashlib

import pytest

from clinosim.modules.output.opaque_ids import (
    CLINOSIM_IDENTIFIER_SYSTEM_PREFIX,
    derive_opaque_id,
    structural_key_system,
    wrap_as_identifier,
)

pytestmark = pytest.mark.unit


# === structural_key_system ===


def test_structural_key_system_concatenates_prefix_and_kind() -> None:
    assert structural_key_system("medication-request-key") == "urn:clinosim:identifier:medication-request-key"


def test_structural_key_system_uses_shared_prefix_constant() -> None:
    result = structural_key_system("x")
    assert result.startswith(CLINOSIM_IDENTIFIER_SYSTEM_PREFIX)


def test_structural_key_system_rejects_empty_kind() -> None:
    with pytest.raises(ValueError, match="kind must be non-empty"):
        structural_key_system("")


def test_structural_key_system_rejects_whitespace_only_kind() -> None:
    with pytest.raises(ValueError, match="kind must be non-empty"):
        structural_key_system("   ")


# === derive_opaque_id ===


def test_derive_opaque_id_is_deterministic() -> None:
    """Byte-diff reproducibility requires that the same structural_key always
    resolve to the same opaque id across runs."""
    a = derive_opaque_id("mr-", "abx-hai-ENC-POP-000905-266868769799-vap-0-cft")
    b = derive_opaque_id("mr-", "abx-hai-ENC-POP-000905-266868769799-vap-0-cft")
    assert a == b


def test_derive_opaque_id_prefix_is_retained() -> None:
    result = derive_opaque_id("obs-", "some-structural-key")
    assert result.startswith("obs-")


def test_derive_opaque_id_matches_sha256_truncation() -> None:
    """The id must equal ``{prefix}{sha256(key).hexdigest()[:hash_len]}``
    exactly — no salt, no additional transformation. Pinning this so a future
    'optimization' cannot silently change downstream ids and break byte-diff
    reproducibility across runs."""
    key = "some-structural-key"
    expected_digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    result = derive_opaque_id("obs-", key, hash_len=12)
    assert result == f"obs-{expected_digest[:12]}"


def test_derive_opaque_id_default_hash_length_is_12() -> None:
    result = derive_opaque_id("x-", "k")
    # prefix "x-" (2) + 12 hex = 14
    assert len(result) == 14


def test_derive_opaque_id_custom_hash_length_respected() -> None:
    assert len(derive_opaque_id("x-", "k", hash_len=8)) == 10
    assert len(derive_opaque_id("x-", "k", hash_len=16)) == 18


def test_derive_opaque_id_different_keys_produce_different_ids() -> None:
    """Not a strict cryptographic property (sha256 truncation can collide) but
    a smoke test that near-neighbor inputs produce distinct ids — the common
    case for clinosim structural keys."""
    a = derive_opaque_id("x-", "key1")
    b = derive_opaque_id("x-", "key2")
    assert a != b


def test_derive_opaque_id_length_equals_prefix_plus_hash_len() -> None:
    """Output length is deterministic and independent of structural_key content
    — the helper's core promise. Callers rely on this to keep composed
    Resource.id lengths bounded regardless of how large the source compound
    key grows (the class of failure Issue #349 exists to eliminate)."""
    for prefix, key, hash_len in [
        ("mr-", "k", 12),
        ("obs-", "k" * 1000, 12),
        ("cnd-", "some-key", 8),
        ("x-", "another", 64),
    ]:
        result = derive_opaque_id(prefix, key, hash_len=hash_len)
        assert len(result) == len(prefix) + hash_len, (
            f"prefix={prefix!r} hash_len={hash_len} → expected {len(prefix) + hash_len}, got {len(result)}: {result!r}"
        )


def test_derive_opaque_id_realistic_clinosim_usage_stays_well_under_64() -> None:
    """Under realistic clinosim conventions — short 2-5 char lowercase prefix
    + trailing hyphen, default 12-hex hash — Resource.id stays ≤ 18 chars
    regardless of the structural_key size. Well under FHIR R4's 64-char limit
    (the class of failure Issue #349 exists to eliminate) and close to
    Issue #349's aspirational ≤ 16-char target for the common short prefixes.
    """
    long_compound_key = "abx-hai-ENC-POP-000905-266868769799-vap-0-ceftriaxone-narrowed"
    for prefix in ("mr-", "obs-", "cnd-", "spec-"):
        result = derive_opaque_id(prefix, long_compound_key)
        assert len(result) <= 18, f"prefix={prefix!r} → {result!r} ({len(result)} chars)"
        assert len(result) < 64  # explicit FHIR-limit reminder


def test_derive_opaque_id_output_is_lowercase_hex_after_prefix() -> None:
    """Downstream URI encoding, filesystem paths, and case-insensitive
    reference matching all benefit from lowercase-hex opaque bodies."""
    result = derive_opaque_id("x-", "some-key")
    body = result[2:]
    assert body == body.lower()
    assert all(c in "0123456789abcdef" for c in body)


def test_derive_opaque_id_rejects_empty_prefix() -> None:
    with pytest.raises(ValueError, match="prefix must be non-empty"):
        derive_opaque_id("", "k")


def test_derive_opaque_id_rejects_empty_structural_key() -> None:
    with pytest.raises(ValueError, match="structural_key must be non-empty"):
        derive_opaque_id("x-", "")


@pytest.mark.parametrize("bad_len", [-1, 0, 3, 65, 128])
def test_derive_opaque_id_rejects_out_of_range_hash_len(bad_len: int) -> None:
    with pytest.raises(ValueError, match="hash_len must be in"):
        derive_opaque_id("x-", "k", hash_len=bad_len)


# === wrap_as_identifier ===


def test_wrap_as_identifier_returns_fhir_shape() -> None:
    result = wrap_as_identifier(
        "abx-hai-ENC-POP-000905-vap-0-cft",
        "urn:clinosim:identifier:regimen-key",
    )
    assert result == {
        "system": "urn:clinosim:identifier:regimen-key",
        "value": "abx-hai-ENC-POP-000905-vap-0-cft",
    }


def test_wrap_as_identifier_round_trip_recovers_structural_key() -> None:
    """Round-trip invariant: an opaque id + its Identifier entry together
    preserve the full structural key, so downstream consumers can recover
    it without string-parsing the (now opaque) Resource.id.

    Exercises the exact v16 offender shape from PR #348 / Issue #347 —
    the compound key that motivated the whole refactor."""
    structural_key = "abx-hai-ENC-POP-000905-266868769799-vap-0-cft-n"
    opaque = derive_opaque_id("mr-", structural_key)
    ident = wrap_as_identifier(structural_key, structural_key_system("regimen-key"))
    # Opaque id is short and does not leak the structural key.
    assert len(opaque) < 32
    assert structural_key not in opaque
    # Identifier preserves the full key verbatim for round-trip.
    assert ident["value"] == structural_key
    assert ident["system"] == "urn:clinosim:identifier:regimen-key"


def test_wrap_as_identifier_rejects_empty_key() -> None:
    with pytest.raises(ValueError, match="structural_key must be non-empty"):
        wrap_as_identifier("", "urn:clinosim:identifier:x")


def test_wrap_as_identifier_rejects_empty_system() -> None:
    with pytest.raises(ValueError, match="system must be non-empty"):
        wrap_as_identifier("k", "")
