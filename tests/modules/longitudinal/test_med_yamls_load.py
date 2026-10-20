"""Phase 4a Task 5 — Loader picks up the two escalation yamls."""

from __future__ import annotations

from clinosim.modules.longitudinal.loader import load_attribute_specs


EXPECTED = {
    "dm_escalate_sglt2i_e11": {
        "emits_meds": ["Empagliflozin"],
        "fire_marker": "dm_escalate_sglt2i_e11",
        "requires_chronic_codes": ["E11"],
    },
    "dm_escalate_insulin_e11": {
        "emits_meds": ["Insulin glargine"],
        "fire_marker": "dm_escalate_insulin_e11",
        "requires_chronic_codes": ["E11"],
    },
}


def test_dm_escalation_yamls_load():
    load_attribute_specs.cache_clear()
    specs = load_attribute_specs()
    for attr_id, want in EXPECTED.items():
        assert attr_id in specs, f"missing {attr_id}"
        body = specs[attr_id].body
        assert body.emits_meds == want["emits_meds"]
        assert body.fire_marker == want["fire_marker"]
        assert body.emits_icd == ""
        assert body.one_shot is True
        assert specs[attr_id].clinical_scope.requires_chronic_codes == want["requires_chronic_codes"]


def test_dm_escalation_yamls_independent():
    """Review Focus #5: insulin yaml does not depend_on sglt2i yaml."""
    load_attribute_specs.cache_clear()
    specs = load_attribute_specs()
    insulin_deps = specs["dm_escalate_insulin_e11"].depends_on
    assert "dm_escalate_sglt2i_e11" not in insulin_deps
    assert "hba1c" in insulin_deps
