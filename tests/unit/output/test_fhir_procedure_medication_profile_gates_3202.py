"""Procedure and medication FHIR builders gate profile structure on the
country profile, not on the country (Issue #3202).

``docs/design-guides/country-profile-spec.md`` §5: the JP Core profile URLs
(Procedure, Immunization, nursing Observations, MedicationRequest,
MedicationAdministration), the JP Core ``rpNumber`` / ``orderInRp``
identifier slices and the JP-CLINS eCS ``nocoded`` medication coding are
emitted only when ``profile.uses("jp_core" | "jp_clins")``; the profile URLs
come from ``clinosim/codes/data/fhir-profiles-jp-core.yaml``. The tests swap
the profile's ``fhir_profiles`` list and check the structure follows it.
"""

from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import pytest

import clinosim.country_profile as cp
from clinosim.codes import data_table, get_system_uri
from clinosim.modules.output.fhir_r4.lib.context import BundleContext
from clinosim.modules.output.fhir_r4.lib.jp_profiles import (
    JP_MEDICATION_ADMINISTRATION_INDEX_SYSTEM,
    JP_MEDICATION_RP_GROUP_NUMBER_SYSTEM,
)
from clinosim.modules.output.fhir_r4.medications.medications import (
    _build_medication_admin,
    _build_medication_request_identifiers,
    _build_medication_request_meta,
    _resolve_medication_concept,
)
from clinosim.modules.output.fhir_r4.procedures.immunization import _bb_immunizations
from clinosim.modules.output.fhir_r4.procedures.nursing import _bb_nursing_observations
from clinosim.modules.output.fhir_r4.procedures.procedures import _build_procedure

pytestmark = pytest.mark.unit

_JP_SLICES = {JP_MEDICATION_RP_GROUP_NUMBER_SYSTEM, JP_MEDICATION_ADMINISTRATION_INDEX_SYSTEM}
_NOCODED_CS = get_system_uri("medication-nocoded")


def _jp_core(resource_type: str) -> list[str]:
    return list(data_table("fhir-profiles-jp-core")["profiles"][resource_type])


@pytest.fixture
def with_profiles(monkeypatch: pytest.MonkeyPatch) -> Callable[[tuple[str, ...]], None]:
    """Replace every country's ``fhir_profiles`` with the given list."""
    real = cp._profile

    def apply(names: tuple[str, ...]) -> None:
        monkeypatch.setattr(cp, "_profile", lambda code: real(code).model_copy(update={"fhir_profiles": names}))

    return apply


_PROC = {
    "procedure_id": "PROC-1",
    "patient_id": "PAT-1",
    "encounter_id": "ENC-1",
    "procedure_type": "ORIF",
    "procedure_code": "27236",
    "procedure_code_jp": "K0463",
    "procedure_code_us": "27236",
    "start_datetime": "2026-04-06T14:30:00",
    "end_datetime": "2026-04-06T16:00:00",
}
_MAR = {
    "order_id": "ORD-1",
    "drug_name": "Amlodipine",
    "scheduled_datetime": "2026-01-01T08:00:00",
    "actual_datetime": "2026-01-01T08:05:00",
    "status": "given",
    "dose": "5mg",
    "route": "PO",
    "administered_by": "N-1",
}


def _immunization(country: str) -> dict:
    ctx = BundleContext(
        record={
            "immunizations": [{"vaccine_cvx": "115", "occurrence_date": "2005-06-01", "status": "completed"}],
            "encounters": [],
        },
        country=country,
        roster_map={},
        hospital_config={},
        patient_data={},
        patient_id="P1",
        is_readmission=False,
        prior_encounter_id=None,
        primary_dx_code="",
        admit_dx_code="",
        admit_dx_system="",
        primary_enc_id="",
        patient_sex="",
    )
    return _bb_immunizations(ctx)[0]


def _news2(country: str) -> dict:
    ctx = SimpleNamespace(
        record={
            "encounters": [{"encounter_id": "ENC-1", "encounter_type": "inpatient"}],
            "vital_signs": [{"timestamp": "2026-05-12T10:00:00", "news2_score": 3}],
        },
        country=country,
        patient_id="P1",
        primary_enc_id="ENC-1",
    )
    return next(o for o in _bb_nursing_observations(ctx) if o["id"].startswith("news2-"))


def _resources(country: str) -> dict[str, Any]:
    concept, _ = _resolve_medication_concept("Zzzunlistedmab 5 mg", "", country, "PO")
    return {
        "procedure": _build_procedure(dict(_PROC), "PAT-1", 0, country),
        "immunization": _immunization(country),
        "news2": _news2(country),
        "mr_meta": _build_medication_request_meta(country, ""),
        "mr_ids": _build_medication_request_identifiers("k1", country, "1", "1")["identifier"],
        "ma": _build_medication_admin(dict(_MAR), "PAT-1", 0, country),
        "uncoded": concept,
    }


def _loinc_codes(obs: dict) -> set[str]:
    return {c["code"] for c in obs["code"]["coding"] if c["system"] == "http://loinc.org"}


def test_jp_without_jp_profiles_emits_no_jp_structure(with_profiles) -> None:
    with_profiles(())
    r = _resources("JP")
    for key in ("procedure", "immunization", "news2", "ma"):
        assert "meta" not in r[key], key
    assert r["mr_meta"] == {}
    assert not {i["system"] for i in r["mr_ids"]} & _JP_SLICES
    assert not {i["system"] for i in r["ma"]["identifier"]} & _JP_SLICES
    assert "115635-5" in _loinc_codes(r["news2"])
    assert "coding" not in r["uncoded"]


def test_a_country_applying_jp_profiles_gets_the_jp_structure(with_profiles) -> None:
    with_profiles(("jp_core", "jp_clins"))
    r = _resources("US")
    assert r["procedure"]["meta"]["profile"] == _jp_core("Procedure")
    assert r["immunization"]["meta"]["profile"] == _jp_core("Immunization")
    assert r["news2"]["meta"]["profile"] == _jp_core("Observation")
    assert r["mr_meta"] == {"meta": {"profile": _jp_core("MedicationRequest")}}
    assert r["ma"]["meta"]["profile"] == _jp_core("MedicationAdministration")
    assert _JP_SLICES <= {i["system"] for i in r["mr_ids"]}
    assert _JP_SLICES <= {i["system"] for i in r["ma"]["identifier"]}
    assert "115635-5" not in _loinc_codes(r["news2"])
    assert [c["system"] for c in r["uncoded"]["coding"]] == [_NOCODED_CS]
