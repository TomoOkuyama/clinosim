"""Diagnosis-coding rule tables of the encounter simulators (Issue #2552).

The tables live in ``reference_data/diagnosis_rules.yaml``; this module loads
them once, validates every code, id and lab name they name, and answers the
lookups the outpatient, unknown-condition and inpatient daily-loop simulators
make.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from clinosim.codes import code_exists, system_key_for
from clinosim.country_profile import supported_countries
from clinosim.datafiles import load_validated_yaml

_YAML = Path(__file__).resolve().parent / "reference_data" / "diagnosis_rules.yaml"
_MODULES = Path(__file__).resolve().parents[1] / "modules"


class _VisitTypeCodes(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    default: str
    by_visit: dict[str, str] = Field(default_factory=dict)


class _VisitPurposeCodes(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    fallback: str
    post_discharge: str
    by_visit_type: dict[str, _VisitTypeCodes]


class _UnknownCodes(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    admission: str
    unresolved: str
    partially_resolved: str


class _UnknownConditionCodes(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    default: _UnknownCodes
    by_pattern: dict[str, _UnknownCodes]


class _LabFinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    finding: str
    above: float


class _DifferentialFindings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    labs: dict[str, _LabFinding]
    day1_imaging: dict[str, list[str]]


class _SevereSepsis(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    vasopressor_classes: list[str]
    labs_at_or_above: dict[str, float]
    labs_below: dict[str, float]


class _SepticShock(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    vasopressor_classes: list[str]
    map_below: float
    labs_above: dict[str, float]


class _SepsisSeverity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    codes: list[str]
    sepsis_code: str
    severe_sepsis: _SevereSepsis
    septic_shock: _SepticShock


class DiagnosisRulesFile(BaseModel):
    """Shape of ``diagnosis_rules.yaml`` (Issue #2956). The codes, ids and
    labs it names are checked against their registries by ``_check``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    visit_purpose_codes: _VisitPurposeCodes
    unknown_condition_codes: _UnknownConditionCodes
    differential_findings: _DifferentialFindings
    sepsis_severity: _SepsisSeverity


@dataclass(frozen=True)
class UnknownConditionCodes:
    """ICD codes of an unknown-condition admission."""

    admission: str
    unresolved: str
    partially_resolved: str


@dataclass(frozen=True)
class LabFindingRule:
    """A differential finding that is true when the lab value is above ``above``."""

    finding: str
    above: float


@dataclass(frozen=True)
class OrganDysfunctionRule:
    """Severe sepsis: a vasopressor given, or a lab at or above / below its
    threshold (SOFA organ score of 2 or more)."""

    code: str
    vasopressor_classes: frozenset[str]
    labs_at_or_above: dict[str, float]
    labs_below: dict[str, float]


@dataclass(frozen=True)
class SepticShockRule:
    """Septic shock: a vasopressor given, a MAP below ``map_below`` and a lab
    above its threshold (lactate) — Sepsis-3."""

    code: str
    vasopressor_classes: frozenset[str]
    map_below: float
    labs_above: dict[str, float]


@dataclass(frozen=True)
class SepsisSeverityRules:
    """Severity code of a sepsis discharge diagnosis (Issue #3269)."""

    codes: frozenset[str]
    sepsis_code: str
    severe_sepsis: OrganDysfunctionRule
    septic_shock: SepticShockRule


@dataclass(frozen=True)
class _DiagnosisRules:
    visit_fallback: str
    post_discharge: str
    visit_type_default: dict[str, str]
    visit_codes: dict[tuple[str, str], str]
    unknown_default: UnknownConditionCodes
    unknown_by_pattern: dict[str, UnknownConditionCodes]
    lab_findings: dict[str, LabFindingRule]
    day1_imaging: dict[str, tuple[str, ...]]
    sepsis_severity: SepsisSeverityRules


def _unknown_codes(entry: dict[str, Any]) -> UnknownConditionCodes:
    return UnknownConditionCodes(
        admission=str(entry["admission"]),
        unresolved=str(entry["unresolved"]),
        partially_resolved=str(entry["partially_resolved"]),
    )


def _sepsis_severity(entry: dict[str, Any]) -> SepsisSeverityRules:
    severe, shock = entry["severe_sepsis"], entry["septic_shock"]
    return SepsisSeverityRules(
        codes=frozenset(str(c) for c in entry["codes"]),
        sepsis_code=str(entry["sepsis_code"]),
        severe_sepsis=OrganDysfunctionRule(
            code=str(severe["code"]),
            vasopressor_classes=frozenset(str(c) for c in severe["vasopressor_classes"]),
            labs_at_or_above={str(k): float(v) for k, v in severe["labs_at_or_above"].items()},
            labs_below={str(k): float(v) for k, v in severe["labs_below"].items()},
        ),
        septic_shock=SepticShockRule(
            code=str(shock["code"]),
            vasopressor_classes=frozenset(str(c) for c in shock["vasopressor_classes"]),
            map_below=float(shock["map_below"]),
            labs_above={str(k): float(v) for k, v in shock["labs_above"].items()},
        ),
    )


def _registered_in_both_locales(code: str) -> bool:
    """Whether ``code``, mapped for each country, is registered in that
    country's diagnosis code system (US ICD-10-CM, JP WHO ICD-10), for every
    supported country (country profile, Issue #3143)."""
    from clinosim.locale.loader import map_diagnosis_code

    return all(
        code_exists(system_key_for("diagnosis", country), map_diagnosis_code(code, country))
        for country in supported_countries()
    )


def _check(rules: _DiagnosisRules) -> None:
    """Every ICD code is registered, every visit / disease id names a real
    pediatric schedule entry or disease YAML, every pattern has a label in the
    unknown-condition catalog and every lab is a known analyte."""
    from clinosim.codes.drugs import all_drug_ids, drug_classes
    from clinosim.locale.loader import load_narrative_labels
    from clinosim.modules.observation.engine import get_lab_unit
    from clinosim.modules.pediatric.calendar import load_pediatric_schedule

    unknown_codes = [rules.unknown_default, *rules.unknown_by_pattern.values()]
    sepsis = rules.sepsis_severity
    codes = {
        *sepsis.codes,
        sepsis.sepsis_code,
        sepsis.severe_sepsis.code,
        sepsis.septic_shock.code,
        rules.visit_fallback,
        rules.post_discharge,
        *rules.visit_type_default.values(),
        *rules.visit_codes.values(),
        *(c for u in unknown_codes for c in (u.admission, u.unresolved, u.partially_resolved)),
    }
    problems = [f"unregistered ICD-10 code {c}" for c in sorted(codes) if not _registered_in_both_locales(c)]
    pediatric_ids = {str(e.get("disease_id", "")) for e in load_pediatric_schedule().values()}
    problems += [
        f"unknown pediatric visit {visit}"
        for vtype, visit in sorted(rules.visit_codes)
        if vtype == "pediatric_visit" and visit not in pediatric_ids
    ]
    pattern_labels = load_narrative_labels().get("unknown_condition_pattern", {})
    problems += [f"unknown condition pattern {p}" for p in sorted(rules.unknown_by_pattern) if p not in pattern_labels]
    sepsis_labs = {
        *rules.lab_findings,
        *sepsis.severe_sepsis.labs_at_or_above,
        *sepsis.severe_sepsis.labs_below,
        *sepsis.septic_shock.labs_above,
    }
    problems += [f"unknown lab {lab}" for lab in sorted(sepsis_labs) if not get_lab_unit(lab)]
    problems += [
        f"sepsis_severity: {c} is not one of codes"
        for c in sorted({sepsis.sepsis_code, sepsis.severe_sepsis.code, sepsis.septic_shock.code} - sepsis.codes)
    ]
    catalog_classes = {c for d in all_drug_ids() for c in drug_classes(d)}
    problems += [
        f"unknown drug class {c}"
        for c in sorted(sepsis.severe_sepsis.vasopressor_classes | sepsis.septic_shock.vasopressor_classes)
        if c not in catalog_classes
    ]
    disease_ids = {p.stem for p in (_MODULES / "disease" / "reference_data").glob("*.yaml")}
    problems += [f"unknown disease {d}" for d in sorted(rules.day1_imaging) if d not in disease_ids]
    if problems:
        raise ValueError(f"diagnosis_rules.yaml: {'; '.join(problems)}")


@cache
def _rules() -> _DiagnosisRules:
    data = load_validated_yaml(_YAML, DiagnosisRulesFile)
    visit = data["visit_purpose_codes"]
    by_type = visit["by_visit_type"]
    unknown = data["unknown_condition_codes"]
    findings = data["differential_findings"]
    rules = _DiagnosisRules(
        visit_fallback=str(visit["fallback"]),
        post_discharge=str(visit["post_discharge"]),
        visit_type_default={str(t): str(e["default"]) for t, e in by_type.items()},
        visit_codes={
            (str(t), str(v)): str(code) for t, e in by_type.items() for v, code in (e.get("by_visit") or {}).items()
        },
        unknown_default=_unknown_codes(unknown["default"]),
        unknown_by_pattern={str(p): _unknown_codes(e) for p, e in unknown["by_pattern"].items()},
        lab_findings={
            str(lab): LabFindingRule(finding=str(e["finding"]), above=float(e["above"]))
            for lab, e in findings["labs"].items()
        },
        day1_imaging={str(d): tuple(str(f) for f in fs) for d, fs in findings["day1_imaging"].items()},
        sepsis_severity=_sepsis_severity(data["sepsis_severity"]),
    )
    _check(rules)
    return rules


def visit_purpose_code(visit_type: str, visit_id: str) -> str:
    """The Z-family code of an outpatient visit purpose (``""`` when the visit
    type has none)."""
    rules = _rules()
    return rules.visit_codes.get((visit_type, visit_id)) or rules.visit_type_default.get(visit_type, "")


def post_discharge_visit_code() -> str:
    """The code of a post-discharge follow-up visit without a chronic code."""
    return _rules().post_discharge


def fallback_visit_code() -> str:
    """The code of an outpatient visit nothing else codes."""
    return _rules().visit_fallback


def unknown_condition_codes(pattern: str) -> UnknownConditionCodes:
    """Admission / discharge codes of the unknown-condition pattern ``pattern``."""
    rules = _rules()
    return rules.unknown_by_pattern.get(pattern, rules.unknown_default)


def lab_finding_rules() -> dict[str, LabFindingRule]:
    """Lab name → the differential finding its value decides."""
    return _rules().lab_findings


def day1_imaging_findings(disease_id: str) -> tuple[str, ...]:
    """Imaging findings that are true on hospital day 1 for ``disease_id``."""
    return _rules().day1_imaging.get(disease_id, ())


def sepsis_severity_rules() -> SepsisSeverityRules:
    """The sepsis severity-code rules (Issue #3269)."""
    return _rules().sepsis_severity
