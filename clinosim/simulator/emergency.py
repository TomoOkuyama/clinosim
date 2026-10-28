"""Emergency department visit simulation."""

from __future__ import annotations

import re
from datetime import datetime, timedelta

import numpy as np

from clinosim import determinism
from clinosim.codes import system_key_for
from clinosim.codes.hl7_encounter import ActPriority, AdmitSource, DischargeDisposition
from clinosim.modules.disease.severity import sample_severity_category
from clinosim.modules.encounter.engine import create_inpatient_encounter
from clinosim.modules.observation.engine import get_lab_unit
from clinosim.modules.order.treatment_classifier import classify_encounter_treatment
from clinosim.modules.physiology._vital_signs_thresholds import PAIN_SCORE_SCALE
from clinosim.modules.staff.engine import (
    FALLBACK_PHYSICIAN_ID,
    StaffRoster,
    assign_staff,
)
from clinosim.simulator._ed_thresholds import (
    DEFAULT_TRIAGE_LAB_PANEL,
    DEFAULT_TRIAGE_LAB_PROBABILITY,
    ED_IMAGING_ORDER_OFFSET_MEAN_MIN,
    ED_IMAGING_ORDER_OFFSET_STD_MIN,
    ED_LAB_ORDER_OFFSET_MEAN_MIN,
    ED_LAB_ORDER_OFFSET_STD_MIN,
    ED_LAB_RESULT_OFFSET_MEAN_MIN,
    ED_LAB_RESULT_OFFSET_STD_MIN,
    ED_OBSERVATION_EXTENSION_HOURS,
    ED_OBSERVATION_MAX_EXTENSIONS,
    ED_PAIN_BASELINE,
    ED_PAIN_INFLAMMATION_SCALE,
    ED_PAIN_MAX,
    ED_PAIN_MIN,
    ED_PAIN_NOISE_STD,
    ED_REASSESS_BEFORE_DISCHARGE_MIN,
    ED_RELEASE_PAIN_MAX,
    ED_RELEASE_SBP_MIN,
    ED_RELEASE_SPO2_MIN,
    ED_RELEASE_SPO2_MIN_COPD,
    ED_TREATMENT_ORDER_OFFSET_MEAN_MIN,
    ED_TREATMENT_ORDER_OFFSET_STD_MIN,
    ED_TREATMENT_RESPONSE_FACTOR,
    ED_VITALS_OFFSET_MIN,
)
from clinosim.simulator.vitals_pipeline import _loc_for
from clinosim.types.clinical import ClinicalDiagnosis, ConditionEvent, PhysiologicalState
from clinosim.types.encounter import (
    Encounter,
    EncounterStatus,
    EncounterType,
    Order,
    OrderResult,
    OrderStatus,
    OrderType,
    PrescriptionRecord,
    VitalSignRecord,
)
from clinosim.types.output import CIFPatientRecord
from clinosim.types.patient import PatientProfile

_ED_SYMPTOM_AXES = (
    "pain_level",
    "oxygenation_impairment",
    "sympathetic_activation",
    "consciousness_impairment",
    "respiratory_depression",  # naloxone reversal (Issue #2154)
)


def ed_treatment_response(state: PhysiologicalState) -> PhysiologicalState:
    """State after one round of ED treatment (Issue #2090): symptom axes and a
    volume deficit fall by ``ED_TREATMENT_RESPONSE_FACTOR``; perfusion recovers
    by the same fraction of its deficit. Returns a copy."""
    from copy import deepcopy

    after = deepcopy(state)
    for axis in _ED_SYMPTOM_AXES:
        setattr(after, axis, getattr(after, axis) * ED_TREATMENT_RESPONSE_FACTOR)
    if after.volume_status < 0:
        after.volume_status *= ED_TREATMENT_RESPONSE_FACTOR
    after.perfusion_status = 1.0 - (1.0 - after.perfusion_status) * ED_TREATMENT_RESPONSE_FACTOR
    return after


def ed_release_safe(*, spo2: float, sbp: int, avpu: str, pain: int, copd: bool) -> bool:
    """Treat-and-release criteria on the reassessment vitals (Issue #2090)."""
    spo2_min = ED_RELEASE_SPO2_MIN_COPD if copd else ED_RELEASE_SPO2_MIN
    return spo2 >= spo2_min and sbp >= ED_RELEASE_SBP_MIN and avpu in ("A", "") and pain <= ED_RELEASE_PAIN_MAX


_ED_DISPOSITIONS = {
    "discharge_home": DischargeDisposition.HOME,
    "transfer_psychiatric": DischargeDisposition.PSY,
}


