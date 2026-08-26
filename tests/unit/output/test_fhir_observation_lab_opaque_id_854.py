"""Issue #854 Bucket A row 4 (PR-obs-lab): lab Observation opaque id +
identifier round-trip + DR.result[] cross-ref byte-consistency.

Extends the opaque-id pattern (PR #357 → #863 → #867 → #868 → #869) to lab
``Observation``. Pre-#854 ``Observation.id`` embedded ``{encounter_id}-{idx:04d}``
after a ``lab-`` prefix (33+ chars, silently coupled to Order-list position).
Post-#854 every lab Observation emits ``lab-<12hex>`` (16 chars, fixed) and
carries the pre-#854 compound as ``identifier[]`` under
:data:`LAB_OBSERVATION_KEY_SYSTEM` for round-trip.

The critical byte-consistency invariant this file guards:

* ``Observation.id`` (writer: ``observations._build_lab_observation``)
* ``DiagnosticReport.result[].reference`` (writer:
  ``diagnostic_report.build_dr_resource``)

both funnel through the same resolver so a future format change ripples
through one call site (PR-90 silent-no-op defense). A drift here would
detach every DR from its component Observations without any FHIR-schema
error — invisible to validators, catastrophic for consumers.
"""

from __future__ import annotations

import re

import pytest

from clinosim.modules.output.fhir_r4.labs.diagnostic_report import (
    LAB_OBSERVATION_ID_PREFIX,
    LAB_OBSERVATION_KEY_SYSTEM,
    _GroupedPanel,
    _lab_observation_structural_key,
    _resolve_lab_observation_id,
    build_dr_resource,
    lab_observation_id,
)
from clinosim.modules.output.fhir_r4.labs.observations import _bb_labs, _build_lab_observation
from clinosim.modules.output.fhir_r4.lib.common import BundleContext

pytestmark = pytest.mark.unit


_OPAQUE_LAB_OBS_PATTERN = re.compile(r"^lab-[0-9a-f]{12}$")


# === _resolve_lab_observation_id — direct helper ===


def test_resolve_lab_observation_id_opaque_shape() -> None:
    """Fixed 16 chars: ``lab-`` (4) + 12 hex."""
    result = _resolve_lab_observation_id("ENC-POP-000003-028876635735-0000")
    assert _OPAQUE_LAB_OBS_PATTERN.match(result), f"got {result!r}"
    assert len(result) == 16


def test_resolve_lab_observation_id_is_deterministic() -> None:
    key = "ENC-POP-000003-028876635735-0042"
    assert _resolve_lab_observation_id(key) == _resolve_lab_observation_id(key)


def test_resolve_lab_observation_id_distinguishes_encounters_and_indices() -> None:
    """Distinct (encounter, idx) tuples yield distinct opaque ids."""
    keys = [
        _lab_observation_structural_key("ENC-POP-000003-028876635735", 0),
        _lab_observation_structural_key("ENC-POP-000003-028876635735", 1),
        _lab_observation_structural_key("ENC-POP-000004-346099516150", 0),
    ]
    ids = {_resolve_lab_observation_id(k) for k in keys}
    assert len(ids) == 3


def test_lab_observation_key_system_uri() -> None:
    assert LAB_OBSERVATION_KEY_SYSTEM == "urn:clinosim:identifier:lab-observation-key"


def test_lab_observation_id_prefix_constant() -> None:
    assert LAB_OBSERVATION_ID_PREFIX == "lab-"


def test_lab_observation_structural_key_shape() -> None:
    """Structural key = pre-#854 id body (without ``lab-`` prefix)."""
    assert _lab_observation_structural_key("ENC-POP-000003-028876635735", 42) == ("ENC-POP-000003-028876635735-0042")


def test_lab_observation_id_wraps_structural_key_then_resolver() -> None:
    """The convenience wrapper composes the two helpers verbatim — the
    resolver's output must match the manual composition byte-for-byte so
    the writer / reader stay coupled through one call site."""
    enc, idx = "ENC-001", 7
    direct = lab_observation_id(enc, idx)
    manual = _resolve_lab_observation_id(_lab_observation_structural_key(enc, idx))
    assert direct == manual


