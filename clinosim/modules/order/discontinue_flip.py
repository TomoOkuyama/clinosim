"""De-escalation status-flip enricher (Issue #1346).

Antibiotic stewardship & other treatment-modification archetypes in
disease YAMLs declare ``treatment_modifications.day_N.stop: [DrugName]``
blocks. ``simulator/daily_loop`` emits these as a stand-alone
``Order(order_type=MEDICATION, display_name="DISCONTINUE: DrugName")``
so the downstream MAR builder can filter phantom administrations
(session-98 F4/F5 fix; see ``medication_pipeline._generate_mar_entries``
line 371). What was previously missing is the counterpart on the
ORIGINAL ``Cefazolin`` (or Metformin, or …) order — its ``status``
remained ``PLACED`` through discharge, so FHIR ``MedicationRequest``
rendered the original antibiotic as still-active even after the
DISCONTINUE marker fired on Day 3. Random-sample review of a
cellulitis admission (Issue #1346) flagged 4-antibiotic stacking
(Cefazolin + Meropenem + Vancomycin + Pip/Tazo) with no visible
stewardship — the escalation drugs were added but the original was
never marked stopped.

This enricher runs POST_ENCOUNTER (after the daily loop completes,
before FHIR emit). It walks ``record.orders`` for ``DISCONTINUE: X``
markers and flips the original matching X order's status to
``STOPPED``. Byte-preserving to per-day MAR generation because those
runs finished BEFORE this enricher fires — the flipped status only
propagates into the encounter-final ``MedicationRequest`` emit, not
into the day-loop's per-order MAR iteration.

Match strategy: display-name whitespace-normalized substring. An
Order emitted as ``"Cefazolin 2g"`` matches the ``DISCONTINUE:
Cefazolin`` marker's stripped drug name (``"Cefazolin"``). Multiple
same-drug orders (unusual) all flip together — clinically the
DISCONTINUE marker discontinues ALL active orders of that drug.

Determinism: RNG-free. Reads/mutates only ``record.orders``.
"""

from __future__ import annotations

from clinosim.modules._shared import MED_STOP_ORDER_ID_MARKER
from clinosim.simulator.enrichers import EnricherContext
from clinosim.types.encounter import OrderStatus, OrderType


def _drug_key(display_name: str) -> str:
    """Whitespace-collapsed lowercase first-token of the display name.

    ``"Cefazolin 2g"`` → ``"cefazolin"``. Matches the DISCONTINUE marker's
    stripped drug name (which is authored by daily_loop as the bare
    drug name after ``"DISCONTINUE: "``)."""
    first = (display_name or "").strip().split()[0] if display_name else ""
    return first.lower()


def enrich_discontinue_flip(ctx: EnricherContext) -> None:
    """POST_ENCOUNTER enricher — Issue #1346.

    For each patient record in ``ctx.records``, collect the drug names
    referenced by any ``DISCONTINUE: X`` MEDICATION order (identified by
    the ``MED_STOP_ORDER_ID_MARKER`` in the order_id) and flip all
    prior-emitted matching X medication orders' status to STOPPED.

    Idempotent: an already-STOPPED order is skipped. Byte-preserving to
    per-day MAR generation which completed before this enricher runs.
    """
    for record in ctx.records:
        orders = getattr(record, "orders", None) or []
        # Collect drug names to stop.
        stop_drug_keys: set[str] = set()
        for o in orders:
            if getattr(o, "order_type", None) != OrderType.MEDICATION:
                continue
            if MED_STOP_ORDER_ID_MARKER not in str(getattr(o, "order_id", "")):
                continue
            display = str(getattr(o, "display_name", "") or "")
            if not display.startswith("DISCONTINUE:"):
                continue
            # Strip the marker prefix and take the drug name.
            drug = display[len("DISCONTINUE:") :].strip()
            key = _drug_key(drug)
            if key:
                stop_drug_keys.add(key)
        if not stop_drug_keys:
            continue
        # Flip original matching orders to STOPPED.
        for o in orders:
            if getattr(o, "order_type", None) != OrderType.MEDICATION:
                continue
            if MED_STOP_ORDER_ID_MARKER in str(getattr(o, "order_id", "")):
                continue  # the DISCONTINUE order itself — already stopped
            if getattr(o, "status", None) == OrderStatus.STOPPED:
                continue  # idempotent
            display = str(getattr(o, "display_name", "") or "")
            if display.startswith("DISCONTINUE:"):
                continue
            if _drug_key(display) in stop_drug_keys:
                # Direct attribute set — the CIF is mutable and this only
                # runs POST_ENCOUNTER (after per-day MAR generation).
                try:
                    o.status = OrderStatus.STOPPED
                except AttributeError:
                    # Defensive: fall through for immutable Order proxies.
                    pass


__all__ = ["enrich_discontinue_flip", "_drug_key"]
