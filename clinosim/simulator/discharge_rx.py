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
    {"metformin", "celecoxib", "ibuprofen", "naproxen", "enoxaparin", "alendronate"}
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
        rng = np.random.default_rng(discharge_prescription_seed(patient.patient_id, encounter_id))

    items: list[dict] = []
    seen_dedup_keys: set[str] = set()

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

    def _append_item(drug_spec: dict) -> None:
        """Renal-check + dedup + append. Shared by exclusive & independent paths."""
        drug_name = drug_spec.get("drug", "")
        if not drug_name:
            return
        if final_renal_function < DISCHARGE_RENAL_HOLD_THRESHOLD and any(
            rd in drug_name.lower() for rd in _RENAL_HOLD_DRUGS
        ):
            return
        key = _dedup_key(drug_name)
        if key in seen_dedup_keys:
            return
        seen_dedup_keys.add(key)
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
                "duration_days": drug_spec.get("duration_days", 7),
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
            _append_item(picked)

    return PrescriptionRecord(
        prescription_id=f"RX-{patient.patient_id}-DC",
        patient_id=patient.patient_id,
        prescriber_id=prescriber_id,
        issue_date=admission_time,
        items=items,
    )
