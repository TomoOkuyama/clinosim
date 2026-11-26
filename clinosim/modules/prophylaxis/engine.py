"""Prophylaxis engine — YAML loader + skip-condition dispatch + order builder.

Determinism: no RNG consumption. Every decision is a pure function of
patient / encounter state + the yaml rule set.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from clinosim.codes.drugs import drug_classes
from clinosim.datafiles import load_data_yaml
from clinosim.locale.localized import language_slot, localized_field
from clinosim.modules._shared import COMPLICATION_TREATMENT_ORDER_ID_MARKER

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


class _RenalAdjustment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    crcl_below_ml_min: float = Field(gt=0)
    dose_quantity: float = Field(gt=0)


class _Regimen(BaseModel):
    """One country's prophylaxis regimen (Issue #3449)."""

    model_config = ConfigDict(extra="forbid")

    drug: str = Field(min_length=1)
    dose_quantity: float = Field(gt=0)
    dose_unit: str = Field(min_length=1)
    route: str = Field(min_length=1)
    frequency: str = Field(min_length=1)
    frequency_per_day: int = Field(ge=1)
    administration_hours: list[int] = Field(min_length=1)
    renal_adjustment: _RenalAdjustment | None = None

    @field_validator("administration_hours")
    @classmethod
    def _hours_of_day(cls, hours: list[int]) -> list[int]:
        if any(h not in range(24) for h in hours) or hours != sorted(set(hours)):
            raise ValueError("administration_hours must be increasing hours of the day (0-23)")
        return hours

    @model_validator(mode="after")
    def _one_hour_per_dose(self) -> _Regimen:
        if len(self.administration_hours) != self.frequency_per_day:
            raise ValueError("administration_hours must list one hour per daily dose (frequency_per_day)")
        return self


class _DvtRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    min_los_hours: float = Field(gt=0)
    guideline: str
    clinical_intent: dict[str, str]
    default_country: str
    regimens: dict[str, _Regimen] = Field(min_length=1)

    @model_validator(mode="after")
    def _default_regimen_exists(self) -> _DvtRule:
        if self.default_country not in self.regimens:
            raise ValueError(f"default_country {self.default_country!r} has no regimen")
        return self


class _CreatinineClearance(BaseModel):
    """Cockcroft-Gault terms (``renal_dose.crcl_cockcroft_gault``)."""

    model_config = ConfigDict(extra="forbid")

    equation: Literal["cockcroft_gault"]
    age_offset: float = Field(gt=0)
    denominator: float = Field(gt=0)
    female_factor: float = Field(gt=0, le=1)
    creatinine_unit: str = Field(min_length=1)


class _ProphylaxisRules(BaseModel):
    """Shape of prophylaxis_rules.yaml (Issue #2762)."""

    model_config = ConfigDict(extra="forbid")

    metadata: dict[str, Any] = Field(default_factory=dict)
    dvt_prophylaxis: _DvtRule
    creatinine_clearance: _CreatinineClearance
    skip_conditions: dict[str, _SkipRule] = Field(min_length=1)


@lru_cache(maxsize=1)
def _load_rules() -> dict[str, Any]:
    data = load_data_yaml(_YAML_PATH) or {}
    _ProphylaxisRules.model_validate(data)
    return data


def _dvt_rule() -> dict[str, Any]:
    return _load_rules().get("dvt_prophylaxis", {}) or {}


def _default_dvt_regimen() -> dict[str, Any]:
    """The regimen of the rule's ``default_country`` (used where no country applies)."""
    rule = _dvt_rule()
    return rule["regimens"][rule["default_country"]]


def dvt_regimen(country: str) -> dict[str, Any]:
    """The prophylaxis regimen of ``country`` (the rule's ``default_country`` when it has none)."""
    rule = _dvt_rule()
    regimens: dict[str, Any] = rule["regimens"]
    return regimens.get(str(country or "").upper()) or regimens[rule["default_country"]]


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
            the default country's regimen drug — Enoxaparin). Fed into
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
        candidate_drug = _default_dvt_regimen()["drug"]
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


def _crcl_function(record: Any, enc: Any, country: str) -> Any:
    """``creatinine (mg/dL) -> CrCl (mL/min)`` for the stay's patient (age and
    charted weight at admission), or None when the patient lacks them."""
    from clinosim.modules.population.encounter_anthropometry import age_at_measurement, encounter_weight_kg
    from clinosim.modules.prophylaxis.renal_dose import crcl_cockcroft_gault

    patient = getattr(record, "patient", None)
    adm = getattr(enc, "admission_datetime", None)
    if patient is None or adm is None:
        return None
    try:
        weight = encounter_weight_kg(patient, str(getattr(enc, "encounter_id", "") or ""), adm, country)
        age = age_at_measurement(patient, adm)[0]
    except (TypeError, ValueError, KeyError):
        return None
    if not weight or weight <= 0:
        return None
    terms = _load_rules()["creatinine_clearance"]
    sex = str(getattr(patient, "sex", "") or "")

    def crcl_of(creatinine: float) -> float:
        return crcl_cockcroft_gault(
            creatinine,
            age,
            weight,
            sex,
            age_offset=terms["age_offset"],
            denominator=terms["denominator"],
            female_factor=terms["female_factor"],
        )

    return crcl_of


