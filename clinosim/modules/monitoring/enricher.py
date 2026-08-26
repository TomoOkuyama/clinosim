"""POST_RECORDS enricher: inject chronic-med → monitoring labs (Issue #757).

For each patient record, look up every drug in ``patient.current_medications``
against ``medication_monitoring.yaml`` and inject the standard-of-care
monitoring labs the drug requires. Currently ships one lab per eligible
encounter (MVP scope, closes the immediate #736 gap); frequency scheduling
is deferred to a follow-up PR under META #757.

Determinism:

- Uses a per-patient sub-RNG derived from
  ``ENRICHER_SEED_OFFSETS["medication_monitoring"]`` so master RNG is not
  touched (matches the ``care_level`` / ``family_history`` pattern).
- Per-order noise draws use ``individual_lab_seed(order_id)`` — identical
  isolation to ``outpatient.py`` and ``inpatient.py`` Pass 1 (AD-16).
- The synthetic order_id is content-derived (``<encounter_id>-MED-MON-<idx>``),
  so it stays stable across repeated runs on the same seed.

Dedup:

- Skips a monitoring lab if the record already carries an Order or
  OrderResult for that analyte. Disease-YAML flows that legitimately
  order INR (sepsis, PE, GI bleed) are respected; only the medication-
  driven gap is filled.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import numpy as np

from clinosim.modules._shared import get_attr_or_key as _get
from clinosim.modules.observation.engine import (
    canonical_lab_name,
    generate_lab_result,
    get_lab_unit,
)
from clinosim.modules.observation.engine import determine_flag as _determine_flag
from clinosim.seeding import ENRICHER_SEED_OFFSETS, derive_sub_seed, individual_lab_seed
from clinosim.types.encounter import EncounterType, Order, OrderResult, OrderStatus


def enrich_medication_monitoring(ctx: Any) -> None:
    """Inject chronic-medication-driven monitoring labs into each record.

    See module docstring for design + dedup rules. Silent no-op when the
    mapping YAML has no drug entries or when no record's patient is on any
    mapped drug.
    """
    from clinosim.modules.monitoring.mapping import load_medication_monitoring, match_drugs

    try:
        mapping = load_medication_monitoring()
    except FileNotFoundError:
        return
    if not mapping:
        return

    country = "US"
    cfg = _get(ctx, "config")
    if cfg is not None:
        country = _get(cfg, "country", "US") or "US"

    for record in _get(ctx, "records", []) or []:
        _inject_for_record(record, mapping, ctx.master_seed, country, match_drugs)


def _inject_for_record(record: Any, mapping: dict, master_seed: int, country: str, match_drugs) -> None:
    """Handle one CIFPatientRecord: match drugs, inject each missing monitoring lab."""
    patient = _get(record, "patient")
    if patient is None:
        return
    meds = getattr(patient, "current_medications", None) or []
    if not meds:
        return

    matched_drugs = match_drugs(meds, mapping)
    if not matched_drugs:
        return

    encounter = _pick_target_encounter(record)
    if encounter is None:
        return

    # Deduplicate against existing lab orders / results on this record so the
    # enricher never double-orders a lab the disease YAML already fires. Match
    # on canonical analyte name (e.g. "PT-INR" ↔ "PT_INR" collapse via
    # `canonical_lab_name`).
    existing = _existing_analytes(record)

    # Per-patient sub-RNG for enricher-scoped micro-decisions (currently only
    # scheduling jitter within the encounter). Master RNG is untouched.
    pid = getattr(patient, "patient_id", "") or ""
    enricher_rng = np.random.default_rng(
        derive_sub_seed(master_seed, ENRICHER_SEED_OFFSETS["medication_monitoring"], pid or "x")
    )

    true_labs = _derive_true_labs_for_patient(patient, matched_drugs)

    injected_count = 0
    for drug in matched_drugs:
        drug_entry = mapping[drug]
        # Issue #871: JA display for the drug (used to compose the JP
        # `Order.clinical_intent_ja` template). Falls back to the canonical
        # EN drug key when the YAML has no `drug_ja` slot.
        drug_ja = str(drug_entry.get("drug_ja") or drug)
        for lab_spec in drug_entry.get("monitoring") or []:
            analyte = canonical_lab_name(str(lab_spec.get("lab") or ""))
            if not analyte or analyte in existing:
                continue
            _inject_one_lab(
                record=record,
                encounter=encounter,
                patient=patient,
                analyte=analyte,
                display_name=str(lab_spec.get("lab") or analyte),
                loinc=str(lab_spec.get("loinc") or ""),
                rationale=str(lab_spec.get("rationale") or f"{drug} monitoring"),
                # Issue #871: JA rationale for the JP `reasonCode.text` emit
                # path. Empty when the YAML has no `rationale_ja` slot yet;
                # `_inject_one_lab` then leaves `clinical_intent_ja` empty
                # and the SR emitter falls back to the EN string.
                rationale_ja=str(lab_spec.get("rationale_ja") or ""),
                drug=drug,
                drug_ja=drug_ja,
                true_value=true_labs.get(analyte),
                enricher_rng=enricher_rng,
                country=country,
                injected_index=injected_count,
            )
            existing.add(analyte)
            injected_count += 1


def _pick_target_encounter(record: Any) -> Any | None:
    """Return the first outpatient encounter, else the first encounter, else None."""
    encounters = _get(record, "encounters", []) or []
    if not encounters:
        return None
    for e in encounters:
        if _get(e, "encounter_type", None) == EncounterType.OUTPATIENT:
            return e
    return encounters[0]


def _existing_analytes(record: Any) -> set[str]:
    """Set of canonical analyte names the record already has orders / results for."""
    seen: set[str] = set()
    for o in _get(record, "orders", []) or []:
        name = getattr(o, "display_name", None) or ""
        if name:
            seen.add(canonical_lab_name(name))
        r = getattr(o, "result", None)
        if r is not None:
            lab = getattr(r, "lab_name", None) or ""
            if lab:
                seen.add(canonical_lab_name(lab))
    for r in _get(record, "lab_results", []) or []:
        lab = getattr(r, "lab_name", None) or ""
        if lab:
            seen.add(canonical_lab_name(lab))
    return seen


def _derive_true_labs_for_patient(patient: Any, matched_drugs: list[str]) -> dict[str, float]:
    """Physiology-derived lab true-values with the appropriate medication flags on,
    merged with the BASELINE_LAB_NORMALS reference-normal fallback.

    Delegates to ``physiology.engine.derive_lab_values`` and
    ``medication_flags_from_context`` so the emitted PT_INR (warfarin case)
    lands in the therapeutic 2.0-3.0 band exactly as it would for a
    warfarin patient on a sepsis / AF encounter. Analytes that physiology
    does not model (e.g. TSH — no ``on_levothyroxine`` flag exists yet)
    fall through to ``BASELINE_LAB_NORMALS`` — matches the outpatient
    call site pattern (``simulator/outpatient.py``:229 uses the same
    ``true_labs.get(canon, baseline_values.get(canon, 1.0))`` chain).
    Physiological state is the default-constructed healthy state; the
    enricher's job is a baseline monitoring lab, not an acute-illness
    reflection.
    """
    from clinosim.modules.observation.engine import BASELINE_LAB_NORMALS
    from clinosim.modules.physiology.engine import (
        derive_lab_values,
        medication_flags_from_context,
        scenario_flags_from_protocol,
    )
    from clinosim.types.clinical import PhysiologicalState

    state = PhysiologicalState()
    flags = {
        **scenario_flags_from_protocol(None),
        **medication_flags_from_context(patient),
    }
    sex = getattr(patient, "sex", "M") or "M"
    age = int(getattr(patient, "age", 0) or 0)
    has_dm = any("E11" in (getattr(c, "code", "") or "") for c in getattr(patient, "chronic_conditions", []) or [])
    labs = dict(derive_lab_values(state, sex=sex, age=age, has_diabetes=has_dm, **flags))
    # Merge baseline normals for analytes physiology does not model (e.g. TSH,
    # LDL, HDL, TG, TC, ESR, Ca). Physiology values win when both exist so a
    # medication_flags-driven value (like warfarin PT_INR) is never overwritten.
    for lab_name, ref_val in BASELINE_LAB_NORMALS.items():
        labs.setdefault(lab_name, ref_val)
    return labs


def _inject_one_lab(
    *,
    record: Any,
    encounter: Any,
    patient: Any,
    analyte: str,
    display_name: str,
    loinc: str,
    rationale: str,
    rationale_ja: str,
    drug: str,
    drug_ja: str,
    true_value: float | None,
    enricher_rng: np.random.Generator,
    country: str,
    injected_index: int,
) -> None:
    """Append one synthetic monitoring Order + OrderResult to the record."""
    enc_id = getattr(encounter, "encounter_id", "") or "ENC"
    order_id = f"ORD-{enc_id}-MED-MON-{injected_index:02d}"
    lab_rng = np.random.default_rng(individual_lab_seed(order_id))

    admit_dt = getattr(encounter, "admission_datetime", None)
    if admit_dt is None:
        return

    # Jitter kept small and enricher-scoped so master RNG is unaffected;
    # 10-30 min post-admission mirrors the outpatient lab-draw pattern
    # (a follow-up visit's PT-INR is drawn during the visit, not at hour 0).
    jitter_min = int(enricher_rng.integers(10, 30))
    ordered_dt = admit_dt + timedelta(minutes=jitter_min)

    # Compute observed value via the shared 3-layer noise + physiologic-limit
    # clamp used everywhere else (`clinosim/modules/observation/engine.py`).
    if true_value is None or true_value <= 0:
        return
    observed = generate_lab_result(analyte, float(true_value), lab_rng)
    flag = _determine_flag(analyte, observed, sex=getattr(patient, "sex", "M"), country=country)

    # Issue #871: bilingual `clinical_intent` — EN stays as the CIF canonical
    # (behavior-parseable form used by `_sr_intent_from_clinical_intent`,
    # `medication_pipeline._determine_route`, etc.); JA is display-only and
    # consumed by the JP SR emit path via `_pick_reason_text`. When
    # `rationale_ja` is empty (YAML not yet migrated), leave the JA slot
    # empty so the emit path falls back to the EN string.
    clinical_intent_ja = f"慢性投薬モニタリング ({drug_ja}): {rationale_ja}" if rationale_ja else ""
    order = Order(
        order_id=order_id,
        encounter_id=enc_id,
        patient_id=getattr(patient, "patient_id", "") or "",
        order_type=_lab_order_type(),
        order_code=loinc,
        display_name=display_name,
        urgency="routine",
        clinical_intent=f"Chronic-medication monitoring ({drug}): {rationale}",
        clinical_intent_ja=clinical_intent_ja,
        ordered_datetime=ordered_dt,
        ordered_by=getattr(encounter, "attending_physician_id", "") or "",
        status=OrderStatus.RESULTED,
    )
    result = OrderResult(
        result_datetime=ordered_dt + timedelta(hours=2),
        performed_by="",  # enricher-time synthesis; no per-tech staffing lookup
        lab_name=analyte,
        value=observed,
        unit=get_lab_unit(analyte),
        flag=flag,
    )
    order.result = result

    _append(record, "orders", order)
    _append(record, "lab_results", result)


def _lab_order_type():
    """Local import guard so this module does not pull the whole Enum at import time."""
    from clinosim.types.encounter import OrderType

    return OrderType.LAB


def _append(record: Any, field_name: str, item: Any) -> None:
    """Defensive list-append for records that could be dataclass or dict."""
    lst = getattr(record, field_name, None)
    if isinstance(lst, list):
        lst.append(item)
        return
    if isinstance(record, dict):
        record.setdefault(field_name, []).append(item)
