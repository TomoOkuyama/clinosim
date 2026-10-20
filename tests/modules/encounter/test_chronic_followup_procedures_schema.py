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


def test_g47_33_central_apnea_does_not_activate_g47_30_block():
    """Review Focus #1: G47.33 central sleep apnea must NOT share the OSA
    block via prefix match. chronic_followup lookup is exact-key."""
    data = load_chronic_followup()
    assert "G47.30" in data
    # Explicitly out-of-scope sibling codes must have no block entry here.
    assert data.get("G47.33") is None
    assert data.get("G47.31") is None


def test_simulator_outpatient_chronic_followup_lookup_is_exact_key():
    """Review Focus #1 adjunct: outpatient.py must NOT prefix-match
    chronic codes against chronic_followup.yaml keys — exact dict.get
    only."""
    from pathlib import Path

    src = (Path(__file__).resolve().parents[3] / "clinosim" / "simulator" / "outpatient.py").read_text(encoding="utf-8")
    # The forbidden pattern below is startswith-based iteration over the
    # chronic_followup dict keys — if a future refactor introduces that,
    # this test fires and the author decides whether sub-code match is
    # intentional (and updates G47.30 scope accordingly).
    forbidden_substrings = (
        "for k in fu:\n            if chronic_code.startswith(k)",
        "fu[next(k for k in fu if chronic_code.startswith(k))]",
    )
    for phrase in forbidden_substrings:
        assert phrase not in src, f"prefix match crept in: {phrase!r}"
