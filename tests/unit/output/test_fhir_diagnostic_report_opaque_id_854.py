"""Issue #854 Bucket B (PR-diagnostic-report): DiagnosticReport opaque id
across all 3 emit paths (lab-panel / microbiology / radiology).

Extends the opaque-id pattern (PR #357 → #863 → #867 → #868 → #869 →
#878 [lab] → #879 [vs/gcs/news2] → #880 [stand-alones] → #881 [mb-org/sus]
→ #882 [Specimen] → #883 [Condition]) to `DiagnosticReport`.

Post-#854 every DR.id is opaque, with 3 distinct prefixes preserved so
consumers filtering by `.startswith("dr-mb-")` / `.startswith("imgrpt-")`
keep working:

    lab-panel DR:    dr-<12hex>       (15 chars, fixed)
    microbiology DR: dr-mb-<12hex>    (18 chars, fixed)
    radiology DR:    imgrpt-<12hex>   (19 chars, fixed)

Three PUBLIC key-system URIs — one per DR family. The DR is a leaf
resource in the FHIR reference graph on the p=200 sample (nothing
references DR.id back), so no cross-ref cascade guard is needed here
(unlike PR-condition / PR-specimen). The `imaging_report.py` Composition
builder still uses the CIF-side `report.report_id`
(`imgrpt-{enc_id}-{idx}`) for seq extraction — that CIF field is
unchanged; only the FHIR emit path became opaque.
"""

from __future__ import annotations

import re
from types import SimpleNamespace

import pytest

from clinosim.modules.output.fhir_r4.labs.diagnostic_report import (
    LAB_PANEL_DR_KEY_SYSTEM,
    MB_DR_KEY_SYSTEM,
    RADIOLOGY_DR_KEY_SYSTEM,
    _GroupedPanel,
    _resolve_lab_panel_dr_id,
    _resolve_mb_dr_id,
    _resolve_radiology_dr_id,
    build_dr_resource,
)
from clinosim.modules.output.fhir_r4.labs.microbiology import _bb_microbiology

pytestmark = pytest.mark.unit


_OPAQUE_LAB_PANEL_DR_PATTERN = re.compile(r"^dr-[0-9a-f]{12}$")
_OPAQUE_MB_DR_PATTERN = re.compile(r"^dr-mb-[0-9a-f]{12}$")
_OPAQUE_RADIOLOGY_DR_PATTERN = re.compile(r"^imgrpt-[0-9a-f]{12}$")


# === Resolver contracts (3 families) ===


def test_resolve_lab_panel_dr_id_opaque_shape() -> None:
    result = _resolve_lab_panel_dr_id("cbc-ENC-001-0")
    assert _OPAQUE_LAB_PANEL_DR_PATTERN.match(result), f"got {result!r}"
    assert len(result) == 15


def test_resolve_mb_dr_id_opaque_shape() -> None:
    result = _resolve_mb_dr_id("ENC-001-0")
    assert _OPAQUE_MB_DR_PATTERN.match(result), f"got {result!r}"
    assert len(result) == 18


def test_resolve_radiology_dr_id_opaque_shape() -> None:
    """Structural key is the CIF report_id stripped of its `imgrpt-` prefix."""
    result = _resolve_radiology_dr_id("ENC-001-0")
    assert _OPAQUE_RADIOLOGY_DR_PATTERN.match(result), f"got {result!r}"
    assert len(result) == 19


def test_all_three_resolvers_deterministic() -> None:
    key = "ENC-001-0"
    assert _resolve_lab_panel_dr_id(key) == _resolve_lab_panel_dr_id(key)
    assert _resolve_mb_dr_id(key) == _resolve_mb_dr_id(key)
    assert _resolve_radiology_dr_id(key) == _resolve_radiology_dr_id(key)


def test_three_families_produce_distinct_ids_from_same_key() -> None:
    key = "ENC-001-0"
    ids = {_resolve_lab_panel_dr_id(key), _resolve_mb_dr_id(key), _resolve_radiology_dr_id(key)}
    assert len(ids) == 3


def test_key_system_uris() -> None:
    assert LAB_PANEL_DR_KEY_SYSTEM == "urn:clinosim:identifier:lab-panel-diagnostic-report-key"
    assert MB_DR_KEY_SYSTEM == "urn:clinosim:identifier:mb-diagnostic-report-key"
    assert RADIOLOGY_DR_KEY_SYSTEM == "urn:clinosim:identifier:radiology-diagnostic-report-key"


# === Emit path — lab-panel DR ===


