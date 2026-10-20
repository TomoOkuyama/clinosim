"""CIF-layer Markov stage trajectory validation (Phase 2 Task 12).

Builds the end-to-end proof that the longitudinal engine's Markov
pattern reaches CIF per-encounter emit. Without this coverage the
engine builds stage trajectories in
``PersonRecord.longitudinal_history`` but no caller reads them,
leaving every CKD patient's `ChronicCondition.stage` empty or
frozen.

Analogous to Phase 1's test_hba1c_trajectory_in_cif.py.

See Phase 2 plan Task 12 brief + spec §9.2.
"""

from __future__ import annotations

import json
import tempfile
from collections import defaultdict
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def cif_dir() -> Path:
    """Generate one tiny p=100 US seed=42 3-year cohort and share across
    tests. 3 years lets CKD progression manifest across patients."""
    import subprocess
    import sys

    tmp = tempfile.mkdtemp(prefix="longitudinal_stage_cif_")
    out = Path(tmp)
    subprocess.run(
        [
            sys.executable,
            "-m",
            "clinosim.simulator.cli",
            "simulate",
            "-o",
            str(out),
            "--country",
            "US",
            "-p",
            "100",
            "-s",
            "42",
            "--start",
            "2024-01-01",
            "--end",
            "2026-12-31",
            "--format",
            "cif",
        ],
        check=True,
    )
    patients_dir = out / "cif" / "structural" / "patients"
    assert patients_dir.exists(), f"CIF generation produced no patients dir under {out}"
    return patients_dir


_CKD_STAGE_INDEX = {
    "CKD G1": 0,
    "CKD G2": 1,
    "CKD G3a": 2,
    "CKD G3b": 3,
    "CKD G4": 4,
    "CKD G5": 5,
}


def _ckd_stages_per_patient(cif_dir: Path) -> dict[str, list[str]]:
    """Group CKD stage strings seen on ChronicCondition entries by patient id."""
    out: dict[str, list[str]] = defaultdict(list)
    for f in sorted(cif_dir.glob("*.json")):
        d = json.loads(f.read_text())
        pat = d.get("patient") or {}
        pid = pat.get("patient_id", "")
        chronic = pat.get("chronic_conditions") or []
        for c in chronic:
            if (c.get("code") or "").startswith("N18"):
                stage = (c.get("stage") or "").strip()
                if stage and stage in _CKD_STAGE_INDEX:
                    out[pid].append(stage)
    return out


@pytest.mark.integration
def test_cif_ckd_cohort_stage_distribution_populated(cif_dir: Path) -> None:
    """Across a p=100 cohort, at least one CKD patient must carry a
    non-empty stage string on their ChronicCondition entries. Zero
    staged CKD patients means the Markov engine's chronic_stages
    never reached CIF (the Phase 2 analogue of the Phase 1 C1
    regression)."""
    stages_by_pid = _ckd_stages_per_patient(cif_dir)
    assert len(stages_by_pid) >= 1, (
        "no CKD patient emitted a stage string — Markov chronic_stages not reaching CIF via activator"
    )
    all_stages = [s for vals in stages_by_pid.values() for s in vals]
    assert all_stages, "no CKD stage rows emitted on any patient"
    # Confirm variety: not everyone pinned to the same stage (would
    # suggest initial_distribution never ran or stage got frozen).
    assert len(set(all_stages)) >= 2, (
        f"all CKD patients at the same stage {sorted(set(all_stages))!r} — "
        f"Markov initial_distribution + step not producing cohort variety"
    )


@pytest.mark.integration
def test_cif_ckd_stage_distribution_spans_multiple_bands(cif_dir: Path) -> None:
    """A p=100 CKD cohort's stage distribution should span at least 3
    of the 6 KDIGO bands. Below 3 suggests the initial_distribution
    did not sample properly."""
    stages_by_pid = _ckd_stages_per_patient(cif_dir)
    all_stages = {s for vals in stages_by_pid.values() for s in vals}
    assert len(all_stages) >= 3, (
        f"CKD cohort spans only {sorted(all_stages)!r} bands (<3); initial_distribution sampling may be truncated"
    )
