import pytest

from clinosim.codes import get_system_uri, lookup

pytestmark = pytest.mark.unit


def test_loinc_codes():
    assert lookup("loinc", "72166-2", "en")
    assert lookup("loinc", "11331-6", "en")


@pytest.mark.parametrize("code", ["266919005", "8517006", "449868002",
                                  "105542008", "160573003", "86933000"])
def test_snomed_values(code):
    assert lookup("snomed-ct", code, "en") not in ("", code)


@pytest.mark.parametrize("code", ["independent", "support1", "support2",
                                  "care1", "care2", "care3", "care4", "care5"])
def test_care_level_codes(code):
    assert lookup("jp-care-level", code, "en")
    assert lookup("jp-care-level", code, "ja")


def test_care_level_system_uri():
    assert get_system_uri("jp-care-level").startswith("http")