def ed_disposition(protocol: dict | None, severity: str) -> DischargeDisposition:
    """Discharge disposition of an ED visit (Issue #2124): the YAML's
    ``disposition_by_severity`` entry for the sampled severity, else its
    ``disposition``; home when neither maps to a known code."""
    spec = protocol or {}
    key = (spec.get("disposition_by_severity") or {}).get(severity) or spec.get("disposition") or ""
    return _ED_DISPOSITIONS.get(key, DischargeDisposition.HOME)


def ed_diagnosis_code(spec: dict, patient: PatientProfile) -> str:
    """ICD-10 code of an ED visit: the first ``icd10_code_by_chronic_prefix``
    entry whose prefix the patient carries (e.g. recurrent vs single-episode
    depression, Issue #2124), else ``icd10_code``."""
    chronic = [str(getattr(c, "code", c)) for c in getattr(patient, "chronic_conditions", []) or []]
    for prefix, code in (spec.get("icd10_code_by_chronic_prefix") or {}).items():
        if any(c.startswith(prefix) for c in chronic):
            return str(code)
    return str(spec.get("icd10_code", "R69"))  # R69 = Illness, unspecified


def ed_lab_true_value(lab_spec: dict, severity: str, derived: float) -> float:
    """True value of one ED workup analyte: the spec's ``value_by_severity``
    entry for the sampled severity (screening scores such as C-SSRS / PHQ-9
    that the physiology does not model, Issue #2129), else ``derived``."""
    by_severity = lab_spec.get("value_by_severity") or {}
    if severity in by_severity:
        return float(by_severity[severity])
    return derived


def _ed_medication_skipped(
    drug_name: str,
    patient: PatientProfile,
    indication_codes: list[str],
    active_drugs: list[str],
    encounter_id: str,
    visit_time: datetime,
    cond_name: str,
    hint: str,
) -> bool:
    """Demographic and drug-drug gates for an ED medication (ED treatment
    orders and, Issue #2155, discharge prescriptions). Logs the skip on
    ``patient.safety_skip_log`` and returns True when the drug is dropped."""
    from clinosim.modules import drug_safety
    from clinosim.modules.drug_safety import check_demographic_gate
    from clinosim.modules.drug_safety.verdict import SEVERITY_RANK, SafetySkipEntry, SafetyVerdict

    _gate = check_demographic_gate(
        drug_name,
        patient_age=patient.age,
        patient_sex=patient.sex,
        indication_codes=indication_codes,
    )
    if _gate.should_skip:
        # Log the skip so downstream verification / audit can prove the
        # gate fired instead of the drug silently disappearing. Reuse
        # the existing SafetySkipEntry container to share provenance
        # tooling with the DDI gate (drug_safety.check_pair).
        _wrapped = SafetyVerdict(
            severity=_gate.severity,
            rule_id=_gate.rule_id,
            matched_classes=None,
            matched_active_drug=None,
            rationale_en=_gate.rationale_en,
            rationale_ja=_gate.rationale_ja,
            substitution_hint=None,
        )
        _matched = _gate.matched_drug_name or drug_name
        patient.safety_skip_log.append(
            SafetySkipEntry(
                encounter_id=encounter_id,
                candidate_drug=drug_name,
                candidate_drug_ja=drug_name,
                active_conflict=f"demographic:age={patient.age},sex={patient.sex}",
                active_conflict_ja=f"適応外:年齢={patient.age},性別={patient.sex}",
                verdict=_wrapped,
                substituted_with=None,
                substituted_with_ja=None,
                context_hint=f"{hint}_dispatch:{cond_name}:matched={_matched}",
                timestamp=visit_time.isoformat(),
            )
        )
        return True
    # Issue #1347 (META #1392 Cluster A part 4): drug-drug pair
    # gate for ED order emit. Prior to this pass the ED order
    # dispatcher only checked the demographic gate (age/sex
    # rules); it did NOT call ``check_candidate_against_active``
    # so a patient on chronic Rivaroxaban + Celecoxib could
    # receive Ketorolac IV + Ibuprofen PO in the same ED visit
    # (3-NSAID stacking on top of anticoag — massive GI-bleed
    # risk). ``active_drugs`` is the caller's active med set (chronic
    # medications plus the drugs already ordered or prescribed).
    # Drops on "skip" severity (major / contraindicated); logs
    # a SafetySkipEntry so downstream verification can prove the
    # gate fired instead of the drug silently disappearing.
    _ddi_verdicts = drug_safety.check_candidate_against_active(drug_name, active_drugs)
    _ddi_worst = max(
        (v for v in _ddi_verdicts if not v.is_allowed),
        key=lambda v: SEVERITY_RANK[v.severity],
        default=None,
    )
    if _ddi_worst is not None and _ddi_worst.default_action == "skip":
        patient.safety_skip_log.append(
            SafetySkipEntry(
                encounter_id=encounter_id,
                candidate_drug=drug_name,
                candidate_drug_ja=(drug_safety.japanese_display(drug_name) or drug_name),
                active_conflict=_ddi_worst.matched_active_drug or "",
                active_conflict_ja=(
                    drug_safety.japanese_display(_ddi_worst.matched_active_drug or "")
                    or (_ddi_worst.matched_active_drug or "")
                ),
                verdict=_ddi_worst,
                substituted_with=None,
                substituted_with_ja=None,
                context_hint=f"{hint}_ddi:{cond_name}",
                timestamp=visit_time.isoformat(),
            )
        )
        return True
    return False


