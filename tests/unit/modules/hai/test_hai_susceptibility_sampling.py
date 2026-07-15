"""Unit tests for HAI antibiogram-driven S/I/R susceptibility sampling (Task 5)."""

import numpy as np
import pytest

from clinosim.modules.antibiotic import ANTIBIOTIC_LOINC_LOOKUP
from clinosim.modules.hai import HAI_TYPES, load_hai_antibiogram
from clinosim.modules.hai.enricher import _append_hai_culture
from clinosim.types.hai import HAIEvent


@pytest.fixture(scope="module")
def antibiogram():
    return load_hai_antibiogram()


def _make_event(hai_type, organism_snomed, hai_id="hai-enc1-x-0"):
    return HAIEvent(
        hai_id=hai_id,
        encounter_id="enc1",
        hai_type=hai_type,
        source_device_id="dev1",
        icd10_code="T80.211A",
        snomed_code="111111111",
        onset_date="2024-01-15",
        organism_snomed=organism_snomed,
        culture_specimen_id=f"spec-{hai_id}",
    )


def _spec_cfg():
    return {"specimen": "blood", "specimen_snomed": "119297000", "test_loinc": "600-7"}


@pytest.mark.unit
def test_susceptibilities_populated_for_clabsi_saureus(antibiogram):
    rec = {}
    ev = _make_event(HAI_TYPES[0], "3092008")
    rng = np.random.default_rng(42)
    _append_hai_culture(rec, ev, _spec_cfg(), "2024-01-15", antibiogram, rng)
    micros = rec["microbiology"]
    assert len(micros) == 1
    susc = micros[0].susceptibilities
    assert len(susc) == 6  # 6 abx in antibiogram for clabsi/3092008
    for r in susc:
        assert r.interpretation in {"S", "I", "R"}


@pytest.mark.unit
def test_hai_event_id_backref_set(antibiogram):
    rec = {}
    ev = _make_event(HAI_TYPES[0], "3092008", hai_id="hai-test-id")
    rng = np.random.default_rng(42)
    _append_hai_culture(rec, ev, _spec_cfg(), "2024-01-15", antibiogram, rng)
    assert rec["microbiology"][0].hai_event_id == "hai-test-id"


@pytest.mark.unit
def test_vancomycin_always_s_for_saureus(antibiogram):
    """vancomycin row is [1.00, 0.00, 0.00] in clabsi/3092008."""
    for seed in range(20):
        rec = {}
        ev = _make_event(HAI_TYPES[0], "3092008")
        rng = np.random.default_rng(seed)
        _append_hai_culture(rec, ev, _spec_cfg(), "2024-01-15", antibiogram, rng)
        vanc = [
            r
            for r in rec["microbiology"][0].susceptibilities
            if r.antibiotic_loinc == ANTIBIOTIC_LOINC_LOOKUP["vancomycin"]
        ]
        assert len(vanc) == 1
        assert vanc[0].interpretation == "S"


@pytest.mark.unit
def test_organism_not_in_antibiogram_yields_empty_susceptibilities(antibiogram):
    """E. faecalis is in hai_organisms.yaml but not antibiogram — empty list ok."""
    rec = {}
    ev = _make_event(HAI_TYPES[0], "78065002")  # E. faecalis
    rng = np.random.default_rng(42)
    _append_hai_culture(rec, ev, _spec_cfg(), "2024-01-15", antibiogram, rng)
    assert rec["microbiology"][0].susceptibilities == []


@pytest.mark.unit
def test_empirical_s_distribution_for_clabsi_ecoli(antibiogram):
    """E. coli ceftriaxone is [0.89, 0.02, 0.09] — 5000 trials → ~89% S."""
    s_count = 0
    n = 5000
    for seed in range(n):
        rec = {}
        ev = _make_event(HAI_TYPES[0], "112283007")
        rng = np.random.default_rng(seed)
        _append_hai_culture(rec, ev, _spec_cfg(), "2024-01-15", antibiogram, rng)
        ctx = [
            r
            for r in rec["microbiology"][0].susceptibilities
            if r.antibiotic_loinc == ANTIBIOTIC_LOINC_LOOKUP["ceftriaxone"]
        ]
        assert len(ctx) == 1
        if ctx[0].interpretation == "S":
            s_count += 1
    rate = s_count / n
    assert 0.87 <= rate <= 0.91, f"E. coli ceftriaxone S rate {rate:.3f} outside expected"
