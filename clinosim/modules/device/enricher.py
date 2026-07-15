"""Device enricher (AD-55 Module, AD-56 post_records).

Walks every CIFPatientRecord, calls place_devices_for_encounter for each
inpatient encounter, and writes list[DeviceRecord] under
extensions["device"]. Independent per-patient sub-seed
(ENRICHER_SEED_OFFSETS["device"] = 0x4445) keeps the main RNG stream
untouched (AD-16). Phase 1 of the device + HAI 4-PR series; Phase 2
hai enricher consumes extensions["device"].
"""

from __future__ import annotations

import numpy as np

from clinosim.modules._shared import get_attr_or_key as _get
from clinosim.modules._shared import get_or_create_container
from clinosim.modules.device.engine import (
    load_devices_config,
    place_devices_for_encounter,
)
from clinosim.simulator.seeding import ENRICHER_SEED_OFFSETS, derive_sub_seed


def enrich_device(ctx) -> None:
    """post_records enricher entry point.

    For each CIFPatientRecord in ctx.records, evaluates every encounter
    and writes list[DeviceRecord] under extensions["device"] when at least
    one device is placed. Empty patient → no extensions key written.
    """
    cfg = load_devices_config()
    for rec in ctx.records:
        patient = _get(rec, "patient")
        pid = _get(patient, "patient_id", "") if patient else ""
        rng = np.random.default_rng(
            derive_sub_seed(
                ctx.master_seed,
                ENRICHER_SEED_OFFSETS["device"],
                pid or "x",
            )
        )
        devices = []
        for encounter in _get(rec, "encounters", []) or []:
            devices.extend(place_devices_for_encounter(rec, encounter, rng, cfg))
        if not devices:
            continue
        ext = get_or_create_container(rec, "extensions", dict)
        ext["device"] = devices
