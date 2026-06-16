"""Unit tests for microbiology culture & susceptibility generation + FHIR (AD-55)."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime

import pytest

import clinosim.modules.output.fhir_r4_adapter as fhir
from clinosim.codes import lookup as code_lookup
from clinosim.modules.observation.microbiology import (
    _load,
    generate_microbiology,
    has_microbiology,
)

_DT = datetime(2024, 3, 1, 10, 0)


@pytest.mark.unit
class TestGenerator:
    def test_has_microbiology(self):
        assert has_microbiology("sepsis")
        assert has_microbiology("urinary_tract_infection")
        assert not has_microbiology("diabetes")
        assert not has_microbiology("")

    def test_non_infection_returns_empty(self):
        assert generate_microbiology("acute_mi", _DT, "ENC-1", 42) == []

    def test_deterministic(self):
        a = generate_microbiology("sepsis", _DT, "ENC-X", 42)
        b = generate_microbiology("sepsis", _DT, "ENC-X", 42)
        assert [asdict(x) for x in a] == [asdict(x) for x in b]

    def test_different_encounter_differs_seed(self):
        # Different encounter ids should generally not be identical across many draws.
        results = {
            tuple((m.specimen, m.growth, m.organism_snomed) for m in
                   generate_microbiology("sepsis", _DT, f"ENC-{i}", 42))
            for i in range(20)
        }
        assert len(results) > 1

    def test_uti_produces_urine_culture(self):
        mb = generate_microbiology("urinary_tract_infection", _DT, "ENC-U", 42)
        assert len(mb) == 1
        assert mb[0].specimen == "urine"
        assert mb[0].test_loinc and mb[0].specimen_snomed

    def test_growth_has_valid_organism_and_susceptibilities(self):
        data = _load()
        valid_org = {o["snomed"] for o in data["organisms"].values()}
        valid_abx = set(data["antibiotics"].values())
        seen_growth = False
        for i in range(50):
            for m in generate_microbiology("sepsis", _DT, f"E{i}", 7):
                if m.growth:
                    seen_growth = True
                    assert m.organism_snomed in valid_org
                    assert m.reported_datetime is not None
                    for s in m.susceptibilities:
                        assert s.antibiotic_loinc in valid_abx
                        assert s.interpretation in ("S", "I", "R")
                else:
                    assert m.organism_snomed == ""
                    assert m.susceptibilities == []
        assert seen_growth


@pytest.mark.unit
class TestCodesResolve:
    def test_all_reference_codes_have_display(self):
        data = _load()
        for o in data["organisms"].values():
            assert code_lookup("snomed-ct", o["snomed"], "en") != o["snomed"]
            assert code_lookup("snomed-ct", o["snomed"], "ja") != o["snomed"]
        for spec in data["specimens"].values():
            assert code_lookup("snomed-ct", spec["snomed"], "en") != spec["snomed"]
            assert code_lookup("loinc", spec["test_loinc"], "en") != spec["test_loinc"]
        for loinc in data["antibiotics"].values():
            assert code_lookup("loinc", loinc, "en") != loinc


@pytest.mark.unit
class TestFhirBuilder:
    def _bundle(self, disease_id, country="JP"):
        mb = generate_microbiology(disease_id, _DT, "ENC-T", 3)
        rec = {
            "patient": {"patient_id": "POP-1", "sex": "F"},
            "encounters": [{"encounter_id": "ENC-T"}],
            "clinical_diagnosis": {},
            "microbiology": [asdict(m) for m in mb],
        }
        return fhir._build_bundle(rec, country), mb

    def test_emits_specimen_report_observations(self):
        bundle, mb = self._bundle("urinary_tract_infection")
        types = [e["resource"]["resourceType"] for e in bundle["entry"]]
        assert "Specimen" in types
        assert "DiagnosticReport" in types
        assert types.count("Observation") >= 1

    def test_reference_integrity(self):
        bundle, _ = self._bundle("sepsis")
        ids = {f"{e['resource']['resourceType']}/{e['resource']['id']}" for e in bundle["entry"]}
        for e in bundle["entry"]:
            r = e["resource"]
            if r["resourceType"] == "DiagnosticReport":
                assert r["specimen"][0]["reference"] in ids
                for ref in r["result"]:
                    assert ref["reference"] in ids
                assert r["subject"]["reference"] == "Patient/POP-1"

    def test_no_growth_uses_value_string(self):
        # cellulitis often no growth; find a no-growth culture deterministically across seeds
        for i in range(30):
            mb = generate_microbiology("cellulitis", _DT, f"NG-{i}", 1)
            no_growth = [m for m in mb if m.growth is False]
            if no_growth:
                rec = {
                    "patient": {"patient_id": "P", "sex": "M"},
                    "encounters": [{"encounter_id": f"NG-{i}"}],
                    "clinical_diagnosis": {},
                    "microbiology": [asdict(m) for m in mb],
                }
                bundle = fhir._build_bundle(rec, "US")
                org = next(e["resource"] for e in bundle["entry"]
                           if e["resource"]["id"].startswith("mb-org"))
                assert org.get("valueString") == "No growth"
                return
        pytest.skip("no no-growth culture sampled")
