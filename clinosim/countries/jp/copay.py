"""JP 一部負担金割合 — the copay rule (``copay_rule`` "jp_age_income";
Issue #3016, moved here by Issue #3194).

By age on the coverage date (school entry, 70, 75) and, from 70, by a
per-person income quantile; the rates are identity.yaml ``copay``. Without a
birth date the category rate applies (``category_copay_pct``).
"""

from __future__ import annotations

from datetime import date

from clinosim.country_profile import register_implementation


def _jp_school_entry(dob: date) -> date:
    """1 April of the school year a child enters elementary school (学校教育法):
    a child who is 6 by 1 April enters that April (birthdays 2 April to
    1 April of the following year share a school year)."""
    year = dob.year + 6 if (dob.month, dob.day) <= (4, 1) else dob.year + 7
    return date(year, 4, 1)


def jp_income_quantile(patient_id: str) -> float:
    """Per-person income quantile in [0, 1) for the JP copay tier (Issue #3016);
    stable for a person across years, no RNG draw."""
    from clinosim.determinism import sha_quantile

    return sha_quantile(f"jp-copay-income|{patient_id}")


def jp_copay_pct(dob: date, on: date, income_q: float, country: str) -> int:
    """JP 一部負担金割合 (%) on ``on`` (Issue #3016), from identity.yaml ``copay``:
    by age (school entry, 70, 75) and, from 70, by the income quantile."""
    from clinosim.modules.output.fhir_r4.demographics.patient import _age_gate_config, _age_on, _identity_cfg

    cfg = _identity_cfg(country).get("copay", {}) or {}
    late_age = _age_gate_config(country)["late_elderly_min_age"]
    age = _age_on(dob, on)
    if age >= late_age:
        le = cfg["late_elderly"]
        if income_q < float(le["high_income_share"]):
            return int(le["high_income_pct"])
        middle_from = date.fromisoformat(str(le["middle_income_from"]))
        if on >= middle_from and income_q < float(le["high_income_share"]) + float(le["middle_income_share"]):
            return int(le["middle_income_pct"])
        return int(le["pct"])
    old = cfg["age_70_74"]
    if age >= int(old["min_age"]):
        return int(old["high_income_pct"]) if income_q < float(old["high_income_share"]) else int(old["pct"])
    if on < _jp_school_entry(dob):
        return int(cfg["preschool_pct"])
    return int(cfg["standard_pct"])


@register_implementation("copay_rule", "jp_age_income")
def jp_copay_rule(dob: date | None, on: date, patient_id: str, category: str, country: str) -> int:
    """The JP copay percentage of ``patient_id`` on ``on``."""
    if not dob:
        from clinosim.modules.output.fhir_r4.demographics.patient import category_copay_pct

        return category_copay_pct(dob, on, patient_id, category, country)
    return jp_copay_pct(dob, on, jp_income_quantile(patient_id), country)
