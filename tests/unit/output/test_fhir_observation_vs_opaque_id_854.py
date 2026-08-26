"""Issue #854 Bucket A row 4 (PR-obs-vs): vs / gcs / news2 Observation opaque id
+ identifier round-trip.

Extends the opaque-id pattern (PR #357 → #863 → #867 → #868 → #869 → #878)
to stand-alone vital-sign scoring Observations. Three id-prefix families
migrate in this PR:

* ``vs-*`` (~827k records on JP p=10000 s500): per-parameter vitals
  (heart-rate / temperature / spo2 / respiratory-rate), the BP-panel
  consolidated Observation, the AVPU ``loc`` Observation, and the
  supplemental-oxygen ``o2`` Observation. All 4 emit sites in
  ``labs/observations.py`` funnel through ``_resolve_vital_sign_observation_id``.
* ``gcs-*`` (~212k records): Glasgow Coma Scale total.
* ``news2-*`` (~212k records): NEWS2 score.

Post-#854 every ``vs-*`` id is ``vs-<12hex>`` (15 chars, fixed);
``gcs-<12hex>`` (16 chars); ``news2-<12hex>`` (18 chars). The compound
structural key ``{encounter_id or patient_id}-{index:04d}-{suffix}`` (vs)
or ``{enc or patient_id}-{i}`` (gcs/news2) is preserved on
``Observation.identifier[]`` under the per-family
``VITAL_SIGN_OBSERVATION_KEY_SYSTEM`` / ``GCS_SCORE_KEY_SYSTEM`` /
``NEWS2_SCORE_KEY_SYSTEM`` so consumers recover the source-path metadata.

All three families are stand-alone — no cross-ref cascade — so this file
covers resolver contract, per-family emit shape, and identifier-round-trip
only. The reference-integrity guard that PR #878 (lab Observation) needed
has no analogue here.
"""

from __future__ import annotations

import re
from types import SimpleNamespace

import pytest

from clinosim.modules.output.fhir_r4.labs.observations import (
    VITAL_SIGN_OBSERVATION_ID_PREFIX,
    VITAL_SIGN_OBSERVATION_KEY_SYSTEM,
    _build_vital_observations,
    _resolve_vital_sign_observation_id,
)
from clinosim.modules.output.fhir_r4.procedures.nursing import (
    GCS_SCORE_ID_PREFIX,
    GCS_SCORE_KEY_SYSTEM,
    NEWS2_SCORE_ID_PREFIX,
    NEWS2_SCORE_KEY_SYSTEM,
    _bb_nursing_observations,
    _resolve_gcs_score_id,
    _resolve_news2_score_id,
)

pytestmark = pytest.mark.unit


_OPAQUE_VS_PATTERN = re.compile(r"^vs-[0-9a-f]{12}$")
_OPAQUE_GCS_PATTERN = re.compile(r"^gcs-[0-9a-f]{12}$")
_OPAQUE_NEWS2_PATTERN = re.compile(r"^news2-[0-9a-f]{12}$")


# === Resolver contracts — direct helpers ===


def test_resolve_vital_sign_observation_id_opaque_shape() -> None:
    """Fixed 15 chars: ``vs-`` (3) + 12 hex."""
    result = _resolve_vital_sign_observation_id("ENC-POP-000012-351553611449-0105-heart-rate")
    assert _OPAQUE_VS_PATTERN.match(result), f"got {result!r}"
    assert len(result) == 15


def test_resolve_gcs_score_id_opaque_shape() -> None:
    """Fixed 16 chars: ``gcs-`` (4) + 12 hex."""
    result = _resolve_gcs_score_id("ENC-POP-000106-377339127727-297")
    assert _OPAQUE_GCS_PATTERN.match(result), f"got {result!r}"
    assert len(result) == 16


def test_resolve_news2_score_id_opaque_shape() -> None:
    """Fixed 18 chars: ``news2-`` (6) + 12 hex."""
    result = _resolve_news2_score_id("ENC-POP-000106-377339127727-297")
    assert _OPAQUE_NEWS2_PATTERN.match(result), f"got {result!r}"
    assert len(result) == 18


def test_all_three_resolvers_are_deterministic() -> None:
    """Same structural key → same opaque id, across all three resolvers."""
    key = "ENC-abc-0001-heart-rate"
    assert _resolve_vital_sign_observation_id(key) == _resolve_vital_sign_observation_id(key)
    assert _resolve_gcs_score_id(key) == _resolve_gcs_score_id(key)
    assert _resolve_news2_score_id(key) == _resolve_news2_score_id(key)


