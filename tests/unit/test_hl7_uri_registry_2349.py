"""HL7 systems are referenced by registry key, not URI literal (Issue #2349)."""

from __future__ import annotations

from pathlib import Path

import pytest

from clinosim.codes import get_system_uri
from clinosim.modules.output.fhir_r4.builder import _drop_entries_after_death
from clinosim.modules.output.fhir_r4.encounters.encounter import _build_encounter

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2]


def test_no_hl7_terminology_uri_literal_in_modules() -> None:
    offenders = [
        str(p.relative_to(_ROOT))
        for p in (_ROOT / "clinosim/modules").rglob("*.py")
        for line in p.read_text(encoding="utf-8").splitlines()
        if '"http://terminology.hl7.org/CodeSystem/' in line
    ]
    assert not offenders, offenders


@pytest.mark.parametrize(
    ("key", "uri"),
    [
        ("hl7-medicationrequest-category", "http://terminology.hl7.org/CodeSystem/medicationrequest-category"),
        ("hl7-v3-confidentiality", "http://terminology.hl7.org/CodeSystem/v3-Confidentiality"),
        ("hl7-ex-diagnosistype", "http://terminology.hl7.org/CodeSystem/ex-diagnosistype"),
        ("hl7-coverage-class", "http://terminology.hl7.org/CodeSystem/coverage-class"),
    ],
)
def test_registered_keys(key: str, uri: str) -> None:
    assert get_system_uri(key) == uri


def _post_mortem_disposition(country: str) -> dict:
    enc = _build_encounter(
        {
            "encounter_id": "E1",
            "encounter_type": "inpatient",
            "admission_datetime": "2026-01-01T09:00:00",
            "discharge_datetime": "2026-01-20T09:00:00",
            "discharge_disposition": "home",
        },
        "patient-1",
        country=country,
    )
    lang = "ja" if country == "JP" else "en"
    kept = _drop_entries_after_death([{"resource": enc}], "2026-01-10", lang, country)
    return kept[0]["resource"]["hospitalization"]["dischargeDisposition"]


def test_post_mortem_disposition_override_carries_a_display() -> None:
    disp = _post_mortem_disposition("US")
    assert disp["coding"][0]["code"] == "exp"
    assert disp["coding"][0]["display"] == "Expired"
    assert disp["text"] == "Expired"


def test_jp_post_mortem_disposition_is_a_death_from_another_cause() -> None:
    # Issue #3150: a JP stay codes the DPC discharge outcome; a death outside
    # the simulated course is 7 傷病以外による死亡.
    disp = _post_mortem_disposition("JP")
    assert disp["coding"][0]["code"] == "7"
    assert disp["coding"][0]["display"] == "傷病以外による死亡"
    assert disp["text"] == "傷病以外による死亡"
