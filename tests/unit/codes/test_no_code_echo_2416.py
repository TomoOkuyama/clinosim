"""A display lookup never returns the code itself (Issue #2416)."""

from __future__ import annotations

import pytest

from clinosim.codes import display, get_display, lookup
from clinosim.modules.output.fhir_r4.lib.common import display_entry

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("system", "code"), [("snomed-ct", "999999999"), ("loinc", "99999-9"), ("icd-10-cm", "Z99.999")]
)
def test_lookup_miss_is_empty(system: str, code: str) -> None:
    assert lookup(system, code, "ja") == ""
    assert get_display(system, code, "JP") == ""
    assert display(system, code, "ja") is None


def test_lookup_hit_equals_display() -> None:
    assert lookup("snomed-ct", "387713003", "ja") == display("snomed-ct", "387713003", "ja")


def test_display_entry() -> None:
    assert display_entry("Body height") == {"display": "Body height"}
    assert display_entry("") == {}
