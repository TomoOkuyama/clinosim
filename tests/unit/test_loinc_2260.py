"""Issue #2260: emitted LOINC codes are registered with their authoritative
display, and the scale observations use real LOINC codes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from clinosim.codes.loinc import loinc_coding, loinc_display
from clinosim.modules.output.fhir_r4.labs.stage_scale_observations import _SCALE_SPECS

pytestmark = pytest.mark.unit

_SNAPSHOT = Path(__file__).resolve().parents[2] / "clinosim" / "codes" / "authoritative" / "loinc_2_82_tx.json"

# Verified on tx.fhir.org (LOINC 2.83) on 2026-10-31.
_VERIFIED = {
    "11341-5": "History of Occupation",
    "9274-2": "5 minute Apgar Score",
    "18748-4": "Diagnostic imaging study",
    "18725-2": "Microbiology studies (set)",
    "75859-9": "Modified rankin scale",
    "72088-8": "Clinical Dementia Rating scale [CDR]",
}


@pytest.mark.parametrize(("code", "display"), sorted(_VERIFIED.items()))
def test_registered_with_the_authoritative_display(code: str, display: str) -> None:
    assert loinc_display(code, "en") == display
    snapshot = {c["code"]: c["display"] for c in json.loads(_SNAPSHOT.read_text(encoding="utf-8"))["concept"]}
    assert snapshot[code] == display


def test_scales_use_real_loinc_codes() -> None:
    assert _SCALE_SPECS["mrs"].loinc == "75859-9"
    assert _SCALE_SPECS["cdr"].loinc == "72088-8"
    # No LOINC code exists for EDSS or Hoehn & Yahr: display-only.
    assert _SCALE_SPECS["edss"].loinc is None
    assert _SCALE_SPECS["hy"].loinc is None


def test_unregistered_code_has_no_display() -> None:
    assert "display" not in loinc_coding("00000-0", "en")
