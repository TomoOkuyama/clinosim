"""HAI enricher (AD-55 Module, AD-56 post_records, PR-B).

Consumes extensions["device"] from PR-A. Samples HAI onsets via CDC NHSN
per-line-day risk rates, writes list[HAIEvent] under extensions["hai"],
appends a MicrobiologyResult to record.microbiology so the existing
_fhir_microbiology.py builder emits the culture automatically.
Independent per-patient sub-seed (ENRICHER_SEED_OFFSETS["hai"] = 0x4841
"HA") keeps the main RNG untouched (AD-16).
"""
from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np

from clinosim.modules._shared import get_attr_or_key as _get
from clinosim.modules.hai.engine import (
    _add_days,
    _sample_organism,
    load_hai_codes,
    load_hai_organisms,
    load_hai_rates,
    load_hai_specimens,
    sample_hai_onset,
)
from clinosim.simulator.seeding import ENRICHER_SEED_OFFSETS, derive_sub_seed
from clinosim.types.hai import HAIEvent
from clinosim.types.microbiology import MicrobiologyResult

_DEVICE_TO_HAI = {
    "cvc": "clabsi",
    "indwelling_catheter": "cauti",
    "mechanical_ventilator": "vap",
}


def enrich_hai(ctx) -> None:
    """post_records enricher entry point.

    Walks ctx.records, samples HAI per device, writes
    extensions["hai"] + appends culture MicrobiologyResults.
    """
    rates_cfg = load_hai_rates()["hai_rates"]
    codes_cfg = load_hai_codes()["hai_codes"]
    organisms_cfg = load_hai_organisms()["hai_organisms"]
    specimens_cfg = load_hai_specimens()["hai_specimens"]
    for rec in ctx.records:
        patient = _get(rec, "patient")
        pid = _get(patient, "patient_id", "") if patient else ""
        rng = np.random.default_rng(
            derive_sub_seed(
                ctx.master_seed,
                ENRICHER_SEED_OFFSETS["hai"],
                pid or "x",
            )
        )
        ext = _get(rec, "extensions", {}) or {}
        devices = ext.get("device", []) or []
        if not devices:
            continue
        hai_events: list[HAIEvent] = []
        for device in devices:
            device_type = _get(device, "device_type", "")
            hai_type = _DEVICE_TO_HAI.get(device_type)
            if not hai_type:
                continue
            occurred, onset_offset = sample_hai_onset(device, rates_cfg[hai_type], rng)
            if not occurred or onset_offset is None:
                continue
            organism = _sample_organism(organisms_cfg[hai_type], rng)
            enc_id = _get(device, "encounter_id", "")
            placement_date = _get(device, "placement_date", "")
            hai_id = f"hai-{enc_id}-{hai_type}-{len(hai_events)}"
            onset_date = _add_days(placement_date, onset_offset)
            ev = HAIEvent(
                hai_id=hai_id,
                encounter_id=enc_id,
                hai_type=hai_type,
                source_device_id=_get(device, "device_id", ""),
                icd10_code=codes_cfg[hai_type]["icd10_us_billable"],
                snomed_code=codes_cfg[hai_type]["snomed"],
                onset_date=onset_date,
                organism_snomed=organism,
                culture_specimen_id=f"spec-hai-{hai_id}",
            )
            hai_events.append(ev)
            _append_hai_culture(rec, ev, specimens_cfg[hai_type], onset_date)
        if hai_events:
            if isinstance(rec, dict):
                rec.setdefault("extensions", {})["hai"] = hai_events
            else:
                rec.extensions["hai"] = hai_events


def _append_hai_culture(rec, hai: HAIEvent, spec_cfg: dict, onset_date: str) -> None:
    """Append a MicrobiologyResult so _fhir_microbiology.py emits the culture."""
    onset_dt = datetime.fromisoformat(onset_date)
    micro = MicrobiologyResult(
        encounter_id=hai.encounter_id,
        specimen=spec_cfg["specimen"],
        specimen_snomed=spec_cfg["specimen_snomed"],
        test_loinc=spec_cfg["test_loinc"],
        collected_datetime=onset_dt,
        reported_datetime=onset_dt + timedelta(days=2),
        growth=True,
        organism_snomed=hai.organism_snomed,
        quantitation="positive",
        susceptibilities=[],
    )
    if isinstance(rec, dict):
        rec.setdefault("microbiology", []).append(micro)
    else:
        rec.microbiology.append(micro)
