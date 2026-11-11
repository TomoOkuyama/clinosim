"""Labs FHIR builders gate profile structure on the country profile, not on
the country (Issue #3201).

``docs/design-guides/country-profile-spec.md`` §5: a lab / vital-sign /
anthropometric / blood-type Observation, a lab / microbiology / radiology
DiagnosticReport and an ImagingStudy carry their JP Core structure
(``meta.profile``, the JP ``category:first`` slice, the JP document code, the
omitted ``procedureCode``) only when ``profile.uses("jp_core")``, and the
profile URLs come from ``clinosim/codes/data/fhir-profiles-jp-core.yaml``.
The tests swap the profile's ``fhir_profiles`` list and check the structure
follows it.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from types import SimpleNamespace
from typing import Any

import pytest

import clinosim.country_profile as cp
from clinosim.codes import data_table
from clinosim.modules.output.fhir_r4.labs.anthropometrics import _build_one_observation
from clinosim.modules.output.fhir_r4.labs.blood_type import _build_blood_type_obs
from clinosim.modules.output.fhir_r4.labs.diagnostic_report import (
    RADIOLOGY_DR_ID_PREFIX,
    _bb_diagnostic_reports,
    build_lab_panel_reports,
)
from clinosim.modules.output.fhir_r4.labs.imaging_study import _build_imaging_study
from clinosim.modules.output.fhir_r4.labs.microbiology import _bb_microbiology
from clinosim.modules.output.fhir_r4.labs.observations import _bb_labs
from clinosim.modules.output.fhir_r4.lib.context import BundleContext
from clinosim.modules.output.fhir_r4.lib.profile_meta import profile_meta
from clinosim.types.encounter import Order, OrderResult, OrderStatus, OrderType
from clinosim.types.imaging import ImagingSeries, ImagingStudyRecord, RadiologyReport

pytestmark = pytest.mark.unit

_LOINC = "http://loinc.org"


def _variant(key: str) -> list[str]:
    return list(data_table("fhir-profiles-jp-core")["variants"][key])


@pytest.fixture
def with_profiles(monkeypatch: pytest.MonkeyPatch) -> Callable[[tuple[str, ...]], None]:
    """Replace every country's ``fhir_profiles`` with the given list."""
    real = cp._profile

    def apply(names: tuple[str, ...]) -> None:
        monkeypatch.setattr(cp, "_profile", lambda code: real(code).model_copy(update={"fhir_profiles": names}))

    return apply


def _ctx(country: str, **record: Any) -> BundleContext:
    return BundleContext(
        record={"orders": [], "encounters": [{"encounter_id": "enc1", "attending_physician_id": "doc1"}], **record},
        country=country,
        roster_map={},
        hospital_config={},
        patient_data={},
        patient_id="pt1",
        is_readmission=False,
        prior_encounter_id=None,
        primary_dx_code="",
        admit_dx_code="",
        admit_dx_system="",
        primary_enc_id="enc1",
        patient_sex="",
    )


def _cbc_orders() -> list[Order]:
    t = datetime(2026, 6, 29, 8, 5)
    out: list[Order] = []
    for i, name in enumerate(["WBC", "Hb", "Hct", "Plt"]):
        o = Order(
            order_id=f"O{i}",
            encounter_id="enc1",
            patient_id="pt1",
            order_type=OrderType.LAB,
            order_code="X",
            display_name=name,
            ordered_datetime=t,
            ordered_by="doc1",
            status=OrderStatus.RESULTED,
            panel_key="CBC",
        )
        o.result = OrderResult(result_datetime=t, performed_by="tech1", lab_name=name, value=6.0, unit="u")
        out.append(o)
    return out


_CULTURE = {
    "specimen": "blood",
    "test_loinc": "600-7",
    "organism_snomed": "3092008",
    "growth": True,
    "reported_datetime": "2026-06-29T10:00:00",
    "susceptibilities": [],
}


