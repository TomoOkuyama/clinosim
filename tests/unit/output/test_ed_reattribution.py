"""N-3 fix: ED bridge Encounter reattribution walker.

Sole routing trigger is doc_type (LOINC 34878-9 ED note / 54094-8 ED
triage note). Timestamp routing was explored and rejected — see the
module docstring for why.
"""

from __future__ import annotations

from types import SimpleNamespace

from clinosim.modules.output.fhir_r4.encounters.encounter import resolve_encounter_id
from clinosim.modules.output.fhir_r4.lib.ed_reattribution import (
    reattribute_encounter_to_ed_bridge,
)

# Issue #854 PR-encounter: cross-refs use the shared opaque resolver.
# Precompute the two references the walker matches / rewrites so tests
# work at the emit-format layer.
_IMP_CIF = "ENC-POP-000001-111"
_IMP_REF = f"Encounter/{resolve_encounter_id(_IMP_CIF)}"
_ED_REF = f"Encounter/{resolve_encounter_id(f'{_IMP_CIF}-ED')}"
_OTHER_REF = f"Encounter/{resolve_encounter_id('OTHER-ENC-999')}"


def _ctx_with_ed_imp(imp_id: str = _IMP_CIF):
    """Minimal ctx whose record has an ED-admitted IMP encounter."""
    record = {"encounters": [{"encounter_id": imp_id, "admit_source": "emd"}]}
    return SimpleNamespace(record=record)


def _ctx_without_ed(imp_id: str = _IMP_CIF):
    record = {"encounters": [{"encounter_id": imp_id, "admit_source": "outp"}]}
    return SimpleNamespace(record=record)


# ---- doc_type trigger (ED_NOTE, ED_TRIAGE_NOTE) -------------------------------


def test_ed_note_composition_rerouted_to_ed_bridge():
    """LOINC 34878-9 (ED note) on Composition → -ED."""
    ctx = _ctx_with_ed_imp()
    resource = {
        "resourceType": "Composition",
        "id": "comp-1",
        "type": {"coding": [{"system": "http://loinc.org", "code": "34878-9"}]},
        "encounter": {"reference": _IMP_REF},
    }
    reattribute_encounter_to_ed_bridge(resource, ctx)
    assert resource["encounter"]["reference"] == _ED_REF


def test_ed_triage_documentreference_top_level_encounter_rerouted():
    """LOINC 54094-8 with top-level `encounter` field → -ED."""
    ctx = _ctx_with_ed_imp()
    resource = {
        "resourceType": "DocumentReference",
        "id": "doc-1",
        "type": {"coding": [{"system": "http://loinc.org", "code": "54094-8"}]},
        "encounter": {"reference": _IMP_REF},
    }
    reattribute_encounter_to_ed_bridge(resource, ctx)
    assert resource["encounter"]["reference"] == _ED_REF


def test_ed_triage_documentreference_context_encounter_rerouted():
    """FHIR R4 DocumentReference emits encounter under context.encounter[]
    (not a top-level `encounter` field). Walker must rewrite the nested
    reference too — otherwise 22 ED_TRIAGE_NOTE per p=200 stay orphaned
    on IMP."""
    ctx = _ctx_with_ed_imp()
    resource = {
        "resourceType": "DocumentReference",
        "id": "doc-triage",
        "type": {"coding": [{"code": "54094-8"}]},
        "context": {
            "encounter": [{"reference": _IMP_REF}],
            "period": {"start": "2026-02-10T06:00:00+09:00"},
        },
    }
    reattribute_encounter_to_ed_bridge(resource, ctx)
    assert resource["context"]["encounter"][0]["reference"] == _ED_REF


def test_admission_hp_composition_stays_on_imp():
    """LOINC 34117-2 (H&P) — NOT an ED type, must stay on IMP even
    when timestamped at IMP admission (previous timestamp-based draft
    misrouted these because their date == ED window end)."""
    ctx = _ctx_with_ed_imp()
    resource = {
        "resourceType": "Composition",
        "id": "comp-hp",
        "type": {"coding": [{"code": "34117-2"}]},
        "date": "2026-02-10T08:37:00+09:00",
        "encounter": {"reference": _IMP_REF},
    }
    reattribute_encounter_to_ed_bridge(resource, ctx)
    assert resource["encounter"]["reference"] == _IMP_REF


