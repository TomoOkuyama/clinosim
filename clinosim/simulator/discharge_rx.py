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

from datetime import datetime

import numpy as np

from clinosim import determinism
from clinosim.modules.disease.protocol import DiseaseProtocol
from clinosim.modules.physiology.renal_thresholds import DISCHARGE_RENAL_HOLD_THRESHOLD
from clinosim.types.encounter import PrescriptionRecord
from clinosim.types.patient import PatientProfile

# Drugs held at discharge when renal function is impaired.
# Threshold `final_renal_function < DISCHARGE_RENAL_HOLD_THRESHOLD` maps to
# KDIGO stage 3b+ CKD or active AKI. Held drugs include nephrotoxins
# (NSAIDs) and drugs cleared renally where a stopped dose is safer than a
# discharge-strength one (metformin for lactic-acidosis risk, enoxaparin
# for bleeding-risk).
_RENAL_HOLD_DRUGS: frozenset[str] = frozenset(
    {
        "metformin",
        "celecoxib",
        "ibuprofen",
        "naproxen",
        "diclofenac",
        "loxoprofen",
        "meloxicam",
        "ketorolac",
        "indomethacin",
        "enoxaparin",
        "alendronate",
        # Issue #1335 (META #1392 Cluster A part 3): ACE-I / ARB families
        # gate on renal function at discharge as well as during the
        # inpatient course. When ``final_renal_function <
        # DISCHARGE_RENAL_HOLD_THRESHOLD`` (KDIGO stage 3b+ / active
        # AKI), afferent-arteriolar and efferent-arteriolar
        # vasoactive agents must not be transcribed onto the discharge
        # prescription regardless of which disease protocol drove the
        # admission (the lab-derived AKI Condition enricher added in
        # #1326 can attach a N17.x diagnosis to a non-AKI-primary
        # admission — this list catches those too).
        "enalapril",
        "lisinopril",
        "captopril",
        "ramipril",
        "perindopril",
        "benazepril",
        "losartan",
        "valsartan",
        "candesartan",
        "olmesartan",
        "telmisartan",
        "irbesartan",
        "azilsartan",
    }
)


def _dedup_key(name: str) -> str:
    """Whitespace-normalized lowercase key for cross-source drug dedup."""
    return " ".join(name.lower().split())


def build_discharge_rx(
    patient: PatientProfile,
    disease_id: str,
    protocol: DiseaseProtocol,
    prescriber_id: str,
    admission_time: datetime,
    rng: np.random.Generator | None = None,
    *,
    encounter_id: str = "",
    country_key: str = "japan",
    final_renal_function: float = 1.0,
) -> PrescriptionRecord:
    """Build discharge prescription from protocol.

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

    # Issue #1335 (META #1392 Cluster A part 3): expose the disease
    # protocol's ``medication_holds`` at discharge — this is the same
    # data ``medication_pipeline`` consumes for inpatient order gating.
    # Prior to this pass discharge_rx only knew a fixed
    # ``_RENAL_HOLD_DRUGS`` set (Metformin, NSAIDs, Enoxaparin,
    # Alendronate) plus renal-function threshold, so ACE-I / ARB /
    # ARB-family drugs held during the inpatient AKI course were still
    # transcribed onto the discharge Rx from the patient's home-med
    # list. Reading the same protocol block keeps the inpatient and
    # discharge-Rx hold sets in a single source of truth. Compared
    # against lowercase substring match to mirror how
    # ``medication_pipeline`` matches (substring, not exact) so
    # multi-name entries in the YAML (e.g. Enalapril / Lisinopril /
    # Captopril) each match their MR text variant.
    protocol_held: set[str] = set()
    if protocol and getattr(protocol, "medication_holds", None):
        for _hold in protocol.medication_holds or []:
            for _d in _hold.get("drugs", []) or []:
                _dl = str(_d).lower().strip()
                if _dl:
                    protocol_held.add(_dl)

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

    def _append_item(drug_spec: dict, chronic_continuation: bool = False) -> None:
        """Renal-check + dedup + narrow drug_safety triple-antithrombotic
        gate + append. Shared by exclusive & independent paths.

        ``chronic_continuation`` = True for items sourced from a
        ``continue_at_discharge`` category block (anticoagulation, statin,
        antihypertensive, antiplatelet — lifelong secondary-prevention meds).
        For those, the default ``duration_days`` is the chronic-renewal
        length (28) rather than the acute-course default (7) — the
        ``_deactivate_to_layer1`` carry-forward filter (helpers.py
        ``_ACUTE_COURSE_MAX_DAYS = 14``) would otherwise drop them from
        the next admission's home-medication orders. Explicit
        ``duration_days`` in the YAML always wins over the default.
        """
        drug_name = drug_spec.get("drug", "")
        if not drug_name:
            return
        if final_renal_function < DISCHARGE_RENAL_HOLD_THRESHOLD and any(
            rd in drug_name.lower() for rd in _RENAL_HOLD_DRUGS
        ):
            return
        # Issue #1335: apply the disease-protocol medication_holds at
        # discharge as well. Substring match on lowercase drug_name to
        # mirror ``medication_pipeline``'s inpatient hold semantics.
        if protocol_held and any(h in drug_name.lower() for h in protocol_held):
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
        seen_dedup_keys.add(key)
        default_duration = 28 if chronic_continuation else 7
        # Issue #476: propagate authored localized dose instructions
        # (`dose_ja` / `dose_en`) into the item dict so the discharge-Rx FHIR
        # builder can emit them as country-scoped `dosageInstruction.text`.
        # Empty for the ~all entries that carry a real numeric dose; only the
        # 5 disease-YAML entries flagged by #476 populate these.
        items.append(
            {
                "drug_name": drug_name,
                "drug_name_ja": drug_spec.get("drug_ja", ""),
                "dose": drug_spec.get("dose", ""),
                "duration_days": drug_spec.get("duration_days", default_duration),
                "route": drug_spec.get("route", "PO"),
                "dose_ja": drug_spec.get("dose_ja", ""),
                "dose_en": drug_spec.get("dose_en", ""),
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
    for med in combined:
        drug_name = med.drug_name
        if not drug_name:
            continue
        drug_lower = drug_name.lower()
        if final_renal_function < DISCHARGE_RENAL_HOLD_THRESHOLD and any(rd in drug_lower for rd in _RENAL_HOLD_DRUGS):
            continue  # do not restart nephrotoxic drug at discharge
        key = _dedup_key(drug_name)
        if key in seen_dedup_keys:
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

    return PrescriptionRecord(
        prescription_id=f"RX-{patient.patient_id}-DC",
        patient_id=patient.patient_id,
        prescriber_id=prescriber_id,
        issue_date=admission_time,
        items=items,
    )
