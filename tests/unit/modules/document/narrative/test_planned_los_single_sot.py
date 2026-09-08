"""Planned-LOS single source of truth — Issue #1185 F4.

Two slots in the same admission_hp document previously reported
different planned LOS numbers (25 日 in `_compose_ap_plan_from_state`
vs 17 日 in `_build_acp_estimated_los`) because the two builders
used different sources:

- `_compose_ap_plan_from_state` — `ctx.los_days` (the actual
  observed LOS at document-write time; tautologically 100% accurate
  but unrealistic for an AT-ADMISSION prediction).
- `_build_acp_estimated_los` — `_estimated_los_days` canonical
  resolver, which reads `disease_protocol.target_los[country]
  [severity].mean`.

The fix routes both slots through `_estimated_los_days`. Now the
"予定入院期間" and "推定入院期間" slots quote the same number.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from clinosim.modules.document.narrative.template_generator import (
    TemplateNarrativeGenerator,
)
from clinosim.types.document import DocumentType, NarrativeContext
from clinosim.types.patient import PatientProfile


def _mk_ctx_with_protocol(actual_los: int, protocol_mean_los: int) -> NarrativeContext:
    """Build a NarrativeContext where actual LOS ≠ protocol mean LOS."""
    p = PatientProfile(patient_id="pt-1185")
    p.chronic_conditions = []
    p.current_medications = []
    p.age = 65
    p.sex = "M"

    # Minimal disease-protocol stub — the resolver reads `target_los`
    # with yaml country keys ("japan" / "us"), not FHIR country codes.
    protocol = SimpleNamespace(
        target_los={"japan": {"moderate": {"mean": protocol_mean_los}}},
    )

    enc = SimpleNamespace(
        encounter_id="enc-1185",
        admission_datetime=datetime(2026, 2, 15, 10, 0),
        encounter_type=SimpleNamespace(value="inpatient"),
    )
    return NarrativeContext(
        patient=p,
        encounter=enc,
        encounter_type=enc.encounter_type,
        disease_protocol=protocol,
        encounter_protocol=None,
        clinical_course_archetype="uncomplicated_improvement",
        severity="moderate",
        day_index=0,
        los_days=actual_los,
        vitals=[],
        lab_results=[],
        medications=[],
        diagnoses=[],
        procedures=[],
        allergies=[],
        document_type=DocumentType.ADMISSION_HP,
        target_lang="ja",
        locale="jp",
    )


def test_ap_plan_uses_protocol_mean_not_actual_los() -> None:
    ctx = _mk_ctx_with_protocol(actual_los=25, protocol_mean_los=17)
    gen = TemplateNarrativeGenerator()
    plan_text = gen._compose_ap_plan_from_state(ctx)
    # Must include the protocol-mean value (17), not the actual observed LOS (25).
    assert "約17日" in plan_text
    assert "約25日" not in plan_text


def test_acp_estimated_los_matches_ap_plan() -> None:
    # Both slots must resolve to the same number when both are read
    # from the same NarrativeContext.
    ctx = _mk_ctx_with_protocol(actual_los=25, protocol_mean_los=17)
    gen = TemplateNarrativeGenerator()
    plan_text = gen._compose_ap_plan_from_state(ctx)
    acp_text, _ = gen._build_acp_estimated_los(ctx)
    # Extract the digit sequence following 約 from both strings and compare.
    import re

    m_plan = re.search(r"約(\d+)日", plan_text)
    m_acp = re.search(r"約(\d+)日", acp_text)
    assert m_plan is not None, plan_text
    assert m_acp is not None, acp_text
    assert m_plan.group(1) == m_acp.group(1)


def test_falls_back_to_actual_when_protocol_missing() -> None:
    # No disease_protocol → `_estimated_los_days` falls back to
    # `ctx.los_days`, and both slots share that value.
    ctx = _mk_ctx_with_protocol(actual_los=25, protocol_mean_los=17)
    ctx.disease_protocol = None
    gen = TemplateNarrativeGenerator()
    plan_text = gen._compose_ap_plan_from_state(ctx)
    assert "約25日" in plan_text


def test_english_variant() -> None:
    ctx = _mk_ctx_with_protocol(actual_los=25, protocol_mean_los=17)
    ctx.target_lang = "en"
    ctx.locale = "us"
    # For the US locale the resolver reads the "us" yaml key; add it so
    # protocol_mean_los is discoverable.
    ctx.disease_protocol.target_los["us"] = {"moderate": {"mean": 17}}
    gen = TemplateNarrativeGenerator()
    plan_text = gen._compose_ap_plan_from_state(ctx)
    assert "~17 days" in plan_text
    assert "~25 days" not in plan_text
