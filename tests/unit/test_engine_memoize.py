"""F4 memoize test: cache manifest / eligibility / hit / miss / staleness。"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from clinosim.simulator.memoize import (
    CacheManifest,
    compute_config_hash,
    eligible_patient_ids,
    is_cache_valid,
    read_cache_manifest,
    write_cache_manifest,
)
from clinosim.types.config import SimulatorConfig
from clinosim.types.encounter import Encounter, EncounterType
from clinosim.types.output import CIFPatientRecord
from clinosim.types.patient import PatientProfile

pytestmark = pytest.mark.unit


def test_config_hash_stable():
    """同 config → 同 hash。"""
    c1 = SimulatorConfig(random_seed=42, catchment_population=200, country="US")
    c2 = SimulatorConfig(random_seed=42, catchment_population=200, country="US")
    assert compute_config_hash(c1) == compute_config_hash(c2)


def test_config_hash_ignores_snapshot_date():
    """snapshot_date が変わっても hash は同一(cache は cursor 越えで使うため)。"""
    c1 = SimulatorConfig(
        random_seed=42, catchment_population=200, country="US", snapshot_date="2026-05-31"
    )
    c2 = c1.model_copy(update={"snapshot_date": "2026-06-01"})
    assert compute_config_hash(c1) == compute_config_hash(c2)


def test_config_hash_detects_seed_change():
    """seed が違えば hash 変わる。"""
    c1 = SimulatorConfig(random_seed=42, catchment_population=200, country="US")
    c2 = c1.model_copy(update={"random_seed": 43})
    assert compute_config_hash(c1) != compute_config_hash(c2)


def test_config_hash_detects_country_change():
    """country が違えば hash 変わる。"""
    c1 = SimulatorConfig(random_seed=42, catchment_population=200, country="US")
    c2 = c1.model_copy(update={"country": "JP"})
    assert compute_config_hash(c1) != compute_config_hash(c2)


def test_write_and_read_manifest(tmp_path):
    config = SimulatorConfig(
        random_seed=42, catchment_population=200, country="US", snapshot_date="2026-05-31"
    )
    write_cache_manifest(tmp_path, config)
    manifest = read_cache_manifest(tmp_path)
    assert manifest is not None
    assert isinstance(manifest, CacheManifest)
    assert manifest.master_seed == 42
    assert manifest.country == "US"
    assert manifest.snapshot_date == "2026-05-31"


def test_read_manifest_absent_returns_none(tmp_path):
    assert read_cache_manifest(tmp_path) is None


def test_is_cache_valid_happy_path(tmp_path):
    config = SimulatorConfig(
        random_seed=42, catchment_population=200, country="US", snapshot_date="2026-05-31"
    )
    write_cache_manifest(tmp_path, config)
    # cursor だけ進めた
    new_config = config.model_copy(update={"snapshot_date": "2026-06-01"})
    valid, reason = is_cache_valid(tmp_path, new_config)
    assert valid, reason


def test_is_cache_valid_seed_mismatch(tmp_path):
    config = SimulatorConfig(random_seed=42, catchment_population=200, country="US")
    write_cache_manifest(tmp_path, config)
    new_config = config.model_copy(update={"random_seed": 99})
    valid, reason = is_cache_valid(tmp_path, new_config)
    assert not valid
    assert "seed" in reason.lower()


def test_is_cache_valid_missing_manifest(tmp_path):
    config = SimulatorConfig(random_seed=42, catchment_population=200, country="US")
    valid, reason = is_cache_valid(tmp_path, config)
    assert not valid
    assert "manifest" in reason.lower() or "no cache" in reason.lower()


def test_eligible_patient_ids_all_completed():
    """全 encounter が prev_cursor 以前に discharge 済 → eligible。"""
    patient = PatientProfile(patient_id="p1")
    enc = Encounter(
        encounter_id="e1",
        patient_id="p1",
        encounter_type=EncounterType.INPATIENT,
        admission_datetime=datetime(2025, 5, 1),
        discharge_datetime=datetime(2025, 5, 10),
    )
    r = CIFPatientRecord(patient=patient, encounters=[enc])
    result = eligible_patient_ids([r], date(2025, 6, 30))
    assert result == {"p1"}


def test_eligible_patient_ids_in_progress_excluded():
    """discharge_datetime = None (in-progress) → not eligible。"""
    patient = PatientProfile(patient_id="p1")
    enc = Encounter(
        encounter_id="e1",
        patient_id="p1",
        encounter_type=EncounterType.INPATIENT,
        admission_datetime=datetime(2025, 6, 25),
        discharge_datetime=None,  # in-progress
    )
    r = CIFPatientRecord(patient=patient, encounters=[enc])
    result = eligible_patient_ids([r], date(2025, 6, 30))
    assert result == set()


def test_eligible_patient_ids_discharge_past_cursor_excluded():
    """discharge_datetime > prev_cursor → not eligible(cursor 越え)。"""
    patient = PatientProfile(patient_id="p1")
    enc = Encounter(
        encounter_id="e1",
        patient_id="p1",
        encounter_type=EncounterType.INPATIENT,
        admission_datetime=datetime(2025, 6, 25),
        discharge_datetime=datetime(2025, 7, 5),  # > cursor 2025-06-30
    )
    r = CIFPatientRecord(patient=patient, encounters=[enc])
    result = eligible_patient_ids([r], date(2025, 6, 30))
    assert result == set()
