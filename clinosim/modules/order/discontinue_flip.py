"""Treatment-modification stop enricher (Issue #1346).

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
        # treatment-change event for narrative surface (Issue #1403,
        # semantics revised in #1413).
        # Issue #1413 (S114): S114 verify of US p=10000 s=357 flagged
        # all 165 US + 277 JP stop events as `event_type="deescalate"`
        # even though all 17 existing YAML `treatment_modifications.
        # day_N.stop` blocks are actually ESCALATIONS (Cefazolin →
        # Meropenem+Vancomycin for cellulitis worsening;
        # Ampicillin/Sulbactam → Meropenem for aspiration pneumonia
        # deterioration; Pip/Tazo → Meropenem+Vancomycin for sepsis
        # rescue; Ceftriaxone → Meropenem for UTI worsening). The
        # pre-#1413 default of `"deescalate"` mislabeled 100 % of
        # these switches. This block now emits `"switch"` (neutral —
        # "X was discontinued on day N; Y started") by default. A
        # future PR with an explicit `stewardship_action: "de_escalate"`
        # YAML flag or a spectrum-comparison verdict may upgrade the
        # event_type to `"deescalate"` on a case-by-case basis.
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
                    _marker_drug, stop_day = stop_drug_info[key]
                    replacement = _find_replacement_agent(orders, key, stop_day)
                    # Extract archetype from the marker's clinical_intent
                    # for a more informative `active_conflict` than the
                    # pre-#1413 hardcoded "antibiotic stewardship".
                    marker_intent = _marker_clinical_intent(orders, key)
                    # Prefer the ORIGINAL order's display (with dose) over
                    # the DISCONTINUE marker's bare drug name — narrative
                    # cites the drug + dose for clinical specificity
                    # ("Cefazolin 2g" > "Cefazolin").
                    _log_treatment_change(
                        patient,
                        encounter_id=encounter_id,
                        stopped_drug=display,
                        stopped_drug_ja=getattr(o, "display_name_ja", "") or display,
                        replacement_agent=replacement,
                        stop_day=stop_day,
                        clinical_intent=marker_intent,
                        timestamp=getattr(o, "ordered_datetime", None) or adm_dt,
                    )
                    logged_keys.add(key)


def _find_replacement_agent(orders, stopped_key: str, stop_day: int | None) -> str | None:
    """Pick the replacement agent emitted around the stop day. Simple
    heuristic: first non-DISCONTINUE, non-stopped MEDICATION order
    whose drug key differs from the stopped drug. Returns the raw
    display or None.

    Issue #1413 (S114) rename: the pre-#1413 name
    ``_find_narrower_replacement`` over-claimed clinical direction. The
    heuristic returns whatever agent fires after the stop marker
    regardless of spectrum — could be broader (escalation) or narrower
    (de-escalation). All 17 existing disease-YAML stop blocks pair the
    stop with a broader-spectrum start (clinical worsening trigger),
    so the returned replacement is almost always broader-spectrum in
    production data. The narrative render layer must treat this as a
    neutral "replacement" and NOT assert narrowing.
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
        return display
    return None


def _marker_clinical_intent(orders, stopped_key: str) -> str:
    """Return the DISCONTINUE marker's `clinical_intent` for the given
    stopped drug key. `daily_loop` emits this as
    ``"Day N <archetype>: stop <drug>"`` (see `daily_loop.py:455`) —
    the `<archetype>` token (e.g. "treatment_resistant",
    "gradual_deterioration", "complicated_delayed") is a meaningful
    signal about WHY the stop fired, and is preferable to the
    pre-#1413 hardcoded "antibiotic stewardship" phrasing that
    contradicted the actual escalation semantics.
    """
    for o in orders:
        if getattr(o, "order_type", None) != OrderType.MEDICATION:
            continue
        if MED_STOP_ORDER_ID_MARKER not in str(getattr(o, "order_id", "")):
            continue
        display = str(getattr(o, "display_name", "") or "")
        if not display.startswith("DISCONTINUE:"):
            continue
        drug = display[len("DISCONTINUE:") :].strip()
        if _drug_key(drug) != stopped_key:
            continue
        intent = str(getattr(o, "clinical_intent", "") or "")
        if intent:
            return intent
    return ""


