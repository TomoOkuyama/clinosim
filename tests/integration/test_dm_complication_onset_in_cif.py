"""CIF-layer DM complication onset validation (Phase 3 Task 6).

End-to-end proof that the event pattern reaches CIF: a p=100 US seed=42
5y cohort must show at least a handful of DM patients carrying one of
the Phase 3 complication codes (E11.21 nephropathy, E11.311 retinopathy,
E11.42 neuropathy) after the sim completes.

Analogous to Phase 1/2 cohort tests.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

import pytest

_DM_COMPLICATION_CODES = {"E11.21", "E11.311", "E11.42"}


@pytest.fixture(scope="module")
def cif_dir() -> Path:
    tmp = tempfile.mkdtemp(prefix="longitudinal_event_cif_")
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
            "2028-12-31",
            "--format",
            "cif",
        ],
        check=True,
    )
    patients_dir = out / "cif" / "structural" / "patients"
    assert patients_dir.exists(), f"CIF generation produced no patients dir under {out}"
    return patients_dir


def _complication_codes_per_patient(cif_dir: Path) -> dict[str, set[str]]:
    """Group DM complication ICDs by patient id across all encounter files."""
    out: dict[str, set[str]] = defaultdict(set)
    for f in sorted(cif_dir.glob("*.json")):
        d = json.loads(f.read_text())
        pat = d.get("patient") or {}
        pid = pat.get("patient_id", "")
        chronic = pat.get("chronic_conditions") or []
        is_dm = any((c.get("code") or "").startswith(("E11", "E10")) for c in chronic)
        if not is_dm:
            continue
        for c in chronic:
            code = c.get("code") or ""
            if code in _DM_COMPLICATION_CODES:
                out[pid].add(code)
    return out


@pytest.mark.integration
def test_cif_dm_cohort_shows_complication_onsets(cif_dir: Path) -> None:
    """A p=100 5y US DM cohort should have at least one patient carrying
    at least one of E11.21 / E11.311 / E11.42 — proof the event pattern
    reaches CIF. If zero patients have any complication, the event
    pattern never wrote through to person.chronic_conditions."""
    comps_by_pid = _complication_codes_per_patient(cif_dir)
    carriers = {pid: codes for pid, codes in comps_by_pid.items() if codes}
    assert len(carriers) >= 1, (
        f"no DM patient carries any complication from {_DM_COMPLICATION_CODES} — "
        f"event pattern not reaching CIF; checked {sum(1 for _ in cif_dir.glob('*.json'))} files"
    )
