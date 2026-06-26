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
