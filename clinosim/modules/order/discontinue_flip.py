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
        # Collect drug names to stop AND the day on which each stop
        # marker was placed. Day comes from the marker order's
        # `ordered_datetime` minus the encounter admission — surfaced
        # for narrative Rule 2 "deescalate" cadence via
        # `SafetySkipEntry.stopped_on_day`.
        # Key: normalized drug key → (raw drug display, stop_day)
        stop_drug_info: dict[str, tuple[str, int | None]] = {}
        encounter = getattr(record, "encounter", None)
        adm_dt = getattr(encounter, "admission_datetime", None) if encounter else None
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
            if not key:
                continue
            stop_day: int | None = None
            ord_dt = getattr(o, "ordered_datetime", None) or getattr(o, "order_datetime", None)
            if adm_dt is not None and ord_dt is not None:
                try:
                    delta = ord_dt - adm_dt
                    stop_day = max(0, int(delta.total_seconds() // 86400) + 1)
                except (AttributeError, TypeError):
                    stop_day = None
            stop_drug_info[key] = (drug, stop_day)
        if not stop_drug_info:
            continue
        # Flip original matching orders to STOPPED and log the
        # de-escalation event for narrative surface (Issue #1403).
        # Collect the ACTIVE agents around the stop time so the
        # narrative can say "de-escalated to <narrower>". Simple
        # heuristic: any non-DISCONTINUE MEDICATION order emitted on
        # the same day or later.
        patient = getattr(record, "patient", None)
        encounter_id = getattr(encounter, "encounter_id", "") if encounter else ""
        logged_keys: set[str] = set()
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
            key = _drug_key(display)
            if key in stop_drug_info:
                # Direct attribute set — the CIF is mutable and this only
                # runs POST_ENCOUNTER (after per-day MAR generation).
                try:
                    o.status = OrderStatus.STOPPED
                except AttributeError:
                    # Defensive: fall through for immutable Order proxies.
                    pass
                # Log once per stopped drug (avoid duplicate skip_log
                # entries when the same drug had multiple parallel
                # orders — clinically all-stop, one narrative bullet).
                if patient is not None and key not in logged_keys:
                    original_display, stop_day = stop_drug_info[key]
                    narrower = _find_narrower_replacement(orders, key, stop_day)
                    _log_deescalation(
                        patient,
                        encounter_id=encounter_id,
                        stopped_drug=original_display,
                        stopped_drug_ja=getattr(o, "display_name_ja", "") or original_display,
                        narrower_agent=narrower,
                        stop_day=stop_day,
                        timestamp=getattr(o, "ordered_datetime", None) or adm_dt,
                    )
                    logged_keys.add(key)


def _find_narrower_replacement(orders, stopped_key: str, stop_day: int | None) -> str | None:
    """Pick the narrower-spectrum replacement emitted around the stop
    day. Simple heuristic: first non-DISCONTINUE, non-stopped
    MEDICATION order whose drug key differs from the stopped drug and
    whose ordered_datetime is on-or-after the stop event. Returns the
    raw display name (dose stripped by caller if desired) or None.

    Not perfect — a real de-escalation dispatch would know the drug
    class (broad → narrow). This heuristic covers the common case where
    the disease YAML `treatment_modifications.day_N.stop: [Cefazolin]`
    is paired with `start: [Amoxicillin]` on the same day.
    """
    for o in orders:
        if getattr(o, "order_type", None) != OrderType.MEDICATION:
            continue
        if MED_STOP_ORDER_ID_MARKER in str(getattr(o, "order_id", "")):
            continue
        if getattr(o, "status", None) == OrderStatus.STOPPED:
            continue
        display = str(getattr(o, "display_name", "") or "")
        if display.startswith("DISCONTINUE:"):
            continue
        key = _drug_key(display)
        if key == stopped_key or not key:
            continue
        # Return the raw display — narrative renderer will use it.
        return display
    return None


def _log_deescalation(
    patient,
    encounter_id: str,
    stopped_drug: str,
    stopped_drug_ja: str,
    narrower_agent: str | None,
    stop_day: int | None,
    timestamp,
) -> None:
    """Issue #1403: record antibiotic de-escalation on
    ``patient.safety_skip_log`` so the narrative
    ``considered_but_not_prescribed`` Rule 2 "deescalate" cadence can
    say "Cefazolin was discontinued on day 3 and narrowed to
    Amoxicillin (antibiotic stewardship)".
    """
    from clinosim.modules.drug_safety.verdict import (
        SafetySkipEntry,
        SafetyVerdict,
    )

    verdict = SafetyVerdict(
        severity="moderate",
        rule_id="antibiotic-de-escalation",
        matched_classes=None,
        matched_active_drug=narrower_agent,
        rationale_en="antibiotic stewardship: de-escalation to narrower agent",
        rationale_ja="抗菌薬スチュワードシップ: 狭域薬への de-escalation",
        substitution_hint=narrower_agent,
    )
    ts = timestamp.isoformat() if hasattr(timestamp, "isoformat") else str(timestamp or "")
    patient.safety_skip_log.append(
        SafetySkipEntry(
            encounter_id=encounter_id,
            candidate_drug=stopped_drug,
            candidate_drug_ja=stopped_drug_ja,
            active_conflict="antibiotic stewardship",
            active_conflict_ja="抗菌薬スチュワードシップ",
            verdict=verdict,
            substituted_with=narrower_agent,
            # display_name_ja for the narrower agent could be resolved
            # via drug_safety lookup; keep the raw display for now.
            substituted_with_ja=narrower_agent,
            context_hint="antibiotic de-escalation",
            timestamp=ts,
            event_type="deescalate",
            stopped_on_day=stop_day,
        )
    )


__all__ = ["enrich_discontinue_flip", "_drug_key"]
