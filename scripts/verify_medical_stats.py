"""Broader medical-statistics verify: chronic prevalence, acute rates,
mortality, encounter mix, age/sex pyramid, cancer prevalence.

Companion to `verify_bundle.py` — compares cohort statistics against
real-world benchmark bands (NHANES / CDC for US, 患者調査 /
国民生活基礎調査 for JP) to catch epidemiological drift. Prints an OK /
OUT verdict per axis with the observed value and benchmark range.
Cohort bias is documented in the session-98 VERIFY_REPORT: hospital
patient population ≠ general population, so some prevalences
(hypertension under-emit, COPD over-emit) legitimately deviate.

Usage:
    python scripts/verify_medical_stats.py <out_dir> {US|JP}

Requires the same bundle layout as `verify_bundle.py` (fhir_r4/*.ndjson).
Assumes a 2-year simulation window (2023-01-01 → 2025-01-01); adjust
`SIM_YEARS` below for other windows.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

OUT = Path(sys.argv[1])
COUNTRY = sys.argv[2].upper()
FHIR = OUT / "fhir_r4"
SIM_YEARS = 2  # 2023-01-01 → 2025-01-01


def read_nd(p):
    if not p.exists():
        return
    with p.open() as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


# --- benchmark table (rough real-world values) ---
BENCH = {
    "US": {
        "hypertension_adult_prev_pct": (40, 50),  # NHANES ~45%
        "diabetes_adult_prev_pct": (9, 14),  # ~11.6%
        "copd_adult_prev_pct": (4, 8),  # ~6%
        "asthma_adult_prev_pct": (6, 10),  # ~8%
        "ckd_adult_prev_pct": (10, 20),  # ~15%
        "cad_adult_prev_pct": (4, 8),  # ~6%
        "chf_adult_prev_pct": (1.5, 3.5),  # ~2.4%
        "dyslipidemia_adult_prev_pct": (25, 40),  # ~30-35%
        "cancer_any_active_prev_pct": (4, 8),  # ~5%
        "mi_incidence_per_1000_yr": (2, 5),  # ~3/1000/year adults
        "stroke_incidence_per_1000_yr": (2, 5),  # ~3/1000/year
        "pneumonia_hosp_per_1000_yr": (3, 10),  # ~5/1000/year
        "sepsis_incidence_per_1000_yr": (1, 5),
        "mortality_per_1000_yr": (7, 11),  # ~8.7
        "outpatient_share_pct": (60, 90),
        "ed_share_pct": (5, 20),
        "inpatient_share_pct": (1, 8),
        "median_age": (35, 45),  # 38.9
    },
    "JP": {
        "hypertension_adult_prev_pct": (35, 50),
        "diabetes_adult_prev_pct": (10, 15),
        "copd_adult_prev_pct": (3, 8),  # underdiagnosed
        "asthma_adult_prev_pct": (6, 12),
        "ckd_adult_prev_pct": (10, 18),
        "cad_adult_prev_pct": (3, 7),
        "chf_adult_prev_pct": (1.5, 4),
        "dyslipidemia_adult_prev_pct": (30, 50),
        "cancer_any_active_prev_pct": (5, 10),
        "mi_incidence_per_1000_yr": (1, 3),  # lower than US
        "stroke_incidence_per_1000_yr": (2, 6),  # higher than US
        "pneumonia_hosp_per_1000_yr": (4, 12),
        "sepsis_incidence_per_1000_yr": (1, 4),
        "mortality_per_1000_yr": (9, 13),  # ~11.4 (older pop)
        "outpatient_share_pct": (60, 90),
        "ed_share_pct": (2, 15),  # lower ED reliance in JP
        "inpatient_share_pct": (1, 8),
        "median_age": (43, 52),  # 48.4
    },
}

# --- hospital-cohort (Medicare-user / hospital-catchment) target bands ---
# The chronic_prevalence blocks in clinosim/locale/{us,jp}/demographics.yaml
# explicitly target Medicare-user hospital-catchment prevalences (e.g. COPD
# YAML comment "cohort target ~12% (Medicare-user)"), which sit higher than
# general-population NHANES / MHLW rates. The header note on this script
# already flags "COPD over-emit legitimately deviate"; issues #1109 (COPD),
# #1110 (DM), #1111 (Dyslipidemia) were the surfaced instances of that
# design characteristic.
#
# When present, an axis is considered acceptable if it hits EITHER the
# general benchmark above OR the hospital-cohort target below. Printed
# marker is "OK   " for general match, "OK-HC" for hospital-cohort match
# only, "OUT  " for neither. Absent an entry here, the axis is judged on
# the general benchmark alone (behavior unchanged from pre-#1109).
HOSPITAL_COHORT_TARGET = {
    "US": {
        # Values reflect Medicare-user cohort per the YAML comments in
        # clinosim/locale/us/demographics.yaml chronic_prevalence.
        "copd_adult_prev_pct": (8, 14),  # YAML target ~12% (Medicare-user)
        "diabetes_adult_prev_pct": (14, 22),  # YAML target ~18-20% (Medicare-user)
        "dyslipidemia_adult_prev_pct": (40, 60),  # YAML target ~55% (Medicare-user)
        # Issue #1117 (C11j, 2026-09-05): US hospital-catchment median age
        # sits +5-15 yr above general Census — care-seeking filter drops
        # non-visitors, elderly seek more care. Header note "hospital patient
        # population ≠ general population, so some prevalences legitimately
        # deviate" applies to median age too.
        "median_age": (45, 60),  # Medicare-user hospital median
        "outpatient_share_pct": (60, 95),  # chronic-care AMB heavy
    },
    "JP": {
        # Values reflect hospital-cohort skew per YAML comments in
        # clinosim/locale/jp/demographics.yaml chronic_prevalence.
        "copd_adult_prev_pct": (8, 14),  # YAML target ~12% (elderly hospital-catchment)
        "diabetes_adult_prev_pct": (15, 22),  # YAML target ~15-20% (hospital-catchment)
        "dyslipidemia_adult_prev_pct": (40, 60),  # YAML target ~50-55% (hospital-catchment)
        # Issue #1117 (C11j, 2026-09-05): JP hospital 65+ ≈ 56 % of total per
        # MHLW 患者調査 2020 (referenced in demographics.yaml header),
        # yielding cohort median age ~60-68 vs general population ~48.
        "median_age": (58, 68),  # MHLW hospital-catchment median
        "outpatient_share_pct": (60, 95),  # chronic-care AMB heavy
    },
}

b = BENCH[COUNTRY]
b_hc = HOSPITAL_COHORT_TARGET.get(COUNTRY, {})

# --- Patient roll: sex, age, deceased ---
patients = {}
for p in read_nd(FHIR / "Patient.ndjson"):
    bd = p.get("birthDate", "")[:4]
    try:
        birth_y = int(bd)
    except (TypeError, ValueError):
        birth_y = None
    patients[p["id"]] = {
        "sex": p.get("gender", ""),
        "birth_year": birth_y,
        "deceased": bool(p.get("deceasedDateTime") or p.get("deceasedBoolean")),
        "death_date": p.get("deceasedDateTime", "")[:10],
    }
n_pat = len(patients)
n_adult = sum(1 for x in patients.values() if x["birth_year"] and (2024 - x["birth_year"]) >= 18)
n_deceased = sum(1 for x in patients.values() if x["deceased"])

# Median age at 2024
ages = sorted(2024 - x["birth_year"] for x in patients.values() if x["birth_year"])
median_age = ages[len(ages) // 2] if ages else None
mean_age = sum(ages) / len(ages) if ages else None

# Sex ratio
sex_dist = Counter(x["sex"] for x in patients.values())

# Age pyramid buckets
buckets = Counter()
for a in ages:
    if a < 5:
        buckets["00-04"] += 1
    elif a < 15:
        buckets["05-14"] += 1
    elif a < 25:
        buckets["15-24"] += 1
    elif a < 45:
        buckets["25-44"] += 1
    elif a < 65:
        buckets["45-64"] += 1
    elif a < 75:
        buckets["65-74"] += 1
    elif a < 85:
        buckets["75-84"] += 1
    else:
        buckets["85+"] += 1

# --- Chronic disease prevalence (adult, unique patients with any Condition of code) ---
prefixes = {
    "hypertension": ("I10", "I11", "I12", "I13", "I15"),
    "diabetes": ("E10", "E11", "E13", "E14"),
    "copd": ("J44",),
    "asthma": ("J45",),
    "ckd": ("N18",),
    "cad": ("I20", "I21", "I22", "I23", "I24", "I25"),
    "chf": ("I50", "I11.0", "I13.0"),
    "dyslipidemia": ("E78",),
    "cancer_any": tuple(f"C{n:02d}" for n in range(0, 100)) + tuple(f"D{n:02d}" for n in range(0, 49)),
}
adult_with_dx = {k: set() for k in prefixes}
# also incidence tallies (encounters or conditions with dates in sim period)
acute_prefixes = {
    "mi": ("I21", "I22"),
    "stroke": ("I63", "I61", "I60", "I64", "I65", "I66", "I67", "I68"),
    "sepsis": ("A40", "A41", "R65.20", "R65.21"),
    "pneumonia": ("J13", "J14", "J15", "J16", "J17", "J18", "J12", "J09", "J10", "J11"),
    "appendicitis": ("K35", "K36", "K37"),
    "cholecystitis": ("K80", "K81"),
}
acute_cases = {k: set() for k in acute_prefixes}  # unique (patient, year, code_prefix)


def code_starts(codes, prefixes_tuple):
    return any(cc.startswith(prefixes_tuple) for cc in codes)


for c in read_nd(FHIR / "Condition.ndjson"):
    pid = (c.get("subject", {}).get("reference", "") or "").replace("Patient/", "")
    if pid not in patients:
        continue
    age = None
    if patients[pid]["birth_year"]:
        age = 2024 - patients[pid]["birth_year"]
    codes = [cd.get("code", "") for cd in c.get("code", {}).get("coding", [])]
    for name, pfx in prefixes.items():
        if code_starts(codes, pfx):
            if age is not None and age >= 18:
                adult_with_dx[name].add(pid)
    onset = c.get("onsetDateTime", "")[:10]
    for name, pfx in acute_prefixes.items():
        if code_starts(codes, pfx):
            acute_cases[name].add(c.get("id"))

# --- Encounter mix ---
enc_class = Counter()
enc_dates = Counter()
total_enc = 0
for e in read_nd(FHIR / "Encounter.ndjson"):
    cls = e.get("class", {}).get("code", "")
    enc_class[cls] += 1
    total_enc += 1

# ED = 'EMER', inpatient = 'IMP', outpatient = 'AMB' (or others)
ed = enc_class.get("EMER", 0)
imp = enc_class.get("IMP", 0)
amb = enc_class.get("AMB", 0) + enc_class.get("ambulatory", 0)
other = total_enc - ed - imp - amb


# --- Print report ---
def band(name, val, low, high, unit="", hc_key=""):
    """Format an axis line. When ``hc_key`` is set and the value falls outside
    the general benchmark but inside the hospital-cohort target for that key,
    prints "OK-HC" (hospital-cohort acceptable) with both bands. Otherwise
    prints "OK " or "OUT" against the general benchmark alone."""
    ok = low <= val <= high if val is not None else False
    hc_lo, hc_hi = b_hc.get(hc_key, (None, None)) if hc_key else (None, None)
    hc_ok = (hc_lo is not None and hc_lo <= val <= hc_hi) if val is not None else False
    if ok:
        marker = "OK "
        tail = ""
    elif hc_ok:
        marker = "OK-HC"
        tail = f" hospital-cohort {hc_lo}-{hc_hi}{unit}"
    else:
        marker = "OUT"
        tail = f" hospital-cohort {hc_lo}-{hc_hi}{unit}" if hc_lo is not None else ""
    return f"  [{marker}] {name:44s} = {val:>8.2f}{unit}  benchmark {low}-{high}{unit}{tail}"


print(f"===== {COUNTRY}  p={n_pat} adults={n_adult}  ({SIM_YEARS} yr sim) =====\n")

print("--- Demographics ---")
print(f"  patients: {n_pat}, adults(≥18@2024): {n_adult}, deceased: {n_deceased}")
print(f"  sex distribution: {dict(sex_dist)}")
print(f"  median age (2024): {median_age}, mean age: {mean_age:.1f}")
print(band("median_age", median_age, *b["median_age"], hc_key="median_age"))
print(f"  age pyramid: {dict(sorted(buckets.items()))}")

print("\n--- Chronic disease prevalence (unique adult patients) ---")


def prev_pct(name):
    return (len(adult_with_dx[name]) / n_adult * 100) if n_adult else 0


for name in ["hypertension", "diabetes", "copd", "asthma", "ckd", "cad", "chf", "dyslipidemia", "cancer_any"]:
    v = prev_pct(name)
    hc_key = f"{name}_adult_prev_pct" if name != "cancer_any" else "cancer_any_active_prev_pct"
    lo, hi = b.get(hc_key, ("", ""))
    print(band(f"{name}_prev", v, lo, hi, "%", hc_key=hc_key) + f"  (unique adults n={len(adult_with_dx[name])})")

print("\n--- Acute / incidence (per 1000 population per year) ---")
for name in ["mi", "stroke", "sepsis", "pneumonia"]:
    n = len(acute_cases[name])
    per_1000_yr = n / n_pat * 1000 / SIM_YEARS
    key = f"{name}_incidence_per_1000_yr" if name != "pneumonia" else "pneumonia_hosp_per_1000_yr"
    lo, hi = b.get(key, (0, 100))
    print(band(f"{name}_incidence", per_1000_yr, lo, hi, "/1000/yr") + f"  (cases n={n})")
for name in ["appendicitis", "cholecystitis"]:
    n = len(acute_cases[name])
    per_1000_yr = n / n_pat * 1000 / SIM_YEARS
    print(f"  [   ] {name + '_incidence':44s} = {per_1000_yr:>8.2f}/1000/yr  (no benchmark; n={n})")

print("\n--- Mortality (per 1000 per year) ---")
mort = n_deceased / n_pat * 1000 / SIM_YEARS
lo, hi = b["mortality_per_1000_yr"]
print(band("mortality_all_cause", mort, lo, hi, "/1000/yr") + f"  (deceased n={n_deceased})")

print("\n--- Encounter mix ---")


def enc_pct(k):
    return (k / total_enc * 100) if total_enc else 0


print(f"  total encounters: {total_enc}, class dist: {dict(enc_class)}")
print(band("outpatient_share (AMB)", enc_pct(amb), *b["outpatient_share_pct"], "%", hc_key="outpatient_share_pct"))
print(band("ed_share (EMER)", enc_pct(ed), *b["ed_share_pct"], "%"))
print(band("inpatient_share (IMP)", enc_pct(imp), *b["inpatient_share_pct"], "%"))
if other:
    print(f"  other encounter classes: {other} ({enc_pct(other):.1f}%)")


# ---------------------------------------------------------------------------
# Issue #1066 (drug_safety): contraindicated pair count in FHIR MRs
# ---------------------------------------------------------------------------
try:
    from clinosim.modules.drug_safety.engine import check_pair as _check_pair

    print("\n--- Drug safety (Issue #1066) ---")
    fhir_dir = Path(sys.argv[1]) / "fhir_r4"
    if not fhir_dir.exists():
        fhir_dir = Path(sys.argv[1])  # caller may pass fhir dir directly
    mr_file = fhir_dir / "MedicationRequest.ndjson"
    if not mr_file.exists():
        print(f"  [WARN] MedicationRequest.ndjson not found under {fhir_dir}")
    else:
        per_patient: dict[str, list[str]] = {}
        for line in mr_file.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            mr = json.loads(line)
            subject = mr.get("subject", {}).get("reference", "")
            display = ""
            med = mr.get("medicationCodeableConcept", {})
            for cd in med.get("coding", []) or []:
                if cd.get("display"):
                    display = cd["display"]
                    break
            if not display:
                display = med.get("text", "")
            if display and subject:
                per_patient.setdefault(subject, []).append(display)
        pair_counts: Counter = Counter()
        for drugs in per_patient.values():
            for i, a in enumerate(drugs):
                for b_ in drugs[i + 1 :]:
                    v = _check_pair(a, b_)
                    if v.severity in {"major", "contraindicated"}:
                        pair_counts[v.rule_id or "unknown"] += 1
        total = sum(pair_counts.values())
        print(f"  contraindicated_pair_count (major + contraindicated): {total} (target: 0)")
        if pair_counts:
            for rule_id, cnt in pair_counts.most_common():
                print(f"    {rule_id}: {cnt}")
except ImportError:
    print("\n[SKIP] clinosim.modules.drug_safety not importable — skip drug_safety metrics")
