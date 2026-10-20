"""Backward-compat facade for the historical ``simulator/helpers.py`` grab-bag.

(Issue #544) split the 491-line grab-bag into topic-owned modules.
This file remains as a thin re-export layer so existing callers continue to
work; new code should import from the topic-owned modules directly:

    - ``simulator/discharge_gate.py`` — discharge readiness, readmission,
      mortality
    - ``simulator/hospital_ops.py`` — ward + department resolution
    - ``simulator/patient_writeback.py`` — Layer-1 person / patient cache sync
    - ``modules/disease/localization.py`` — country → YAML key,
      chief-complaint translation, department extraction
    - ``modules/order/route_heuristic.py`` — medication route heuristic

The two housekeeping helpers that did not fit a topic module cleanly
(``_deactivate_to_layer1`` — Layer-1 CIF write-back;
``_select_secondary_disease`` — mixed-condition selection;
``_determine_route`` — order-side medication route heuristic) still live
here for now and will migrate in a follow-up cycle.
"""

from __future__ import annotations

from typing import Any

import numpy as np

# ---------------------------------------------------------------------------
# Backward-compat re-exports (Issue #544). Permanent compatibility shim —
# import from the topic module directly in new code, but existing call
# sites may continue to use these aliases indefinitely.
# ---------------------------------------------------------------------------
from clinosim.modules.disease.localization import (  # noqa: F401
    _country_to_yaml_key,
    _disease_chief_complaint,
    _disease_chief_complaint_ja,
    _disease_to_department,
)
from clinosim.modules.disease.protocol import (
    DiseaseProtocol,
    load_all_disease_protocols,
)
from clinosim.modules.population.engine import HospitalizationSummary, LifeEvent
from clinosim.simulator.discharge_gate import (  # noqa: F401
    _check_discharge_ready,
    _evaluate_mortality,
    _evaluate_readmission,
)
from clinosim.simulator.hospital_ops import pick_ward, resolve_department  # noqa: F401
from clinosim.types.clinical import PhysiologicalState
from clinosim.types.output import CIFPatientRecord
from clinosim.types.patient import HomeMedication, PatientProfile

__all__ = [
    "DiseaseProtocol",
    "HospitalizationSummary",
    "LifeEvent",
    "PhysiologicalState",
    "CIFPatientRecord",
    "PatientProfile",
    # Public loader (Issue #557 rename). The pre-rename underscore alias
    # `_load_all_disease_protocols` was removed after its one-release
    # deprecation cycle; import `load_all_disease_protocols` directly.
    "load_all_disease_protocols",
    # Issue #544 re-exports (kept for one deprecation cycle; import from the
    # topic module in new code — mypy-strict requires explicit `__all__`
    # membership for underscore-prefixed re-exports).
    "_country_to_yaml_key",
    "_disease_chief_complaint",
    "_disease_chief_complaint_ja",
    "_disease_to_department",
    "_check_discharge_ready",
    "_evaluate_mortality",
    "_evaluate_readmission",
    "pick_ward",
    "resolve_department",
    # Housekeeping helpers that still live here (see follow-up cycle).
    "_deactivate_to_layer1",
    "_select_secondary_disease",
    "_determine_route",
]


def _sha_weighted_choice(salt: str, choices: tuple[str, ...], weights: tuple[float, ...]) -> str:
    """Deterministic weighted choice from a SHA256-hashed salt.

    Thin wrapper over :func:`clinosim.determinism.sha_weighted_choice`
    — kept here (plus the `_` prefix) as the historical API that
    ``_promote_stroke_sequela_at_discharge`` and its test harness
    import. New callers should use ``clinosim.determinism`` directly.
    """
    from clinosim.determinism import sha_weighted_choice

    return sha_weighted_choice(salt, choices, weights)


# Mapping from acute-stroke disease_id → (sequela_icd, stage weights).
# Kept inline here (not in a yaml) because the lookup lives at the
# dispatch hot path and the mapping is a single-use convention
# tied to the stroke→sequela promotion. Stage labels / weights live
# authoritatively in ``modules.patient._severity_activation`` and
# are imported lazily to avoid a top-of-file cycle with the
# patient module.
_STROKE_SEQUELA_MAP: dict[str, str] = {
    "cerebral_infarction": "I69.3",
    "hemorrhagic_stroke": "I69.1",
}


