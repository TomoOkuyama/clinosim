"""Phase 3a 3-axis DQR: structural / clinical / JP-language.

Axis 1 (structural):
  - WBC + CRP refRange + interpretation 100%
  - LOINC 6690-2 (WBC) + 1988-5 (CRP)
  - JLAC10 2A020 (WBC) + 5C070 (CRP)

Axis 2 (clinical relative-delta):
  - HAI cohort WBC/CRP elevated vs non-HAI baseline
  - Rare-event acceptance: skip if cohort < 5

Axis 3 (JP language):
  - US 日本語混入 = 0
  - JP WBC/CRP displays localised
"""
from __future__ import annotations

import json
import statistics
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).parent / "phase3a_dqr"

# HAI Condition ICD-10-CM codes (from PR #89)
HAI_ICD = {
    "T80.211A": "CLABSI",
    "T83.511A": "CAUTI",
    "J95.851":  "VAP",
}

# WBC + CRP codes (LOINC + JLAC10)
WBC_CODES = {"6690-2", "2A010"}
CRP_CODES = {"1988-5", "5C070"}


def read_ndjson(path: Path):
    if not path.exists():
        return
    with path.open() as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def _coding_codes(r):
    return {c.get("code") for c in (r.get("code") or {}).get("coding", [])}


def axis1_structural(country: str) -> tuple[int, int, int, int, list[str]]:
    """Returns (WBC n, WBC w/refRange+interp, CRP n, CRP w/refRange+interp, issues)."""
    issues: list[str] = []
    obs_path = ROOT / country / "fhir_r4" / "Observation.ndjson"
    wbc_n = wbc_full = 0
    crp_n = crp_full = 0
    for r in read_ndjson(obs_path):
        codes = _coding_codes(r)
        if codes & WBC_CODES:
            wbc_n += 1
            if r.get("referenceRange") and r.get("interpretation"):
                wbc_full += 1
        if codes & CRP_CODES:
            crp_n += 1
            if r.get("referenceRange") and r.get("interpretation"):
                crp_full += 1
    if wbc_n and wbc_full != wbc_n:
        issues.append(f"{country.upper()}: WBC refRange+interp {wbc_full}/{wbc_n}")
    if crp_n and crp_full != crp_n:
        issues.append(f"{country.upper()}: CRP refRange+interp {crp_full}/{crp_n}")
    return wbc_n, wbc_full, crp_n, crp_full, issues


def axis2_clinical_delta(country: str) -> dict:
    """Returns {hai_type or 'baseline': {WBC: list, CRP: list}}."""
    # Build encounter_id -> hai_type from HAI Conditions
    hai_encounters: dict[str, str] = {}
    cond_path = ROOT / country / "fhir_r4" / "Condition.ndjson"
    for c in read_ndjson(cond_path):
        codes = _coding_codes(c)
        for icd, hai_type in HAI_ICD.items():
            if icd in codes:
                enc_ref = (c.get("encounter") or {}).get("reference", "")
                enc_id = enc_ref.split("/")[-1] if enc_ref else None
                if enc_id:
                    hai_encounters[enc_id] = hai_type
                break

    # Build encounter_id -> encounter_class to limit baseline to inpatient
    enc_class: dict[str, str] = {}
    enc_path = ROOT / country / "fhir_r4" / "Encounter.ndjson"
    for e in read_ndjson(enc_path):
        eid = e.get("id", "")
        cls = (e.get("class") or {}).get("code", "")
        if eid:
            enc_class[eid] = cls

    # Collect WBC + CRP per cohort
    cohorts: dict[str, dict[str, list[float]]] = defaultdict(
        lambda: {"WBC": [], "CRP": []}
    )
    obs_path = ROOT / country / "fhir_r4" / "Observation.ndjson"
    for r in read_ndjson(obs_path):
        codes = _coding_codes(r)
        is_wbc = bool(codes & WBC_CODES)
        is_crp = bool(codes & CRP_CODES)
        if not (is_wbc or is_crp):
            continue
        enc_ref = (r.get("encounter") or {}).get("reference", "")
        enc_id = enc_ref.split("/")[-1] if enc_ref else ""
        if not enc_id:
            continue
        # Only count baseline from inpatient encounters (HAI is inpatient-only)
        cohort = hai_encounters.get(enc_id)
        if cohort is None:
            if enc_class.get(enc_id, "") != "IMP":
                continue
            cohort = "baseline"
        val = (r.get("valueQuantity") or {}).get("value")
        if val is None:
            continue
        key = "WBC" if is_wbc else "CRP"
        cohorts[cohort][key].append(float(val))
    return dict(cohorts)


