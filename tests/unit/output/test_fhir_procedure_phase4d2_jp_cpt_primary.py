"""JP output of a CPT-only Procedure (Phase 4d CPAP / polysomnography).

Phase 4d.2 put the CPT code under the CPT system URI rather than the
K-codes URI. Issue #3009 goes further: JP output never carries CPT (a US
code system), so a CPT-only procedure has no CPT coding on JP and a
procedure with a K-code has no secondary CPT. US output is unchanged.
"""

from __future__ import annotations

import pytest

from clinosim.codes import get_system_uri
from clinosim.modules.output.fhir_r4.procedures.procedures import _build_procedure

pytestmark = pytest.mark.unit


def _cpt_only_proc(code: str, display: str) -> dict:
    """CIF ProcedureRecord dict with only ``procedure_code_us`` populated
    — matches the Phase 4d outpatient.py emit shape for OSA follow-up."""
    return {
        "procedure_id": "proc-4d2",
        "patient_id": "pt-4d2",
        "encounter_id": "enc-4d2",
        "procedure_type": display,
        "procedure_code": code,
        "procedure_code_us": code,
        "start_datetime": "2026-06-15T09:00:00",
        "end_datetime": "2026-06-15T09:15:00",
    }


def test_jp_cpt_only_cpap_has_no_cpt_coding() -> None:
    """CPT-only CPAP (94660) on JP output has no CPT coding (Issue #3009)."""
    res = _build_procedure(_cpt_only_proc("94660", "CPAP therapy"), "pt-4d2", 0, "JP")
    codings = res["code"].get("coding", [])
    cpt_uri = get_system_uri("cpt")
    k_uri = get_system_uri("k-codes")
    # Issue #3009: no CPT on JP, and the CPT code is never put under K-codes.
    assert not [c for c in codings if c.get("system") == cpt_uri]
    assert not [c for c in codings if c.get("code") == "94660" and c.get("system") == k_uri]


def test_jp_cpt_only_polysomnography_has_no_cpt_coding() -> None:
    """CPT-only polysomnography (95810) on JP output — same contract."""
    res = _build_procedure(_cpt_only_proc("95810", "Polysomnography"), "pt-4d2", 0, "JP")
    codings = res["code"].get("coding", [])
    cpt_uri = get_system_uri("cpt")
    k_uri = get_system_uri("k-codes")
    assert not any(c.get("system") == cpt_uri for c in codings)
    assert not any(c.get("code") == "95810" and c.get("system") == k_uri for c in codings)


def test_us_cpt_only_cpap_unchanged() -> None:
    """US output of the same input is unchanged — US primary system is
    CPT by default so the fix is a no-op on the US side."""
    res = _build_procedure(_cpt_only_proc("94660", "CPAP therapy"), "pt-4d2", 0, "US")
    codings = res["code"]["coding"]
    cpt_uri = get_system_uri("cpt")
    assert any(c.get("code") == "94660" and c.get("system") == cpt_uri for c in codings)


def test_jp_with_k_code_populated_still_uses_k_codes_primary() -> None:
    """Non-regression — when a real K-code is populated (JP-authoritative
    coding), primary system stays K-codes. Example: K7222 is a real
    K-code for a chest procedure; the simulator sets ``procedure_code``
    and ``procedure_code_jp`` to the K-code, with ``procedure_code_us``
    carrying the CPT translation."""
    proc = {
        "procedure_id": "proc-4d2-k",
        "patient_id": "pt-4d2",
        "encounter_id": "enc-4d2",
        "procedure_type": "Thoracentesis",
        "procedure_code": "K078",
        "procedure_code_jp": "K078",
        "procedure_code_us": "32555",
        "start_datetime": "2026-06-15T09:00:00",
        "end_datetime": "2026-06-15T09:15:00",
    }
    res = _build_procedure(proc, "pt-4d2", 0, "JP")
    codings = res["code"]["coding"]
    k_uri = get_system_uri("k-codes")
    cpt_uri = get_system_uri("cpt")
    # Primary (first entry) under K-codes URI with the K-code.
    assert codings[0]["system"] == k_uri
    assert codings[0]["code"] == "K078"
    # Issue #3009: no secondary CPT on JP.
    assert not any(c.get("system") == cpt_uri for c in codings)
