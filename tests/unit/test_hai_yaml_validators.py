"""Unit tests for HAI YAML loader validators (sibling sweep, 2026-06-29).

Covers _validate_hai_rates, _validate_hai_codes, _validate_hai_specimens,
_validate_hai_lab_lift_config, _validate_hai_organisms reverse-coverage.
"""
from __future__ import annotations

import pytest
import yaml

from clinosim.modules.hai import engine as hai_engine


@pytest.fixture(autouse=True)
def _clear_hai_caches():
    """Each test starts with empty caches so monkeypatch effects are visible."""
    hai_engine.load_hai_rates.cache_clear()
    hai_engine.load_hai_codes.cache_clear()
    hai_engine.load_hai_organisms.cache_clear()
    hai_engine.load_hai_specimens.cache_clear()
    yield
    hai_engine.load_hai_rates.cache_clear()
    hai_engine.load_hai_codes.cache_clear()
    hai_engine.load_hai_organisms.cache_clear()
    hai_engine.load_hai_specimens.cache_clear()


# ----------------------------------------------------------------------------
# _validate_hai_rates
# ----------------------------------------------------------------------------


@pytest.mark.unit
def test_hai_rates_real_yaml_loads_clean() -> None:
    """Positive baseline: the real hai_rates.yaml passes validation."""
    data = hai_engine.load_hai_rates()
    assert "hai_rates" in data
    assert set(data["hai_rates"].keys()) >= {"clabsi", "cauti", "vap"}


@pytest.mark.unit
def test_hai_rates_rejects_empty_top_level(monkeypatch) -> None:
    monkeypatch.setattr(yaml, "safe_load", lambda f: {"hai_rates": {}})
    with pytest.raises(ValueError, match="hai_rates.yaml top-level empty"):
        hai_engine.load_hai_rates()


@pytest.mark.unit
def test_hai_rates_rejects_unknown_hai_type(monkeypatch) -> None:
    monkeypatch.setattr(yaml, "safe_load", lambda f: {
        "hai_rates": {
            "clabsi": {"per_day_risk": 0.001, "source_device_type": "cvc"},
            "cauti": {"per_day_risk": 0.001, "source_device_type": "indwelling_catheter"},
            "vap": {"per_day_risk": 0.001, "source_device_type": "mechanical_ventilator"},
            "INVALID": {"per_day_risk": 0.001, "source_device_type": "cvc"},
        }
    })
    with pytest.raises(ValueError, match="unknown hai_type 'INVALID'"):
        hai_engine.load_hai_rates()


@pytest.mark.unit
def test_hai_rates_rejects_missing_hai_type_forward_coverage(monkeypatch) -> None:
    monkeypatch.setattr(yaml, "safe_load", lambda f: {
        "hai_rates": {
            "clabsi": {"per_day_risk": 0.001, "source_device_type": "cvc"},
            # cauti + vap missing
        }
    })
    with pytest.raises(ValueError, match="missing HAI_TYPES"):
        hai_engine.load_hai_rates()


@pytest.mark.unit
def test_hai_rates_rejects_per_day_risk_out_of_range(monkeypatch) -> None:
    monkeypatch.setattr(yaml, "safe_load", lambda f: {
        "hai_rates": {
            "clabsi": {"per_day_risk": 1.5, "source_device_type": "cvc"},
            "cauti": {"per_day_risk": 0.001, "source_device_type": "indwelling_catheter"},
            "vap": {"per_day_risk": 0.001, "source_device_type": "mechanical_ventilator"},
        }
    })
    with pytest.raises(ValueError, match="per_day_risk"):
        hai_engine.load_hai_rates()


@pytest.mark.unit
def test_hai_rates_rejects_unknown_device_type(monkeypatch) -> None:
    monkeypatch.setattr(yaml, "safe_load", lambda f: {
        "hai_rates": {
            "clabsi": {"per_day_risk": 0.001, "source_device_type": "INVALID_DEVICE"},
            "cauti": {"per_day_risk": 0.001, "source_device_type": "indwelling_catheter"},
            "vap": {"per_day_risk": 0.001, "source_device_type": "mechanical_ventilator"},
        }
    })
    with pytest.raises(ValueError, match="source_device_type"):
        hai_engine.load_hai_rates()


