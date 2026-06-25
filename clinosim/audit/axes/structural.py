"""Structural axis: FHIR resource integrity for the codes declared in
spec.structural_obs_codes.

Checks (all FAIL-severity on miss):
- 100% referenceRange + interpretation coverage
- id uniqueness across each NDJSON file
- display != code on every coding
- (reference integrity check: deferred to Phase 2 — needs cross-file
  walk; structural pass is sufficient at Phase 1 since invariant is
  already enforced by output adapter tests)
"""

from __future__ import annotations

from clinosim.audit.registry import ModuleAuditSpec
from clinosim.audit.types import (
    AuditFinding,
    AxisResult,
    Cohort,
    Severity,
)


def _wanted_codes(spec: ModuleAuditSpec) -> set[str]:
    out: set[str] = set()
    for codes in spec.structural_obs_codes.values():
        out.update(codes)
    return out


def run(spec: ModuleAuditSpec, cohort: Cohort) -> AxisResult:
    result = AxisResult(axis="structural", module=spec.name)
    wanted = _wanted_codes(spec)
    if not wanted:
        return result  # N/A — no codes to check

    per_code_n: dict[str, int] = {c: 0 for c in wanted}
    per_code_full: dict[str, int] = {c: 0 for c in wanted}

    for country in cohort.countries():
        # Per-country id namespace — US and JP are independent FHIR
        # exports, so an ID legitimately existing in both is not a
        # collision. We only catch duplicates within a single cohort.
        seen_ids: set[str] = set()
        for row in cohort.ndjson(country, "Observation"):
            codes = {c.get("code", "") for c in (row.get("code") or {}).get("coding", [])}
            matched = codes & wanted
            if not matched:
                continue
            for c in matched:
                per_code_n[c] += 1
                if row.get("referenceRange") and row.get("interpretation"):
                    per_code_full[c] += 1
            rid = row.get("id", "")
            if rid in seen_ids:
                result.findings.append(
                    AuditFinding(
                        Severity.FAIL,
                        f"duplicate Observation id {rid!r} in {country}",
                    )
                )
            else:
                seen_ids.add(rid)
            for c in (row.get("code") or {}).get("coding", []):
                code = c.get("code", "")
                display = c.get("display", "")
                if code and display and code == display:
                    result.findings.append(
                        AuditFinding(
                            Severity.FAIL,
                            f"display equals code {code!r} on Observation {rid}",
                        )
                    )

    for code in wanted:
        n = per_code_n[code]
        full = per_code_full[code]
        if n == 0:
            continue
        result.info[f"{code}_n"] = n
        pct = round(100.0 * full / n, 2)
        result.info[f"{code}_refRange_interp_pct"] = pct
        if pct < 100.0:
            result.findings.append(
                AuditFinding(
                    Severity.FAIL,
                    f"{code} refRange + interpretation coverage {full}/{n} = {pct}% (need 100%)",
                )
            )

    return result
