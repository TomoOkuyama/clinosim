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
from clinosim.codes import get_system_uri
from clinosim.modules.output._fhir_microbiology import MB_ORG_ID_PREFIX

# Canonical SNOMED CT URI (PR3b-3 stage-1 adversarial finding C3): substring
# match against "snomed" silently broke on OID form
# (urn:oid:2.16.840.1.113883.6.96) or uppercase variants — same class as
# PR-90's hai_type case-mismatch silent no-op. Use canonical equality.
_SNOMED_URI = get_system_uri("snomed-ct")

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


def _is_susceptibility_observation(row: dict) -> tuple[str, str] | None:
    """PR3b-3: if this Observation is an antibiotic susceptibility, return
    (antibiotic_loinc, interpretation_code) else None. Susceptibility
    Observations encode the antibiotic LOINC in code.coding[0].code and the
    S/I/R interpretation in valueCodeableConcept.coding[0].code."""
    codings = (row.get("code") or {}).get("coding", []) or []
    if not codings:
        return None
    abx_loinc = codings[0].get("code", "")
    vcc = row.get("valueCodeableConcept") or {}
    vcc_codings = vcc.get("coding", []) or []
    if not vcc_codings:
        return None
    interp = vcc_codings[0].get("code", "")
    if interp not in ("S", "I", "R"):
        return None
    return (abx_loinc, interp)


def _organism_per_encounter(cohort: Cohort, country: str) -> dict[str, set[str]]:
    """Return {encounter_id: {organism_snomed, ...}} from microbiology Observations.

    Walks Observation.ndjson once, filters to mb-org-* organism observations
    that carry a valueCodeableConcept SNOMED code (growth observations).
    No-growth observations (valueString="No growth"/"発育なし"), non-mb
    Observations, missing encounter refs, and non-SNOMED valueCodeableConcept
    codings are skipped.

    Used by the PR3b-3 R-rate gate (per-(hai_type, organism) cohort filter)
    and empty-rate gate (panel-eligible denominator filter).
    """
    out: dict[str, set[str]] = {}
    for row in cohort.ndjson(country, "Observation"):
        rid = row.get("id", "")
        if not rid.startswith(MB_ORG_ID_PREFIX):
            continue
        eid = _enc_id(row)
        if not eid:
            continue
        vcc = row.get("valueCodeableConcept") or {}
        codings = vcc.get("coding", []) or []
        for c in codings:
            sys_uri = c.get("system", "") or ""
            if sys_uri == _SNOMED_URI:
                code = c.get("code", "") or ""
                if code:
                    out.setdefault(eid, set()).add(code)
    return out


