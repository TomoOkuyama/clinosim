"""Phase 4d.2: JP output of a CPT-only Procedure emits the primary
coding under the CPT system URI, not the K-codes system URI.

Phase 4d emits CPAP (CPT 99503) and polysomnography (CPT 95810) on the
CIF ProcedureRecord path with ``procedure_code_us`` set but no
``procedure_code_jp``. Prior to Phase 4d.2 the JP FHIR emit path put
these codes under the ``http://jpfhir.jp/fhir/core/CodeSystem/
JP_MedicalProcedure_CS`` (K-codes) system URI — semantically wrong,
since 99503 / 95810 are CPT codes not K-codes. A consumer validating
against the K-codes system would reject them.

This test pins the fix: when ``is_jp(country)`` and no K-code is
available but a CPT code is, the primary ``coding[]`` entry carries
the CPT system URI. The redundant secondary CPT entry is suppressed
in that same case.
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


def test_jp_cpt_only_cpap_primary_coding_uses_cpt_system() -> None:
    """CPT-only CPAP (99503) on JP output — primary coding carries the
    CPT system URI, not the K-codes URI."""
    res = _build_procedure(_cpt_only_proc("99503", "CPAP therapy"), "pt-4d2", 0, "JP")
    codings = res["code"]["coding"]
    cpt_uri = get_system_uri("cpt")
    k_uri = get_system_uri("k-codes")
    # Exactly one CPT 99503 entry (primary), zero under K-codes URI.
    cpt_entries = [c for c in codings if c.get("code") == "99503" and c.get("system") == cpt_uri]
    k_entries = [c for c in codings if c.get("code") == "99503" and c.get("system") == k_uri]
    assert len(cpt_entries) == 1
    assert len(k_entries) == 0


def test_jp_cpt_only_polysomnography_primary_coding_uses_cpt_system() -> None:
    """CPT-only polysomnography (95810) on JP output — same contract."""
    res = _build_procedure(_cpt_only_proc("95810", "Polysomnography"), "pt-4d2", 0, "JP")
    codings = res["code"]["coding"]
    cpt_uri = get_system_uri("cpt")
    k_uri = get_system_uri("k-codes")
    assert any(c.get("code") == "95810" and c.get("system") == cpt_uri for c in codings)
    assert not any(c.get("code") == "95810" and c.get("system") == k_uri for c in codings)


def test_us_cpt_only_cpap_unchanged() -> None:
    """US output of the same input is unchanged — US primary system is
    CPT by default so the fix is a no-op on the US side."""
    res = _build_procedure(_cpt_only_proc("99503", "CPAP therapy"), "pt-4d2", 0, "US")
    codings = res["code"]["coding"]
    cpt_uri = get_system_uri("cpt")
    assert any(c.get("code") == "99503" and c.get("system") == cpt_uri for c in codings)


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
    # Secondary CPT 32555 still emitted for interop.
    assert any(c.get("code") == "32555" and c.get("system") == cpt_uri for c in codings)
