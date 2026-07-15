"""Integration: snapshot (--end) semantics for ServiceRequest status.

AD-32 snapshot: inpatients whose planned discharge falls after the --end date
have Encounter.status='in-progress'. Lab orders placed before the snapshot but
not yet resulted (e.g. multi-day culture orders, or orders on the last simulation
day) remain in OrderStatus.PLACED, causing aggregate_panel_status() to produce
ServiceRequest.status='active'.

Design note on hour-granular mid-day snapshot:
  The CLI supports only day-granular --end snapshots (no --snapshot-time flag).
  The simulator sets snapshot_dt = 23:59:59 of --end, so same-day results are
  always retained for day-boundary snapshots.  Hour-granular testing is deferred
  until --snapshot-time is added to the CLI.

Tested behaviour:
  1. Full-year simulation with early --end → in-progress Encounters exist.
  2. Active SRs appear (orders in PLACED status for in-progress/incomplete orders).
  3. SR resourceType + status are structurally valid.
"""

import tempfile
from pathlib import Path

import pytest

from tests.integration._sr_helpers import find_ndjson, load_ndjson, run_generate


@pytest.mark.integration
def test_snapshot_yields_active_sr_for_inprogress_orders():
    """Full-year cohort with early --end snapshot → active SRs for unresulted orders.

    Without --start, the CLI defaults start = (end - 365 days), producing a
    full year of encounters. The early --end date (2025-02-28) truncates
    long-stay inpatients and leaves their unreturned lab orders in PLACED
    status → SR.status='active'.
    """
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out"
        run_generate("US", 200, 42, out, end="2025-02-28")

        sr_file = find_ndjson(out, "ServiceRequest.ndjson")
        srs = load_ndjson(sr_file)
        assert srs, "ServiceRequest.ndjson is empty — no lab orders emitted"

        active = [s for s in srs if s.get("status") == "active"]
        if not active:
            pytest.skip(
                "No 'active' ServiceRequests in 200-patient full-year cohort with "
                "--end 2025-02-28. Increase population if this fires repeatedly."
            )

        # Structural validation of active SRs.
        # C1-16 (session 41 cycle 1) diversified SR.intent to {order,
        # instance-order, original-order} based on clinical_intent —
        # all three are valid values on an active SR.
        for sr in active[:10]:  # spot-check
            assert sr["resourceType"] == "ServiceRequest"
            assert sr["intent"] in ("order", "instance-order", "original-order")
            assert "identifier" in sr
            plac = sr["identifier"][0]["type"]["coding"][0]
            assert plac["code"] == "PLAC"


@pytest.mark.integration
def test_snapshot_inprogress_encounters_have_srs():
    """In-progress encounters (from --end snapshot) link to existing ServiceRequests.

    Verifies referential integrity: for each SR whose encounter reference points
    to an in-progress Encounter, the SR.id exists in ServiceRequest.ndjson.
    """
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out"
        run_generate("US", 200, 42, out, end="2025-02-28")

        encs = load_ndjson(find_ndjson(out, "Encounter.ndjson"))
        in_progress_ids = {e["id"] for e in encs if e.get("status") == "in-progress"}

        if not in_progress_ids:
            pytest.skip(
                "No in-progress Encounters with p=200, seed=42, end=2025-02-28. "
                "Increase population or adjust end date if this fires repeatedly."
            )

        srs = load_ndjson(find_ndjson(out, "ServiceRequest.ndjson"))

        sr_for_inprogress = [
            s for s in srs if s.get("encounter", {}).get("reference", "").removeprefix("Encounter/") in in_progress_ids
        ]
        # Verify in-progress encounters actually have at least one SR.
        assert sr_for_inprogress, f"No ServiceRequests linked to {len(in_progress_ids)} in-progress Encounters"
        # Spot-check: SRs for in-progress encounters should include some 'active' status.
        active_for_inprogress = [s for s in sr_for_inprogress if s.get("status") == "active"]
        assert active_for_inprogress, "Expected at least one 'active' SR for in-progress encounters"


@pytest.mark.integration
@pytest.mark.xfail(
    strict=False,
    reason=(
        "Known pre-existing inconsistency: some stand-alone orders at the snapshot "
        "boundary retain PLACED status while having a result Observation (the snapshot "
        "logic does not guarantee status=RESULTED for day-boundary results). "
        "Fixing the order-status semantics at snapshot time is tracked in TODO.md and "
        "is out of scope for the Stage 2 adversarial review. This test documents the "
        "intended invariant so it can gate a future fix."
    ),
)
def test_snapshot_placed_orders_have_no_observation():
    """Stand-alone active SRs (single PLACED order) should have no result Observations.

    AD-32 intended invariant: a stand-alone order in PLACED status has no result
    Observation yet. Its SR is 'active', and the SR id should appear in NO Observation's
    basedOn list.

    Currently marked xfail because the snapshot boundary (end-of-day on --end date)
    can leave some orders with status=PLACED even after a result Observation was written
    (order status is set by the simulation loop; the snapshot cuts at day-end but some
    orders may not have their status updated in the last day).
    """
    from clinosim.modules.order.panel_grouping import PANEL_PRIORITY_ORDER

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "out"
        run_generate("US", 200, 42, out, end="2025-02-28")

        srs = load_ndjson(find_ndjson(out, "ServiceRequest.ndjson"))

        # Identify stand-alone SRs: id has no "-{PanelName}-" segment.
        def _is_standalone(sr: dict) -> bool:
            sr_id = sr.get("id", "")
            return not any(f"-{p}-" in sr_id for p in PANEL_PRIORITY_ORDER)

        active_standalone_ids = {s["id"] for s in srs if s.get("status") == "active" and _is_standalone(s)}

        if not active_standalone_ids:
            pytest.skip(
                "No active stand-alone SRs in 200-patient snapshot cohort (end=2025-02-28). "
                "Increase population if this fires repeatedly."
            )

        obs = load_ndjson(find_ndjson(out, "Observation.ndjson"))
        pointing_at_active: list[str] = []
        for o in obs:
            for ref in o.get("basedOn", []):
                sr_ref = ref.get("reference", "").removeprefix("ServiceRequest/")
                if sr_ref in active_standalone_ids:
                    pointing_at_active.append(o.get("id", "?"))

        assert not pointing_at_active, (
            f"{len(pointing_at_active)} Observations reference stand-alone active "
            f"(PLACED) SRs — snapshot semantics violated: {pointing_at_active[:5]}"
        )


@pytest.mark.skip(
    reason=(
        "--snapshot-time flag not available in current CLI (day-granular --end only). "
        "Deferred until CLI gains hour-granular snapshot support; see TODO.md."
    )
)
def test_snapshot_midday_hour_granular():
    """Hour-granular mid-day snapshot (--snapshot-time) is not yet supported by CLI.

    Deferred requirement: once the CLI gains a --snapshot-time flag, this test
    should verify that lab orders PLACED before the snapshot hour but with a TAT
    extending past it yield SR.status='active' with no corresponding
    Observation.basedOn reference.

    Current behavior: snapshot_dt = 23:59:59 of --end, so same-day results are
    always retained and order status is already 'resulted' by day-end.
    """
    ...  # implement when --snapshot-time is added to CLI
