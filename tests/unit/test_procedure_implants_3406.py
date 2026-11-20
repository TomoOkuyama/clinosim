"""Procedures that leave a device record it and the operative note states it (Issue #3406)."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from clinosim.codes.procedures import procedure_implants
from clinosim.locale.loader import load_narrative_op_implants
from clinosim.modules.document.narrative.renderers.section_builders.op_pn_notes import build_op_equipment
from clinosim.modules.procedure.engine import _BEDSIDE_PROCEDURES, _bedside_record, simulate_surgery

_IMPLANT_PROCEDURES = ("coronary_pci", "pacemaker_implant", "Total knee arthroplasty", "ORIF with volar locking plate")


@pytest.mark.parametrize("proc_type", _IMPLANT_PROCEDURES)
def test_implant_procedure_has_catalog_implants(proc_type):
    assert procedure_implants(proc_type)


def test_non_implant_procedure_has_none():
    assert procedure_implants("central_line") == ()
    assert procedure_implants("laparoscopic appendectomy") == ()


def test_every_implant_slug_has_en_and_ja():
    table = load_narrative_op_implants()
    for slug in (
        "compression hip screw",
        "drug-eluting stent",
        "pacing leads",
        "pedicle screw and rod construct",
        *[s for t in _IMPLANT_PROCEDURES for s in procedure_implants(t)],
    ):
        assert table[slug].get("en") and table[slug].get("ja"), slug


@pytest.mark.parametrize(
    "proc_type,en,ja",
    [
        ("coronary_pci", "Drug-eluting stent", "薬剤溶出性ステント"),
        ("pacemaker_implant", "Pacemaker generator", "ペースメーカー本体"),
    ],
)
@pytest.mark.parametrize("lang", ["en", "ja"])
def test_bedside_implant_procedure_note_names_device(proc_type, en, ja, lang, monkeypatch):
    spec = next(p for p in _BEDSIDE_PROCEDURES if p[0] == proc_type)
    rec = _bedside_record("P1", "E1", proc_type, spec, spec[1], datetime(2024, 1, 1), 60, 0, "x", "D1")
    assert rec.implants_used
    gen = SimpleNamespace(_primary_surgical_procedure=lambda ctx: rec)
    ctx = SimpleNamespace(target_lang=lang)
    text, _ = build_op_equipment(gen, ctx)
    assert (en if lang == "en" else ja) in text
    assert "none" not in text.lower() and "なし" not in text


def test_fall_from_height_default_fixation_records_spinal_implant():
    from pathlib import Path

    import numpy as np
    import yaml

    import clinosim

    path = Path(clinosim.__file__).parent / "modules/disease/reference_data/fall_from_height.yaml"
    proc = yaml.safe_load(path.read_text())["procedure"]
    default = {k: v for k, v in proc.items() if k != "by_diagnosis"}
    patient = SimpleNamespace(patient_id="P1", age=40, chronic_conditions=[])
    rec, _ = simulate_surgery(
        patient,
        "fall_from_height",
        "E1",
        datetime(2024, 1, 1),
        SimpleNamespace(procedure=default),
        np.random.default_rng(1),
        "US",
    )
    assert rec.implants_used == ["pedicle screw and rod construct"]
