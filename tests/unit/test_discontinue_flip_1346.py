"""Issue #1346 — antibiotic de-escalation status flip.

``simulator/daily_loop`` emits a stand-alone ``Order(display_name=
"DISCONTINUE: X")`` when a disease-YAML archetype's
``treatment_modifications.day_N.stop: [X]`` fires. Prior to this
enricher the ORIGINAL X medication order stayed at ``PLACED`` through
discharge, so FHIR ``MedicationRequest`` rendered Cefazolin (or
whichever antibiotic) as still-active even after the DISCONTINUE
marker landed on Day 3. Random-sample review of a cellulitis IMP
admission (Issue #1346) flagged 4-antibiotic stacking:
Cefazolin + Meropenem + Vancomycin + Pip/Tazo concurrent through
Days 3-5.

This enricher runs POST_ENCOUNTER and walks ``record.orders`` for
``DISCONTINUE: X`` markers, then flips the original matching X order's
``status`` to ``STOPPED``. Byte-preserving to per-day MAR generation
(which finished before this fires).
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any

from clinosim.modules.order.discontinue_flip import _drug_key, enrich_discontinue_flip
from clinosim.simulator.enrichers import EnricherContext
from clinosim.types.encounter import Order, OrderStatus, OrderType


def _mk_ctx(records: list[Any]) -> EnricherContext:
    return EnricherContext(config=SimpleNamespace(country="US"), master_seed=0, records=records)


def _mk_record(orders: list[Order]) -> Any:
    return SimpleNamespace(orders=orders)


def _mk_med_order(order_id: str, display_name: str) -> Order:
    return Order(
        order_id=order_id,
        display_name=display_name,
        order_type=OrderType.MEDICATION,
        status=OrderStatus.PLACED,
        ordered_datetime=datetime(2026, 6, 1, 8, 0),
    )


def test_drug_key_extracts_first_token_lowercased():
    assert _drug_key("Cefazolin 2g") == "cefazolin"
    assert _drug_key("Meropenem") == "meropenem"
    assert _drug_key("Piperacillin/Tazobactam 4.5g IV q8h") == "piperacillin/tazobactam"
    assert _drug_key("") == ""


def test_discontinue_flip_flips_matching_cefazolin_status():
    cefazolin = _mk_med_order("ORD-enc-001-D1-CEF", "Cefazolin 2g")
    stop_marker = _mk_med_order("ORD-enc-001-STOP-D3-0-CEFAZOLI", "DISCONTINUE: Cefazolin")
    meropenem = _mk_med_order("ORD-enc-001-START-D3-MEROPENEM", "Meropenem 1g")
    rec = _mk_record([cefazolin, stop_marker, meropenem])
    enrich_discontinue_flip(_mk_ctx([rec]))
    assert cefazolin.status == OrderStatus.STOPPED
    # Meropenem (unrelated) untouched
    assert meropenem.status == OrderStatus.PLACED
    # DISCONTINUE marker itself is not flipped by the enricher (its status
    # is separately handled at FHIR emit via MED_STOP_ORDER_ID_MARKER)
    assert stop_marker.status == OrderStatus.PLACED


def test_discontinue_flip_no_marker_no_op():
    cefazolin = _mk_med_order("ORD-enc-002-D1-CEF", "Cefazolin 2g")
    rec = _mk_record([cefazolin])
    enrich_discontinue_flip(_mk_ctx([rec]))
    assert cefazolin.status == OrderStatus.PLACED


def test_discontinue_flip_case_insensitive_first_token_only():
    """A DISCONTINUE marker for ``Cefazolin`` matches any ``cefazolin ...``
    display name regardless of case or trailing dose fragment."""
    cef1 = _mk_med_order("ORD-enc-003-D1-CEF1", "cefazolin 1g")  # lowercase
    cef2 = _mk_med_order("ORD-enc-003-D1-CEF2", "Cefazolin 2g IV")  # capitalized
    other = _mk_med_order("ORD-enc-003-D1-OTHER", "Ceftriaxone 1g")  # different drug
    stop_marker = _mk_med_order("ORD-enc-003-STOP-D3-0-CEF", "DISCONTINUE: Cefazolin")
    rec = _mk_record([cef1, cef2, other, stop_marker])
    enrich_discontinue_flip(_mk_ctx([rec]))
    assert cef1.status == OrderStatus.STOPPED
    assert cef2.status == OrderStatus.STOPPED
    assert other.status == OrderStatus.PLACED, "Ceftriaxone must not be flipped by a Cefazolin DISCONTINUE"


def test_discontinue_flip_idempotent():
    cef = _mk_med_order("ORD-enc-004-D1-CEF", "Cefazolin 2g")
    stop_marker = _mk_med_order("ORD-enc-004-STOP-D3-0-CEF", "DISCONTINUE: Cefazolin")
    rec = _mk_record([cef, stop_marker])
    enrich_discontinue_flip(_mk_ctx([rec]))
    enrich_discontinue_flip(_mk_ctx([rec]))
    assert cef.status == OrderStatus.STOPPED


def test_discontinue_flip_multiple_stops_all_flipped():
    """Multiple DISCONTINUE markers in a single record — every referenced
    original is flipped."""
    cef = _mk_med_order("ORD-enc-005-D1-CEF", "Cefazolin 2g")
    metfor = _mk_med_order("ORD-enc-005-HOMEMED-METFORMIN", "Metformin 500mg")
    stop_cef = _mk_med_order("ORD-enc-005-STOP-D3-0-CEF", "DISCONTINUE: Cefazolin")
    stop_met = _mk_med_order("ORD-enc-005-STOP-D1-0-METFORMIN", "DISCONTINUE: Metformin")
    rec = _mk_record([cef, metfor, stop_cef, stop_met])
    enrich_discontinue_flip(_mk_ctx([rec]))
    assert cef.status == OrderStatus.STOPPED
    assert metfor.status == OrderStatus.STOPPED


# ---------------------------------------------------------------------------
# Issue #1413 (S114): safety_skip_log emit + event_type="switch" default
# ---------------------------------------------------------------------------


from clinosim.modules.order.discontinue_flip import _extract_archetype  # noqa: E402


def test_discontinue_flip_emits_skip_log_with_switch_event_type():
    """Issue #1413: default `event_type` for treatment_modifications
    stop events is `"switch"` (neutral), NOT `"deescalate"` (which is
    now opt-in only). Pre-#1413 emitted `"deescalate"` for every stop,
    mislabeling 100% of production data since all 17 disease-YAML
    stop blocks are escalations.
    """
    from types import SimpleNamespace

    from clinosim.types.patient import PatientProfile

    patient = PatientProfile(patient_id="pt-1")
    cefazolin = _mk_med_order("ORD-enc-101-D1-CEF", "Cefazolin 2g")
    stop_marker = _mk_med_order("ORD-enc-101-STOP-D3-0-CEF", "DISCONTINUE: Cefazolin")
    stop_marker.clinical_intent = "Day 3 treatment_resistant: stop Cefazolin"
    meropenem = _mk_med_order("ORD-enc-101-D3-MEROP", "Meropenem 1g")
    encounter = SimpleNamespace(
        encounter_id="ENC-101",
        admission_datetime=datetime(2026, 6, 1, 8, 0),
    )
    rec = SimpleNamespace(orders=[cefazolin, stop_marker, meropenem], encounter=encounter, patient=patient)
    enrich_discontinue_flip(_mk_ctx([rec]))
    assert cefazolin.status == OrderStatus.STOPPED
    assert len(patient.safety_skip_log) == 1
    entry = patient.safety_skip_log[0]
    assert entry.event_type == "switch"  # NOT "deescalate"
    assert entry.candidate_drug == "Cefazolin 2g"
    assert entry.substituted_with == "Meropenem 1g"
    assert entry.encounter_id == "ENC-101"
    # active_conflict must carry the archetype context, not the pre-#1413
    # hardcoded "antibiotic stewardship" phrasing.
    assert "treatment plan change" in entry.active_conflict
    assert "treatment_resistant" in entry.active_conflict
    # verdict.rule_id renamed from "antibiotic-de-escalation" to a
    # neutral marker.
    assert entry.verdict.rule_id == "treatment-modification-switch"


def test_extract_archetype_parses_daily_loop_clinical_intent():
    """Issue #1413: `_extract_archetype` parses the `daily_loop`-authored
    format `"Day N <archetype>: stop <drug>"` and returns the archetype
    token, or "" when the format is not recognized.
    """
    assert _extract_archetype("Day 3 treatment_resistant: stop Cefazolin") == "treatment_resistant"
    assert _extract_archetype("Day 5 gradual_deterioration: stop Ampicillin/Sulbactam") == "gradual_deterioration"
    assert _extract_archetype("Day 1 complicated_delayed: stop Ceftriaxone") == "complicated_delayed"
    assert _extract_archetype("") == ""
    assert _extract_archetype("no colon here") == ""
    assert _extract_archetype("Day 3") == ""  # too few tokens