# Strength written into a protocol drug name ("Ibuprofen 600mg",
# "Amoxicillin/clavulanate 875/125mg"); a discharge prescription item
# carries it as ``dose`` unless the entry declares one.
_DOSE_IN_NAME = re.compile(r"\d[\d.]*(?:/\d[\d.]*)*\s*(?:mg|mcg|g|mL|%)", re.IGNORECASE)


def _ed_discharge_prescription(
    protocol: dict | None,
    patient: PatientProfile,
    encounter: Encounter,
    indication_codes: list[str],
    country: str,
    cond_name: str,
) -> PrescriptionRecord | None:
    """Take-home prescriptions of a treat-and-release or clinic visit (Issue #2155).

    Each ``discharge_prescriptions[]`` entry is drawn with its
    ``probability`` from a per-encounter sub-seed (the inpatient discharge
    seed, AD-16), so the draw leaves every other event of the cohort
    unchanged. ``locale_exclude`` / ``locale_name`` work as on
    ``treatment[]``; the demographic and drug-drug gates of ED treatment
    orders apply against the chronic medications and the drugs already
    prescribed. Visits that do not end at home carry no prescription.
    """
    from clinosim.modules import drug_safety
    from clinosim.seeding import discharge_prescription_seed

    specs = (protocol or {}).get("discharge_prescriptions") or []
    if not specs or encounter.discharge_disposition != DischargeDisposition.HOME:
        return None
    # An ED take-home script is written at departure; a clinic visit's
    # prescription is dated at the visit start, like the outpatient renewal.
    issued = (
        encounter.discharge_datetime or encounter.admission_datetime
        if encounter.encounter_type == EncounterType.EMERGENCY
        else encounter.admission_datetime
    )
    rng = determinism.default_rng(discharge_prescription_seed(patient.patient_id, encounter.encounter_id))
    country_key = "jp" if str(country).lower() in ("jp", "japan") else "us"
    active = [m.drug_name for m in (patient.current_medications or []) if m.drug_name]
    items: list[dict] = []
    for spec in specs:
        if rng.random() > spec.get("probability", 1.0):
            continue
        if country.upper() in {str(c).upper() for c in spec.get("locale_exclude") or []}:
            continue  # not marketed in this country; drawn above to keep the stream
        name = str((spec.get("locale_name") or {}).get(country_key) or spec.get("drug", ""))
        if not name or _ed_medication_skipped(
            name,
            patient,
            indication_codes,
            active,
            encounter.encounter_id,
            issued,
            cond_name,
            "ed_discharge_rx",
        ):
            continue
        active.append(name)
        # Item shape of the inpatient discharge prescription: the drug name
        # without its strength, which goes in ``dose``.
        strength = m.group(0) if (m := _DOSE_IN_NAME.search(name)) else ""
        drug = " ".join(_DOSE_IN_NAME.sub("", name).split()) or name
        items.append(
            {
                "drug_name": drug,
                "drug_name_ja": drug_safety.japanese_display(drug) or "",
                "dose": str(spec.get("dose") or strength),
                "route": str(spec.get("route", "PO")),
                "frequency": str(spec.get("frequency", "")),
                "duration_days": spec.get("duration_days"),
            }
        )
    if not items:
        return None
    return PrescriptionRecord(
        prescription_id=f"RX-{patient.patient_id}-{encounter.encounter_id}",
        patient_id=patient.patient_id,
        prescriber_id=encounter.attending_physician_id,
        issue_date=issued,
        items=items,
    )


