"""Lab-derived complication diagnosis enricher (Issue #1326).

Some acute complications (AKI on top of another admission, hyperkalemia,
metabolic-acidosis crises) develop mid-admission with a definitive
laboratory signature. When the sim samples an admission for one disease
(e.g. `heart_failure_exacerbation`) and the daily-loop's physiology
engine drives Creatinine into KDIGO Stage 3 territory (>= 4.0 mg/dL)
without the pre-existing chronic profile explaining it (no N18.4/5/6
ESRD baseline), a real EHR would carry a secondary N17.x AKI diagnosis
on the encounter. Pre-#1326 the sim emitted the Cr Observation but not
the paired Condition, so downstream AKI-detection models trained on
the cohort undercounted CHF/sepsis-cohort AKI.

This module adds a single POST_ENCOUNTER enricher that scans an
inpatient encounter's `lab_results` for Creatinine peaks and appends a
`working_diagnoses` entry when the KDIGO Stage 3 absolute threshold is
crossed and no N17.x diagnosis already exists on the encounter. The
existing FHIR emit path (`modules/output/fhir_r4/conditions/conditions.py`,
`working_diagnoses` walker added in Issue #1307) then produces the
Condition resource — no new emit code path required.

Determinism: RNG-free. Purely lab-value-driven.

Scope (this module):
    - Creatinine peak → N17.9 (AKI KDIGO Stage 3 absolute).

Deferred (future extensions of this same module):
    - Cr rise >= 3x baseline (KDIGO Stage 3 relative) — needs a
      reliable baseline reference; today the sim's baseline sits in
      the physiology profile and is not surfaced to POST_ENCOUNTER
      context in an easy shape.
    - K > 6.5 → E87.5 hyperkalemia Condition.
    - pH < 7.2 or HCO3 < 15 → E87.2 acidosis Condition.
    - Renal-dose adjustment of Enoxaparin / Metformin / DOACs when
      the AKI trigger fires (belongs in `drug_safety` module, not here).
"""

from __future__ import annotations

from typing import Any

from clinosim.simulator.enrichers import EnricherContext

# ---------------------------------------------------------------------------
# KDIGO absolute-threshold gates
# ---------------------------------------------------------------------------

CREATININE_KDIGO_STAGE3_ABSOLUTE_MG_DL: float = 4.0
"""Serum creatinine (mg/dL) above which KDIGO 2012 AKI Stage 3 is
defined by the absolute criterion alone (:kbd:`Cr ≥ 4.0`), regardless
of pre-admission baseline. Chosen instead of the ``1.5x baseline`` or
``3x baseline`` relative criteria to keep the enricher self-contained —
per-patient baseline Cr is not exposed to the POST_ENCOUNTER context
in a stable-across-refactors way. Under-fires on smaller AKI events
(intended: better under-fire than emit false-positive N17 on a stable
CKD patient whose Cr sits at 3-4 mg/dL by design)."""

CKD_STAGE_45_ICD_PREFIXES: tuple[str, ...] = ("N18.4", "N18.5", "N18.6", "N18.5", "N18.6", "N19")
"""ICD-10 code prefixes for CKD stages 4-5 and unspecified renal failure.
Patients carrying any of these as a CHRONIC condition are excluded
from lab-derived AKI emit — their steady-state Cr already sits near or
above the threshold, so peak > 4.0 is not diagnostic of new AKI. The
sim's chronic-condition activator writes CKD stages as ``N18.<digit>``
directly, so a prefix match on ``N18.4/5/6`` is precise. ``N19``
(unspecified renal failure) is an ESRD proxy in some coding practices;
inclusion prevents a spurious N17 stacked on it."""

AKI_CODE_PREFIXES: tuple[str, ...] = ("N17",)
"""Prefixes an existing encounter diagnosis must match for this enricher
to consider the AKI already recorded (any N17.x variant — the sim's
AKI disease branch samples N17.0 / N17.1 / N17.2 / N17.8 / N17.9)."""

LAB_DERIVED_AKI_DIAGNOSIS_CODE: str = "N17.9"
"""ICD-10 code emitted for a lab-derived AKI (`Acute kidney failure,
unspecified`). Deliberately unspecified because the enricher has no
etiology signal (no distinguishing FENa / muddy-brown-casts data at
this layer) — a specific N17.0-8 code would over-claim."""

LAB_DERIVED_AKI_SOURCE_TAG: str = "lab_derived_aki_kdigo_stage3"
"""Value written to the ``source`` field on the appended
``working_diagnoses`` entry so downstream FHIR emit can distinguish
lab-derived Conditions from disease-protocol-driven ones. The FHIR
emit's evidence-text branch (Issue #1307) currently only maps
``"in_hospital_complication"`` vs other-string; other-string maps to
the "Secondary diagnosis carried onto the encounter" label. A future
follow-up could add a lab-derived evidence label if useful."""