def _log_treatment_change(
    patient,
    encounter_id: str,
    stopped_drug: str,
    stopped_drug_ja: str,
    replacement_agent: str | None,
    stop_day: int | None,
    clinical_intent: str,
    timestamp,
) -> None:
    """Issue #1403 + #1413: record a treatment-modification stop on
    ``patient.safety_skip_log`` so the narrative
    ``considered_but_not_prescribed`` Rule 2 "switch" cadence can say
    "X was discontinued on day N; Y started (clinical worsening per
    <archetype>)".

    Emits `event_type="switch"` (neutral) — the pre-#1413 default of
    `"deescalate"` mislabeled 100 % of production stops as
    de-escalations when they are actually escalations (see #1413).
    An explicit `stewardship_action: "de_escalate"` YAML flag or a
    spectrum-comparison verdict can upgrade to `"deescalate"` in a
    future PR.
    """
    from clinosim.modules.drug_safety.verdict import (
        SafetySkipEntry,
        SafetyVerdict,
    )

    # Turn "Day 3 treatment_resistant: stop Cefazolin" into an
    # active_conflict phrase like "day 3 treatment-resistant course"
    # for the JA rationale variant.
    archetype = _extract_archetype(clinical_intent)
    if archetype:
        conflict_en = f"treatment plan change (archetype: {archetype})"
        conflict_ja = f"治療計画変更 (経過型: {archetype})"
    else:
        conflict_en = "treatment plan change"
        conflict_ja = "治療計画変更"

    verdict = SafetyVerdict(
        severity="moderate",
        rule_id="treatment-modification-switch",
        matched_classes=None,
        matched_active_drug=replacement_agent,
        rationale_en=(
            f"treatment_modifications stop→start: "
            f"{stopped_drug} discontinued"
            + (f", {replacement_agent} started" if replacement_agent else "")
            + (f" ({archetype})" if archetype else "")
        ),
        rationale_ja=(
            f"treatment_modifications による中止→開始: "
            f"{stopped_drug} 中止"
            + (f"、{replacement_agent} 開始" if replacement_agent else "")
            + (f" ({archetype})" if archetype else "")
        ),
        substitution_hint=replacement_agent,
    )
    ts = timestamp.isoformat() if hasattr(timestamp, "isoformat") else str(timestamp or "")
    patient.safety_skip_log.append(
        SafetySkipEntry(
            encounter_id=encounter_id,
            candidate_drug=stopped_drug,
            candidate_drug_ja=stopped_drug_ja,
            active_conflict=conflict_en,
            active_conflict_ja=conflict_ja,
            verdict=verdict,
            substituted_with=replacement_agent,
            # display_name_ja for the replacement could be resolved via
            # drug_safety lookup; keep the raw display for now.
            substituted_with_ja=replacement_agent,
            context_hint=clinical_intent or "treatment_modifications switch",
            timestamp=ts,
            event_type="switch",
            stopped_on_day=stop_day,
        )
    )


def _extract_archetype(clinical_intent: str) -> str:
    """Parse the archetype token out of a DISCONTINUE marker's
    ``clinical_intent`` field. Format authored by ``daily_loop``:
    ``"Day 3 treatment_resistant: stop Cefazolin"``. Returns the
    archetype token ("treatment_resistant") or empty string.
    """
    if not clinical_intent:
        return ""
    # Format: "Day N <archetype>: stop <drug>"
    if ":" not in clinical_intent:
        return ""
    prefix = clinical_intent.split(":", 1)[0].strip()
    # prefix = "Day 3 treatment_resistant"
    parts = prefix.split(None, 2)
    if len(parts) < 3:
        return ""
    return parts[2].strip()


__all__ = ["enrich_discontinue_flip", "_drug_key"]