def test_vs_and_gcs_and_news2_produce_distinct_ids_from_same_key() -> None:
    """Distinct prefixes ensure the three families' opaque id spaces do not collide."""
    key = "ENC-abc-0001"
    vs_id = _resolve_vital_sign_observation_id(key)
    gcs_id = _resolve_gcs_score_id(key)
    news2_id = _resolve_news2_score_id(key)
    assert {vs_id, gcs_id, news2_id} == {vs_id, gcs_id, news2_id}
    assert vs_id.startswith("vs-")
    assert gcs_id.startswith("gcs-")
    assert news2_id.startswith("news2-")


def test_key_system_uris() -> None:
    assert VITAL_SIGN_OBSERVATION_KEY_SYSTEM == "urn:clinosim:identifier:vital-sign-observation-key"
    assert GCS_SCORE_KEY_SYSTEM == "urn:clinosim:identifier:gcs-score-observation-key"
    assert NEWS2_SCORE_KEY_SYSTEM == "urn:clinosim:identifier:news2-score-observation-key"


def test_id_prefix_constants() -> None:
    assert VITAL_SIGN_OBSERVATION_ID_PREFIX == "vs-"
    assert GCS_SCORE_ID_PREFIX == "gcs-"
    assert NEWS2_SCORE_ID_PREFIX == "news2-"


# === _build_vital_observations — 4 emit paths ===


def _vs_record(**overrides) -> dict:
    """Minimal vital-signs record with all common fields; overrides tweak per-test."""
    base = {
        "heart_rate": 78,
        "temperature_celsius": 37.0,
        "respiratory_rate": 16,
        "spo2_pct": 97,
        "timestamp": "2026-05-12T14:28:38",
    }
    base.update(overrides)
    return base


def test_build_vital_observations_per_param_id_opaque_us() -> None:
    """Every emitted vs Observation carries an opaque ``vs-<12hex>`` id + a
    round-trip identifier under :data:`VITAL_SIGN_OBSERVATION_KEY_SYSTEM`.
    Post-#854 the id no longer ends in the ``heart-rate`` / ``bp-panel`` /
    ``loc`` / ``o2`` suffix, so tests must not filter by suffix — they
    must inspect the recovered structural key on ``identifier[]`` instead."""
    entries = _build_vital_observations(
        _vs_record(), patient_id="POP-000002", index=5, country="US", encounter_id="ENC-001"
    )
    assert entries, "expected per-parameter vs Observations"
    for e in entries:
        r = e["resource"]
        assert _OPAQUE_VS_PATTERN.match(r["id"]), f"non-opaque vs id: {r['id']!r}"
        idents = r.get("identifier") or []
        vs_key_idents = [i for i in idents if i.get("system") == VITAL_SIGN_OBSERVATION_KEY_SYSTEM]
        assert len(vs_key_idents) == 1, f"expected exactly 1 vs-key identifier, got {idents!r}"
        assert vs_key_idents[0]["value"].startswith("ENC-001-0005-")


def test_build_vital_observations_bp_panel_present_when_both_systolic_and_diastolic() -> None:
    """BP-panel emit fires only when both systolic + diastolic present; id is opaque."""
    vs = _vs_record(systolic_bp=120, diastolic_bp=78)
    entries = _build_vital_observations(vs, patient_id="POP-000002", index=5, country="US", encounter_id="ENC-001")
    bp_panels = [
        e["resource"] for e in entries if e["resource"].get("code", {}).get("coding", [{}])[0].get("code") == "85354-9"
    ]
    assert len(bp_panels) == 1
    bp = bp_panels[0]
    assert _OPAQUE_VS_PATTERN.match(bp["id"]), f"non-opaque bp-panel id: {bp['id']!r}"
    # Identifier round-trip carries the pre-#854 structural key.
    vs_key_idents = [i for i in bp.get("identifier", []) if i.get("system") == VITAL_SIGN_OBSERVATION_KEY_SYSTEM]
    assert len(vs_key_idents) == 1
    assert vs_key_idents[0]["value"] == "ENC-001-0005-bp-panel"


