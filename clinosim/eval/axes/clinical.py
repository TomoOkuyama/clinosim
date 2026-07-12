"""Clinical axis — coherence checks (5 checks, MVP)."""

from __future__ import annotations

from datetime import date

from clinosim.audit.types import Cohort
from clinosim.eval.engine import EvalCheck, Outcome, Severity

# Physiological plausibility bounds. Values outside these are almost
# certainly a bug — not a real edge case. All in the units clinosim emits.
_LAB_BOUNDS = {
    # LOINC → (min, max, unit hint)
    "6690-2":  (0.0, 500.0, "WBC 10^9/L"),                # WBC
    "718-7":   (0.0, 25.0, "Hb g/dL"),                    # Hemoglobin
    "2160-0":  (0.0, 30.0, "Creatinine mg/dL"),           # Serum creatinine
    "2345-7":  (0.0, 1500.0, "Glucose mg/dL"),            # Serum glucose
    "2823-3":  (0.0, 10.0, "Potassium mEq/L"),            # Serum potassium
    "2951-2":  (0.0, 200.0, "Sodium mEq/L"),              # Serum sodium
    "1975-2":  (0.0, 50.0, "Total bilirubin mg/dL"),      # Total bili
    "6301-6":  (0.5, 20.0, "PT-INR"),                     # PT-INR
}


def run(cohort: Cohort, country: str) -> list[EvalCheck]:
    return [
        _check_lab_values_physiological_range(cohort, country),
        _check_age_condition_consistency(cohort, country),
        _check_medication_date_sanity(cohort, country),
        _check_encounter_temporal_ordering(cohort, country),
        _check_condition_encounter_link(cohort, country),
    ]


# --------------------------------------------------------------------------- #

def _check_lab_values_physiological_range(cohort: Cohort, country: str) -> EvalCheck:
    """Lab values must fall inside gross physiological bounds. Any WBC
    of 10^30 or negative creatinine is a defect."""
    out_of_range: dict[str, int] = {}
    total_checked = 0
    for row in _read(cohort, country, "Observation"):
        code_bag = (row.get("code") or {}).get("coding") or []
        loinc_code = _first_code_for_system(code_bag, "http://loinc.org")
        if not loinc_code or loinc_code not in _LAB_BOUNDS:
            continue
        vq = row.get("valueQuantity") or {}
        val = vq.get("value")
        if val is None:
            continue
        total_checked += 1
        lo, hi, _hint = _LAB_BOUNDS[loinc_code]
        if not (lo <= val <= hi):
            out_of_range[loinc_code] = out_of_range.get(loinc_code, 0) + 1

    if total_checked == 0:
        return EvalCheck(
            name="lab_values_physiological_range",
            outcome=Outcome.NA,
            severity=Severity.MAJOR,
            message="No LOINC-coded lab values in the checked set were found.",
        )
    if not out_of_range:
        return EvalCheck(
            name="lab_values_physiological_range",
            outcome=Outcome.PASS,
            severity=Severity.MAJOR,
            message=f"{total_checked} lab value(s) checked; all within physiological bounds.",
            detail={"checked": total_checked, "loinc_bounds": _bounds_summary()},
        )
    return EvalCheck(
        name="lab_values_physiological_range",
        outcome=Outcome.FAIL,
        severity=Severity.MAJOR,
        message=f"{sum(out_of_range.values())} lab value(s) out of physiological bounds",
        detail={"by_loinc": out_of_range, "checked": total_checked},
    )


def _check_age_condition_consistency(cohort: Cohort, country: str) -> EvalCheck:
    """Adult-only conditions must not appear on pediatric patients (< 12 y),
    pediatric-only conditions must not appear on adults (> 18 y)."""
    # Build Patient.id → age (years) map from birthDate + any death or
    # first-encounter reference.
    ages_by_patient = _patient_ages(cohort, country)

    # These ICD-10-CM (US) / ICD-10 (JP) codes are strictly adult-onset.
    adult_only_prefixes = {"I10", "I25", "I48", "I50", "E11", "N18", "N40", "F03"}
    peds_only_prefixes: set[str] = set()  # Reserved — clinosim does not model peds diseases yet.

    problems: list[str] = []
    for row in _read(cohort, country, "Condition"):
        pid = (row.get("subject") or {}).get("reference", "").split("/", 1)[-1]
        age = ages_by_patient.get(pid)
        if age is None:
            continue
        codes = (row.get("code") or {}).get("coding") or []
        for c in codes:
            code = c.get("code", "")
            for prefix in adult_only_prefixes:
                if code.startswith(prefix) and age < 12:
                    problems.append(f"pediatric patient (age {age}) with {code}")
                    break
            for prefix in peds_only_prefixes:
                if code.startswith(prefix) and age > 18:
                    problems.append(f"adult patient (age {age}) with peds-only {code}")
                    break
        if len(problems) > 20:
            break

    if not problems:
        return EvalCheck(
            name="age_condition_consistency",
            outcome=Outcome.PASS,
            severity=Severity.MAJOR,
            message="No adult-only conditions on pediatric patients.",
        )
    return EvalCheck(
        name="age_condition_consistency",
        outcome=Outcome.FAIL,
        severity=Severity.MAJOR,
        message=f"{len(problems)} age-condition mismatch(es)",
        detail={"problems_sample": problems[:20]},
    )


