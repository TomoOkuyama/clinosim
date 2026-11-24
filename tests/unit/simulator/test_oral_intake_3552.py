"""A patient who is unresponsive or ventilated is nil by mouth and gets no oral dose (Issue #3552)."""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from clinosim.locale.loader import hold_reason_display
from clinosim.simulator import daily_loop as dl
from clinosim.simulator.oral_intake import apply_oral_intake_holds, oral_intake_rules
from clinosim.types.clinical import PhysiologicalState
from clinosim.types.encounter import MedicationAdministration, OrderStatus, OrderType, VitalSignRecord

pytestmark = pytest.mark.unit

T0 = datetime(2026, 3, 1, 9, 0)
RULES = oral_intake_rules()


def _reading(hour: float, level: str) -> VitalSignRecord:
    return VitalSignRecord(
        timestamp=T0 + timedelta(hours=hour), heart_rate=90, systolic_bp=120, consciousness_level=level
    )


def _dose(hour: float, route: str = "PO", status: str = "given") -> MedicationAdministration:
    when = T0 + timedelta(hours=hour)
    return MedicationAdministration(
        order_id="O1", drug_name="Amlodipine", scheduled_datetime=when, actual_datetime=when, status=status, route=route
    )


def _stay_and_run(state: PhysiologicalState):
    stay = SimpleNamespace(
        patient=SimpleNamespace(patient_id="POP-1"),
        encounter_id="ENC-1",
        admission_time=T0,
        attending_id="DR-1",
        disease_id="pneumonia",
        country="US",
    )
    return stay, dl._Run(state=state, differential=None, orders=[], dvt_prophylaxis_planned=False)


def _diets(run) -> list[str]:
    return [o.display_name for o in run.orders if o.order_type == OrderType.DIET]


def test_oral_dose_after_a_pain_or_unresponsive_reading_is_held() -> None:
    vitals = [_reading(0, "A"), _reading(2, "U")]
    doses = [_dose(1), _dose(3), _dose(3.5, route="IV")]
    held = apply_oral_intake_holds(doses, vitals, lambda t: False)
    assert held == 1
    assert [d.status for d in doses] == ["given", "held", "given"]
    assert doses[1].hold_reason == RULES.hold_reason_consciousness
    assert doses[1].actual_datetime is None
    assert hold_reason_display(RULES.hold_reason_consciousness, "ja") != RULES.hold_reason_consciousness


def test_oral_dose_resumes_when_the_level_recovers() -> None:
    vitals = [_reading(0, "P"), _reading(4, "A")]
    doses = [_dose(1), _dose(5)]
    apply_oral_intake_holds(doses, vitals, lambda t: False)
    assert [d.status for d in doses] == ["held", "given"]


def test_oral_dose_held_while_ventilated() -> None:
    doses = [_dose(1), _dose(5)]
    apply_oral_intake_holds(doses, [_reading(0, "A")], lambda t: t >= T0 + timedelta(hours=4))
    assert [d.status for d in doses] == ["given", "held"]
    assert doses[1].hold_reason == RULES.hold_reason_ventilated


def test_order_diet_is_npo_when_the_latest_reading_is_unresponsive() -> None:
    stay, run = _stay_and_run(PhysiologicalState())
    run.vitals = [_reading(0, "A"), _reading(24, "U")]
    dl._order_diet(stay, run, 2)
    assert _diets(run) == [RULES.npo_diet]
    # Recovered: the next day's order re-advances the diet.
    run.vitals.append(_reading(40, "A"))
    dl._order_diet(stay, run, 3)
    assert _diets(run)[-1] == "regular_diet"


def test_diet_turns_npo_at_the_first_reduced_reading_of_the_day() -> None:
    stay, run = _stay_and_run(PhysiologicalState())
    run.prev_diet = "regular_diet"
    run.vitals = [_reading(2, "A"), _reading(10, "P"), _reading(12, "U")]
    run.mars = [_dose(3), _dose(11), _dose(13)]
    dl._hold_oral_intake(stay, run, 0)
    assert _diets(run) == [RULES.npo_diet]
    assert [o.ordered_datetime for o in run.orders] == [T0 + timedelta(hours=10)]
    assert [m.status for m in run.mars] == ["given", "held", "held"]


def _meal_line(lang: str, medications: list[dict]) -> str | None:
    from clinosim.modules.document.narrative._nursing_shift_items import ShiftData, _item_meal

    ctx = SimpleNamespace(
        encounter={"admission_datetime": "2026-03-01T09:00:00"},
        day_index=0,
        orders=[{"order_type": "diet", "ordered_datetime": "2026-03-01T09:30:00", "display_name": "NPO"}],
        adl_assessments=[],
        intake_output_records=[],
        medications=medications,
    )
    window = (datetime(2026, 3, 1, 8), datetime(2026, 3, 1, 16))
    return _item_meal(ShiftData(ctx=ctx, lang=lang, readings=[], prior=None, window=window))


def test_shift_note_says_oral_doses_are_given_with_sips_under_npo() -> None:
    given = {"status": "given", "route": "PO", "scheduled_datetime": "2026-03-01T10:00:00"}
    iv = {"status": "given", "route": "IV", "scheduled_datetime": "2026-03-01T10:00:00"}
    assert "sips of water" in (_meal_line("en", [given]) or "")
    assert "少量の水" in (_meal_line("ja", [given]) or "")
    assert "sips" not in (_meal_line("en", [iv]) or "")
    assert "sips" not in (_meal_line("en", [{**given, "status": "held"}]) or "")


def test_diet_ordered_earlier_in_the_day_than_the_reading_is_overridden() -> None:
    """A soft diet ordered at 14:00 (latest reading then alert) and a P reading
    at 15:00: NPO from 15:00; the diet remembered for tomorrow's change check is NPO."""
    stay, run = _stay_and_run(PhysiologicalState())
    run.prev_diet = "soft_diet"
    run.orders = [
        SimpleNamespace(
            order_type=OrderType.DIET,
            display_name="soft_diet",
            ordered_datetime=T0 + timedelta(hours=5),
            status=OrderStatus.PLACED,
        )
    ]
    run.vitals = [_reading(4, "A"), _reading(6, "P")]
    dl._hold_oral_intake(stay, run, 0)
    assert _diets(run) == ["soft_diet", RULES.npo_diet]
    assert run.prev_diet == RULES.npo_diet
    dl._hold_oral_intake(stay, run, 0)  # idempotent
    assert _diets(run) == ["soft_diet", RULES.npo_diet]
