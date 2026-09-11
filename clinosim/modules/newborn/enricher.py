"""POST_ENCOUNTER enricher for newborn birth-admission workup (#1252).

Runs after every simulated encounter, gates on the newborn-birth record
(perinatal.py stamps ``condition_event.condition_type = "newborn_birth"``
on the baby-side CIF record) and appends the clinical events this
module owns. This PR's slice: Vitamin K prophylaxis (JP oral × 2, US
IM × 1). Follow-up PRs stack Apgar / hearing screen / metabolic screen
/ bilirubin / CCHD SpO2 / ophthalmic prophylaxis in the same seam.

Enricher order (see `clinosim/simulator/enrichers.py`): 92 — after
`nursing_assignment` (94) is not required (no dependency) but this is
placed before `document` (95) so any downstream document narrative
that references Vitamin K administration has the MAR entry in hand.
"""

from __future__ import annotations

import logging
from typing import Any

from clinosim.modules._shared import get_attr_or_key as _get
from clinosim.modules._shared import set_attr_or_key as _set
from clinosim.modules.newborn.engine import (
    build_apgar_scores,
    build_newborn_shift_vitals,
    build_vitamin_k_administrations,
    is_newborn_birth_record,
)

logger = logging.getLogger(__name__)


def enrich_newborn(ctx: Any) -> None:
    """POST_ENCOUNTER entrypoint. Iterates `ctx.records`, no-ops on
    non-newborn records, appends Vitamin K MAR entries to newborn
    records. RNG-free (deterministic schedule from
    `newborn_screening.yaml`).
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
        except Exception:  # pragma: no cover — defensive
            logger.exception("newborn enricher failed on record; continuing")
            continue
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
