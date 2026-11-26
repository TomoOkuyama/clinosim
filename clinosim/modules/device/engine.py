"""Pure functions for the device module (AD-55).

place_devices_for_encounter takes a CIFPatientRecord + Encounter and
returns a list of DeviceRecord for that encounter (deterministic; no RNG),
honouring devices.yaml placement criteria. State unchanged
(BNP-pattern surgical principle).

Placement and removal dates follow the placing event and the end of the
device's indication (Issue #3516, ``simulator/device_removal.py``); a device
whose indication never ends is removed on the discharge date.
"""

from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from clinosim.codes import code_exists
from clinosim.datafiles import load_data_yaml
from clinosim.types.clinical import PhysiologicalState
from clinosim.types.device import DeviceRecord
from clinosim.types.encounter import Encounter, EncounterType
from clinosim.types.output import CIFPatientRecord

_HERE = Path(__file__).resolve().parent
_REF_DIR = _HERE / "reference_data"


# Indication tokens ``_evaluate_indications`` can return; placement criteria
# in devices.yaml may name only these (Issue #2760).
INDICATION_TOKENS = frozenset({"severity_moderate_plus", "altered_consciousness", "hypoxia", "intubated"})


class _Criterion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    any: list[str] = Field(min_length=1)

    @field_validator("any")
    @classmethod
    def _known(cls, tokens: list[str]) -> list[str]:
        unknown = sorted(set(tokens) - INDICATION_TOKENS)
        if unknown:
            raise ValueError(f"devices.yaml: unknown placement tokens {unknown}; expected {sorted(INDICATION_TOKENS)}")
        return tokens


class _Device(BaseModel):
    model_config = ConfigDict(extra="forbid")

    snomed_code: str
    # Empty: not an ICU device (placed by its own rule, e.g. non-invasive ventilation, Issue #3705).
    placement_criteria: list[_Criterion]
    # A home device (Issue #3837): ICD-10 prefixes of the chronic conditions whose
    # treatment it is, and the ``procedure_type`` names of the therapy that dates
    # its start.
    home_for_conditions: list[str] = Field(default_factory=list)
    therapy_procedure_types: list[str] = Field(default_factory=list)

    @field_validator("snomed_code")
    @classmethod
    def _registered(cls, code: str) -> str:
        if not code_exists("snomed-ct", code, exact=True):
            raise ValueError(f"devices.yaml SNOMED {code!r} not in codes/data/snomed-ct.yaml")
        return code


class _DevicesConfig(BaseModel):
    """Shape of devices.yaml (Issue #2760)."""

    model_config = ConfigDict(extra="forbid")

    metadata: dict[str, Any] = Field(default_factory=dict)
    devices: dict[str, _Device] = Field(min_length=1)


@lru_cache(maxsize=1)
def load_devices_config() -> dict[str, Any]:
    """Load device reference data from devices.yaml (cached, validated)."""
    data = load_data_yaml(_REF_DIR / "devices.yaml")
    _DevicesConfig.model_validate(data)
    return data


