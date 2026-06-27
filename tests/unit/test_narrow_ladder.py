"""PR3b-3: narrow_ladder.yaml loader + 3-way cross-validation tests."""
from __future__ import annotations

import pytest

from clinosim.modules.antibiotic import ANTIBIOTIC_DRUGS
from clinosim.modules.antibiotic.engine import load_narrow_ladder
from clinosim.modules.hai import HAI_TYPES, load_hai_antibiogram


@pytest.mark.unit
def test_load_narrow_ladder_succeeds() -> None:
    """Happy path: load returns three-level nested dict."""
    ladder = load_narrow_ladder()
    assert set(ladder.keys()) == set(HAI_TYPES)
    for hai_type, organism_map in ladder.items():
        assert isinstance(organism_map, dict)
        for organism_snomed, drug_list in organism_map.items():
            assert isinstance(drug_list, list)
            assert all(isinstance(d, str) for d in drug_list)
            assert len(drug_list) >= 1


@pytest.mark.unit
def test_narrow_ladder_three_way_validation_holds() -> None:
    """Every (hai_type, organism, drug_key) entry must exist in antibiogram +
    ANTIBIOTIC_DRUGS + HAI_TYPES (the load-time invariant)."""
    ladder = load_narrow_ladder()
    antibiogram = load_hai_antibiogram()
    valid_drugs = set(ANTIBIOTIC_DRUGS.keys())
    for hai_type, organism_map in ladder.items():
        assert hai_type in HAI_TYPES
        for organism_snomed, drug_list in organism_map.items():
            assert organism_snomed in antibiogram[hai_type], (
                f"ladder organism {hai_type}/{organism_snomed} not in antibiogram"
            )
            antibiogram_drugs = set(antibiogram[hai_type][organism_snomed].keys())
            for drug_key in drug_list:
                assert drug_key in valid_drugs, (
                    f"ladder drug {drug_key!r} not in ANTIBIOTIC_DRUGS"
                )
                assert drug_key in antibiogram_drugs, (
                    f"ladder entry {hai_type}/{organism_snomed}/{drug_key} "
                    f"not in antibiogram"
                )


@pytest.mark.unit
def test_unknown_hai_type_raises(tmp_path, monkeypatch) -> None:
    """Inject a bad YAML with uppercase hai_type → ValueError at load time."""
    bad_yaml = tmp_path / "bad.yaml"
    bad_yaml.write_text(
        'narrow_ladder:\n  CLABSI:\n    "3092008": [cefazolin]\n',
        encoding="utf-8",
    )
    from clinosim.modules.antibiotic import engine
    monkeypatch.setattr(engine, "_NARROW_LADDER_YAML", bad_yaml)
    load_narrow_ladder.cache_clear()
    with pytest.raises(ValueError, match="unknown hai_type"):
        load_narrow_ladder()
    load_narrow_ladder.cache_clear()


@pytest.mark.unit
def test_unknown_organism_raises(tmp_path, monkeypatch) -> None:
    """Inject ladder organism not in antibiogram for its hai_type → ValueError."""
    bad_yaml = tmp_path / "bad.yaml"
    bad_yaml.write_text(
        'narrow_ladder:\n  clabsi:\n    "9999999": [cefazolin]\n',
        encoding="utf-8",
    )
    from clinosim.modules.antibiotic import engine
    monkeypatch.setattr(engine, "_NARROW_LADDER_YAML", bad_yaml)
    load_narrow_ladder.cache_clear()
    with pytest.raises(ValueError, match="not in antibiogram"):
        load_narrow_ladder()
    load_narrow_ladder.cache_clear()


@pytest.mark.unit
def test_unknown_drug_raises(tmp_path, monkeypatch) -> None:
    """Inject ladder drug_key not in ANTIBIOTIC_DRUGS → ValueError."""
    bad_yaml = tmp_path / "bad.yaml"
    bad_yaml.write_text(
        'narrow_ladder:\n  clabsi:\n    "3092008": [nonexistent_drug]\n',
        encoding="utf-8",
    )
    from clinosim.modules.antibiotic import engine
    monkeypatch.setattr(engine, "_NARROW_LADDER_YAML", bad_yaml)
    load_narrow_ladder.cache_clear()
    with pytest.raises(ValueError, match="not in ANTIBIOTIC_DRUGS"):
        load_narrow_ladder()
    load_narrow_ladder.cache_clear()