def _promote_stroke_sequela_at_discharge(person: Any, disease_id: str, record: Any, summary: Any) -> None:
    """Append the appropriate I69.3 / I69.1 chronic sequela and
    sample an initial mRS stage immediately on survival-at-discharge
    from a stroke encounter.

    Idempotent — a person who already carries the sequela ICD on
    their chronic_conditions list skips without re-sampling. See
    the call site docstring in ``_deactivate_to_layer1`` for the
    clinical rationale and RNG-neutrality note.
    """
    if record.deceased:
        return
    sequela_icd = _STROKE_SEQUELA_MAP.get(disease_id)
    if sequela_icd is None:
        return
    if sequela_icd in person.chronic_conditions:
        return

    # Lazy import to avoid a module-load cycle with
    # clinosim.modules.patient._severity_activation (which imports
    # from population types that re-export via this helpers module).
    from clinosim.modules.patient._severity_activation import (
        I69_1_STAGE_WEIGHTS,
        I69_3_STAGE_WEIGHTS,
        I69_3_STAGES,
    )

    person.chronic_conditions.append(sequela_icd)
    weights = I69_1_STAGE_WEIGHTS if sequela_icd == "I69.1" else I69_3_STAGE_WEIGHTS
    encounter_id = getattr(summary, "encounter_id", "") or ""
    salt = f"{getattr(person, 'person_id', '')}|stroke_mrs|{encounter_id}|v1"
    stage = _sha_weighted_choice(salt, I69_3_STAGES, weights)
    # Phase 2 longitudinal (Issue #1696): stroke-sequela stage lives in
    # the YearSnapshot owned by the longitudinal engine. Write into the
    # snapshot matching the discharge year — the engine will advance it
    # yearly thereafter via the stroke_sequela_i69_* Markov yamls.
    stage_date = getattr(summary, "discharge_date", None)
    stage_year = stage_date.year if stage_date is not None else None
    if stage_year is not None and person.longitudinal_history:
        for snap in person.longitudinal_history:
            if snap.year == stage_year:
                snap.chronic_stages["I69"] = stage
                break
        else:
            # No snapshot for discharge_year yet: write into the latest
            # (engine's advance_one_year typically fills ahead of
            # mid-year hospital discharge).
            person.longitudinal_history[-1].chronic_stages["I69"] = stage


