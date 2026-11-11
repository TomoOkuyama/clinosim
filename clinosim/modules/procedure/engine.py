"""Procedure engine — surgical and procedural workflow simulation.

Generates procedure events (surgery, bedside procedures) with timing,
team assignment, complications, and physiological state changes.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import cache
from pathlib import Path
from typing import Any

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, field_validator

from clinosim import determinism
from clinosim.codes import data_table
from clinosim.codes.procedures import bedside_procedures, country_procedure_code
from clinosim.countries import country_slot
from clinosim.datafiles import load_data_yaml
from clinosim.locale.loader import load_care_practice, load_code_mapping
from clinosim.modules.procedure._bedside_thresholds import (
    BEDSIDE_DURATION_MEAN_MIN,
    BEDSIDE_DURATION_MIN_MIN,
    BEDSIDE_DURATION_STD_MIN,
    BEDSIDE_HOURS_OFFSET_EXPONENTIAL_MEAN,
    BEDSIDE_HOURS_OFFSET_MIN,
    BEDSIDE_SEVERITY_MILD_MULTIPLIER,
    BEDSIDE_SEVERITY_MODERATE_MULTIPLIER,
    BEDSIDE_SEVERITY_MULTIPLIER_FALLBACK,
    BEDSIDE_SEVERITY_SEVERE_MULTIPLIER,
)
from clinosim.modules.procedure._rehab_thresholds import (
    REHAB_IMPROVED_MIN_POD,
    REHAB_PAIN_BASE_SCORE,
    REHAB_PAIN_DECAY_PER_POD,
    REHAB_PAIN_FAIR_PARTICIPATION_THRESHOLD,
    REHAB_PAIN_MAX_SCORE,
    REHAB_PAIN_MIN_SCORE,
    REHAB_PAIN_STD,
    REHAB_PHASE_EARLY_MAX_POD,
    REHAB_PHASE_MID_MAX_POD,
    REHAB_REFUSAL_PROBABILITY,
    REHAB_SESSION_START_HOUR,
    REHAB_SKIP_DAY_PROBABILITY,
    REHAB_START_POD,
)
from clinosim.modules.procedure._surgery_thresholds import (
    ASA_AGE_HIGH_THRESHOLD,
    ASA_AGE_LOW_THRESHOLD,
    ASA_BASE_CLASS,
    ASA_COMORBIDITY_HIGH_THRESHOLD,
    ASA_COMORBIDITY_LOW_THRESHOLD,
    ASA_HIGH_CLASS,
    ASA_LOW_CLASS,
    DEFAULT_EBL_MEAN_ML,
    DEFAULT_EBL_STD_ML,
    DEFAULT_SURGERY_DURATION_MEAN_MIN,
    DEFAULT_SURGERY_DURATION_STD_MIN,
    EBL_ANEMIA_LIFT_DIVISOR,
    EBL_ANEMIA_LIFT_THRESHOLD_ML,
    EBL_MAJOR_BLEED_PERFUSION_PENALTY,
    EBL_MAJOR_BLEED_THRESHOLD_ML,
    EBL_MIN_ML,
    HIP_FRACTURE_ORIF_INTRAMEDULLARY_NAIL_PROBABILITY,
    HIP_FRACTURE_ORIF_PROBABILITY,
    INTRAOP_ANESTHESIA_HYPOTENSION_PROBABILITY,
    INTRAOP_EBL_BLEEDING_MULTIPLIER,
    INTRAOP_EXCESSIVE_BLEEDING_PROBABILITY,
    SPINAL_ANESTHESIA_PROBABILITY_WHEN_ALLOWED,
    SURGERY_DURATION_MIN_MIN,
    SURGERY_INFLAMMATION_LIFT,
    SURGERY_VOLUME_LIFT,
)
from clinosim.seeding import issue939_procedure_seed
from clinosim.types.procedure import ProcedureRecord, RehabSession

__all__ = ["ProcedureRecord", "RehabSession"]


def _hours_to_surgery(proc_data: dict, country: str, rng: np.random.Generator) -> float:
    """Hours from admission to incision: one normal draw.

    Uses the disease YAML's ``procedure.time_to_surgery.<us|japan>``
    (``mean_hours`` / ``sd_hours``) when present (Issue #2067), otherwise the
    country defaults. The floor is the country default floor, lowered to half
    the declared mean for emergent / same-day pathways (acute SDH ~3 h,
    elective TKA ~3 h); YAMLs that declare the defaults draw identically.
    """
    # Issue #3142: the country default (locale/<cc>/care_practice.yaml).
    default = load_care_practice(country).time_to_surgery_hours
    mean, sd, floor = default.mean, default.sd, default.floor
    declared = (proc_data.get("time_to_surgery") or {}).get(country_slot(country, scheme="legacy_japan"))
    if declared:
        mean = float(declared.get("mean_hours", mean))
        sd = float(declared.get("sd_hours", sd))
        floor = min(floor, mean / 2)
    return max(floor, float(rng.normal(mean, sd)))


def simulate_surgery(
    patient: Any,
    disease_id: str,
    encounter_id: str,
    admission_time: datetime,
    protocol: Any,
    rng: np.random.Generator,
    country: str,
    surgeon_id: str = "",
    anesthesiologist_id: str = "",
    operating_rooms: int = 2,
) -> tuple[ProcedureRecord, dict[str, float]]:
    """Simulate a surgical procedure. Returns the record and state impacts.

    Currently supports: hip fracture ORIF/hemiarthroplasty.
    """
    proc_data = protocol.procedure if hasattr(protocol, "procedure") and protocol.procedure else {}

    hours_to_surgery = _hours_to_surgery(proc_data, country, rng)

    surgery_start = admission_time + timedelta(hours=hours_to_surgery)

    # Duration
    dur_config = proc_data.get(
        "typical_duration_minutes",
        {"mean": DEFAULT_SURGERY_DURATION_MEAN_MIN, "sd": DEFAULT_SURGERY_DURATION_STD_MIN},
    )
    duration = int(
        max(
            SURGERY_DURATION_MIN_MIN,
            rng.normal(
                dur_config.get("mean", DEFAULT_SURGERY_DURATION_MEAN_MIN),
                dur_config.get("sd", DEFAULT_SURGERY_DURATION_STD_MIN),
            ),
        )
    )

    # Anesthesia
    anesthesia = proc_data.get("anesthesia", "spinal or general")
    if "spinal" in anesthesia:
        anesthesia_type = "spinal" if rng.random() < SPINAL_ANESTHESIA_PROBABILITY_WHEN_ALLOWED else "general"
    else:
        anesthesia_type = "general"

    # ASA class
    age = patient.age if hasattr(patient, "age") else 75
    n_conditions = len(patient.chronic_conditions) if hasattr(patient, "chronic_conditions") else 1
    asa = ASA_BASE_CLASS
    if n_conditions >= ASA_COMORBIDITY_LOW_THRESHOLD or age >= ASA_AGE_LOW_THRESHOLD:
        asa = ASA_LOW_CLASS
    if n_conditions >= ASA_COMORBIDITY_HIGH_THRESHOLD and age >= ASA_AGE_HIGH_THRESHOLD:
        asa = ASA_HIGH_CLASS

    # EBL
    ebl_config = proc_data.get("estimated_blood_loss_ml", {"mean": DEFAULT_EBL_MEAN_ML, "sd": DEFAULT_EBL_STD_ML})
    ebl = int(
        max(
            EBL_MIN_ML,
            rng.normal(ebl_config.get("mean", DEFAULT_EBL_MEAN_ML), ebl_config.get("sd", DEFAULT_EBL_STD_ML)),
        )
    )

    # Intraop complications
    intraop_comps = []
    if rng.random() < INTRAOP_EXCESSIVE_BLEEDING_PROBABILITY:
        intraop_comps.append("excessive_bleeding")
        ebl = int(ebl * INTRAOP_EBL_BLEEDING_MULTIPLIER)
    if rng.random() < INTRAOP_ANESTHESIA_HYPOTENSION_PROBABILITY:
        intraop_comps.append("anesthesia_hypotension")

    # Procedure type (hip fracture specific)
    if disease_id == "hip_fracture":
        if rng.random() < HIP_FRACTURE_ORIF_PROBABILITY:
            proc_type = "ORIF"
            proc_code_jp = load_code_mapping("procedure", "JP")["ORIF_femur"]
            proc_code_us = load_code_mapping("procedure", "US")["ORIF_femur"]
            implants = [
                "compression hip screw"
                if rng.random() < HIP_FRACTURE_ORIF_INTRAMEDULLARY_NAIL_PROBABILITY
                else "intramedullary nail"
            ]
        else:
            proc_type = "hemiarthroplasty"
            proc_code_jp = load_code_mapping("procedure", "JP")["hemiarthroplasty_hip"]
            proc_code_us = load_code_mapping("procedure", "US")["hemiarthroplasty_hip"]
            implants = ["bipolar femoral prosthesis"]
    else:
        # Read procedure codes from disease YAML
        proc_type = proc_data.get("type", "surgery").split("/")[0].strip().split(" or ")[0].strip()
        proc_code_jp = proc_data.get("procedure_code_jp", "")
        proc_code_us = proc_data.get("procedure_code_us", "")
        implants = []

    # Primary code for this country
    proc_code = country_procedure_code(country, {"k-codes": proc_code_jp, "cpt": proc_code_us})

    # Surgical approach from disease YAML (protocol.procedure.approach)
    approach_map = proc_data.get("approach", {}) or {}
    approach = approach_map.get(proc_type, "") if isinstance(approach_map, dict) else str(approach_map)

    # Metadata (SNOMED category / body site), outcome, location
    meta = _PROCEDURE_METADATA.get(proc_type) or _PROCEDURE_METADATA["surgery"]
    or_number = int(rng.integers(1, max(2, operating_rooms + 1)))
    location_id = f"loc-or-{or_number}"

    record = ProcedureRecord(
        procedure_id=f"PROC-{patient.patient_id}-001",
        patient_id=patient.patient_id,
        encounter_id=encounter_id,
        procedure_type=proc_type,
        procedure_code=proc_code,
        procedure_code_jp=proc_code_jp,
        procedure_code_us=proc_code_us,
        start_datetime=surgery_start,
        end_datetime=surgery_start + timedelta(minutes=duration),
        duration_minutes=duration,
        primary_surgeon_id=surgeon_id,
        anesthesiologist_id=anesthesiologist_id,
        anesthesia_type=anesthesia_type,
        asa_class=asa,
        estimated_blood_loss_ml=ebl,
        implants_used=implants,
        intraop_complications=intraop_comps,
        preop_diagnosis=disease_id,
        postop_diagnosis=disease_id,
        approach=approach,
        category_code=meta.category_code,
        body_site_code=meta.body_site_code,
        outcome_code=_derive_outcome(intraop_comps),
        complication_codes=_map_complications(intraop_comps),
        location_id=location_id,
    )

    # State impacts from surgery
    state_impacts: dict[str, float] = {}
    # Blood loss → anemia
    if ebl > EBL_ANEMIA_LIFT_THRESHOLD_ML:
        state_impacts["anemia_level"] = ebl / EBL_ANEMIA_LIFT_DIVISOR
    # Fluid administration
    state_impacts["volume_status"] = SURGERY_VOLUME_LIFT
    # Inflammation from tissue trauma
    state_impacts["inflammation_level"] = SURGERY_INFLAMMATION_LIFT
    # Excessive bleeding → perfusion impact
    if ebl > EBL_MAJOR_BLEED_THRESHOLD_ML:
        state_impacts["perfusion_status"] = EBL_MAJOR_BLEED_PERFUSION_PENALTY

    return record, state_impacts


# ============================================================
# SNOMED CT codes used by this module (resolved via clinosim.codes at output time)
# ============================================================
# SNOMED CT category / outcome sentinels, complication map, and the
# per-procedure_type metadata table all live in
# `clinosim/codes/data/procedure-snomed-metadata.yaml` (hardcoded-review
# Phase A9). The module-level aliases below preserve the historical
# Python names so every call site (`simulate_surgery`,
# `generate_bedside_procedures`, `_map_complications`, `_derive_outcome`)
# stays unchanged.
#
# feedback FB-F8: SNOMED 103693007 is inactive; active 386053000
# "Evaluation procedure" replaces it (cycle 8 extension). The replacement
# is applied in the yaml.


@cache
def _procedure_snomed_metadata() -> dict[str, Any]:
    """Load the procedure-SNOMED metadata authority yaml."""
    return data_table("procedure-snomed-metadata")


def _sct_category(key: str) -> str:
    return str((_procedure_snomed_metadata().get("category") or {}).get(key) or "")


def _sct_outcome(key: str) -> str:
    return str((_procedure_snomed_metadata().get("outcome") or {}).get(key) or "")


_SCT_CATEGORY_SURGICAL = _sct_category("surgical")
_SCT_CATEGORY_DIAGNOSTIC = _sct_category("diagnostic")
_SCT_CATEGORY_THERAPEUTIC = _sct_category("therapeutic")

_SCT_OUTCOME_SUCCESS = _sct_outcome("success")
_SCT_OUTCOME_PARTIAL = _sct_outcome("partial")
_SCT_OUTCOME_UNSUCCESS = _sct_outcome("unsuccess")


# Complication key → SNOMED code.
def _complication_sct_from_yaml() -> dict[str, str]:
    raw = _procedure_snomed_metadata().get("complications", {}) or {}
    return {str(k): str(v) for k, v in raw.items()}


_COMPLICATION_SCT: dict[str, str] = _complication_sct_from_yaml()


# ============================================================
# Procedure metadata table
# ============================================================
# Maps procedure_type → FHIR Procedure category + body site (SNOMED).
# Used by both simulate_surgery and generate_bedside_procedures to populate
# the structural FHIR fields.
@dataclass(frozen=True)
class ProcedureMeta:
    category_code: str  # SNOMED category
    body_site_code: str = ""  # SNOMED body site (empty if n/a)


def _procedure_metadata_from_yaml() -> dict[str, ProcedureMeta]:
    raw = _procedure_snomed_metadata()
    cat_map: dict[str, str] = {str(k): str(v) for k, v in (raw.get("category") or {}).items()}
    out: dict[str, ProcedureMeta] = {}
    for key, row in (raw.get("procedures", {}) or {}).items():
        if not isinstance(row, dict):
            continue
        cat_key = str(row.get("category") or "")
        out[str(key)] = ProcedureMeta(
            category_code=cat_map.get(cat_key, ""),
            body_site_code=str(row.get("body_site") or ""),
        )
    return out


_PROCEDURE_METADATA: dict[str, ProcedureMeta] = _procedure_metadata_from_yaml()


def _derive_outcome(complications: list[str]) -> str:
    """Derive SNOMED outcome code from complication list."""
    if not complications:
        return _SCT_OUTCOME_SUCCESS
    # Anesthesia hypotension / minor bleeding → partially successful
    return _SCT_OUTCOME_PARTIAL


def _map_complications(intraop_comps: list[str]) -> list[str]:
    """Map internal complication keys → SNOMED codes."""
    return [_COMPLICATION_SCT[c] for c in intraop_comps if c in _COMPLICATION_SCT]


# ============================================================
# Bedside / routine inpatient procedures
# ============================================================

# (procedure_type, CPT, K-code, name_en, name_ja, anesthesia) — built from the
# procedure catalog (codes/data/clinosim-procedure-catalog.yaml, Issue #2263).
_BEDSIDE_PROCEDURES: list[tuple[str, str, str, str, str, str]] = [
    (
        str(e["type"]),
        str(e.get("cpt") or ""),
        str(e.get("k_code") or ""),
        str(e["name"]["en"]),
        str(e["name"]["ja"]),
        str(e["anesthesia"]),
    )
    for e in bedside_procedures()
]

# Procedure dispatch per disease / ED condition, from
# reference_data/procedure_rules.yaml (Issue #2525): `bedside_rules` draw from
# the encounter RNG; `isolated_rules` (Issue #939 — PCI, pacemaker, craniotomy,
# ileus tube, bowel resection) each draw from a per-(encounter, procedure)
# sub-RNG (`issue939_procedure_seed`) so the shared stream is untouched.
_ProcedureRules = list[tuple[list[str], list[tuple[str, float]]]]


class _Rule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    diseases: list[str] = Field(min_length=1)
    procedures: dict[str, float] = Field(min_length=1)

    @field_validator("diseases")
    @classmethod
    def _known_diseases(cls, diseases: list[str]) -> list[str]:
        # Matching is exact, so an unknown id would never fire (Issue #2526).
        modules = Path(__file__).resolve().parents[1]
        known = {p.stem for d in ("disease", "encounter") for p in (modules / d / "reference_data").glob("*.yaml")}
        unknown = sorted(set(diseases) - known)
        if unknown:
            raise ValueError(f"procedure_rules.yaml: unknown disease / ED condition ids {unknown}")
        return diseases

    @field_validator("procedures")
    @classmethod
    def _known_procedures(cls, procedures: dict[str, float]) -> dict[str, float]:
        known = {p[0] for p in _BEDSIDE_PROCEDURES}
        unknown = sorted(set(procedures) - known)
        if unknown:
            raise ValueError(f"procedure_rules.yaml: unknown procedures {unknown}")
        bad = sorted(k for k, v in procedures.items() if not 0.0 <= v <= 1.0)
        if bad:
            raise ValueError(f"procedure_rules.yaml: probabilities outside [0, 1] for {bad}")
        return procedures


class _ProcedureRulesConfig(BaseModel):
    """Shape of procedure_rules.yaml (validated at load)."""

    model_config = ConfigDict(extra="forbid")

    metadata: dict[str, Any] = Field(default_factory=dict)
    bedside_rules: list[_Rule]
    isolated_rules: list[_Rule]


def _load_procedure_rules() -> tuple[_ProcedureRules, _ProcedureRules]:
    """Both rule tables, validated by ``_ProcedureRulesConfig``: every disease
    names a disease or ED condition YAML, every procedure is in the bedside
    catalog, and every probability lies in [0, 1]."""
    data = load_data_yaml(Path(__file__).resolve().parent / "reference_data" / "procedure_rules.yaml")
    config = _ProcedureRulesConfig.model_validate(data)
    return (
        [(list(r.diseases), list(r.procedures.items())) for r in config.bedside_rules],
        [(list(r.diseases), list(r.procedures.items())) for r in config.isolated_rules],
    )


_PROCEDURE_RULES, _ISSUE939_PROCEDURE_RULES = _load_procedure_rules()

# Procedure types dispatched from `_ISSUE939_PROCEDURE_RULES` — used to guard
# against accidental duplication into `_PROCEDURE_RULES` in future edits.
_ISSUE939_PROCEDURE_TYPES: frozenset[str] = frozenset(
    proc_type for _match, rules in _ISSUE939_PROCEDURE_RULES for proc_type, _prob in rules
)


def build_intubation_procedure(
    patient_id: str, encounter_id: str, start: datetime, country: str, procedure_id: str
) -> ProcedureRecord:
    """Endotracheal intubation performed when the state crosses the airway
    threshold (Issue #2091): CPT 31500 / K-code J044, sedation, fixed duration
    (no RNG draw)."""
    spec = {p[0]: p for p in _BEDSIDE_PROCEDURES}["intubation"]
    _, cpt, kcode, _name_en, _name_ja, anesthesia = spec
    meta = _PROCEDURE_METADATA.get("intubation")
    return ProcedureRecord(
        procedure_id=procedure_id,
        patient_id=patient_id,
        encounter_id=encounter_id,
        procedure_type="intubation",
        procedure_code=country_procedure_code(country, {"k-codes": kcode, "cpt": cpt}),
        procedure_code_jp=kcode,
        procedure_code_us=cpt,
        start_datetime=start,
        end_datetime=start + timedelta(minutes=int(BEDSIDE_DURATION_MEAN_MIN)),
        duration_minutes=int(BEDSIDE_DURATION_MEAN_MIN),
        primary_surgeon_id="",
        anesthesia_type=anesthesia,
        category_code=meta.category_code if meta else _SCT_CATEGORY_THERAPEUTIC,
        body_site_code=meta.body_site_code if meta else "",
        outcome_code=_SCT_OUTCOME_SUCCESS,
        complication_codes=[],
        location_id="",
    )


def _bedside_record(
    patient_id: str,
    encounter_id: str,
    proc_type: str,
    spec: tuple[str, str, str, str, str, str],
    code: str,
    start: datetime,
    duration: int,
    proc_idx: int,
    fallback_category: str,
) -> ProcedureRecord:
    """One bedside procedure of the catalogue ``spec`` (names resolved downstream, AD-30)."""
    _, cpt, kcode, _name_en, _name_ja, anesthesia = spec
    meta = _PROCEDURE_METADATA.get(proc_type)
    return ProcedureRecord(
        procedure_id=f"PROC-{patient_id}-{proc_idx + 2:03d}",
        patient_id=patient_id,
        encounter_id=encounter_id,
        procedure_type=proc_type,
        procedure_code=code,
        procedure_code_jp=kcode,
        procedure_code_us=cpt,
        start_datetime=start,
        end_datetime=start + timedelta(minutes=duration),
        duration_minutes=duration,
        primary_surgeon_id="",
        anesthesia_type=anesthesia,
        category_code=meta.category_code if meta else fallback_category,
        body_site_code=meta.body_site_code if meta else "",
        outcome_code=_SCT_OUTCOME_SUCCESS,
        complication_codes=[],
        location_id="",
    )


def age_gated_procedures(
    patient_id: str,
    encounter_id: str,
    rules: list[dict],
    age_days: int,
    start: datetime,
    first_index: int,
    country: str,
) -> list[ProcedureRecord]:
    """The protocol's ``procedures_by_age_days`` performed for a patient
    ``age_days`` old (Issue #3063), numbered from ``first_index``. No random
    draw: each rule in its age range is performed, for the mean bedside
    duration."""
    proc_lookup = {p[0]: p for p in _BEDSIDE_PROCEDURES}
    results: list[ProcedureRecord] = []
    for rule in rules:
        if not int(rule["min_age_days"]) <= age_days <= int(rule["max_age_days"]):
            continue
        proc_type = str(rule["procedure"])
        spec = proc_lookup[proc_type]
        code = country_procedure_code(country, {"k-codes": spec[2], "cpt": spec[1]})
        results.append(
            _bedside_record(
                patient_id,
                encounter_id,
                proc_type,
                spec,
                code,
                start,
                int(BEDSIDE_DURATION_MEAN_MIN),
                first_index + len(results),
                _SCT_CATEGORY_THERAPEUTIC,
            )
        )
    return results


def generate_bedside_procedures(
    patient_id: str,
    encounter_id: str,
    disease_id: str,
    admission_time: datetime,
    severity: str,
    rng: np.random.Generator,
    country: str,
) -> list[ProcedureRecord]:
    """Generate bedside/routine procedures based on disease and severity.

    Uses rule-based matching: disease_id is matched against _PROCEDURE_RULES,
    and each candidate procedure fires with its probability, scaled by severity.
    """
    severity_mult = {
        "severe": BEDSIDE_SEVERITY_SEVERE_MULTIPLIER,
        "moderate": BEDSIDE_SEVERITY_MODERATE_MULTIPLIER,
        "mild": BEDSIDE_SEVERITY_MILD_MULTIPLIER,
    }.get(severity, BEDSIDE_SEVERITY_MULTIPLIER_FALLBACK)
    proc_lookup = {p[0]: p for p in _BEDSIDE_PROCEDURES}

    triggered: dict[str, float] = {}  # procedure_type → max probability
    for disease_match, proc_list in _PROCEDURE_RULES:
        if disease_id not in disease_match:
            continue
        for proc_type, prob in proc_list:
            # Take the highest probability across matching rules
            triggered[proc_type] = max(triggered.get(proc_type, 0), prob)

    results: list[ProcedureRecord] = []
    proc_idx = 0
    for proc_type, base_prob in triggered.items():
        prob = min(1.0, base_prob * severity_mult)
        if rng.random() >= prob:
            continue
        spec = proc_lookup.get(proc_type)
        if not spec:
            continue

        _, cpt, kcode, *_ = spec
        # A procedure without a code in this country (JP peripheral IV: no
        # separate fee; US oxygen: no CPT) is still recorded; the FHIR
        # Procedure then carries its name and the other country's coding,
        # never an empty code (Issue #2340).
        code = country_procedure_code(country, {"k-codes": kcode, "cpt": cpt})
        # Names not stored — FHIR adapter resolves via code_lookup (AD-30)

        # Timing: most bedside procedures happen within first 24h
        hours_offset = max(BEDSIDE_HOURS_OFFSET_MIN, float(rng.exponential(BEDSIDE_HOURS_OFFSET_EXPONENTIAL_MEAN)))
        proc_time = admission_time + timedelta(hours=hours_offset)
        duration = int(max(BEDSIDE_DURATION_MIN_MIN, rng.normal(BEDSIDE_DURATION_MEAN_MIN, BEDSIDE_DURATION_STD_MIN)))

        results.append(
            _bedside_record(
                patient_id,
                encounter_id,
                proc_type,
                spec,
                code,
                proc_time,
                duration,
                proc_idx,
                _SCT_CATEGORY_THERAPEUTIC,
            )
        )
        proc_idx += 1

    # Issue #939 — isolated sub-RNG loop for cardiology / neurosurgery /
    # GI-obstruction interventions. Runs AFTER the shared-rng loop so
    # `proc_idx` continues incrementing (procedure_id uniqueness) but the
    # per-encounter sub-RNG does not touch the shared patient stream.
    for disease_match, proc_list in _ISSUE939_PROCEDURE_RULES:
        if disease_id not in disease_match:
            continue
        for proc_type, base_prob in proc_list:
            sub_rng = determinism.default_rng(issue939_procedure_seed(encounter_id, proc_type))
            prob = min(1.0, base_prob * severity_mult)
            if sub_rng.random() >= prob:
                continue
            spec = proc_lookup.get(proc_type)
            if not spec:
                continue

            _, cpt, kcode, *_ = spec
            # An intervention without a code in the country's procedure code
            # system is not dispatched (Issue #3144; every catalogued
            # intervention has both a CPT and a K-code).
            code = country_procedure_code(country, {"k-codes": kcode, "cpt": cpt})
            if not code:
                continue

            hours_offset = max(
                BEDSIDE_HOURS_OFFSET_MIN,
                float(sub_rng.exponential(BEDSIDE_HOURS_OFFSET_EXPONENTIAL_MEAN)),
            )
            proc_time = admission_time + timedelta(hours=hours_offset)
            duration = int(
                max(
                    BEDSIDE_DURATION_MIN_MIN,
                    sub_rng.normal(BEDSIDE_DURATION_MEAN_MIN, BEDSIDE_DURATION_STD_MIN),
                )
            )

            results.append(
                _bedside_record(
                    patient_id,
                    encounter_id,
                    proc_type,
                    spec,
                    code,
                    proc_time,
                    duration,
                    proc_idx,
                    _SCT_CATEGORY_SURGICAL,
                )
            )
            proc_idx += 1

    return results


def generate_rehab_sessions(
    patient_id: str,
    encounter_id: str,
    surgery_date: datetime,
    total_days: int,
    rng: np.random.Generator,
    country: str,
) -> list[RehabSession]:
    """Generate rehabilitation sessions for post-surgical recovery."""
    sessions: list[RehabSession] = []

    # Rehab starts POD 1 (day after surgery)
    start_day = REHAB_START_POD
    duration = load_care_practice(country).rehab_session_minutes  # Issue #3142

    activities_by_phase = {
        "early": ["bed exercises", "sitting up", "standing with assist"],
        "mid": ["walker ambulation", "stair practice", "transfer training"],
        "late": ["independent ambulation", "ADL practice", "stair climbing"],
    }

    for day_offset in range(start_day, total_days):
        # Skip some days randomly (weekend reduction, patient fatigue)
        if rng.random() < REHAB_SKIP_DAY_PROBABILITY:
            continue

        # Determine phase
        if day_offset <= REHAB_PHASE_EARLY_MAX_POD:
            phase = "early"
        elif day_offset <= REHAB_PHASE_MID_MAX_POD:
            phase = "mid"
        else:
            phase = "late"

        activities = list(
            rng.choice(activities_by_phase[phase], size=min(3, len(activities_by_phase[phase])), replace=False)
        )  # noqa: E501

        pain = int(
            max(
                REHAB_PAIN_MIN_SCORE,
                min(
                    REHAB_PAIN_MAX_SCORE,
                    rng.normal(REHAB_PAIN_BASE_SCORE - day_offset * REHAB_PAIN_DECAY_PER_POD, REHAB_PAIN_STD),
                ),
            )
        )

        participation = "good"
        if pain > REHAB_PAIN_FAIR_PARTICIPATION_THRESHOLD:
            participation = "fair"
        if rng.random() < REHAB_REFUSAL_PROBABILITY:
            participation = "refused"

        progress = "improved" if day_offset > REHAB_IMPROVED_MIN_POD else "stable"
        if participation == "refused":
            progress = "unable_to_assess"

        session = RehabSession(
            session_id=f"REHAB-{patient_id}-{day_offset:03d}",
            patient_id=patient_id,
            encounter_id=encounter_id,
            therapy_type="PT",
            session_date=surgery_date + timedelta(days=day_offset, hours=REHAB_SESSION_START_HOUR),
            duration_minutes=duration,
            day_post_op=day_offset,
            activities=activities,
            patient_participation=participation,
            pain_score=pain,
            functional_progress=progress,
        )
        sessions.append(session)

    return sessions
