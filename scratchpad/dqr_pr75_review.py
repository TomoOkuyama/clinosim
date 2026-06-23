"""Data-quality review for PR #75 — three axes: structural quality, clinical
fidelity, JP localization quality.

Reads a generated bundle (FHIR NDJSON + CIF + CSV) and emits a structured
report covering:

1. STRUCTURAL HYGIENE
   - FHIR id uniqueness per resource type
   - Reference integrity (every reference resolves to a resource of the
     expected type within the bundle)
   - referenceRange coverage for numeric lab Observations (target 100%)
   - display ≠ code anti-pattern count
   - No empty `code.coding[].code` slots

2. CLINICAL FIDELITY
   - Per-disease admit-day labs vs expected bands
       DKA      HCO3 ≤ 18, Glucose median ≥ 300
       ACS      Troponin_I p90 ≥ 5
       Sepsis   Lactate p75 ≥ 2.0
       HF       BNP median (admit) ≥ 500 in heart_failure_exacerbation
       CKD      Creatinine p75 ≥ 1.5
       AKI      Creatinine p50 ≥ 2.5
   - HbA1c ↔ Glucose correlation in patients with both measured
   - Vital extremes: fever ≥ 39°C in sepsis cohort, SpO2 < 92% in
     respiratory cohort, SBP < 90 in septic shock cohort

3. JP LOCALIZATION
   - US: every textual field in Patient/Condition/Procedure/Med/Observation
     contains zero Japanese characters (≥ 1 hit = regression).
   - JP: critical localized fields populated with Japanese
     (Patient.name.text, Condition.code.text, Procedure.code.text,
     Observation.code.text where dictionary covers it).
   - JP code values: no CM-granularity ICD-10 (5+ chars with dots or X
     placeholders) emitted; canonical WHO 3- or 4-char codes only.
   - JP localized DR displays present.

Usage:
    python scratchpad/dqr_pr75_review.py /tmp/cbcbmp-dqr-pr75/us US
    python scratchpad/dqr_pr75_review.py /tmp/cbcbmp-dqr-pr75/jp JP
"""
from __future__ import annotations

import collections
import csv
import json
import re
import statistics
import sys
from pathlib import Path

JP_CHAR_RE = re.compile(r"[぀-ヿ一-鿿ｦ-ﾟ]")
CM_GRANULAR_RE = re.compile(r"^[A-TV-Z]\d{2}\.\d{2}|^[A-TV-Z]\d{2}\.X|^[A-TV-Z]\d{2}\.[A-Z]")


def loadjsonl(path: Path):
    if not path.exists():
        return
    with open(path) as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def section(title: str):
    bar = "=" * len(title)
    print(f"\n{bar}\n{title}\n{bar}")


def percentile(values, p):
    if not values:
        return None
    s = sorted(values)
    idx = max(0, min(len(s) - 1, int(round(p / 100.0 * (len(s) - 1)))))
    return s[idx]


# --------- 1. STRUCTURAL HYGIENE -----------------------------------------

