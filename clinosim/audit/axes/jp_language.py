"""JP-language axis: localization integrity across all resources.

Checks:
- US output contains ZERO non-ASCII characters in display fields
  (no JP leakage into US cohort).
- JP output: all human-readable fields (display, text, name) contain
  Japanese characters when applicable. Exceptions:
  - Units (mg, mL, mcg, IU, etc.) — allowed in any language
  - Dual coding interop slots (e.g., CPT coding[1], interop languages)

Supported resources (JP):
  - Observation.code.coding[].display
  - MedicationAdministration.dosage.text
  - MedicationRequest.dosageInstruction[].text
  - Procedure.code.text and code.coding[].display (except CPT slot)
  - AllergyIntolerance.code.text and code.coding[].display

Module-specific observation codes (structural_obs_codes) are still
checked; additional resource checks run automatically on all cohorts.
Issue #473: extends coverage to eliminate 13k+ undetected localization
gaps in medication + procedure resources.
"""

from __future__ import annotations

import re

from clinosim.audit.registry import ModuleAuditSpec
from clinosim.audit.types import AuditFinding, AxisResult, Cohort, Severity

_UNIT_ALLOWLIST = {
    "mg",
    "mL",
    "mcg",
    "ug",
    "IU",
    "g",
    "L",
    "dL",
    "mmol",
    "h",
    "d",
    "PO",
    "IV",
    "IM",
    "SC",
    "PRN",
    "BID",
    "TID",
    "QID",
    "QD",
    "QAM",
    "QPM",
    "QHS",
    "QOD",
    "PC",
    "AC",
    "HS",
    "STAT",
}


def _has_non_ascii(s: str) -> bool:
    return any(ord(c) > 127 for c in s or "")


def _is_allowed_latin(s: str) -> bool:
    if not s:
        return True
    text = s.strip()
    words = re.findall(r"[a-zA-Z0-9]+", text)
    if not words:
        return True
    return all(word in _UNIT_ALLOWLIST or word.isdigit() for word in words)


def _has_english_violation(s: str) -> bool:
    if not s:
        return False
    if _has_non_ascii(s):
        return False
    return not _is_allowed_latin(s)


def run(spec: ModuleAuditSpec, cohort: Cohort) -> AxisResult:
    result = AxisResult(axis="jp_language", module=spec.name)
    countries = cohort.countries()

    if "us" in countries:
        us_violations = 0
        for row in cohort.ndjson("us", "Observation"):
            for coding in (row.get("code") or {}).get("coding", []):
                if _has_non_ascii(coding.get("display", "")):
                    us_violations += 1
                    break
        for row in cohort.ndjson("us", "MedicationAdministration"):
            dosage = row.get("dosage", {})
            if isinstance(dosage, dict) and _has_non_ascii(dosage.get("text", "")):
                us_violations += 1
        for row in cohort.ndjson("us", "MedicationRequest"):
            for dosage in row.get("dosageInstruction", []):
                if isinstance(dosage, dict) and _has_non_ascii(dosage.get("text", "")):
                    us_violations += 1
                    break
        for row in cohort.ndjson("us", "Procedure"):
            code_concept = row.get("code", {})
            if isinstance(code_concept, dict):
                if _has_non_ascii(code_concept.get("text", "")):
                    us_violations += 1
                    continue
                for coding in code_concept.get("coding", []):
                    if _has_non_ascii(coding.get("display", "")):
                        us_violations += 1
                        break
        for row in cohort.ndjson("us", "AllergyIntolerance"):
            code_concept = row.get("code", {})
            if isinstance(code_concept, dict):
                if _has_non_ascii(code_concept.get("text", "")):
                    us_violations += 1
                    continue
                for coding in code_concept.get("coding", []):
                    if _has_non_ascii(coding.get("display", "")):
                        us_violations += 1
                        break

        result.info["us_non_ascii_violations"] = us_violations
        if us_violations > 0:
            result.findings.append(
                AuditFinding(
                    Severity.FAIL,
                    f"US output has {us_violations} resources with non-ASCII display/text",
                )
            )

    if "jp" not in countries:
        return result

    jp_violations = 0
    violation_details = {}

    for row in cohort.ndjson("jp", "MedicationAdministration"):
        dosage = row.get("dosage", {})
        if isinstance(dosage, dict):
            text = dosage.get("text", "")
            if _has_english_violation(text):
                jp_violations += 1
                k = "MedicationAdministration.dosage.text"
                violation_details[k] = violation_details.get(k, 0) + 1

    for row in cohort.ndjson("jp", "MedicationRequest"):
        for dosage in row.get("dosageInstruction", []):
            if isinstance(dosage, dict):
                text = dosage.get("text", "")
                if _has_english_violation(text):
                    jp_violations += 1
                    k = "MedicationRequest.dosageInstruction[].text"
                    violation_details[k] = violation_details.get(k, 0) + 1
                    break

    for row in cohort.ndjson("jp", "Procedure"):
        code_concept = row.get("code", {})
        if isinstance(code_concept, dict):
            text = code_concept.get("text", "")
            if _has_english_violation(text):
                jp_violations += 1
                violation_details["Procedure.code.text"] = violation_details.get("Procedure.code.text", 0) + 1
            else:
                for idx, coding in enumerate(code_concept.get("coding", [])):
                    if idx == 1:
                        continue
                    display = coding.get("display", "")
                    if _has_english_violation(display):
                        jp_violations += 1
                        k = "Procedure.code.coding[].display"
                        violation_details[k] = violation_details.get(k, 0) + 1
                        break

    for row in cohort.ndjson("jp", "AllergyIntolerance"):
        code_concept = row.get("code", {})
        if isinstance(code_concept, dict):
            text = code_concept.get("text", "")
            if _has_english_violation(text):
                jp_violations += 1
                violation_details["AllergyIntolerance.code.text"] = (
                    violation_details.get("AllergyIntolerance.code.text", 0) + 1
                )
            else:
                for coding in code_concept.get("coding", []):
                    display = coding.get("display", "")
                    if _has_english_violation(display):
                        jp_violations += 1
                        k = "AllergyIntolerance.code.coding[].display"
                        violation_details[k] = violation_details.get(k, 0) + 1
                        break

    if spec.structural_obs_codes:
        jp_localized = {a: 0 for a in spec.structural_obs_codes}
        jp_total = {a: 0 for a in spec.structural_obs_codes}
        for row in cohort.ndjson("jp", "Observation"):
            codings = (row.get("code") or {}).get("coding", [])
            for analyte, codes in spec.structural_obs_codes.items():
                if any(c.get("code", "") in codes for c in codings):
                    jp_total[analyte] += 1
                    if any(_has_non_ascii(c.get("display", "")) for c in codings):
                        jp_localized[analyte] += 1
                    break

        for analyte, total in jp_total.items():
            if total == 0:
                continue
            result.info[f"jp_{analyte}_localized"] = jp_localized[analyte]
            result.info[f"jp_{analyte}_total"] = total
            if jp_localized[analyte] == 0:
                result.findings.append(
                    AuditFinding(
                        Severity.FAIL,
                        f"Observation {analyte}: 0 of {total} have localized display",
                    )
                )

    result.info["jp_cross_resource_violations"] = jp_violations
    if violation_details:
        result.info["jp_violation_by_field"] = violation_details
    if jp_violations > 0:
        details = "; ".join(f"{k}={v}" for k, v in violation_details.items())
        result.findings.append(
            AuditFinding(
                Severity.FAIL,
                f"JP output has {jp_violations} resources with English text ({details})",
            )
        )

    return result