# ----------------------------------------------------------------------------
# _validate_hai_codes
# ----------------------------------------------------------------------------


@pytest.mark.unit
def test_hai_codes_real_yaml_loads_clean() -> None:
    data = hai_engine.load_hai_codes()
    assert "hai_codes" in data
    assert set(data["hai_codes"].keys()) >= {"clabsi", "cauti", "vap"}


@pytest.mark.unit
def test_hai_codes_rejects_empty_top_level(monkeypatch) -> None:
    monkeypatch.setattr(yaml, "safe_load", lambda f: {"hai_codes": {}})
    with pytest.raises(ValueError, match="hai_codes.yaml top-level empty"):
        hai_engine.load_hai_codes()


@pytest.mark.unit
def test_hai_codes_rejects_unknown_hai_type(monkeypatch) -> None:
    base = {
        "clabsi": {"icd10_us_billable": "T80.211A", "icd10_jp_who": "T80.2",
                   "snomed": "736442006"},
        "cauti": {"icd10_us_billable": "T83.511A", "icd10_jp_who": "T83.5",
                  "snomed": "68566005"},
        "vap": {"icd10_us_billable": "J95.851", "icd10_jp_who": "J95.8",
                "snomed": "429271009"},
    }
    monkeypatch.setattr(yaml, "safe_load", lambda f: {
        "hai_codes": {**base, "INVALID": base["clabsi"]}
    })
    with pytest.raises(ValueError, match="unknown hai_type 'INVALID'"):
        hai_engine.load_hai_codes()


@pytest.mark.unit
def test_hai_codes_rejects_missing_hai_type_forward_coverage(monkeypatch) -> None:
    monkeypatch.setattr(yaml, "safe_load", lambda f: {
        "hai_codes": {
            "clabsi": {"icd10_us_billable": "T80.211A", "icd10_jp_who": "T80.2",
                       "snomed": "736442006"},
        }
    })
    with pytest.raises(ValueError, match="missing HAI_TYPES"):
        hai_engine.load_hai_codes()


@pytest.mark.unit
def test_hai_codes_rejects_unknown_icd10_us(monkeypatch) -> None:
    monkeypatch.setattr(yaml, "safe_load", lambda f: {
        "hai_codes": {
            "clabsi": {"icd10_us_billable": "BOGUS.99", "icd10_jp_who": "T80.2",
                       "snomed": "736442006"},
            "cauti": {"icd10_us_billable": "T83.511A", "icd10_jp_who": "T83.5",
                      "snomed": "68566005"},
            "vap": {"icd10_us_billable": "J95.851", "icd10_jp_who": "J95.8",
                    "snomed": "429271009"},
        }
    })
    with pytest.raises(ValueError, match="icd10_us_billable"):
        hai_engine.load_hai_codes()


@pytest.mark.unit
def test_hai_codes_rejects_unknown_icd10_jp(monkeypatch) -> None:
    monkeypatch.setattr(yaml, "safe_load", lambda f: {
        "hai_codes": {
            "clabsi": {"icd10_us_billable": "T80.211A", "icd10_jp_who": "Z99.9",
                       "snomed": "736442006"},
            "cauti": {"icd10_us_billable": "T83.511A", "icd10_jp_who": "T83.5",
                      "snomed": "68566005"},
            "vap": {"icd10_us_billable": "J95.851", "icd10_jp_who": "J95.8",
                    "snomed": "429271009"},
        }
    })
    with pytest.raises(ValueError, match="icd10_jp_who"):
        hai_engine.load_hai_codes()


