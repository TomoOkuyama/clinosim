"""Issue #2995: the admission H&P lists the medications the patient was
taking when admitted — the record's ``home_medications_at_admission``
snapshot — not the patient's medication list at the end of the simulation,
which later encounters (a discharge, death) may have replaced or emptied."""

from __future__ import annotations

import pytest

from clinosim.modules.document.narrative.context import build_narrative_context
from clinosim.modules.document.narrative.renderers.section_builders.patient_history import (
    build_medications_at_home,
)
from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator
from clinosim.types.document import DocumentType

pytestmark = pytest.mark.unit

_APIXABAN = {"drug_name": "Apixaban", "drug_name_ja": "アピキサバン", "route": "PO", "dose": "5mg", "frequency": "bid"}
_METFORMIN = {
    "drug_name": "Metformin",
    "drug_name_ja": "メトホルミン",
    "route": "PO",
    "dose": "500mg",
    "frequency": "bid",
}


def _record(at_admission: list[dict] | None, current: list[dict]) -> dict:
    record: dict = {
        "patient": {"patient_id": "POP-2995", "age": 70, "sex": "F", "current_medications": current},
        "encounters": [{"encounter_id": "ENC-2995", "encounter_type": "inpatient"}],
    }
    if at_admission is not None:
        record["home_medications_at_admission"] = at_admission
    return record


def _home_meds_text(record: dict, country: str) -> str:
    ctx = build_narrative_context(record, record["encounters"][0], DocumentType.ADMISSION_HP, 0, country)
    text, _ = build_medications_at_home(TemplateNarrativeGenerator(), ctx)
    return text


@pytest.mark.parametrize(
    ("country", "apixaban", "none_text"),
    [("US", "Apixaban", "No home medications"), ("JP", "アピキサバン", "常用薬なし")],
)
def test_an_admission_with_an_active_apixaban_prescription_lists_it(
    country: str, apixaban: str, none_text: str
) -> None:
    # The patient's list was emptied after this admission (e.g. by a later death).
    text = _home_meds_text(_record([_APIXABAN, _METFORMIN], current=[]), country)
    assert apixaban in text
    assert none_text not in text


def test_the_admission_snapshot_wins_over_the_end_of_simulation_list() -> None:
    # A drug started at a later discharge is not a home medication of this admission.
    text = _home_meds_text(_record([_APIXABAN], current=[_APIXABAN, _METFORMIN]), "US")
    assert "Apixaban" in text and "Metformin" not in text


def test_no_medications_at_admission_says_none() -> None:
    assert _home_meds_text(_record([], current=[_METFORMIN]), "US") == "No home medications"


def test_a_record_without_the_snapshot_falls_back_to_the_patient_list() -> None:
    assert "Metformin" in _home_meds_text(_record(None, current=[_METFORMIN]), "US")


@pytest.mark.parametrize(("country", "language", "apixaban"), [("US", "en", "Apixaban"), ("JP", "ja", "アピキサバン")])
def test_the_narrative_pass_reads_the_admission_snapshot(country: str, language: str, apixaban: str) -> None:
    """The production context factory (``TemplateNarrativePass._build_context``)
    carries the snapshot to the H&P section builder."""
    from clinosim.modules.document import specs_for_country
    from clinosim.modules.document.narrative.passes import TemplateNarrativePass

    record = _record([_APIXABAN], current=[])
    record["encounters"][0].update(
        {"admission_datetime": "2025-06-01T10:00:00", "discharge_datetime": "2025-06-06T11:00:00"}
    )
    spec = next(s for s in specs_for_country(country.lower()) if s.type_key == "admission_hp")
    ctx = TemplateNarrativePass(cif_dir="/nonexistent", country=country)._build_context(
        record, record["encounters"][0], spec, language
    )
    text, facts = build_medications_at_home(TemplateNarrativeGenerator(), ctx)
    assert apixaban in text
    assert facts == ["ctx.home_medications_at_admission"]
