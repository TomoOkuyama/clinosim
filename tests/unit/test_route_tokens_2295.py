"""The route heuristic matches whole tokens, not substrings of drug names (Issue #2295)."""

from __future__ import annotations

import pytest

from clinosim.simulator.helpers import _determine_route

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "drug",
    [
        "Escitalopram",
        "Ezetimibe",
        "Simvastatin",
        "Rivaroxaban",
        "Oseltamivir",
        "Osimertinib",
        "Rifaximin",
        "Tegafur-Gimeracil-Oteracil",
        "Sulfamethoxazole-Trimethoprim",
        "Cefcapene pivoxil",
    ],
)
def test_oral_drugs_are_not_routed_by_letters_inside_their_names(drug: str) -> None:
    assert _determine_route(drug, "") == "PO"


@pytest.mark.parametrize(
    ("drug", "intent", "route"),
    [
        ("Ceftriaxone", "", "IV"),
        ("Normal saline", "IV fluid resuscitation", "IV"),
        ("Heparin", "heparin drip", "IV"),
        ("Enoxaparin", "", "SC"),
        ("Insulin", "SC sliding scale", "SC"),
        ("Ceftriaxone", "IM single dose", "IM"),
        ("Metformin", "", "PO"),
    ],
)
def test_explicit_route_tokens_and_parenteral_drugs(drug: str, intent: str, route: str) -> None:
    assert _determine_route(drug, intent) == route
