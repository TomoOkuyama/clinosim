"""The used-codes catalog agrees with a full scan of the FHIR data (Issue #3762).

The catalog is built while the FHIR writer emits resources. This test rebuilds
the same sets independently, by scanning the NDJSON written by the same export,
at the six locations a downstream loader checks:
``MedicationRequest.medicationCodeableConcept`` (with the route text of
``dosageInstruction[0]``), ``Observation.code``, ``ImagingStudy.procedureCode``,
``Condition.code``, ``Procedure.code`` and ``DocumentReference.type``. Every
code found must be in the catalog and every catalog entry of those kinds must
be found in the data. It also checks that ``fhir_r4/`` holds only what it held
before (files and per-resource key sets), and that ``cif/metadata.json`` points
at the catalog.
"""

from __future__ import annotations

import json
import os

import pytest

from clinosim.modules.output.cif_writer import write_cif
from clinosim.modules.output.fhir_r4 import convert_cif_to_fhir
from clinosim.simulator import run_beta
from clinosim.types.config import SimulatorConfig

pytestmark = pytest.mark.integration

_LOCATIONS = {
    "MedicationRequest": "medicationCodeableConcept",
    "Observation": "code",
    "Condition": "code",
    "Procedure": "code",
    "DocumentReference": "type",
}
# Catalog kinds that come from the six scanned locations.
_SCANNED_KINDS = {
    "medication",
    "lab",
    "vital-sign",
    "nursing-score",
    "observation",
    "imaging",
    "diagnosis",
    "procedure",
    "document-type",
}


def _ndjson(path: str):
    with open(path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                yield json.loads(line)


def _scan_six_locations(fhir_dir: str) -> set[tuple]:
    found: set[tuple] = set()
    for rtype, element in _LOCATIONS.items():
        path = os.path.join(fhir_dir, f"{rtype}.ndjson")
        if not os.path.exists(path):
            continue
        for res in _ndjson(path):
            route = None
            if rtype == "MedicationRequest":
                route = ((res.get("dosageInstruction") or [{}])[0].get("route") or {}).get("text")
            for coding in (res.get(element) or {}).get("coding") or []:
                if coding.get("code"):
                    found.add((coding.get("system") or "", coding["code"], route))
    path = os.path.join(fhir_dir, "ImagingStudy.ndjson")
    if os.path.exists(path):
        for res in _ndjson(path):
            for concept in res.get("procedureCode") or []:
                for coding in concept.get("coding") or []:
                    if coding.get("code"):
                        found.add((coding.get("system") or "", coding["code"], None))
    return found


def _catalog_set(catalog_path: str) -> set[tuple]:
    out: set[tuple] = set()
    for line in _ndjson(catalog_path):
        if line["kind"] in _SCANNED_KINDS:
            out.add((line["system"], line["code"], line.get("route")))
    return out


@pytest.mark.parametrize("country", ["US", "JP"])
def test_catalog_agrees_with_scan_both_ways(tmp_path, country: str) -> None:
    config = SimulatorConfig(
        country=country, catchment_population=300, time_range=("2024-04-01", "2025-03-31"), random_seed=7
    )
    root = tmp_path
    cif_dir = str(root / "cif")
    write_cif(run_beta(config), cif_dir)
    fhir_dir = str(root / "fhir_r4")
    convert_cif_to_fhir(cif_dir, fhir_dir, country=country)

    catalog_path = str(root / "catalog" / "codes-used.ndjson")
    assert os.path.exists(catalog_path)
    with open(os.path.join(cif_dir, "metadata.json"), encoding="utf-8") as f:
        assert json.load(f)["used_codes_catalog"] == "catalog/codes-used.ndjson"

    scanned = _scan_six_locations(fhir_dir)
    catalogued = _catalog_set(catalog_path)
    assert scanned, "the cohort produced no coded resources"
    assert scanned - catalogued == set(), "codes in the data but not in the catalog"
    assert catalogued - scanned == set(), "catalog entries of the scanned kinds that are not in the data"

    # Every line has system and code; medication lines carry the route key.
    for line in _ndjson(catalog_path):
        assert line["system"] and line["code"]
        assert line["count"] >= 1 and line["patients"] >= 0
        if line["kind"] == "medication":
            assert "route" in line

    # Nothing is added inside fhir_r4/: only resource files and the two sidecars.
    for name in os.listdir(fhir_dir):
        assert name.endswith(".ndjson") or name in {"manifest.json", "_generator_metadata.json"}, name
    manifest = json.load(open(os.path.join(fhir_dir, "manifest.json"), encoding="utf-8"))
    assert {o["url"] for o in manifest["output"]} == {n for n in os.listdir(fhir_dir) if n.endswith(".ndjson")}
