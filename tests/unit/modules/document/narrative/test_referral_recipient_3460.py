"""A referral letter names the same institution in the narrative and FHIR, is
written only when care moves to another provider, and its remarks are separated
sentences (Issue #3460)."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from clinosim.modules.document import engine
from clinosim.modules.document.narrative.renderers.section_builders import jp_clins
from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator
from clinosim.modules.document.referral_recipient import (
    format_referral_destination_text,
    is_transfer_disposition,
    pick_external_hospital,
    referral_recipients_config,
)
from clinosim.types.document import DocumentType, NarrativeContext

pytestmark = pytest.mark.unit


def _ctx(patient_id: str, encounter_id: str, lang: str = "ja", code_status: str = "") -> NarrativeContext:
    return NarrativeContext(
        patient=SimpleNamespace(patient_id=patient_id, sex="male", age=70, chronic_conditions=[]),
        encounter={
            "encounter_id": encounter_id,
            "admission_datetime": "2026-01-10T10:00:00",
            "discharge_datetime": "2026-01-18T10:00:00",
            "discharge_disposition": "snf",
        },
        encounter_type=None,
        disease_protocol=None,
        encounter_protocol=None,
        clinical_course_archetype="",
        severity="moderate",
        day_index=7,
        los_days=8,
        vitals=[],
        lab_results=[],
        medications=[],
        diagnoses=[],
        procedures=[],
        allergies=[],
        document_type=DocumentType.REFERRAL_NOTE,
        target_lang=lang,
        locale="jp" if lang == "ja" else "us",
        authored_datetime=datetime(2026, 1, 18, 10, 0),
        code_status=code_status,
    )


@pytest.fixture(scope="module")
def gen() -> TemplateNarrativeGenerator:
    return TemplateNarrativeGenerator()


def test_narrative_names_the_institution_the_fhir_composition_names(gen) -> None:
    from clinosim.modules.output.fhir_r4.documents.composition import _build_composition

    for i in range(40):
        pid, eid = f"POP-{i:06d}", f"ENC-{i:04d}"
        text, _ = jp_clins.build_referral_destination(gen, _ctx(pid, eid))
        entry = pick_external_hospital(pid, eid, "jp")
        assert entry is not None and entry["name"] in text
        assert "御担当医" in text and "他院" not in text
        doc = {
            "document_id": f"doc-{eid}-02",
            "loinc_code": "57133-1",
            "format_type": "composition",
            "patient_id": pid,
            "encounter_id": eid,
            "authored_datetime": "2026-01-20T10:00:00",
            "language": "ja",
            "period_start": "2026-01-15T09:00:00",
            "period_end": "2026-01-20T10:00:00",
        }
        comp = _build_composition(doc, {"referral_destination": text}, "ja", country="JP")
        top = {s["code"]["coding"][0]["code"]: s for s in comp["section"]}
        assert text in top["910"]["text"]["div"]
        assert top["910"]["entry"] == [{"reference": f"Organization/{entry['id']}"}]


def test_the_recipient_is_a_hospital_not_a_clinic() -> None:
    from clinosim.locale.loader import load_external_organizations

    types = {e["id"]: e["type"] for e in load_external_organizations("jp")}
    allowed = set(referral_recipients_config().recipient_types)
    for i in range(200):
        entry = pick_external_hospital(f"P{i}", f"E{i}", "jp")
        assert entry is not None and types[entry["id"]] in allowed


def test_a_country_without_a_catalog_names_no_recipient(gen) -> None:
    assert pick_external_hospital("P1", "E1", "us") is None
    text, facts = jp_clins.build_referral_destination(gen, _ctx("P1", "E1", "en"))
    assert text and facts == []


def test_the_destination_sentence_in_both_languages() -> None:
    entry = {"id": "x", "name": "東京中央総合病院"}
    assert format_referral_destination_text(entry, "ja") == "紹介先:東京中央総合病院 御担当医 先生 御侍史。"
    assert format_referral_destination_text(entry, "en") == "Referral destination: 東京中央総合病院, Dear Doctor."


@pytest.mark.parametrize(
    ("disposition", "planned"),
    [("snf", True), ("hosp", True), ("other-hcf", True), ("home", False), ("exp", False), ("", False)],
)
def test_a_letter_is_planned_only_for_a_transfer_of_care(disposition: str, planned: bool) -> None:
    f = engine._EncounterFacts(
        record=None,
        encounter={"discharge_disposition": disposition},
        encounter_id="ENC-1",
        pid="P1",
        admission_dt=datetime(2026, 1, 10),
        discharge_dt=datetime(2026, 1, 18),
        los_days=8,
        config=None,
    )
    assert bool(engine._plan_discharge_referral(None, f)) is planned
    assert is_transfer_disposition(disposition) is planned


def test_a_stay_still_in_progress_has_no_letter() -> None:
    f = engine._EncounterFacts(
        record=None,
        encounter={"discharge_disposition": "snf"},
        encounter_id="ENC-1",
        pid="P1",
        admission_dt=datetime(2026, 1, 10),
        discharge_dt=None,
        los_days=0,
        config=None,
    )
    assert engine._plan_discharge_referral(None, f) == []


def test_remarks_are_separate_sentences(gen) -> None:
    for lang in ("ja", "en"):
        text, _ = jp_clins.build_referral_remarks(gen, _ctx("P1", "E1", lang, code_status="304251008"))
        assert "）コード" not in text and ")Code" not in text
        assert text.count("。" if lang == "ja" else ". ") >= 1
