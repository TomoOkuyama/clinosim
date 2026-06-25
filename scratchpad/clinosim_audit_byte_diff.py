"""Byte-diff vs master to verify clinosim/audit/ doesn't touch simulation."""
from __future__ import annotations

import hashlib
from pathlib import Path

ROOT = Path(__file__).parent / "clinosim_audit_byte_diff"
MASTER = ROOT / "master"
BRANCH = ROOT / "branch"


def sha256_of(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def line_count(p: Path) -> int:
    return sum(1 for _ in p.open("rb"))


def report(country: str) -> None:
    print(f"\n## {country.upper()}")
    print("| NDJSON | master sha256 | branch sha256 | master lines | branch lines | verdict |")
    print("|---|---|---|---|---|---|")
    md = MASTER / country / "fhir_r4"
    bd = BRANCH / country / "fhir_r4"
    if not md.exists():
        return
    for path in sorted(md.glob("*.ndjson")):
        bp = bd / path.name
        if not bp.exists():
            continue
        m = sha256_of(path)
        b = sha256_of(bp)
        verdict = "IDENTICAL" if m == b else "DIFF"
        print(
            f"| {path.name} | {m[:12]}... | {b[:12]}... | "
            f"{line_count(path)} | {line_count(bp)} | {verdict} |"
        )


if __name__ == "__main__":
    for c in ("us", "jp"):
        report(c)
