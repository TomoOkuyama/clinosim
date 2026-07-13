#!/usr/bin/env python3
"""Diagnose Bug C: identify whether triage L1/L5 absence is caused by
upstream severity collapse or YAML distribution narrowness."""
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path


def run_cohort(country: str, tmp: Path) -> Path:
    out = tmp / f"{country.lower()}_diag"
    r = subprocess.run(
        [sys.executable, "-m", "clinosim.simulator.cli", "simulate",
         "-p", "500", "--country", country, "-o", str(out),
         "--format", "cif"],
        capture_output=True, text=True, timeout=900,
    )
    assert r.returncode == 0, r.stderr
    return out


def analyze(cif_dir: Path):
    structural = cif_dir / "cif" / "structural" / "patients"
    triage_levels = Counter()
    ed_count = 0
    for fn in structural.iterdir():
        if not fn.suffix == ".json":
            continue
        d = json.loads(fn.read_text())
        for enc in d.get("encounters", []) or []:
            etype = enc.get("encounter_type", "")
            if etype != "emergency":
                continue
            ed_count += 1
            # Triage level is in triage_data.level
            triage_data = enc.get("triage_data", {})
            tl = triage_data.get("level", "unknown")
            triage_levels[tl] += 1
    print(f"  ED encounters: {ed_count}")
    print(f"  Triage level distribution: {dict(triage_levels)}")
    # Convert to percentages
    if ed_count > 0:
        pcts = {k: f"{100*v/ed_count:.1f}%" for k, v in sorted(triage_levels.items())}
        print(f"  Triage level percentages: {pcts}")


def main():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        for country in ("US", "JP"):
            print(f"=== {country} ===")
            cif = run_cohort(country, tmp_path)
            analyze(cif)


if __name__ == "__main__":
    main()
