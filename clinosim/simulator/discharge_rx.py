"""Discharge-prescription builder — extracted from `simulator/inpatient.py`.

Renal-hold filtering, exclusive-class categorical selection, chronic-medication
transcription, and disease-YAML `continue_at_discharge` continuation live here.
Called from `simulator/inpatient.py::_simulate_patient` at the discharge site.

Related design references (kept in one place for the discharge chain):
- Issue #432 : `exclusive_classes` categorical selection for `discharge_oral`
- Issue #437 : `continue_at_discharge` category flag reader
- Issue #439 : per-(patient, encounter) sub-RNG isolation (AD-16 pattern)
- Issue #440 : `_deactivate_to_layer1` sync + short-term drug_name_ja threading
- Issue #442 : structured dose / route / drug_name_ja end-to-end threading
- Issue #452 : `HomeMedication` migration
- Issue #476 : `dose_ja` / `dose_en` authored instruction propagation
- Issue #433 : `baseline_chronic_medications` immutable snapshot for
              renal-hold restart
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import datetime
from typing import Any

import numpy as np

from clinosim import determinism
from clinosim.codes.drugs import drug_classes, drug_display, drug_key
from clinosim.locale.i18n import t
from clinosim.locale.localized import language_slot
from clinosim.modules.disease.protocol import DiseaseProtocol
from clinosim.modules.physiology.renal_thresholds import DISCHARGE_RENAL_HOLD_THRESHOLD
from clinosim.types.encounter import PrescriptionRecord
from clinosim.types.patient import PatientProfile


def _age_years_at(patient: PatientProfile, when: datetime) -> int | None:
    """The patient's completed years at ``when`` (None without a date of
    birth): the age a discharge_oral entry's ``age_min`` / ``age_max`` gate
    reads (Issue #3264)."""
    from clinosim.modules.observation.pediatric_ranges import age_in_completed_months

    months = age_in_completed_months(getattr(patient, "date_of_birth", None), when)
    return None if months is None else months // 12


def renal_hold_drugs() -> frozenset[str]:
    """Drugs held at discharge when renal function is impaired: the shared
    renal drug list (``simulator/reference_data/renal_medication_rules.yaml``; Issue
    #2296), used with ``final_renal_function < DISCHARGE_RENAL_HOLD_THRESHOLD``
    (KDIGO stage 3b+ CKD or active AKI)."""
    from clinosim.simulator.medication_pipeline import renal_medication_rules

    return frozenset(renal_medication_rules())  # drug keys (Issue #2377)


def _dedup_key(name: str) -> str:
    """Cross-source drug dedup key: the catalog drug_id, else the normalised
    name (Issue #2377: "Amlodipine" and "アムロジピン" are one drug)."""
    return drug_key(name)


def _discharge_protocol_hold_reason_en(disease_id: str | None) -> str:
    """EN hold_reason for a disease-protocol-driven discharge medication hold.

    Phase 1c-5 (2026-09-23): the human-readable EN form replaces the
    machine-slug ``<disease_id> protocol hold`` that used to appear
    verbatim in narratives. When ``disease_id`` is a known complication
    slug (``heart_failure_exacerbation`` / ``acute_kidney_injury`` /
    …) the humanised ``_COMPLICATION_EN`` display is used; otherwise
    the slug is passed through so a novel disease surfaces something
    rather than being dropped.
    """
    from clinosim.modules.document.narrative.template_generator import (
        _localize_complication,
    )

    if not disease_id:
        return t("order_intent.discharge_protocol", "en")
    label = _localize_complication(disease_id, "en") or disease_id
    # Phase 1d-73: return a bare noun phrase (no "held per…" prefix)
    # so the narrative template `- {considered} was held … because of
    # {conflict}.` doesn't compose into "…because of held per…" (a
    # broken second "held"). Sibling ``_discharge_protocol_hold_reason_ja``
    # applies the same reformulation for JA.
    return t("order_intent.disease_discharge_protocol", "en", disease=label)


def _discharge_protocol_hold_reason_ja(disease_id: str | None) -> str:
    """JA hold_reason for a disease-protocol-driven discharge medication hold.

    Phase 1c-5 (2026-09-23): pre-fix the JP p=10000 audit found the raw
    slug (``heart_failure_exacerbation protocol による保留``) leaking into
    JA narratives (~2,900 occurrences). Route the disease_id through
    ``_localize_complication`` so JA reads 「心不全増悪のプロトコルに
    よる保留」.
    """
    from clinosim.modules.document.narrative.template_generator import (
        _localize_complication,
    )

    if not disease_id:
        return t("order_intent.discharge_protocol", "ja")
    label = _localize_complication(disease_id, "ja") or disease_id
    # Phase 1d-73: bare noun phrase (no 「保留」 suffix) so the JA
    # narrative template 「・{considered}：{conflict}のため今回入院中
    # は保留。」 doesn't collapse into "…保留のため…保留" (二重「保留」).
    return t("order_intent.disease_discharge_protocol", "ja", disease=label)


def _log_discharge_hold(
    patient: PatientProfile,
    encounter_id: str,
    held_drug_name: str,
    held_drug_name_ja: str,
    hold_reason: str,
    hold_reason_ja: str,
    timestamp: datetime,
    taken: frozenset[str] | None = None,
) -> None:
    """Issue #1403: record a discharge-Rx hold (renal-threshold or
    disease-protocol medication_holds) on ``patient.safety_skip_log``.
    Sister of ``medication_pipeline._log_disease_medication_hold`` for
    the discharge side. See that helper for the rationale.

    Issue #2992: "held" describes a drug the patient was taking. With
    ``taken`` (drug keys of the home medications and the stay's medication
    orders), a drug outside it is not logged: a protocol discharge drug the
    patient never started is simply not prescribed.
    """
    if taken is not None and drug_key(held_drug_name) not in taken:
        return
    from clinosim.modules.drug_safety.verdict import (
        SafetySkipEntry,
        SafetyVerdict,
    )

    verdict = SafetyVerdict(
        severity="major",
        rule_id="discharge-medication-hold",
        matched_classes=None,
        matched_active_drug=hold_reason,
        rationale_en=t("order_intent.discharge_hold", "en", reason=hold_reason),
        rationale_ja=t("order_intent.discharge_hold", "ja", reason=hold_reason_ja),
        substitution_hint=None,
    )
    patient.safety_skip_log.append(
        SafetySkipEntry(
            encounter_id=encounter_id,
            candidate_drug=held_drug_name,
            candidate_drug_ja=held_drug_name_ja,
            active_conflict=hold_reason,
            active_conflict_ja=hold_reason_ja,
            verdict=verdict,
            substituted_with=None,
            substituted_with_ja=None,
            context_hint=hold_reason,
            timestamp=timestamp.isoformat(),
            event_type="hold",
        )
    )


def limit_triple_antithrombotic(items: list[dict], home_medications: list[str]) -> None:
    """Issue #2717: with an oral anticoagulant (on this prescription or at
    home), dual antiplatelet therapy becomes the anticoagulant + clopidogrel,
    and aspirin a short course (not carried into the home medications).
    Issue #3234: the in-stay gate of an ACS admission applies the same plan
    (``drug_safety.acs_plan_action``)."""
    from clinosim.modules import drug_safety
    from clinosim.modules.drug_safety.engine import triple_therapy_after_acs_plan

    def classes(name: str) -> set[str]:
        return set(drug_safety.resolve_classes(name) or ())

    names = [str(i.get("drug_name", "") or "") for i in items]
    on_oac = any({"anticoagulant.doac", "anticoagulant.vka"} & classes(n) for n in [*names, *home_medications] if n)
    p2y12 = [i for i in items if "antiplatelet.p2y12" in classes(str(i.get("drug_name", "")))]
    aspirin = [i for i in items if "antiplatelet.cox_inhibitor" in classes(str(i.get("drug_name", "")))]
    if not (on_oac and p2y12 and aspirin):
        return
    plan = triple_therapy_after_acs_plan()
    keep = drug_safety.acs_plan_p2y12_names()
    for item in p2y12:
        if item["drug_name"] != keep.get("en"):
            item["drug_name"] = keep.get("en", item["drug_name"])
            item["drug_name_ja"] = keep.get("ja", item.get("drug_name_ja", ""))
            item["dose"] = str(plan.get("p2y12_dose", item.get("dose", "")))
    for item in aspirin:
        item["duration_days"] = int(plan.get("aspirin_days", 7))


def _resolve_item_dose(
    spec: dict[str, Any],
    home_meds: Iterable[Any],
    weight_kg: Callable[[], float],
) -> dict[str, str]:
    """The ``dose`` / ``route`` / ``frequency`` of a ``discharge_oral`` entry
    (Issues #3461, #3462).

    An entry with ``home_dose: resume`` continues the regimen of the patient's
    home medication of the same drug when it has a recorded dose. Otherwise an
    entry's ``start_dose`` (a structured dose, or the weight-based basal-insulin
    rule of ``insulin_initiation.yaml`` applied to the weight charted at
    admission) is started. An entry with neither keeps its own fields. Draws
    nothing.
    """
    own = {
        "dose": str(spec.get("dose", "") or ""),
        "route": str(spec.get("route", "PO")),
        "frequency": str(spec.get("frequency", "") or ""),
    }
    start = spec.get("start_dose")
    if not start:
        return own
    if spec.get("home_dose") == "resume":
        wanted = drug_key(str(spec.get("drug_id") or spec.get("drug") or ""))
        for med in home_meds:
            if med.dose and _dedup_key(med.drug_name) == wanted:
                return {"dose": med.dose, "route": med.route or own["route"], "frequency": med.frequency}
    if "rule" in start:
        from clinosim.modules.order.insulin_initiation import basal_insulin_start_dose

        return basal_insulin_start_dose(weight_kg())
    return {
        "dose": str(start["dose"]),
        "route": str(start.get("route") or own["route"]),
        "frequency": str(start.get("frequency") or own["frequency"]),
    }


def build_discharge_rx(
    patient: PatientProfile,
    disease_id: str,
    protocol: DiseaseProtocol,
    prescriber_id: str,
    admission_time: datetime,
    rng: np.random.Generator | None = None,
    *,
    encounter_id: str = "",
    country_key: str,
    final_renal_function: float = 1.0,
    ordered_drugs: Iterable[str] = (),
    severity: str = "",
    aki_active: bool = False,
    lactate_high: bool = False,
    discharge_time: datetime | None = None,
    extra_specs: Iterable[dict[str, Any]] = (),
    excluded_classes: frozenset[str] = frozenset(),
    spared_classes: frozenset[str] = frozenset(),
    held_anticoagulants: Iterable[str] = (),
) -> PrescriptionRecord:
    """Build discharge prescription from protocol.

    ``ordered_drugs`` are the names of the stay's medication orders; with the
    home medications they are the drugs a discharge hold may name (Issue #2992).
    ``severity`` is the stay's severity category (the antithrombotic plan of a
    stroke protocol, Issue #3277).

    ``aki_active`` (Issue #3281): the final creatinine still meets the KDIGO AKI
    definition — the nephrotoxic and renally cleared drugs of
    ``reference_data/aki_response.yaml`` are held and logged; once it no longer
    does they continue (restart).

    ``lactate_high`` (Issue #3539): the final lactate is at or above the metformin
    hold threshold (``aki_response.yaml`` ``lactate_hold``) — metformin is held
    and logged until a later lactate is below it.

    ``extra_specs`` (Issue #3864): ``discharge_oral``-style entries added to the
    prescription, the anticoagulant a complication started in hospital; they
    pass the same renal, hold, allergy and dedup checks as the protocol's.

    ``excluded_classes`` / ``spared_classes`` (Issue #3864): the drug classes a
    complication's stop action rules out at discharge (every systemic
    antibiotic once the inciting one was stopped for C. difficile colitis, less
    the spared classes); such a drug is held and logged like any other discharge
    hold, except a ``from_complication`` entry (the C. difficile course).

    ``held_anticoagulants`` (Issue #3896): the home anticoagulants a complication
    held in hospital (``complication_actions.held_home_anticoagulants``). Each gets
    an explicit decision, ACC 2020 expert consensus pathway on bleeding on oral
    anticoagulants (point 10): once bleeding is controlled, "all other patients
    should likely restart their anticoagulation as soon as it is medically safe to
    do so". The item of a drug still on the prescription says ``reconciliation:
    "resumed"``; a drug a discharge rule keeps off the prescription is stopped and
    logged like any other discharge hold (renal, AKI, protocol, or, with none of
    those, "not resumed"). Not modelled: discontinuation for a low thromboembolic
    risk (the pathway's other branch; the simulator carries no CHA2DS2-VASc score)
    and a changed agent (the anticoagulant a complication starts is refused beside
    a home one by the safety rules, so the home drug stays). Draws nothing.

    ``discharge_time`` (Issue #3441): the discharge datetime, the timestamp of the
    discharge holds logged on ``patient.safety_skip_log`` (the admission time when
    not given). A hold is logged only once the final item list is known to lack
    the drug: a drug that ends up on the prescription was not held.

    Applies renal contraindication checks so that nephrotoxic drugs or drugs
    requiring renal clearance are not prescribed at discharge if the patient's
    renal function is impaired.

    Issue #439 P1: per-(patient, encounter) sub-RNG derived internally from
    ``discharge_prescription_seed`` so YAML edits to ``drugs.discharge_oral`` /
    ``drugs.<category>`` do not shift unrelated patients' cohorts. Sibling of
    AD-59 ``panel_specimen_seed`` / ``individual_lab_seed``. Production callers
    pass ``encounter_id`` and leave ``rng=None`` — the helper derives the RNG
    internally. Tests may inject an explicit ``rng`` to exercise probabilistic
    invariants across a range of RNG streams; when both are provided the
    explicit ``rng`` wins (test-only escape hatch).
    """
    if rng is None:
        from clinosim.seeding import discharge_prescription_seed

        if not encounter_id:
            raise ValueError(
                "build_discharge_rx: either `rng` or `encounter_id` must be "
                "provided (encounter_id is required so the sub-RNG is stable "
                "across runs; rng override is intended for test property "
                "exploration only)."
            )
        rng = determinism.default_rng(discharge_prescription_seed(patient.patient_id, encounter_id))

    items: list[dict] = []
    seen_dedup_keys: set[str] = set()
    taken = frozenset(
        k
        for k in (
            *(m.drug_id or drug_key(m.drug_name) for m in getattr(patient, "current_medications", None) or []),
            *(drug_key(name) for name in ordered_drugs),
        )
        if k
    )

    # Issue #1335 (META #1392 Cluster A part 3): expose the disease
    # protocol's ``medication_holds`` at discharge — this is the same
    # data ``medication_pipeline`` consumes for inpatient order gating.
    # Prior to this pass discharge_rx only knew a fixed
    # ``renal_hold_drugs()`` set (Metformin, NSAIDs, Enoxaparin,
    # Alendronate) plus renal-function threshold, so ACE-I / ARB /
    # ARB-family drugs held during the inpatient AKI course were still
    # transcribed onto the discharge Rx from the patient's home-med
    # list. Reading the same protocol block keeps the inpatient and
    # discharge-Rx hold sets in a single source of truth. Compared
    # by drug identity (catalog drug_id, Issue #2377), as
    # ``medication_pipeline`` does.
    protocol_held: set[str] = set()
    if protocol and getattr(protocol, "medication_holds", None):
        for _hold in protocol.medication_holds or []:
            # Issue #3441: a hold applies at discharge only when its YAML entry
            # says so (``applies_at_discharge``); the default is admission only
            # (e.g. oral -> IV diuretic during decompensation).
            if not _hold.get("applies_at_discharge", False):
                continue
            for _d in _hold.get("drugs", []) or []:
                _dk = drug_key(str(_d))
                if _dk:
                    protocol_held.add(_dk)

    hold_time = discharge_time or admission_time
    pending_holds: list[dict] = []

    def _record_hold(**kwargs: Any) -> None:
        """Issue #3441: queue a discharge hold; ``pending_holds`` is logged
        after the item list is final, for the drugs it does not contain."""
        pending_holds.append(kwargs)

    # A' Phase 1 (Issue #440) dedup: with `patient.current_medications` now
    # tracking newly started drugs across encounters, both the protocol
    # ``discharge_oral`` path AND the chronic-transcribe path below can
    # append the same drug name. Without dedup, the same drug accumulates on
    # every subsequent admission (2 admissions → 2 copies, 3 admissions → 3,
    # etc.). Match key is lowercase whitespace-normalized ``drug_name``. This
    # is an EXACT-name dedup: it does NOT collapse representational variants
    # ("Insulin glargine" vs "Insulin glargine 4 units/kg/day") because
    # dose/formulation differences are clinically meaningful and belong in
    # separate line items.

    def _aki_hold(drug_name: str, drug_name_ja: str) -> bool:
        """Issue #3281: True (and logged) when the final creatinine still
        meets the AKI definition and ``drug_name`` is nephrotoxic or renally
        cleared (``aki_response.yaml``); it continues once AKI has resolved."""
        from clinosim.locale.loader import hold_reason_display
        from clinosim.simulator.aki_response import aki_response_rules, holds_for_aki, holds_for_lactate

        if lactate_high and holds_for_lactate(drug_name):
            reason = aki_response_rules().lactate_hold.reason
        elif aki_active and holds_for_aki(drug_name):
            reason = aki_response_rules().reason
        else:
            return False
        _record_hold(
            encounter_id=encounter_id,
            held_drug_name=drug_name,
            held_drug_name_ja=drug_name_ja or drug_name,
            hold_reason=hold_reason_display(reason, "en"),
            hold_reason_ja=hold_reason_display(reason, "ja"),
            taken=taken,
        )
        return True

    def _reconcile_conflict(drug_name: str, drug_name_ja: str) -> bool:
        """Issue #2713: True (and logged) when ``drug_name`` duplicates the
        class of an item already on this prescription (ACE inhibitor + ARB,
        two P2Y12 inhibitors, DOAC + warfarin); the earlier item is kept."""
        from clinosim.modules import drug_safety

        rules = drug_safety.discharge_reconciliation_rules()
        on_rx = [it["drug_name"] for it in items if it.get("drug_name")]
        for verdict in drug_safety.check_candidate_against_active(drug_name, on_rx):
            if verdict.rule_id in rules:
                _record_hold(
                    encounter_id=encounter_id,
                    held_drug_name=drug_name,
                    held_drug_name_ja=drug_name_ja,
                    hold_reason=verdict.rationale_en or str(verdict.rule_id),
                    hold_reason_ja=verdict.rationale_ja or str(verdict.rule_id),
                    taken=taken,
                )
                return True
        return False

    def _allergy_conflict(drug_name: str, chronic_continuation: bool) -> bool:
        """Issue #2924: True when the patient's active allergies rule out
        ``drug_name``; the skip is logged and the alternative
        ``suggest_alternative`` finds for the rule's indication, if any, is
        prescribed in its place."""
        from clinosim.modules import drug_safety

        verdict = drug_safety.allergy_skip_verdict(drug_name, getattr(patient, "allergies", None) or [])
        if verdict is None:
            return False
        alt = drug_safety.suggest_alternative(
            drug_name,
            verdict.substitution_hint,
            active_meds=[it["drug_name"] for it in items if it.get("drug_name")],
            disease_ctx=protocol,
            country=country_key,
            allergen_codes=drug_safety.allergy_entries(getattr(patient, "allergies", None) or []),
        )
        from clinosim.simulator.medication_pipeline import log_allergy_skip

        log_allergy_skip(
            patient,
            drug_name,
            verdict,
            encounter_id=encounter_id,
            timestamp=admission_time,
            substituted_with=alt.drug if alt else None,
        )
        if alt is not None and (alt.default_route or "PO").upper() == "PO":
            _append_item(
                {"drug": alt.drug, "dose": alt.default_dose, "frequency": alt.default_frequency, "route": "PO"},
                chronic_continuation=chronic_continuation,
            )
        return True

    # Home medications (the immutable baseline plus the current list) a
    # `home_dose: resume` entry continues; the admission weight is looked up
    # only when a weight-based start dose is needed.
    home_meds = list(patient.baseline_chronic_medications or []) + list(patient.current_medications or [])

    def _admission_weight_kg() -> float:
        from clinosim.modules.population.encounter_anthropometry import encounter_weight_kg

        return float(encounter_weight_kg(patient, encounter_id, admission_time, country_key))

    def _append_item(drug_spec: dict, chronic_continuation: bool = False) -> None:
        """Renal-check + dedup + narrow drug_safety triple-antithrombotic
        gate + append. Shared by exclusive & independent paths.

        ``chronic_continuation`` = True for items sourced from a
        ``continue_at_discharge`` category block (anticoagulation, statin,
        antihypertensive, antiplatelet — lifelong secondary-prevention meds).
        For those, the default ``duration_days`` is the chronic-renewal
        length (28) rather than the acute-course default (7) — the
        ``_deactivate_to_layer1`` carry-forward filter (helpers.py
        ``ACUTE_COURSE_MAX_DAYS = 14``) would otherwise drop them from
        the next admission's home-medication orders. Explicit
        ``duration_days`` in the YAML always wins over the default.
        """
        # META #1804 Phase 2.d: prefer catalog resolve_drug when the
        # drug_spec carries drug_id; fall back to legacy drug / drug_ja
        # fields for entries not yet migrated. The catalog is the
        # display SoT once drug_id is set.
        _drug_id = str(drug_spec.get("drug_id") or "")
        if _drug_id:
            from clinosim.codes.drugs import resolve_drug

            _rec = resolve_drug(_drug_id)
            drug_name = _rec.names.get("en", "") or ""
            drug_name_ja = _rec.names.get("ja", "") or drug_name
        else:
            drug_name = drug_spec.get("drug", "")
            drug_name_ja = drug_display(drug_name, "ja") or drug_name
        if not drug_name:
            return
        if _allergy_conflict(drug_name, chronic_continuation):
            return
        _classes = set(drug_classes(drug_name))
        if _classes & excluded_classes and not _classes & spared_classes and not drug_spec.get("from_complication"):
            _record_hold(
                encounter_id=encounter_id,
                held_drug_name=drug_name,
                held_drug_name_ja=drug_name_ja or drug_name,
                hold_reason=t("order_intent.antibiotic_stopped_for_complication", "en"),
                hold_reason_ja=t("order_intent.antibiotic_stopped_for_complication", "ja"),
                taken=taken,
            )
            return
        if final_renal_function < DISCHARGE_RENAL_HOLD_THRESHOLD and drug_key(drug_name) in renal_hold_drugs():
            # Issue #1403: log renal-driven hold for narrative surface
            # (matches inpatient medication_pipeline._log_disease_medication_hold
            # semantic — discharge Rx side).
            _record_hold(
                encounter_id=encounter_id,
                held_drug_name=drug_name,
                held_drug_name_ja=drug_name_ja or drug_name,
                hold_reason=t("order_intent.renal_impairment", "en"),
                hold_reason_ja=t("order_intent.renal_impairment", "ja"),
                taken=taken,
            )
            return
        if _aki_hold(drug_name, drug_name_ja or drug_name):
            return
        # Issue #1335: apply the disease-protocol medication_holds at
        # discharge as well, matched by drug identity (Issue #2377).
        if protocol_held and drug_key(drug_name) in protocol_held:
            # Issue #1403: log the silent protocol-driven hold at
            # discharge for narrative surface.
            _record_hold(
                encounter_id=encounter_id,
                held_drug_name=drug_name,
                held_drug_name_ja=drug_name_ja or drug_name,
                hold_reason=_discharge_protocol_hold_reason_en(disease_id),
                hold_reason_ja=_discharge_protocol_hold_reason_ja(disease_id),
                taken=taken,
            )
            return
        key = _dedup_key(drug_name)
        if key in seen_dedup_keys:
            return
        # Issue #1334 part 2 (META #1392 Cluster A): narrow, direction-
        # aware drug_safety gate for the triple-antithrombotic pattern
        # (DOAC + Aspirin + P2Y12 concurrently post-CVA). The gate:
        # - fires only for the ``doac-plus-p2y12`` rule (not the older
        #   ``anticoagulant-plus-nsaid`` rule, whose DOAC+Aspirin
        #   combination remains permitted here — the cerebral_infarction
        #   YAML's `antiplatelet` + `anticoagulation` continue_at_discharge
        #   blocks intentionally emit both for post-CVA dual-secondary-
        #   prevention);
        # - is direction-aware — the CANDIDATE must be the P2Y12 side.
        #   When the candidate is the anticoagulant (DOAC) and a P2Y12 is
        #   already emitted, the DOAC is KEPT (anticoagulation is the
        #   higher-priority antithrombotic for cardioembolic stroke), and
        #   the residual P2Y12 stays. Clean triple → dual conversion when
        #   the YAML order places anticoagulation BEFORE antiplatelet;
        #   partial conversion (DOAC + P2Y12 dual, no ordering fix)
        #   otherwise. A follow-up under META #1392 may reorder the
        #   discharge iteration and gate both directions once a
        #   cardioembolic-vs-atherothrombotic stroke discriminator is
        #   surfaced on the encounter.
        from clinosim.modules import drug_safety

        _candidate_classes = set(drug_safety.resolve_classes(drug_name) or ())
        if "antiplatelet.p2y12" in _candidate_classes:
            already_emitted = [it["drug_name"] for it in items if it.get("drug_name")]
            for active in already_emitted:
                v = drug_safety.check_pair(drug_name, active)
                if v.rule_id == "doac-plus-p2y12" and not v.is_allowed:
                    return  # drop the P2Y12 candidate that would form the triple
        if _reconcile_conflict(drug_name, drug_name_ja or drug_name):
            return
        seen_dedup_keys.add(key)
        default_duration = 28 if chronic_continuation else 7
        # Issue #476: propagate authored localized dose instructions
        # (`dose_ja` / `dose_en`) into the item dict so the discharge-Rx FHIR
        # builder can emit them as country-scoped `dosageInstruction.text`.
        # Empty for the ~all entries that carry a real numeric dose; only the
        # 5 disease-YAML entries flagged by #476 populate these.
        resolved = _resolve_item_dose(drug_spec, home_meds, _admission_weight_kg)
        # Issue #3896: the weight / interaction dose of the label (edoxaban).
        from clinosim.simulator.complication_actions import dose_reduction_rule, reduced_dose

        dose_rule = dose_reduction_rule(_drug_id or drug_key(drug_name))
        dose_en = language_slot(drug_spec.get("dose_text"), "en")
        dose_ja = language_slot(drug_spec.get("dose_text"), "ja")
        if dose_rule is not None:
            reduced = reduced_dose(
                _drug_id or drug_key(drug_name),
                _admission_weight_kg(),
                [*(m.drug_name for m in home_meds if m.drug_name), *ordered_drugs],
            )
            if reduced:
                resolved = {**resolved, "dose": reduced}
                dose_en, dose_ja = dose_rule.dose_text.get("en", ""), dose_rule.dose_text.get("ja", "")
        items.append(
            {
                "drug_name": drug_name,
                "drug_name_ja": drug_name_ja,
                "dose": resolved["dose"],
                # Issue #2613: an entry whose dose text carries no cadence
                # (warfarin "Titrate to INR ...") states it in `frequency`.
                "frequency": resolved["frequency"],
                "duration_days": drug_spec.get("duration_days", default_duration),
                "route": resolved["route"],
                "dose_ja": dose_ja,
                "dose_en": dose_en,
            }
        )

    # Issue #432: `discharge_oral` blocks may declare `exclusive_classes` +
    # per-entry `drug_class` (same schema as chronic_medications.yaml). The
    # partition + categorical draw is shared with the activator via
    # `select_with_exclusive_classes` — single edit point for the "at most one
    # per exclusive class" semantic. `independent_mode="always"` preserves the
    # pre-#432 behavior where every non-exclusive discharge_oral entry was
    # appended unconditionally (byte-compat with disease protocols that predate
    # exclusive_classes).
    from clinosim.modules._shared import select_with_exclusive_classes

    discharge_oral_block = protocol.drugs.get("discharge_oral", {})
    if isinstance(discharge_oral_block, dict):
        exclusive_classes = set(discharge_oral_block.get("exclusive_classes") or ())
        discharge_drugs = discharge_oral_block.get(country_key, [])
    else:
        exclusive_classes = set()
        discharge_drugs = discharge_oral_block  # legacy shape (unlikely)
    if isinstance(discharge_drugs, dict):
        discharge_drugs = [discharge_drugs]

    for picked in select_with_exclusive_classes(
        discharge_drugs,
        exclusive_classes,
        rng,
        independent_mode="always",
        context=f"disease {disease_id!r} discharge_oral",
        patient_age=_age_years_at(patient, admission_time),
    ):
        _append_item(picked)

    # Continue chronic medications (with renal check + dedup vs protocol path).
    # The dedup keeps the FIRST occurrence, so a drug added by the protocol
    # discharge_oral wins over the chronic transcription (protocol carries the
    # authoritative dose/duration for this admission's discharge, whereas
    # chronic entries default to dose="" / 28-day supply).
    # Issue #452 PR 3: read `med.drug_name` directly.
    # Issue #433 C1: prefer baseline_chronic_medications (immutable snapshot
    # captured at activator time) UNION current_medications (dynamic — may
    # carry hospital-started drugs propagated forward by PR A Phase 1 sync).
    # This is the fix for "chronic drug permanently lost after renal-hold":
    # a metformin held during an AKI admission stays in baseline; when the
    # next admission's final_renal_function >= 0.3 (renal recovered), the
    # renal-hold filter no longer applies and the drug is re-emitted from
    # baseline even though it was absent from that intermediate admission's
    # discharge_prescription.items. Older PatientProfile fixtures without a
    # populated baseline fall back to current_medications only.
    baseline = list(patient.baseline_chronic_medications) if patient.baseline_chronic_medications else []
    baseline_keys = {_dedup_key(m.drug_name) for m in baseline if m.drug_name}
    combined = list(baseline) + [m for m in patient.current_medications if _dedup_key(m.drug_name) not in baseline_keys]
    # Issue #2713: a baseline-only drug that an escalation replaced (e.g.
    # Atorvastatin after the Rosuvastatin switch) yields to the current agent.
    from clinosim.modules import drug_safety as _ds

    _reconcile = _ds.discharge_reconciliation_rules()
    _current_names = [m.drug_name for m in patient.current_medications if m.drug_name]
    _current_keys = {_dedup_key(n) for n in _current_names}
    from clinosim.simulator.antithrombotic_plan import started_in_stay_keys

    plan_agents = started_in_stay_keys(protocol, country_key)
    for med in combined:
        drug_name = med.drug_name
        if not drug_name:
            continue
        if _dedup_key(drug_name) in plan_agents and _dedup_key(drug_name) not in baseline_keys:
            continue  # Issue #3277: an antithrombotic of the stay follows the plan below
        if _dedup_key(drug_name) not in _current_keys and any(
            v.rule_id in _reconcile for v in _ds.check_candidate_against_active(drug_name, _current_names)
        ):
            continue
        if final_renal_function < DISCHARGE_RENAL_HOLD_THRESHOLD and drug_key(drug_name) in renal_hold_drugs():
            continue  # do not restart nephrotoxic drug at discharge
        if _dedup_key(drug_name) not in seen_dedup_keys and _aki_hold(drug_name, med.drug_name_ja or drug_name):
            continue  # Issue #3281: held while AKI persists
        if _dedup_key(drug_name) not in seen_dedup_keys and _allergy_conflict(drug_name, True):
            continue  # Issue #2924: not continued against a recorded allergy
        key = _dedup_key(drug_name)
        if key in seen_dedup_keys:
            continue
        if _reconcile_conflict(drug_name, med.drug_name_ja or drug_name):
            continue
        seen_dedup_keys.add(key)
        items.append(
            {
                "drug_name": drug_name,
                "drug_name_ja": med.drug_name_ja,
                "dose": med.dose,
                "route": med.route,
                "frequency": med.frequency,
                "duration_days": 28,
            }
        )

    # Issues #417 stage 1 / #437: continue_at_discharge — data-declared chronic
    # continuation categories in disease YAML (e.g. cerebral_infarction's
    # `drugs.anticoagulation` / `drugs.statin` / `drugs.antihypertensive` /
    # `drugs.antiplatelet`). Prior to this loop those categories were dead
    # data (no Python reader anywhere), so a patient admitted for
    # cerebral_infarction without a matching chronic condition received an
    # empty discharge prescription — verification (POP=8, seed=901,
    # JP) confirmed 8/8 empty. Categories opt in via
    # `continue_at_discharge: true`; this is the single reader.
    #
    # Cross-source exclusive-class de-duplication uses approach (a) — derive
    # covered exclusive classes from `patient.chronic_conditions` via
    # `chronic_medications.yaml`. If the chronic ICD already covers the same
    # exclusive class (e.g. I48 → "anticoagulant"), the loop skips the block
    # entirely so `_derive_home_medications`' pick (transcribed above via
    # patient.current_medications) remains the sole anticoagulant. Approach
    # (a) is chosen over (a') "reverse-lookup from item strings" because
    # `patient.current_medications` is a plain `list[str]` — reverse-lookup
    # would require drug-name substring matching, which is the fragility
    # documented in Issue #442. Known gap: same YAML declaring BOTH
    # `discharge_oral` and a flagged category with overlapping exclusive
    # classes is not covered by (a); no current disease has this shape (see
    # PR body). Refs #442.
    from clinosim.locale.loader import load_chronic_medications

    _chronic_data = load_chronic_medications()
    covered_exclusive_classes: set[str] = set()
    for cond in getattr(patient, "chronic_conditions", None) or []:
        code = getattr(cond, "code", cond) if not isinstance(cond, str) else cond
        if not code:
            continue
        spec = _chronic_data.get(code) or _chronic_data.get(str(code).split(".")[0])
        if not spec:
            continue
        covered_exclusive_classes.update(spec.get("exclusive_classes") or ())

    for cat_name, block in (protocol.drugs or {}).items():
        if cat_name == "discharge_oral":
            continue  # already handled above
        if not isinstance(block, dict):
            continue
        if not block.get("continue_at_discharge"):
            continue
        # Issue #3277: the antithrombotic blocks of a protocol's plan follow
        # the plan (an anticoagulant for an indication, else aspirin) instead
        # of every entry being added on top of each other.
        from clinosim.simulator.antithrombotic_plan import discharge_specs

        plan_specs = discharge_specs(
            patient,
            protocol,
            cat_name,
            severity=severity,
            country_key=country_key,
            encounter_id=encounter_id,
            prescribed=[str(it.get("drug_name", "")) for it in items],
        )
        if plan_specs is not None:
            for spec in plan_specs:
                _append_item(spec, chronic_continuation=True)
            continue
        cat_exclusive = set(block.get("exclusive_classes") or ())
        # Cross-source guard: chronic ICD already emitted a drug of this class.
        if cat_exclusive & covered_exclusive_classes:
            continue
        cat_drug_list = block.get(country_key, [])
        if isinstance(cat_drug_list, dict):
            cat_drug_list = [cat_drug_list]
        for picked in select_with_exclusive_classes(
            cat_drug_list,
            cat_exclusive,
            rng,
            independent_mode="bernoulli",
            context=f"disease {disease_id!r} {cat_name} (continue_at_discharge)",
        ):
            # Discharge prescriptions are oral-only. Infusions (IV heparin
            # bridge, IV nicardipine drip) are inpatient-only even when the
            # category is flagged for continuation.
            if str(picked.get("route", "PO")).upper() != "PO":
                continue
            _append_item(picked, chronic_continuation=True)

    # Issue #3864: the anticoagulant a complication started in hospital is
    # continued (``complication_actions.complication_discharge_specs``).
    for spec in extra_specs:
        before = len(items)
        _append_item(spec, chronic_continuation=True)
        if len(items) > before:
            # The anticoagulant of the complication takes priority over an
            # antiplatelet the safety rules rule out with it (the stroke plan's
            # aspirin: "the anticoagulant alone"); the pair would be refused in
            # hospital.
            from clinosim.modules import drug_safety

            added = str(items[-1]["drug_name"])
            items[:] = [
                it
                for it in items[:-1]
                if not (
                    "antiplatelet" in drug_classes(str(it.get("drug_name", "")))
                    and not drug_safety.check_pair(added, str(it["drug_name"])).is_allowed
                )
            ] + [items[-1]]

    limit_triple_antithrombotic(items, home_medications=[m.drug_name for m in patient.current_medications])
    for held_name in held_anticoagulants:
        held_key = drug_key(held_name)
        same = [it for it in items if drug_key(str(it["drug_name"])) == held_key]
        if same:
            same[0]["reconciliation"] = "resumed"
        elif not any(drug_key(h["held_drug_name"]) == held_key for h in pending_holds):
            _record_hold(
                encounter_id=encounter_id,
                held_drug_name=held_name,
                held_drug_name_ja=drug_display(held_name, "ja") or held_name,
                hold_reason=t("order_intent.held_anticoagulant_not_resumed", "en"),
                hold_reason_ja=t("order_intent.held_anticoagulant_not_resumed", "ja"),
                taken=taken,
            )
    # Issue #3004: a minor's discharge doses are weight-based (weight charted
    # at admission), like the inpatient orders.
    if encounter_id:
        from clinosim.modules.order.pediatric_dose import pediatric_dose_text
        from clinosim.simulator.medication_pipeline import child_dosing

        child = child_dosing(patient, encounter_id, admission_time, country_key)
        if child is not None:
            for item in items:
                item["dose"] = pediatric_dose_text(str(item.get("drug_name", "")), str(item.get("dose", "")), *child)
    prescribed_keys = {drug_key(str(it.get("drug_name", ""))) for it in items}
    for hold in pending_holds:
        if drug_key(hold["held_drug_name"]) in prescribed_keys:
            continue  # Issue #3441: on the final prescription, so not held
        _log_discharge_hold(patient, timestamp=hold_time, **hold)
    return PrescriptionRecord(
        prescription_id=f"RX-{patient.patient_id}-DC",
        patient_id=patient.patient_id,
        prescriber_id=prescriber_id,
        issue_date=admission_time,
        items=items,
    )
