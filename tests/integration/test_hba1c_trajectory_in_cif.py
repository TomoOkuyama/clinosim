"""CIF-layer HbA1c trajectory validation (Phase 1 Task 11 missing deliverable).

Builds the end-to-end proof that the longitudinal engine's AR(1)
latent reaches CIF per-encounter lab emit. Without this coverage the
engine builds trajectories in `PersonRecord.longitudinal_history` but
no caller reads them, collapsing every DM patient's HbA1c to a flat
value (the review-pass C1 regression).

See Phase 1 plan Task 11 brief + spec §9.2.
"""

from __future__ import annotations

import json
import tempfile
from collections import defaultdict
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def cif_dir() -> Path:
    """Generate one tiny p=100 US seed=42 2-year cohort and share across
    tests. 2-year span ensures DM patients have 2 YearSnapshots so
    between-year HbA1c variance is measurable."""
    import subprocess
    import sys

    tmp = tempfile.mkdtemp(prefix="longitudinal_cif_")
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
            "2025-12-31",
            "--format",
            "cif",
        ],
        check=True,
    )
    patients_dir = out / "cif" / "structural" / "patients"
    assert patients_dir.exists(), f"CIF generation produced no patients dir under {out}"
    return patients_dir


def _hba1c_values_per_dm_patient(cif_dir: Path) -> dict[str, list[float]]:
    """Group HbA1c lab values by patient_id across all encounter files."""
    out: dict[str, list[float]] = defaultdict(list)
    for f in sorted(cif_dir.glob("*.json")):
        d = json.loads(f.read_text())
        pat = d.get("patient") or {}
        pid = pat.get("patient_id", "")
        chronic = pat.get("chronic_conditions") or []
        is_dm = any((c.get("code") or "").startswith(("E11", "E10")) for c in chronic)
        if not is_dm:
            continue
        for lab in d.get("lab_results") or []:
            if (lab.get("lab_name") or "").lower() == "hba1c":
                out[pid].append(float(lab["value"]))
    return out


@pytest.mark.integration
def test_cif_dm_patients_hba1c_cohort_varies_across_patients(cif_dir: Path) -> None:
    """Cross-patient variance: a p=100 cohort's DM patients emit
    HbA1c values that span a range, not a single flat value. The
    pre-threading regression collapsed every DM patient to 9.0 — this
    test fails loudly on that case."""
    hba1c_by_pid = _hba1c_values_per_dm_patient(cif_dir)
    assert len(hba1c_by_pid) >= 5, f"too few DM patients to assess variance (n={len(hba1c_by_pid)})"
    all_values = [v for vals in hba1c_by_pid.values() for v in vals]
    assert all_values, "no HbA1c lab rows emitted on any DM patient"
    spread = max(all_values) - min(all_values)
    assert spread > 1.0, (
        f"DM-cohort HbA1c spread {spread:.2f} ≤ 1.0 % — the engine's "
        f"AR(1) latent is not reaching CIF; every patient landed near "
        f"the same value ({sorted(set(all_values))[:5]}). This is the "
        f"review-pass C1 regression."
    )


@pytest.mark.integration
def test_cif_dm_cohort_mean_hba1c_matches_mean_reversion_target(cif_dir: Path) -> None:
    """Cohort mean sits within 1.0 % of the yaml's mean_reversion_target
    (7.3 %) — a sanity check that the latent is wired in roughly the
    right register (not inverted, not scaled wrong)."""
    hba1c_by_pid = _hba1c_values_per_dm_patient(cif_dir)
    all_values = [v for vals in hba1c_by_pid.values() for v in vals]
    assert all_values
    mean = sum(all_values) / len(all_values)
    assert abs(mean - 7.3) < 1.0, (
        f"DM-cohort mean HbA1c {mean:.2f} is >1 % away from the "
        f"mean_reversion_target 7.3. Latent-reaching-CIF path probably "
        f"collapsed to a constant."
    )
