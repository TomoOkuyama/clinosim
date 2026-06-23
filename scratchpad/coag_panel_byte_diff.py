"""Byte-diff report for the Coag panel physiology PR.

Unlike the BMP Cl/Ca PR (PR #78), this PR makes NO structural change to the
master RNG stream — APTT/PT/Fibrinogen derives are pure additions in
derive_lab_values that route through the already-established AD-59 sub-RNGs
(panel_specimen_seed, individual_lab_seed). The AD-59 invariant ("adding a
new analyte must not shift unrelated patients") was structurally enforced
already by PR #78.

Therefore the expected byte-diff invariant on this PR is:

  Patient.ndjson           IDENTICAL  (sha256 equal between master and branch)
  Encounter.ndjson         IDENTICAL
  Condition.ndjson         IDENTICAL
  MedicationRequest.ndjson IDENTICAL
  MedicationAdministration.ndjson IDENTICAL
  Procedure.ndjson         IDENTICAL
  ImagingStudy.ndjson      IDENTICAL
  Immunization.ndjson      IDENTICAL
  FamilyMemberHistory.ndjson IDENTICAL
  Observation.ndjson       CHANGES — new APTT (14979-9), PT (5902-2),
                                     Fibrinogen (3255-7) Observations
                                     [JP: 2B020, 2B030 PT-with-seconds, 2B100]
  DiagnosticReport.ndjson  CHANGES — new Coag DRs (LOINC 24373-3) and the
                                     existing DR result[] references may
                                     include the new Observation ids.

This script runs the simulator on master fbd80607 and on the current
branch (HEAD), records sha256 of each NDJSON, and reports which files
changed. Any divergence on the "IDENTICAL" set is a defect to investigate
(AD-59 violation).

The 2000-patient, seed=42 footprint matches PR #74/#78's byte-diff scratch.
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRATCH = Path(__file__).resolve().parent
MASTER_REF = "fbd80607"

EXPECTED_IDENTICAL = [
    "Patient.ndjson", "Encounter.ndjson", "Condition.ndjson",
    "MedicationRequest.ndjson", "MedicationAdministration.ndjson",
    "Procedure.ndjson", "ImagingStudy.ndjson", "Immunization.ndjson",
    "FamilyMemberHistory.ndjson",
]
EXPECTED_CHANGED = ["Observation.ndjson", "DiagnosticReport.ndjson"]
NEW_LOINC = {
    "14979-9": "APTT (US)",
    "5902-2": "PT (US, seconds)",
    "3255-7": "Fibrinogen (US)",
}
NEW_JLAC10 = {
    "2B020": "APTT (JP)",
    "2B030": "PT/PT_INR (JP) — analyte shared, count goes up",
    "2B100": "Fibrinogen (JP)",
}
COAG_PANEL_LOINC = "24373-3"


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
    out_lines.append("")
    out_lines.append(f"All IDENTICAL files match: **{all_ok}**\n")

    out_lines.append("### CHANGED files (expected — new APTT/PT/Fibrinogen + Coag DRs)\n")
    out_lines.append("| File | master lines | branch lines | delta |")
    out_lines.append("|------|--------------|--------------|-------|")
    for f in EXPECTED_CHANGED:
        m_n = count_lines(m_root / f)
        b_n = count_lines(b_root / f)
        out_lines.append(f"| `{f}` | {m_n} | {b_n} | {b_n - m_n:+d} |")
    out_lines.append("")

    out_lines.append("### New analyte emission counts (Observation)\n")
    obs_master = code_counts(m_root / "Observation.ndjson")
    obs_branch = code_counts(b_root / "Observation.ndjson")
    code_set = NEW_LOINC if country == "US" else NEW_JLAC10
    out_lines.append("| code | analyte | master | branch | delta |")
    out_lines.append("|------|---------|--------|--------|-------|")
    for code, label in code_set.items():
        m = obs_master.get(code, 0)
        b = obs_branch.get(code, 0)
        out_lines.append(f"| `{code}` | {label} | {m} | {b} | {b - m:+d} |")
    out_lines.append("")

    out_lines.append("### Coag DR emission count (DiagnosticReport, LOINC 24373-3)\n")
    dr_master = code_counts(m_root / "DiagnosticReport.ndjson")
    dr_branch = code_counts(b_root / "DiagnosticReport.ndjson")
    m = dr_master.get(COAG_PANEL_LOINC, 0)
    b = dr_branch.get(COAG_PANEL_LOINC, 0)
    out_lines.append(f"| `{COAG_PANEL_LOINC}` (Coag panel) | master={m} | branch={b} | delta={b-m:+d} |")
    out_lines.append("")


def main() -> int:
    # Check no uncommitted changes
    r = subprocess.run(["git", "status", "--porcelain"], cwd=REPO,
                       capture_output=True, text=True, check=True)
    if r.stdout.strip():
        # Allow untracked files only; refuse if anything is staged or modified
        lines = [ln for ln in r.stdout.splitlines()
                 if not ln.startswith("??")]
        if lines:
            print("Uncommitted changes present; aborting:", file=sys.stderr)
            print(r.stdout, file=sys.stderr)
            return 2

    # Remember current branch
    current = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"],
                             cwd=REPO, capture_output=True, text=True, check=True
                             ).stdout.strip()
    print(f"Current branch: {current}")

    SCRATCH.mkdir(exist_ok=True)
    master_root = SCRATCH / "coag_byte_diff_master"
    branch_root = SCRATCH / "coag_byte_diff_branch"

    try:
        # Generate from master fbd80607
        print(f"\n=== Generating master @ {MASTER_REF} ===")
        subprocess.run(["git", "checkout", MASTER_REF], cwd=REPO, check=True)
        for country in ("US", "JP"):
            out = master_root / country.lower()
            if not (out / "fhir_r4" / "Patient.ndjson").exists():
                run_simulator(out, country=country)
            else:
                print(f"  {country} master output cached at {out}")

        # Generate from branch HEAD
        print(f"\n=== Generating branch @ {current} ===")
        subprocess.run(["git", "checkout", current], cwd=REPO, check=True)
        for country in ("US", "JP"):
            out = branch_root / country.lower()
            if not (out / "fhir_r4" / "Patient.ndjson").exists():
                run_simulator(out, country=country)
            else:
                print(f"  {country} branch output cached at {out}")

    finally:
        # Always restore branch on exit
        cur = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"],
                             cwd=REPO, capture_output=True, text=True
                             ).stdout.strip()
        if cur != current:
            subprocess.run(["git", "checkout", current], cwd=REPO, check=True)

    # Report
    out_lines: list[str] = []
    out_lines.append(f"# Coag Panel PR — Byte-Diff Report\n")
    out_lines.append(f"- master ref: `{MASTER_REF}`")
    out_lines.append(f"- branch: `{current}` HEAD")
    out_lines.append(f"- p=2000, seed=42, both countries (US, JP)")
    for country in ("US", "JP"):
        report_for_country(country, master_root / country.lower(),
                           branch_root / country.lower(), out_lines)

    results_path = SCRATCH / "coag_panel_byte_diff_results.md"
    results_path.write_text("\n".join(out_lines))
    print(f"\n=== Report written to {results_path} ===")
    print("\n".join(out_lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
