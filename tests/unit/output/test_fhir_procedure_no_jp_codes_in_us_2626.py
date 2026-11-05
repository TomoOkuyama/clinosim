"""Issue #2626: US output codes procedures with US code systems only."""

from __future__ import annotations

import pytest

from clinosim.modules.output.fhir_r4.procedures.procedures import _build_procedure

pytestmark = pytest.mark.unit

_JP_PROCEDURE_SYSTEM = "urn:oid:1.2.392.200119.4.401"


def _proc(country: str) -> dict:
    return {
        "procedure_id": "PROC-1",
        "procedure_code": "36556" if country == "US" else "G005-3",
        "encounter_id": "ENC-1",
        "procedure_type": "Central venous catheter insertion",
        "procedure_code_us": "36556",
        "procedure_code_jp": "G005-3",
        "start_datetime": "2025-03-01T10:00:00",
        "end_datetime": "2025-03-01T10:30:00",
    }


def test_a_us_procedure_has_no_japanese_code() -> None:
    systems = [c["system"] for c in _build_procedure(_proc("US"), "P1", 0, "US")["code"]["coding"]]
    assert _JP_PROCEDURE_SYSTEM not in systems
    assert "http://www.ama-assn.org/go/cpt" in systems


def test_a_jp_procedure_keeps_its_k_code() -> None:
    systems = [c["system"] for c in _build_procedure(_proc("JP"), "P1", 0, "JP")["code"]["coding"]]
    assert systems[0] == _JP_PROCEDURE_SYSTEM
