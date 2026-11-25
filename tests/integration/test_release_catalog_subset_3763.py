"""A dataset's used-codes catalog is a subset of the release catalog (Issue #3763).

Every code a generated dataset uses must be a code the release can emit, for
the same country: the consumer prepares master tables from the release catalog
and must not meet a code in the data that is not in it. The two are compared on
``(resource, element, system, code, route)``: the kind of an Observation code
(lab, vital sign, nursing score, other) is a finer label than the release
reference data attributes everywhere, the element is not.
"""

from __future__ import annotations

import json

import pytest

from clinosim.modules.output.cif_writer import write_cif
from clinosim.modules.output.fhir_r4 import convert_cif_to_fhir
from clinosim.modules.output.fhir_r4.release_catalog import build_release_catalog
from clinosim.simulator import run_beta
from clinosim.types.config import SimulatorConfig

pytestmark = pytest.mark.integration


def _keys(lines) -> set[tuple]:
    return {(x["resource"], x["element"], x["system"], x["code"], x.get("route")) for x in lines}


@pytest.mark.parametrize("country", ["US", "JP"])
def test_used_codes_are_a_subset_of_the_release_catalog(tmp_path, country: str) -> None:
    config = SimulatorConfig(
        country=country, catchment_population=300, time_range=("2024-04-01", "2025-03-31"), random_seed=11
    )
    write_cif(run_beta(config), str(tmp_path / "cif"))
    convert_cif_to_fhir(str(tmp_path / "cif"), str(tmp_path / "fhir_r4"), country=country)
    with open(tmp_path / "catalog" / "codes-used.ndjson", encoding="utf-8") as f:
        used = [json.loads(line) for line in f if line.strip()]
    assert used
    missing = _keys(used) - _keys(build_release_catalog(country).lines())
    assert not missing, (
        f"codes in the dataset but not in the {country} release catalog: {sorted(map(str, missing))[:20]}"
    )
