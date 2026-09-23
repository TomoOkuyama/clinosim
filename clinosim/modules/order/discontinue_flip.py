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

# Clinical-course archetype token localization was moved to
# ``clinosim/locale/shared/narrative_archetypes.yaml`` (Phase 1d-1).
# The daily_loop DISCONTINUE marker's clinical_intent field encodes the
# archetype (``treatment_resistant`` / ``gradual_deterioration`` / …)
# and ``_log_treatment_change`` propagates it into the safety-skip
# ``active_conflict_ja`` field the template ``switch`` renderer reads.


def _localize_archetype(archetype: str, lang: str) -> str:
    """Resolve a clinical-course archetype slug to its localized display.

    Language-agnostic: ``lang`` is a direct YAML lookup key (via
    ``resolve_localized_display``), so adding a new locale is a
    data-only change — no branch here needs editing. Fallback chain:
    entry[lang] → entry["en"] → humanised slug.
    """
    if not archetype:
        return ""
    key = str(archetype).strip().lower()
    from clinosim.locale.loader import load_narrative_archetypes, resolve_localized_display

    return resolve_localized_display(
        load_narrative_archetypes().get(key, {}),
        lang,
        fallback=key.replace("_", " "),
    )


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
        # Issue #1416: production CIFPatientRecord uses `record.encounters`
        # (list); the POST_ENCOUNTER contract passes exactly one encounter
        # per record. Pre-#1416 read `record.encounter` (singular) which
        # was `None` on production data → `encounter_id=""` on skip_log
        # entries (breaking the `_build_safety_skips` filter that matches
        # entry.encounter_id == encounter.id) AND `stop_day=None` (breaking
        # the START-D<day>- match in `_find_replacement_agent`). Try
        # `encounter` singular first (hand-authored test fixtures), then
        # fall through to `encounters[0]` (production).
        encounter = getattr(record, "encounter", None)
        if encounter is None:
            encs = getattr(record, "encounters", None) or []
            if encs:
                encounter = encs[0]
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
                    # Phase 1c-3 (2026-09-22): fall through to
                    # ``_localize_drug_name`` when the order carries no
                    # explicit ``display_name_ja`` (most treatment_
                    # modifications entries don't). Pre-fix
                    # "Ampicillin/Sulbactam" / "Ceftriaxone" leaked as
                    # the raw English display in the JA plan-section
                    # narratives. Uses the same shared drug_names_ja
                    # table the FHIR emit path uses.
                    _ja_display = getattr(o, "display_name_ja", "") or ""
                    if not _ja_display:
                        try:
                            from clinosim.modules.output.fhir_r4.lib.localization import _localize_drug_name

                            _ja_display = _localize_drug_name(display, "JP") or display
                        except Exception:  # noqa: BLE001 — never fail the enricher on i18n
                            _ja_display = display
                    _log_treatment_change(
                        patient,
                        encounter_id=encounter_id,
                        stopped_drug=display,
                        stopped_drug_ja=_ja_display,
                        replacement_agent=replacement,
                        stop_day=stop_day,
                        clinical_intent=marker_intent,
                        timestamp=getattr(o, "ordered_datetime", None) or adm_dt,
                    )
                    logged_keys.add(key)