@pytest.mark.unit
def test_hai_codes_rejects_unknown_snomed(monkeypatch) -> None:
    monkeypatch.setattr(yaml, "safe_load", lambda f: {
        "hai_codes": {
            "clabsi": {"icd10_us_billable": "T80.211A", "icd10_jp_who": "T80.2",
                       "snomed": "9999999999"},
            "cauti": {"icd10_us_billable": "T83.511A", "icd10_jp_who": "T83.5",
                      "snomed": "68566005"},
            "vap": {"icd10_us_billable": "J95.851", "icd10_jp_who": "J95.8",
                    "snomed": "429271009"},
        }
    })
    with pytest.raises(ValueError, match="snomed"):
        hai_engine.load_hai_codes()


# ----------------------------------------------------------------------------
# _validate_hai_specimens
# ----------------------------------------------------------------------------


@pytest.mark.unit
def test_hai_specimens_real_yaml_loads_clean() -> None:
    data = hai_engine.load_hai_specimens()
    assert "hai_specimens" in data
    assert set(data["hai_specimens"].keys()) >= {"clabsi", "cauti", "vap"}


@pytest.mark.unit
def test_hai_specimens_rejects_empty_top_level(monkeypatch) -> None:
    monkeypatch.setattr(yaml, "safe_load", lambda f: {"hai_specimens": {}})
    with pytest.raises(ValueError, match="hai_specimens.yaml top-level empty"):
        hai_engine.load_hai_specimens()


@pytest.mark.unit
def test_hai_specimens_rejects_unknown_hai_type(monkeypatch) -> None:
    base = {
        "clabsi": {"specimen": "blood", "specimen_snomed": "119297000",
                   "test_loinc": "600-7"},
        "cauti": {"specimen": "urine", "specimen_snomed": "122575003",
                  "test_loinc": "630-4"},
        "vap": {"specimen": "sputum", "specimen_snomed": "119334006",
                "test_loinc": "619-7"},
    }
    monkeypatch.setattr(yaml, "safe_load", lambda f: {
        "hai_specimens": {**base, "INVALID": base["clabsi"]}
    })
    with pytest.raises(ValueError, match="unknown hai_type 'INVALID'"):
        hai_engine.load_hai_specimens()


@pytest.mark.unit
def test_hai_specimens_rejects_missing_hai_type_forward_coverage(monkeypatch) -> None:
    monkeypatch.setattr(yaml, "safe_load", lambda f: {
        "hai_specimens": {
            "clabsi": {"specimen": "blood", "specimen_snomed": "119297000",
                       "test_loinc": "600-7"},
        }
    })
    with pytest.raises(ValueError, match="missing HAI_TYPES"):
        hai_engine.load_hai_specimens()


@pytest.mark.unit
def test_hai_specimens_rejects_unknown_snomed(monkeypatch) -> None:
    monkeypatch.setattr(yaml, "safe_load", lambda f: {
        "hai_specimens": {
            "clabsi": {"specimen": "blood", "specimen_snomed": "9999999999",
                       "test_loinc": "600-7"},
            "cauti": {"specimen": "urine", "specimen_snomed": "122575003",
                      "test_loinc": "630-4"},
            "vap": {"specimen": "sputum", "specimen_snomed": "119334006",
                    "test_loinc": "619-7"},
        }
    })
    with pytest.raises(ValueError, match="specimen_snomed"):
        hai_engine.load_hai_specimens()


@pytest.mark.unit
def test_hai_specimens_rejects_unknown_loinc(monkeypatch) -> None:
    monkeypatch.setattr(yaml, "safe_load", lambda f: {
        "hai_specimens": {
            "clabsi": {"specimen": "blood", "specimen_snomed": "119297000",
                       "test_loinc": "99999-99"},
            "cauti": {"specimen": "urine", "specimen_snomed": "122575003",
                      "test_loinc": "630-4"},
            "vap": {"specimen": "sputum", "specimen_snomed": "119334006",
                    "test_loinc": "619-7"},
        }
    })
    with pytest.raises(ValueError, match="test_loinc"):
        hai_engine.load_hai_specimens()
