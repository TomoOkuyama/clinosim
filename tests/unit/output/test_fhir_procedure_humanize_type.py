"""Issue #1766: snake_case ``procedure_type`` classifier keys must not
leak into ``Procedure.code.coding[].display`` as the fallback value.
The classifier is stable (``chemotherapy_administration``,
``hearing_screen_aabr``, …) and consumed by narrative / screening
logic, but when the per-country code lookup (CPT / K-code) misses, the
FHIR builder uses the same string as the display fallback — which the
HL7 validator rejects at ERROR severity against bound CodeableConcept
displays.

The humanizer in ``procedures._humanize_procedure_type`` converts the
key to a Title Case label with known acronyms (AABR / MS / etc.)
preserved before the string reaches ``coding[].display``.
"""

from __future__ import annotations

import pytest

from clinosim.modules.output.fhir_r4.procedures.procedures import (
    _humanize_procedure_type,
)


@pytest.mark.parametrize(
    "snake_case,expected",
    [
        ("chemotherapy_administration", "Chemotherapy administration"),
        ("radiation_therapy", "Radiation therapy"),
        ("pregnancy_termination", "Pregnancy termination"),
        ("hearing_screen_aabr", "Hearing screen AABR"),
        ("metabolic_screen_tandem_ms", "Metabolic screen tandem MS"),
        ("cpap_titration", "Cpap titration"),  # CPAP as first word stays Capitalized
        # No underscore → unchanged
        ("CPAP therapy", "CPAP therapy"),
        ("Polysomnography", "Polysomnography"),
        # Edge: empty string unchanged
        ("", ""),
    ],
)
def test_humanize_procedure_type(snake_case: str, expected: str) -> None:
    """The humanizer must convert snake_case keys to human-readable
    Title Case labels (preserving listed acronyms)."""
    assert _humanize_procedure_type(snake_case) == expected


def test_humanize_never_contains_underscore_for_snake_case_input() -> None:
    """Invariant: output of a snake_case input must have no underscore."""
    for key in (
        "chemotherapy_administration",
        "hearing_screen_aabr",
        "metabolic_screen_tandem_ms",
        "radiation_therapy",
        "pregnancy_termination",
    ):
        assert "_" not in _humanize_procedure_type(key)
