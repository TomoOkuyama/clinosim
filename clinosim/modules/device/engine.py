"""Pure functions for the device module (AD-55).

place_devices_for_encounter takes a CIFPatientRecord + Encounter +
sub-rng and returns a list of DeviceRecord for that encounter,
honouring devices.yaml placement criteria. State unchanged
(BNP-pattern surgical principle).

Phase 1 simplification (PR-A): ICU stay period is approximated as the
inpatient Encounter's admission_datetime / discharge_datetime, because
the CIF does not currently record an explicit ICU sub-period. This
slightly over-estimates true ICU line-days but stays clinically
defensible for the HAI Phase 2 risk-window computation.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from clinosim.types.clinical import PhysiologicalState
from clinosim.types.device import DeviceRecord
from clinosim.types.encounter import Encounter, EncounterType
from clinosim.types.output import CIFPatientRecord

_HERE = Path(__file__).resolve().parent
_REF_DIR = _HERE / "reference_data"


@lru_cache(maxsize=1)
def load_devices_config() -> dict[str, Any]:
    """Load device reference data from devices.yaml (cached)."""
    with (_REF_DIR / "devices.yaml").open() as f:
        data = yaml.safe_load(f)
    return data


def _evaluate_indications(
    state: PhysiologicalState,
    severity_moderate_plus: bool,
    altered_consciousness: bool,
) -> set[str]:
    """Return the set of indication tokens met at ICU transfer time.

    Tokens:
      severity_moderate_plus — passed in (derived from record.icu_transferred
                               AND encounter.encounter_type == INPATIENT)
      altered_consciousness  — passed in (derived from vital_signs[i].gcs_score
                               < 13 within encounter scope)
      hypoxia                — state.perfusion_status < 0.4 (proxy for
                               severe-illness hypoxia; SpO2 not on
                               PhysiologicalState in v0.2)
      high_respiratory_demand — state.respiratory_fraction > 0.7
                                (COPD/asthma CO2 retention pattern)
    """
    indications: set[str] = set()
    if severity_moderate_plus:
        indications.add("severity_moderate_plus")
    if altered_consciousness:
        indications.add("altered_consciousness")
    if state.perfusion_status < 0.4:
        indications.add("hypoxia")
    if state.respiratory_fraction > 0.7:
        indications.add("high_respiratory_demand")
    return indications


def _indications_met(criteria: list[dict], met: set[str]) -> bool:
    """Evaluate a criteria list. Currently only 'any:' clauses supported."""
    if not criteria:
        return False
    for clause in criteria:
        if "any" in clause and any(tok in met for tok in clause["any"]):
            return True
    return False


def _altered_consciousness_for_encounter(
    record: CIFPatientRecord, encounter: Encounter
) -> bool:
    """True if any vital_sign for this encounter has GCS < 13."""
    enc_id = encounter.encounter_id
    for vs in record.vital_signs or []:
        if getattr(vs, "encounter_id", "") != enc_id:
            continue
        gcs = getattr(vs, "gcs_score", None)
        if gcs is not None and gcs < 13:
            return True
    return False


def _peak_state_for_encounter(
    record: CIFPatientRecord, encounter: Encounter
) -> PhysiologicalState:
    """Pick a representative PhysiologicalState for the encounter.

    Phase 1 simplification: use the first recorded state; falls back to a
    default PhysiologicalState when the patient has none.
    """
    if record.physiological_states:
        return record.physiological_states[0]
    return PhysiologicalState()


def place_devices_for_encounter(
    record: CIFPatientRecord,
    encounter: Encounter,
    rng: np.random.Generator,
    devices_config: dict[str, Any],
) -> list[DeviceRecord]:
    """Return DeviceRecord list for a single encounter.

    Returns [] when:
    - the patient did not transfer to ICU during their stay
    - the encounter is not an inpatient encounter
    - no device's placement_criteria are met by the patient state
    """
    if not record.icu_transferred:
        return []
    if encounter.encounter_type != EncounterType.INPATIENT:
        return []
    severity_moderate_plus = True   # ICU transfer ≈ severity moderate+
    altered = _altered_consciousness_for_encounter(record, encounter)
    state = _peak_state_for_encounter(record, encounter)
    indications = _evaluate_indications(state, severity_moderate_plus, altered)
    placement = encounter.admission_datetime.date().isoformat()
    removal = (
        encounter.discharge_datetime.date().isoformat()
        if encounter.discharge_datetime
        else None
    )
    out: list[DeviceRecord] = []
    enc_id = encounter.encounter_id or "unknown"
    for device_type, cfg in devices_config["devices"].items():
        if not _indications_met(cfg["placement_criteria"], indications):
            continue
        out.append(DeviceRecord(
            device_id=f"dev-{enc_id}-{device_type}-{len(out)}",
            encounter_id=enc_id,
            device_type=device_type,
            snomed_code=cfg["snomed_code"],
            placement_date=placement,
            removal_date=removal,
            placement_indication=",".join(sorted(indications)),
        ))
    return out
