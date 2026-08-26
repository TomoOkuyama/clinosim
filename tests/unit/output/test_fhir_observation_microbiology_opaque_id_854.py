"""Issue #854 Bucket A row 4 (PR-obs-microbiology): mb-org / mb-sus
Observation opaque id + identifier round-trip + DR.result[] cross-ref
byte-consistency.

Extends the opaque-id pattern (PR #357 → #863 → #867 → #868 → #869 →
#878 [lab] → #879 [vs/gcs/news2] → #880 [stand-alones]) to the last
Observation families remaining in Bucket A row 4:

    mb-org-* (organism isolate)              → mb-org-<12hex> (19 chars, fixed)
    mb-sus-* (per-antibiotic susceptibility) → mb-sus-<12hex> (19 chars, fixed)

Reference-integrity guard: ``DiagnosticReport.result[]`` references both
by opaque id — funneled through the same ``_resolve_mb_org_id`` /
``_resolve_mb_sus_id`` resolvers the writer uses so the reference edge
stays byte-consistent with the writer by construction. A drift here
would detach every microbiology DR from its component isolate /
susceptibility Observations without any FHIR-schema error — invisible to
validators, catastrophic for consumers (same silent-no-op class the lab
PR #878 guarded against).

Structural keys — always the pre-#854 id body without the prefix — are:

    mb-org: ``{enc or patient_id}-{i}``
    mb-sus: ``{enc or patient_id}-{i}-{j}``  where ``j`` is the 0-based
            index in the culture's ``susceptibilities`` list.
"""

from __future__ import annotations

import re
from types import SimpleNamespace

import pytest

from clinosim.modules.output.fhir_r4.labs.microbiology import (
    HAI_EVENT_ID_SYSTEM,
    MB_ORG_ID_PREFIX,
    MB_ORG_KEY_SYSTEM,
    MB_SUS_ID_PREFIX,
    MB_SUS_KEY_SYSTEM,
    _bb_microbiology,
    _resolve_mb_org_id,
    _resolve_mb_sus_id,
)

pytestmark = pytest.mark.unit


_OPAQUE_MB_ORG_PATTERN = re.compile(r"^mb-org-[0-9a-f]{12}$")
_OPAQUE_MB_SUS_PATTERN = re.compile(r"^mb-sus-[0-9a-f]{12}$")


# === Resolver contracts ===


def test_resolve_mb_org_id_opaque_shape() -> None:
    """Fixed 19 chars: ``mb-org-`` (7) + 12 hex."""
    result = _resolve_mb_org_id("ENC-POP-000012-abc-0")
    assert _OPAQUE_MB_ORG_PATTERN.match(result), f"got {result!r}"
    assert len(result) == 19


def test_resolve_mb_sus_id_opaque_shape() -> None:
    """Fixed 19 chars: ``mb-sus-`` (7) + 12 hex."""
    result = _resolve_mb_sus_id("ENC-POP-000012-abc-0-0")
    assert _OPAQUE_MB_SUS_PATTERN.match(result), f"got {result!r}"
    assert len(result) == 19


def test_resolvers_are_deterministic() -> None:
    key = "ENC-POP-000012-abc-0"
    assert _resolve_mb_org_id(key) == _resolve_mb_org_id(key)
    assert _resolve_mb_sus_id(key) == _resolve_mb_sus_id(key)


def test_mb_org_and_mb_sus_distinct_ids_from_same_key() -> None:
    """Distinct prefixes ensure the two families' opaque id spaces do not collide."""
    key = "ENC-abc-0"
    assert _resolve_mb_org_id(key) != _resolve_mb_sus_id(key)


def test_key_system_uris() -> None:
    assert MB_ORG_KEY_SYSTEM == "urn:clinosim:identifier:mb-organism-observation-key"
    assert MB_SUS_KEY_SYSTEM == "urn:clinosim:identifier:mb-susceptibility-observation-key"


def test_id_prefix_constants() -> None:
    assert MB_ORG_ID_PREFIX == "mb-org-"
    assert MB_SUS_ID_PREFIX == "mb-sus-"


# === Emit-path smoke tests ===


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
        "susceptibilities": [
            {"antibiotic_loinc": "18866-6", "interpretation": "S"},
            {"antibiotic_loinc": "18928-4", "interpretation": "R"},
        ],
    }


def _find_by_prefix(resources: list[dict], prefix: str) -> list[dict]:
    return [r for r in resources if r.get("id", "").startswith(prefix)]


def test_bb_microbiology_mb_org_id_is_opaque_with_identifier() -> None:
    ctx = _mb_ctx([_sample_culture()])
    resources = _bb_microbiology(ctx)
    mb_orgs = _find_by_prefix(resources, "mb-org-")
    assert len(mb_orgs) == 1
    r = mb_orgs[0]
    assert _OPAQUE_MB_ORG_PATTERN.match(r["id"]), f"non-opaque mb-org id: {r['id']!r}"
    key_idents = [i for i in r.get("identifier", []) if i.get("system") == MB_ORG_KEY_SYSTEM]
    assert len(key_idents) == 1
    assert key_idents[0]["value"] == "ENC-001-0"


