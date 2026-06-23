"""Byte-diff report for the Phase 2a (D-dimer + causes_vte + J5) PR.

Adapted from scratchpad/coag_panel_byte_diff.py (PR #80).

The Phase 2a PR makes two kinds of changes:
1. New D_dimer Observations across 7 disease cohorts that already order
   {test:"D_dimer"} (PE/DVT/sepsis/MI/cerebral_infarction/COPD/AF-RVR) —
   pre-PR these orders silently dropped.
2. J5 fix side-effect: ED-route MI patients now produce MI-grade
   Troponin / CK-MB via the now-wired causes_myocardial_injury flag
   at emergency.py:122. Existing Troponin/CK-MB Observations for those
   patients gain values from the MI-grade branch.

Expected byte-diff invariant:

  Patient.ndjson           IDENTICAL  (sha256 equal)
  Encounter.ndjson         IDENTICAL
  Condition.ndjson         IDENTICAL
  MedicationRequest.ndjson IDENTICAL
  MedicationAdministration.ndjson IDENTICAL
  Procedure.ndjson         IDENTICAL
  ImagingStudy.ndjson      IDENTICAL (or MISSING on both)
  Immunization.ndjson      IDENTICAL
  FamilyMemberHistory.ndjson IDENTICAL
  Observation.ndjson       CHANGES — new D-dimer + ED MI troponin uplift
  DiagnosticReport.ndjson  essentially unchanged (D-dimer is panel-external
                            to LOINC 24373-3 Coag panel)
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRATCH = Path(__file__).resolve().parent
MASTER_REF = "b6bc8eab"

EXPECTED_IDENTICAL = [
    "Patient.ndjson", "Encounter.ndjson", "Condition.ndjson",
    "MedicationRequest.ndjson", "MedicationAdministration.ndjson",
    "Procedure.ndjson", "ImagingStudy.ndjson", "Immunization.ndjson",
    "FamilyMemberHistory.ndjson",
]
EXPECTED_CHANGED = ["Observation.ndjson", "DiagnosticReport.ndjson"]
NEW_LOINC = {"48065-7": "D-dimer (US)"}
NEW_JLAC10 = {"2B140": "D-dimer (JP)"}
COAG_PANEL_LOINC = "24373-3"  # should NOT change (D-dimer is panel-external)


def sha256(path: Path) -> str:
    if not path.exists():
        return "MISSING"
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def count_lines(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(1 for _ in open(path))


def code_counts(path: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    if not path.exists():
        return counts
    with open(path) as f:
        for line in f:
            try:
                rec = json.loads(line)
            except Exception:
                continue
            codings = rec.get("code", {}).get("coding") or []
            for c in codings:
                code = c.get("code")
                if code:
                    counts[code] = counts.get(code, 0) + 1
    return counts


def troponin_distribution(path: Path) -> dict[str, int]:
    """Bin Troponin_I values by clinical bucket."""
    bins = {"<1": 0, "1-5": 0, "5-30": 0, ">30": 0}
    if not path.exists():
        return bins
    with open(path) as f:
        for line in f:
            try:
                rec = json.loads(line)
            except Exception:
                continue
            codings = rec.get("code", {}).get("coding") or []
            if not any(c.get("code") in ("10839-9", "5C094") for c in codings):
                continue
            v = rec.get("valueQuantity", {}).get("value")
            if v is None:
                continue
            if v < 1:
                bins["<1"] += 1
            elif v < 5:
                bins["1-5"] += 1
            elif v < 30:
                bins["5-30"] += 1
            else:
                bins[">30"] += 1
    return bins


def run_simulator(out_dir: Path, country: str, n: int = 2000, seed: int = 42) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        sys.executable, "-m", "clinosim.simulator.cli",
        "generate", "--country", country, "-p", str(n), "-s", str(seed),
        "-o", str(out_dir), "--format", "fhir",
    ], check=True, cwd=REPO)


def report_for_country(country: str, master_dir: Path, branch_dir: Path,
                       out_lines: list[str]) -> None:
    m_root = master_dir / "fhir_r4"
    b_root = branch_dir / "fhir_r4"
    out_lines.append(f"\n## {country} (p=2000 seed=42)\n")
    out_lines.append("### IDENTICAL invariant\n")
    out_lines.append("| File | master | branch | match |")
    out_lines.append("|------|--------|--------|-------|")
    all_ok = True
    for f in EXPECTED_IDENTICAL:
        ms = sha256(m_root / f)
        bs = sha256(b_root / f)
        ok = (ms == bs)
        if not ok:
            all_ok = False
        mark = "OK" if ok else "MISMATCH"
        out_lines.append(f"| `{f}` | `{ms}` | `{bs}` | {mark} |")
    out_lines.append(f"\nAll IDENTICAL files match: **{all_ok}**\n")

    out_lines.append("### CHANGED files (expected — D-dimer + J5 MI troponin)\n")
    out_lines.append("| File | master lines | branch lines | delta |")
    out_lines.append("|------|--------------|--------------|-------|")
    for f in EXPECTED_CHANGED:
        m_n = count_lines(m_root / f)
        b_n = count_lines(b_root / f)
        out_lines.append(f"| `{f}` | {m_n} | {b_n} | {b_n - m_n:+d} |")

    out_lines.append("\n### New D-dimer emission counts (Observation)\n")
    obs_master = code_counts(m_root / "Observation.ndjson")
    obs_branch = code_counts(b_root / "Observation.ndjson")
    code_set = NEW_LOINC if country == "US" else NEW_JLAC10
    out_lines.append("| code | analyte | master | branch | delta |")
    out_lines.append("|------|---------|--------|--------|-------|")
    for code, label in code_set.items():
        m = obs_master.get(code, 0)
        b = obs_branch.get(code, 0)
        out_lines.append(f"| `{code}` | {label} | {m} | {b} | {b - m:+d} |")

    out_lines.append("\n### J5 evidence — Troponin_I distribution shift in ED MI patients\n")
    out_lines.append("Pre-J5: ED-presentation MI patients hit only the type-2 branch "
                     "(troponin ~0.5 ng/mL). Post-J5: a subset reaches MI-grade (>5 or >30).\n")
    m_bins = troponin_distribution(m_root / "Observation.ndjson")
    b_bins = troponin_distribution(b_root / "Observation.ndjson")
    out_lines.append("| bucket (ng/mL) | master count | branch count | delta |")
    out_lines.append("|----------------|--------------|--------------|-------|")
    for bucket in ("<1", "1-5", "5-30", ">30"):
        m = m_bins.get(bucket, 0)
        b = b_bins.get(bucket, 0)
        out_lines.append(f"| {bucket} | {m} | {b} | {b - m:+d} |")

    out_lines.append("\n### Coag DR (24373-3) — should NOT change (D-dimer is panel-external)\n")
    dr_master = code_counts(m_root / "DiagnosticReport.ndjson")
    dr_branch = code_counts(b_root / "DiagnosticReport.ndjson")
    m = dr_master.get(COAG_PANEL_LOINC, 0)
    b = dr_branch.get(COAG_PANEL_LOINC, 0)
    out_lines.append(f"| `{COAG_PANEL_LOINC}` (Coag panel) | master={m} | branch={b} | delta={b-m:+d} |\n")


def main() -> int:
    r = subprocess.run(["git", "status", "--porcelain"], cwd=REPO,
                       capture_output=True, text=True, check=True)
    if r.stdout.strip():
        lines = [ln for ln in r.stdout.splitlines() if not ln.startswith("??")]
        if lines:
            print("Uncommitted changes present; aborting:", file=sys.stderr)
            print(r.stdout, file=sys.stderr)
            return 2

    current = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"],
                             cwd=REPO, capture_output=True, text=True, check=True
                             ).stdout.strip()
    print(f"Current branch: {current}")

    SCRATCH.mkdir(exist_ok=True)
    master_root = SCRATCH / "phase2a_byte_diff_master"
    branch_root = SCRATCH / "phase2a_byte_diff_branch"

    try:
        print(f"\n=== Generating master @ {MASTER_REF} ===")
        subprocess.run(["git", "checkout", MASTER_REF], cwd=REPO, check=True)
        for country in ("US", "JP"):
            out = master_root / country.lower()
            if not (out / "fhir_r4" / "Patient.ndjson").exists():
                run_simulator(out, country=country)
            else:
                print(f"  {country} master output cached at {out}")

        print(f"\n=== Generating branch @ {current} ===")
        subprocess.run(["git", "checkout", current], cwd=REPO, check=True)
        for country in ("US", "JP"):
            out = branch_root / country.lower()
            if not (out / "fhir_r4" / "Patient.ndjson").exists():
                run_simulator(out, country=country)
            else:
                print(f"  {country} branch output cached at {out}")
    finally:
        cur = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"],
                             cwd=REPO, capture_output=True, text=True
                             ).stdout.strip()
        if cur != current:
            subprocess.run(["git", "checkout", current], cwd=REPO, check=True)

    out_lines: list[str] = []
    out_lines.append("# Phase 2a — Byte-Diff Report (D-dimer + causes_vte + J5)\n")
    out_lines.append(f"- master ref: `{MASTER_REF}`")
    out_lines.append(f"- branch: `{current}` HEAD")
    out_lines.append(f"- p=2000, seed=42, both countries (US, JP)")
    for country in ("US", "JP"):
        report_for_country(country, master_root / country.lower(),
                           branch_root / country.lower(), out_lines)

    results_path = SCRATCH / "phase2a_byte_diff_results.md"
    results_path.write_text("\n".join(out_lines))
    print(f"\n=== Report written to {results_path} ===")
    print("\n".join(out_lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