def test_build_dr_resource_lab_panel_id_is_opaque_with_identifier() -> None:
    group = _GroupedPanel(panel_name="CBC", bucket="2026-05-12", obs_idxs=[0, 1, 2, 3])
    r = build_dr_resource(
        group,
        patient_id="POP-1",
        encounter_id="ENC-001",
        country="US",
        performer_ref=None,
        issued=None,
        seq=0,
    )
    assert _OPAQUE_LAB_PANEL_DR_PATTERN.match(r["id"]), f"non-opaque lab-panel DR id: {r['id']!r}"
    key_idents = [i for i in r.get("identifier", []) if i.get("system") == LAB_PANEL_DR_KEY_SYSTEM]
    assert len(key_idents) == 1
    assert key_idents[0]["value"] == "cbc-ENC-001-0"


def test_build_dr_resource_lab_panel_same_input_reproduces_same_id() -> None:
    group = _GroupedPanel(panel_name="CBC", bucket="2026-05-12", obs_idxs=[0, 1, 2, 3])
    a = build_dr_resource(group, "P", "ENC-1", "US", None, None, 0)
    b = build_dr_resource(group, "P", "ENC-1", "US", None, None, 0)
    assert a["id"] == b["id"]


# === Emit path — microbiology DR ===


def _mb_ctx(cultures: list, *, encounter_id: str = "ENC-001", country: str = "US") -> SimpleNamespace:
    return SimpleNamespace(
        record={
            "patient": {"patient_id": "POP-000002"},
            "microbiology": cultures,
            "encounters": [{"encounter_id": encounter_id, "attending_physician_id": "STAFF-001"}],
        },
        country=country,
        roster_map={},
        hospital_config={},
        patient_data={"patient_id": "POP-000002"},
        patient_id="POP-000002",
        primary_enc_id=encounter_id,
    )


def _sample_culture() -> dict:
    return {
        "specimen": "blood",
        "test_loinc": "600-7",
        "specimen_snomed": "119297000",
        "collected_datetime": "2026-05-12T14:28:38",
        "reported_datetime": "2026-05-13T09:00:00",
        "growth": True,
        "organism_snomed": "3092008",
        "susceptibilities": [{"antibiotic_loinc": "18866-6", "interpretation": "S"}],
    }


def test_bb_microbiology_dr_id_is_opaque_with_identifier() -> None:
    ctx = _mb_ctx([_sample_culture()])
    resources = _bb_microbiology(ctx)
    drs = [r for r in resources if r["resourceType"] == "DiagnosticReport"]
    assert len(drs) == 1
    r = drs[0]
    assert _OPAQUE_MB_DR_PATTERN.match(r["id"]), f"non-opaque mb DR id: {r['id']!r}"
    key_idents = [i for i in r.get("identifier", []) if i.get("system") == MB_DR_KEY_SYSTEM]
    assert len(key_idents) == 1
    assert key_idents[0]["value"] == "ENC-001-0"


def test_bb_microbiology_dr_hai_identifier_coexists_with_structural_key() -> None:
    culture = _sample_culture()
    culture["hai_event_id"] = "HAI-EVENT-99"
    ctx = _mb_ctx([culture])
    resources = _bb_microbiology(ctx)
    dr = next(r for r in resources if r["resourceType"] == "DiagnosticReport")
    systems = {i["system"] for i in dr.get("identifier", [])}
    assert "urn:clinosim:identifier:hai-event-id" in systems
    assert MB_DR_KEY_SYSTEM in systems


# === Coverage guard ===


def test_all_dr_ids_from_in_process_emit_are_opaque() -> None:
    """Drive both the microbiology + lab-panel emit paths end-to-end and
    assert every ``DiagnosticReport.id`` matches its opaque pattern for
    the family it belongs to. Radiology DR emit is covered by the
    dedicated `test_fhir_radiology_dr.py` file — this guard focuses on
    the two families we directly drive here."""
    ctx = _mb_ctx([_sample_culture(), _sample_culture()])
    resources = _bb_microbiology(ctx)
    mb_dr_ids = [r["id"] for r in resources if r["resourceType"] == "DiagnosticReport"]
    assert mb_dr_ids
    for rid in mb_dr_ids:
        assert _OPAQUE_MB_DR_PATTERN.match(rid), f"non-opaque mb DR id leaked: {rid!r}"

    # Lab-panel DR direct build.
    group = _GroupedPanel(panel_name="CBC", bucket="2026-05-12", obs_idxs=[0, 1, 2, 3])
    lab_dr = build_dr_resource(group, "P", "ENC-1", "US", None, None, 0)
    assert _OPAQUE_LAB_PANEL_DR_PATTERN.match(lab_dr["id"])
