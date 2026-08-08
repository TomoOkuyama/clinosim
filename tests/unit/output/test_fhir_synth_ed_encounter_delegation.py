"""Regression guards for Issue #546 — synth-ED Encounter delegates to
canonical `_build_encounter`.

These tests lock the post-refactor behaviour:

1. `_bb_encounters` calls `_build_encounter` twice per IMP encounter with
   `admit_source_encounter_id` set (once for the primary IMP, once for
   the synth-ED bridge) — no parallel dict construction.
2. The synth-ED bridge Encounter's `class.coding[0].display` matches what
   `_build_encounter` would emit for a plain `encounter_type="emergency"`
   input — silent-drift is impossible when both go through the same
   builder.
3. The synth-ED bridge omits `hospitalization.dischargeDisposition`
   entirely — the ED→IMP transition is expressed via `partOf`, and the
   canonical `home` fallback (encounter.py:487) is suppressed by the
   caller's post-hoc pop. See spec DD2 / DD4.
4. The synth-ED bridge's admit-source display comes from the CS registry
   (`code_lookup("hl7-admit-source", "outp", <lang>)`) — single source
   of truth.
5. The synth-ED bridge's `participant[0].type[]` has the canonical
   ATND coding shape (proof of full delegation to `_build_encounter`,
   which is the only source of that shape via `make_participant`).
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from clinosim.codes import lookup as code_lookup
from clinosim.modules.output.fhir_r4.encounters.encounter import _build_encounter
from clinosim.modules.output.fhir_r4.lib.common import BundleContext
from clinosim.modules.output.fhir_r4.lib.inline_bb import _bb_encounters


def _make_ctx(country: str) -> BundleContext:
    """Build a BundleContext with one IMP encounter that has an
    ``admit_source_encounter_id`` set — the trigger for synth-ED emission.
    """
    imp_id = "ENC-000001"
    ed_id = f"{imp_id}-ED"
    encounters = [
        {
            "encounter_id": imp_id,
            "encounter_type": "inpatient",
            "status": "completed",
            "admission_datetime": "2026-01-15T10:00:00",
            "discharge_datetime": "2026-01-20T14:00:00",
            "admit_source": "emd",
            "admit_source_encounter_id": ed_id,
            "attending_physician_id": "PRAC-000001",
            "chief_complaint": "Chest pain",
        }
    ]
    return BundleContext(
        record={"encounters": encounters, "orders": []},
        country=country,
        roster_map={},
        hospital_config={},
        patient_data={"chronic_conditions": []},
        patient_id="POP-000001",
        is_readmission=False,
        prior_encounter_id=None,
        primary_dx_code="",
        admit_dx_code="",
        admit_dx_system="icd-10-cm",
        primary_enc_id=imp_id,
        patient_sex="M",
    )


def _synth_ed_resource(resources: list[dict]) -> dict:
    """Return the ED bridge encounter (id ends with ``-ED``) from the list."""
    for r in resources:
        if r.get("id", "").endswith("-ED"):
            return r
    raise AssertionError(f"No synth-ED bridge encounter in resources: {[r.get('id') for r in resources]}")


@pytest.mark.parametrize("country", ["JP", "US"])
def test_synth_ed_delegated_via_canonical_builder(country: str) -> None:
    """Refactor guarantee: `_bb_encounters` calls `_build_encounter` for
    BOTH the primary IMP AND the synth-ED bridge. No parallel emit path.
    """
    ctx = _make_ctx(country)
    with patch(
        "clinosim.modules.output.fhir_r4.lib.inline_bb._build_encounter",
        wraps=_build_encounter,
    ) as spy:
        _bb_encounters(ctx)
    assert spy.call_count == 2, (
        f"_build_encounter should be called twice (primary IMP + synth-ED); "
        f"got {spy.call_count}. A parallel emitter has regressed."
    )


@pytest.mark.parametrize("country", ["JP", "US"])
def test_synth_ed_class_display_matches_canonical(country: str) -> None:
    """Silent-drift guard: synth-ED bridge's class.display equals what
    the canonical builder emits for a plain emergency Encounter.
    """
    ctx = _make_ctx(country)
    synth_ed = _synth_ed_resource(_bb_encounters(ctx))
    canonical_emergency = _build_encounter(
        {"encounter_id": "cmp", "encounter_type": "emergency", "status": "completed"},
        patient_id="POP-000001",
        country=country,
    )
    assert synth_ed["class"]["display"] == canonical_emergency["class"]["display"]


@pytest.mark.parametrize("country", ["JP", "US"])
def test_synth_ed_omits_discharge_disposition(country: str) -> None:
    """Spec DD2 + DD4: synth-ED emits no ``dischargeDisposition``.

    ED→IMP transition is expressed via ``partOf`` on the IMP encounter.
    The canonical ``home`` fallback (encounter.py:487) is suppressed by the
    caller's post-hoc pop.
    """
    ctx = _make_ctx(country)
    synth_ed = _synth_ed_resource(_bb_encounters(ctx))
    hosp = synth_ed.get("hospitalization", {})
    assert "dischargeDisposition" not in hosp, f"synth-ED must NOT emit dischargeDisposition (spec DD2). Got: {hosp!r}"


@pytest.mark.parametrize("country,lang", [("JP", "ja"), ("US", "en")])
def test_synth_ed_admit_source_uses_registry_display(country: str, lang: str) -> None:
    """Single-source-of-truth: synth-ED's admitSource display equals the
    CS registry lookup, not a bespoke hardcoded string.
    """
    ctx = _make_ctx(country)
    synth_ed = _synth_ed_resource(_bb_encounters(ctx))
    admit_source_display = synth_ed["hospitalization"]["admitSource"]["coding"][0]["display"]
    expected = code_lookup("hl7-admit-source", "outp", lang)
    assert admit_source_display == expected


@pytest.mark.parametrize("country", ["JP", "US"])
def test_synth_ed_participant_has_canonical_type(country: str) -> None:
    """Full delegation proof: ``participant[0].type[]`` comes from
    ``make_participant`` (canonical) and has an ATND coding under
    v3-ParticipationType. The pre-refactor inline emitter omitted
    ``type[]``.
    """
    ctx = _make_ctx(country)
    synth_ed = _synth_ed_resource(_bb_encounters(ctx))
    participants = synth_ed.get("participant", [])
    assert participants, "synth-ED must have a participant (attending physician)"
    types = participants[0].get("type", [])
    assert types, "participant[0].type[] must be present (canonical shape)"
    coding = types[0]["coding"][0]
    assert coding["code"] == "ATND"
    assert coding["system"].endswith("v3-ParticipationType")
