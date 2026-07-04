"""Unit tests for microbiology culture & susceptibility generation + FHIR (AD-55)."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime

import pytest

import clinosim.modules.output.fhir_r4_adapter as fhir
from clinosim.codes import get_system_uri
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

    def test_jp_culture_uses_jlac10_code(self):
        bundle, mb = self._bundle("urinary_tract_infection", country="JP")
        org_obs = next(e["resource"] for e in bundle["entry"]
                       if e["resource"]["id"].startswith("mb-org"))
        coding = org_obs["code"]["coding"][0]
        assert coding["system"] == get_system_uri("jlac10")
        assert coding["code"] == "6B010"

    def test_us_culture_still_uses_loinc(self):
        bundle, mb = self._bundle("urinary_tract_infection", country="US")
        org_obs = next(e["resource"] for e in bundle["entry"]
                       if e["resource"]["id"].startswith("mb-org"))
        coding = org_obs["code"]["coding"][0]
        assert coding["system"] == get_system_uri("loinc")
        assert coding["code"] == mb[0].test_loinc

    def test_hai_derived_culture_resolves_same_as_community(self):
        # Mimics the MicrobiologyResult shape hai/enricher.py builds (only
        # specimen / specimen_snomed / test_loinc / growth / organism_snomed /
        # hai_event_id set) — proves the single change point in
        # _fhir_microbiology.py covers HAI-derived cultures too, since both
        # sources carry the same country-neutral `specimen` key.
        hai_culture = {
            "encounter_id": "ENC-HAI",
            "specimen": "blood",
            "specimen_snomed": "119297000",
            "test_loinc": "600-7",
            "growth": True,
            "organism_snomed": "3092008",
            "quantitation": "",
            "susceptibilities": [],
            "hai_event_id": "HAI-1",
        }
        rec = {
            "patient": {"patient_id": "P-HAI", "sex": "F"},
            "encounters": [{"encounter_id": "ENC-HAI"}],
            "clinical_diagnosis": {},
            "microbiology": [hai_culture],
        }
        bundle = fhir._build_bundle(rec, "JP")
        org_obs = next(e["resource"] for e in bundle["entry"]
                       if e["resource"]["id"].startswith("mb-org"))
        coding = org_obs["code"]["coding"][0]
        assert coding["system"] == get_system_uri("jlac10")
        assert coding["code"] == "6B010"

    def test_jp_unmapped_specimen_falls_back_to_test_loinc(self):
        # Defensive regression guard for the fallback branch itself: today all 4
        # real specimens (blood/urine/sputum/wound) are mapped, so this branch is
        # unreachable with real data — but the `.get(specimen, fallback)` code
        # path must still behave correctly if a future specimen is added to
        # microbiology.yaml before code_mapping_microbiology.yaml is updated for it.
        unmapped_culture = {
            "encounter_id": "ENC-UNMAPPED",
            "specimen": "csf",  # not a key in code_mapping_microbiology.yaml
            "specimen_snomed": "258450006",
            "test_loinc": "6463-4",
            "growth": True,
            "organism_snomed": "9861002",
            "quantitation": "",
            "susceptibilities": [],
            "hai_event_id": "",
        }
        rec = {
            "patient": {"patient_id": "P-UNMAPPED", "sex": "M"},
            "encounters": [{"encounter_id": "ENC-UNMAPPED"}],
            "clinical_diagnosis": {},
            "microbiology": [unmapped_culture],
        }
        bundle = fhir._build_bundle(rec, "JP")
        org_obs = next(e["resource"] for e in bundle["entry"]
                       if e["resource"]["id"].startswith("mb-org"))
        coding = org_obs["code"]["coding"][0]
        assert coding["system"] == get_system_uri("loinc")
        assert coding["code"] == "6463-4"

    def test_jp_susceptibility_uses_jlac10_code(self):
        bundle, _ = self._bundle("sepsis", country="JP")
        sus_obs = [e["resource"] for e in bundle["entry"]
                   if e["resource"]["id"].startswith("mb-sus")]
        assert sus_obs, "expected at least one susceptibility Observation"
        for obs in sus_obs:
            coding = obs["code"]["coding"][0]
            assert coding["system"] == get_system_uri("jlac10")
            assert coding["code"] == "6C010"

    def test_us_susceptibility_still_uses_loinc(self):
        bundle, mb = self._bundle("sepsis", country="US")
        sus_obs = [e["resource"] for e in bundle["entry"]
                   if e["resource"]["id"].startswith("mb-sus")]
        assert sus_obs, "expected at least one susceptibility Observation"
        expected_loincs = {s.antibiotic_loinc for m in mb for s in m.susceptibilities}
        actual_loincs = {obs["code"]["coding"][0]["code"] for obs in sus_obs}
        assert actual_loincs == expected_loincs
        for obs in sus_obs:
            assert obs["code"]["coding"][0]["system"] == get_system_uri("loinc")

    def test_jp_unmapped_antibiotic_falls_back_to_antibiotic_loinc(self):
        # Defensive regression guard for the fallback branch: every real
        # antibiotic_loinc value in microbiology.yaml is mapped today, so this
        # branch is unreachable with real data — but a future antibiotic added
        # to microbiology.yaml before code_mapping_microbiology_susceptibility.yaml
        # is updated for it must not get its LOINC value mistagged as jlac10.
        unmapped_culture = {
            "encounter_id": "ENC-UNMAPPED-ABX",
            "specimen": "blood",
            "specimen_snomed": "119297000",
            "test_loinc": "600-7",
            "growth": True,
            "organism_snomed": "3092008",
            "quantitation": "",
            "susceptibilities": [{"antibiotic_loinc": "99999-1", "interpretation": "S"}],
            "hai_event_id": "",
        }
        rec = {
            "patient": {"patient_id": "P-UNMAPPED-ABX", "sex": "M"},
            "encounters": [{"encounter_id": "ENC-UNMAPPED-ABX"}],
            "clinical_diagnosis": {},
            "microbiology": [unmapped_culture],
        }
        bundle = fhir._build_bundle(rec, "JP")
        sus_obs = next(e["resource"] for e in bundle["entry"]
                       if e["resource"]["id"].startswith("mb-sus"))
        coding = sus_obs["code"]["coding"][0]
        assert coding["system"] == get_system_uri("loinc")
        assert coding["code"] == "99999-1"