def _deactivate_to_layer1(
    person: Any,
    record: CIFPatientRecord,
    disease_id: str,
    *,
    patient_cache: dict[tuple[str, int | None], PatientProfile],
) -> None:
    """Feed hospital results back to Layer 1 PersonRecord after discharge.

    Updates chronic conditions, medications, and hospitalization history so
    future encounters can reference the patient's medical history.

    A' Phase 1 (Issue #440): also syncs the Layer 2 ``PatientProfile`` held in
    ``patient_cache[(person.person_id, as_of_year)]``. Without this sync a drug newly
    started during the hospitalization never reaches the cached profile, so
    the next encounter's ``_generate_home_medication_orders`` silently omits
    it. ``patient_cache`` is keyword-only + required so a caller cannot drop
    the sync by omitting the argument.
    """
    person.has_visited_hospital = True
    person.visit_count += 1

    if record.encounters:
        enc = record.encounters[0]
        person.last_encounter_id = enc.encounter_id
        person.last_disease_id = disease_id
        if enc.discharge_datetime:
            person.last_discharge_date = enc.discharge_datetime.date()

    dx_code = record.clinical_diagnosis.discharge_diagnosis_code
    if dx_code:
        base_code = dx_code.split(".")[0] if "." in dx_code else dx_code
        chronic_prefixes = ("I", "E", "J44", "J45", "N18", "M", "G20", "F00", "K21", "N40")
        # Issue #947: sex-lock table moved to
        # `clinosim/locale/shared/icd10_sex_restrictions.yaml`. Any
        # anatomy-locked discharge-Dx (BPH N40, prostatitis N41, female-
        # pelvic N70–N77, pregnancy O00–O9A, sex-specific malignancies
        # C50–C63, …) is now blocked from chronic propagation via the
        # unified `sex_gating.is_sex_locked_for` helper.
        from clinosim.simulator.sex_gating import is_sex_locked_for

        _patient_sex = str(getattr(person, "sex", "") or "").upper()[:1]
        if is_sex_locked_for(dx_code, _patient_sex):
            pass  # skip; wrong sex for this ICD
        elif any(base_code.startswith(p) for p in chronic_prefixes):
            existing_bases = {c.split(".")[0] for c in person.chronic_conditions}
            if base_code not in existing_bases:
                person.chronic_conditions.append(base_code)

    # Issue #452 PR 1: `PersonRecord.current_medications` is now
    # `list[HomeMedication]` — carry route / dose / frequency through from
    # `discharge_prescription.items` instead of dropping them.
    #
    # Issue #914 Bucket B: acute short-course therapy (antibiotics
    # `discharge_oral` 7-day course, steroid tapers 5-7 days, PPI H. pylori
    # eradication 14 days) must NOT carry forward as a persistent chronic
    # home medication. Pre-fix, every discharge item — including these
    # finite courses — replaced `person.current_medications`, so the next
    # outpatient visit's prescription-renewal loop (`outpatient.py:325`)
    # re-emitted the antibiotic as if it were a chronic drug. That is how
    # 12 hypertension follow-ups at JP p=1000 s500 acquired 3+ antibiotics
    # despite the encounter being for I10 essential hypertension —
    # discharge Rx from a prior admission was being renewed indefinitely.
    #
    # Cutoff: ``0 < duration_days <= 14`` filters out acute courses (UTI
    # oral abx 7, steroid taper 5-7, PPI eradication 14, etc.) while
    # preserving chronic transcription (``discharge_rx.py`` hardcodes
    # ``duration_days=28`` for chronic renewal and ``duration_days=28``
    # for ``continue_at_discharge`` category defaults) and any longer
    # supply schedule.
    #
    # ``duration_days == 0`` is the disease-YAML convention for "long-term
    # / unspecified" (see e.g. ``atrial_fibrillation_rvr.yaml``'s
    # ``continue_home_medications`` block which sets Apixaban /
    # Metoprolol_succinate with ``duration_days: 0`` to mark them as
    # indefinite AFib therapy). Treating 0 as an acute short course
    # would drop lifelong secondary-prevention drugs from the persistent
    # home-medication list — the exact regression this filter was meant
    # to avoid, in reverse.
    _ACUTE_COURSE_MAX_DAYS = 14
    if record.discharge_prescription and record.discharge_prescription.items:
        new_meds: list[HomeMedication] = []
        for item in record.discharge_prescription.items:
            if not isinstance(item, dict):
                continue
            drug_name = item.get("drug_name") or item.get("drug") or item.get("name") or ""
            if not drug_name:
                continue
            # Issue #914 Bucket B: drop finite courses from the persistent
            # home-medication carry-forward. The discharge Rx itself still
            # emits (the patient did receive the 7-day antibiotic), only
            # the chronic-med list is guarded.
            _dur = item.get("duration_days")
            if _dur is not None:
                try:
                    d = int(_dur)
                    if 0 < d <= _ACUTE_COURSE_MAX_DAYS:
                        continue
                except (TypeError, ValueError):
                    pass
            dq = item.get("dose_quantity")
            try:
                dose_qty = float(dq) if dq is not None and dq != "" else None
            except (TypeError, ValueError):
                dose_qty = None
            new_meds.append(
                HomeMedication(
                    drug_name=str(drug_name),
                    drug_name_ja=str(item.get("drug_name_ja") or ""),
                    route=str(item.get("route") or ""),
                    dose=str(item.get("dose") or ""),
                    dose_quantity=dose_qty,
                    dose_unit=str(item.get("dose_unit") or ""),
                    frequency=str(item.get("frequency") or ""),
                )
            )
        person.current_medications = new_meds

    residual_infl = 0.0
    residual_renal = 1.0
    if record.physiological_states:
        final = record.physiological_states[-1]
        residual_infl = final.inflammation_level
        residual_renal = final.renal_function

    admission_date = record.encounters[0].admission_datetime.date() if record.encounters else None
    discharge_date = person.last_discharge_date
    if admission_date and discharge_date:
        los = (discharge_date - admission_date).days
    else:
        los = len(record.physiological_states) - 1

    summary = HospitalizationSummary(
        encounter_id=person.last_encounter_id or "",
        disease_id=disease_id,
        admission_date=admission_date or discharge_date or record.encounters[0].admission_datetime.date(),
        discharge_date=discharge_date or admission_date or record.encounters[0].admission_datetime.date(),
        los_days=max(1, los),
        outcome="deceased" if record.deceased else "discharged",
        discharge_diagnoses=[dx_code] if dx_code else [disease_id],
        # HospitalizationSummary.discharge_medications remains typed list[str]
        # (historical log). Project HomeMedication → drug_name.
        discharge_medications=[m.drug_name for m in person.current_medications],
        residual_inflammation=residual_infl,
        residual_renal=residual_renal,
        was_readmission=record.is_readmission,
    )
    person.hospitalization_history.append(summary)

    # Issue #1581 extension — immediate (at-discharge) stroke-sequela
    # promotion. If the just-concluded encounter was for an ischemic
    # (cerebral_infarction) or hemorrhagic (hemorrhagic_stroke)
    # stroke AND the patient survived, append the corresponding
    # I69.3 / I69.1 chronic condition and sample an initial mRS
    # stage. Mirrors the aging-pass promotion
    # (``aging._stroke_sequela_promotion``) but fires immediately
    # so subsequent encounters within the same simulated year see
    # the chronic condition rather than waiting for the next
    # year's aging pass to catch up (which was a 1-year
    # classification delay — the analog of the newborn secondary
    # pass issue fixed by META #1596). The initial mRS is sampled
    # via SHA-based deterministic draw keyed by the encounter id
    # so the master RNG stream stays unaffected (RNG-neutral
    # additive pattern — cf.
    # ``feedback_rng_neutral_additive_field``).
    _promote_stroke_sequela_at_discharge(person, disease_id, record, summary)

    # A' Phase 1 (Issue #440) sync: keep the cached Layer 2 profile's
    # `current_medications` in step with the Layer 1 update. Missing key
    # here means an unexpected caller path — fail loud rather than silently
    # no-op.
    # Issue #1581 — the patient_cache is now keyed by
    # ``(person_id, as_of_year)`` tuples so the engine can serve
    # year-aware stage lookups. For the medication sync we only need
    # ONE cached profile for this person (medications are not year-
    # keyed), so we patch every cached variant that matches this
    # person_id. The invariant becomes "at least one variant exists"
    # rather than "exact person_id key exists".
    # patient_cache is now exclusively tuple-keyed per the signature
    # (dict[tuple[str, int | None], PatientProfile]); the str-key
    # fallback path is unreachable since PR #1630 narrowed the type.
    matching_keys = [k for k in patient_cache if k[0] == person.person_id]
    assert matching_keys, (
        f"patient_cache missing person_id={person.person_id!r}. "
        f"Every call site must precede _deactivate_to_layer1 with "
        f"_activate_cached(person)."
    )
    for key in matching_keys:
        patient_cache[key].current_medications = list(person.current_medications)


