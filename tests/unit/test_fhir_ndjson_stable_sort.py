"""F2 core invariant: 各 NDJSON file の resource が id 昇順で emit される。

行 diff friendly 化のため。行順序が cursor 依存(patient_records の iteration 順)だと
2 snapshot の diff で spurious "line moved" が出る。id sort 済であれば diff は
純粋な "new resource" / "changed content" だけを surface する。
"""

from __future__ import annotations

import json

import pytest

from clinosim.modules.output.cif_writer import write_cif
from clinosim.modules.output.fhir_r4_adapter import convert_cif_to_fhir
from clinosim.simulator.engine import run_beta
from clinosim.types.config import SimulatorConfig


@pytest.mark.unit
def test_ndjson_files_id_sorted(tmp_path):
    """F2 core: 各 NDJSON が id 昇順で emit される。"""
    config = SimulatorConfig(
        random_seed=42,
        catchment_population=30,
        country="US",
        time_range=("2026-01-01", "2026-03-31"),
    )
    ds = run_beta(config)
    cif_dir = tmp_path / "cif"
    fhir_dir = tmp_path / "fhir"
    write_cif(ds, str(cif_dir))
    convert_cif_to_fhir(str(cif_dir), str(fhir_dir), country="US")

    ndjson_files = list(fhir_dir.glob("*.ndjson"))
    assert ndjson_files, "no NDJSON emitted"
    for ndjson_file in ndjson_files:
        lines = [line for line in ndjson_file.read_text().splitlines() if line.strip()]
        ids = [json.loads(line).get("id", "") for line in lines]
        assert ids == sorted(ids), (
            f"{ndjson_file.name} not id-sorted:\n  actual: {ids[:5]}...\n  sorted: {sorted(ids)[:5]}..."
        )
