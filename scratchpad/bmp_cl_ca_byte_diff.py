"""Byte-diff report for the BMP Cl/Ca physiology PR (post Pass 1 sub-RNG fix).

The Pass 1 master-RNG-cascade fix (individual_lab_seed) is a structural
change: by design it shifts the master stream draw count and therefore
shifts patient cohorts off pre-PR master. master-vs-branch byte equality
is *not* the invariant after this PR. The real invariants are:

  1. SAME seed twice on the same code produces byte-identical output —
     covered by tests/integration/test_individual_lab_isolation.py.
  2. Adding/removing an individual lab order in a disease YAML cannot
     shift unrelated patients' cohorts via the master stream — the
     guarantee that individual_lab_seed provides (the integration test
     above asserts this at the structural level by way of Cl reaching
     RESULTED).

This script generates US/JP at p=2000 seed=42 from (a) master HEAD and
(b) the current feature branch and reports the actual cohort drift +
new Cl/Ca emission counts as PR evidence. It is NOT a pass/fail gate.
"""
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def run_simulator(cwd: Path, out_dir: Path, country: str, n: int, seed: int = 42) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run([
        sys.executable, "-m", "clinosim.simulator.cli",
        "generate", "--country", country, "-p", str(n), "-s", str(seed),
        "-o", str(out_dir), "--format", "fhir", "csv",
    ], check=True, cwd=cwd)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def patient_count(ndjson: Path) -> int:
    return sum(1 for _ in open(ndjson))


def observation_count_by_loinc(ndjson: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    with open(ndjson) as f:
        for line in f:
            o = json.loads(line)
            if not o.get("id", "").startswith("lab-"):
                continue
            code = (o.get("code", {}).get("coding") or [{}])[0].get("code", "")
            counts[code] = counts.get(code, 0) + 1
    return counts


def report(master: Path, branch: Path, country: str) -> None:
    print(f"\n### {country} ###")

    m_pat = master / "fhir_r4" / "Patient.ndjson"
    b_pat = branch / "fhir_r4" / "Patient.ndjson"
    print(f"Patient count: master={patient_count(m_pat)}  branch={patient_count(b_pat)}")

    m_obs = master / "fhir_r4" / "Observation.ndjson"
    b_obs = branch / "fhir_r4" / "Observation.ndjson"
    print(f"Observation total: master={patient_count(m_obs)}  branch={patient_count(b_obs)}")

    new_codes = {"2075-0": "Cl(US)", "17861-6": "Ca(US)", "3H020": "Cl(JP)", "3H030": "Ca(JP)"}
    m_counts = observation_count_by_loinc(m_obs)
    b_counts = observation_count_by_loinc(b_obs)
    print(f"\nNew Cl/Ca emissions on branch:")
    for code, label in new_codes.items():
        print(f"  {label} ({code}): master={m_counts.get(code, 0)}  branch={b_counts.get(code, 0)}")


def main() -> None:
    work = Path(tempfile.mkdtemp(prefix="bmp-cl-ca-byte-diff-"))
    master_dir = work / "master"
    branch_dir = work / "branch"

    master_repo = work / "master-repo"
    subprocess.run(["git", "worktree", "add", str(master_repo), "master"],
                   check=True, cwd=REPO)
    try:
        for country, n in [("US", 2000), ("JP", 2000)]:
            print(f"\n=== Generating master {country} p={n} (seed=42) ===")
            run_simulator(master_repo, master_dir / country, country, n)
            print(f"=== Generating branch {country} p={n} (seed=42) ===")
            run_simulator(REPO, branch_dir / country, country, n)
        for country in ("US", "JP"):
            report(master_dir / country, branch_dir / country, country)
        print(f"\nWorkspaces kept at {work} for inspection.")
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", str(master_repo)],
                       check=False, cwd=REPO)


if __name__ == "__main__":
    main()
