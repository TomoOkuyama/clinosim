"""Unit tests for microbiology load-time validation (PR-A Task 4)."""
from pathlib import Path
import textwrap

import pytest

from clinosim.modules.observation import microbiology as micro_mod


def _write_yaml(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "microbiology.yaml"
    p.write_text(textwrap.dedent(body))
    return p


@pytest.mark.unit
def test_healthy_yaml_loads_without_raising(monkeypatch, tmp_path):
    """Sanity: a well-formed YAML stays loadable."""
    healthy = """
    specimens:
      blood: {snomed: "119297000", test_loinc: "600-7"}
    antibiotics:
      vancomycin: "18991-2"
    organisms:
      staph:
        snomed: "3092008"
        antibiogram:
          vancomycin: [1.0, 0.0, 0.0]
    diseases:
      sepsis:
        organisms: {staph: 1.0}
        cultures:
          - {specimen: blood, order_prob: 1.0, growth_prob: 0.5}
    """
    yaml_path = _write_yaml(tmp_path, healthy)
    monkeypatch.setattr(micro_mod, "_REF_DIR", yaml_path.parent)
    micro_mod._load.cache_clear()  # noqa: SLF001
    try:
        data = micro_mod._load()
        assert "antibiotics" in data
    finally:
        micro_mod._load.cache_clear()  # noqa: SLF001


@pytest.mark.unit
def test_organism_antibiogram_with_typo_raises_at_load_time(monkeypatch, tmp_path):
    """The load-bearing guarantee: typo in organism antibiogram key is loud."""
    bad = """
    specimens:
      blood: {snomed: "119297000", test_loinc: "600-7"}
    antibiotics:
      vancomycin: "18991-2"
    organisms:
      staph:
        snomed: "3092008"
        antibiogram:
          vancomicin: [1.0, 0.0, 0.0]
    diseases:
      sepsis:
        organisms: {staph: 1.0}
        cultures:
          - {specimen: blood, order_prob: 1.0, growth_prob: 0.5}
    """
    yaml_path = _write_yaml(tmp_path, bad)
    monkeypatch.setattr(micro_mod, "_REF_DIR", yaml_path.parent)
    micro_mod._load.cache_clear()  # noqa: SLF001
    try:
        with pytest.raises(ValueError, match="unknown antibiotic key 'vancomicin'"):
            micro_mod._load()
    finally:
        micro_mod._load.cache_clear()  # noqa: SLF001


@pytest.mark.unit
def test_disease_references_unknown_organism_raises(monkeypatch, tmp_path):
    """Cross-reference #2: disease.organisms key not in organisms section."""
    bad = """
    specimens:
      blood: {snomed: "119297000", test_loinc: "600-7"}
    antibiotics:
      vancomycin: "18991-2"
    organisms:
      staph:
        snomed: "3092008"
        antibiogram:
          vancomycin: [1.0, 0.0, 0.0]
    diseases:
      sepsis:
        organisms: {stapph: 1.0}
        cultures:
          - {specimen: blood, order_prob: 1.0, growth_prob: 0.5}
    """
    yaml_path = _write_yaml(tmp_path, bad)
    monkeypatch.setattr(micro_mod, "_REF_DIR", yaml_path.parent)
    micro_mod._load.cache_clear()  # noqa: SLF001
    try:
        with pytest.raises(ValueError, match="unknown organism 'stapph'"):
            micro_mod._load()
    finally:
        micro_mod._load.cache_clear()  # noqa: SLF001


@pytest.mark.unit
def test_disease_culture_references_unknown_specimen_raises(monkeypatch, tmp_path):
    """Cross-reference #3: disease.cultures[i].specimen not in specimens section."""
    bad = """
    specimens:
      blood: {snomed: "119297000", test_loinc: "600-7"}
    antibiotics:
      vancomycin: "18991-2"
    organisms:
      staph:
        snomed: "3092008"
        antibiogram:
          vancomycin: [1.0, 0.0, 0.0]
    diseases:
      sepsis:
        organisms: {staph: 1.0}
        cultures:
          - {specimen: blod, order_prob: 1.0, growth_prob: 0.5}
    """
    yaml_path = _write_yaml(tmp_path, bad)
    monkeypatch.setattr(micro_mod, "_REF_DIR", yaml_path.parent)
    micro_mod._load.cache_clear()  # noqa: SLF001
    try:
        with pytest.raises(ValueError, match="unknown specimen 'blod'"):
            micro_mod._load()
    finally:
        micro_mod._load.cache_clear()  # noqa: SLF001


@pytest.mark.unit
def test_specimen_missing_snomed_raises(monkeypatch, tmp_path):
    """Cross-reference #5: specimen.snomed must be a non-empty string."""
    bad = """
    specimens:
      blood: {snomed: "", test_loinc: "600-7"}
    antibiotics:
      vancomycin: "18991-2"
    organisms:
      staph:
        snomed: "3092008"
        antibiogram:
          vancomycin: [1.0, 0.0, 0.0]
    diseases:
      sepsis:
        organisms: {staph: 1.0}
        cultures:
          - {specimen: blood, order_prob: 1.0, growth_prob: 0.5}
    """
    yaml_path = _write_yaml(tmp_path, bad)
    monkeypatch.setattr(micro_mod, "_REF_DIR", yaml_path.parent)
    micro_mod._load.cache_clear()  # noqa: SLF001
    try:
        with pytest.raises(ValueError, match="invalid SNOMED"):
            micro_mod._load()
    finally:
        micro_mod._load.cache_clear()  # noqa: SLF001


@pytest.mark.unit
def test_specimen_missing_test_loinc_raises(monkeypatch, tmp_path):
    """Cross-reference #6: specimen.test_loinc must be a non-empty string."""
    bad = """
    specimens:
      blood: {snomed: "119297000", test_loinc: ""}
    antibiotics:
      vancomycin: "18991-2"
    organisms:
      staph:
        snomed: "3092008"
        antibiogram:
          vancomycin: [1.0, 0.0, 0.0]
    diseases:
      sepsis:
        organisms: {staph: 1.0}
        cultures:
          - {specimen: blood, order_prob: 1.0, growth_prob: 0.5}
    """
    yaml_path = _write_yaml(tmp_path, bad)
    monkeypatch.setattr(micro_mod, "_REF_DIR", yaml_path.parent)
    micro_mod._load.cache_clear()  # noqa: SLF001
    try:
        with pytest.raises(ValueError, match="invalid test_loinc"):
            micro_mod._load()
    finally:
        micro_mod._load.cache_clear()  # noqa: SLF001


@pytest.mark.unit
def test_disease_organisms_as_list_raises_valueerror(monkeypatch, tmp_path):
    """disease.organisms as list (not dict) must raise ValueError, not AttributeError."""
    bad = """
    specimens:
      blood: {snomed: "119297000", test_loinc: "600-7"}
    antibiotics:
      vancomycin: "18991-2"
    organisms:
      staph:
        snomed: "3092008"
        antibiogram:
          vancomycin: [1.0, 0.0, 0.0]
    diseases:
      sepsis:
        organisms:
          - staph
        cultures:
          - {specimen: blood, order_prob: 1.0, growth_prob: 0.5}
    """
    yaml_path = _write_yaml(tmp_path, bad)
    monkeypatch.setattr(micro_mod, "_REF_DIR", yaml_path.parent)
    micro_mod._load.cache_clear()  # noqa: SLF001
    try:
        with pytest.raises(ValueError, match="'organisms' must be a mapping"):
            micro_mod._load()
    finally:
        micro_mod._load.cache_clear()  # noqa: SLF001


@pytest.mark.unit
def test_organism_missing_snomed_raises(monkeypatch, tmp_path):
    """Cross-reference #4: organism.snomed must be a non-empty string."""
    bad = """
    specimens:
      blood: {snomed: "119297000", test_loinc: "600-7"}
    antibiotics:
      vancomycin: "18991-2"
    organisms:
      staph:
        snomed: ""
        antibiogram:
          vancomycin: [1.0, 0.0, 0.0]
    diseases:
      sepsis:
        organisms: {staph: 1.0}
        cultures:
          - {specimen: blood, order_prob: 1.0, growth_prob: 0.5}
    """
    yaml_path = _write_yaml(tmp_path, bad)
    monkeypatch.setattr(micro_mod, "_REF_DIR", yaml_path.parent)
    micro_mod._load.cache_clear()  # noqa: SLF001
    try:
        with pytest.raises(ValueError, match="invalid SNOMED"):
            micro_mod._load()
    finally:
        micro_mod._load.cache_clear()  # noqa: SLF001


@pytest.mark.unit
def test_organism_antibiogram_sir_triple_wrong_length_raises(monkeypatch, tmp_path):
    """Cross-reference #8: organism.antibiogram[key] must be exactly 3 elements [S, I, R]."""
    bad = """
    specimens:
      blood: {snomed: "119297000", test_loinc: "600-7"}
    antibiotics:
      vancomycin: "18991-2"
    organisms:
      staph:
        snomed: "3092008"
        antibiogram:
          vancomycin: [1.0, 0.0]
    diseases:
      sepsis:
        organisms: {staph: 1.0}
        cultures:
          - {specimen: blood, order_prob: 1.0, growth_prob: 0.5}
    """
    yaml_path = _write_yaml(tmp_path, bad)
    monkeypatch.setattr(micro_mod, "_REF_DIR", yaml_path.parent)
    micro_mod._load.cache_clear()  # noqa: SLF001
    try:
        with pytest.raises(ValueError, match="3-element \\[S, I, R\\] list"):
            micro_mod._load()
    finally:
        micro_mod._load.cache_clear()  # noqa: SLF001


@pytest.mark.unit
def test_organism_antibiogram_sir_triple_zero_sum_raises(monkeypatch, tmp_path):
    """Cross-reference #8: organism.antibiogram[key] SIR triple must sum > 0."""
    bad = """
    specimens:
      blood: {snomed: "119297000", test_loinc: "600-7"}
    antibiotics:
      vancomycin: "18991-2"
    organisms:
      staph:
        snomed: "3092008"
        antibiogram:
          vancomycin: [0.0, 0.0, 0.0]
    diseases:
      sepsis:
        organisms: {staph: 1.0}
        cultures:
          - {specimen: blood, order_prob: 1.0, growth_prob: 0.5}
    """
    yaml_path = _write_yaml(tmp_path, bad)
    monkeypatch.setattr(micro_mod, "_REF_DIR", yaml_path.parent)
    micro_mod._load.cache_clear()  # noqa: SLF001
    try:
        with pytest.raises(ValueError, match="SIR triple sums to zero"):
            micro_mod._load()
    finally:
        micro_mod._load.cache_clear()  # noqa: SLF001


@pytest.mark.unit
def test_antibiotic_empty_loinc_raises(monkeypatch, tmp_path):
    """Cross-reference #7: antibiotics[key] value must be non-empty string (LOINC)."""
    bad = """
    specimens:
      blood: {snomed: "119297000", test_loinc: "600-7"}
    antibiotics:
      vancomycin: ""
    organisms:
      staph:
        snomed: "3092008"
        antibiogram:
          vancomycin: [1.0, 0.0, 0.0]
    diseases:
      sepsis:
        organisms: {staph: 1.0}
        cultures:
          - {specimen: blood, order_prob: 1.0, growth_prob: 0.5}
    """
    yaml_path = _write_yaml(tmp_path, bad)
    monkeypatch.setattr(micro_mod, "_REF_DIR", yaml_path.parent)
    micro_mod._load.cache_clear()  # noqa: SLF001
    try:
        with pytest.raises(ValueError, match="invalid LOINC value"):
            micro_mod._load()
    finally:
        micro_mod._load.cache_clear()  # noqa: SLF001
