"""An operative note states what the record holds, not a fixed skeleton (Issue #3549).

Urgency from ``Encounter.priority``, assistants only when recorded, no
transfusion assertion beside an unrecorded blood loss, and a repeat PCI that
names the stent placed before.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from clinosim.codes.snomed_concepts import SURGICAL_PROCEDURE
from clinosim.modules.document.narrative.renderers._shared_helpers import primary_surgical_procedure
from clinosim.modules.document.narrative.renderers.section_builders.op_pn_notes import (
    build_op_blood_loss,
    build_op_course,
    build_op_findings,
    build_op_surgeon,
)
from clinosim.types.document import DocumentType, NarrativeContext


class _Gen:
    def _primary_surgical_procedure(self, ctx):
        return primary_surgical_procedure(ctx)

    def _resolve_procedure_display(self, proc, lang):
        return "PCI"


def _proc(**kw) -> dict:
    base = {
        "procedure_id": "P2",
        "encounter_id": "e",
        "category_code": SURGICAL_PROCEDURE,
        "procedure_type": "coronary_pci",
        "procedure_code": "92920",
        "start_datetime": "2026-07-09T13:00:00",
        "preop_diagnosis": "",
        "intraop_complications": [],
        "body_site_code": "",
        "assistant_ids": [],
        "estimated_blood_loss_ml": None,
    }
    base.update(kw)
    return base


def _ctx(lang: str, *, priority: str = "", procs: list | None = None, prior: list | None = None) -> NarrativeContext:
    return NarrativeContext(
        patient=SimpleNamespace(patient_id="p", sex="M", chronic_conditions=[]),
        encounter=SimpleNamespace(
            encounter_id="e", encounter_type=SimpleNamespace(value="inpatient"), priority=priority
        ),
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
        procedures=procs if procs is not None else [_proc()],
        prior_procedures=prior or [],
        allergies=[],
        document_type=DocumentType.OPERATIVE_NOTE,
        target_lang=lang,
        locale="jp" if lang == "ja" else "us",
    )


@pytest.mark.parametrize(
    ("priority", "en", "ja"),
    [
        ("EM", "emergency procedure performed", "緊急術式を施行"),
        ("UR", "urgent procedure", "準緊急術式"),
        ("EL", "elective procedure", "予定術式を施行"),
    ],
)
def test_urgency_follows_encounter_priority(priority: str, en: str, ja: str) -> None:
    assert en in build_op_course(_Gen(), _ctx("en", priority=priority))[0]
    assert ja in build_op_course(_Gen(), _ctx("ja", priority=priority))[0]


@pytest.mark.parametrize("lang", ["en", "ja"])
def test_no_planned_claim_without_priority(lang: str) -> None:
    text = build_op_course(_Gen(), _ctx(lang, priority="EM"))[0]
    assert "planned" not in text and "予定" not in text
    plain = build_op_course(_Gen(), _ctx(lang))[0]
    assert "planned" not in plain and "予定" not in plain


@pytest.mark.parametrize("lang", ["en", "ja"])
def test_assistants_omitted_when_none_recorded(lang: str) -> None:
    text = build_op_surgeon(_Gen(), _ctx(lang, procs=[_proc(primary_surgeon_id="")]))[0]
    assert "助手" not in text and "Assistants" not in text


def test_assistants_stated_when_recorded() -> None:
    ctx = _ctx("en", procs=[_proc(assistant_ids=["S1"])])
    assert "Assistants:" in build_op_surgeon(_Gen(), ctx)[0]


@pytest.mark.parametrize("lang", ["en", "ja"])
def test_unrecorded_blood_loss_does_not_deny_transfusion(lang: str) -> None:
    text = build_op_blood_loss(_Gen(), _ctx(lang))[0]
    assert "no intraoperative transfusion" not in text and "術中輸血なし" not in text
    assert "not recorded" in text or "記録なし" in text


def test_recorded_transfusion_is_stated_with_unrecorded_blood_loss() -> None:
    tx = {"encounter_id": "e", "procedure_type": "blood_transfusion", "procedure_id": "T"}
    text = build_op_blood_loss(_Gen(), _ctx("en", procs=[_proc(), tx]))[0]
    assert "transfusion given" in text


def test_recorded_blood_loss_still_states_no_transfusion() -> None:
    text = build_op_blood_loss(_Gen(), _ctx("en", procs=[_proc(estimated_blood_loss_ml=200)]))[0]
    assert "200 mL" in text and "no intraoperative transfusion" in text


def test_repeat_pci_names_the_earlier_stent_en() -> None:
    first = _proc(
        procedure_id="P1", encounter_id="e0", start_datetime="2026-06-20T21:00:00", implants_used=["drug-eluting stent"]
    )
    text, facts = build_op_findings(_Gen(), _ctx("en", prior=[first]))
    assert "Prior implant placed on 2026-06-20: Drug-eluting stent" in text
    assert "ctx.prior_procedures" in facts


def test_repeat_pci_names_the_earlier_stent_ja() -> None:
    first = _proc(
        procedure_id="P1", encounter_id="e0", start_datetime="2026-06-20T21:00:00", implants_used=["drug-eluting stent"]
    )
    text, _ = build_op_findings(_Gen(), _ctx("ja", prior=[first]))
    assert "2026-06-20" in text and "前回" in text


def test_first_pci_has_no_prior_line() -> None:
    later = _proc(procedure_id="P3", encounter_id="e9", start_datetime="2026-08-01T10:00:00")
    text, _ = build_op_findings(_Gen(), _ctx("en", prior=[later]))
    assert "Prior" not in text