def test_observation_stays_on_imp_regardless_of_timestamp():
    """Observation is not a routed type — timestamp doesn't matter."""
    ctx = _ctx_with_ed_imp()
    resource = {
        "resourceType": "Observation",
        "effectiveDateTime": "2026-02-10T06:00:00+09:00",  # would be "in ED window"
        "encounter": {"reference": _IMP_REF},
    }
    reattribute_encounter_to_ed_bridge(resource, ctx)
    assert resource["encounter"]["reference"] == _IMP_REF


def test_nursing_documentreference_stays_on_imp():
    """LOINC 34746-8 (nursing note) is not an ED type — must NOT route,
    even if its timestamp happens to land in the ED window. Regression
    guard for the pre-doc_type-only draft that misrouted nursing notes
    stamped 08:00 (before an 08:37 admission) to the -ED bridge."""
    ctx = _ctx_with_ed_imp()
    resource = {
        "resourceType": "DocumentReference",
        "type": {"coding": [{"code": "34746-8"}]},
        "context": {
            "encounter": [{"reference": _IMP_REF}],
            "period": {"start": "2026-02-10T08:00:00+09:00"},
        },
    }
    reattribute_encounter_to_ed_bridge(resource, ctx)
    assert resource["context"]["encounter"][0]["reference"] == _IMP_REF


# ---- gate conditions ----------------------------------------------------------


def test_no_op_when_not_ed_admission():
    """admit_source != emd → walker does nothing."""
    ctx = _ctx_without_ed()
    resource = {
        "resourceType": "Composition",
        "type": {"coding": [{"code": "34878-9"}]},  # would trigger if EMD
        "encounter": {"reference": _IMP_REF},
    }
    reattribute_encounter_to_ed_bridge(resource, ctx)
    # No -ED bridge exists for outpatient admits.
    assert resource["encounter"]["reference"] == _IMP_REF


def test_no_op_when_no_encounter_field():
    """Patient / Practitioner have no encounter field → skipped cleanly."""
    ctx = _ctx_with_ed_imp()
    resource = {"resourceType": "Patient", "id": "POP-000001"}
    reattribute_encounter_to_ed_bridge(resource, ctx)
    assert "encounter" not in resource


def test_no_op_when_reference_targets_different_encounter():
    """Reference already points elsewhere (e.g. secondary encounter) — respect it."""
    ctx = _ctx_with_ed_imp()
    resource = {
        "resourceType": "Composition",
        "type": {"coding": [{"code": "34878-9"}]},
        "encounter": {"reference": _OTHER_REF},
    }
    reattribute_encounter_to_ed_bridge(resource, ctx)
    assert resource["encounter"]["reference"] == _OTHER_REF


def test_idempotent_on_already_routed_resource():
    """Running the walker twice does not double-suffix."""
    ctx = _ctx_with_ed_imp()
    resource = {
        "resourceType": "Composition",
        "type": {"coding": [{"code": "34878-9"}]},
        "encounter": {"reference": _IMP_REF},
    }
    reattribute_encounter_to_ed_bridge(resource, ctx)
    reattribute_encounter_to_ed_bridge(resource, ctx)
    assert resource["encounter"]["reference"] == _ED_REF


def test_imp_id_cached_on_ctx():
    """_resolve_ed_imp_id sets a cache attribute so repeated walker calls are cheap."""
    ctx = _ctx_with_ed_imp()
    reattribute_encounter_to_ed_bridge({"resourceType": "Patient"}, ctx)
    assert getattr(ctx, "_ed_imp_id_cache", None) == "ENC-POP-000001-111"


def test_imp_id_cache_negative_sentinel_when_not_ed():
    """Non-EMD ctx caches a False sentinel so we don't re-parse per resource."""
    ctx = _ctx_without_ed()
    reattribute_encounter_to_ed_bridge({"resourceType": "Patient"}, ctx)
    assert ctx._ed_imp_id_cache is False


def test_missing_encounter_id_disables_routing():
    """No encounter_id on IMP → cannot compute -ED target → no routing."""
    ctx = SimpleNamespace(record={"encounters": [{"encounter_id": "", "admit_source": "emd"}]})
    resource = {
        "resourceType": "Composition",
        "type": {"coding": [{"code": "34878-9"}]},
        "encounter": {"reference": "Encounter/ENC-X"},
    }
    reattribute_encounter_to_ed_bridge(resource, ctx)
    assert resource["encounter"]["reference"] == "Encounter/ENC-X"
