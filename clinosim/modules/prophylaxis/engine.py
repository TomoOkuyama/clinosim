"""Prophylaxis engine — YAML loader + skip-condition dispatch + order builder.

Determinism: no RNG consumption. Every decision is a pure function of
patient / encounter state + the yaml rule set.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from clinosim.datafiles import load_data_yaml
from clinosim.locale.localized import language_slot, localized_field

_HERE = Path(__file__).resolve().parent
_YAML_PATH = _HERE / "reference_data" / "prophylaxis_rules.yaml"


class _SkipRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str = Field(min_length=1)
    drug_classes: list[str] = Field(default_factory=list)
    infusion_drug_classes: list[str] = Field(default_factory=list)
    icd_prefixes: list[str] = Field(default_factory=list)
    pediatric_age_ceiling: int | None = Field(default=None, ge=0)

    @field_validator("drug_classes", "infusion_drug_classes")
    @classmethod
    def _known_classes(cls, classes: list[str]) -> list[str]:
        from clinosim.codes.drugs import all_drug_ids, drug_classes

        known = {c for d in all_drug_ids() for c in drug_classes(d)}
        unknown = sorted(set(classes) - known)
        if unknown:
            raise ValueError(f"prophylaxis_rules.yaml: drug classes {unknown} name no catalog drug")
        return classes


class _ProphylaxisRules(BaseModel):
    """Shape of prophylaxis_rules.yaml (Issue #2762)."""

    model_config = ConfigDict(extra="forbid")

    metadata: dict[str, Any] = Field(default_factory=dict)
    dvt_prophylaxis: dict[str, Any]
    skip_conditions: dict[str, _SkipRule] = Field(min_length=1)


@lru_cache(maxsize=1)
def _load_rules() -> dict[str, Any]:
    data = load_data_yaml(_YAML_PATH) or {}
    _ProphylaxisRules.model_validate(data)
    return data


def _dvt_rule() -> dict[str, Any]:
    return _load_rules().get("dvt_prophylaxis", {}) or {}


def _skip_conditions() -> dict[str, dict[str, Any]]:
    return _load_rules().get("skip_conditions", {}) or {}


# NOTE: ``pediatric_anticoag_ceiling()`` was introduced as a shared
# helper for the Issue #1306 dual-path gate (order/engine +
# prophylaxis/engine). Issue #1342 collapsed the two paths — the
# ``prophylaxis`` module is now the single DVT_prophylaxis SoT, so the
# pediatric ceiling is read only once, inside
# :func:`should_skip_dvt_prophylaxis` above (via ``_skip_conditions()``).
# The public shim was removed here (vulture / dead-code CI gate).


def _is_therapeutic_anticoagulant(med: Any, rule: dict[str, Any]) -> bool:
    """Whether an active medication (record or name) is a therapeutic
    anticoagulant under ``rule`` (``drug_classes`` / ``infusion_drug_classes``)."""
    from clinosim.codes.drugs import medication_matches
    from clinosim.modules.order.absolute_dose import is_continuous_infusion

    if medication_matches(med, classes=tuple(rule.get("drug_classes") or ())):
        return True
    if not medication_matches(med, classes=tuple(rule.get("infusion_drug_classes") or ())):
        return False
    if isinstance(med, str):
        return is_continuous_infusion("", med)
    get = med.get if isinstance(med, dict) else lambda k, d=None: getattr(med, k, d)
    return is_continuous_infusion(str(get("frequency", "") or ""), str(get("drug_name", "") or ""))


def should_skip_dvt_prophylaxis(
    *,
    patient: Any,
    encounter: Any,
    admission_dx_code: str = "",
    active_medications: list[Any] | None = None,
    candidate_drug: str = "",
) -> tuple[bool, str]:
    """Return ``(skip, reason)`` — the enricher records ``reason`` in the
    trace so audit consumers can see WHY prophylaxis was withheld.

    Args:
        patient: PatientProfile-like (reads ``current_medications`` if
            ``active_medications`` is None).
        encounter: Encounter with ``admission_datetime`` / ``discharge_datetime``.
        admission_dx_code: ICD code from ``clinical_diagnosis``. Empty string
            means no dx available — do not skip on the dx-based rules.
        active_medications: optional pre-computed list of drug-name strings.
        candidate_drug: the drug the enricher intends to add (defaults to
            the DVT rule's ``drug`` — Enoxaparin). Fed into
            ``drug_safety.check_candidate_against_active`` so any
            major/contraindicated pair against ``active_medications``
            skips prophylaxis (Issue #1087).

    Never raises. If the rule yaml is malformed, returns ``(False, "")`` so
    the caller emits prophylaxis (safe default).
    """
    conditions = _skip_conditions()

    # Rule 0 (Issue #1276): pediatric age gate. AAP / CHEST 2019
    # pediatric VTE prophylaxis guidelines do not recommend routine
    # prophylaxis for the "any adult inpatient ≥ 48 h LOS" trigger
    # this rule set applies. Skip below `pediatric_age_ceiling`
    # (18, Issue #3082). A follow-up in the pediatric care module (Issue
    # #1137) can layer positive-indication detection (ortho surgery,
    # ICU immobilization, Kawasaki disease) + weight-based dosing.
    peds_rule = conditions.get("pediatric_age_gate", {}) or {}
    peds_ceiling = peds_rule.get("pediatric_age_ceiling")
    if peds_ceiling is not None:
        pat_age = getattr(patient, "age", None)
        if pat_age is None:
            # Derive from date_of_birth against admission_datetime.
            dob = getattr(patient, "date_of_birth", None)
            adm = getattr(encounter, "admission_datetime", None)
            if isinstance(dob, str) and dob and adm is not None:
                try:
                    dob_dt = datetime.fromisoformat(dob).date()
                    adm_date = adm.date() if isinstance(adm, datetime) else datetime.fromisoformat(str(adm)).date()
                    pat_age = (
                        adm_date.year - dob_dt.year - ((adm_date.month, adm_date.day) < (dob_dt.month, dob_dt.day))
                    )
                except (TypeError, ValueError):
                    pat_age = None
        if isinstance(pat_age, int) and pat_age < int(peds_ceiling):
            return True, "pediatric_age_gate"

    # Rule 1: therapeutic anticoagulant on board, decided by drug class
    # (Issue #2762): an oral anticoagulant, or a heparin given as a continuous
    # infusion (prophylactic SC heparin is not therapeutic).
    meds: list[Any] = (
        list(active_medications)
        if active_medications is not None
        else list(getattr(patient, "current_medications", None) or [])
    )
    ac_rule = conditions.get("therapeutic_anticoagulant_active", {}) or {}
    if any(_is_therapeutic_anticoagulant(m, ac_rule) for m in meds if m):
        return True, "therapeutic_anticoagulant_active"

    # Rule 2/3/4: ICD-prefix conditions on admission dx.
    if admission_dx_code:
        dx_upper = admission_dx_code.upper().strip()
        for rule_name in (
            "active_bleeding_or_hemorrhage",
            "perinatal_delivery",
            "active_dvt_pe_treatment",
        ):
            rule = conditions.get(rule_name, {}) or {}
            for prefix in rule.get("icd_prefixes", []) or []:
                if dx_upper.startswith(str(prefix).upper()):
                    return True, rule_name

    # Rule 5 (Issue #1087): drug_safety pair check — the candidate drug
    # (Enoxaparin) would create a major/contraindicated pair with an
    # already-active med (chronic aspirin, in-encounter NSAID, etc.).
    if not candidate_drug:
        candidate_drug = _dvt_rule().get("drug", "Enoxaparin") or "Enoxaparin"
    active_names = [
        m if isinstance(m, str) else str(getattr(m, "drug_name", None) or getattr(m, "drug", None) or "") for m in meds
    ]
    active_names = [n for n in active_names if n]
    if active_names:
        try:
            from clinosim.modules.drug_safety.engine import (
                check_candidate_against_active,
            )

            verdicts = check_candidate_against_active(candidate_drug, active_names)
        except Exception:  # pragma: no cover — defensive: never let a
            # drug_safety failure block prophylaxis.
            verdicts = []
        for v in verdicts:
            if v.severity in ("major", "contraindicated"):
                return True, f"drug_safety_pair:{v.rule_id or 'unknown'}"

    return False, ""


def _encounter_los_hours(encounter: Any) -> float:
    adm = getattr(encounter, "admission_datetime", None) or (
        encounter.get("admission_datetime") if isinstance(encounter, dict) else None
    )
    dc = getattr(encounter, "discharge_datetime", None) or (
        encounter.get("discharge_datetime") if isinstance(encounter, dict) else None
    )
    if adm is None or dc is None:
        return 0.0
    try:
        if isinstance(adm, str):
            adm = datetime.fromisoformat(adm)
        if isinstance(dc, str):
            dc = datetime.fromisoformat(dc)
        return max(0.0, (dc - adm).total_seconds() / 3600.0)
    except (TypeError, ValueError):
        return 0.0


def _admission_dx_from_record(record: Any) -> str:
    """Extract admission / discharge ICD code from record.clinical_diagnosis."""
    cd = getattr(record, "clinical_diagnosis", None)
    if cd is None:
        return ""
    for attr in ("discharge_diagnosis_code", "admission_diagnosis_code"):
        v = getattr(cd, attr, "") or ""
        if v:
            return str(v)
    return ""


def build_dvt_prophylaxis_orders(
    *,
    record: Any,
    encounter_id_override: str = "",
) -> list[Any]:
    """Return a list of ``Order`` dataclasses (each ready to be appended
    to ``record.orders``) representing the DVT prophylaxis regimen for
    the encounter's LOS.

    Emits one Order (Enoxaparin 40 mg SC daily). The matching
    MedicationAdministration rows can be added by the caller if the
    sim detail level warrants them; the Order alone is the load-bearing
    FHIR MedicationRequest signal.

    Never raises. Returns ``[]`` when the encounter should be skipped
    (short LOS, contraindication, therapeutic AC already on board).
    """
    encounters = getattr(record, "encounters", []) or []
    if not encounters:
        return []
    # Focus on the primary IMP encounter (records generated by
    # simulator.inpatient hold one encounter per record).
    enc = encounters[0]
    encounter_type = str(getattr(enc, "encounter_type", "") or "").lower()
    if encounter_type not in ("inpatient", "imp"):
        return []

    rule = _dvt_rule()
    min_los = float(rule.get("min_los_hours", 48))
    if _encounter_los_hours(enc) < min_los:
        return []

    patient = getattr(record, "patient", None)
    admission_dx = _admission_dx_from_record(record)

    # #1087 (C1): union chronic (patient.current_medications) + in-encounter
    # (record.orders where OrderType is MEDICATION and not cancelled/stopped).
    # This lets the drug_safety gate see the aspirin / NSAID that the
    # prophylaxis Enoxaparin would clash with.
    from clinosim.types.encounter import OrderStatus, OrderType

    chronic = [
        getattr(m, "drug_name", None) or getattr(m, "drug", None) or ""
        for m in (getattr(patient, "current_medications", None) or [])
    ]
    in_encounter = [
        (getattr(o, "display_name", "") or "")
        for o in (getattr(record, "orders", None) or [])
        if getattr(o, "order_type", None) == OrderType.MEDICATION
        and getattr(o, "status", None) not in (OrderStatus.CANCELLED, OrderStatus.STOPPED)
    ]
    active_meds = [m for m in chronic + in_encounter if m]

    skip, reason = should_skip_dvt_prophylaxis(
        patient=patient,
        encounter=enc,
        admission_dx_code=admission_dx,
        active_medications=active_meds,
        candidate_drug=rule.get("drug", "Enoxaparin"),
    )
    if skip:
        return []

    encounter_id = encounter_id_override or (getattr(enc, "encounter_id", "") or "")
    if not encounter_id:
        return []

    # An order is placed at a time of the stay: with no admission time there
    # is no order (the wall clock is never a generation input; determinism spec).
    adm_dt = getattr(enc, "admission_datetime", None)
    if isinstance(adm_dt, str):
        try:
            ordered_dt = datetime.fromisoformat(adm_dt) + timedelta(hours=6)
        except (TypeError, ValueError):
            return []
    elif isinstance(adm_dt, datetime):
        ordered_dt = adm_dt + timedelta(hours=6)
    else:
        return []

    # Emit as a real Order dataclass so downstream CLI debug printers and
    # any consumer expecting attribute access work uniformly.
    from clinosim.types.encounter import Order, OrderStatus, OrderType

    order = Order(
        order_id=f"ORD-{encounter_id}-DVT-01",
        encounter_id=encounter_id,
        patient_id=getattr(patient, "patient_id", "") if patient else "",
        order_type=OrderType.MEDICATION,
        order_code="",
        display_name=rule["drug"],
        urgency="routine",
        clinical_intent=localized_field(rule, "clinical_intent", "en"),
        clinical_intent_ja=language_slot(rule.get("clinical_intent"), "ja"),
        ordered_datetime=ordered_dt,
        ordered_by=getattr(enc, "attending_physician_id", "") or "",
        status=OrderStatus.PLACED,
        dose_quantity=rule.get("dose_quantity"),
        dose_unit=rule.get("dose_unit", ""),
        frequency=rule.get("frequency", ""),
        route=rule.get("route", "SC"),
    )
    return [order]