def test_bb_microbiology_mb_sus_id_is_opaque_with_identifier() -> None:
    ctx = _mb_ctx([_sample_culture()])
    resources = _bb_microbiology(ctx)
    mb_suses = _find_by_prefix(resources, "mb-sus-")
    assert len(mb_suses) == 2  # one per antibiotic
    for j, r in enumerate(mb_suses):
        assert _OPAQUE_MB_SUS_PATTERN.match(r["id"]), f"non-opaque mb-sus id: {r['id']!r}"
        key_idents = [i for i in r.get("identifier", []) if i.get("system") == MB_SUS_KEY_SYSTEM]
        assert len(key_idents) == 1
        assert key_idents[0]["value"] == f"ENC-001-0-{j}"


def test_bb_microbiology_hai_identifier_still_prepended_when_present() -> None:
    """HAI event round-trip identifier must survive alongside the new structural-key
    identifier — the two participate in different downstream consumers."""
    culture = _sample_culture()
    culture["hai_event_id"] = "HAI-EVENT-42"
    ctx = _mb_ctx([culture])
    resources = _bb_microbiology(ctx)
    for r in _find_by_prefix(resources, "mb-org-") + _find_by_prefix(resources, "mb-sus-"):
        systems = {i.get("system") for i in r.get("identifier", [])}
        assert HAI_EVENT_ID_SYSTEM in systems, f"HAI identifier missing from {r['id']!r}"
        assert MB_ORG_KEY_SYSTEM in systems or MB_SUS_KEY_SYSTEM in systems, (
            f"structural-key identifier missing from {r['id']!r}"
        )


def test_bb_microbiology_dr_result_references_use_opaque_ids() -> None:
    """The critical byte-consistency invariant: ``DR.result[]`` references
    resolve to Observations that exist in the emit set — 0 dangling."""
    ctx = _mb_ctx([_sample_culture()])
    resources = _bb_microbiology(ctx)
    obs_ids = {r["id"] for r in resources if r["resourceType"] == "Observation"}
    dr_refs = []
    for r in resources:
        if r["resourceType"] == "DiagnosticReport":
            for entry in r.get("result", []):
                dr_refs.append(entry.get("reference", ""))
    assert dr_refs, "expected DR.result[] populated"
    dangling = [ref for ref in dr_refs if ref.removeprefix("Observation/") not in obs_ids]
    assert not dangling, f"DR.result[] references detached from Observation set: {dangling}"


def test_bb_microbiology_multiple_cultures_produce_distinct_opaque_ids() -> None:
    ctx = _mb_ctx([_sample_culture(), _sample_culture()])
    resources = _bb_microbiology(ctx)
    mb_org_ids = [r["id"] for r in _find_by_prefix(resources, "mb-org-")]
    mb_sus_ids = [r["id"] for r in _find_by_prefix(resources, "mb-sus-")]
    # 2 cultures × 1 organism each = 2 mb-org; × 2 susceptibilities = 4 mb-sus.
    assert len(mb_org_ids) == 2 and len(set(mb_org_ids)) == 2
    assert len(mb_sus_ids) == 4 and len(set(mb_sus_ids)) == 4


def test_bb_microbiology_same_input_reproduces_same_id() -> None:
    """Byte-diff invariant."""
    ctx = _mb_ctx([_sample_culture()])
    a = _bb_microbiology(ctx)
    b = _bb_microbiology(ctx)
    a_ids = [r["id"] for r in a if r["resourceType"] == "Observation"]
    b_ids = [r["id"] for r in b if r["resourceType"] == "Observation"]
    assert a_ids == b_ids


# === Coverage guard ===


def test_all_mb_ids_from_in_process_emit_are_opaque() -> None:
    """Emit two cultures with multiple susceptibilities and assert every emitted
    ``mb-org-*`` / ``mb-sus-*`` id matches its opaque pattern. Guards against
    a future emit-path addition that silently re-introduces the compound id."""
    ctx = _mb_ctx([_sample_culture(), _sample_culture()])
    resources = _bb_microbiology(ctx)
    mb_ids = [r["id"] for r in resources if r["id"].startswith(("mb-org-", "mb-sus-"))]
    assert mb_ids, "fixture should emit at least one mb Observation"
    for rid in mb_ids:
        pattern = _OPAQUE_MB_ORG_PATTERN if rid.startswith("mb-org-") else _OPAQUE_MB_SUS_PATTERN
        assert pattern.match(rid), f"non-opaque mb id leaked: {rid!r}"
