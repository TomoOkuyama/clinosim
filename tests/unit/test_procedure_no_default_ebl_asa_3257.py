"""Issue #3257: a procedure record carries blood loss, ASA class and an
anesthesia type only where the procedure has them.

``ProcedureRecord`` used to default ``estimated_blood_loss_ml=300``,
``asa_class=2`` and ``anesthesia_type="general"``, so every non-surgical
record (urinary catheter, echocardiography, PCI, CPAP, newborn screens ...)
asserted 300 mL blood loss and ASA 2. An unknown value is now empty (None /
""), the catalog supplies the anesthesia type, and the bedside / interventional
record names the physician who performed it.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import numpy as np
import pytest

from clinosim.modules.document.narrative.renderers.section_builders import op_pn_notes
from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator
from clinosim.modules.newborn import build_hearing_screen_procedure, build_metabolic_screen_procedure
from clinosim.modules.procedure.engine import (
    age_gated_procedures,
    build_intubation_procedure,
    generate_bedside_procedures,
)
from clinosim.types.clinical import ConditionEvent
from clinosim.types.encounter import Encounter, EncounterType
from clinosim.types.output import CIFPatientRecord
from clinosim.types.patient import PatientProfile
from clinosim.types.procedure import ProcedureRecord

pytestmark = pytest.mark.unit

_CATALOG_ANESTHESIA = {"coronary_pci": "local", "urinary_catheter": "none", "echocardiography": "none"}


def test_record_defaults_are_empty_not_asserted() -> None:
    rec = ProcedureRecord(procedure_id="P1")
    assert rec.estimated_blood_loss_ml is None
    assert rec.asa_class is None
    assert rec.anesthesia_type == ""


@pytest.mark.parametrize("country", ["US", "JP"])
def test_bedside_and_interventional_records_have_no_ebl_asa_and_name_the_operator(country: str) -> None:
    seen: set[str] = set()
    for seed in range(40):
        for proc in generate_bedside_procedures(
            "PAT-1",
            f"ENC-{seed}",
            "acute_mi",
            datetime(2026, 4, 6, 10, 0),
            "severe",
            np.random.default_rng(seed),
            country,
            performer_id="STAFF-ATT-1",
        ):
            seen.add(proc.procedure_type)
            assert proc.estimated_blood_loss_ml is None
            assert proc.asa_class is None
            assert proc.primary_surgeon_id == "STAFF-ATT-1"
            if proc.procedure_type in _CATALOG_ANESTHESIA:
                assert proc.anesthesia_type == _CATALOG_ANESTHESIA[proc.procedure_type]
            assert proc.anesthesia_type
    assert "coronary_pci" in seen


def test_age_gated_procedure_uses_catalog_anesthesia_and_operator() -> None:
    rules = [{"procedure": "lumbar_puncture", "min_age_days": 8, "max_age_days": 21}]
    (proc,) = age_gated_procedures(
        "PAT-2", "ENC-2", rules, 10, datetime(2026, 4, 6, 10, 0), 0, "US", performer_id="STAFF-ED-1"
    )
    assert proc.anesthesia_type == "local"
    assert proc.estimated_blood_loss_ml is None
    assert proc.asa_class is None
    assert proc.primary_surgeon_id == "STAFF-ED-1"


def test_intubation_names_the_operator() -> None:
    proc = build_intubation_procedure(
        "PAT-3", "ENC-3", datetime(2026, 4, 6, 10, 0), "JP", "PROC-PAT-3-AIR00", performer_id="STAFF-ATT-3"
    )
    assert proc.anesthesia_type == "sedation"
    assert proc.estimated_blood_loss_ml is None
    assert proc.asa_class is None
    assert proc.primary_surgeon_id == "STAFF-ATT-3"


def _newborn_record() -> CIFPatientRecord:
    admit = datetime(2026, 6, 1, 10, 0)
    pid = "POP-000001-BABY"
    return CIFPatientRecord(
        patient=PatientProfile(patient_id=pid, sex="M", age=0),
        encounters=[
            Encounter(
                encounter_id=f"ENC-{pid}-01",
                patient_id=pid,
                encounter_type=EncounterType.INPATIENT,
                admission_datetime=admit,
                discharge_datetime=admit + timedelta(days=5),
            )
        ],
        condition_event=ConditionEvent(
            condition_id=f"COND-{pid}-BIRTH", condition_type="newborn_birth", ground_truth_diseases=["Z38.0"]
        ),
    )


@pytest.mark.parametrize("country", ["US", "JP"])
def test_newborn_screens_are_done_without_anesthesia(country: str) -> None:
    hearing = build_hearing_screen_procedure(_newborn_record())
    metabolic = build_metabolic_screen_procedure(_newborn_record(), country)
    for proc in (hearing, metabolic):
        assert proc is not None
        assert proc.anesthesia_type == "none"
        assert proc.estimated_blood_loss_ml is None
        assert proc.asa_class is None


# ---------------------------------------------------------------------------
# Notes: an empty value is printed as not recorded, never as 0 mL / local.
# ---------------------------------------------------------------------------

_SURGICAL = "387713003"


def _ctx(proc: ProcedureRecord, lang: str) -> SimpleNamespace:
    return SimpleNamespace(
        target_lang=lang,
        locale="JP" if lang == "ja" else "US",
        encounter=SimpleNamespace(encounter_id=proc.encounter_id),
        procedures=[proc],
        related_procedure_id=proc.procedure_id,
        roster_map={},
    )


def _proc(**kw: object) -> ProcedureRecord:
    base: dict = dict(
        procedure_id="PROC-1",
        encounter_id="ENC-1",
        procedure_type="coronary_pci",
        procedure_code="92920",
        procedure_code_us="92920",
        procedure_code_jp="K546",
        category_code=_SURGICAL,
        start_datetime=datetime(2026, 4, 6, 12, 0),
    )
    base.update(kw)
    return ProcedureRecord(**base)


@pytest.mark.parametrize(("lang", "expected"), [("en", "without anesthesia"), ("ja", "麻酔なし")])
def test_procedure_note_renders_none_as_no_anesthesia(lang: str, expected: str) -> None:
    text, _ = op_pn_notes.build_pn_analgesia(TemplateNarrativeGenerator(), _ctx(_proc(anesthesia_type="none"), lang))
    assert expected in text
    assert "局所" not in text and "local" not in text.lower()


@pytest.mark.parametrize("lang", ["en", "ja"])
def test_procedure_note_unknown_anesthesia_is_not_documented(lang: str) -> None:
    text, _ = op_pn_notes.build_pn_analgesia(TemplateNarrativeGenerator(), _ctx(_proc(anesthesia_type=""), lang))
    assert text in {"Analgesia: not documented.", "麻酔・鎮静: 記録なし。"}


@pytest.mark.parametrize("lang", ["en", "ja"])
def test_operative_note_without_ebl_or_asa_prints_neither(lang: str) -> None:
    proc = _proc(anesthesia_type="local")
    gen = TemplateNarrativeGenerator()
    anes, _ = op_pn_notes.build_op_anesthesia(gen, _ctx(proc, lang))
    assert "ASA" not in anes
    ebl, _ = op_pn_notes.build_op_blood_loss(gen, _ctx(proc, lang))
    assert "mL" not in ebl
    assert ("not recorded" in ebl) if lang == "en" else ("記録なし" in ebl)


def test_operative_note_prints_recorded_ebl_and_asa() -> None:
    proc = _proc(anesthesia_type="general", asa_class=3, estimated_blood_loss_ml=250)
    gen = TemplateNarrativeGenerator()
    anes, _ = op_pn_notes.build_op_anesthesia(gen, _ctx(proc, "en"))
    assert "ASA class 3" in anes
    ebl, _ = op_pn_notes.build_op_blood_loss(gen, _ctx(proc, "en"))
    assert "250 mL" in ebl


def test_every_catalog_anesthesia_renders_in_both_notes() -> None:
    from clinosim.codes.procedures import bedside_procedures, catalog_procedure_types, procedure_anesthesia
    from clinosim.locale.loader import load_narrative_labels

    labels = load_narrative_labels()
    values = {procedure_anesthesia(t) for t in catalog_procedure_types()} - {""}
    assert {str(e["anesthesia"]) for e in bedside_procedures()} <= values
    for value in values:
        assert value in labels["op_anesthesia_type"], value
        assert value == "none" or value in labels["pn_analgesia_type"], value
