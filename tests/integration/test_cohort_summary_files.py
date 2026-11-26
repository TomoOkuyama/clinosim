"""A small US and JP simulate writes ``summary/cohort-summary.json`` and the metadata counts patients."""

from __future__ import annotations

import glob
import json
import os

import pytest

from clinosim.modules.output.cif_writer import write_cif
from clinosim.modules.output.cohort_summary import write_cohort_summary
from clinosim.simulator import run_beta
from clinosim.types.config import SimulatorConfig

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("country", ["US", "JP"])
def test_simulate_writes_summary_and_patient_counts(tmp_path, country: str) -> None:
    config = SimulatorConfig(
        country=country, catchment_population=40, time_range=("2025-01-01", "2025-03-31"), random_seed=11
    )
    cif_dir = str(tmp_path / "cif")
    write_cif(run_beta(config), cif_dir)
    path = write_cohort_summary(cif_dir)

    assert path == str(tmp_path / "summary" / "cohort-summary.json")
    with open(os.path.join(cif_dir, "metadata.json"), encoding="utf-8") as f:
        meta = json.load(f)
    assert meta["cohort_summary"] == "summary/cohort-summary.json"
    assert "total_patients_generated" not in meta

    files = glob.glob(os.path.join(cif_dir, "structural", "patients", "*.json"))
    pids = set()
    for p in files:
        with open(p, encoding="utf-8") as f:
            pids.add(json.load(f)["patient"]["patient_id"])
    assert meta["total_records"] == len(files)
    assert meta["total_patients"] == len(pids)
    assert meta["total_patients"] <= meta["total_records"]

    with open(path, encoding="utf-8") as f:
        text = f.read()
    summary = json.loads(text)
    assert summary["country"] == country
    assert summary["patients"]["total"] == len(pids)
    assert sum(b["patients"] for b in summary["patients"]["by_age_band"]) == len(pids)
    assert sum(summary["patients"]["by_sex"].values()) == len(pids)
    assert summary["encounters"]["total"] == sum(summary["encounters"]["by_type"].values())
    assert summary["conditions"]["chronic"], "the cohort has chronic conditions"
    if country == "US":
        assert text.isascii()
    else:
        assert any(not c["display"].isascii() for c in summary["conditions"]["chronic"] if c["display"])
    # Deterministic: rewriting from the same CIF gives the same bytes.
    write_cohort_summary(cif_dir)
    with open(path, encoding="utf-8") as f:
        assert f.read() == text
