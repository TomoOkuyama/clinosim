"""Unit tests for hai_empirical.yaml loader + import-time validation."""
import pytest

from clinosim.modules.antibiotic import ANTIBIOTIC_DRUGS
from clinosim.modules.antibiotic.engine import load_hai_empirical
from clinosim.modules.hai import HAI_TYPES


@pytest.mark.unit
def test_load_hai_empirical_returns_dict_keyed_by_hai_type():
    data = load_hai_empirical()
    assert set(data.keys()) == set(HAI_TYPES)


@pytest.mark.unit
def test_load_hai_empirical_clabsi_idsa_2009():
    data = load_hai_empirical()
    clabsi = data["clabsi"]
    assert clabsi["duration_days"] == 14
    drugs = {d["drug_key"]: d for d in clabsi["drugs"]}
    assert set(drugs.keys()) == {"vancomycin", "piperacillin_tazobactam"}
    assert drugs["vancomycin"]["dose"] == "1g"
    assert drugs["vancomycin"]["route"] == "IV"
    assert drugs["vancomycin"]["frequency"] == "q12h"
    assert drugs["piperacillin_tazobactam"]["dose"] == "3.375g"
    assert drugs["piperacillin_tazobactam"]["frequency"] == "q6h"


@pytest.mark.unit
def test_load_hai_empirical_cauti_idsa_2009():
    data = load_hai_empirical()
    cauti = data["cauti"]
    assert cauti["duration_days"] == 7
    assert len(cauti["drugs"]) == 1
    assert cauti["drugs"][0]["drug_key"] == "ceftriaxone"
    assert cauti["drugs"][0]["frequency"] == "q24h"
    assert cauti["drugs"][0]["dose"] == "1g"


@pytest.mark.unit
def test_load_hai_empirical_vap_idsa_2016():
    data = load_hai_empirical()
    vap = data["vap"]
    assert vap["duration_days"] == 7
    drug_keys = {d["drug_key"] for d in vap["drugs"]}
    assert drug_keys == {"vancomycin", "piperacillin_tazobactam"}


@pytest.mark.unit
def test_load_hai_empirical_all_drug_keys_canonical():
    data = load_hai_empirical()
    for hai_type, cfg in data.items():
        for drug in cfg["drugs"]:
            assert drug["drug_key"] in ANTIBIOTIC_DRUGS, (
                f"{hai_type}: {drug['drug_key']!r} not in canonical "
                f"ANTIBIOTIC_DRUGS {ANTIBIOTIC_DRUGS}"
            )


@pytest.mark.unit
def test_unknown_hai_key_raises_value_error(tmp_path, monkeypatch):
    """YAML with an HAI key not in HAI_TYPES must raise at load time."""
    bad_yaml = tmp_path / "bad.yaml"
    bad_yaml.write_text(
        "hai_empirical:\n"
        "  cauti:\n"
        "    duration_days: 7\n"
        "    drugs: [{drug_key: Ceftriaxone, dose: 1g, route: IV, frequency: q24h}]\n"
        "  bogus_hai:\n"
        "    duration_days: 7\n"
        "    drugs: [{drug_key: Ceftriaxone, dose: 1g, route: IV, frequency: q24h}]\n"
    )
    from clinosim.modules.antibiotic import engine
    engine.load_hai_empirical.cache_clear()
    monkeypatch.setattr(engine, "_HAI_EMPIRICAL_YAML", bad_yaml)
    with pytest.raises(ValueError, match="unknown hai_type"):
        engine.load_hai_empirical()
    engine.load_hai_empirical.cache_clear()


@pytest.mark.unit
def test_unknown_drug_key_raises_value_error(tmp_path, monkeypatch):
    """YAML with a drug_key not in ANTIBIOTIC_DRUGS must raise at load time."""
    bad_yaml = tmp_path / "bad.yaml"
    bad_yaml.write_text(
        "hai_empirical:\n"
        "  cauti:\n"
        "    duration_days: 7\n"
        "    drugs: [{drug_key: BogusAbx, dose: 1g, route: IV, frequency: q24h}]\n"
    )
    from clinosim.modules.antibiotic import engine
    engine.load_hai_empirical.cache_clear()
    monkeypatch.setattr(engine, "_HAI_EMPIRICAL_YAML", bad_yaml)
    with pytest.raises(ValueError, match="unknown drug_key"):
        engine.load_hai_empirical()
    engine.load_hai_empirical.cache_clear()