def test_build_vital_observations_loc_present_when_consciousness_level_set() -> None:
    vs = _vs_record(consciousness_level="A")
    entries = _build_vital_observations(vs, patient_id="POP-000002", index=5, country="JP", encounter_id="ENC-001")
    locs = [
        e["resource"] for e in entries if e["resource"].get("code", {}).get("coding", [{}])[0].get("code") == "80288-4"
    ]
    assert len(locs) == 1
    loc = locs[0]
    assert _OPAQUE_VS_PATTERN.match(loc["id"]), f"non-opaque loc id: {loc['id']!r}"
    vs_key_idents = [i for i in loc.get("identifier", []) if i.get("system") == VITAL_SIGN_OBSERVATION_KEY_SYSTEM]
    assert len(vs_key_idents) == 1
    assert vs_key_idents[0]["value"] == "ENC-001-0005-loc"


def test_build_vital_observations_o2_present_when_on_supplemental_oxygen() -> None:
    vs = _vs_record(
        on_supplemental_oxygen=True,
        oxygen_flow_rate_lpm=3,
        oxygen_delivery_device="nasal_cannula",
    )
    entries = _build_vital_observations(vs, patient_id="POP-000002", index=5, country="US", encounter_id="ENC-001")
    o2s = [
        e["resource"] for e in entries if e["resource"].get("code", {}).get("coding", [{}])[0].get("code") == "3151-8"
    ]
    assert len(o2s) == 1
    o2 = o2s[0]
    assert _OPAQUE_VS_PATTERN.match(o2["id"]), f"non-opaque o2 id: {o2['id']!r}"
    vs_key_idents = [i for i in o2.get("identifier", []) if i.get("system") == VITAL_SIGN_OBSERVATION_KEY_SYSTEM]
    assert len(vs_key_idents) == 1
    assert vs_key_idents[0]["value"] == "ENC-001-0005-o2"


def test_build_vital_observations_falls_back_to_patient_id_when_encounter_missing() -> None:
    """Structural key uses patient_id when encounter_id is empty (pre-#854 semantics)."""
    entries = _build_vital_observations(_vs_record(), patient_id="POP-000002", index=5, country="US", encounter_id="")
    for e in entries:
        idents = e["resource"].get("identifier", [])
        vs_key_idents = [i for i in idents if i.get("system") == VITAL_SIGN_OBSERVATION_KEY_SYSTEM]
        assert len(vs_key_idents) == 1
        # patient_id fallback ⇒ structural key body starts with the patient id.
        assert vs_key_idents[0]["value"].startswith("POP-000002-0005-"), (
            f"structural key did not fall back to patient_id: {vs_key_idents[0]!r}"
        )


def test_build_vital_observations_same_input_produces_same_id() -> None:
    """Byte-diff invariant."""
    a = _build_vital_observations(_vs_record(), patient_id="POP-000002", index=5, country="US", encounter_id="ENC-001")
    b = _build_vital_observations(_vs_record(), patient_id="POP-000002", index=5, country="US", encounter_id="ENC-001")
    assert [e["resource"]["id"] for e in a] == [e["resource"]["id"] for e in b]


# === _bb_nursing_observations — gcs / news2 emit path ===


def _make_nursing_ctx(vital_signs: list, *, encounter_id: str = "ENC-001", country: str = "US") -> SimpleNamespace:
    return SimpleNamespace(
        record={
            "patient": {"patient_id": "POP-000002"},
            "vital_signs": vital_signs,
            "encounters": [{"primary_nurse_id": "STAFF-N-001"}],
        },
        country=country,
        roster_map={},
        hospital_config={},
        patient_data={"patient_id": "POP-000002"},
        patient_id="POP-000002",
        primary_enc_id=encounter_id,
    )


def test_bb_nursing_gcs_id_is_opaque_and_carries_identifier() -> None:
    ctx = _make_nursing_ctx([{"timestamp": "2026-05-12T14:28:38", "gcs_score": 15, "measured_by": "STAFF-N-001"}])
    resources = _bb_nursing_observations(ctx)
    gcs_obs = [r for r in resources if r["id"].startswith("gcs-")]
    assert len(gcs_obs) == 1
    r = gcs_obs[0]
    assert _OPAQUE_GCS_PATTERN.match(r["id"]), f"non-opaque gcs id: {r['id']!r}"
    idents = r.get("identifier") or []
    gcs_key_idents = [i for i in idents if i.get("system") == GCS_SCORE_KEY_SYSTEM]
    assert len(gcs_key_idents) == 1
    assert gcs_key_idents[0]["value"] == "ENC-001-0"


