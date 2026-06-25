"""Phase 3a byte-diff: master vs branch NDJSON comparison.

Expected (per spec §8 v3):
- Patient/Encounter/Condition/MedReq/MedAdmin/Procedure/Imaging/
  Immunization/FamilyMemberHistory/Device/DeviceUseStatement/Specimen/
  DiagnosticReport: byte-IDENTICAL (POST_ENCOUNTER migration preserves
  per-patient sub-seed determinism for device + hai sampling)
- Observation: same line count, WBC + CRP values shifted in HAI cohort rows
"""
from __future__ import annotations

import hashlib
from pathlib import Path

ROOT = Path(__file__).parent / "phase3a_byte_diff"
MASTER = ROOT / "master"
BRANCH = ROOT / "branch"


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def line_count(path: Path) -> int:
    return sum(1 for _ in path.open("rb"))


def report(country: str) -> None:
    print(f"\n## {country.upper()}\n")
    print(
        "| NDJSON | master sha256 | branch sha256 "
        "| master lines | branch lines | verdict |"
    )
    print("|---|---|---|---|---|---|")
    master_dir = MASTER / country / "fhir_r4"
    branch_dir = BRANCH / country / "fhir_r4"
    files = sorted({p.name for p in master_dir.glob("*.ndjson")} |
                   {p.name for p in branch_dir.glob("*.ndjson")})
    for name in files:
        m_path = master_dir / name
        b_path = branch_dir / name
        if not m_path.exists():
            print(f"| {name} | MISSING | — | 0 | "
                  f"{line_count(b_path) if b_path.exists() else 0} | NEW |")
            continue
        if not b_path.exists():
            print(f"| {name} | — | MISSING | {line_count(m_path)} | 0 | REMOVED |")
            continue
        m_hash = sha256_of(m_path)
        b_hash = sha256_of(b_path)
        m_lines = line_count(m_path)
        b_lines = line_count(b_path)
        if m_hash == b_hash:
            verdict = "IDENTICAL"
        elif m_lines == b_lines:
            verdict = "same-count shift"
        else:
            verdict = "count diff"
        print(
            f"| {name} | {m_hash[:12]}... | {b_hash[:12]}... "
            f"| {m_lines} | {b_lines} | {verdict} |"
        )


if __name__ == "__main__":
    for country in ("us", "jp"):
        report(country)
