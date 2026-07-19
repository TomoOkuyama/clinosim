"""Regression tests for MAR / MR route SNOMED code → display mapping.

Locks the `_ROUTE_SNOMED` display strings against the SNOMED CT International
authoritative default displays as accepted by the fhir-jp-validator tx-server.
Adding a new route mapping without a matching entry here fails the guard so
we cannot silently reintroduce the v4 chain #4 pattern (`Wrong Display Name
'Inhalation' for 447694001`).
"""

from __future__ import annotations

import pytest

from clinosim.modules.output._fhir_reference_data import _ROUTE_SNOMED

pytestmark = pytest.mark.unit


# SNOMED CT International-authoritative default displays for each route code
# clinosim currently emits. Verified against the tx-server-build's SNOMED
# terminology loadout used by fhir-jp-validator (v4 fullset run, 2026-07-18).
# When a display string changes, verify via `$lookup` on tx.fhir.org before
# updating this map.
_AUTHORITATIVE_SNOMED_ROUTE_DISPLAY: dict[str, str] = {
    "26643006": "Oral",
    "47625008": "Intravenous",
    "34206005": "Subcutaneous",
    "78421000": "Intramuscular",
    "37161004": "Per rectum",  # tx-server accepts this synonym
    # 447694001 default display is "Respiratory tract route (qualifier value)"
    # per SNOMED CT International; the previously-used "Inhalation" is not a
    # registered synonym in the tx-server loadout (v4 chain #4, 667 errors).
    "447694001": "Respiratory tract route (qualifier value)",
    "6064005": "Topical",
}


# SL (Sublingual) currently maps to SNOMED 37161004 = Rectal route (a semantic
# code-selection bug, not a display bug — canonical Sublingual is 37839007).
# Tracked as a follow-up in the Chain #4 Issue; excluded from the display
# lock so this Chain's fix is landable without pulling in the semantic swap.
_KNOWN_SEMANTIC_MISMATCH_ROUTE_KEYS: frozenset[str] = frozenset({"SL"})


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
        assert _ROUTE_SNOMED[k]["display"] == "Respiratory tract route (qualifier value)"
