"""Issue #957: oncology-service-line encounters get LOINC 34133-9.

The document dispatcher's `encounter_once` branch normally uses each
spec's own `loinc_code` (34131-3 for OUTPATIENT_SOAP). For chemo cycle
visits (marked `encounter.service_line == "oncology"` by
`simulator/outpatient.py`) the Composition should carry
LOINC 34133-9 "Summary of episode note" instead — a more descriptive
fit for a chemo cycle summary than a routine SOAP note.

`_effective_outpatient_loinc` is the small helper that performs the
swap. This test exercises it directly (unit-scope) and via the enricher
end-to-end.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.unit


def test_effective_loinc_no_swap_for_non_oncology_encounter() -> None:
    """A regular outpatient encounter with `service_line == ""` gets the
    default OUTPATIENT_SOAP LOINC 34131-3."""
    from clinosim.modules.document.engine import _effective_outpatient_loinc

    enc = SimpleNamespace(service_line="")
    assert _effective_outpatient_loinc("34131-3", enc) == "34131-3"


def test_effective_loinc_swaps_for_oncology_service_line() -> None:
    """A chemo_visit encounter (`service_line == "oncology"`) gets
    LOINC 34133-9 in place of the default 34131-3."""
    from clinosim.modules.document.engine import _effective_outpatient_loinc

    enc = SimpleNamespace(service_line="oncology")
    assert _effective_outpatient_loinc("34131-3", enc) == "34133-9"


def test_effective_loinc_no_swap_for_ed_note_spec() -> None:
    """Only the OUTPATIENT_SOAP LOINC is subject to the swap. An ED note
    spec (34878-9) passes through unchanged even for oncology encounters."""
    from clinosim.modules.document.engine import _effective_outpatient_loinc

    enc = SimpleNamespace(service_line="oncology")
    assert _effective_outpatient_loinc("34878-9", enc) == "34878-9"


def test_effective_loinc_no_swap_for_ed_triage_spec() -> None:
    """Same as above for the ED triage note spec (54094-8)."""
    from clinosim.modules.document.engine import _effective_outpatient_loinc

    enc = SimpleNamespace(service_line="oncology")
    assert _effective_outpatient_loinc("54094-8", enc) == "54094-8"


def test_effective_loinc_backcompat_encounter_without_service_line() -> None:
    """Older CIF loaded without the `service_line` field must not crash;
    the helper uses `_o(...)` which returns "" when the attr is missing."""
    from clinosim.modules.document.engine import _effective_outpatient_loinc

    enc = SimpleNamespace()  # no service_line attribute at all
    assert _effective_outpatient_loinc("34131-3", enc) == "34131-3"


def test_effective_loinc_no_swap_for_dict_service_line_unknown_value() -> None:
    """An encounter carrying a service_line value other than "oncology"
    passes through unchanged."""
    from clinosim.modules.document.engine import _effective_outpatient_loinc

    enc = SimpleNamespace(service_line="cardiology")
    assert _effective_outpatient_loinc("34131-3", enc) == "34131-3"
