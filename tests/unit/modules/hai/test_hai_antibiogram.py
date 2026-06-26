import pytest

from clinosim.modules.hai import HAI_TYPES, load_hai_antibiogram


def test_load_returns_nested_mapping():
    abg = load_hai_antibiogram()
    assert isinstance(abg, dict)
    for hai_type, organisms in abg.items():
        assert hai_type in HAI_TYPES
        for snomed, abx_table in organisms.items():
            assert isinstance(snomed, str)
            for abx_key, triple in abx_table.items():
                assert isinstance(triple, list)
                assert len(triple) == 3
                assert abs(sum(triple) - 1.0) < 0.01


def test_load_is_cached_idempotent():
    a = load_hai_antibiogram()
    b = load_hai_antibiogram()
    assert a is b


def _run_with_yaml(monkeypatch, tmp_path, yaml_text):
    yaml_path = tmp_path / "hai_antibiogram.yaml"
    yaml_path.write_text(yaml_text)
    from clinosim.modules import hai

    hai.load_hai_antibiogram.cache_clear()  # noqa: SLF001
    monkeypatch.setattr(hai, "_HAI_ANTIBIOGRAM_PATH", yaml_path)
    try:
        hai.load_hai_antibiogram()
    finally:
        hai.load_hai_antibiogram.cache_clear()  # noqa: SLF001


def test_unknown_hai_type_raises(monkeypatch, tmp_path):
    with pytest.raises(ValueError, match="unknown hai_type"):
        _run_with_yaml(monkeypatch, tmp_path, """
hai_antibiogram:
  CLABSI:
    "3092008":
      vancomycin: [1.0, 0.0, 0.0]
""")


def test_organism_not_in_hai_organisms_raises(monkeypatch, tmp_path):
    with pytest.raises(ValueError, match="not in hai_organisms"):
        _run_with_yaml(monkeypatch, tmp_path, """
hai_antibiogram:
  clabsi:
    "99999999":
      vancomycin: [1.0, 0.0, 0.0]
""")


def test_unknown_antibiotic_key_raises(monkeypatch, tmp_path):
    with pytest.raises(ValueError, match="unknown antibiotic key"):
        _run_with_yaml(monkeypatch, tmp_path, """
hai_antibiogram:
  clabsi:
    "3092008":
      lol_unknown_drug: [1.0, 0.0, 0.0]
""")


def test_triple_must_be_length_3(monkeypatch, tmp_path):
    with pytest.raises(ValueError, match="length 3"):
        _run_with_yaml(monkeypatch, tmp_path, """
hai_antibiogram:
  clabsi:
    "3092008":
      vancomycin: [1.0, 0.0]
""")


def test_triple_must_sum_to_one(monkeypatch, tmp_path):
    with pytest.raises(ValueError, match="must sum to ~1.0"):
        _run_with_yaml(monkeypatch, tmp_path, """
hai_antibiogram:
  clabsi:
    "3092008":
      vancomycin: [0.5, 0.0, 0.0]
""")
