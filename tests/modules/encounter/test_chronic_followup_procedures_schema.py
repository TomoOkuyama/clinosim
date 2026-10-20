"""Phase 4d — chronic_followup.yaml carries a procedures: field on OSA block."""

from __future__ import annotations

from clinosim.locale.loader import load_chronic_followup


def test_chronic_followup_loads_without_error():
    data = load_chronic_followup()
    assert isinstance(data, dict)


def test_g47_30_block_declares_procedures():
    """Phase 4d: G47.30 block carries procedures list with CPAP + polysomnography."""
    data = load_chronic_followup()
    block = data.get("G47.30") or {}
    procedures = block.get("procedures") or []
    codes = [p.get("snomed") for p in procedures]
    assert "47545007" in codes  # CPAP therapy
    assert "70404000" in codes  # Polysomnography


def test_g47_30_procedures_declare_frequency():
    data = load_chronic_followup()
    block = data.get("G47.30") or {}
    procedures = block.get("procedures") or []
    frequencies = {p["snomed"]: p["frequency"] for p in procedures}
    assert frequencies.get("47545007") == "every_visit"
    assert frequencies.get("70404000") == "baseline_only"


def test_polysomnography_snomed_resolves_from_name():
    """Phase 4d Task 2: polysomnography / sleep study → SNOMED 70404000
    via the pre-existing procedure name → SNOMED resolver."""
    from clinosim.modules.output.fhir_r4.procedures.procedure_name_snomed import (
        resolve_procedure_snomed,
    )

    result = resolve_procedure_snomed("polysomnography")
    assert result is not None
    snomed, _display = result
    assert snomed == "70404000"

    result2 = resolve_procedure_snomed("sleep study")
    assert result2 is not None
    assert result2[0] == "70404000"


def test_cpap_snomed_still_resolves():
    """Phase 4d regression: pre-existing CPAP SNOMED path still works."""
    from clinosim.modules.output.fhir_r4.procedures.procedure_name_snomed import (
        resolve_procedure_snomed,
    )

    result = resolve_procedure_snomed("cpap")
    assert result is not None
    assert result[0] == "47545007"
