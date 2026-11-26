"""The result of an OSA patient's baseline polysomnography (Issue #3837).

``reference_data/sleep_study.yaml`` holds the AHI severity bands and the
procedure the result belongs to. The AHI is drawn from a sub-RNG of the
patient id (``seeding.sleep_study_seed``), so no other stream moves.
"""

from __future__ import annotations

import functools
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, model_validator

from clinosim import determinism
from clinosim.datafiles import load_data_yaml
from clinosim.locale.i18n import t
from clinosim.locale.loader import order_test_display
from clinosim.seeding import sleep_study_seed
from clinosim.types.encounter import Encounter, Order, OrderResult, OrderStatus, OrderType

__all__ = ["sleep_study_ahi", "sleep_study_result_order", "sleep_study_rules"]

_YAML = Path(__file__).resolve().parent / "reference_data" / "sleep_study.yaml"
_UNIT = "{events}/h"


class SleepStudyRules(BaseModel):
    """Schema of ``reference_data/sleep_study.yaml``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    analyte: str
    procedure_snomed: str
    condition_prefix: str
    abnormal_from: float
    severity_bands: dict[str, tuple[float, float]]

    @model_validator(mode="after")
    def _check(self) -> SleepStudyRules:
        for name, (lo, hi) in self.severity_bands.items():
            if not 0 <= lo < hi:
                raise ValueError(f"severity_bands {name}: need 0 <= low < high")
        return self


@functools.cache
def sleep_study_rules() -> SleepStudyRules:
    """The validated ``sleep_study.yaml`` (shared, read-only)."""
    return SleepStudyRules.model_validate(load_data_yaml(_YAML))


def sleep_study_ahi(patient_id: str, severity: str) -> float:
    """The apnea-hypopnea index (events/h, one decimal) of the patient's study,
    uniform within the band of ``severity``."""
    lo, hi = sleep_study_rules().severity_bands[severity]
    value = lo + float(determinism.default_rng(sleep_study_seed(patient_id)).random()) * (hi - lo)
    return min(round(value, 1), round(hi - 0.1, 1))


def _osa_severity(patient: Any) -> str | None:
    prefix = sleep_study_rules().condition_prefix
    for cond in getattr(patient, "chronic_conditions", None) or []:
        code = str(getattr(cond, "code", "") or "")
        severity = str(getattr(cond, "severity", "") or "")
        if code.startswith(prefix) and severity in sleep_study_rules().severity_bands:
            return severity
    return None


def sleep_study_result_order(
    patient: Any,
    encounter: Encounter,
    procedures: list[Any],
    performed_by: str,
    result_offset: timedelta,
) -> tuple[Order, OrderResult] | None:
    """The AHI order and result for the study recorded by ``procedures`` in this
    visit, or None when the visit records no such study or the patient's OSA
    carries no known severity. The result is reported after the study ends."""
    rules = sleep_study_rules()
    study = next((p for p in procedures if str(p.procedure_id).endswith(f"-{rules.procedure_snomed}")), None)
    severity = _osa_severity(patient)
    if study is None or severity is None:
        return None
    order_id = f"ORD-{encounter.encounter_id}-SLEEP-{rules.analyte}"
    ahi = sleep_study_ahi(patient.patient_id, severity)
    reported: datetime = study.end_datetime + result_offset
    result = OrderResult(
        result_datetime=reported,
        performed_by=performed_by,
        lab_name=rules.analyte,
        value=ahi,
        unit=_UNIT,
    )
    result.flag = "H" if ahi >= rules.abnormal_from else None
    order = Order(
        order_id=order_id,
        encounter_id=encounter.encounter_id,
        patient_id=patient.patient_id,
        order_type=OrderType.LAB,
        order_code=rules.analyte,
        display_name=rules.analyte,
        urgency="routine",
        clinical_intent=t("encounter_intent.sleep_study_result", "en", test=rules.analyte),
        clinical_intent_ja=t("encounter_intent.sleep_study_result", "ja", test=order_test_display(rules.analyte, "ja")),
        ordered_datetime=study.start_datetime,
        ordered_by=encounter.attending_physician_id,
        status=OrderStatus.RESULTED,
        result=result,
    )
    return order, result