def build_dvt_prophylaxis_orders(
    *,
    record: Any,
    encounter_id_override: str = "",
    country: str,
) -> list[Any]:
    """Return a list of ``Order`` dataclasses (each ready to be appended
    to ``record.orders``) representing the DVT prophylaxis regimen for
    the encounter's LOS.

    The regimen is the country's (``prophylaxis_rules.yaml``, Issue #3449): US
    Enoxaparin 40 mg SC daily, 30 mg daily while the Cockcroft-Gault creatinine
    clearance from the latest creatinine is below 30 mL/min (the dose is reduced
    once: the first creatinine below the threshold stops the order at its
    result time and a second order carries the reduced dose); JP unfractionated
    heparin 5,000 IU SC every 12 hours. The matching MedicationAdministration rows are added by the enricher.

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
    regimen = dvt_regimen(country)
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
    # Issue #3864: a therapeutic anticoagulant a complication started during
    # the stay (``COMPLICATION_TREATMENT_ORDER_ID_MARKER``) does not remove the
    # prophylaxis given before it: the prophylaxis ends at that order.
    started_for_complication: list[Any] = []
    in_encounter = []
    for o in getattr(record, "orders", None) or []:
        if getattr(o, "order_type", None) != OrderType.MEDICATION or getattr(o, "status", None) in (
            OrderStatus.CANCELLED,
            OrderStatus.STOPPED,
        ):
            continue
        if COMPLICATION_TREATMENT_ORDER_ID_MARKER in str(getattr(o, "order_id", "")) and "anticoagulant" in (
            drug_classes(getattr(o, "drug_id", "") or getattr(o, "display_name", "") or "")
        ):
            started_for_complication.append(o)
            continue
        in_encounter.append(getattr(o, "display_name", "") or "")
    active_meds = [m for m in chronic + in_encounter if m]

    skip, reason = should_skip_dvt_prophylaxis(
        patient=patient,
        encounter=enc,
        admission_dx_code=admission_dx,
        active_medications=active_meds,
        candidate_drug=regimen["drug"],
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

    # Issue #3864: the prophylaxis ends when the stay's therapeutic
    # anticoagulation starts, and is not given at all when that was before it.
    therapeutic_start = min(
        (o.ordered_datetime for o in started_for_complication if getattr(o, "ordered_datetime", None) is not None),
        default=None,
    )
    if therapeutic_start is not None and therapeutic_start <= ordered_dt:
        return []

    # Dose tiers over the stay (Issue #3449): one period without a renal rule.
    periods: list[tuple[datetime, bool]] = [(ordered_dt, False)]
    renal = regimen.get("renal_adjustment")
    discharge = getattr(enc, "discharge_datetime", None)
    if renal and isinstance(discharge, datetime):
        crcl_of = _crcl_function(record, enc, country)
        if crcl_of is not None:
            from clinosim.modules.prophylaxis.renal_dose import creatinine_series, dose_periods

            periods = dose_periods(
                creatinine_series(record, _load_rules()["creatinine_clearance"]["creatinine_unit"]),
                start=ordered_dt,
                end=discharge,
                crcl_of=crcl_of,
                crcl_below=float(renal["crcl_below_ml_min"]),
            )

    if therapeutic_start is not None:
        periods = [p for p in periods if p[0] < therapeutic_start]

    # Emit as real Order dataclasses so downstream CLI debug printers and
    # any consumer expecting attribute access work uniformly.
    from clinosim.types.encounter import Order

    orders: list[Order] = []
    for i, (since, reduced) in enumerate(periods, start=1):
        order = Order(
            order_id=f"ORD-{encounter_id}-DVT-{i:02d}",
            encounter_id=encounter_id,
            patient_id=getattr(patient, "patient_id", "") if patient else "",
            order_type=OrderType.MEDICATION,
            order_code="",
            display_name=regimen["drug"],
            urgency="routine",
            clinical_intent=localized_field(rule, "clinical_intent", "en"),
            clinical_intent_ja=language_slot(rule.get("clinical_intent"), "ja"),
            ordered_datetime=since,
            ordered_by=getattr(enc, "attending_physician_id", "") or "",
            status=OrderStatus.PLACED,
            dose_quantity=renal["dose_quantity"] if (reduced and renal) else regimen["dose_quantity"],
            dose_unit=regimen["dose_unit"],
            frequency=regimen["frequency"],
            frequency_per_day=regimen["frequency_per_day"],
            route=regimen["route"],
        )
        if orders:
            # The dose changed: this order replaces the one before it.
            order.prior_order_id = orders[-1].order_id
            orders[-1].status = OrderStatus.STOPPED
            orders[-1].end_datetime = since
        orders.append(order)
    if therapeutic_start is not None and orders:
        orders[-1].status = OrderStatus.STOPPED
        orders[-1].end_datetime = therapeutic_start
    return orders
