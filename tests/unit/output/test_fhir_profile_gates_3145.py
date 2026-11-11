"""Demographics and condition FHIR builders gate profile structure on the
country profile, not on the country (Issue #3145).

``docs/design-guides/country-profile-spec.md`` §5: a builder emits a JP Core /
JP-CLINS / US Core element (``meta.profile``, the kanji / kana name entries,
the eCS diagnosis-type extension, the license identifier, the US Core
extensions, the NPI) only when ``profile.uses(...)`` says the country's output
applies that FHIR profile, and the profile URLs come from
``clinosim/codes/data/fhir-profiles-*.yaml``. The tests swap the profile's
``fhir_profiles`` list and check the structure follows it.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

import clinosim.country_profile as cp
from clinosim.codes import data_table
from clinosim.modules.output.fhir_r4.conditions.allergy_intolerance import _build_allergy_intolerance
from clinosim.modules.output.fhir_r4.conditions.conditions import _condition_skeleton, _ConditionContext
from clinosim.modules.output.fhir_r4.demographics.patient import _build_occupation_observation, _build_patient
from clinosim.modules.output.fhir_r4.demographics.practitioner import _build_practitioner, _build_practitioner_role
from clinosim.modules.output.fhir_r4.demographics.smoking_alcohol import _obs
from clinosim.modules.output.fhir_r4.lib.profile_meta import profile_meta

pytestmark = pytest.mark.unit

_ISO21090 = "http://hl7.org/fhir/StructureDefinition/iso21090-EN-representation"


def _jp_core(resource_type: str) -> list[str]:
    return list(data_table("fhir-profiles-jp-core")["profiles"][resource_type])


@pytest.fixture
def with_profiles(monkeypatch: pytest.MonkeyPatch) -> Callable[[tuple[str, ...]], None]:
    """Replace every country's ``fhir_profiles`` with the given list."""
    real = cp._profile

    def apply(names: tuple[str, ...]) -> None:
        monkeypatch.setattr(cp, "_profile", lambda code: real(code).model_copy(update={"fhir_profiles": names}))

    return apply


_PATIENT = {
    "patient_id": "pt-1",
    "name": {"family_name": "田中", "given_name": "太郎", "phonetic": "タナカ タロウ"},
    "sex": "M",
    "date_of_birth": "1970-01-01",
    "race": "white",
    "address": {"state": "東京都", "city": "千代田区", "line1": "丸の内 1-1-1", "postal_code": "100-0005"},
}
_ROSTER = {
    "DR-1": {
        "name": "田中 太郎",
        "name_phonetic": "タナカ タロウ",
        "role": "physician",
        "department": "cardiology",
        "specialty": "cardiology",
    }
}


def test_profile_meta_reads_the_profile_url_table() -> None:
    assert profile_meta("Practitioner", "JP") == {"meta": {"profile": _jp_core("Practitioner")}}
    assert profile_meta("Practitioner", "US") == {}


def test_profile_meta_returns_a_fresh_list() -> None:
    first = profile_meta("Condition", "JP")
    first["meta"]["profile"].append("x")
    assert profile_meta("Condition", "JP") == {"meta": {"profile": _jp_core("Condition")}}


def test_jp_without_jp_profiles_emits_no_jp_structure(with_profiles) -> None:
    with_profiles(())
    patient = _build_patient(dict(_PATIENT), "JP")
    assert "meta" not in patient
    assert len(patient["name"]) == 1 and "extension" not in patient["name"][0]
    assert "extension" not in patient

    practitioner = _build_practitioner("DR-1", _ROSTER, "JP")
    assert "meta" not in practitioner
    assert [i["system"] for i in practitioner["identifier"]] == ["urn:clinosim:staff"]
    assert all("extension" not in n for n in practitioner["name"])
    assert "meta" not in _build_practitioner_role("DR-1", _ROSTER, "JP")

    assert "meta" not in _obs("o1", "JP", "72166-2", "Tobacco smoking status", "snomed-ct", "8517006")
    occupation = _build_occupation_observation("office_worker", "pt-1", "JP")
    assert occupation is None or "meta" not in occupation

    ctx = _ConditionContext("pt-1", "JP", [], False, "M")
    cond = _condition_skeleton(
        ctx,
        condition_id="c1",
        structural_key="k1",
        diagnosis_type="principal",
        clinical_status="active",
        category="problem-list-item",
        mapped_code="I10",
    )
    assert "meta" not in cond and "extension" not in cond

    allergy = _build_allergy_intolerance({"allergen_code": "91936005", "allergy_id": "a1"}, "pt-1", "ja", "JP")
    assert allergy is not None and "meta" not in allergy


def test_a_country_applying_jp_core_gets_the_jp_core_structure(with_profiles) -> None:
    with_profiles(("jp_core",))
    patient = _build_patient(dict(_PATIENT), "US")
    assert patient["meta"]["profile"] == _jp_core("Patient")
    assert [e["valueCode"] for n in patient["name"] for e in n["extension"] if e["url"] == _ISO21090] == [
        "IDE",
        "SYL",
    ]
    practitioner = _build_practitioner("DR-1", _ROSTER, "US")
    assert practitioner["meta"]["profile"] == _jp_core("Practitioner")
    ctx = _ConditionContext("pt-1", "US", [], False, "M")
    cond = _condition_skeleton(
        ctx,
        condition_id="c1",
        structural_key="k1",
        diagnosis_type="principal",
        clinical_status="active",
        category="problem-list-item",
        mapped_code="I10",
    )
    # JP Core alone: the JP-CLINS eCS diagnosis-type extension stays off.
    assert cond["meta"]["profile"] == _jp_core("Condition")
    assert "extension" not in cond


def test_us_core_structure_follows_the_us_core_profile(with_profiles) -> None:
    with_profiles(())
    patient = _build_patient(dict(_PATIENT), "US")
    assert "extension" not in patient
    practitioner = _build_practitioner("DR-1", _ROSTER, "US")
    assert [i["system"] for i in practitioner["identifier"]] == ["urn:clinosim:staff"]
