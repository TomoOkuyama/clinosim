"""JP-language axis: localization integrity.

Checks:
- US output Observation display fields contain ZERO non-ASCII
  characters (no JP leakage into US cohort).
- JP output Observation displays for the codes in
  spec.structural_obs_codes contain Japanese characters (at least one
  non-ASCII codepoint). Missing JP cohort is acceptable — N/A.

Code values are checked against the LOINC and JLAC10 tuples in
spec.structural_obs_codes so this axis is reusable for any Module that
declares its observation codes.
"""

from __future__ import annotations

from clinosim.audit.registry import ModuleAuditSpec
from clinosim.audit.types import AuditFinding, AxisResult, Cohort, Severity


def _has_non_ascii(s: str) -> bool:
    return any(ord(c) > 127 for c in s or "")


def _wanted(spec: ModuleAuditSpec) -> set[str]:
    out: set[str] = set()
    for codes in spec.structural_obs_codes.values():
        out.update(codes)
    return out


def run(spec: ModuleAuditSpec, cohort: Cohort) -> AxisResult:
    result = AxisResult(axis="jp_language", module=spec.name)
    countries = cohort.countries()

    # US: zero non-ASCII display violations across all Observation
    # codings (no language scope — any non-ASCII in US is wrong).
    if "us" in countries:
        us_violations = 0
        for row in cohort.ndjson("us", "Observation"):
            for coding in (row.get("code") or {}).get("coding", []):
                if _has_non_ascii(coding.get("display", "")):
                    us_violations += 1
                    break
        result.info["us_non_ascii_display_violations"] = us_violations
        if us_violations > 0:
            result.findings.append(
                AuditFinding(
                    Severity.FAIL,
                    f"US output has {us_violations} Observations with non-ASCII display",
                )
            )

    # JP: each requested analyte must have at least one localized display
    if "jp" not in countries or not spec.structural_obs_codes:
        return result

    jp_localized: dict[str, int] = {a: 0 for a in spec.structural_obs_codes}
    jp_total: dict[str, int] = {a: 0 for a in spec.structural_obs_codes}
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
                    f"{analyte}: 0 of {total} JP Observations have a localized display",
                )
            )

    return result
