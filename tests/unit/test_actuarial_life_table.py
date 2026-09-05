"""Actuarial life table data-file loader tests (Issue #1114 C11g-1).

Validates the shape + realism of ``locale/shared/actuarial_life_table.yaml``.
No consumer wired yet — this test IS the loader's only current caller,
which is intentional: it catches YAML edits before C11g-2 lands.
"""

from __future__ import annotations

import pytest

from clinosim.locale.loader import load_actuarial_life_table

_AGE_BANDS = [0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80, 85, 90, 95]


@pytest.fixture(scope="module")
def actuarial() -> dict:
    return load_actuarial_life_table()


def test_top_level_shape(actuarial: dict) -> None:
    assert "annual_mortality_qx" in actuarial
    assert "provenance" in actuarial
    qx = actuarial["annual_mortality_qx"]
    assert set(qx.keys()) == {"us", "jp"}
    for country in ("us", "jp"):
        assert set(qx[country].keys()) == {"male", "female"}


@pytest.mark.parametrize("country", ["us", "jp"])
@pytest.mark.parametrize("sex", ["male", "female"])
def test_all_age_bands_present(actuarial: dict, country: str, sex: str) -> None:
    band_data = actuarial["annual_mortality_qx"][country][sex]
    assert set(band_data.keys()) == set(_AGE_BANDS)
    for age, qx in band_data.items():
        assert 0.0 < float(qx) < 1.0, f"{country} {sex} age {age}: qx {qx} out of (0, 1)"


@pytest.mark.parametrize("country", ["us", "jp"])
@pytest.mark.parametrize("sex", ["male", "female"])
def test_mortality_monotonic_from_late_adulthood(actuarial: dict, country: str, sex: str) -> None:
    """qx should rise monotonically (non-decreasing) from age 20 onward.
    Infant mortality creates the only legitimate dip below age 10; the
    young-adult plateau (e.g. JP male 20-24 and 25-29 both round to
    0.000492) is allowed via ``>=``. Catches transcription errors that
    would silently swap age bands."""
    band_data = actuarial["annual_mortality_qx"][country][sex]
    late_bands = [b for b in _AGE_BANDS if b >= 20]
    values = [float(band_data[b]) for b in late_bands]
    for a, b, va, vb in zip(late_bands, late_bands[1:], values, values[1:]):
        assert vb >= va, f"{country} {sex}: qx({b}) {vb} < qx({a}) {va}"


@pytest.mark.parametrize(
    "country, sex, age, expected_low, expected_high",
    [
        # Sanity anchors: infant mortality (0-4 band, dominated by <1 yr)
        ("us", "male", 0, 0.0010, 0.0020),
        ("us", "female", 0, 0.0008, 0.0016),
        ("jp", "male", 0, 0.0003, 0.0007),
        ("jp", "female", 0, 0.0003, 0.0006),
        # Elderly (85-89 band): rising fast, JP < US at older ages
        ("us", "male", 85, 0.11, 0.16),
        ("us", "female", 85, 0.08, 0.13),
        ("jp", "male", 85, 0.08, 0.13),
        ("jp", "female", 85, 0.05, 0.08),
    ],
)
def test_anchor_values_in_realistic_range(
    actuarial: dict, country: str, sex: str, age: int, expected_low: float, expected_high: float
) -> None:
    v = float(actuarial["annual_mortality_qx"][country][sex][age])
    assert expected_low <= v <= expected_high, f"{country} {sex} age {age}: {v} outside {expected_low}-{expected_high}"


@pytest.mark.parametrize("country", ["us", "jp"])
def test_female_mortality_lower_than_male_in_working_ages(actuarial: dict, country: str) -> None:
    """Female mortality is universally lower than male across working
    ages (20-64) in both countries — a well-established epidemiological
    fact. Catches accidental sex-column swaps."""
    for age in (20, 30, 40, 50, 60):
        m = float(actuarial["annual_mortality_qx"][country]["male"][age])
        f = float(actuarial["annual_mortality_qx"][country]["female"][age])
        assert f < m, f"{country} age {age}: female qx {f} not < male qx {m}"


def test_provenance_metadata(actuarial: dict) -> None:
    prov = actuarial["provenance"]
    for country in ("us", "jp"):
        assert country in prov
        entry = prov[country]
        assert entry["reference_year"] == 2020
        assert entry["document"].startswith("https://")
        assert isinstance(entry["tables_consulted"], list)
        assert len(entry["tables_consulted"]) == 2
