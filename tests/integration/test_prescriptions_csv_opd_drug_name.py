"""Issue #450 guard: ``prescriptions.csv`` outpatient-renewal rows
(``-OPD`` prescription_id suffix) must populate ``drug_name``.

Pre-fix (session 73 measurement, seed=42 JP p=500, 2025-2026 window):
5296 / 5779 rows (91.6%) had empty ``drug_name`` because
``outpatient.py`` populated ``{"drug": med, "duration_days": 30}`` while
``csv_adapter.py`` read only ``item.get("drug_name")`` — key-name shape
mismatch (``drug`` vs ``drug_name``) without a fallback. 3 sibling
consumers (``simulator/helpers.py``, ``document/narrative/passes.py``,
``modules/output/hospital_course_extractor.py``) already had a fallback;
csv_adapter did not.

This PR unifies the outpatient item shape to
``{drug_name, dose, route, duration_days}`` (matches inpatient) AND
adds a fallback in csv_adapter so pre-migration serialized runs still
populate drug_name. The two are landed together because either alone
leaves either the historical or the forward-flow path silently dropping
drug_name.

Refs #450 / #445 / #442.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from clinosim.modules.output.cif_writer import write_cif
from clinosim.modules.output.csv_adapter import convert_cif_to_csv
from clinosim.simulator.engine import run_beta
from clinosim.types.config import SimulatorConfig


@pytest.mark.integration
def test_prescriptions_csv_opd_rows_populate_drug_name(tmp_path: Path):
    """Small deterministic cohort MUST have non-empty ``drug_name`` on
    every ``-OPD`` row.

    Chooses a seed and population known to produce prescription renewal
    outpatient visits within 1 year of simulation (chronic_followup +
    prescription_renewal encounter YAMLs declare ``prescriptions_renewed:
    true`` which fires when ``patient.current_medications`` is non-empty).
    """
    cfg = SimulatorConfig(
        random_seed=42,
        catchment_population=200,
        country="JP",
        time_range=("2025-01", "2026-01"),
    )
    ds = run_beta(cfg)
    assert ds.patients

    cif_dir = tmp_path / "cif"
    csv_dir = tmp_path / "csv"
    write_cif(ds, str(cif_dir))
    convert_cif_to_csv(str(cif_dir), str(csv_dir), country="JP")

    csv_path = csv_dir / "prescriptions.csv"
    assert csv_path.is_file(), f"prescriptions.csv not produced at {csv_path}"

    total_opd = 0
    empty_drug_name_opd = 0
    sample_bad: list[dict] = []
    with csv_path.open() as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            pid = row.get("prescription_id", "") or ""
            if not pid.endswith("-OPD"):
                continue
            total_opd += 1
            if not (row.get("drug_name") or "").strip():
                empty_drug_name_opd += 1
                if len(sample_bad) < 3:
                    sample_bad.append(row)

    assert total_opd > 0, (
        f"cohort produced no OPD rows in {csv_path} — test is vacuous. "
        f"Population or seed may be too small to trigger prescription renewals."
    )
    assert empty_drug_name_opd == 0, (
        f"{empty_drug_name_opd}/{total_opd} OPD rows have empty drug_name. "
        f"Regression to pre-#450 behavior. Sample bad rows: {sample_bad}"
    )