def _check_medication_date_sanity(cohort: Cohort, country: str) -> EvalCheck:
    """MedicationRequest.authoredOn must fall after the patient's birthDate."""
    births = {row.get("id"): row.get("birthDate") for row in _read(cohort, country, "Patient")}
    problems: list[str] = []
    for row in _read(cohort, country, "MedicationRequest"):
        pid = (row.get("subject") or {}).get("reference", "").split("/", 1)[-1]
        birth = births.get(pid)
        authored = (row.get("authoredOn") or "")[:10]
        if not birth or not authored:
            continue
        if authored < birth:
            problems.append(f"MedicationRequest/{row.get('id', '?')} authoredOn={authored} < birthDate={birth}")

    if not problems:
        return EvalCheck(
            name="medication_date_sanity",
            outcome=Outcome.PASS,
            severity=Severity.MAJOR,
            message="No MedicationRequests are dated before the patient's birth.",
        )
    return EvalCheck(
        name="medication_date_sanity",
        outcome=Outcome.FAIL,
        severity=Severity.MAJOR,
        message=f"{len(problems)} MedicationRequest date sanity violation(s)",
        detail={"problems_sample": problems[:10]},
    )


def _check_encounter_temporal_ordering(cohort: Cohort, country: str) -> EvalCheck:
    """Encounter.period.start ≤ Encounter.period.end. Both dates required
    for finished encounters; in-progress encounters may omit end."""
    problems: list[str] = []
    for row in _read(cohort, country, "Encounter"):
        period = row.get("period") or {}
        start = period.get("start")
        end = period.get("end")
        if start and end and end < start:
            problems.append(f"Encounter/{row.get('id', '?')} end {end} before start {start}")

    if not problems:
        return EvalCheck(
            name="encounter_temporal_ordering",
            outcome=Outcome.PASS,
            severity=Severity.MAJOR,
            message="All Encounter periods are non-decreasing.",
        )
    return EvalCheck(
        name="encounter_temporal_ordering",
        outcome=Outcome.FAIL,
        severity=Severity.MAJOR,
        message=f"{len(problems)} Encounter(s) with reversed period",
        detail={"problems_sample": problems[:10]},
    )


def _check_condition_encounter_link(cohort: Cohort, country: str) -> EvalCheck:
    """When Condition.encounter is set, it must reference an emitted
    Encounter. (A missing encounter link is allowed — used for
    chronic problem-list items.)"""
    valid_encounters = {row.get("id") for row in _read(cohort, country, "Encounter")}
    problems: list[str] = []
    for row in _read(cohort, country, "Condition"):
        enc_ref = (row.get("encounter") or {}).get("reference", "")
        if enc_ref.startswith("Encounter/"):
            enc_id = enc_ref.split("/", 1)[1]
            if enc_id not in valid_encounters:
                problems.append(f"Condition/{row.get('id', '?')} → {enc_ref} (unresolved)")

    if not problems:
        return EvalCheck(
            name="condition_encounter_link",
            outcome=Outcome.PASS,
            severity=Severity.MINOR,
            message="All Condition.encounter references resolve to emitted Encounters.",
        )
    return EvalCheck(
        name="condition_encounter_link",
        outcome=Outcome.FAIL,
        severity=Severity.MINOR,
        message=f"{len(problems)} Condition.encounter reference(s) unresolved",
        detail={"problems_sample": problems[:10]},
    )


# --------------------------------------------------------------------------- #
# helpers

def _read(cohort: Cohort, country: str, resource_type: str):
    import json
    path = cohort.root / country / "fhir_r4" / f"{resource_type}.ndjson"
    if not path.exists():
        return iter(())
    def _gen():
        with path.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue
    return _gen()


def _first_code_for_system(coding: list, system: str) -> str | None:
    for c in coding:
        if c.get("system") == system:
            return c.get("code")
    return None


def _patient_ages(cohort: Cohort, country: str) -> dict[str, int]:
    today = date.today()
    ages: dict[str, int] = {}
    for row in _read(cohort, country, "Patient"):
        pid = row.get("id")
        birth = row.get("birthDate")
        if not (pid and birth):
            continue
        try:
            b = date.fromisoformat(birth[:10])
            ages[pid] = today.year - b.year - int(
                (today.month, today.day) < (b.month, b.day)
            )
        except ValueError:
            continue
    return ages


def _bounds_summary() -> dict[str, str]:
    return {code: f"[{lo}, {hi}] {hint}" for code, (lo, hi, hint) in _LAB_BOUNDS.items()}
