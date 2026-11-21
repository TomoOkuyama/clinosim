"""An operative note states the indication (Issue #3472).

``preop_diagnosis`` is stamped only on the surgical path; a procedure recorded
by an isolated rule (pacemaker, PCI, ...) or at the bedside carried none, so
the note named no indication. The narrative now falls back to the encounter's
admission / discharge diagnosis, and states "not documented" when the stay has
no diagnosis at all.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from clinosim.codes.snomed_concepts import SURGICAL_PROCEDURE
from clinosim.modules.document.narrative.renderers._shared_helpers import primary_surgical_procedure
from clinosim.modules.document.narrative.renderers.section_builders.op_pn_notes import build_op_findings
from clinosim.types.document import DocumentType, NarrativeContext


class _Gen:
    def _primary_surgical_procedure(self, ctx):
        return primary_surgical_procedure(ctx)


def _ctx(lang: str, *, preop: str = "", postop: str = "", dx: list[dict] | None = None) -> NarrativeContext:
    proc = {
        "encounter_id": "e",
        "category_code": SURGICAL_PROCEDURE,
        "procedure_type": "pacemaker_implant",
        "procedure_code": "0JH606Z",
        "procedure_code_system": "icd-10-pcs",
        "preop_diagnosis": preop,
        "postop_diagnosis": postop,
        "intraop_complications": [],
        "body_site_code": "",
    }
    return NarrativeContext(
        patient=SimpleNamespace(patient_id="p", sex="M", chronic_conditions=[]),
        encounter=SimpleNamespace(encounter_id="e", encounter_type=SimpleNamespace(value="inpatient")),
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
        diagnoses=dx or [],
        procedures=[proc],
        allergies=[],
        document_type=DocumentType.OPERATIVE_NOTE,
        target_lang=lang,
        locale="jp" if lang == "ja" else "us",
    )


_HF = [{"admission_diagnosis_code": "I50.9", "discharge_diagnosis_code": "I50.9"}]


def test_blank_preop_falls_back_to_the_encounter_diagnosis_en() -> None:
    text, facts = build_op_findings(_Gen(), _ctx("en", dx=_HF))
    assert "Pre-operative diagnosis / indication: Heart failure, unspecified (I50.9)" in text
    assert "Post-operative diagnosis" not in text  # same as pre-op: not repeated
    assert "ctx.diagnoses" in facts
    assert "planned procedure" not in text


def test_blank_preop_falls_back_to_the_encounter_diagnosis_ja() -> None:
    text, _ = build_op_findings(_Gen(), _ctx("ja", dx=_HF))
    assert "術前診断・適応：" in text
    assert "I50.9" in text


def test_postop_shown_when_discharge_differs() -> None:
    dx = [{"admission_diagnosis_code": "I50.9", "discharge_diagnosis_code": "I21.9"}]
    text, _ = build_op_findings(_Gen(), _ctx("en", dx=dx))
    assert "Pre-operative diagnosis / indication: Heart failure" in text
    assert "Post-operative diagnosis: Acute myocardial infarction" in text


def test_recorded_preop_is_unchanged() -> None:
    text, _ = build_op_findings(_Gen(), _ctx("en", preop="hip_fracture", dx=_HF))
    assert "Heart failure" not in text
    assert "Pre-operative diagnosis / indication:" in text


@pytest.mark.parametrize("lang,needle", [("en", "Indication: not documented"), ("ja", "適応：記載なし")])
def test_no_diagnosis_states_not_documented(lang: str, needle: str) -> None:
    text, _ = build_op_findings(_Gen(), _ctx(lang))
    assert needle in text