@pytest.mark.unit
def test_empty_narrow_ladder_raises(tmp_path, monkeypatch) -> None:
    """Empty top-level mapping → silent no-op gate (adversarial-1 C-5)."""
    bad_yaml = tmp_path / "bad.yaml"
    bad_yaml.write_text("narrow_ladder: {}\n", encoding="utf-8")
    from clinosim.modules.antibiotic import engine
    monkeypatch.setattr(engine, "_NARROW_LADDER_YAML", bad_yaml)
    load_narrow_ladder.cache_clear()
    with pytest.raises(ValueError, match="empty narrow_ladder"):
        load_narrow_ladder()
    load_narrow_ladder.cache_clear()


@pytest.mark.unit
def test_empty_drug_list_raises(tmp_path, monkeypatch) -> None:
    """Empty drug list for an organism → silent no-op gate (adversarial-1 C-5)."""
    bad_yaml = tmp_path / "bad.yaml"
    bad_yaml.write_text(
        'narrow_ladder:\n  clabsi:\n    "3092008": []\n',
        encoding="utf-8",
    )
    from clinosim.modules.antibiotic import engine
    monkeypatch.setattr(engine, "_NARROW_LADDER_YAML", bad_yaml)
    load_narrow_ladder.cache_clear()
    with pytest.raises(ValueError, match="empty drug list"):
        load_narrow_ladder()
    load_narrow_ladder.cache_clear()


@pytest.mark.unit
def test_antibiogram_organism_must_have_ladder_entry(tmp_path, monkeypatch) -> None:
    """Reverse-coverage: every (hai_type, organism) in antibiogram must have a
    ladder entry. Missing entry = silent no-op narrow for that organism
    (adversarial-1 C-3 PR-90 class)."""
    # Construct a ladder missing clabsi/3092008 (S.aureus is in antibiogram)
    bad_yaml = tmp_path / "bad.yaml"
    bad_yaml.write_text(
        # All entries except clabsi/3092008 — the antibiogram has S.aureus there
        # so reverse-coverage MUST raise.
        'narrow_ladder:\n  clabsi:\n    "60875001": [cefazolin, vancomycin]\n'
        '    "112283007": [ceftriaxone]\n    "56415008": [ceftriaxone]\n'
        '    "52499004": [cefepime]\n'
        '  cauti:\n    "112283007": [ceftriaxone]\n    "56415008": [ceftriaxone]\n'
        '    "52499004": [cefepime]\n    "73457008": [ceftriaxone]\n'
        '  vap:\n    "3092008": [cefazolin]\n    "52499004": [cefepime]\n'
        '    "56415008": [ceftriaxone]\n    "112283007": [ceftriaxone]\n'
        '    "14385002": [cefepime]\n    "91288006": [cefepime]\n'
        '    "113697002": [trimethoprim_sulfamethoxazole]\n',
        encoding="utf-8",
    )
    from clinosim.modules.antibiotic import engine
    monkeypatch.setattr(engine, "_NARROW_LADDER_YAML", bad_yaml)
    load_narrow_ladder.cache_clear()
    with pytest.raises(ValueError, match="missing ladder entries"):
        load_narrow_ladder()
    load_narrow_ladder.cache_clear()


@pytest.mark.unit
def test_drug_not_in_antibiogram_for_organism_raises(tmp_path, monkeypatch) -> None:
    """Inject ladder drug that is in ANTIBIOTIC_DRUGS but absent from the
    antibiogram entry for this (hai_type, organism) → ValueError. This is
    the 3-way silent-no-op gate (CAUTI/E.coli has no piperacillin_tazobactam)."""
    bad_yaml = tmp_path / "bad.yaml"
    bad_yaml.write_text(
        'narrow_ladder:\n  cauti:\n    "112283007": [piperacillin_tazobactam]\n',
        encoding="utf-8",
    )
    from clinosim.modules.antibiotic import engine
    monkeypatch.setattr(engine, "_NARROW_LADDER_YAML", bad_yaml)
    load_narrow_ladder.cache_clear()
    with pytest.raises(ValueError, match="not in antibiogram"):
        load_narrow_ladder()
    load_narrow_ladder.cache_clear()