def _simulate_ed_visit(
    patient: PatientProfile,
    condition: dict,
    visit_time: datetime,
    roster: StaffRoster,
    rng: np.random.Generator,
    country: str = "US",
    config: object | None = None,
    force_severity: str | None = None,
    allowed_severities: tuple[str, ...] | None = None,
) -> CIFPatientRecord:
    """Simulate an ED visit using YAML protocol if available, else basic.

    Issue #345: `force_severity` bypasses the stochastic
    `sample_severity_category` call so enumeration mode can generate one
    patient per (encounter × severity) combination deterministically. Value
    must be a key already declared in the encounter YAML's
    `severity_distribution` (or a naturally supported category such as
    "moderate" when the YAML omits severity — routine outpatient scheduled
    visits). None preserves the legacy stochastic behavior.
    """
    from clinosim.modules.observation.engine import (
        canonical_lab_name,
        determine_flag,
        generate_lab_result,
        is_qualitative_test,
    )
    from clinosim.modules.physiology.engine import (
        apply_disease_onset,
        derive_lab_values,
        derive_observed_vitals,
        initialize_state,
        medication_flags_from_context,
        scenario_flags_from_protocol,
    )

    # Try to load detailed YAML protocol
    cond_name = condition.get("name", condition.get("condition_id", "ed_visit"))
    try:
        from clinosim.modules.encounter.protocol import load_encounter_condition

        protocol = load_encounter_condition(cond_name)
    except (FileNotFoundError, Exception):
        protocol = None

    from clinosim.locale.text import resolve_text

    raw_chief = (protocol or condition).get("chief_complaint", cond_name)
    chief = resolve_text(raw_chief, country=country)

    encounter = create_inpatient_encounter(
        patient.patient_id,
        visit_time,
        chief_complaint=chief,
    )
    # Issue #360 G1 (iris4h-ai 2026-07-22): store JP chief on the JP field
    # regardless of the country param so a downstream JP FHIR emission on a
    # US-generated CIF still has a JP fallback (rare but supported).
    _chief_ja = resolve_text(raw_chief, language="ja")
    _chief_en = resolve_text(raw_chief, language="en")
    if _chief_ja and _chief_ja != _chief_en:
        encounter.chief_complaint_ja = _chief_ja
    proto_enc_type = (protocol or condition).get("encounter_type", "emergency")
    encounter.encounter_type = EncounterType.OUTPATIENT if proto_enc_type == "outpatient" else EncounterType.EMERGENCY
    encounter.status = EncounterStatus.COMPLETED

    # Issue #915: ED encounters must draw the attending physician from the
    # emergency-medicine pool (DR-EM-*), not the internal-medicine pool. The
    # pre-fix hardcoded "internal_medicine" left every generated DR-EM
    # practitioner unreferenced by any Encounter — a real ED is staffed by
    # emergency-medicine specialists, not internists moonlighting.
    # ``assign_staff`` falls through to any physician if the roster has no
    # DR-EM (small hospitals / test fixtures), so the change is safe when
    # the ED specialty pool is empty.
    staff = assign_staff("admission", "emergency_medicine", roster, rng)
    encounter.attending_physician_id = staff.get("attending_physician", FALLBACK_PHYSICIAN_ID)

    # ED stay duration from protocol or default
    if protocol:
        # Shared categorical severity primitive (FP-SEV-MODEL). ED encounter YAML
        # carries no modifiers/minimum, so pass []/None; the sampled category is the
        # single source used for triage + ed_stay_hours.
        # Issue #345: enumeration mode passes force_severity to skip
        # stochastic sampling so every (encounter × severity) combination is
        # exercised deterministically.
        if force_severity is not None:
            severity = force_severity
        else:
            sev_dist = protocol.get("severity_distribution", {})
            if allowed_severities is not None:
                # Issue #2132: severities the hospital admits are not ED-only visits.
                sev_dist = {s: (p if s in allowed_severities else 0.0) for s, p in sev_dist.items()}
            severity = sample_severity_category(sev_dist, [], patient, rng, None)
        stay_cfg = protocol.get("ed_stay_hours", {}).get(severity, {"mean": 3, "sd": 1})
        ed_hours = float(rng.normal(stay_cfg["mean"], stay_cfg["sd"]))
    else:
        severity = force_severity or "moderate"
        ed_hours = float(rng.normal(3.5, 1.0))
    encounter.discharge_datetime = visit_time + timedelta(hours=max(1, ed_hours))
    # AD-65 Bug C fix: persist sampled severity onto the Encounter so the
    # POST_ENCOUNTER triage_enricher (clinosim/modules/triage/engine.py) can read
    # it instead of silently defaulting to "moderate" for every ED encounter
    # (root cause of all-L2-L4, zero-L1/L5 triage_level distribution).
    encounter.severity = severity

    # Pre-assign a lab tech for this visit's labs
    lab_tech_assignment = assign_staff("lab_collection", "laboratory", roster, rng)
    lab_tech_id = lab_tech_assignment.get("performing_technician", "")

    orders: list[Order] = []
    lab_results: list[OrderResult] = []

    # Labs from protocol workup
    workup = (protocol or {}).get("workup", {})
    lab_specs = workup.get("labs", [])
    if not lab_specs and not protocol:
        # Default: basic triage-lab panel (see _ed_thresholds.py)
        if rng.random() < DEFAULT_TRIAGE_LAB_PROBABILITY:
            lab_specs = list(DEFAULT_TRIAGE_LAB_PANEL)

    # Comorbidity-aware true values via the same physiology path as inpatient (AD-57):
    # a baseline state built from the patient's chronic conditions (CKD → high Cr, etc.),
    # then derive_lab_values. baseline_values is the reference-normal fallback for analytes
    # physiology doesn't model (HbA1c/WBC/CRP etc. resolve via _true_labs first). DET-6.
    from clinosim.modules.observation.engine import BASELINE_LAB_NORMALS

    baseline_values = BASELINE_LAB_NORMALS
    _state = initialize_state(patient.physiological_profile, patient.chronic_conditions, patient.patient_id)
    _state.timestamp = visit_time
    # Acute-presentation injection (AD-57): fold the ED scenario's physiological impact (by
    # the sampled severity) into the state so BOTH labs and vitals reflect the acute illness
    # (e.g. UTI → WBC/CRP/temp up, gastroenteritis → dehydration), not just the comorbidity
    # baseline. Data-driven from the encounter YAML's optional initial_state_impact, reusing
    # the same physiology entry point as inpatient onset. No new RNG draws (determinism).
    if protocol and protocol.get("initial_state_impact"):
        _state = apply_disease_onset(
            _state,
            severity,
            protocol["initial_state_impact"],
            acid_base_type=protocol.get("acid_base_type", "metabolic"),
        )
    _has_dm = any("E11" in (getattr(c, "code", "") or "") for c in patient.chronic_conditions)
    _has_dyslipidemia = any("E78" in (getattr(c, "code", "") or "") for c in patient.chronic_conditions)
    # J5 (Phase 2a): wire all scenario flags (causes_myocardial_injury,
    # causes_vte) through the helper. Pre-Phase-2a, the ED path passed no
    # flag — ED-presentation MI patients had no troponin upshift.
    # Phase 2b (2026-06-24): also merge medication flags (on_warfarin).
    # ED is admit-day; no in-hospital ramp (no MAR / day-into-stay applies) —
    # chronic-only path runs via patient.current_medications.
    _flags = {
        **scenario_flags_from_protocol(protocol),
        **medication_flags_from_context(patient),
    }
    from clinosim.modules.physiology.engine import hba1c_latent_at as _hba1c_latent_at

    _hba1c_latent = _hba1c_latent_at(patient, visit_time)
    _true_labs = derive_lab_values(
        _state,
        sex=patient.sex,
        age=patient.age,
        has_diabetes=_has_dm,
        has_dyslipidemia=_has_dyslipidemia,
        hba1c_latent=_hba1c_latent,
        **_flags,
    )
    # AD-16: per-lab-order sub-RNG so probability skips / noise / timing draws
    # cannot poison the patient master stream when derive_lab_values gains a new
    # analyte (Cl/Ca emission, etc.). See inpatient.py Pass 1 for the parallel
    # fix on the inpatient side.
    from clinosim.seeding import individual_lab_seed

    for i, lab_spec in enumerate(lab_specs):
        test = lab_spec.get("test", "")
        order_id = f"ORD-{encounter.encounter_id}-ED-L{i}"
        lab_rng = np.random.default_rng(individual_lab_seed(order_id))
        prob = lab_spec.get("probability", 1.0)
        if lab_rng.random() > prob:
            continue
        # Skip non-quantitative diagnostics (e.g. ECG) misfiled under labs — not lab
        # analytes, must not get a fabricated value (AD-57 cleanup).
        canon = canonical_lab_name(test)
        # Qualitative tests (urinalysis, urine drug screen, …) have no numeric
        # baseline but are real results (Issue #2138: previously dropped).
        if canon not in _true_labs and canon not in baseline_values and not is_qualitative_test(canon):
            continue
        order = Order(
            order_id=order_id,
            patient_id=patient.patient_id,
            order_type=OrderType.LAB,
            display_name=test,
            urgency="stat",
            clinical_intent=f"ED workup: {test}",
            # Issue #871: JA display for JP SR reasonCode.text.
            clinical_intent_ja=f"救急外来精査: {test}",
            ordered_datetime=visit_time
            + timedelta(minutes=int(lab_rng.normal(ED_LAB_ORDER_OFFSET_MEAN_MIN, ED_LAB_ORDER_OFFSET_STD_MIN))),
            ordered_by=encounter.attending_physician_id,
            status=OrderStatus.PLACED,
        )
        true_val = ed_lab_true_value(lab_spec, severity, _true_labs.get(canon, baseline_values.get(canon, 1.0)))
        dist = lab_spec.get("result_distribution")
        observed: float | str
        if dist and is_qualitative_test(canon):
            # Condition-specific categorical result (Issue #2138), e.g. pyuria
            # in cystitis rather than the generic dipstick mix.
            observed = str(lab_rng.choice(list(dist["options"]), p=list(dist["weights"])))
        else:
            observed = generate_lab_result(canon, true_val, lab_rng)
        flag = determine_flag(canon, observed, sex=patient.sex, country=country)
        order.result = OrderResult(
            result_datetime=visit_time
            + timedelta(minutes=int(lab_rng.normal(ED_LAB_RESULT_OFFSET_MEAN_MIN, ED_LAB_RESULT_OFFSET_STD_MIN))),
            performed_by=lab_tech_id,
            lab_name=canon,
            value=observed,
            unit=get_lab_unit(canon),
            flag=flag,
        )
        order.status = OrderStatus.RESULTED
        orders.append(order)
        lab_results.append(order.result)

    # Imaging from protocol
    for i, img_spec in enumerate(workup.get("imaging", [])):
        test = img_spec.get("test", "")
        if rng.random() > img_spec.get("probability", 1.0):
            continue
        orders.append(
            Order(
                order_id=f"ORD-{encounter.encounter_id}-ED-I{i}",
                patient_id=patient.patient_id,
                order_type=OrderType.IMAGING,
                display_name=test,
                urgency="stat",
                clinical_intent=f"ED imaging: {test}",
                # Issue #871: JA display for JP SR reasonCode.text.
                clinical_intent_ja=f"救急外来画像検査: {test}",
                ordered_datetime=visit_time
                + timedelta(minutes=int(rng.normal(ED_IMAGING_ORDER_OFFSET_MEAN_MIN, ED_IMAGING_ORDER_OFFSET_STD_MIN))),
                ordered_by=encounter.attending_physician_id,
                status=OrderStatus.PLACED,
            )
        )

    # Issue #1316 / #1328: demographic contraindication gate. Pediatric
    # Aspirin (Reye's syndrome), pediatric Nitroglycerin, and non-adult-male
    # Tamsulosin all leaked into ED treatment orders through this loop
    # before the gate was wired. The gate runs on MEDICATION-classified
    # entries only; PROCEDURE / THERAPY entries (e.g. "Foley catheter
    # insertion", "IV normal saline") never carry age/sex contraindications
    # in the current catalog. Gate rules are declarative
    # (drug_safety/reference_data/demographic_gates.yaml); adding a new
    # rule requires no changes to this dispatcher.

    _proto_icd = (protocol or condition).get("icd10_code")
    _indication_codes: list[str] = []
    if _proto_icd:
        _indication_codes.append(str(_proto_icd))
    for _cc in patient.chronic_conditions:
        _cc_code = getattr(_cc, "code", None) or getattr(_cc, "icd10_code", None)
        if _cc_code:
            _indication_codes.append(str(_cc_code))

    # Treatment orders from protocol — classify via the canonical
    # treatment_classifier (single source of truth shared with the inpatient
    # supportive path in modules/order/engine.py; J5 pattern prevention).
    # Default is MEDICATION; non-drug names route to PROCEDURE or THERAPY.
    # Issue #1323: locale-aware treatment name — a ``treatment[]`` item may
    # carry an optional ``locale_name: {jp: "...", us: "..."}`` map that
    # picks the country-appropriate drug string (e.g. Prednisolone JP /
    # Prednisone US for the same active corticosteroid). Old entries with
    # only ``name`` keep working unchanged. Country key mirrors the disease-
    # yaml supportive[] ``locale_detail`` split in modules/order/engine.py.
    _tx_country_key = "jp" if str(country).lower() in ("jp", "japan") else "us"
    for i, tx in enumerate((protocol or {}).get("treatment", [])):
        if rng.random() > tx.get("probability", 1.0):
            continue
        if country.upper() in {str(c).upper() for c in tx.get("locale_exclude") or []}:
            continue  # not marketed in this country (Issue #2136); drawn above to keep the stream
        _locale_name = tx.get("locale_name") or {}
        _tx_name = str(_locale_name.get(_tx_country_key) or tx.get("name", ""))
        _order_type = classify_encounter_treatment(_tx_name)
        if _order_type == OrderType.MEDICATION:
            _active_ed = [m.drug_name for m in (patient.current_medications or []) if m.drug_name] + [
                str(o.display_name) for o in orders if o.order_type == OrderType.MEDICATION and o.display_name
            ]
            if _ed_medication_skipped(
                _tx_name,
                patient,
                _indication_codes,
                _active_ed,
                encounter.encounter_id,
                visit_time,
                cond_name,
                "ed_treatment",
            ):
                continue
        orders.append(
            Order(
                order_id=f"ORD-{encounter.encounter_id}-ED-T{i}",
                patient_id=patient.patient_id,
                order_type=_order_type,
                display_name=_tx_name,
                urgency="stat",
                clinical_intent=f"ED treatment: {tx.get('intent', _tx_name)}",
                # Issue #871: JA display for JP SR reasonCode.text. `tx["intent"]`
                # or `_tx_name` are kept as-is (may be EN or already-JA
                # depending on the source); the shell is translated.
                clinical_intent_ja=f"救急外来治療: {tx.get('intent', _tx_name)}",
                ordered_datetime=visit_time
                + timedelta(
                    minutes=int(rng.normal(ED_TREATMENT_ORDER_OFFSET_MEAN_MIN, ED_TREATMENT_ORDER_OFFSET_STD_MIN))
                ),
                ordered_by=encounter.attending_physician_id,
                status=OrderStatus.PLACED,
            )
        )

    # Vitals — physiology-driven via the same derivation path as inpatient (AD-57):
    # true values come from the comorbidity-adjusted state, then measurement noise.
    ed_nurse_id = assign_staff("medication_administration", "emergency_medicine", roster, rng).get(
        "administering_nurse", ""
    )  # noqa: E501
    vit_time = visit_time + timedelta(minutes=ED_VITALS_OFFSET_MIN)
    raw = derive_observed_vitals(_state, patient.baseline_vitals, vit_time, rng)
    # ED presentations are acute → pain skews higher, scaled by inflammation.
    _pain_mean = _state.inflammation_level * ED_PAIN_INFLAMMATION_SCALE + ED_PAIN_BASELINE
    pain = int(max(ED_PAIN_MIN, min(ED_PAIN_MAX, rng.normal(_pain_mean, ED_PAIN_NOISE_STD))))
    if _state.pain_level:
        pain = max(pain, int(min(ED_PAIN_MAX, round(_state.pain_level * PAIN_SCORE_SCALE))))
    # AVPU (Issue #2081): ED triage assesses consciousness from the state
    # (consciousness axis, then perfusion); scheduled clinic visits do not
    # assess it, so no AVPU / GCS is recorded for them.
    if proto_enc_type == "outpatient":
        avpu = ""
    else:
        avpu = _loc_for(_state, "", 0, rng)
    vitals = [
        VitalSignRecord(
            timestamp=vit_time,
            temperature_celsius=round(raw["temperature"], 1),
            heart_rate=int(round(raw["heart_rate"])),
            systolic_bp=int(round(raw["systolic_bp"])),
            diastolic_bp=int(round(raw["diastolic_bp"])),
            respiratory_rate=int(round(raw["respiratory_rate"])),
            spo2=round(raw["spo2"], 1),
            pain_score=pain,
            consciousness_level=avpu,
            measured_by=ed_nurse_id,
            data_source="manual",
        )
    ]

    # Post-treatment reassessment before treat-and-release (Issue #2090): one
    # treatment round, reassessment vitals shortly before departure, and
    # observation extensions (with another treatment round) until the release
    # criteria are met. Scheduled clinic visits are not reassessed.
    if proto_enc_type != "outpatient":
        _cond_id = str((protocol or condition).get("condition_id") or cond_name)
        _copd = _cond_id.startswith("copd")
        _reassess = ed_treatment_response(_state)
        for _round in range(ED_OBSERVATION_MAX_EXTENSIONS + 1):
            _t = encounter.discharge_datetime - timedelta(minutes=ED_REASSESS_BEFORE_DISCHARGE_MIN)
            _t = max(_t, vit_time + timedelta(minutes=ED_REASSESS_BEFORE_DISCHARGE_MIN))
            _raw = derive_observed_vitals(_reassess, patient.baseline_vitals, _t, rng)
            _pain = int(min(ED_PAIN_MAX, max(ED_PAIN_MIN, round(_reassess.pain_level * PAIN_SCORE_SCALE))))
            _avpu = _loc_for(_reassess, "", 0, rng)
            vitals.append(
                VitalSignRecord(
                    timestamp=_t,
                    temperature_celsius=round(_raw["temperature"], 1),
                    heart_rate=int(round(_raw["heart_rate"])),
                    systolic_bp=int(round(_raw["systolic_bp"])),
                    diastolic_bp=int(round(_raw["diastolic_bp"])),
                    respiratory_rate=int(round(_raw["respiratory_rate"])),
                    spo2=round(_raw["spo2"], 1),
                    pain_score=_pain,
                    consciousness_level=_avpu,
                    measured_by=ed_nurse_id,
                    data_source="manual",
                    nursing_note="reassessment",
                )
            )
            if _round == ED_OBSERVATION_MAX_EXTENSIONS or ed_release_safe(
                spo2=_raw["spo2"], sbp=int(round(_raw["systolic_bp"])), avpu=_avpu, pain=_pain, copd=_copd
            ):
                break
            encounter.discharge_datetime += timedelta(hours=ED_OBSERVATION_EXTENSION_HOURS)
            _reassess = ed_treatment_response(_reassess)

    # Enrich medication orders + assign encounter_id
    from clinosim.modules.order.engine import enrich_medication_order

    for o in orders:
        if o.order_type == OrderType.MEDICATION:
            enrich_medication_order(o)
        if not o.encounter_id:
            o.encounter_id = encounter.encounter_id

    # ED encounter metadata
    encounter.admit_source = AdmitSource.OUTP
    encounter.discharge_disposition = ed_disposition(protocol, severity)
    encounter.priority = ActPriority.EM
    encounter.admitting_physician_id = encounter.attending_physician_id
    encounter.discharging_physician_id = encounter.attending_physician_id
    discharge_rx = _ed_discharge_prescription(protocol, patient, encounter, _indication_codes, country, cond_name)

    # Use ICD-10 from encounter YAML (required by FHIR R4)
    icd_code = ed_diagnosis_code(protocol or condition, patient)
    (protocol or condition).get("icd10_display", chief or cond_name)

    # C1-09: emit bedside procedures for ED severe cases.
    # Reuse the existing procedure engine (already keyed by internal condition
    # id) so we don't duplicate the SNOMED / CPT / K-code table. Sampled at the
    # ED encounter rng stream, deterministic (AD-16).
    from clinosim.modules.procedure.engine import generate_bedside_procedures

    ed_procedures = (
        generate_bedside_procedures(
            patient.patient_id,
            encounter.encounter_id,
            cond_name,
            encounter.admission_datetime,
            severity,
            rng,
            country=country,
        )
        if severity in ("moderate", "severe")
        else []
    )

    record = CIFPatientRecord(
        patient=patient,
        encounters=[encounter],
        orders=orders,
        vital_signs=vitals,
        lab_results=lab_results,
        procedures=ed_procedures,
        discharge_prescription=discharge_rx,
        condition_event=ConditionEvent(
            condition_id=f"COND-{patient.patient_id}-ED",
            condition_type="ed_visit",
            ground_truth_diseases=[cond_name],
        ),
        clinical_diagnosis=ClinicalDiagnosis(
            admission_diagnosis_code=icd_code,
            admission_diagnosis_system=system_key_for("diagnosis", country),
            discharge_diagnosis_code=icd_code,
            discharge_diagnosis_system=system_key_for("diagnosis", country),
        ),
    )

    # POST_ENCOUNTER stage for ED encounters (α-min-2 Task 14 fix)
    # triage_enricher (order=93) populates triage_data; document_enricher (order=95)
    # dispatches ED_NOTE + ED_TRIAGE_NOTE for EMERGENCY encounters.
    # Only fires when config is provided (engine.py passes it; cli test-ed does not).
    if config is not None:
        from clinosim.simulator.enrichers import (
            POST_ENCOUNTER,
            EnricherContext,
            run_stage,
        )

        run_stage(
            POST_ENCOUNTER,
            EnricherContext(
                config=config,
                master_seed=config.random_seed,  # type: ignore[attr-defined]
                records=[record],
                roster=roster,
            ),
        )

    return record