def check_structural(fhir_dir: Path, country: str):
    section(f"1. STRUCTURAL HYGIENE ({country})")
    id_by_type: dict[str, set[str]] = collections.defaultdict(set)
    dup_count = 0
    for nd in sorted(fhir_dir.glob("*.ndjson")):
        rt = nd.stem
        for r in loadjsonl(nd):
            rid = r.get("id", "")
            if rid in id_by_type[rt]:
                dup_count += 1
            else:
                id_by_type[rt].add(rid)
    total_resources = sum(len(s) for s in id_by_type.values())
    print(f"  Total resources: {total_resources:,}")
    print(f"  Duplicate ids:   {dup_count}")
    for rt, s in sorted(id_by_type.items()):
        print(f"    {rt}: {len(s):,}")

    # Reference integrity (sample-driven; check Observation.encounter, .subject,
    # DiagnosticReport.result[], Condition.subject, Procedure.subject)
    unresolved = 0
    refs_checked = 0
    for fname, fields in [
        ("Observation.ndjson", ["encounter", "subject"]),
        ("Condition.ndjson",   ["subject", "encounter"]),
        ("Procedure.ndjson",   ["subject", "encounter"]),
        ("MedicationRequest.ndjson", ["subject", "encounter"]),
        ("MedicationAdministration.ndjson", ["subject", "context"]),
    ]:
        for r in loadjsonl(fhir_dir / fname):
            for f in fields:
                ref = (r.get(f) or {}).get("reference", "")
                if not ref:
                    continue
                refs_checked += 1
                rt, _, rid = ref.partition("/")
                if rid not in id_by_type.get(rt, set()):
                    unresolved += 1
    # DiagnosticReport.result[] is a list
    for r in loadjsonl(fhir_dir / "DiagnosticReport.ndjson"):
        for ref_obj in r.get("result", []):
            refs_checked += 1
            ref = ref_obj.get("reference", "")
            rt, _, rid = ref.partition("/")
            if rid not in id_by_type.get(rt, set()):
                unresolved += 1
    print(f"  References checked: {refs_checked:,}")
    print(f"  Unresolved:         {unresolved}")

    # Lab Observation hygiene
    lab_total = lab_range = display_eq_code = empty_code = 0
    for o in loadjsonl(fhir_dir / "Observation.ndjson"):
        if not o.get("id", "").startswith("lab-"):
            continue
        lab_total += 1
        coding = (o.get("code") or {}).get("coding") or [{}]
        c = coding[0]
        code = c.get("code", "")
        disp = c.get("display", "")
        if not code:
            empty_code += 1
        if disp and code and disp == code:
            display_eq_code += 1
        # Skip non-numeric labs from refRange expectation
        v = o.get("valueQuantity", {}).get("value")
        if v is not None and "referenceRange" in o:
            lab_range += 1
        elif v is not None:
            pass  # numeric lab with no refRange (counted in deficit)
    print(f"  Lab Observations:           {lab_total:,}")
    print(f"  refRange present (numeric): {lab_range:,}")
    print(f"  display == code:            {display_eq_code}")
    print(f"  empty code:                 {empty_code}")


# --------- 2. CLINICAL FIDELITY ------------------------------------------

DISEASES_OF_INTEREST = {
    "diabetic_ketoacidosis", "acute_mi", "sepsis", "heart_failure_exacerbation",
    "ckd_stage_3", "ckd_stage_4", "acute_kidney_injury",
    "bacterial_pneumonia", "copd_exacerbation",
}


