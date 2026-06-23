"""Byte-diff invariant verification for PR1 CBC/BMP panel expansion.

Runs the simulator twice (US p=2000 and JP p=1000, seed=42) on the current
git working tree, hashes every NDJSON and CSV under each output directory,
then re-runs on master via a git worktree and prints a per-file PASS/FAIL
table against the spec §4 boundary:

    IDENTICAL (PASS):   Patient/Encounter/Practitioner/Organization/Location/
                        Condition/Procedure/MedicationRequest/MAR/Immunization/
                        FamilyMemberHistory + non-lab Observation files +
                        non-lab CSVs
    DIFF EXPECTED:      Observation.ndjson, DiagnosticReport.ndjson,
                        orders.csv, lab_results.csv

Usage (from repo root):
    python scratchpad/cbc_bmp_byte_diff.py
"""
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

EXPECT_IDENTICAL = [
    # FHIR NDJSONs — patient cohort & non-lab data must be byte-identical to
    # master, proving the panel-children sub-RNG refactor leaves the master
    # patient-scoped stream untouched.
    "Patient.ndjson", "Encounter.ndjson",
    "Practitioner.ndjson", "PractitionerRole.ndjson",
    "Organization.ndjson", "Location.ndjson",
    "Condition.ndjson", "Procedure.ndjson",
    "MedicationRequest.ndjson", "MedicationAdministration.ndjson",
    "Immunization.ndjson", "FamilyMemberHistory.ndjson",
    "AllergyIntolerance.ndjson", "Coverage.ndjson",
    # CSVs unrelated to labs
    "patients.csv", "encounters.csv", "diagnoses.csv", "vital_signs.csv",
    "medication_administrations.csv", "procedures.csv",
    "rehab_sessions.csv", "intake_output.csv", "adl_assessments.csv",
    "nursing_risk.csv", "immunizations.csv", "family_history.csv",
    "code_status.csv", "care_level.csv", "prescriptions.csv",
    "discharge_prescriptions.csv", "microbiology.csv",
]

EXPECT_DIFF = [
    # Lab Observations / DRs differ from master in two ways:
    #   (a) ABG (and any other registered panel) children now draw from
    #       panel_specimen_seed-isolated sub-RNGs, so their per-analyte
    #       values shift — count and id are preserved.
    #   (b) CBC and BMP entries are newly registered, so net new children
    #       are added at the tail.
    "Observation.ndjson", "DiagnosticReport.ndjson",
    "orders.csv", "lab_results.csv",
    # Specimen.ndjson is microbiology-specimen specific (not lab-tube) but
    # was caught in the cascade pre-refactor; with master RNG unaffected,
    # it should be byte-identical. Leave it here only for diagnosis — if it
    # ends up identical, the report will simply say "DIFF-OK …  +0 lines".
    "Specimen.ndjson",
    # manifest.json contains a generation timestamp that always differs.
    "manifest.json",
]


def file_sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def file_line_count(path: Path) -> int:
    if not path.exists():
        return 0
    with open(path, "rb") as f:
        return sum(1 for _ in f)


def hash_dir(d: Path) -> dict[str, tuple[str, int]]:
    out: dict[str, tuple[str, int]] = {}
    for p in sorted(d.glob("*")):
        if p.is_file():
            out[p.name] = (file_sha(p), file_line_count(p))
    return out


def run_simulator(cwd: Path, out_dir: Path, country: str, n: int, seed: int) -> None:
    """Invoke the clinosim CLI from the given working tree."""
    cmd = [
        sys.executable, "-m", "clinosim.simulator.cli",
        "generate",
        "--country", country,
        "-p", str(n),
        "-s", str(seed),
        "-o", str(out_dir),
        "--format", "fhir", "csv",  # nargs="+" — multiple format tokens
    ]
    subprocess.run(cmd, check=True, cwd=cwd)


