"""Severity code of a sepsis discharge diagnosis from the stay's recorded
facts (Issue #3269).

A sepsis stay is coded septic shock only with shock physiology — a vasopressor
given, a mean arterial pressure below target and a raised lactate (Sepsis-3) —
and severe sepsis only with a recorded organ dysfunction; otherwise it keeps
the sepsis code. Diagnostic confidence does not pick the severity. The rules
live in ``reference_data/diagnosis_rules.yaml`` (``sepsis_severity``). The
function reads CIF facts only and draws nothing.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from clinosim.codes.drugs import drug_classes
from clinosim.simulator.diagnosis_rules import sepsis_severity_rules
from clinosim.simulator.vasoactive_support import mean_arterial_pressure
from clinosim.types.encounter import MedicationAdministration, OrderResult, VitalSignRecord


def _vasopressor_given(mars: Iterable[MedicationAdministration], classes: frozenset[str]) -> bool:
    return any(m.status == "given" and classes & set(drug_classes(m.drug_id or m.drug_name)) for m in mars)


def _lab_values(lab_results: Iterable[OrderResult]) -> dict[str, list[float]]:
    values: dict[str, list[float]] = {}
    for result in lab_results:
        if isinstance(result.value, (int, float)) and not isinstance(result.value, bool):
            values.setdefault(result.lab_name, []).append(float(result.value))
    return values


def _any_above(values: Mapping[str, list[float]], limits: Mapping[str, float]) -> bool:
    return any(v > limit for lab, limit in limits.items() for v in values.get(lab, ()))


def _any_at_or_above(values: Mapping[str, list[float]], limits: Mapping[str, float]) -> bool:
    return any(v >= limit for lab, limit in limits.items() for v in values.get(lab, ()))


def _any_below(values: Mapping[str, list[float]], limits: Mapping[str, float]) -> bool:
    return any(v < limit for lab, limit in limits.items() for v in values.get(lab, ()))


def sepsis_severity_code(
    code: str,
    *,
    vitals: Iterable[VitalSignRecord],
    mars: Iterable[MedicationAdministration],
    lab_results: Iterable[OrderResult],
) -> str:
    """The discharge code of a stay the differential resolved to ``code``:
    a sepsis-family code (``sepsis_severity.codes``) becomes septic shock,
    severe sepsis or sepsis by the stay's vitals, MAR and lab results; any
    other code is returned unchanged."""
    rules = sepsis_severity_rules()
    if code not in rules.codes:
        return code
    mars = list(mars)
    labs = _lab_values(lab_results)
    shock = rules.septic_shock
    if (
        _vasopressor_given(mars, shock.vasopressor_classes)
        and any(
            mean_arterial_pressure(v.systolic_bp, v.diastolic_bp) < shock.map_below
            for v in vitals
            if v.systolic_bp is not None and v.diastolic_bp is not None
        )
        and _any_above(labs, shock.labs_above)
    ):
        return shock.code
    severe = rules.severe_sepsis
    if (
        _vasopressor_given(mars, severe.vasopressor_classes)
        or _any_at_or_above(labs, severe.labs_at_or_above)
        or _any_below(labs, severe.labs_below)
    ):
        return severe.code
    return rules.sepsis_code
