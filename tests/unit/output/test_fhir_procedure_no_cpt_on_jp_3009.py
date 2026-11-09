"""JP Procedures carry no US CPT coding (Issue #3009)."""

from __future__ import annotations

import re

import pytest

from clinosim.codes import get_system_uri
from clinosim.modules.output.fhir_r4.procedures.procedures import _build_procedure

pytestmark = pytest.mark.unit

_CPT = get_system_uri("cpt")
_K = get_system_uri("k-codes")
_JA = re.compile(r"[぀-ヿ一-鿿]")


def _proc(code_us: str, code_jp: str = "", proc_type: str = "Colonoscopy") -> dict:
    return {
        "procedure_id": "proc-3009",
        "patient_id": "pt",
        "encounter_id": "enc",
        "procedure_type": proc_type,
        "procedure_code": code_jp or code_us,
        "procedure_code_us": code_us,
        "procedure_code_jp": code_jp,
        "start_datetime": "2026-06-15T09:00:00",
    }


def test_a_jp_colonoscopy_has_no_cpt_and_a_japanese_name() -> None:
    res = _build_procedure(_proc("45378"), "pt", 0, "JP")
    assert not [c for c in res["code"].get("coding", []) if c["system"] == _CPT]
    assert _JA.search(res["code"]["text"]), res["code"]["text"]


def test_a_jp_procedure_with_a_k_code_keeps_it_and_drops_the_cpt() -> None:
    res = _build_procedure(_proc("59510", "K898", "Cesarean delivery"), "pt", 0, "JP")
    systems = [c["system"] for c in res["code"]["coding"]]
    assert _K in systems and _CPT not in systems


def test_a_jp_procedure_pinned_to_cpt_drops_the_coding() -> None:
    proc = {**_proc("94660", proc_type="CPAP therapy"), "procedure_system_key": "cpt"}
    res = _build_procedure(proc, "pt", 0, "JP")
    assert _CPT not in [c["system"] for c in res["code"].get("coding", [])]


def test_us_keeps_cpt() -> None:
    res = _build_procedure(_proc("45378"), "pt", 0, "US")
    assert any(c["system"] == _CPT and c["code"] == "45378" for c in res["code"]["coding"])