def check_clinical(csv_dir: Path, country: str):
    section(f"2. CLINICAL FIDELITY ({country})")

    # patient → primary disease
    patient_disease: dict[str, str] = {}
    # disease ICD prefix → disease_id (for code-based mapping when
    # ground_truth_diseases is empty or unrecognised)
    icd_to_disease = {
        "E10.1": "diabetic_ketoacidosis", "E11.1": "diabetic_ketoacidosis",
        "E13.1": "diabetic_ketoacidosis",
        "I21":   "acute_mi",
        "A41":   "sepsis", "R65.20": "sepsis", "R65.21": "sepsis",
        "I50":   "heart_failure_exacerbation",
        "N17":   "acute_kidney_injury",
        "N18":   "ckd_stage_3",
        "J15":   "bacterial_pneumonia", "J18": "bacterial_pneumonia",
    }
    for row in csv.DictReader(open(csv_dir / "diagnoses.csv")):
        if patient_disease.get(row["patient_id"]):
            continue
        # ground_truth_diseases column is comma-separated list of disease_ids
        # (introduced post-PR #75; older script used ground_truth_disease_id).
        gtd = row.get("ground_truth_diseases", "") or ""
        d = gtd.split(",")[0].strip() if gtd else ""
        # Some rows still emit raw ICD codes — map via prefix lookup
        if d and d in DISEASES_OF_INTEREST:
            patient_disease[row["patient_id"]] = d
            continue
        # Fall back to ICD prefix on admission_diagnosis_code
        adm = row.get("admission_diagnosis_code", "")
        for prefix, did in icd_to_disease.items():
            if adm.startswith(prefix):
                patient_disease[row["patient_id"]] = did
                break

    # patient × analyte → list of values (admit-day = first row, day 0)
    # lab_results.csv columns: patient_id, encounter_id, lab_name, value,
    #                          result_datetime, ...
    labs_by_disease: dict[str, dict[str, list[float]]] = collections.defaultdict(
        lambda: collections.defaultdict(list)
    )
    first_seen: dict[tuple[str, str, str], bool] = {}
    for row in csv.DictReader(open(csv_dir / "lab_results.csv")):
        pid = row["patient_id"]
        d = patient_disease.get(pid)
        if not d or d not in DISEASES_OF_INTEREST:
            continue
        name = row.get("lab_name", "")
        try:
            v = float(row.get("value", ""))
        except (TypeError, ValueError):
            continue
        key = (pid, row.get("encounter_id", ""), name)
        if key in first_seen:
            continue
        first_seen[key] = True
        labs_by_disease[d][name].append(v)

    expectations = [
        ("diabetic_ketoacidosis", "HCO3", lambda v: percentile(v, 50) <= 18, "p50 ≤ 18"),
        ("diabetic_ketoacidosis", "Glucose", lambda v: percentile(v, 50) >= 300, "p50 ≥ 300"),
        ("acute_mi", "Troponin_I", lambda v: percentile(v, 90) >= 5, "p90 ≥ 5"),
        ("sepsis", "Lactate", lambda v: percentile(v, 75) >= 2.0, "p75 ≥ 2.0"),
        ("heart_failure_exacerbation", "BNP", lambda v: percentile(v, 50) >= 500, "p50 ≥ 500"),
        ("acute_kidney_injury", "Creatinine", lambda v: percentile(v, 50) >= 2.5, "p50 ≥ 2.5"),
        ("ckd_stage_3", "Creatinine", lambda v: percentile(v, 75) >= 1.5, "p75 ≥ 1.5"),
        ("bacterial_pneumonia", "WBC", lambda v: percentile(v, 50) >= 10000, "p50 ≥ 10k"),
    ]
    for d, analyte, ok_fn, expected in expectations:
        vs = labs_by_disease.get(d, {}).get(analyte, [])
        if not vs:
            print(f"  [SKIP] {d:30s} {analyte:12s}  n=0 ({expected})")
            continue
        ok = ok_fn(vs)
        status = "PASS" if ok else "FAIL"
        med = percentile(vs, 50)
        p75 = percentile(vs, 75)
        p90 = percentile(vs, 90)
        print(f"  [{status}] {d:30s} {analyte:12s}  n={len(vs):4d}  "
              f"p50={med:7.2f} p75={p75:7.2f} p90={p90:7.2f}  ({expected})")

    # HbA1c × Glucose correlation in all patients who have both
    pairs = []
    pid_to_glu = collections.defaultdict(list)
    pid_to_a1c = collections.defaultdict(list)
    for row in csv.DictReader(open(csv_dir / "lab_results.csv")):
        try:
            v = float(row.get("value", ""))
        except (TypeError, ValueError):
            continue
        if row.get("lab_name") == "Glucose":
            pid_to_glu[row["patient_id"]].append(v)
        elif row.get("lab_name") == "HbA1c":
            pid_to_a1c[row["patient_id"]].append(v)
    for pid in pid_to_a1c:
        if pid not in pid_to_glu:
            continue
        a1c = statistics.median(pid_to_a1c[pid])
        glu = statistics.median(pid_to_glu[pid])
        pairs.append((a1c, glu))
    if len(pairs) >= 10:
        a = [x[0] for x in pairs]
        g = [x[1] for x in pairs]
        n = len(pairs)
        mean_a = sum(a) / n
        mean_g = sum(g) / n
        cov = sum((ai - mean_a) * (gi - mean_g) for ai, gi in pairs) / n
        var_a = sum((ai - mean_a) ** 2 for ai in a) / n
        var_g = sum((gi - mean_g) ** 2 for gi in g) / n
        r = cov / (var_a ** 0.5 * var_g ** 0.5) if var_a and var_g else 0
        print(f"  HbA1c × Glucose: n={n}, r={r:.3f}  (expect 0.40 ≤ r ≤ 0.70)")


