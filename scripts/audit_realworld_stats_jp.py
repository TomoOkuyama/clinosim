"""Compare a clinosim JP FHIR ndjson cohort to real-world Japanese statistics.

Runs a multi-dimension distribution audit over a directory of Patient /
Condition / Immunization / Encounter / Observation / AllergyIntolerance
ndjson files. For each dimension it prints actual vs target vs a
real-world benchmark, flagging deviations >5% (⚠️) and >10% (❌).

**Benchmark selection is critical.** Two dimensions in particular use
non-obvious benchmarks and were historically mis-compared against the
general Census / per-season statistic:

* **Age distribution**: compared against MHLW 患者調査 2020
  (hospital-attending patient population), not 国勢調査
  (general-population Census). The emitted cohort is care-seeking
  filtered so it skews elderly-heavy by design — see
  ``clinosim/modules/population/README.md`` "Cohort skew vs sampled
  population".
* **Immunization coverage**: compared per-season for annual vaccines
  and per-lifetime for `once` vaccines, not the aggregate
  "% of patients with ≥1 record". See
  ``clinosim/modules/immunization/README.md`` "Cumulative record vs
  per-season semantics".

Chronic disease targets come from ``clinosim/locale/jp/demographics.yaml``
config and are cross-checked against MHLW / JCS / JDS / JSN guideline
prevalence.

Usage
-----

    python scripts/audit_realworld_stats_jp.py <fhir_r4_dir>

Where ``<fhir_r4_dir>`` is a directory containing ``*.ndjson`` files
(one FHIR resource per line). Typical layout::

    <cohort>/jp/fhir_r4/Patient.ndjson
    <cohort>/jp/fhir_r4/Condition.ndjson
    ...

Exit code 0 always; the deviations are reported textually. This is a
diagnostic, not a hard gate.
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import sys

# ---------------------------------------------------------------------------
# Benchmarks
# ---------------------------------------------------------------------------

# MHLW 患者調査 2020 総患者数 (千人) 年齢階級別 (approximate share of the
# hospital-attending patient population). This is the CORRECT benchmark for
# clinosim's emitted patient cohort — comparing against general-population
# Census (国勢調査) is an apples-to-oranges error because the emitted cohort
# is filtered through care-seeking + encounter emission gates.
# Source: https://www.mhlw.go.jp/toukei/saikin/hw/kanja/20/index.html
MHLW_PATIENT_SURVEY_AGE_2020 = {
    "0-14": 0.054,
    "15-24": 0.032,
    "25-34": 0.053,
    "35-44": 0.074,
    "45-54": 0.101,
    "55-64": 0.127,
    "65-74": 0.212,
    "75-84": 0.208,
    "85+": 0.140,
}

# JP chronic disease per-code age-band prevalence config targets, mirrored
# from clinosim/locale/jp/demographics.yaml. Keep in sync when the config
# moves.
CHRONIC_CONFIG_TARGETS_JP = {
    "I10": [("40-59", 0.20), ("60-69", 0.50), ("70-99", 0.65)],
    "E11": [("40-59", 0.04), ("60-69", 0.09), ("70-99", 0.11)],
    "E78": [("40-59", 0.15), ("60-69", 0.40), ("70-99", 0.45)],
    "J44": [("40-59", 0.03), ("60-99", 0.10)],
    "N18": [("60-69", 0.06), ("70-99", 0.12)],
    "I50": [("65-74", 0.03), ("75-99", 0.08)],
    "I48": [("50-74", 0.015), ("75-99", 0.09)],
    "I25": [("50-69", 0.03), ("70-99", 0.10)],
    "M81": [("60-69", 0.15), ("70-99", 0.25)],
    "F00": [("65-84", 0.03), ("85-99", 0.16)],
}
REAL_WORLD_JP_NOTES = {
    "I10": "MHLW 高血圧 40+ 40-50%, 60+ 60%+ (JSH 2019)",
    "E11": "MHLW 糖尿病 20+ 12.1%, 70+ 20%+ (JDS 2019)",
    "E78": "脂質異常症 40+ 25-40% (JAS 2022)",
    "J44": "COPD 40+ 8.6%, 診断済 5% (NICE 2001)",
    "N18": "CKD 20+ 13% (JSN 2015)",
    "I50": "心不全 高齢者 5-10% (JCS 2018)",
    "I48": "AFib 全体 1-2%, 80+ 5%+ (JCS 2020)",
    "I25": "冠動脈疾患 60+ 5-15% (JCS 2018)",
    "M81": "骨粗鬆症 女性 65+ 30%+, 男性 20% (JOSTEO 2015)",
    "F00": "認知症 65+ 15%, 85+ 40% (MHLW 2020)",
}

# JP immunization per-season / per-lifetime targets, mirrored from
# clinosim/locale/jp/immunization_schedule.yaml.
IMM_TARGETS_JP = {
    "flu_annual_65plus_M": 0.55,
    "flu_annual_65plus_F": 0.58,
    "covid_once_65plus_M": 0.90,
    "covid_once_65plus_F": 0.92,
    "pneumo_once_65plus_M": 0.40,
    "pneumo_once_65plus_F": 0.42,
}
FLU_HISTORY_YEARS = 10  # from immunization_schedule.yaml

# Lifestyle-observation category tables (Observation.id prefix → real-world
# benchmark line).
LIFESTYLE_OBS_TABLE = [
    (
        "3. Smoking status (adults 20+, by sex)",
        "smoking-",
        "MHLW 国民健康・栄養調査 2019: 男 27.1%, 女 7.6% current",
    ),
    (
        "4. Alcohol use (adults 20+, by sex)",
        "alcohol-",
        "MHLW 国民健康・栄養調査 2019: 男 大量飲酒者 14.9%, 女 9.1%",
    ),
]

# ---------------------------------------------------------------------------
# Loading helpers
# ---------------------------------------------------------------------------


def load_bundle(fhir_dir: str) -> dict[str, list[dict]]:
    resources: dict[str, list[dict]] = collections.defaultdict(list)
    for name in sorted(os.listdir(fhir_dir)):
        if not name.endswith(".ndjson"):
            continue
        rtype = name.replace(".ndjson", "")
        with open(os.path.join(fhir_dir, name)) as fh:
            for line in fh:
                resources[rtype].append(json.loads(line))
    return resources


def _age_bucket(age: int) -> str:
    for lo, hi, label in [
        (0, 14, "0-14"),
        (15, 24, "15-24"),
        (25, 34, "25-34"),
        (35, 44, "35-44"),
        (45, 54, "45-54"),
        (55, 64, "55-64"),
        (65, 74, "65-74"),
        (75, 84, "75-84"),
        (85, 999, "85+"),
    ]:
        if lo <= age <= hi:
            return label
    return "?"


def _in_band(age: int, band: str) -> bool:
    lo, hi = map(int, band.split("-"))
    return lo <= age <= hi


def _section(t: str) -> None:
    print(f"\n{'=' * 78}\n{t}\n{'=' * 78}")


def _cmp(label: str, actual: float, target: float, tol: float = 0.05, source: str = "") -> None:
    delta = actual - target
    status = "✅" if abs(delta) <= tol else ("⚠️" if abs(delta) <= tol * 2 else "❌")
    print(f"  {status} {label}: actual={actual:.3f} vs target={target:.3f} (Δ={delta:+.3f}) [{source}]")


# ---------------------------------------------------------------------------
# Dimension audits
# ---------------------------------------------------------------------------


def audit_sex(pts: list[dict], n: int) -> None:
    _section("1. Sex distribution (M:F ratio)")
    sex = collections.Counter(p.get("gender") for p in pts)
    _cmp("M ratio", sex.get("male", 0) / n, 0.487, tol=0.03, source="Census 2020 M 48.7%")
    _cmp("F ratio", sex.get("female", 0) / n, 0.513, tol=0.03, source="Census 2020 F 51.3%")


ELDERLY_BANDS = ("65-74", "75-84", "85+")


def audit_age(n: int, ages_by_pid: dict[str, int]) -> None:
    _section("2. Age distribution vs MHLW 患者調査 2020 (hospital patients)")
    print("  [Not general-population Census — clinosim emits a care-seeking-filtered patient cohort;")
    print("   see modules/population/README.md 'Cohort skew vs sampled population'.]")
    bkt = collections.Counter(_age_bucket(a) for a in ages_by_pid.values())
    for label, target in MHLW_PATIENT_SURVEY_AGE_2020.items():
        actual = bkt.get(label, 0) / n
        _cmp(f"age {label}", actual, target, tol=0.03, source="MHLW 患者調査 2020")
    share_65 = sum(bkt.get(band, 0) for band in ELDERLY_BANDS) / n
    target_65 = sum(MHLW_PATIENT_SURVEY_AGE_2020[band] for band in ELDERLY_BANDS)
    _cmp(
        "65+ share",
        share_65,
        target_65,
        tol=0.05,
        source="MHLW 患者調査 2020 65+ ≈ 56%",
    )


def audit_smoking_alcohol(resources: dict, pts: list[dict], ages_by_pid: dict[str, int]) -> None:
    for label, prefix, real in LIFESTYLE_OBS_TABLE:
        _section(label)
        pid_by_id = {p["id"]: p for p in pts}
        by_sex_code: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
        for observation in resources.get("Observation", []):
            if not observation.get("id", "").startswith(prefix):
                continue
            pid = observation.get("subject", {}).get("reference", "").replace("Patient/", "")
            pt = pid_by_id.get(pid)
            if not pt:
                continue
            if ages_by_pid.get(pid, 0) < 20:
                continue
            codings = observation.get("valueCodeableConcept", {}).get("coding") or [{}]
            code = codings[0].get("code", "?")
            by_sex_code[pt.get("gender", "?")][code] += 1
        for sex_label in ("male", "female"):
            counts = by_sex_code.get(sex_label, {})
            total = sum(counts.values())
            if total:
                print(f"  {sex_label} n={total}: {dict(counts)}")
        print(f"  [real: {real}]")


def audit_chronic(resources: dict, pts: list[dict], ages_by_pid: dict[str, int]) -> dict[str, set[str]]:
    _section("5. Chronic disease prevalence (config target vs actual vs 実世界)")
    pt_chronic: dict[str, set[str]] = collections.defaultdict(set)
    for condition in resources.get("Condition", []):
        if condition.get("encounter"):
            continue
        pid = condition.get("subject", {}).get("reference", "").replace("Patient/", "")
        for coding in condition.get("code", {}).get("coding") or []:
            code = coding.get("code", "").split(".")[0]
            if code:
                pt_chronic[pid].add(code)
                break

    for code, bands in CHRONIC_CONFIG_TARGETS_JP.items():
        for band, target in bands:
            in_band_pts = [pid for pid, a in ages_by_pid.items() if _in_band(a, band)]
            if not in_band_pts:
                continue
            with_code = sum(1 for pid in in_band_pts if code in pt_chronic.get(pid, set()))
            actual = with_code / len(in_band_pts)
            _cmp(
                f"{code} age {band}",
                actual,
                target,
                tol=0.05,
                source=f"config / {REAL_WORLD_JP_NOTES.get(code, '')[:60]}",
            )

    _section("6. Chronic conditions per patient")
    counts = collections.Counter(len(codes) for codes in pt_chronic.values())
    n = len(pts)
    for c in range(15):
        if c in counts:
            print(f"  {c} conditions: {counts[c]:4d} ({100 * counts[c] / n:.1f}%)")
    zero = n - sum(counts.values())
    if zero:
        print(f"  0 conditions: {zero:4d} ({100 * zero / n:.1f}%)")
    total_conditions = sum(k * v for k, v in counts.items())
    print(f"  MEAN chronic conditions/patient: {total_conditions / n:.2f}")
    print("  [real: MHLW 国民生活基礎調査 2019 — 65+ 平均 2.3, 全年齢 1.4 (慢性疾患保有数)]")
    return pt_chronic


def audit_encounters(resources: dict) -> None:
    _section("7. Encounter class distribution")
    enc_types = collections.Counter(e.get("class", {}).get("code") for e in resources.get("Encounter", []))
    total = sum(enc_types.values())
    if not total:
        print("  (no encounters)")
        return
    for cls, cnt in enc_types.most_common():
        print(f"  {cls}: {cnt} ({100 * cnt / total:.1f}%)")
    print("  [real: MHLW 患者調査 2020 — 外来受療率 5,658 / 入院 960 = ~85% AMB]")


def audit_death(pts: list[dict], n: int) -> None:
    _section("8. Death rate")
    deceased = sum(1 for p in pts if p.get("deceasedDateTime") or p.get("deceasedBoolean"))
    print(f"  Deceased: {deceased}/{n} ({100 * deceased / n:.2f}%)")
    print("  [real: JP 粗死亡率 2020: 11.1/1,000/year ≈ 1.11%/year; 1-year snapshot ~1%]")


def audit_immunization(resources: dict, ages_by_pid: dict[str, int], sex_by_pid: dict[str, str]) -> None:
    _section("9. Immunization (per-season / per-lifetime, NOT cumulative ≥1)")
    print("  [Cumulative '≥1 record' comparison against per-season MHLW rate is WRONG.")
    print("   See modules/immunization/README.md 'Cumulative record vs per-season'.]")

    flu_shots_by_pt: collections.Counter = collections.Counter()
    covid_by_pt: set[str] = set()
    pneumo_by_pt: set[str] = set()
    for imm in resources.get("Immunization", []):
        pid = imm.get("patient", {}).get("reference", "").replace("Patient/", "")
        codings = imm.get("vaccineCode", {}).get("coding") or []
        cvx = None
        for coding in codings:
            if "cvx" in (coding.get("system", "") or "").lower():
                cvx = coding.get("code")
                break
        if cvx is None and codings:
            cvx = codings[0].get("code")
        if cvx == "150":
            flu_shots_by_pt[pid] += 1
        elif cvx == "309":
            covid_by_pt.add(pid)
        elif cvx == "33":
            pneumo_by_pt.add(pid)

    old_m = [pid for pid, a in ages_by_pid.items() if a >= 65 and sex_by_pid.get(pid) == "male"]
    old_f = [pid for pid, a in ages_by_pid.items() if a >= 65 and sex_by_pid.get(pid) == "female"]

    def _per_season_flu(patients: list[str], sex_label: str, target: float) -> None:
        if not patients:
            return
        total_shots = sum(flu_shots_by_pt[pid] for pid in patients)
        opportunities = len(patients) * FLU_HISTORY_YEARS
        rate = total_shots / opportunities
        _cmp(
            f"flu per-season {sex_label} 65+",
            rate,
            target,
            tol=0.05,
            source=f"MHLW ~{int(target * 100)}% (per-season, hist={FLU_HISTORY_YEARS}y)",
        )

    def _once_rate(patients: list[str], has_it: set[str], sex_label: str, vaccine: str, target: float) -> None:
        if not patients:
            return
        rate = sum(1 for pid in patients if pid in has_it) / len(patients)
        _cmp(
            f"{vaccine} lifetime {sex_label} 65+",
            rate,
            target,
            tol=0.05,
            source=f"config / MHLW target {target}",
        )

    _per_season_flu(old_m, "M", IMM_TARGETS_JP["flu_annual_65plus_M"])
    _per_season_flu(old_f, "F", IMM_TARGETS_JP["flu_annual_65plus_F"])
    _once_rate(old_m, covid_by_pt, "M", "COVID", IMM_TARGETS_JP["covid_once_65plus_M"])
    _once_rate(old_f, covid_by_pt, "F", "COVID", IMM_TARGETS_JP["covid_once_65plus_F"])
    _once_rate(old_m, pneumo_by_pt, "M", "PPSV23", IMM_TARGETS_JP["pneumo_once_65plus_M"])
    _once_rate(old_f, pneumo_by_pt, "F", "PPSV23", IMM_TARGETS_JP["pneumo_once_65plus_F"])


def audit_allergy(resources: dict, n: int) -> None:
    _section("10. Allergy prevalence")
    pts_with = {
        a.get("patient", {}).get("reference", "").replace("Patient/", "")
        for a in resources.get("AllergyIntolerance", [])
    }
    print(f"  Patients with ≥1 allergy: {len(pts_with)}/{n} ({100 * len(pts_with) / n:.1f}%)")
    print("  [real: JP アレルギー疾患実態調査 2011 — 何らかのアレルギー 30-40%; 薬物 5-10%]")


def audit_invariants(resources: dict, sex_by_pid: dict[str, str]) -> None:
    _section("11. Sex-restricted disease invariants")
    n40_female = 0
    for condition in resources.get("Condition", []):
        for coding in condition.get("code", {}).get("coding") or []:
            if coding.get("code", "").startswith("N40"):
                pid = condition.get("subject", {}).get("reference", "").replace("Patient/", "")
                if sex_by_pid.get(pid) == "female":
                    n40_female += 1
    mark = "✅" if n40_female == 0 else "❌"
    print(f"  {mark} N40 (BPH) in females: {n40_female}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__ and __doc__.split("\n")[0])
    ap.add_argument("fhir_dir", help="Directory containing FHIR ndjson files (e.g. <cohort>/jp/fhir_r4/)")
    ap.add_argument(
        "--snapshot-year",
        type=int,
        default=2026,
        help="Reference year for age calculation (default: 2026)",
    )
    args = ap.parse_args()

    if not os.path.isdir(args.fhir_dir):
        print(f"ERROR: {args.fhir_dir} is not a directory", file=sys.stderr)
        return 2

    resources = load_bundle(args.fhir_dir)
    pts = resources.get("Patient", [])
    n = len(pts)
    if not n:
        print(f"ERROR: no Patient.ndjson under {args.fhir_dir}", file=sys.stderr)
        return 2

    ages_by_pid = {p["id"]: args.snapshot_year - int(p["birthDate"][:4]) for p in pts if p.get("birthDate")}
    sex_by_pid = {p["id"]: p.get("gender") for p in pts}

    print(f"Loaded {n} patients from {args.fhir_dir} (snapshot year {args.snapshot_year})")
    audit_sex(pts, n)
    audit_age(n, ages_by_pid)
    audit_smoking_alcohol(resources, pts, ages_by_pid)
    audit_chronic(resources, pts, ages_by_pid)
    audit_encounters(resources)
    audit_death(pts, n)
    audit_immunization(resources, ages_by_pid, sex_by_pid)
    audit_allergy(resources, n)
    audit_invariants(resources, sex_by_pid)

    print(f"\n{'=' * 78}\nSUMMARY: ⚠️ = deviation >5%, ❌ = deviation >10%\n{'=' * 78}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
