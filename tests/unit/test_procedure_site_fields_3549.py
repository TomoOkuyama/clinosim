"""Site details and per-procedure durations of a procedure record (Issues #3549, #3550).

Side of paired-site operations, access site and target vessel of a PCI, the
insertion vein of a central line, and bedside durations from the procedure
catalog; all drawn from a dedicated sub-seed so no shared stream moves.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from types import SimpleNamespace

import numpy as np
import pytest

from clinosim.codes import procedures as catalog_mod
from clinosim.codes.snomed import snomed_map
from clinosim.modules.disease.laterality import stroke_lesion_side
from clinosim.modules.document.narrative.renderers._shared_helpers import primary_surgical_procedure
from clinosim.modules.document.narrative.renderers.section_builders.op_pn_notes import (
    build_op_findings,
    build_pn_procedure_name,
)
from clinosim.modules.imaging.engine import imaging_laterality
from clinosim.modules.output.fhir_r4.procedures.procedures import _build_procedure
from clinosim.modules.procedure.details import procedure_details
from clinosim.modules.procedure.engine import build_intubation_procedure, generate_bedside_procedures
from clinosim.types.document import DocumentType, NarrativeContext

pytestmark = pytest.mark.unit

_T0 = datetime(2026, 3, 1, 8, 0)


def _bedside(disease: str, enc: str, seed: int = 1, severity: str = "severe"):
    rng = np.random.default_rng(seed)
    return generate_bedside_procedures("P", enc, disease, _T0, severity, rng, "US", performer_id="D1"), rng


def test_pci_records_target_vessel_and_access_site():
    vessels, accesses = set(), set()
    for i in range(80):
        d = procedure_details("coronary_pci", f"ENC-{i}")
        assert d.target_vessel in snomed_map("coronary_vessel").values()
        assert d.access_site in snomed_map("arterial_access_site").values()
        assert d.laterality == ""
        vessels.add(d.target_vessel)
        accesses.add(d.access_site)
    assert len(vessels) >= 3 and len(accesses) == 2


def test_central_line_records_an_insertion_vein_and_side():
    veins = Counter()
    for i in range(120):
        d = procedure_details("central_line", f"ENC-{i}")
        assert d.body_site_code in snomed_map("central_vein").values()
        assert d.laterality in ("left", "right")
        veins[d.body_site_code] += 1
    assert len(veins) == 3


def test_details_are_deterministic_and_untouched_types_are_empty():
    assert procedure_details("central_line", "ENC-9") == procedure_details("central_line", "ENC-9")
    empty = procedure_details("urinary_catheter", "ENC-9")
    assert (empty.laterality, empty.access_site, empty.target_vessel, empty.body_site_code) == ("", "", "", "")


def test_stroke_craniotomy_is_on_the_stay_lesion_side():
    for i in range(30):
        enc = f"ENC-{i}"
        assert procedure_details("craniotomy_hematoma_evacuation", enc, "hemorrhagic_stroke").laterality == (
            stroke_lesion_side(enc)
        )


def test_non_stroke_craniotomy_draws_a_side_from_both():
    sides = {
        procedure_details("craniotomy_hematoma_evacuation", f"ENC-{i}", "subdural_hematoma").laterality
        for i in range(40)
    }
    assert sides == {"left", "right"}


def test_orthopedic_side_is_the_side_the_stay_imaging_uses():
    for i in range(30):
        enc = f"ENC-{i}"
        assert procedure_details("hemiarthroplasty", enc, "hip_fracture").laterality == imaging_laterality(enc, "hip")
        assert procedure_details("Total knee arthroplasty", enc, "elective_knee_arthroplasty").laterality == (
            imaging_laterality(enc, "knee")
        )
        assert procedure_details("ORIF with volar locking plate", enc).laterality == imaging_laterality(enc, "wrist")


def test_bedside_pci_and_central_line_carry_the_details():
    procs = []
    for i in range(60):
        procs += _bedside("acute_mi", f"ENC-PCI-{i}")[0] + _bedside("sepsis", f"ENC-CL-{i}")[0]
    pci = [p for p in procs if p.procedure_type == "coronary_pci"]
    lines = [p for p in procs if p.procedure_type == "central_line"]
    assert pci and lines
    assert all(p.target_vessel and p.access_site for p in pci)
    assert all(p.body_site_code in snomed_map("central_vein").values() and p.laterality for p in lines)


def test_recording_details_does_not_move_the_shared_stream():
    """The durations come from one draw per procedure whatever the catalog says."""
    after, _ = {}, None
    for label, cleared in (("catalog", False), ("default", True)):
        if cleared:
            catalog_mod._entries.cache_clear()
            original = catalog_mod._catalog

            def _no_durations():
                data = original()
                return {
                    **data,
                    "bedside": [{k: v for k, v in e.items() if k != "duration_minutes"} for e in data["bedside"]],
                }

            catalog_mod._catalog = _no_durations  # type: ignore[assignment]
        try:
            from clinosim.modules.procedure import engine

            rng = np.random.default_rng(7)
            engine.generate_bedside_procedures("P", "ENC-S", "sepsis", _T0, "severe", rng, "US", performer_id="D1")
            after[label] = rng.bit_generator.state
        finally:
            if cleared:
                catalog_mod._catalog = original  # type: ignore[assignment]
                catalog_mod._entries.cache_clear()
    assert after["catalog"] == after["default"]


def test_bedside_durations_are_per_procedure():
    durations: dict[str, list[int]] = {}
    for i in range(400):
        for disease in ("sepsis", "acute_mi", "heart_failure_exacerbation", "ileus"):
            for p in _bedside(disease, f"ENC-{disease}-{i}", seed=i)[0]:
                durations.setdefault(p.procedure_type, []).append(p.duration_minutes)
    for quick in ("urinary_catheter", "nasogastric_tube"):
        assert durations[quick] and max(durations[quick]) < 15, quick
    assert 15 <= np.mean(durations["central_line"]) <= 35
    assert np.mean(durations["coronary_pci"]) > 40


def test_intubation_takes_a_few_minutes_not_thirty():
    proc = build_intubation_procedure("P", "ENC", _T0, "US", "PROC-1", performer_id="D1")
    assert proc.duration_minutes < 15
    assert (proc.end_datetime - proc.start_datetime).total_seconds() / 60 == proc.duration_minutes


def test_every_catalog_duration_is_well_formed():
    seen = 0
    for entry in catalog_mod.bedside_procedures():
        spec = catalog_mod.procedure_duration(str(entry["type"]))
        if spec is None:
            continue
        seen += 1
        assert spec.mean > 0 and spec.sd > 0 and 0 < spec.min <= spec.mean
        assert spec.max is None or spec.max >= spec.mean
    assert seen >= 20


# --------------------------------------------------------------------------- rendering


class _Gen:
    def _primary_surgical_procedure(self, ctx):
        return primary_surgical_procedure(ctx)

    def _resolve_procedure_display(self, proc, lang):
        return "procedure"


def _ctx(lang: str, proc: dict, doc: DocumentType) -> NarrativeContext:
    return NarrativeContext(
        patient=SimpleNamespace(patient_id="p", sex="M", chronic_conditions=[]),
        encounter=SimpleNamespace(encounter_id="e", encounter_type=SimpleNamespace(value="inpatient"), priority=""),
        encounter_type=SimpleNamespace(value="inpatient"),
        disease_protocol=None,
        encounter_protocol=None,
        clinical_course_archetype="",
        severity="moderate",
        day_index=3,
        los_days=7,
        vitals=[],
        lab_results=[],
        medications=[],
        diagnoses=[],
        procedures=[proc],
        prior_procedures=[],
        allergies=[],
        document_type=doc,
        target_lang=lang,
        locale="jp" if lang == "ja" else "us",
        related_procedure_id=proc["procedure_id"],
    )


def _op(**kw) -> dict:
    base = {
        "procedure_id": "P1",
        "encounter_id": "e",
        "category_code": "387713003",
        "procedure_type": "coronary_pci",
        "procedure_code": "92920",
        "start_datetime": "2026-07-09T13:00:00",
        "preop_diagnosis": "",
        "intraop_complications": [],
        "body_site_code": "41801008",
        "assistant_ids": [],
    }
    base.update(kw)
    return base


@pytest.mark.parametrize(
    ("lang", "needles"),
    [
        ("en", ["Target vessel: left anterior descending artery (LAD)", "Access site: radial artery"]),
        ("ja", ["治療対象血管：左前下行枝（LAD）", "アクセス部位：橈骨動脈"]),
    ],
)
def test_pci_note_names_vessel_and_access(lang, needles):
    proc = _op(target_vessel="59438005", access_site="45631007")
    text = build_op_findings(_Gen(), _ctx(lang, proc, DocumentType.OPERATIVE_NOTE))[0]
    for needle in needles:
        assert needle in text


@pytest.mark.parametrize(("lang", "needle"), [("en", "Side: left"), ("ja", "側：左")])
def test_craniotomy_note_states_the_side(lang, needle):
    proc = _op(procedure_type="craniotomy_hematoma_evacuation", body_site_code="12738006", laterality="left")
    assert needle in build_op_findings(_Gen(), _ctx(lang, proc, DocumentType.OPERATIVE_NOTE))[0]


def test_note_without_recorded_site_details_states_none():
    text = build_op_findings(_Gen(), _ctx("en", _op(), DocumentType.OPERATIVE_NOTE))[0]
    assert "Side:" not in text and "Target vessel" not in text and "Access site" not in text


@pytest.mark.parametrize(("lang", "needle"), [("en", "right internal jugular vein"), ("ja", "内頸静脈（右）")])
def test_central_line_note_names_vein_and_side(lang, needle):
    proc = {
        "procedure_id": "P1",
        "procedure_type": "central_line",
        "procedure_code": "36556",
        "procedure_code_us": "36556",
        "procedure_code_jp": "G005-2",
        "body_site_code": "12123001",
        "laterality": "right",
    }
    assert needle in build_pn_procedure_name(_Gen(), _ctx(lang, proc, DocumentType.PROCEDURE_NOTE))[0]


# --------------------------------------------------------------------------- FHIR


def _fhir(**kw):
    proc = {
        "procedure_id": "PROC-P-001",
        "patient_id": "P",
        "encounter_id": "ENC-1",
        "procedure_type": "coronary_pci",
        "procedure_code": "92920",
        "procedure_code_us": "92920",
        "procedure_code_jp": "K546",
        "start_datetime": "2026-07-09T13:00:00",
        "end_datetime": "2026-07-09T14:00:00",
        "body_site_code": "41801008",
        "outcome_code": "385669000",
    }
    proc.update(kw)
    return _build_procedure(proc, "P", 0, "US")


def test_fhir_body_site_carries_vessel_and_laterality_qualifier():
    res = _fhir(target_vessel="59438005", laterality="left", access_site="7657000")
    codes = [s["coding"][0]["code"] for s in res["bodySite"]]
    assert codes == ["41801008", "59438005", "7771000"]
    assert res["note"][0]["text"] == "Access site: femoral artery"


def test_fhir_without_site_details_is_unchanged():
    res = _fhir()
    assert [s["coding"][0]["code"] for s in res["bodySite"]] == ["41801008"]
    assert "note" not in res