def _evaluate_indications(
    state: PhysiologicalState,
    severity_moderate_plus: bool,
    altered_consciousness: bool,
    intubated: bool = False,
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
    # Issue #2091: hypoxia from the oxygenation axis (or shock-level perfusion);
    # the ventilator is tied to an actual intubation.
    if state.perfusion_status < 0.4 or state.oxygenation_impairment >= 0.6:
        indications.add("hypoxia")
    if intubated:
        indications.add("intubated")
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


def _altered_consciousness_for_encounter(record: CIFPatientRecord, encounter: Encounter) -> bool:
    """True if any vital_sign for this encounter has GCS < 13."""
    enc_id = encounter.encounter_id
    for vs in record.vital_signs or []:
        if getattr(vs, "encounter_id", "") != enc_id:
            continue
        gcs = getattr(vs, "gcs_score", None)
        if gcs is not None and gcs < 13:
            return True
    return False


def _peak_state_for_encounter(record: CIFPatientRecord, encounter: Encounter) -> PhysiologicalState:
    """Worst state of the stay (Issue #2091): lowest perfusion, highest
    oxygenation impairment, highest respiratory fraction. Falls back to a
    default PhysiologicalState when the patient has none."""
    states = record.physiological_states or []
    if not states:
        return PhysiologicalState(timestamp=encounter.admission_datetime)
    return PhysiologicalState(
        timestamp=states[0].timestamp,
        perfusion_status=min(s.perfusion_status for s in states),
        oxygenation_impairment=max(s.oxygenation_impairment for s in states),
        respiratory_fraction=max(s.respiratory_fraction for s in states),
    )


def place_devices_for_encounter(
    record: CIFPatientRecord,
    encounter: Encounter,
    devices_config: dict[str, Any],
) -> list[DeviceRecord]:
    """Return DeviceRecord list for a single encounter.

    Returns [] for a non-inpatient encounter. Two sources of devices:

    - ICU devices (devices.yaml criteria met by an ICU stay);
    - a catheter placed by an insertion procedure or a catheter order of the
      stay that has no ICU device of its type (Issue #3516).

    The placement is the date of the placing event (insertion procedure,
    catheter order, else the ICU transfer day) and the removal the day the
    device's indication ended (``simulator/device_removal.py``). Draws no RNG.
    """
    if encounter.encounter_type != EncounterType.INPATIENT:
        return []
    from clinosim.simulator.device_removal import (
        device_removal_rules,
        extubation_date,
        noninvasive_ventilation_dates,
        placing_date,
        removal_date,
        surgery_dates,
    )

    rules = device_removal_rules().kinds
    admitted = encounter.admission_datetime.date()
    discharged = encounter.discharge_datetime.date() if encounter.discharge_datetime else None
    states = record.physiological_states or []
    operations = surgery_dates(record, encounter)
    enc_id = encounter.encounter_id or "unknown"
    out: list[DeviceRecord] = []

    def _add(device_type: str, placed: date, indication: str, origin: str) -> None:
        rule = rules[device_type]
        removed, basis = removal_date(
            rule, placed=placed, admitted=admitted, discharged=discharged, states=states, operations=operations
        )
        if device_type == "mechanical_ventilator" and (ext := extubation_date(record, encounter)) is not None:
            # Issue #3535: the ventilator comes off at the extubation, not at discharge.
            if removed is None or ext < removed:
                removed, basis = ext, "extubation"
        if removed is not None and removed < placed:
            removed = placed
        # feedback FB-F2: FHIR id 型は英数字+'-'+'.' のみ許可、_ 禁止。
        # device_type YAML key(indwelling_catheter 等)の _ を - に置換。
        _device_type_id = device_type.replace("_", "-")
        out.append(
            DeviceRecord(
                device_id=f"dev-{enc_id}-{_device_type_id}-{len(out)}",
                encounter_id=enc_id,
                device_type=device_type,
                snomed_code=devices_config["devices"][device_type]["snomed_code"],
                placement_date=placed.isoformat(),
                removal_date=removed.isoformat() if removed is not None else None,
                placement_indication=indication,
                origin=origin,
                removal_indication=basis,
            )
        )

    if record.icu_transferred:
        # severity_moderate_plus: ICU transfer ≈ severity moderate+
        altered = _altered_consciousness_for_encounter(record, encounter)
        state = _peak_state_for_encounter(record, encounter)
        intubated = any(
            getattr(p, "procedure_type", "") == "intubation"
            and getattr(p, "encounter_id", "") == encounter.encounter_id
            for p in (record.procedures or [])
        )
        indications = _evaluate_indications(state, True, altered, intubated=intubated)
        icu_day = record.icu_transferred_day if record.icu_transferred_day > 0 else 0
        icu_date = admitted + timedelta(days=icu_day)
        for device_type, cfg in devices_config["devices"].items():
            if not _indications_met(cfg["placement_criteria"], indications):
                continue
            placed = placing_date(rules[device_type], record, encounter) or icu_date
            _add(device_type, placed, ",".join(sorted(indications)), "icu_stay")
    niv = noninvasive_ventilation_dates(record, encounter)
    if niv is not None:
        # Issue #3705: the BiPAP/CPAP device of a stay put on non-invasive ventilation.
        placed, niv_removed = niv
        _add("noninvasive_ventilator", placed, "respiratory_failure", "niv")
        if niv_removed is not None:
            out[-1].removal_date = max(placed, niv_removed).isoformat()
            out[-1].removal_indication = "niv_weaned"
    placed_types = {d.device_type for d in out}
    for device_type, rule in rules.items():
        if device_type in placed_types or not rule.indications:
            continue
        inserted = placing_date(rule, record, encounter)
        if inserted is not None:
            _add(device_type, inserted, "catheter_insertion", "insertion")
    return out


def place_home_devices(record: Any, devices_config: dict[str, Any]) -> list[DeviceRecord]:
    """Home devices of the patient's chronic conditions (Issue #3837): a CPAP
    unit for obstructive sleep apnea. ``origin="home"``, no removal (the unit is
    in use), no infection sampling. The unit is placed at the date of the
    patient's first recorded therapy procedure, else at the condition onset.
    Draws no RNG."""
    from clinosim.modules._shared import get_attr_or_key as _g
    from clinosim.simulator.device_removal import _to_date

    patient = _g(record, "patient")
    pid = str(_g(patient, "patient_id", "") or "")
    conditions = list(_g(patient, "chronic_conditions", []) or [])
    out: list[DeviceRecord] = []
    for device_type, cfg in devices_config["devices"].items():
        prefixes = tuple(cfg.get("home_for_conditions") or ())
        if not prefixes or not pid:
            continue
        match = next((c for c in conditions if str(_g(c, "code", "") or "").startswith(prefixes)), None)
        if match is None:
            continue
        types = set(cfg.get("therapy_procedure_types") or ())
        therapy = sorted(
            (d, str(_g(p, "encounter_id", "") or ""))
            for p in _g(record, "procedures", []) or []
            if _g(p, "procedure_type", "") in types and (d := _to_date(_g(p, "start_datetime", None))) is not None
        )
        placed = therapy[0][0] if therapy else _to_date(_g(match, "onset_date", None))
        if placed is None:
            continue
        out.append(
            DeviceRecord(
                device_id=f"dev-{pid}-{device_type.replace('_', '-')}",
                encounter_id=therapy[0][1] if therapy else "",
                device_type=device_type,
                snomed_code=cfg["snomed_code"],
                placement_date=placed.isoformat(),
                removal_date=None,
                placement_indication=str(_g(match, "code", "") or ""),
                origin="home",
            )
        )
    return out