# === _build_lab_observation — emit path ===


def _lab_order(*, lab_name: str, value: float, encounter_id: str) -> dict:
    """Minimal lab Order fixture — matches what observations.py accepts."""
    return {
        "order_type": "lab",
        "order_id": f"ORD-{lab_name}-0",
        "order_code": lab_name,
        "display_name": lab_name,
        "encounter_id": encounter_id,
        "result": {
            "lab_name": lab_name,
            "value": value,
            "unit": "g/dL",
            "result_datetime": "2026-05-12T14:28:38",
        },
    }


def test_build_lab_observation_id_is_opaque_us() -> None:
    order = _lab_order(lab_name="Hb", value=13.5, encounter_id="ENC-001")
    resource = _build_lab_observation(
        order,
        order["result"],
        patient_id="POP-000002",
        index=3,
        country="US",
        patient_sex="F",
        encounter_id="ENC-001",
    )
    assert resource is not None
    assert _OPAQUE_LAB_OBS_PATTERN.match(resource["id"]), f"got {resource['id']!r}"


def test_build_lab_observation_id_is_opaque_jp() -> None:
    order = _lab_order(lab_name="Hb", value=13.5, encounter_id="ENC-001")
    resource = _build_lab_observation(
        order,
        order["result"],
        patient_id="POP-000002",
        index=3,
        country="JP",
        patient_sex="F",
        encounter_id="ENC-001",
    )
    assert resource is not None
    assert _OPAQUE_LAB_OBS_PATTERN.match(resource["id"]), f"got {resource['id']!r}"


def test_build_lab_observation_carries_structural_key_identifier() -> None:
    """The compound ``{encounter_id}-{idx:04d}`` is preserved verbatim on
    ``identifier[]`` under :data:`LAB_OBSERVATION_KEY_SYSTEM`."""
    order = _lab_order(lab_name="Hb", value=13.5, encounter_id="ENC-001")
    resource = _build_lab_observation(
        order,
        order["result"],
        patient_id="POP-000002",
        index=3,
        country="JP",
        patient_sex="F",
        encounter_id="ENC-001",
    )
    assert resource is not None
    idents = resource.get("identifier") or []
    structural = [i for i in idents if i.get("system") == LAB_OBSERVATION_KEY_SYSTEM]
    assert len(structural) == 1
    assert structural[0]["value"] == "ENC-001-0003"


def test_build_lab_observation_same_key_reproduces_same_id() -> None:
    """Byte-diff invariant: two independent builds from the same fixture agree."""
    order = _lab_order(lab_name="Hb", value=13.5, encounter_id="ENC-001")
    a = _build_lab_observation(
        order,
        order["result"],
        patient_id="POP-000002",
        index=0,
        country="JP",
        patient_sex="F",
        encounter_id="ENC-001",
    )
    b = _build_lab_observation(
        order,
        order["result"],
        patient_id="POP-000002",
        index=0,
        country="JP",
        patient_sex="F",
        encounter_id="ENC-001",
    )
    assert a is not None and b is not None
    assert a["id"] == b["id"]


# === DR.result[] cross-ref byte-consistency ===


def test_dr_result_reference_matches_observation_id_writer() -> None:
    """The DR.result[].reference MUST equal ``Observation/{writer-emitted id}``
    for the same (encounter, idx). A drift here is the PR-90 silent-no-op
    class — no FHIR validator would catch it, but every DR would detach
    from its component Observations."""
    encounter_id = "ENC-001"
    idxs = [0, 1, 2, 3]
    group = _GroupedPanel(panel_name="CBC", bucket="2026-05-12", obs_idxs=idxs)
    dr = build_dr_resource(
        group,
        patient_id="POP-000002",
        encounter_id=encounter_id,
        country="US",
        performer_ref=None,
        issued=None,
        seq=0,
    )
    # For each idx, the DR reference must equal what the Observation writer
    # would produce (via the same resolver).
    for i, idx in enumerate(idxs):
        expected_ref = f"Observation/{lab_observation_id(encounter_id, idx)}"
        assert dr["result"][i]["reference"] == expected_ref