def enrich_lab_derived_dx(ctx: EnricherContext) -> None:
    """POST_ENCOUNTER enricher — Issue #1326.

    For every inpatient record in ``ctx.records``, scan Creatinine
    observations for a peak crossing
    :data:`CREATININE_KDIGO_STAGE3_ABSOLUTE_MG_DL`. When the peak clears
    the threshold AND the encounter is not already carrying an N17.x
    diagnosis (primary / admission / discharge / working) AND the
    patient's chronic profile lacks CKD stage 4-5 or ESRD (their
    baseline may already exceed the threshold by design), append a
    ``working_diagnoses`` entry so the existing FHIR ``working_diagnoses``
    emit path renders a secondary N17.9 Condition on the encounter.

    Determinism: pure lab-value walk; no RNG consumption.
    """
    for record in ctx.records:
        if not getattr(record, "encounters", None):
            continue
        enc = record.encounters[0]
        # Inpatient-only. Outpatient encounters can spot-check Cr but
        # would not develop mid-admission AKI in the sim's model.
        enc_type = getattr(enc, "encounter_type", None)
        enc_type_val = getattr(enc_type, "value", enc_type)
        if str(enc_type_val) != "inpatient":
            continue

        # Skip patients whose chronic CKD-4/5 or ESRD carrier baseline
        # already sits near or above the threshold.
        patient = getattr(record, "patient", None)
        chronic = list(getattr(patient, "chronic_conditions", []) or [])
        chronic_codes = [(getattr(c, "code", None) or (c if isinstance(c, str) else "")) for c in chronic]
        if any(any(str(cc).startswith(prefix) for prefix in CKD_STAGE_45_ICD_PREFIXES) for cc in chronic_codes):
            continue

        # Existing N17.x anywhere on this encounter? (primary /
        # admission / discharge / working / complications).
        existing_codes: set[str] = set()
        cd = getattr(record, "clinical_diagnosis", None)
        if cd is not None:
            existing_codes.add(str(getattr(cd, "admission_diagnosis_code", "") or ""))
            existing_codes.add(str(getattr(cd, "discharge_diagnosis_code", "") or ""))
            for wd in getattr(cd, "working_diagnoses", []) or []:
                if isinstance(wd, dict):
                    existing_codes.add(str(wd.get("disease_id", "") or ""))
        # NOTE — ``complications_occurred`` uses the disease-YAML id string
        # (``"acute_kidney_injury"``) rather than an ICD code. The daily-loop
        # complication engine appends only that string; it does NOT populate
        # ``working_diagnoses`` with the corresponding N17.x entry, so the
        # FHIR Condition emit path (which walks working_diagnoses and
        # admission/discharge/chronic codes) never renders a Condition for
        # a mid-admission AKI complication. We deliberately do NOT treat
        # the ``"acute_kidney_injury"`` complication tag as an
        # already-emitted N17 — that would suppress this enricher on exactly
        # the encounters that need it most. When the tag is present AND no
        # explicit N17.x code is on the encounter, this enricher fills the
        # gap by appending the N17.9 working-diagnoses entry.
        if any(code and any(code.startswith(prefix) for prefix in AKI_CODE_PREFIXES) for code in existing_codes):
            continue

        # Walk labs for Creatinine peak.
        peak_cr: float = 0.0
        peak_dt: Any = None
        for lab in getattr(record, "lab_results", []) or []:
            lab_name = str(getattr(lab, "lab_name", "") or "")
            if lab_name != "Creatinine":
                continue
            val = getattr(lab, "value", None)
            try:
                val_f = float(val) if val is not None else None
            except (TypeError, ValueError):
                continue
            if val_f is None:
                continue
            if val_f > peak_cr:
                peak_cr = val_f
                peak_dt = getattr(lab, "result_datetime", None)

        if peak_cr < CREATININE_KDIGO_STAGE3_ABSOLUTE_MG_DL:
            continue

        # Compute onset_day relative to admission.
        admit_dt = getattr(enc, "admission_datetime", None)
        onset_day = 0
        if admit_dt is not None and peak_dt is not None:
            try:
                onset_day = max(0, (peak_dt.date() - admit_dt.date()).days)
            except AttributeError:
                onset_day = 0

        if cd is None:
            continue
        working = getattr(cd, "working_diagnoses", None)
        if not isinstance(working, list):
            continue
        working.append(
            {
                "disease_id": LAB_DERIVED_AKI_DIAGNOSIS_CODE,
                "onset_day": onset_day,
                "onset_datetime": peak_dt.isoformat() if peak_dt is not None else "",
                "source": LAB_DERIVED_AKI_SOURCE_TAG,
            }
        )