def _select_secondary_disease(
    patient: PatientProfile,
    primary_disease_id: str,
    protocols: dict[str, DiseaseProtocol],
    rng: np.random.Generator,
) -> DiseaseProtocol | None:
    """Select a secondary disease for mixed conditions based on patient's
    chronic diseases.

    Priority: diseases whose prerequisite_condition matches patient's chronic
    conditions. Fallback: any non-surgical disease different from primary.
    """
    matching = []
    for did, proto in protocols.items():
        if did == primary_disease_id or proto.requires_surgery:
            continue
        matching.append(proto)

    if not matching:
        return None

    # Prefer diseases related to patient's comorbidities.
    # Pneumonia is common secondary for any hospitalized patient.
    preferred = [p for p in matching if p.disease_id == "bacterial_pneumonia"]
    if preferred:
        return preferred[0]

    return rng.choice(matching)


def _determine_route(drug_name: str, clinical_intent: str) -> str:
    """Determine medication administration route (order-side heuristic)."""
    combined = (drug_name + " " + clinical_intent).upper()
    if "IV" in combined or "DRIP" in combined:
        return "IV"
    if "SC" in combined or "SUBCUTANEOUS" in combined or "ENOXAPARIN" in combined.upper():
        return "SC"
    if "IM" in combined:
        return "IM"
    iv_drugs = [
        "AMPICILLIN",
        "SULBACTAM",
        "CEFTRIAXONE",
        "MEROPENEM",
        "FUROSEMIDE",
        "NITROGLYCERIN",
        "VANCOMYCIN",
        "LEVOFLOXACIN",
    ]
    for d in iv_drugs:
        if d in drug_name.upper():
            return "IV"
    return "PO"
