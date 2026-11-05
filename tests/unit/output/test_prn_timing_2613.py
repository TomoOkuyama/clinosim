"""Issue #2613: PRN, interval-range and weekly prescriptions carry a timing."""

from __future__ import annotations

import pytest

from clinosim.modules.output.fhir_r4.lib.dosage import resolve_timing_repeat

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("label", "repeat", "prn"),
    [
        ("q4-6h PRN", {"frequency": 1, "period": 4, "periodMax": 6, "periodUnit": "h"}, True),
        ("Q4-6H PRN", {"frequency": 1, "period": 4, "periodMax": 6, "periodUnit": "h"}, True),
        ("PRN (max 2/day)", {"frequency": 1, "frequencyMax": 2, "period": 1, "periodUnit": "d"}, True),
        ("PRN up to 3x/day", {"frequency": 1, "frequencyMax": 3, "period": 1, "periodUnit": "d"}, True),
        (
            "PRN after each loose stool (max 4/day)",
            {"frequency": 1, "frequencyMax": 4, "period": 1, "periodUnit": "d"},
            True,
        ),
        ("weekly", {"frequency": 1, "period": 1, "periodUnit": "wk"}, False),
        ("q6h PRN", {"frequency": 4, "period": 1, "periodUnit": "d"}, True),
    ],
)
def test_the_label_resolves_to_a_timing(label: str, repeat: dict, prn: bool) -> None:
    assert resolve_timing_repeat(label) == (repeat, prn)


def test_a_frequency_written_in_the_dose_text_is_used() -> None:
    from clinosim.modules.output.fhir_r4.lib.dosage import frequency_in_text

    assert frequency_in_text("70mg PO weekly") == "weekly"
    assert frequency_in_text("5mg PO q4-6h PRN") == "q4-6h PRN"
    assert frequency_in_text("40mg") == ""