def _study() -> ImagingStudyRecord:
    return ImagingStudyRecord(
        study_id="imgst-enc1-1",
        study_instance_uid="2.25.42",
        encounter_id="enc1",
        patient_id="pt1",
        order_id="ord1",
        status="available",
        started_datetime=datetime(2026, 6, 30, 10, 0),
        modality_code="CR",
        body_site_snomed="51185008",
        series=[
            ImagingSeries(
                series_uid="2.25.43",
                series_number=1,
                modality_code="CR",
                body_site_snomed="51185008",
                description="PA view",
                instance_count=1,
            )
        ],
        endpoint_id="endpoint-2.25.42",
        report=RadiologyReport(
            report_id="imgrpt-enc1-1",
            status="final",
            findings_text="Right lower lobe consolidation.",
            impression_text="Pneumonia.",
        ),
    )


def _radiology_dr(country: str) -> dict:
    ctx = SimpleNamespace(
        record={"extensions": {"imaging": [_study()]}, "orders": []},
        country=country,
        patient_id="pt1",
        primary_enc_id="enc1",
        roster_map={},
        hospital_config={},
        patient_data={},
        is_readmission=False,
        prior_encounter_id=None,
        primary_dx_code="",
        admit_dx_code="",
    )
    return next(r for r in _bb_diagnostic_reports(ctx) if r["id"].startswith(RADIOLOGY_DR_ID_PREFIX))


def _resources(country: str) -> dict[str, Any]:
    mb = _bb_microbiology(_ctx(country, microbiology=[dict(_CULTURE)]))
    return {
        "labs": _bb_labs(_ctx(country, orders=_cbc_orders())),
        "lab_dr": build_lab_panel_reports(_ctx(country, orders=_cbc_orders()))[0],
        "mb_obs": [r for r in mb if r["resourceType"] == "Observation"],
        "mb_dr": next(r for r in mb if r["resourceType"] == "DiagnosticReport"),
        "rad_dr": _radiology_dr(country),
        "anthro": _build_one_observation("29463-7", 70.0, "pt1", "enc1", "2026-06-29T08:00:00", country, "wt"),
        "blood": _build_blood_type_obs("abo1", country, "883-9", "ABO group", "112144000"),
        "study": _build_imaging_study(_study(), "en", country),
    }


def _first_category_system(resource: dict) -> str:
    return resource["category"][0]["coding"][0]["system"]


def test_profile_meta_reads_the_variant_table() -> None:
    assert profile_meta("DiagnosticReport/Radiology", "JP") == {
        "meta": {"profile": _variant("DiagnosticReport/Radiology")}
    }
    assert profile_meta("DiagnosticReport/Radiology", "US") == {}


def test_jp_without_jp_profiles_emits_no_jp_structure(with_profiles) -> None:
    with_profiles(())
    r = _resources("JP")
    for obs in [*r["labs"], *r["mb_obs"], r["anthro"], r["blood"]]:
        assert "meta" not in obs, obs
    for dr in (r["lab_dr"], r["mb_dr"], r["rad_dr"]):
        assert "meta" not in dr
        assert _first_category_system(dr) != _LOINC
    assert all(c.get("system") != _LOINC or c.get("code") != "18725-2" for c in r["mb_dr"]["code"]["coding"])
    assert "procedureCode" in r["study"]


def test_a_country_applying_jp_core_gets_the_jp_core_structure(with_profiles) -> None:
    with_profiles(("jp_core",))
    r = _resources("US")
    assert all(_variant("Observation/LabResult") == o["meta"]["profile"] for o in [*r["mb_obs"], r["blood"]])
    assert any(o.get("meta", {}).get("profile") == _variant("Observation/LabResult") for o in r["labs"])
    assert r["anthro"]["meta"]["profile"] == list(data_table("fhir-profiles-jp-core")["profiles"]["Observation"])
    assert r["lab_dr"]["meta"]["profile"] == _variant("DiagnosticReport/LabResult")
    assert r["mb_dr"]["meta"]["profile"] == _variant("DiagnosticReport/Microbiology")
    assert r["rad_dr"]["meta"]["profile"] == _variant("DiagnosticReport/Radiology")
    for dr in (r["lab_dr"], r["mb_dr"], r["rad_dr"]):
        assert _first_category_system(dr) == _LOINC
    assert "procedureCode" not in r["study"]
