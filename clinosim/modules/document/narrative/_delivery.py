"""The delivery facts a note of a delivery stay states (Issue #3663).

The mother's record holds them in ``extensions["delivery"]`` (mode,
gestational age, estimated blood loss, complication codes), projected on
``NarrativeContext.delivery``; a record without the extension falls back to
the admission diagnosis (O80 / O82) for the mode and to the pregnancy period
for the gestational age. Every function returns ``None`` / ``""`` / ``[]``
for a fact the record does not hold: a note states what the record holds.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from clinosim.modules._shared import get_attr_or_key as _o

if TYPE_CHECKING:
    from clinosim.types.document import NarrativeContext


def delivery_data(ctx: NarrativeContext) -> dict:
    """The delivery extension of the stay's record (``{}`` for any other stay)."""
    data = getattr(ctx, "delivery", None)
    return data if isinstance(data, dict) else {}


def delivery_mode(ctx: NarrativeContext) -> str | None:
    """``"vaginal"`` / ``"cesarean"`` for a delivery stay, ``None`` for any
    other: the record's mode, else the one the admission diagnosis (O80 / O82)
    gives."""
    from clinosim.modules.document.reference_data_loaders import load_disease_exam

    rule = load_disease_exam().delivery
    mode = delivery_data(ctx).get("mode")
    if mode in rule.modes:
        return str(mode)
    for dx in getattr(ctx, "diagnoses", None) or []:
        code = str(_o(dx, "admission_diagnosis_code", "") or "")
        if code:
            return rule.admission_codes.get(code)
    return None


def gestational_age(ctx: NarrativeContext) -> tuple[int, int] | None:
    """``(weeks, days)`` of gestation at the birth, ``None`` when the record
    holds no gestational age."""
    days = delivery_data(ctx).get("gestational_age_days")
    if not isinstance(days, int) or days <= 0:
        from clinosim.modules.document.narrative.renderers._disease_exam import _gestational_age_days

        days = _gestational_age_days(ctx)
    if not isinstance(days, int) or days <= 0:
        return None
    return days // 7, days % 7


def blood_loss_ml(ctx: NarrativeContext) -> int | None:
    """The estimated blood loss of the delivery in mL (``None`` when unrecorded)."""
    value = delivery_data(ctx).get("estimated_blood_loss_ml")
    return int(value) if isinstance(value, (int, float)) and value > 0 else None


def complication_codes(ctx: NarrativeContext) -> list[str]:
    """The ICD codes of the complications kept for this delivery."""
    return [str(c) for c in delivery_data(ctx).get("complication_codes") or [] if c]


def postpartum_visit_days() -> int | None:
    """Days after the birth of the first scheduled postpartum visit
    (``perinatal.yaml`` ``lifecycle.postpartum_visit_offsets_days``)."""
    from clinosim.locale.loader import load_perinatal_config

    offsets = [
        int(d) for d in (load_perinatal_config().get("lifecycle") or {}).get("postpartum_visit_offsets_days") or []
    ]
    return min(offsets) if offsets else None
