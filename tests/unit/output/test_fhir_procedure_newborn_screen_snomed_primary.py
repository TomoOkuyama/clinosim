"""Cycle-2 M2: newborn screening Procedures emit the primary coding under
the SNOMED CT system URI, not CPT.

Phase 4d.2 fixed the mirror case (JP output of a CPT-only Procedure
emitted under the K-codes URI). This test pins the inverse:

* ``build_hearing_screen_procedure`` stores SNOMED concept id
  ``232717001`` (AABR newborn hearing screening); and
* ``build_metabolic_screen_procedure`` stores SNOMED concept id
  ``405058008`` (newborn blood spot screening).

Neither is a CPT 5-digit code — before this fix the US emit path stamped
them under ``http://www.ama-assn.org/go/cpt`` purely because the
country default system is CPT, which a strict US-Core consumer rejects.

The authoritative fix lives in the CIF layer: ``ProcedureRecord`` grew a
``procedure_system_key`` field; when the record carries
``procedure_system_key="snomed-ct"`` the FHIR builder emits the primary
``coding[]`` entry under the SNOMED CT system URI, overriding the
country default.
"""

from __future__ import annotations

import pytest

from clinosim.codes import get_system_uri
from clinosim.modules.output.fhir_r4.procedures.procedures import _build_procedure

pytestmark = pytest.mark.unit


def _snomed_screen_proc(code: str, proc_type: str) -> dict:
    """CIF ProcedureRecord dict with SNOMED-authored primary code — mirrors
    the shape ``build_hearing_screen_procedure`` /
    ``build_metabolic_screen_procedure`` emit in ``modules/newborn/engine.py``.
    No CPT or K-code is populated; the primary code is the SNOMED concept
    id, pinned via ``procedure_system_key``."""
    return {
        "procedure_id": f"proc-m2-{code}",
        "patient_id": "pt-m2-BABY",
        "encounter_id": "enc-m2",
        "procedure_type": proc_type,
        "procedure_code": code,
        "procedure_system_key": "snomed-ct",
        "category_code": "103693007",
        "start_datetime": "2026-06-01T11:00:00",
        "end_datetime": "2026-06-01T11:15:00",
    }


def test_us_hearing_screen_primary_coding_uses_snomed_system() -> None:
    """SNOMED-coded AABR hearing screen on US output — primary coding
    carries the SNOMED CT system URI, not the CPT URI."""
    res = _build_procedure(
        _snomed_screen_proc("232717001", "hearing_screen_aabr"),
        "pt-m2-BABY",
        0,
        "US",
    )
    codings = res["code"]["coding"]
    sct_uri = get_system_uri("snomed-ct")
    cpt_uri = get_system_uri("cpt")
    # Primary (first) entry under SNOMED CT URI with the SNOMED code.
    assert codings[0]["system"] == sct_uri
    assert codings[0]["code"] == "232717001"
    # Zero entries carry the SNOMED code under the CPT URI.
    assert not any(c.get("code") == "232717001" and c.get("system") == cpt_uri for c in codings)


def test_us_metabolic_screen_primary_coding_uses_snomed_system() -> None:
    """SNOMED-coded tandem-MS metabolic screen on US output — same
    contract."""
    res = _build_procedure(
        _snomed_screen_proc("405058008", "metabolic_screen_tandem_ms"),
        "pt-m2-BABY",
        0,
        "US",
    )
    codings = res["code"]["coding"]
    sct_uri = get_system_uri("snomed-ct")
    cpt_uri = get_system_uri("cpt")
    assert codings[0]["system"] == sct_uri
    assert codings[0]["code"] == "405058008"
    assert not any(c.get("code") == "405058008" and c.get("system") == cpt_uri for c in codings)


def test_jp_hearing_screen_primary_coding_uses_snomed_system() -> None:
    """Same JP contract — JP output of the SNOMED-authored screen
    emits under SNOMED CT, not the K-codes URI."""
    res = _build_procedure(
        _snomed_screen_proc("232717001", "hearing_screen_aabr"),
        "pt-m2-BABY",
        0,
        "JP",
    )
    codings = res["code"]["coding"]
    sct_uri = get_system_uri("snomed-ct")
    k_uri = get_system_uri("k-codes")
    assert codings[0]["system"] == sct_uri
    assert codings[0]["code"] == "232717001"
    assert not any(c.get("code") == "232717001" and c.get("system") == k_uri for c in codings)


def test_us_cpt_only_procedure_unchanged_by_fix() -> None:
    """Non-regression — a US CPT-only Procedure (no
    ``procedure_system_key`` set) still emits under the CPT URI, since
    the country default is CPT for US output. The new field is strictly
    additive."""
    proc = {
        "procedure_id": "proc-m2-cpt",
        "patient_id": "pt-adult",
        "encounter_id": "enc-adult",
        "procedure_type": "Polysomnography",
        "procedure_code": "95810",
        "procedure_code_us": "95810",
        "start_datetime": "2026-06-15T09:00:00",
        "end_datetime": "2026-06-15T09:15:00",
    }
    res = _build_procedure(proc, "pt-adult", 0, "US")
    codings = res["code"]["coding"]
    cpt_uri = get_system_uri("cpt")
    assert codings[0]["system"] == cpt_uri
    assert codings[0]["code"] == "95810"
