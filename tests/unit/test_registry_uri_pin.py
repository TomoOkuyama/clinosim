"""URI pin tests — canonical registry URIs MUST match JP Core NamingSystem
preferred=True fixedUri (session 50 rule).

Purpose
-------
Every URI addition/change to ``clinosim/codes/loader.py::_BUILTIN_URIS`` and
``clinosim/codes/data/*.yaml`` is a claim about the spec canonical. This
test file pins the URI as a module-level constant with its authoritative
source cited in a comment, so a future edit that swaps in a "plausible
looking" URI fails at CI time rather than silently drifting.

The pinned URIs come from ``iris4h-ai/jp_core/package/NamingSystem-*.json``
``uniqueId[].value`` where ``preferred=True`` (spec canonical), or from
the JP-CLINS eCS ``CodeSystem.url`` for spec-published CodeSystems.

Regression detector
-------------------
The trailing ``test_yj_uri_is_not_hot9_alias_oid`` guards against
re-introducing ``urn:oid:1.2.392.100495.20.2.74`` (HOT9 alias OID, NOT
the YJ canonical) — the exact drift B2 (2026-07-26) fixed.
"""

from __future__ import annotations

from clinosim.codes.loader import get_system_uri

# --------------------------------------------------------------------------- #
# Pinned URIs — spec canonical.
#
# Each constant carries the exact authoritative source in the trailing comment
# so a reviewer can verify without leaving this file.

# YJ (JP MHLW 薬価基準 12桁): iris4h-ai/jp_core/package/
#   NamingSystem-jp-medicationcodeyj-namingsystem.json
#   uniqueId[type=uri, preferred=True].value
_YJ_URI = "http://capstandard.jp/iyaku.info/CodeSystem/YJ-code"

# MEDIS HOT7 (7桁): iris4h-ai/jp_core/package/
#   NamingSystem-jp-medis-medicationcodehot7-namingsystem.json
#   uniqueId[type=uri, preferred=True].value
_HOT7_URI = "http://medis.or.jp/CodeSystem/master-HOT7"

# MEDIS HOT9 (9桁): iris4h-ai/jp_core/package/
#   NamingSystem-jp-medis-medicationcodehot9-namingsystem.json
#   uniqueId[type=uri, preferred=True].value
# NOTE: HOT9 の alias OID `urn:oid:1.2.392.100495.20.2.74` は spec 上 preferred=False。
#       この OID は YJ の canonical ではない (YJ 本来の OID は `.73`)。
#       B2 2026-07-26 の registry drift はこの OID を YJ に紐付けていた誤りだった。
_HOT9_URI = "http://medis.or.jp/CodeSystem/master-HOT9"

# MEDIS HOT13 (13桁): iris4h-ai/jp_core/package/
#   NamingSystem-jp-medis-medicationcodehot13-namingsystem.json
#   uniqueId[type=uri, preferred=True].value
_HOT13_URI = "http://medis.or.jp/CodeSystem/master-HOT13"

# JP-CLINS eCS Nocoded fallback CS: clinical-information-sharing#1.12.0/package/
#   CodeSystem-jp-eCS-medicationcode-nocoded-cs.json
#   `url` field (spec-published complete CS)
_MEDICATION_NOCODED_URI = "http://jpfhir.jp/fhir/eCS/CodeSystem/MedicationCodeNocoded_CS"

# Regression detector — this OID MUST NOT be returned by `get_system_uri("yj")`.
# It is HOT9's alias OID (JP Core preferred=False) and was mis-registered under
# the "yj" key until B2 2026-07-26.
_HOT9_ALIAS_OID_NOT_YJ = "urn:oid:1.2.392.100495.20.2.74"


def test_yj_uri_pinned_to_jp_core_preferred_fixed_uri() -> None:
    assert get_system_uri("yj") == _YJ_URI


def test_hot7_uri_pinned_to_jp_core_preferred_fixed_uri() -> None:
    assert get_system_uri("hot7") == _HOT7_URI


def test_hot9_uri_pinned_to_jp_core_preferred_fixed_uri() -> None:
    assert get_system_uri("hot9") == _HOT9_URI


def test_hot13_uri_pinned_to_jp_core_preferred_fixed_uri() -> None:
    assert get_system_uri("hot13") == _HOT13_URI


def test_medication_nocoded_uri_pinned_to_jp_clins_ecs_spec_url() -> None:
    assert get_system_uri("medication-nocoded") == _MEDICATION_NOCODED_URI


def test_yj_uri_is_not_hot9_alias_oid() -> None:
    """Regression: prevent re-introducing the `.74` HOT9 alias OID under `yj`.

    B2 2026-07-26 fixed a canonical registry drift where `_BUILTIN_URIS["yj"]`
    was `urn:oid:1.2.392.100495.20.2.74` — that is HOT9's alias OID, not the
    YJ canonical. This test stops that specific literal from re-appearing.
    """
    assert get_system_uri("yj") != _HOT9_ALIAS_OID_NOT_YJ
