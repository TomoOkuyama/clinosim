"""POST_ENCOUNTER enricher for newborn birth-admission workup (#1252).

Runs after every simulated encounter, gates on the newborn-birth record
(perinatal.py stamps ``condition_event.condition_type = "newborn_birth"``
on the baby-side CIF record) and appends the clinical events this
module owns: Vitamin K prophylaxis (JP oral, US IM) and US erythromycin
ophthalmic prophylaxis as MAR entries, shift vitals, Apgar scores, the
hearing and metabolic screen Procedures (once per newborn), and the
bilirubin / CCHD SpO2 / metabolic-screen workflow data under
``extensions["newborn"]``.

Enricher order (see `clinosim/simulator/enrichers.py`): 92 — placed
before `document` (95) so any downstream document narrative that
references Vitamin K administration has the MAR entry in hand.
"""

from __future__ import annotations

import logging
from typing import Any

from clinosim.modules._shared import get_attr_or_key as _get
from clinosim.modules._shared import set_attr_or_key as _set
from clinosim.modules.newborn.engine import (
    build_apgar_scores,
    build_bilirubin_observations,
    build_cchd_pulse_ox,
    build_hearing_screen_procedure,
    build_metabolic_screen_procedure,
    build_metabolic_screen_workflow_data,
    build_newborn_shift_vitals,
    build_ophthalmic_prophylaxis,
    build_vitamin_k_administrations,
    has_perinatal_baseline_emitted,
    is_newborn_birth_record,
    mark_perinatal_baseline_emitted,
)

logger = logging.getLogger(__name__)


def enrich_newborn(ctx: Any) -> None:
    """POST_ENCOUNTER entrypoint. Iterates `ctx.records`, no-ops on
    non-newborn records, and appends the newborn workup listed in the
    module docstring to newborn records. Schedules come from
    `newborn_screening.yaml`; sampled values (Apgar, screen outcomes,
    bilirubin, SpO2) use per-newborn sha256-keyed sub-RNGs, so the
    master RNG is not consumed.
    """
    records = _get(ctx, "records", None) or []
    country = str(_get(_get(ctx, "config", None), "country", "US") or "US")
    for record in records:
        if not is_newborn_birth_record(record):
            continue
        try:
            new_mars = build_vitamin_k_administrations(record=record, country=country)
            new_vitals = build_newborn_shift_vitals(record=record)
            new_apgar = build_apgar_scores(record=record)
            new_hearing = build_hearing_screen_procedure(record=record)
            new_metabolic = build_metabolic_screen_procedure(record=record, country=country)
            new_metabolic_workflow = build_metabolic_screen_workflow_data(record=record, country=country)
            new_bili = build_bilirubin_observations(record=record)
            new_cchd = build_cchd_pulse_ox(record=record)
            new_oph = build_ophthalmic_prophylaxis(record=record, country=country)
        except Exception:  # pragma: no cover — defensive
            logger.exception("newborn enricher failed on record; continuing")
            continue
        # Issue #1736 — once-per-newborn dedup for the hearing (SNOMED
        # 232717001) + metabolic (SNOMED 405058008) screens. A mother
        # with ≥ 2 deliveries produces two newborn-side CIF records that
        # share ``patient_id = f"{mother_id}-BABY"`` and both carry
        # ``condition_type = "newborn_birth"``; absent dedup, both
        # records emit the baseline screens under the shared ``-BABY``
        # subject, so a FHIR consumer sees the once-per-newborn screens
        # fire twice for the same ``Patient`` resource. The ``build_*``
        # helpers above stay pure (they always compute the Procedure so
        # the determinism / shape unit tests keep working); we only
        # suppress the APPEND here when the tracker already records this
        # ``(patient_id, snomed)`` pair. Mirrors Phase 4d
        # ``baseline_only`` dedup in simulator/outpatient.py (CPAP /
        # polysomnography).
        _pid = str(_get(_get(record, "patient", None), "patient_id", "") or "")
        if new_hearing is not None and _pid:
            if has_perinatal_baseline_emitted(_pid, "232717001"):
                new_hearing = None
            else:
                mark_perinatal_baseline_emitted(_pid, "232717001")
        if new_metabolic is not None and _pid:
            if has_perinatal_baseline_emitted(_pid, "405058008"):
                # Keep the metabolic Procedure AND its sibling
                # ServiceRequest / Specimen / DiagnosticReport workflow
                # stash in lock-step — dropping the Procedure without
                # dropping the workflow would ship SR / Specimen / DR
                # without an accompanying Procedure, which is exactly
                # the kind of split-emit split-brain the by-design
                # registry forbids.
                new_metabolic = None
                new_metabolic_workflow = None
            else:
                mark_perinatal_baseline_emitted(_pid, "405058008")
        if new_bili or new_cchd or new_metabolic_workflow:
            ext = _get(record, "extensions", None)
            if ext is None:
                ext = {}
                _set(record, "extensions", ext)
            nb = ext.setdefault("newborn", {})
            if new_bili:
                nb["bilirubin"] = list(new_bili)
            if new_cchd:
                nb["cchd_pulse_ox"] = list(new_cchd)
            if new_metabolic_workflow:
                # #1252 N6b: stash the ServiceRequest / Specimen /
                # DiagnosticReport payload for the metabolic screen
                # workflow. The three bundle-builders in
                # `clinosim.modules.newborn.fhir_emit` read this to emit
                # the diagnostic-workflow evidence sibling to the
                # existing `Procedure` (which records the physical
                # heel-stick event).
                nb["metabolic_screen"] = dict(new_metabolic_workflow)
        if new_oph:
            existing_mars = _get(record, "medication_administrations", None)
            if existing_mars is None:
                _set(record, "medication_administrations", list(new_oph))
            else:
                existing_mars.extend(new_oph)
        new_procs = [p for p in (new_hearing, new_metabolic) if p is not None]
        if new_procs:
            existing_procs = _get(record, "procedures", None)
            if existing_procs is None:
                _set(record, "procedures", list(new_procs))
            else:
                existing_procs.extend(new_procs)
        if new_apgar:
            # Store under `extensions["newborn"]["apgar"]`. The FHIR
            # emit path (`_bb_newborn_apgar` in the fhir_r4 adapter)
            # walks this and renders LOINC 9271-8 / 9274-2 Observations.
            ext = _get(record, "extensions", None)
            if ext is None:
                _set(record, "extensions", {"newborn": {"apgar": list(new_apgar)}})
            else:
                nb = ext.setdefault("newborn", {})
                nb["apgar"] = list(new_apgar)
        if new_mars:
            existing_mars = _get(record, "medication_administrations", None)
            if existing_mars is None:
                _set(record, "medication_administrations", list(new_mars))
            else:
                existing_mars.extend(new_mars)
        if new_vitals:
            existing_vs = _get(record, "vital_signs", None)
            if existing_vs is None:
                _set(record, "vital_signs", list(new_vitals))
            else:
                existing_vs.extend(new_vitals)
