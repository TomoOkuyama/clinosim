"""What a delivery complication leaves in the record (Issue #3662): the
vital-sign override, the laboratory results and the drug orders that
``perinatal.yaml complications.effects`` gives each kept complication code.

Every value is drawn from a sub-seed keyed on the encounter and the code, never
from a shared stream, so a delivery without a complication is unchanged.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from clinosim import determinism
from clinosim.locale.i18n import t
from clinosim.locale.loader import load_code_mapping
from clinosim.seeding import text_seed
from clinosim.types.encounter import Order, OrderResult, OrderStatus, OrderType

# Minutes from the order to its result (a stat blood draw reported within the hour).
_RESULT_DELAY_MIN = 60


def effects_for(cfg: dict[str, Any], codes: list[str]) -> list[tuple[str, dict[str, Any]]]:
    """``(code, effect)`` of every kept complication that has an effect row."""
    table = (cfg.get("complications") or {}).get("effects") or {}
    return [(code, table[code]) for code in codes if code in table]


def bp_override(
    effects: list[tuple[str, dict[str, Any]]], encounter_id: str, admission: datetime
) -> dict[str, Any] | None:
    """The blood-pressure override of the first complication that sets one:
    ``{"until": datetime, "draw": callable(at) -> (systolic, diastolic)}``."""
    for code, effect in effects:
        spec = effect.get("vitals")
        if not spec:
            continue
        rng = determinism.default_rng(text_seed(f"delivery-complication-vitals|{encounter_id}|{code}"))
        sbp, dbp = spec["systolic_bp"], spec["diastolic_bp"]

        def draw(_at: datetime, rng: Any = rng, sbp: Any = sbp, dbp: Any = dbp) -> tuple[int, int]:
            return (
                int(rng.integers(int(sbp[0]), int(sbp[1]) + 1)),
                int(rng.integers(int(dbp[0]), int(dbp[1]) + 1)),
            )

        return {"until": admission + timedelta(hours=float(spec["duration_hours"])), "draw": draw}
    return None


def lab_orders(
    effects: list[tuple[str, dict[str, Any]]],
    *,
    patient: Any,
    encounter: Any,
    country: str,
    ordered_by: str,
) -> list[Order]:
    """The resulted laboratory orders of the kept complications."""
    from clinosim.modules.observation.engine import determine_flag, get_lab_unit

    loinc = load_code_mapping("lab", "US")
    out: list[Order] = []
    for code, effect in effects:
        rng = determinism.default_rng(text_seed(f"delivery-complication-labs|{encounter.encounter_id}|{code}"))
        key = code.replace(".", "_")
        for i, spec in enumerate(effect.get("labs") or [], start=1):
            low, high = float(spec["value"][0]), float(spec["value"][1])
            digits = int(spec.get("digits", 1))
            value = round(low + (high - low) * float(rng.random()), digits)
            if digits == 0:
                value = int(value)
            ordered = encounter.admission_datetime + timedelta(minutes=float(spec["offset_minutes"]))
            lab = str(spec["lab"])
            order = Order(
                order_id=f"ORD-{encounter.encounter_id}-CXLAB-{key}-{i:02d}",
                encounter_id=encounter.encounter_id,
                patient_id=patient.patient_id,
                order_type=OrderType.LAB,
                order_code=loinc.get(lab, ""),
                order_code_system="loinc" if loinc.get(lab) else "",
                display_name=lab,
                urgency="stat",
                clinical_intent=t(f"perinatal_intent.CXLAB_{key}", "en"),
                clinical_intent_ja=t(f"perinatal_intent.CXLAB_{key}", "ja"),
                ordered_datetime=ordered,
                ordered_by=ordered_by,
                status=OrderStatus.RESULTED,
            )
            order.result = OrderResult(
                result_datetime=ordered + timedelta(minutes=_RESULT_DELAY_MIN),
                performed_by="",
                lab_name=lab,
                value=value,
                unit=get_lab_unit(lab),
                flag=determine_flag(
                    lab,
                    value,
                    sex=patient.sex,
                    country=country,
                    medications=patient.current_medications,
                    age=patient.age,
                ),
            )
            out.append(order)
    return out


def drug_orders(
    effects: list[tuple[str, dict[str, Any]]],
    *,
    patient: Any,
    encounter: Any,
    delivered_at: datetime,
    allowed: Any,
) -> list[Order]:
    """The drug orders of the kept complications; ``allowed(drug_name)`` is the
    allergy gate (an order the mother's allergies rule out is not placed)."""
    out: list[Order] = []
    for _code, effect in effects:
        for spec in effect.get("orders") or []:
            name = str(spec["drug"])
            if not allowed(name):
                continue
            base = encounter.admission_datetime if spec["anchor"] == "admission" else delivered_at
            sfx = str(spec["suffix"])
            out.append(
                Order(
                    order_id=f"ORD-{encounter.encounter_id}-{sfx}-01",
                    encounter_id=encounter.encounter_id,
                    patient_id=patient.patient_id,
                    order_type=OrderType.MEDICATION,
                    display_name=name,
                    urgency=str(spec["urgency"]),
                    clinical_intent=t(f"perinatal_intent.{sfx}", "en"),
                    clinical_intent_ja=t(f"perinatal_intent.{sfx}", "ja"),
                    ordered_datetime=base + timedelta(minutes=float(spec["offset_minutes"])),
                    ordered_by=encounter.attending_physician_id,
                    status=OrderStatus.PLACED,
                    dose_quantity=float(spec["dose"]),
                    dose_unit=str(spec["unit"]),
                    frequency=str(spec["frequency"]),
                    frequency_per_day=int(spec["per_day"]),
                    route=str(spec["route"]),
                    duration_days=1,
                )
            )
    return out
