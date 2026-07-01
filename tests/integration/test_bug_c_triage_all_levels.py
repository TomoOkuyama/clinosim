"""AD-65 Bug C regression test: ED encounters must emit all 5 triage levels.

Root cause (Task 13 diagnostic): `clinosim/simulator/emergency.py` sampled
`severity` ("mild"/"moderate"/"severe") per ED encounter but never stored
it on the `Encounter` object. `clinosim/modules/triage/engine.py:
triage_enricher` read `_o(enc, "severity", "moderate")`, so every ED
encounter silently defaulted to "moderate". Because
`clinosim/modules/triage/reference_data/triage_protocols.yaml`'s
`severity_to_triage_distribution` only reaches triage level "1" via
severity="severe" and level "5" via severity="mild" (moderate spans only
levels 2-4), the entire production cohort emitted `triage_level` in
{2,3,4} — L1 and L5 were structurally unreachable.

Fix: `Encounter.severity: str = ""` field (`clinosim/types/encounter.py`)
+ `encounter.severity = severity` assignment in
`clinosim/simulator/emergency.py` right after severity is sampled.

This test generates a real US cohort end to end via the CLI, reads the
structural CIF, and asserts the triage_level distribution actually
contains all 5 levels above a floor ratio -- verifying the fix at the
full pipeline level, not just at the enricher-unit level (see the
companion zero-arg audit proof in `clinosim/modules/triage/audit.py`).
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest


@pytest.mark.integration
def test_triage_all_5_levels_present(tmp_path: Path) -> None:
    out = tmp_path / "us_bug_c"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "clinosim.simulator.cli",
            "generate",
            "-p",
            "800",
            "--country",
            "US",
            "-o",
            str(out),
            "--format",
            "cif",
        ],
        capture_output=True,
        text=True,
        timeout=900,
    )
    assert result.returncode == 0, result.stderr

    structural = out / "cif" / "structural" / "patients"
    assert structural.is_dir(), f"structural CIF directory missing: {structural}"

    tl_counts: Counter[str] = Counter()
    for fn in structural.iterdir():
        if fn.suffix != ".json":
            continue
        data = json.loads(fn.read_text())
        for enc in data.get("encounters", []) or []:
            if enc.get("encounter_type") != "emergency":
                continue
            triage_data = enc.get("triage_data") or {}
            level = str(triage_data.get("level", "") or "")
            if level:
                tl_counts[level] += 1

    total = sum(tl_counts.values())
    if total < 30:
        pytest.skip(f"too few ED encounters with triage_data ({total}) to assert distribution")

    for level in ("1", "2", "3", "4", "5"):
        ratio = tl_counts.get(level, 0) / total
        assert ratio > 0.005, (
            f"triage_level {level} ratio={ratio:.4f} <= 0.5% threshold "
            f"(counts={dict(tl_counts)}, total={total}) — Bug C regression "
            f"(severity not reaching triage_enricher)"
        )