def _find_replacement_agent(orders, stopped_key: str, stop_day: int | None) -> str | None:
    """Pick the replacement agent that came from the SAME
    ``treatment_modifications.day_N`` YAML block as the STOP marker.

    Issue #1416 (S114 verify-2) fix: the pre-#1416 heuristic scanned
    every non-DISCONTINUE MEDICATION order in the encounter and
    returned the first drug that differed from the stopped one.
    Production data showed this picked IV fluid orders 100 % of the
    time on JP (343/343) and 9 % on US (16/170) — supportive-care MED
    orders (IV fluids, vasopressors, etc.) are emitted BEFORE the
    replacement antibiotic in the order list, so they always won the
    "first non-matching MED order" race.

    Fix: use the ``daily_loop``-authored order-id convention to
    identify only the START orders paired with THIS stop event. STOP
    orders are ``ORD-{encounter_id}-STOP-D{day}-{idx}-{drug8}``; START
    orders from the same treatment_modifications block are
    ``ORD-{encounter_id}-START-D{day}-{drug8}``. Filtering to
    ``-START-D{stop_day}-`` gives us exactly the drugs from
    ``treatment_modifications.day_{stop_day}.start`` — no supportive
    care, no unrelated home meds.

    When ``stop_day`` is None (timestamp arithmetic failed), fall
    through to the pre-#1416 first-non-matching-MED heuristic as a
    best-effort fallback. Returns None when neither path finds a
    replacement (narrative Rule 2 ``switch`` cadence then renders
    "X was discontinued (context)" without a ``; Y started`` clause).
    """
    # Preferred path: match by START order-id convention scoped to the
    # SAME day as the STOP marker. Multi-drug start blocks (e.g.
    # cellulitis "stop Cefazolin; start Meropenem + Vancomycin +
    # Clindamycin") return the FIRST start drug — narrative renders
    # one drug per switch bullet; the other start drugs already surface
    # via `active_medications_today` in the LLM prompt payload.
    #
    # When stop_day is known (production path):
    #   - a START-D<day>- match ⇒ return that drug.
    #   - no START-D<day>- match ⇒ return None. The disease YAML had
    #     no `start:` entry for this stop (e.g. cerebral_infarction
    #     antithrombotic HOLD for hemorrhagic-transformation without a
    #     replacement). Narrative Rule 2 `switch` cadence then renders
    #     "X was discontinued on day N (context)" without a
    #     "; Y started" clause. Do NOT fall through to the greedy
    #     first-non-matching-MED heuristic — that would pick unrelated
    #     supportive-care orders (IV fluid, vasopressor, home meds).
    if stop_day is not None:
        # daily_loop's `day` is 0-indexed while my stop_day is 1-indexed
        # (see enrich_discontinue_flip: `stop_day = max(0,
        # int(delta.total_seconds() // 86400) + 1)`). Try both to be
        # robust across the boundary.
        candidate_prefixes = (
            f"-START-D{int(stop_day) - 1}-",  # daily_loop 0-indexed match
            f"-START-D{int(stop_day)}-",  # 1-indexed match (defensive)
        )
        for o in orders:
            if getattr(o, "order_type", None) != OrderType.MEDICATION:
                continue
            if getattr(o, "status", None) == OrderStatus.STOPPED:
                continue
            oid = str(getattr(o, "order_id", "") or "")
            if not any(pref in oid for pref in candidate_prefixes):
                continue
            display = str(getattr(o, "display_name", "") or "")
            if not display or display.startswith("DISCONTINUE:"):
                continue
            key = _drug_key(display)
            if key == stopped_key or not key:
                continue
            return display
        # stop_day is known but no START-D<day>- match found — return
        # None (stop-only YAML block, no replacement).
        return None

    # Fallback (stop_day is None only — e.g. hand-authored test fixtures
    # where the STOP marker's `ordered_datetime` cannot be diffed
    # against the encounter's `admission_datetime` to derive a day
    # index): first non-DISCONTINUE, non-stopped MED order that differs.
    # Same as the pre-#1416 heuristic. Production data always has
    # stop_day set post-fix, so this path fires only for tests.
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
    #
    # Phase 1c-5 (2026-09-23): the pre-fix code inlined the raw
    # archetype slug (``treatment_resistant`` /
    # ``gradual_deterioration`` / ``complicated_delayed`` / …) into
    # both ``conflict_en`` and ``conflict_ja``. In JA that surfaced as
    # 「治療計画変更 (経過型: treatment_resistant)」 — a leak of ~1,100
    # raw archetype tokens across the JP p=10000 audit. Route the token
    # through ``_ARCHETYPE_JA/_ARCHETYPE_EN`` so JA reads 「治療計画変更
    # (経過型: 治療抵抗性)」.
    archetype = _extract_archetype(clinical_intent)
    if archetype:
        archetype_en = _localize_archetype(archetype, "en")
        archetype_ja = _localize_archetype(archetype, "ja")
        conflict_en = f"treatment plan change (archetype: {archetype_en})"
        conflict_ja = f"治療計画変更 (経過型: {archetype_ja})"
    else:
        archetype_en = ""
        archetype_ja = ""
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
    # Phase 1c-3 (2026-09-22): resolve the replacement-agent drug name to
    # katakana JA via the shared ``drug_names_ja`` table so the narrative
    # renderer's ``substituted_with_ja`` clause emits 「メロペネム 1g 静注
    # 8時間毎」 rather than the raw English "Meropenem 1g IV q8h" that
    # leaked into 46 JP p=500 plan-section narratives pre-fix.
    # ``_localize_drug_name`` is the same helper the FHIR emit path uses;
    # it handles substring drug + dose/route/frequency term translation.
    # Note: ``stopped_drug_ja`` is already resolved at the caller
    # (order.display_name_ja) so we do NOT re-localise it here.
    replacement_ja = replacement_agent
    if replacement_agent:
        try:
            from clinosim.modules.output.fhir_r4.lib.localization import _localize_drug_name

            replacement_ja = _localize_drug_name(replacement_agent, "JP") or replacement_agent
        except Exception:  # noqa: BLE001 — never fail the enricher on i18n
            replacement_ja = replacement_agent
    patient.safety_skip_log.append(
        SafetySkipEntry(
            encounter_id=encounter_id,
            candidate_drug=stopped_drug,
            candidate_drug_ja=stopped_drug_ja,
            active_conflict=conflict_en,
            active_conflict_ja=conflict_ja,
            verdict=verdict,
            substituted_with=replacement_agent,
            substituted_with_ja=replacement_ja,
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
