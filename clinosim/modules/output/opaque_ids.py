"""Opaque id derivation for FHIR Resource.id (Issue #349 Phase 1 foundation).

FHIR R4 defines Resource.id as an opaque logical identifier for referencing.
Historically clinosim encoded structural metadata (parent references, subsystem
tags, intent flags) directly in id strings as compound keys — see Issue #349
for the motivating example. That pattern (a) turned FHIR R4's 64-char
Resource.id limit into a semantic constraint on the data model (PR #348
tactical fix) and (b) forced downstream consumers to string-parse ids instead
of reading dedicated FHIR fields.

This module provides the foundation helpers that later PRs will use to
refactor id-build sites:

* :func:`derive_opaque_id` — deterministic short id derived from a compound key
* :func:`wrap_as_identifier` — round-trip preservation of the compound key as
  a FHIR ``Identifier`` entry
* :func:`structural_key_system` — canonical ``Identifier.system`` URI builder

Determinism (same ``structural_key`` → same opaque id) is essential for
byte-diff reproducibility and cross-run resource resolution. SHA-256 truncation
preserves this while giving a fixed-length output.

Length rationale
----------------
Default hash length = 12 hex chars = 48 bits of entropy. Birthday-collision
threshold ≈ √(2 · 2⁴⁸ · ln 2) ≈ 19.7 M resources of the same kind before 50 %
chance of a single collision. Even at p = 100 000 patients with ~500 M total
resources, per-kind counts stay well below this threshold in realistic
clinosim runs. Callers whose expected per-kind resource count approaches
that threshold should raise ``hash_len`` to 16 (64 bits, threshold ≈ 5·10⁹).

Composed length: a short lowercase prefix such as ``"mr-"`` (3 chars) plus the
default 12-hex digest gives a 15-char Resource.id — well under FHIR R4's
64-char limit and close to Issue #349's aspirational ≤ 16-char target.
"""

from __future__ import annotations

import hashlib

CLINOSIM_IDENTIFIER_SYSTEM_PREFIX = "urn:clinosim:identifier:"
"""Base URI for clinosim-authored FHIR ``Identifier.system`` values.

Concrete identifier systems concatenate a kebab-case kind suffix, e.g.
``urn:clinosim:identifier:medication-request-key``. Aligns with the existing
clinosim URI convention (``urn:clinosim:staff``,
``urn:clinosim:identifier:hai-event-id``).
"""


def structural_key_system(kind: str) -> str:
    """Return the canonical ``Identifier.system`` URI for a structural-key kind.

    Args:
        kind: kebab-case slug describing the structural key's domain, e.g.
            ``"medication-request-key"``, ``"regimen-key"``,
            ``"observation-key"``. Must be non-empty and non-whitespace.

    Returns:
        ``{CLINOSIM_IDENTIFIER_SYSTEM_PREFIX}{kind}``.

    Raises:
        ValueError: if ``kind`` is empty or whitespace only.
    """
    if not kind or not kind.strip():
        raise ValueError("structural_key_system kind must be non-empty")
    return f"{CLINOSIM_IDENTIFIER_SYSTEM_PREFIX}{kind}"


def derive_opaque_id(prefix: str, structural_key: str, hash_len: int = 12) -> str:
    """Return a deterministic opaque FHIR Resource.id for ``structural_key``.

    Format: ``{prefix}{sha256(structural_key).hexdigest()[:hash_len]}``.

    Determinism is by construction — the same ``(prefix, structural_key,
    hash_len)`` triple always yields the same id, so byte-diff reproducibility
    and cross-run resource resolution are preserved.

    Args:
        prefix: short lowercase alphanumeric + hyphen prefix (typically 2-4
            chars + trailing hyphen, e.g. ``"mr-"``, ``"obs-"``, ``"cnd-"``).
            Callers must include the trailing separator if desired — no
            automatic hyphen is inserted. Must be non-empty.
        structural_key: the compound key that fully identifies the resource
            within its kind (e.g.
            ``"abx-hai-ENC-POP-000905-266868769799-vap-0-cft"``). Callers
            preserve this as an ``Identifier`` via :func:`wrap_as_identifier`.
            Must be non-empty.
        hash_len: number of leading hex chars from ``sha256(structural_key)``
            to retain. Default 12 (48 bits of entropy). Range [4, 64].

    Returns:
        Opaque id string. Length = ``len(prefix) + hash_len``.

    Raises:
        ValueError: if ``prefix`` or ``structural_key`` is empty, or
            ``hash_len`` is outside ``[4, 64]``.
    """
    if not prefix:
        raise ValueError("derive_opaque_id prefix must be non-empty")
    if not structural_key:
        raise ValueError("derive_opaque_id structural_key must be non-empty")
    if not 4 <= hash_len <= 64:
        raise ValueError(f"derive_opaque_id hash_len must be in [4, 64], got {hash_len}")
    digest = hashlib.sha256(structural_key.encode("utf-8")).hexdigest()
    return f"{prefix}{digest[:hash_len]}"


def wrap_as_identifier(structural_key: str, system: str) -> dict[str, str]:
    """Return a FHIR ``Identifier`` dict that round-trips ``structural_key``.

    Intended for appending to a Resource's ``identifier[]`` so that consumers
    can recover the original compound key from any resource whose ``.id`` has
    been made opaque by :func:`derive_opaque_id`.

    Args:
        structural_key: the same compound key passed to
            :func:`derive_opaque_id`. Must be non-empty.
        system: an ``Identifier.system`` URI. Use
            :func:`structural_key_system` to construct the canonical clinosim
            URI for a given kind. Must be non-empty.

    Returns:
        FHIR R4 ``Identifier`` dict:
        ``{"system": <system>, "value": <structural_key>}``.

    Raises:
        ValueError: if either argument is empty.
    """
    if not structural_key:
        raise ValueError("wrap_as_identifier structural_key must be non-empty")
    if not system:
        raise ValueError("wrap_as_identifier system must be non-empty")
    return {"system": system, "value": structural_key}
