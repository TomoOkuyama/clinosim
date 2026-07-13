"""Unit tests for clinosim.modules.device.engine (PR-A)."""
from __future__ import annotations

from datetime import datetime

import numpy as np
import pytest

from clinosim.modules.device.engine import (
    _evaluate_indications,
    _indications_met,
    load_devices_config,
    place_devices_for_encounter,
)
from clinosim.types.clinical import PhysiologicalState
from clinosim.types.device import DeviceRecord
from clinosim.types.encounter import Encounter, EncounterType
from clinosim.types.output import CIFPatientRecord

pytestmark = pytest.mark.unit


def test_load_devices_config_returns_three_devices():
    cfg = load_devices_config()
    assert set(cfg["devices"].keys()) == {
        "cvc", "indwelling_catheter", "mechanical_ventilator",
    }


def test_load_devices_config_snomed_codes():
    cfg = load_devices_config()
    assert cfg["devices"]["cvc"]["snomed_code"] == "52124006"
    assert cfg["devices"]["indwelling_catheter"]["snomed_code"] == "23973005"
    assert cfg["devices"]["mechanical_ventilator"]["snomed_code"] == "706172005"


def test_indications_met_any_clause_true_if_any_token_in_set():
    criteria = [{"any": ["severity_moderate_plus", "altered_consciousness"]}]
    assert _indications_met(criteria, {"severity_moderate_plus"}) is True
    assert _indications_met(criteria, {"altered_consciousness"}) is True
    assert _indications_met(criteria, {"hypoxia"}) is False


def test_indications_met_empty_set_is_false():
    criteria = [{"any": ["severity_moderate_plus"]}]
    assert _indications_met(criteria, set()) is False


def test_indications_met_empty_criteria_is_false():
    assert _indications_met([], {"severity_moderate_plus"}) is False


def test_evaluate_indications_severity_moderate_only():
    state = PhysiologicalState()
    indications = _evaluate_indications(
        state, severity_moderate_plus=True, altered_consciousness=False,
    )
    assert indications == {"severity_moderate_plus"}


def test_evaluate_indications_mild_severity_no_token():
    state = PhysiologicalState()
    indications = _evaluate_indications(
        state, severity_moderate_plus=False, altered_consciousness=False,
    )
    assert indications == set()


def test_evaluate_indications_altered_consciousness():
    state = PhysiologicalState()
    indications = _evaluate_indications(
        state, severity_moderate_plus=False, altered_consciousness=True,
    )
    assert indications == {"altered_consciousness"}


def test_evaluate_indications_hypoxia_proxy_perfusion_low():
    state = PhysiologicalState(perfusion_status=0.3)
    indications = _evaluate_indications(
        state, severity_moderate_plus=False, altered_consciousness=False,
    )
    assert "hypoxia" in indications


def test_evaluate_indications_high_respiratory_demand():
    state = PhysiologicalState(respiratory_fraction=0.8)
    indications = _evaluate_indications(
        state, severity_moderate_plus=False, altered_consciousness=False,
    )
    assert "high_respiratory_demand" in indications


def test_place_devices_for_encounter_no_icu_returns_empty():
    rec = CIFPatientRecord()
    rec.icu_transferred = False
    enc = Encounter(encounter_id="enc1", encounter_type=EncounterType.INPATIENT)
    rng = np.random.default_rng(42)
    cfg = load_devices_config()
    out = place_devices_for_encounter(rec, enc, rng, cfg)
    assert out == []


def test_place_devices_for_encounter_non_inpatient_returns_empty():
    rec = CIFPatientRecord()
    rec.icu_transferred = True   # ICU flagged but encounter is outpatient
    enc = Encounter(encounter_id="enc1", encounter_type=EncounterType.OUTPATIENT)
    rng = np.random.default_rng(42)
    cfg = load_devices_config()
    out = place_devices_for_encounter(rec, enc, rng, cfg)
    assert out == []


def test_place_devices_for_encounter_icu_inpatient_emits_cvc_and_catheter():
    """ICU inpatient meets severity_moderate_plus → CVC + catheter."""
    rec = CIFPatientRecord()
    rec.icu_transferred = True
    enc = Encounter(
        encounter_id="enc1",
        encounter_type=EncounterType.INPATIENT,
        admission_datetime=datetime(2026, 1, 1, 8, 0, 0),
        discharge_datetime=datetime(2026, 1, 8, 14, 0, 0),
    )
    rng = np.random.default_rng(42)
    cfg = load_devices_config()
    out = place_devices_for_encounter(rec, enc, rng, cfg)
    types = {d.device_type for d in out}
    assert "cvc" in types
    assert "indwelling_catheter" in types
    # Ventilator only if hypoxia / high_respiratory_demand → not in default state
    assert "mechanical_ventilator" not in types


def test_place_devices_for_encounter_includes_ventilator_when_respiratory():
    rec = CIFPatientRecord()
    rec.icu_transferred = True
    rec.physiological_states = [
        PhysiologicalState(respiratory_fraction=0.8)
    ]
    enc = Encounter(
        encounter_id="enc1",
        encounter_type=EncounterType.INPATIENT,
        admission_datetime=datetime(2026, 1, 1),
        discharge_datetime=datetime(2026, 1, 10),
    )
    rng = np.random.default_rng(42)
    cfg = load_devices_config()
    out = place_devices_for_encounter(rec, enc, rng, cfg)
    assert any(d.device_type == "mechanical_ventilator" for d in out)


def test_place_devices_for_encounter_device_id_format():
    rec = CIFPatientRecord()
    rec.icu_transferred = True
    enc = Encounter(
        encounter_id="abc-123",
        encounter_type=EncounterType.INPATIENT,
        admission_datetime=datetime(2026, 1, 1),
        discharge_datetime=datetime(2026, 1, 5),
    )
    rng = np.random.default_rng(42)
    out = place_devices_for_encounter(rec, enc, rng, load_devices_config())
    for d in out:
        # feedback FB-F2: FHIR id 型準拠のため device_type の _ を - に置換
        _device_type_id = d.device_type.replace("_", "-")
        assert d.device_id.startswith(f"dev-abc-123-{_device_type_id}-")
        assert d.encounter_id == "abc-123"
        assert d.placement_date == "2026-01-01"
        assert d.removal_date == "2026-01-05"
        assert isinstance(d, DeviceRecord)


def test_place_devices_for_encounter_snapshot_in_progress_removal_none():
    rec = CIFPatientRecord()
    rec.icu_transferred = True
    enc = Encounter(
        encounter_id="enc1",
        encounter_type=EncounterType.INPATIENT,
        admission_datetime=datetime(2026, 1, 1),
        discharge_datetime=None,
    )
    rng = np.random.default_rng(42)
    out = place_devices_for_encounter(rec, enc, rng, load_devices_config())
    assert all(d.removal_date is None for d in out)
