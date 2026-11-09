"""Regression tests for MAR / MR route SNOMED code → display mapping.

Locks the `_ROUTE_SNOMED` display strings against the SNOMED CT International
authoritative default displays as accepted by the fhir-jp-validator tx-server.
Adding a new route mapping without a matching entry here fails the guard so
we cannot silently reintroduce the v4 chain #4 pattern (`Wrong Display Name
'Inhalation' for 447694001`).
"""

from __future__ import annotations

import pytest

from clinosim.modules.output.fhir_r4.lib.reference_data import _ROUTE_SNOMED

pytestmark = pytest.mark.unit


# SNOMED CT International-authoritative default displays for each route code
# clinosim currently emits. Verified against the tx-server-build's SNOMED
# terminology loadout used by fhir-jp-validator (v4 fullset run, 2026-07-18).
# When a display string changes, verify via `$lookup` on tx.fhir.org before
# updating this map.
_AUTHORITATIVE_SNOMED_ROUTE_DISPLAY: dict[str, str] = {
    # SNOMED International preferred terms, verified via tx.fhir.org
    # CodeSystem/$lookup (Issue #2258: displays now come from snomed-ct.yaml;
    # the former synonyms "Oral" / "Per rectum" / "Respiratory tract route
    # (qualifier value)" were replaced by the preferred terms).
    "26643006": "Oral route",
    "47625008": "Intravenous route",
    "34206005": "Subcutaneous route",
    "78421000": "Intramuscular route",
    "37161004": "Rectal route",
    "447694001": "Respiratory tract route",
    "6064005": "Topical route",
    "37839007": "Sublingual route",
    "54485002": "Ophthalmic route",
    "718329006": "Infiltration route",
    "12130007": "Intra-articular route",
    "428191002": "Percutaneous route",  # Issue #3005: tx.fhir.org $lookup 2026-11-09
}


# #311 session 60:SL の semantic-mismatch(37161004 → 37839007)は
# fix 済。allowlist から撤去。今後 sibling が同 class の bug を追加した
# 場合はここに一時登録して cross-check test を pass させ、後日別 chain
# で resolve する pattern を継続。
_KNOWN_SEMANTIC_MISMATCH_ROUTE_KEYS: frozenset[str] = frozenset()


@pytest.mark.parametrize("route_key,entry", sorted(_ROUTE_SNOMED.items()))
def test_route_snomed_display_matches_authoritative(route_key: str, entry: dict) -> None:
    if route_key in _KNOWN_SEMANTIC_MISMATCH_ROUTE_KEYS:
        pytest.skip(f"{route_key} pending follow-up (code selection, not display)")
    code = entry["code"]
    display = entry["display"]
    assert code in _AUTHORITATIVE_SNOMED_ROUTE_DISPLAY, (
        f"New route code {code!r} added to _ROUTE_SNOMED without an authoritative-display "
        f"entry in this test — verify the SNOMED CT default display and register it here."
    )
    expected = _AUTHORITATIVE_SNOMED_ROUTE_DISPLAY[code]
    assert display == expected, (
        f"Route {route_key!r} ({code}) emits display {display!r} but the "
        f"SNOMED-authoritative default is {expected!r}. Update either the code or the display."
    )


def test_inhalation_routes_use_respiratory_tract_display() -> None:
    """Chain #4 regression: INHALED / NEBULIZED must not re-emit the
    non-registered 'Inhalation' synonym for SNOMED 447694001."""
    for k in ("INHALED", "NEBULIZED"):
        assert _ROUTE_SNOMED[k]["code"] == "447694001"
        assert _ROUTE_SNOMED[k]["display"] == "Respiratory tract route"


def test_sl_uses_authoritative_sublingual_code() -> None:
    """#311 session 60:SL は authoritative Sublingual code 37839007 を使用。
    37161004 は Rectal(silent-code-substitution bug、session 45+ pattern
    で v6 で 13 件 error として顕在化)。"""
    assert _ROUTE_SNOMED["SL"]["code"] == "37839007"
    # 37161004 は Rectal 専用として PR entry のみが使用。
    assert _ROUTE_SNOMED["PR"]["code"] == "37161004"
    assert _ROUTE_SNOMED["SL"]["code"] != _ROUTE_SNOMED["PR"]["code"], (
        "SL と PR が同じ SNOMED code を使うのは semantic-mismatch(session 60 #311 で fix 済)"
    )
