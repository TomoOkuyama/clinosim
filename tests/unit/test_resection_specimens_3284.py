"""Issue #3284: a resection records the specimen it sends to pathology.

``ProcedureRecord.specimens_sent`` was never populated, so every
appendectomy / cholecystectomy operative note said no tissue was sent to
pathology and the FHIR output had no surgical Specimen. The procedure catalog
now names the specimen of each resection (``specimens``), the procedure engine
copies it into the record, the operative / procedure notes list it in the note
language, and the FHIR output emits one Specimen per entry, collected by the
Procedure.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import numpy as np
import pytest

from clinosim.codes import display as code_display
from clinosim.codes.procedures import catalog_procedure_types, procedure_specimens
from clinosim.codes.snomed import snomed_for
from clinosim.locale.loader import load_narrative_labels
from clinosim.modules.disease.protocol import load_disease_protocol
from clinosim.modules.document.narrative.renderers.section_builders import op_pn_notes
from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator
from clinosim.modules.output.fhir_r4.lib.context import BundleContext
from clinosim.modules.output.fhir_r4.lib.inline_bb import _bb_procedures
from clinosim.modules.output.fhir_r4.procedures.surgical_specimens import (
    PROCEDURE_REFERENCE_EXTENSION,
    _bb_procedure_specimens,
)
from clinosim.modules.procedure.engine import generate_bedside_procedures, simulate_surgery
from clinosim.types.patient import PatientProfile
from clinosim.types.procedure import ProcedureRecord

pytestmark = pytest.mark.unit

_EXPECTED = {
    "laparoscopic appendectomy": ("appendix", "421615004"),
    "laparoscopic cholecystectomy": ("gallbladder", "309205005"),
    "bowel_resection": ("colon_segment", "309488006"),
}


# --- catalog ---------------------------------------------------------------


@pytest.mark.parametrize(("proc_type", "expected"), list(_EXPECTED.items()))
def test_catalog_names_the_resection_specimen(proc_type: str, expected: tuple[str, str]) -> None:
    slug, sct = expected
    assert procedure_specimens(proc_type) == (slug,)
    assert snomed_for("specimen_type", slug) == sct


def test_non_resections_send_no_specimen() -> None:
    for proc_type in ("ORIF", "hemiarthroplasty", "Total knee arthroplasty", "coronary_pci", "wound_debridement"):
        assert procedure_specimens(proc_type) == ()
    assert procedure_specimens("") == ()


def test_every_catalog_specimen_is_coded_and_labelled() -> None:
    from clinosim.codes.procedures import _catalog

    labels = load_narrative_labels()["surgical_specimen"]
    table = _catalog()["specimens"]
    assert set(table) == set(_EXPECTED)
    for proc_type in table:
        assert proc_type in catalog_procedure_types(), proc_type
        for slug in procedure_specimens(proc_type):
            code = snomed_for("specimen_type", slug)
            assert code, slug
            assert code_display("snomed-ct", code, "en"), code
            assert code_display("snomed-ct", code, "ja"), code
            assert labels[slug]["en"] and labels[slug]["ja"], slug


# --- engine ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("disease_id", "slug"), [("acute_appendicitis", "appendix"), ("acute_cholecystitis", "gallbladder")]
)
@pytest.mark.parametrize("country", ["US", "JP"])
def test_simulated_resection_records_its_specimen(disease_id: str, slug: str, country: str) -> None:
    patient = PatientProfile(patient_id="PAT-1", age=40, sex="F")
    record, _ = simulate_surgery(
        patient=patient,
        disease_id=disease_id,
        encounter_id="ENC-1",
        admission_time=datetime(2026, 4, 6, 14, 0),
        protocol=load_disease_protocol(disease_id),
        rng=np.random.default_rng(7),
        country=country,
        surgeon_id="DR-1",
    )
    assert record.specimens_sent == [slug]


def test_specimen_adds_no_rng_draw(monkeypatch: pytest.MonkeyPatch) -> None:
    """The specimen is catalog data: the surgery consumes the same draws and
    builds the same record whether or not the catalog names a specimen."""
    import clinosim.modules.procedure.engine as engine

    def run() -> tuple[ProcedureRecord, float]:
        rng = np.random.default_rng(11)
        record, _ = simulate_surgery(
            patient=PatientProfile(patient_id="PAT-1", age=40, sex="F"),
            disease_id="acute_appendicitis",
            encounter_id="ENC-1",
            admission_time=datetime(2026, 4, 6, 14, 0),
            protocol=load_disease_protocol("acute_appendicitis"),
            rng=rng,
            country="US",
        )
        return record, rng.random()

    with_specimen, next_draw = run()
    monkeypatch.setattr(engine, "procedure_specimens", lambda _t: ())
    without_specimen, next_draw_without = run()
    assert next_draw == next_draw_without
    assert with_specimen.specimens_sent == ["appendix"]
    without_specimen.specimens_sent = ["appendix"]
    assert with_specimen == without_specimen


def test_bedside_bowel_resection_records_the_colon_segment() -> None:
    found = False
    for seed in range(60):
        for proc in generate_bedside_procedures(
            "PAT-2",
            f"ENC-{seed}",
            "ileus",
            datetime(2026, 4, 6, 10, 0),
            "severe",
            np.random.default_rng(seed),
            "JP",
            performer_id="DR-2",
        ):
            if proc.procedure_type == "bowel_resection":
                found = True
                assert proc.specimens_sent == ["colon_segment"]
            else:
                assert proc.specimens_sent == []
    assert found


# --- notes -----------------------------------------------------------------


def _proc(**kw: object) -> ProcedureRecord:
    base: dict = dict(
        procedure_id="PROC-PAT-1-001",
        patient_id="PAT-1",
        encounter_id="ENC-1",
        procedure_type="laparoscopic appendectomy",
        procedure_code="44970",
        procedure_code_us="44970",
        procedure_code_jp="K718-2",
        category_code="387713003",
        body_site_code="66754008",
        primary_surgeon_id="DR-1",
        start_datetime=datetime(2026, 4, 6, 14, 0),
        end_datetime=datetime(2026, 4, 6, 15, 0),
        specimens_sent=["appendix"],
    )
    base.update(kw)
    return ProcedureRecord(**base)


def _note_ctx(proc: ProcedureRecord, lang: str) -> SimpleNamespace:
    return SimpleNamespace(
        target_lang=lang,
        locale="JP" if lang == "ja" else "US",
        encounter=SimpleNamespace(encounter_id=proc.encounter_id),
        procedures=[proc],
        related_procedure_id=proc.procedure_id,
        roster_map={},
    )


@pytest.mark.parametrize(
    ("lang", "expected"),
    [("en", "Specimens sent to pathology: Appendix"), ("ja", "摘出臓器・組織：虫垂（病理検査へ提出）")],
)
def test_operative_note_lists_the_specimen(lang: str, expected: str) -> None:
    text, _ = op_pn_notes.build_op_specimens(TemplateNarrativeGenerator(), _note_ctx(_proc(), lang))
    assert text == expected


@pytest.mark.parametrize(("lang", "expected"), [("en", "Resected colon segment"), ("ja", "切除結腸")])
def test_procedure_note_lists_the_specimen(lang: str, expected: str) -> None:
    proc = _proc(procedure_type="bowel_resection", specimens_sent=["colon_segment"])
    text, _ = op_pn_notes.build_pn_specimens(TemplateNarrativeGenerator(), _note_ctx(proc, lang))
    assert expected in text
    assert "colon_segment" not in text


@pytest.mark.parametrize("lang", ["en", "ja"])
def test_operative_note_without_specimen_says_none(lang: str) -> None:
    proc = _proc(procedure_type="ORIF", specimens_sent=[])
    text, _ = op_pn_notes.build_op_specimens(TemplateNarrativeGenerator(), _note_ctx(proc, lang))
    assert text in {"Specimens sent to pathology: none", "摘出臓器・組織：なし"}


# --- FHIR ------------------------------------------------------------------


def _bundle_ctx(proc: ProcedureRecord, country: str) -> BundleContext:
    from dataclasses import asdict

    record = {"procedures": [asdict(proc)], "encounters": []}
    for p in record["procedures"]:
        for key in ("start_datetime", "end_datetime"):
            p[key] = p[key].isoformat()
    return BundleContext(
        record=record,
        country=country,
        roster_map={},
        hospital_config={},
        patient_data={"patient_id": "PAT-1"},
        patient_id="PAT-1",
        is_readmission=False,
        prior_encounter_id=None,
        primary_dx_code="",
        admit_dx_code="",
        admit_dx_system="icd-10",
        primary_enc_id="ENC-1",
        patient_sex="F",
    )


@pytest.mark.parametrize(("country", "text"), [("US", "Appendix"), ("JP", "虫垂")])
def test_fhir_specimen_is_collected_by_the_procedure(country: str, text: str) -> None:
    ctx = _bundle_ctx(_proc(), country)
    (procedure,) = [r for r in _bb_procedures(ctx) if r["resourceType"] == "Procedure"]
    (specimen,) = _bb_procedure_specimens(ctx)
    assert specimen["resourceType"] == "Specimen"
    assert specimen["subject"] == procedure["subject"]
    coding = specimen["type"]["coding"][0]
    assert coding["code"] == "421615004"
    assert coding["display"] == "Specimen from appendix obtained by appendectomy"
    assert specimen["type"]["text"] == text
    collection = specimen["collection"]
    assert collection["collectedDateTime"] == procedure["performedPeriod"]["end"]
    assert collection["bodySite"] == procedure["bodySite"][0]
    assert collection["collector"] == {"reference": "Practitioner/DR-1"}
    (ext,) = collection["extension"]
    assert ext["url"] == PROCEDURE_REFERENCE_EXTENSION
    assert ext["valueReference"] == {"reference": f"Procedure/{procedure['id']}"}
    assert specimen["id"].startswith("spec-")


def test_fhir_emits_no_specimen_without_one_sent() -> None:
    assert _bb_procedure_specimens(_bundle_ctx(_proc(specimens_sent=[]), "US")) == []
