import pytest

from clinosim.codes import get_system_uri, lookup

pytestmark = pytest.mark.unit


def test_loinc_codes():
    assert lookup("loinc", "72166-2", "en")
    assert lookup("loinc", "11331-6", "en")


@pytest.mark.parametrize("code", ["266919005", "8517006", "449868002",
                                  "105542008", "28127009", "86933000"])
def test_snomed_values(code):
    assert lookup("snomed-ct", code, "en") not in ("", code)


def test_alcohol_social_uses_active_concept():
    # 160573003 is the INACTIVE observable "Alcohol intake (observable entity)",
    # not a drinking-pattern finding — verified inactive via tx.fhir.org (SNOMED
    # CT International). The "social" tier must use active 28127009 Social drinker.
    from clinosim.modules.sdoh import load_social_history

    alcohol = load_social_history()["alcohol_use"]["values"]
    codes = {tier: entry["snomed"] for tier, entry in alcohol.items()}

    assert codes["social"] == "28127009"
    assert "160573003" not in codes.values()
    for code in codes.values():
        assert lookup("snomed-ct", code, "en") not in ("", code)


@pytest.mark.parametrize("code", ["independent", "support1", "support2",
                                  "care1", "care2", "care3", "care4", "care5"])
def test_care_level_codes(code):
    assert lookup("jp-care-level", code, "en")
    assert lookup("jp-care-level", code, "ja")


def test_care_level_system_uri():
    assert get_system_uri("jp-care-level").startswith("http")