def test_bb_labs_and_dr_result_agree_end_to_end() -> None:
    """End-to-end byte-consistency: emit the Observation via ``_bb_labs`` and
    the DR via ``build_dr_resource`` on the same order list, then verify
    every DR.result[] reference resolves to an Observation in the emit set."""
    encounter_id = "ENC-END2END"
    orders = [
        _lab_order(lab_name="WBC", value=8.2, encounter_id=encounter_id),
        _lab_order(lab_name="Hb", value=13.5, encounter_id=encounter_id),
        _lab_order(lab_name="Hct", value=40.1, encounter_id=encounter_id),
        _lab_order(lab_name="Plt", value=210, encounter_id=encounter_id),
    ]
    ctx = _make_bundle_context(orders, encounter_id=encounter_id, country="US")
    obs_resources = _bb_labs(ctx)
    obs_ids = {r["id"] for r in obs_resources}

    # Every emitted Observation.id must have opaque shape.
    for r in obs_resources:
        assert _OPAQUE_LAB_OBS_PATTERN.match(r["id"]), f"non-opaque id emitted: {r['id']!r}"

    # DR.result[] references (via build_dr_resource on the same input) must
    # resolve into the same opaque id set — zero dangling refs.
    from clinosim.modules.output.fhir_r4.labs.diagnostic_report import build_lab_panel_reports

    drs = build_lab_panel_reports(ctx)
    assert drs, "expected at least one DR from a full CBC input"
    dr_refs = [ref["reference"] for dr in drs for ref in dr.get("result", [])]
    assert dr_refs, "expected DR.result[] populated"
    dangling = [ref for ref in dr_refs if ref.removeprefix("Observation/") not in obs_ids]
    assert not dangling, f"DR.result[] references detached from Observation set: {dangling}"


def _make_bundle_context(orders: list, *, encounter_id: str, country: str) -> BundleContext:
    return BundleContext(
        record={
            "patient": {"patient_id": "POP-000002"},
            "orders": orders,
        },
        country=country,
        roster_map={},
        hospital_config={},
        patient_data={"patient_id": "POP-000002"},
        patient_id="POP-000002",
        is_readmission=False,
        prior_encounter_id=None,
        primary_dx_code="",
        admit_dx_code="",
        admit_dx_system="",
        primary_enc_id=encounter_id,
        patient_sex="F",
    )


# === Coverage-guard: every lab-* Observation.id in a p=200 emit is opaque ===


def test_all_lab_observation_ids_are_opaque_shape() -> None:
    """Scan a small in-process emit and assert every Observation whose ``.id``
    starts with ``lab-`` matches the opaque shape. Guards against a future
    emit-path addition that silently re-introduces the compound id (e.g.
    a new writer that inlines ``f"lab-{enc}-..."`` instead of calling the
    resolver)."""
    encounter_id = "ENC-COV"
    orders = [
        _lab_order(lab_name="WBC", value=8.2, encounter_id=encounter_id),
        _lab_order(lab_name="Hb", value=13.5, encounter_id=encounter_id),
        _lab_order(lab_name="Hct", value=40.1, encounter_id=encounter_id),
        _lab_order(lab_name="Plt", value=210, encounter_id=encounter_id),
        _lab_order(lab_name="AST", value=42, encounter_id=encounter_id),
        _lab_order(lab_name="ALT", value=38, encounter_id=encounter_id),
    ]
    ctx = _make_bundle_context(orders, encounter_id=encounter_id, country="JP")
    obs_resources = _bb_labs(ctx)
    lab_ids = [r["id"] for r in obs_resources if r["id"].startswith("lab-")]
    assert lab_ids, "fixture should emit at least one lab Observation"
    non_opaque = [rid for rid in lab_ids if not _OPAQUE_LAB_OBS_PATTERN.match(rid)]
    assert not non_opaque, f"non-opaque lab Observation.id leaked: {non_opaque[:3]}"
