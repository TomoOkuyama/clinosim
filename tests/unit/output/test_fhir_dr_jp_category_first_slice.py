"""Regression: JP DiagnosticReport category:first slice conformance.

Guards session 57 fix (Issue #216) against silent-drop regressions:

* JP lab DR (`JP_DiagnosticReport_LabResult` profile) must emit
  `category:first.coding` with `system=http://loinc.org` and
  `code=LP29693-6`.
* JP microbiology DR (`JP_DiagnosticReport_Microbiology` profile) must emit
  `category:first.coding` with `system=http://loinc.org` and
  `code=LP7819-8`, AND `code.coding` must contain a
  `JP_DocumentCodes_CS 18725-2` entry (patternCodeableConcept requirement).
* US output for both is unchanged (no LOINC category prefix, no
  JP_DocumentCodes_CS in DR.code).

Additionally pins the spec fixedCode values by reading the actual JP Core
StructureDefinition JSON in ``fhir-jp-validator/jp_core/package/``. A
future SNOMED/LOINC version bump that changes the required code MUST
regenerate both the constant in the source module and the pinned literal
in the spec-alignment test — the fail-loud assertion is the regression
gate.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from clinosim.modules.output._fhir_common import BundleContext
from clinosim.modules.output._fhir_diagnostic_report import (
    JP_LAB_DR_CATEGORY_LOINC,
    build_lab_panel_reports,
)
from clinosim.modules.output._fhir_microbiology import (
    JP_MB_DR_CATEGORY_LOINC,
    JP_MB_DR_CODE_CS,
    JP_MB_DR_CODE_VALUE,
    JP_MB_DR_PROFILE_URI,
    _bb_microbiology,
)
from clinosim.types.encounter import Order, OrderResult, OrderStatus, OrderType

_LOINC_URI = "http://loinc.org"
_JP_CORE_DIR = Path(__file__).resolve().parents[3] / ".." / "fhir-jp-validator" / "jp_core" / "package"


# === helpers ===


def _make_ctx_lab(orders: list, country: str) -> BundleContext:
    return BundleContext(
        record={"orders": orders},
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


def _make_cbc_orders() -> list[Order]:
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
        o.result = OrderResult(
            result_datetime=t,
            performed_by="tech1",
            lab_name=name,
            value=6.0,
            unit="u",
        )
        out.append(o)
    return out


def _make_ctx_mb(cultures: list[dict], country: str) -> BundleContext:
    return BundleContext(
        record={
            "microbiology": cultures,
            "encounters": [{"encounter_id": "enc1", "attending_physician_id": "doc1"}],
            "orders": [],
        },
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


def _make_cultures() -> list[dict]:
    return [
        {
            "specimen": "blood",
            "test_loinc": "600-7",
            "organism_snomed": "3092008",
            "growth": True,
            "reported_datetime": "2026-06-29T10:00:00",
            "susceptibilities": [],
        }
    ]


# === lab DR ===


def test_lab_dr_jp_category_first_is_loinc_lp29693_6() -> None:
    ctx = _make_ctx_lab(_make_cbc_orders(), country="JP")
    reports = build_lab_panel_reports(ctx)
    assert reports, "expected at least one lab DR"
    cat = reports[0]["category"]
    assert len(cat) >= 2, "JP lab DR must emit >=2 category elements (LOINC + v2-0074)"
    first_coding = cat[0]["coding"][0]
    assert first_coding["system"] == _LOINC_URI
    assert first_coding["code"] == JP_LAB_DR_CATEGORY_LOINC == "LP29693-6"


def test_lab_dr_us_category_unchanged() -> None:
    ctx = _make_ctx_lab(_make_cbc_orders(), country="US")
    reports = build_lab_panel_reports(ctx)
    assert reports
    cat = reports[0]["category"]
    assert len(cat) == 1, "US lab DR must remain a single-element v2-0074 category"
    assert cat[0]["coding"][0]["code"] == "LAB"


# === microbiology DR ===


def test_mb_dr_jp_profile_and_category_and_code() -> None:
    ctx = _make_ctx_mb(_make_cultures(), country="JP")
    resources = _bb_microbiology(ctx)
    reports = [r for r in resources if r["resourceType"] == "DiagnosticReport"]
    assert len(reports) == 1
    dr = reports[0]

    assert JP_MB_DR_PROFILE_URI in dr["meta"]["profile"], "JP MB DR must declare Microbiology profile"

    cat = dr["category"]
    assert len(cat) >= 2
    first_coding = cat[0]["coding"][0]
    assert first_coding["system"] == _LOINC_URI
    assert first_coding["code"] == JP_MB_DR_CATEGORY_LOINC == "LP7819-8"

    codings = dr["code"]["coding"]
    assert any(c.get("system") == JP_MB_DR_CODE_CS and c.get("code") == JP_MB_DR_CODE_VALUE for c in codings), (
        f"JP MB DR.code must contain JP_DocumentCodes_CS pattern; got {codings}"
    )


def test_mb_dr_us_unchanged() -> None:
    ctx = _make_ctx_mb(_make_cultures(), country="US")
    resources = _bb_microbiology(ctx)
    reports = [r for r in resources if r["resourceType"] == "DiagnosticReport"]
    dr = reports[0]

    assert "meta" not in dr, "US MB DR must not declare a JP profile"
    cat = dr["category"]
    assert len(cat) == 1
    assert cat[0]["coding"][0]["code"] == "MB"
    for c in dr["code"].get("coding", []):
        assert c.get("system") != JP_MB_DR_CODE_CS, "US MB DR must NOT emit JP_DocumentCodes_CS"


# === spec alignment ===


def _read_sd(name: str) -> dict:
    path = _JP_CORE_DIR / f"StructureDefinition-jp-diagnosticreport-{name}.json"
    if not path.exists():
        import pytest

        pytest.skip(f"JP Core spec file not available at {path}")
    with open(path) as f:
        return json.load(f)


def _find_element(sd: dict, element_id: str) -> dict:
    for e in sd.get("differential", {}).get("element", []):
        if e.get("id") == element_id:
            return e
    raise AssertionError(f"element id={element_id} not found in SD")


def test_lab_result_spec_pin_lp29693_6() -> None:
    sd = _read_sd("labresult")
    e = _find_element(sd, "DiagnosticReport.category:first.coding.code")
    assert e.get("fixedCode") == JP_LAB_DR_CATEGORY_LOINC


def test_microbiology_spec_pin_lp7819_8_and_jp_document_codes() -> None:
    sd = _read_sd("microbiology")
    cat_code = _find_element(sd, "DiagnosticReport.category:first.coding.code")
    assert cat_code.get("fixedCode") == JP_MB_DR_CATEGORY_LOINC

    code_elem = _find_element(sd, "DiagnosticReport.code")
    pattern = code_elem.get("patternCodeableConcept", {})
    codings = pattern.get("coding", [])
    assert any(c.get("system") == JP_MB_DR_CODE_CS and c.get("code") == JP_MB_DR_CODE_VALUE for c in codings), (
        f"spec Microbiology DR.code patternCodeableConcept must include JP_DocumentCodes 18725-2; got {codings}"
    )
