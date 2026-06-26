"""Clinical axis: cohort baseline + acceptance verification.

Phase 1 surface:
- For each entry in spec.clinical_acceptance (key = lowercase
  hai_type, value = {icd10_code, WBC_delta_p50, CRP_delta_p50}):
    1. Identify the cohort encounters via Condition.ndjson rows
       whose code.coding[].code == icd10_code.
    2. Split observations into cohort (those linked to a cohort
       encounter) and baseline (other inpatient-class encounters).
    3. Compute cohort_p50 - baseline_p50 for WBC and CRP.
    4. Compare against the WBC_delta_p50 / CRP_delta_p50 thresholds.
    5. cohort < 5 → WARN (rare-event acceptable, mitigated by
       silent_no_op axis lift-firing proof).
    6. Cohort meets acceptance → PASS; misses → FAIL.

Per-event observed-vs-theoretical verification is deferred to Phase 2
(requires CIF state_history walk; the silent_no_op axis already
provides the load-bearing per-event check via lift_firing_proof).
"""

from __future__ import annotations

import statistics

from clinosim.audit.registry import ModuleAuditSpec
from clinosim.audit.types import AuditFinding, AxisResult, Cohort, Severity

_WBC_CODE = "6690-2"
_WBC_CODE_JP = "2A010"
_CRP_CODE = "1988-5"
_CRP_CODE_JP = "5C070"


def _is_wbc(coding: list[dict]) -> bool:
    return any(c.get("code") in (_WBC_CODE, _WBC_CODE_JP) for c in coding)


def _is_crp(coding: list[dict]) -> bool:
    return any(c.get("code") in (_CRP_CODE, _CRP_CODE_JP) for c in coding)


def _enc_id(row: dict) -> str:
    ref = (row.get("encounter") or {}).get("reference", "")
    return ref.split("/")[-1] if ref else ""


def _condition_code_set(row: dict) -> set[str]:
    return {c.get("code", "") for c in (row.get("code") or {}).get("coding", [])}


def run(spec: ModuleAuditSpec, cohort: Cohort) -> AxisResult:
    result = AxisResult(axis="clinical", module=spec.name)
    if not spec.clinical_acceptance:
        return result  # N/A

    # Filter to HAI-type entries only (dict with "icd10_code").
    # Top-level metadata keys (e.g. "hai_resistance_bands", "hai_empty_susceptibilities_max_rate")
    # are skipped here; PR3b-3 will add active enforcement for those keys.
    hai_acceptance = {
        k: v
        for k, v in spec.clinical_acceptance.items()
        if isinstance(v, dict) and "icd10_code" in v
    }
    if not hai_acceptance:
        return result  # N/A — no HAI-type entries

    icd_to_type = {v["icd10_code"]: k for k, v in hai_acceptance.items()}

    for country in cohort.countries():
        cohort_enc: dict[str, set[str]] = {k: set() for k in hai_acceptance}
        for row in cohort.ndjson(country, "Condition"):
            codes = _condition_code_set(row)
            for icd, hai_type in icd_to_type.items():
                if icd in codes:
                    eid = _enc_id(row)
                    if eid:
                        cohort_enc[hai_type].add(eid)

        all_cohort_enc = set().union(*cohort_enc.values()) if cohort_enc else set()
        baseline_enc: set[str] = set()
        for row in cohort.ndjson(country, "Encounter"):
            eid = row.get("id", "")
            cls = (row.get("class") or {}).get("code", "")
            if cls == "IMP" and eid not in all_cohort_enc:
                baseline_enc.add(eid)

        cohort_wbc: dict[str, list[float]] = {k: [] for k in hai_acceptance}
        cohort_crp: dict[str, list[float]] = {k: [] for k in hai_acceptance}
        base_wbc: list[float] = []
        base_crp: list[float] = []
        for row in cohort.ndjson(country, "Observation"):
            codings = (row.get("code") or {}).get("coding", [])
            val = (row.get("valueQuantity") or {}).get("value")
            if val is None:
                continue
            eid = _enc_id(row)
            if not eid:
                continue
            is_w = _is_wbc(codings)
            is_c = _is_crp(codings)
            if not (is_w or is_c):
                continue
            assigned = False
            for hai_type, encs in cohort_enc.items():
                if eid in encs:
                    (cohort_wbc if is_w else cohort_crp)[hai_type].append(val)
                    assigned = True
                    break
            if not assigned and eid in baseline_enc:
                (base_wbc if is_w else base_crp).append(val)

        b_wbc_p50 = statistics.median(base_wbc) if base_wbc else None
        b_crp_p50 = statistics.median(base_crp) if base_crp else None
        result.info[f"{country}_baseline_WBC_p50"] = b_wbc_p50
        result.info[f"{country}_baseline_CRP_p50"] = b_crp_p50

        for hai_type, acceptance in hai_acceptance.items():
            w = cohort_wbc[hai_type]
            c = cohort_crp[hai_type]
            n_w, n_c = len(w), len(c)
            result.info[f"{country}_{hai_type}_n_WBC"] = n_w
            result.info[f"{country}_{hai_type}_n_CRP"] = n_c
            if n_w < 5 and n_c < 5:
                result.findings.append(
                    AuditFinding(
                        Severity.WARN,
                        f"{country}/{hai_type}: cohort too small for delta "
                        f"(n_WBC={n_w}, n_CRP={n_c}); acceptance not verified at "
                        "cohort level (silent_no_op axis covers this).",
                    )
                )
                continue
            if w and b_wbc_p50 is not None:
                dw = statistics.median(w) - b_wbc_p50
                result.info[f"{country}_{hai_type}_WBC_delta_p50"] = round(dw, 1)
                need = acceptance.get("WBC_delta_p50")
                if need is not None and dw < need:
                    result.findings.append(
                        AuditFinding(
                            Severity.FAIL,
                            f"{country}/{hai_type}: WBC delta p50 = {dw:.0f} < required {need}",
                        )
                    )
            if c and b_crp_p50 is not None:
                dc = statistics.median(c) - b_crp_p50
                result.info[f"{country}_{hai_type}_CRP_delta_p50"] = round(dc, 1)
                need = acceptance.get("CRP_delta_p50")
                if need is not None and dc < need:
                    result.findings.append(
                        AuditFinding(
                            Severity.FAIL,
                            f"{country}/{hai_type}: CRP delta p50 = {dc:.1f} < required {need}",
                        )
                    )

    return result
