"""Plan section variation across visits (Issue #1180).

Before the fix, `_build_outpatient_plan` short-circuited to the YAML
`outpatient_soap_template.plan_<lang>` (a per-condition constant),
which made the SOAP Plan section byte-identical across every
outpatient visit for 92.1% of patients. The fallback path composed
from `current_medications + today_rx + today_procs + follow_up` but
`follow_up` also emitted a constant sentinel.

The fix appends a per-encounter deterministic follow-up line to the
YAML plan, so consecutive visits show different follow-up cadence
drawn from a per-condition band.
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


def test_follow_up_line_varies_across_encounters_for_same_patient() -> None:
    # Same patient + same condition + 6 encounter_ids → should produce
    # at least 2 distinct follow-up intervals across the sequence.
    variants = {_run_follow_up(_mk_ctx("I10", f"enc-{k}")) for k in range(6)}
    assert len(variants) >= 2, f"expected variation across 6 encounters, saw {variants}"


def test_hypertension_uses_htn_band() -> None:
    # I10 band = (30, 60, 90) — every rendered interval must be one of these.
    for k in range(20):
        line = _run_follow_up(_mk_ctx("I10", f"enc-htn-{k}"))
        assert any(f"{d}日後" in line for d in (30, 60, 90))


def test_dyslipidemia_uses_longer_band() -> None:
    # E78 band = (90, 120, 180) — should reach at least one value >90.
    seen_days: set[int] = set()
    for k in range(30):
        line = _run_follow_up(_mk_ctx("E78", f"enc-lipid-{k}"))
        for d in (90, 120, 180):
            if f"{d}日後" in line:
                seen_days.add(d)
    assert seen_days, "expected E78 to sample from (90, 120, 180) band"
    assert seen_days.issubset({90, 120, 180})


def test_unknown_condition_uses_generic_band() -> None:
    # A condition not in the band table (e.g., F32.9) falls back to
    # the generic (28, 60, 90) band. Assert values come from that set.
    for k in range(20):
        line = _run_follow_up(_mk_ctx("F32.9", f"enc-x-{k}"))
        assert any(f"{d}日後" in line for d in (28, 60, 90))
