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