def test_bb_nursing_news2_id_is_opaque_and_carries_identifier() -> None:
    ctx = _make_nursing_ctx([{"timestamp": "2026-05-12T14:28:38", "news2_score": 2, "measured_by": "STAFF-N-001"}])
    resources = _bb_nursing_observations(ctx)
    news2_obs = [r for r in resources if r["id"].startswith("news2-")]
    assert len(news2_obs) == 1
    r = news2_obs[0]
    assert _OPAQUE_NEWS2_PATTERN.match(r["id"]), f"non-opaque news2 id: {r['id']!r}"
    idents = r.get("identifier") or []
    news2_key_idents = [i for i in idents if i.get("system") == NEWS2_SCORE_KEY_SYSTEM]
    assert len(news2_key_idents) == 1
    assert news2_key_idents[0]["value"] == "ENC-001-0"


def test_bb_nursing_multiple_vital_signs_produce_distinct_opaque_ids() -> None:
    """Two vital-signs entries → two distinct opaque scoring ids per family."""
    ctx = _make_nursing_ctx(
        [
            {"timestamp": "2026-05-12T14:28:38", "gcs_score": 15, "news2_score": 2, "measured_by": "S1"},
            {"timestamp": "2026-05-12T20:00:00", "gcs_score": 14, "news2_score": 3, "measured_by": "S1"},
        ]
    )
    resources = _bb_nursing_observations(ctx)
    gcs_ids = [r["id"] for r in resources if r["id"].startswith("gcs-")]
    news2_ids = [r["id"] for r in resources if r["id"].startswith("news2-")]
    assert len(gcs_ids) == 2 and len(set(gcs_ids)) == 2
    assert len(news2_ids) == 2 and len(set(news2_ids)) == 2


def test_bb_nursing_falls_back_to_patient_id_when_encounter_missing() -> None:
    ctx = _make_nursing_ctx(
        [{"timestamp": "2026-05-12T14:28:38", "gcs_score": 15, "news2_score": 2, "measured_by": "S1"}],
        encounter_id="",
    )
    resources = _bb_nursing_observations(ctx)
    for r in resources:
        if r["id"].startswith("gcs-"):
            idents = [i for i in r.get("identifier", []) if i.get("system") == GCS_SCORE_KEY_SYSTEM]
            assert idents and idents[0]["value"] == "POP-000002-0"
        elif r["id"].startswith("news2-"):
            idents = [i for i in r.get("identifier", []) if i.get("system") == NEWS2_SCORE_KEY_SYSTEM]
            assert idents and idents[0]["value"] == "POP-000002-0"


# === Coverage guard — no compound id shape leaks back in ===


def test_all_vs_gcs_news2_ids_from_in_process_emit_are_opaque() -> None:
    """Fixture drives all 6 emit sites (per-param + bp-panel + loc + o2 in
    observations.py, gcs + news2 in nursing.py) and asserts every emitted
    ``vs-*`` / ``gcs-*`` / ``news2-*`` id matches its opaque pattern.
    Guards against a future emit-path addition that silently re-introduces
    the compound id (e.g. a new writer that inlines ``f"vs-{enc}-..."``
    instead of calling the resolver)."""
    vs = _vs_record(
        systolic_bp=120,
        diastolic_bp=78,
        consciousness_level="A",
        on_supplemental_oxygen=True,
        oxygen_flow_rate_lpm=3,
        oxygen_delivery_device="nasal_cannula",
        gcs_score=15,
        news2_score=2,
    )
    entries = _build_vital_observations(vs, patient_id="POP-000002", index=5, country="JP", encounter_id="ENC-001")
    vs_ids = [e["resource"]["id"] for e in entries if e["resource"]["id"].startswith("vs-")]
    assert vs_ids, "fixture should emit at least one vs Observation"
    for rid in vs_ids:
        assert _OPAQUE_VS_PATTERN.match(rid), f"non-opaque vs id leaked: {rid!r}"

    ctx = _make_nursing_ctx([vs])
    resources = _bb_nursing_observations(ctx)
    scoring_ids = [r["id"] for r in resources if r["id"].startswith(("gcs-", "news2-"))]
    assert scoring_ids, "fixture should emit gcs + news2 Observations"
    for rid in scoring_ids:
        if rid.startswith("gcs-"):
            assert _OPAQUE_GCS_PATTERN.match(rid), f"non-opaque gcs id leaked: {rid!r}"
        else:
            assert _OPAQUE_NEWS2_PATTERN.match(rid), f"non-opaque news2 id leaked: {rid!r}"