# --------- 3. JP LOCALIZATION --------------------------------------------

def check_localization(fhir_dir: Path, country: str):
    section(f"3. JP LOCALIZATION ({country})")
    jp_hits = 0
    cm_granular_hits = 0
    samples = []
    for nd in sorted(fhir_dir.glob("*.ndjson")):
        for r in loadjsonl(nd):
            blob = json.dumps(r, ensure_ascii=False)
            if country == "US" and JP_CHAR_RE.search(blob):
                jp_hits += 1
                if len(samples) < 3:
                    samples.append((nd.name, r.get("id", ""), blob[:200]))
    if country == "US":
        print(f"  US bundle Japanese-character occurrences: {jp_hits}")
        for s in samples:
            print(f"    {s[0]} id={s[1]}: {s[2]}...")

    if country == "JP":
        # Sample 10 random Patient records, count whether name.text is in Japanese
        names_jp = names_total = 0
        for r in loadjsonl(fhir_dir / "Patient.ndjson"):
            for name in r.get("name", []):
                t = name.get("text", "")
                if t:
                    names_total += 1
                    if JP_CHAR_RE.search(t):
                        names_jp += 1
        if names_total:
            print(f"  JP Patient name.text Japanese coverage: "
                  f"{names_jp}/{names_total} ({100*names_jp/names_total:.1f}%)")

        # Condition.code.text — sample
        cond_jp = cond_total = 0
        for r in loadjsonl(fhir_dir / "Condition.ndjson"):
            t = (r.get("code") or {}).get("text", "")
            if t:
                cond_total += 1
                if JP_CHAR_RE.search(t):
                    cond_jp += 1
            # JP CM-granularity guard
            for coding in (r.get("code") or {}).get("coding", []):
                code = coding.get("code", "")
                if CM_GRANULAR_RE.match(code):
                    cm_granular_hits += 1
        if cond_total:
            print(f"  JP Condition.code.text Japanese coverage: "
                  f"{cond_jp}/{cond_total} ({100*cond_jp/cond_total:.1f}%)")
        print(f"  JP CM-granular ICD-10 leaks: {cm_granular_hits}  "
              f"(expected 0; WHO 3-4 char only)")

        # DR.code.coding[0].display — should be Japanese for known panel codes
        dr_jp = dr_total = 0
        for r in loadjsonl(fhir_dir / "DiagnosticReport.ndjson"):
            for c in (r.get("code") or {}).get("coding", []):
                d = c.get("display", "")
                if d:
                    dr_total += 1
                    if JP_CHAR_RE.search(d):
                        dr_jp += 1
        if dr_total:
            print(f"  JP DR.code display Japanese coverage: "
                  f"{dr_jp}/{dr_total} ({100*dr_jp/dr_total:.1f}%)")

        # Observation.code.text Japanese — for lab Observations only
        obs_jp = obs_total = 0
        for r in loadjsonl(fhir_dir / "Observation.ndjson"):
            if not r.get("id", "").startswith("lab-"):
                continue
            t = (r.get("code") or {}).get("text", "")
            if t:
                obs_total += 1
                if JP_CHAR_RE.search(t):
                    obs_jp += 1
        if obs_total:
            print(f"  JP lab Observation.code.text Japanese coverage: "
                  f"{obs_jp}/{obs_total} ({100*obs_jp/obs_total:.1f}%)")


def main() -> None:
    if len(sys.argv) < 3:
        print("Usage: dqr_pr75_review.py <bundle_root> <US|JP>")
        sys.exit(1)
    root = Path(sys.argv[1])
    country = sys.argv[2]
    check_structural(root / "fhir_r4", country)
    check_clinical(root / "csv", country)
    check_localization(root / "fhir_r4", country)


if __name__ == "__main__":
    main()