def axis3_jp_language(country: str) -> tuple[int, int, list[str]]:
    """Returns (jp_disp_wbc_n, jp_disp_crp_n, issues)."""
    issues: list[str] = []
    obs_path = ROOT / country / "fhir_r4" / "Observation.ndjson"
    wbc_jp = crp_jp = 0
    if country == "us":
        # US: assert ZERO non-ASCII display strings
        bad = 0
        for r in read_ndjson(obs_path):
            for coding in (r.get("code") or {}).get("coding", []):
                disp = coding.get("display", "") or ""
                if any(ord(c) > 127 for c in disp):
                    bad += 1
                    break
            if bad > 5:
                break
        if bad > 0:
            issues.append(f"US: {bad}+ Observations with non-ASCII display")
        return 0, 0, issues
    # JP: assert WBC + CRP displays are localised
    for r in read_ndjson(obs_path):
        for coding in (r.get("code") or {}).get("coding", []):
            disp = coding.get("display", "") or ""
            code = coding.get("code", "")
            non_ascii = any(ord(c) > 127 for c in disp)
            if non_ascii and code in WBC_CODES:
                wbc_jp += 1
                break
            if non_ascii and code in CRP_CODES:
                crp_jp += 1
                break
    if not wbc_jp:
        issues.append("JP: WBC display not localised")
    if not crp_jp:
        issues.append("JP: CRP display not localised")
    return wbc_jp, crp_jp, issues


def print_axis2(country: str, cohorts: dict) -> bool:
    print(f"\n  {country.upper()}:")
    baseline = cohorts.get("baseline", {})
    bw = sorted(baseline.get("WBC", []))
    bc = sorted(baseline.get("CRP", []))
    if bw:
        print(f"    baseline inpatient WBC n={len(bw)} p50={statistics.median(bw):.0f}")
    if bc:
        print(f"    baseline inpatient CRP n={len(bc)} p50={statistics.median(bc):.1f}")
    all_pass = True
    expected = {"CLABSI": (3000, 50), "VAP": (3000, 50), "CAUTI": (1500, 25)}
    for hai_type in ("CLABSI", "VAP", "CAUTI"):
        c = cohorts.get(hai_type, {})
        w = sorted(c.get("WBC", []))
        cr = sorted(c.get("CRP", []))
        if len(w) < 5 and len(cr) < 5:
            print(f"    {hai_type}: n_WBC={len(w)} n_CRP={len(cr)} — too few for delta (Poisson rare)")
            continue
        wd = statistics.median(w) - statistics.median(bw) if (w and bw) else 0
        cd = statistics.median(cr) - statistics.median(bc) if (cr and bc) else 0
        need_w, need_c = expected[hai_type]
        ok_w = wd >= need_w
        ok_c = cd >= need_c
        status = "PASS" if (ok_w and ok_c) else "FAIL"
        if not (ok_w and ok_c):
            all_pass = False
        print(f"    {hai_type}: n_WBC={len(w)} delta_p50={wd:+.0f} (need >={need_w}) "
              f"| n_CRP={len(cr)} delta_p50={cd:+.1f} (need >={need_c}) -> {status}")
    return all_pass


if __name__ == "__main__":
    print("# Phase 3a DQR (US p=10000 + JP p=5000, seed=42)\n")

    print("\n=== Axis 1: Structural ===")
    all_struct_ok = True
    for country in ("us", "jp"):
        wbc_n, wbc_full, crp_n, crp_full, issues = axis1_structural(country)
        ok = (wbc_n == wbc_full and crp_n == crp_full)
        print(f"  {country.upper()}: WBC n={wbc_n} refRange+interp={wbc_full}/{wbc_n} "
              f"| CRP n={crp_n} refRange+interp={crp_full}/{crp_n} -> "
              f"{'PASS' if ok else 'FAIL'}")
        for i in issues:
            print(f"    [issue] {i}")
        all_struct_ok = all_struct_ok and ok

    print("\n=== Axis 2: Clinical relative-delta ===")
    axis2_ok = True
    for country in ("us", "jp"):
        cohorts = axis2_clinical_delta(country)
        if not print_axis2(country, cohorts):
            axis2_ok = False

    print("\n=== Axis 3: JP language ===")
    all_jp_ok = True
    for country in ("us", "jp"):
        wbc_jp, crp_jp, issues = axis3_jp_language(country)
        if country == "us":
            ok = not issues
            print(f"  US: non-ASCII display violations: {'PASS' if ok else 'FAIL'}")
        else:
            ok = wbc_jp > 0 and crp_jp > 0
            print(f"  JP: WBC ja-display={wbc_jp} CRP ja-display={crp_jp} -> "
                  f"{'PASS' if ok else 'FAIL'}")
        for i in issues:
            print(f"    [issue] {i}")
        all_jp_ok = all_jp_ok and ok

    print("\n=== Summary ===")
    print(f"  Axis 1 (structural): {'PASS' if all_struct_ok else 'FAIL'}")
    print(f"  Axis 2 (clinical):   {'PASS' if axis2_ok else 'FAIL'}")
    print(f"  Axis 3 (JP language):{'PASS' if all_jp_ok else 'FAIL'}")
