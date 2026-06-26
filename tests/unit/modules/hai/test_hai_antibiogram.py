import pytest

from clinosim.modules.hai import HAI_TYPES, load_hai_antibiogram


@pytest.mark.unit
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


@pytest.mark.unit
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


@pytest.mark.unit
def test_unknown_hai_type_raises(monkeypatch, tmp_path):
    with pytest.raises(ValueError, match="unknown hai_type"):
        _run_with_yaml(monkeypatch, tmp_path, """
hai_antibiogram:
  CLABSI:
    "3092008":
      vancomycin: [1.0, 0.0, 0.0]
""")


@pytest.mark.unit
def test_organism_not_in_hai_organisms_raises(monkeypatch, tmp_path):
    with pytest.raises(ValueError, match="not in hai_organisms"):
        _run_with_yaml(monkeypatch, tmp_path, """
hai_antibiogram:
  clabsi:
    "99999999":
      vancomycin: [1.0, 0.0, 0.0]
""")


@pytest.mark.unit
def test_unknown_antibiotic_key_raises(monkeypatch, tmp_path):
    with pytest.raises(ValueError, match="unknown antibiotic key"):
        _run_with_yaml(monkeypatch, tmp_path, """
hai_antibiogram:
  clabsi:
    "3092008":
      lol_unknown_drug: [1.0, 0.0, 0.0]
""")


@pytest.mark.unit
def test_triple_must_be_length_3(monkeypatch, tmp_path):
    with pytest.raises(ValueError, match="length 3"):
        _run_with_yaml(monkeypatch, tmp_path, """
hai_antibiogram:
  clabsi:
    "3092008":
      vancomycin: [1.0, 0.0]
""")


@pytest.mark.unit
def test_triple_must_sum_to_one(monkeypatch, tmp_path):
    with pytest.raises(ValueError, match="must sum to ~1.0"):
        _run_with_yaml(monkeypatch, tmp_path, """
hai_antibiogram:
  clabsi:
    "3092008":
      vancomycin: [0.5, 0.0, 0.0]
""")


@pytest.mark.unit
def test_clabsi_saureus_antibiogram_key_order_is_canonical():
    """PR3b-2 Adv #6 F2: YAML insertion order is load-bearing for AD-16
    RNG determinism. Re-sorting the YAML would silently shift downstream
    cohort outcomes. Pin the key order for the organisms used in pinned tests.
    """
    abg = load_hai_antibiogram()
    assert list(abg["clabsi"]["3092008"].keys()) == [
        "vancomycin", "cefazolin", "ceftriaxone", "cefepime",
        "ciprofloxacin", "trimethoprim_sulfamethoxazole",
    ]


@pytest.mark.unit
def test_cauti_ecoli_antibiotic_key_order_is_canonical():
    """PR3b-2 Adv #6 F2: CAUTI/E.coli (112283007) key order is load-bearing."""
    abg = load_hai_antibiogram()
    assert list(abg["cauti"]["112283007"].keys()) == [
        "ceftriaxone", "cefepime", "meropenem",
        "ciprofloxacin", "trimethoprim_sulfamethoxazole",
    ]


@pytest.mark.unit
def test_vap_saureus_antibiogram_key_order_is_canonical():
    """PR3b-2 Adv #6 F2: VAP/S.aureus (3092008) key order is load-bearing."""
    abg = load_hai_antibiogram()
    assert list(abg["vap"]["3092008"].keys()) == [
        "vancomycin", "cefazolin", "ceftriaxone", "cefepime",
        "ciprofloxacin", "trimethoprim_sulfamethoxazole",
    ]