def _panel_eligible_organisms() -> dict[str, set[str]]:
    """Per-hai_type set of organisms with antibiogram entries (panel-eligible).

    Derived from load_hai_antibiogram() keys. Organisms without an antibiogram
    entry (E.faecalis 78065002, C.albicans 53326005, future no-panel additions)
    are automatically excluded — no hard-coded exclusion list. Used by the D2
    empty-rate gate to restrict the denominator to encounters whose culture
    organism actually has a S/I/R panel.
    """
    from clinosim.modules.hai import load_hai_antibiogram  # local: avoids any potential cycle
    abg = load_hai_antibiogram()
    return {hai_type: set(organism_map.keys()) for hai_type, organism_map in abg.items()}


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
        # PR3b-3 D1/D2 (2026-06-29): per-country per-encounter organism map.
        # Built ONCE and reused by D1 (R-rate per-organism filter) + D2
        # (panel-eligible denominator filter) — single Observation.ndjson walk.
        org_per_enc = _organism_per_encounter(cohort, country)

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

        # ---------------------------------------------------------------
        # PR3b-3 D1 complete (2026-06-29): NHSN R-rate gate per
        # (hai_type, organism, antibiotic) cohort. Cohort encounters are
        # filtered by per-organism culture (via org_per_enc above) so bands
        # measure the true per-organism resistance rate (e.g.
        # clabsi/3092008/cefazolin = S.aureus only, not the mixed S.aureus +
        # S.epidermidis + E.coli cohort that would breach the MRSA band).
        # n<30 → WARN guard retained for rare-event safety.
        # ---------------------------------------------------------------
        r_bands = spec.clinical_acceptance.get("hai_resistance_bands") or []
        if r_bands:
            from clinosim.modules.antibiotic import ANTIBIOTIC_LOINC_LOOKUP
            for band in r_bands:
                hai_type_b, organism_b = band["cohort"].split("/", maxsplit=1)
                abx_key = band["antibiotic"]
                abx_loinc = ANTIBIOTIC_LOINC_LOOKUP.get(abx_key)
                if abx_loinc is None:
                    continue
                base_set = cohort_enc.get(hai_type_b, set())
                cohort_enc_set = {
                    e for e in base_set if organism_b in org_per_enc.get(e, set())
                }
                if not cohort_enc_set:
                    result.info[f"{country}_{band['cohort']}_{abx_key}_n"] = 0
                    continue
                r_count = 0
                total_count = 0
                for row in cohort.ndjson(country, "Observation"):
                    eid = _enc_id(row)
                    if eid not in cohort_enc_set:
                        continue
                    s = _is_susceptibility_observation(row)
                    if s is None:
                        continue
                    if s[0] != abx_loinc:
                        continue
                    total_count += 1
                    if s[1] == "R":
                        r_count += 1
                result.info[f"{country}_{band['cohort']}_{abx_key}_n"] = total_count
                if total_count < 30:
                    result.findings.append(AuditFinding(
                        Severity.WARN,
                        f"{country}/{band['cohort']}/{abx_key}: cohort too small "
                        f"(n={total_count}); R-rate band not enforced",
                    ))
                    continue
                r_rate = r_count / total_count
                result.info[f"{country}_{band['cohort']}_{abx_key}_R_rate"] = round(r_rate, 3)
                if r_rate < band["expected_R_min"] or r_rate > band["expected_R_max"]:
                    result.findings.append(AuditFinding(
                        Severity.FAIL,
                        f"{country}/{band['cohort']}/{abx_key}: R-rate "
                        f"{r_rate:.3f} outside band [{band['expected_R_min']}, "
                        f"{band['expected_R_max']}] (source: {band['source']})",
                    ))

        # ---------------------------------------------------------------
        # PR3b-3 D2 complete (2026-06-29): empty-susceptibilities rate gate.
        # Denominator restricted to panel-eligible HAI cohort encounters —
        # those with at least one culture organism that has an antibiogram
        # entry (via _panel_eligible_organisms, derived from
        # load_hai_antibiogram() keys). No-panel organisms
        # (E.faecalis 78065002, C.albicans 53326005) are auto-excluded —
        # no hard-coded exclusion list. Restores NHSN denominator definition
        # the 5% threshold was calibrated against.
        # n<30 → WARN guard retained for rare-event safety.
        # ---------------------------------------------------------------
        empty_max = spec.clinical_acceptance.get("hai_empty_susceptibilities_max_rate")
        if empty_max is not None:
            panel_orgs = _panel_eligible_organisms()
            panel_eligible_encs: set[str] = set()
            for hai_type, encs in cohort_enc.items():
                eligible = panel_orgs.get(hai_type, set())
                for e in encs:
                    if any(org in eligible for org in org_per_enc.get(e, set())):
                        panel_eligible_encs.add(e)

            enc_has_susc: dict[str, bool] = {e: False for e in panel_eligible_encs}
            for row in cohort.ndjson(country, "Observation"):
                eid = _enc_id(row)
                if eid not in enc_has_susc:
                    continue
                if _is_susceptibility_observation(row) is not None:
                    enc_has_susc[eid] = True
            total = len(enc_has_susc)
            result.info[f"{country}_hai_empty_susc_n"] = total
            if total > 0:
                empty_count = sum(1 for v in enc_has_susc.values() if not v)
                empty_rate = empty_count / total
                result.info[f"{country}_hai_empty_susc_rate"] = round(empty_rate, 3)
                if total < 30:
                    result.findings.append(AuditFinding(
                        Severity.WARN,
                        f"{country}: empty-susceptibility cohort too small "
                        f"(n={total}); rate gate not enforced "
                        f"(observed={empty_rate:.3f}, max={empty_max})",
                    ))
                elif empty_rate > empty_max:
                    result.findings.append(AuditFinding(
                        Severity.FAIL,
                        f"{country}: empty-susceptibility rate {empty_rate:.3f} "
                        f"exceeds max {empty_max} (panel-eligible HAI cohort)",
                    ))

        # ---------------------------------------------------------------
        # PR3b-3: narrow-rate gate per hai_type (adversarial-1 C-1 fix:
        # cohort format is now just "<hai_type>", not "<hai_type>/<organism>";
        # the gate measures per-hai_type aggregate narrow rate, which matches
        # what bands are calibrated against). Brittle "stopped" filter narrowed
        # to require the abx-hai- id prefix so non-antibiotic stops don't
        # inflate narrow_count (adversarial-1 I-G2 fix).
        # ---------------------------------------------------------------
        narrow_bands = spec.clinical_acceptance.get("narrow_rate_bands") or []
        if narrow_bands:
            for band in narrow_bands:
                hai_type_b = band["cohort"]  # per-hai_type only (no organism)
                cohort_enc_set = cohort_enc.get(hai_type_b, set())
                if not cohort_enc_set:
                    result.info[f"{country}_{band['cohort']}_narrow_n"] = 0
                    continue
                enc_narrowed: dict[str, bool] = {e: False for e in cohort_enc_set}
                for row in cohort.ndjson(country, "MedicationRequest"):
                    eid = _enc_id(row)
                    if eid not in enc_narrowed:
                        continue
                    rid = row.get("id", "")
                    # Antibiotic order ids are prefixed with the encounter id,
                    # then "req-abx-hai-..." or "req-abx-hai-...-narrowed".
                    # Filter to antibiotic origin so future non-abx stopped
                    # orders cannot inflate narrow_count.
                    if "req-abx-hai-" not in rid:
                        continue
                    if row.get("status") == "stopped" or rid.endswith("-narrowed"):
                        enc_narrowed[eid] = True
                total = len(enc_narrowed)
                narrow_count = sum(1 for v in enc_narrowed.values() if v)
                rate = narrow_count / total if total else 0.0
                result.info[f"{country}_{band['cohort']}_narrow_rate"] = round(rate, 3)
                if total < 30:
                    result.findings.append(AuditFinding(
                        Severity.WARN,
                        f"{country}/{band['cohort']}: narrow cohort too small "
                        f"(n={total}); rate band not enforced",
                    ))
                    continue
                if rate < band["expected_narrow_rate_min"] or rate > band["expected_narrow_rate_max"]:
                    result.findings.append(AuditFinding(
                        Severity.FAIL,
                        f"{country}/{band['cohort']}: narrow rate {rate:.3f} "
                        f"outside band [{band['expected_narrow_rate_min']}, "
                        f"{band['expected_narrow_rate_max']}]",
                    ))

    return result
