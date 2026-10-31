"""Issue #2263: procedure codes and names come from one catalog, and coded
procedure displays go through one K-code-then-CPT lookup."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from clinosim.codes import display
from clinosim.codes.procedures import (
    bedside_procedures,
    procedure_code,
    procedure_code_display,
    procedure_type_display,
)
from clinosim.locale.loader import load_code_mapping
from clinosim.modules.document.narrative._localization import _localize_proc_type
from clinosim.modules.output.fhir_r4.procedures.procedures import _build_procedure
from clinosim.modules.procedure.engine import _BEDSIDE_PROCEDURES

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2] / "clinosim"


def test_engine_table_is_built_from_the_catalog() -> None:
    assert len(_BEDSIDE_PROCEDURES) == len(bedside_procedures())
    assert _BEDSIDE_PROCEDURES[0] == (
        "urinary_catheter",
        "51702",
        "D002",
        "Urinary catheter insertion",
        "尿道カテーテル挿入",
        "none",
    )


def test_procedure_code_per_country() -> None:
    assert procedure_code("urinary_catheter", "US") == "51702"
    assert procedure_code("urinary_catheter", "JP") == "D002"
    assert procedure_code("ecg_12lead", "JP") == ""  # no verified K-code yet
    assert procedure_code("not_a_procedure", "US") == ""


def test_hip_fracture_codes_come_from_the_locale_mapping() -> None:
    assert load_code_mapping("procedure", "US") == {"ORIF_femur": "27236", "hemiarthroplasty_hip": "27125"}
    assert load_code_mapping("procedure", "JP") == {"ORIF_femur": "K0461", "hemiarthroplasty_hip": "K0811"}


def test_coded_display_tries_k_codes_then_cpt() -> None:
    assert procedure_code_display(["", "K0461"], "ja") == display("k-codes", "K0461", "ja")
    assert procedure_code_display(["no-such-code"], "en") is None


def test_fhir_and_narrative_show_the_same_name_for_an_uncoded_type() -> None:
    proc = {"procedure_type": "ecg_12lead", "procedure_id": "p1", "encounter_id": "e1"}
    res = _build_procedure(proc, "pt1", 0, "US")
    assert res["code"]["coding"][0]["display"] == "12-lead ECG" == _localize_proc_type("ecg_12lead", "en")
    assert _localize_proc_type("ecg_12lead", "ja") == procedure_type_display("ecg_12lead", "ja") == "12誘導心電図"
    assert _localize_proc_type("delivery_vaginal", "en") == "delivery vaginal"


def test_one_copy_of_the_display_loop() -> None:
    loop = re.compile(r'for system_key in \("k-codes", "cpt"\)')
    offenders = [
        p.relative_to(_ROOT).as_posix()
        for p in _ROOT.rglob("*.py")
        if loop.search(p.read_text(encoding="utf-8")) and p.name != "procedures.py"
    ]
    assert not offenders, offenders
