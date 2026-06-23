"""Clinical coherence audit for BMP Cl/Ca physiology PR.

Generates US p=4000 + JP p=2000 at seed=42 and walks
Observation.ndjson + Condition.ndjson + Encounter.ndjson, grouping
Cl/Ca/AG values per ground-truth disease cohort. Output: median +
p10/p90 per disease.

Expected ranges (per spec §9.4):
  DKA:      Cl 100-105, Ca 9.0-9.4, AG 20-30
  Sepsis:   Cl 100-104, Ca 8.5-9.0, AG 15-20
  Diarrhea: Cl 108-115, Ca 9.0-9.5, AG 6-10
  CKD/AKI:  Cl 100-105, Ca 8.8-9.2, AG 12-18
  Healthy:  Cl 99-106,  Ca 9.0-10.0, AG 8-14
"""
import collections
import json
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

US_CODES = {"Na": "2951-2", "K": "2823-3", "Cl": "2075-0",
            "HCO3": "1963-8", "Ca": "17861-6"}
JP_CODES = {"Na": "3H010", "K": "3H015", "Cl": "3H020",
            "HCO3": "3G125", "Ca": "3H030"}

COHORTS = {
    "DKA":            ["E10.1", "E11.1", "E13.1"],
    "Sepsis":         ["A41"],
    "AKI":            ["N17"],
    "CKD":            ["N18"],
    "GE/diarrhea":    ["A09", "K52.9"],
    "Pneumonia":      ["J15", "J18"],
    "GI_bleed":       ["K92.2", "K92.0", "K92.1"],
    "MI":             ["I21"],
    "Healthy":        ["Z00"],
}


def run_simulator(cwd: Path, out_dir: Path, country: str, n: int, seed: int = 42) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        sys.executable, "-m", "clinosim.simulator.cli",
        "generate", "--country", country, "-p", str(n), "-s", str(seed),
        "-o", str(out_dir), "--format", "fhir",
    ], check=True, cwd=cwd)


def patient_diagnoses(fhir_dir: Path) -> dict[str, set[str]]:
    out: dict[str, set[str]] = collections.defaultdict(set)
    with open(fhir_dir / "Condition.ndjson") as f:
        for line in f:
            c = json.loads(line)
            pid = (c.get("subject") or {}).get("reference", "").split("/")[-1]
            for coding in (c.get("code", {}).get("coding") or []):
                if coding.get("code"):
                    out[pid].add(coding["code"])
    return out


def encounter_to_patient(fhir_dir: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    with open(fhir_dir / "Encounter.ndjson") as f:
        for line in f:
            e = json.loads(line)
            eid = e.get("id")
            pid = (e.get("subject") or {}).get("reference", "").split("/")[-1]
            if eid and pid:
                out[eid] = pid
    return out


def lab_values(fhir_dir: Path, codes: dict[str, str]) -> list[tuple[str, str, str, float]]:
    code_to_analyte = {v: k for k, v in codes.items()}
    enc_pat = encounter_to_patient(fhir_dir)
    out: list[tuple[str, str, str, float]] = []
    with open(fhir_dir / "Observation.ndjson") as f:
        for line in f:
            o = json.loads(line)
            if not o.get("id", "").startswith("lab-"):
                continue
            loinc = ((o.get("code", {}).get("coding") or [{}])[0]).get("code", "")
            analyte = code_to_analyte.get(loinc)
            if not analyte:
                continue
            v = (o.get("valueQuantity") or {}).get("value")
            if v is None:
                continue
            enc = (o.get("encounter") or {}).get("reference", "").split("/")[-1]
            pid = enc_pat.get(enc, "")
            if pid:
                out.append((pid, enc, analyte, float(v)))
    return out


def quantile(xs: list[float], p: float) -> float:
    if not xs:
        return 0.0
    xs_sorted = sorted(xs)
    k = max(0, min(len(xs_sorted) - 1, int(len(xs_sorted) * p)))
    return xs_sorted[k]


def report(fhir_dir: Path, codes: dict[str, str], label: str) -> None:
    diags = patient_diagnoses(fhir_dir)
    labs = lab_values(fhir_dir, codes)

    enc_values: dict[str, dict[str, float]] = collections.defaultdict(dict)
    enc_pat: dict[str, str] = {}
    for pid, enc, analyte, v in labs:
        enc_values[enc][analyte] = v
        enc_pat[enc] = pid

    cohort_vals: dict[str, dict[str, list[float]]] = collections.defaultdict(
        lambda: {"Cl": [], "Ca": [], "AG": []}
    )
    for enc, vals in enc_values.items():
        pid = enc_pat.get(enc, "")
        if not pid:
            continue
        pat_codes = diags.get(pid, set())
        for cohort, prefixes in COHORTS.items():
            if any(any(c.startswith(p) for c in pat_codes) for p in prefixes):
                if "Cl" in vals:
                    cohort_vals[cohort]["Cl"].append(vals["Cl"])
                if "Ca" in vals:
                    cohort_vals[cohort]["Ca"].append(vals["Ca"])
                if all(k in vals for k in ("Na", "Cl", "HCO3")):
                    ag = vals["Na"] - vals["Cl"] - vals["HCO3"]
                    cohort_vals[cohort]["AG"].append(ag)

    print(f"\n##### {label} #####")
    hdr = f"{'cohort':<14} {'nCl':>5} {'nAG':>5}   "
    hdr += f"{'Cl(p10/p50/p90)':<22}{'Ca(p10/p50/p90)':<22}{'AG(p10/p50/p90)':<22}"
    print(hdr)
    print("-" * len(hdr))
    for cohort in COHORTS:
        cl = cohort_vals[cohort]["Cl"]
        ca = cohort_vals[cohort]["Ca"]
        ag = cohort_vals[cohort]["AG"]
        ncl, nag = len(cl), len(ag)
        if ncl == 0:
            print(f"{cohort:<14} {ncl:>5} {nag:>5}   (no Cl observations)")
            continue
        cl_str = f"{quantile(cl,0.10):5.1f}/{statistics.median(cl):5.1f}/{quantile(cl,0.90):5.1f}"
        ca_str = f"{quantile(ca,0.10):5.2f}/{statistics.median(ca):5.2f}/{quantile(ca,0.90):5.2f}" if ca else "(no Ca)"
        ag_str = f"{quantile(ag,0.10):5.1f}/{statistics.median(ag):5.1f}/{quantile(ag,0.90):5.1f}" if ag else "(no AG triple)"
        print(f"{cohort:<14} {ncl:>5} {nag:>5}   {cl_str:<22}{ca_str:<22}{ag_str:<22}")


def main() -> None:
    work = Path(tempfile.mkdtemp(prefix="bmp-cl-ca-audit-"))
    print("Generating US p=4000 + JP p=2000 (seed=42)...")
    us = work / "us"; jp = work / "jp"
    run_simulator(REPO, us, "US", 4000)
    run_simulator(REPO, jp, "JP", 2000)
    report(us / "fhir_r4", US_CODES, "US")
    report(jp / "fhir_r4", JP_CODES, "JP")
    print(f"\nOutputs kept at {work} for inspection.")


if __name__ == "__main__":
    main()