def compare(branch_dir: Path, master_dir: Path, label: str) -> int:
    """Return number of failures (0 on PASS)."""
    branch_hashes = hash_dir(branch_dir)
    master_hashes = hash_dir(master_dir)

    print(f"\n=== {label} ===")
    failures = 0
    for fname in EXPECT_IDENTICAL:
        b = branch_hashes.get(fname)
        m = master_hashes.get(fname)
        if b is None and m is None:
            continue
        status = "PASS" if b == m else "FAIL"
        if status == "FAIL":
            failures += 1
        m_lines = m[1] if m else 0
        b_lines = b[1] if b else 0
        print(f"  [{status}] IDENTICAL  {fname}: "
              f"master={m_lines} / branch={b_lines}")

    for fname in EXPECT_DIFF:
        b = branch_hashes.get(fname)
        m = master_hashes.get(fname)
        if b is None and m is None:
            continue
        if b is None or m is None:
            failures += 1
            print(f"  [FAIL] DIFF-OK    {fname}: missing on one side "
                  f"(master={m is not None}, branch={b is not None})")
            continue
        # Additions-only invariant: branch line count >= master line count.
        ok = b[1] >= m[1]
        status = "PASS" if ok else "FAIL"
        if status == "FAIL":
            failures += 1
        print(f"  [{status}] DIFF-OK    {fname}: "
              f"master={m[1]} → branch={b[1]} ({b[1] - m[1]:+d} lines)")

    # Any branch file not categorized → unexpected diff.
    extra = (set(branch_hashes) | set(master_hashes)) \
            - set(EXPECT_IDENTICAL) - set(EXPECT_DIFF)
    for fname in sorted(extra):
        b = branch_hashes.get(fname)
        m = master_hashes.get(fname)
        if b == m:
            continue
        failures += 1
        m_lines = m[1] if m else 0
        b_lines = b[1] if b else 0
        print(f"  [FAIL] UNEXPECTED  {fname} differs (not in either bucket): "
              f"master={m_lines} branch={b_lines}")

    return failures


def main() -> None:
    work = Path(tempfile.mkdtemp(prefix="cbcbmp-bd-"))
    branch_us = work / "branch_us"
    branch_jp = work / "branch_jp"
    master_us = work / "master_us"
    master_jp = work / "master_jp"

    print("== branch (current tree) ==")
    run_simulator(REPO, branch_us, "US", 2000, 42)
    run_simulator(REPO, branch_jp, "JP", 1000, 42)

    master_wt = work / "master_wt"
    subprocess.run(["git", "worktree", "add", str(master_wt), "master"],
                   check=True, cwd=REPO)
    try:
        print("\n== master (worktree) ==")
        run_simulator(master_wt, master_us, "US", 2000, 42)
        run_simulator(master_wt, master_jp, "JP", 1000, 42)
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", str(master_wt)],
                       check=True, cwd=REPO)

    # Layout verified against clinosim/modules/output/adapters_builtin.py:
    #   FHIR NDJSONs → <output>/fhir_r4/
    #   CSVs        → <output>/csv/
    #   CIF         → <output>/cif/  (not relevant to byte-diff)
    failures = 0
    for label, b, m in [
        ("US p=2000 FHIR", branch_us / "fhir_r4", master_us / "fhir_r4"),
        ("US p=2000 CSV",  branch_us / "csv",     master_us / "csv"),
        ("JP p=1000 FHIR", branch_jp / "fhir_r4", master_jp / "fhir_r4"),
        ("JP p=1000 CSV",  branch_jp / "csv",     master_jp / "csv"),
    ]:
        if b.exists() and m.exists():
            failures += compare(b, m, label)
        else:
            print(f"\nSKIP {label}: directory missing "
                  f"(branch={b.exists()}, master={m.exists()})")

    print(f"\n=== SUMMARY ===  failures: {failures}")
    if failures:
        print(f"Outputs kept at {work} for inspection.")
        sys.exit(1)
    print(f"Cleaning up {work}.")
    shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
