"""Phase 1 of Issue #1698 — specialty routing table loader."""

from __future__ import annotations

import pytest

from clinosim.locale.loader import load_specialty_routing

pytestmark = pytest.mark.unit


def test_load_specialty_routing_returns_phase1_routes() -> None:
    routes = load_specialty_routing()
    assert isinstance(routes, list)
    specialties = {r["specialty"] for r in routes}
    assert {"cardiology", "oncology", "psychiatry", "pulmonology"} <= specialties
    cadences = {r["cadence"] for r in routes}
    assert cadences <= {"annual", "semi_annual", "quarterly"}


def test_load_specialty_routing_phase1_cadences() -> None:
    routes = load_specialty_routing()
    by_specialty_cadence = {(r["specialty"], r["cadence"]) for r in routes}
    assert ("oncology", "annual") in by_specialty_cadence
    assert ("cardiology", "semi_annual") in by_specialty_cadence
    assert ("psychiatry", "quarterly") in by_specialty_cadence
    assert ("pulmonology", "annual") in by_specialty_cadence
