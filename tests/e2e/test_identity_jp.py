"""End-to-end: JP resident identifier & insurance numbering (AD-54).

Verifies the full pipeline carries insurance enrollment into Layer 2, that FHIR
Coverage builds with resolvable payor references, and that the 個人番号 privacy
chokepoint holds (national_id present in CIF, never emitted to FHIR).
"""

import json
from dataclasses import asdict

import pytest

from clinosim.modules.output.fhir_r4_adapter import (
    _build_coverage_resources,
    _build_patient,
)
from clinosim.simulator import run_beta
from clinosim.types.config import SimulatorConfig


@pytest.fixture(scope="module")
def jp_dataset():
    return run_beta(SimulatorConfig(catchment_population=2_000, random_seed=7, country="JP"))


@pytest.mark.e2e
class TestJPIdentity:
    def test_every_patient_has_enrollment(self, jp_dataset):
        recs = jp_dataset.patients
        assert recs
        for r in recs:
            assert r.patient.identity is not None
            enr = r.patient.identity.current_enrollment()
            assert enr is not None
            assert enr.insurer_number and enr.member_id

    def test_household_id_carried_to_layer2(self, jp_dataset):
        assert all(r.patient.household_id for r in jp_dataset.patients)

    def test_late_elderly_use_per_individual_scheme(self, jp_dataset):
        elderly = [r for r in jp_dataset.patients if r.patient.age >= 75]
        for r in elderly:
            enr = r.patient.identity.current_enrollment()
            assert enr.category == "late_elderly"
            assert enr.group_symbol is None  # per-individual, no 記号

    def test_coverage_builds_with_resolvable_payor(self, jp_dataset):
        built = 0
        for r in jp_dataset.patients:
            res = _build_coverage_resources(asdict(r.patient), "JP")
            if not res:
                continue
            built += 1
            org_refs = {
                f"Organization/{x['id']}" for x in res if x["resourceType"] == "Organization"
            }
            cov = next(x for x in res if x["resourceType"] == "Coverage")
            assert cov["payor"][0]["reference"] in org_refs
            assert cov["beneficiary"]["reference"] == f"Patient/{r.patient.patient_id}"
        assert built == len(jp_dataset.patients)

    def test_national_id_in_cif_not_in_fhir(self, jp_dataset):
        """Privacy chokepoint: national_id exists in Layer 2/CIF but never in FHIR."""
        seen_national_id = False
        for r in jp_dataset.patients:
            pdict = asdict(r.patient)
            nid = pdict["identity"]["national"]["national_id"]
            assert nid  # present in CIF (extensibility)
            seen_national_id = True
            blob = json.dumps(_build_coverage_resources(pdict, "JP"), default=str)
            blob += json.dumps(_build_patient(pdict, "JP"), default=str)
            assert nid not in blob
        assert seen_national_id


@pytest.mark.e2e
class TestJPInsuranceToggle:
    def test_no_jp_insurance_omits_enrollment(self):
        """--no-jp-insurance (jp_insurance_numbers=False) → no enrollment, no Coverage."""
        ds = run_beta(SimulatorConfig(
            catchment_population=1_500, random_seed=7,
            country="JP", jp_insurance_numbers=False,
        ))
        assert ds.patients
        assert all(r.patient.identity is None for r in ds.patients)
        assert all(
            not _build_coverage_resources(asdict(r.patient), "JP")
            for r in ds.patients[:25]
        )
