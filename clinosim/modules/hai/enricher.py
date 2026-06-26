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
from clinosim.modules.antibiotic import ANTIBIOTIC_LOINC_LOOKUP
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
from clinosim.types.microbiology import MicrobiologyResult, SusceptibilityResult

_SIR = ("S", "I", "R")

_DEVICE_TO_HAI = {
    "cvc": "clabsi",
    "indwelling_catheter": "cauti",
    "mechanical_ventilator": "vap",
}


def _get_forced_hai_event(ctx) -> dict | None:
    """Return the first ForcedScenario.force_hai_event if set, else None.

    PR3b-1 Task 7b: deterministic HAI testing infrastructure. A non-None
    return overrides stochastic per-line-day risk sampling — for each
    device of the matching hai_type, exactly one HAI event is emitted
    at placement_date + onset_offset_days using the supplied organism.
    """
    forced_scenarios = getattr(ctx.config, "forced_scenarios", None) or []
    for fs in forced_scenarios:
        fe = getattr(fs, "force_hai_event", None)
        if isinstance(fe, dict) and fe.get("hai_type"):
            return fe
    return None


def enrich_hai(ctx) -> None:
    """post_records enricher entry point.

    Walks ctx.records, samples HAI per device, writes
    extensions["hai"] + appends culture MicrobiologyResults.

    PR3b-1 Task 7b: if any ForcedScenario.force_hai_event is set, bypass
    Poisson per-line-day sampling for matching devices (deterministic
    test infrastructure).
    """
    # Local import to break the hai/__init__ → enricher → hai circular chain.
    from clinosim.modules.hai import load_hai_antibiogram  # noqa: PLC0415

    rates_cfg = load_hai_rates()["hai_rates"]
    codes_cfg = load_hai_codes()["hai_codes"]
    organisms_cfg = load_hai_organisms()["hai_organisms"]
    specimens_cfg = load_hai_specimens()["hai_specimens"]
    antibiogram_cfg = load_hai_antibiogram()
    forced = _get_forced_hai_event(ctx)
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
            if forced is not None:
                if hai_type != forced["hai_type"]:
                    continue
                onset_offset = int(forced["onset_offset_days"])
                organism = forced["organism_snomed"]
            else:
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
            _append_hai_culture(rec, ev, specimens_cfg[hai_type], onset_date,
                                antibiogram_cfg, rng)
        if hai_events:
            if isinstance(rec, dict):
                rec.setdefault("extensions", {})["hai"] = hai_events
            else:
                rec.extensions["hai"] = hai_events


def _append_hai_culture(
    rec,
    hai: HAIEvent,
    spec_cfg: dict,
    onset_date: str,
    antibiogram_cfg: dict,
    rng: np.random.Generator,
) -> None:
    """Append a MicrobiologyResult so _fhir_microbiology.py emits the culture.

    Populates susceptibilities via NHSN-anchored antibiogram lookup keyed by
    (hai_type, organism_snomed). Sets hai_event_id as a backref for PR3b-3.
    """
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
        hai_event_id=hai.hai_id,
    )
    organism_table = (
        antibiogram_cfg.get(hai.hai_type, {}).get(hai.organism_snomed, {})
    )
    for abx_key, sir_probs in organism_table.items():
        loinc = ANTIBIOTIC_LOINC_LOOKUP.get(abx_key)
        if not loinc:
            continue  # unreachable at runtime (Task 4 validates load time)
        probs = np.array(sir_probs, dtype=float)
        if probs.sum() <= 0:
            continue
        probs = probs / probs.sum()
        interp = _SIR[int(rng.choice(len(_SIR), p=probs))]
        micro.susceptibilities.append(
            SusceptibilityResult(antibiotic_loinc=str(loinc), interpretation=interp)
        )
    if isinstance(rec, dict):
        rec.setdefault("microbiology", []).append(micro)
    else:
        rec.microbiology.append(micro)
