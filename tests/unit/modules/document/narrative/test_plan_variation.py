"""Plan section variation across visits (Issue #1180).

Before the fix, `_build_outpatient_plan` short-circuited to the YAML
`outpatient_soap_template.plan_<lang>` (a per-condition constant),
which made the SOAP Plan section byte-identical across every
outpatient visit for 92.1% of patients. The fallback path composed
from `current_medications + today_rx + today_procs + follow_up` but
`follow_up` also emitted a constant sentinel.

Issue #2287: a patient with a chronic follow-up schedule gets the
scheduled interval. Issue #3465 removed the 28 / 60 / 90 day rotation
(an interval nothing scheduled); a visit with no schedule states none.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from clinosim.modules.document.narrative.template_generator import (
    TemplateNarrativeGenerator,
)
from clinosim.types.document import DocumentType, NarrativeContext
from clinosim.types.patient import PatientProfile


def _mk_ctx(chronic_code: str, encounter_id: str, patient_id: str = "pt-plan") -> NarrativeContext:
    p = PatientProfile(patient_id=patient_id)
    p.chronic_conditions = [SimpleNamespace(code=chronic_code)]
    p.current_medications = []
    p.age = 65
    p.sex = "M"
    enc = SimpleNamespace(
        encounter_id=encounter_id,
        admission_datetime=datetime(2026, 8, 1, 10, 0),
    )
    return NarrativeContext(
        patient=p,
        encounter=enc,
        encounter_type=None,
        disease_protocol=None,
        encounter_protocol=None,
        clinical_course_archetype="uncomplicated_improvement",
        severity="moderate",
        day_index=0,
        los_days=1,
        vitals=[],
        lab_results=[],
        medications=[],
        diagnoses=[],
        procedures=[],
        allergies=[],
        document_type=DocumentType.OUTPATIENT_SOAP,
        target_lang="ja",
        locale="jp",
    )


def _run_follow_up(ctx: NarrativeContext) -> str:
    return TemplateNarrativeGenerator()._compose_follow_up_line(ctx)


def test_follow_up_line_deterministic_for_same_encounter() -> None:
    a = _run_follow_up(_mk_ctx("I10", "enc-1"))
    b = _run_follow_up(_mk_ctx("I10", "enc-1"))
    assert a == b


def test_scheduled_condition_states_its_follow_up_interval() -> None:
    # Issue #2287: the note states the interval the calendar schedules
    # (chronic_followup.yaml follow_up_interval_months): I10 every 4 months,
    # E78 every 3, N18 monthly.
    for k in range(5):
        assert "4か月後" in _run_follow_up(_mk_ctx("I10", f"enc-htn-{k}"))
        assert "3か月後" in _run_follow_up(_mk_ctx("E78", f"enc-lipid-{k}"))
        assert "1か月後" in _run_follow_up(_mk_ctx("N18", f"enc-ckd-{k}"))


def test_unknown_condition_states_no_invented_interval() -> None:
    # Issue #3465: a condition with no follow-up schedule and no scheduled
    # next visit states none (the former 28 / 60 / 90 day rotation is gone).
    for k in range(20):
        assert _run_follow_up(_mk_ctx("F32.9", f"enc-x-{k}")) == ""
