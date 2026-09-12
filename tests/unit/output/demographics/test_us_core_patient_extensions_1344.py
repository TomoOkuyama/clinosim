"""Issue #1344: US Core Patient extensions (race / ethnicity / birthsex).

Verifies the extension builders return well-formed FHIR structures for
every OMB category the sim samples and are absent on JP output.
"""

from __future__ import annotations

import pytest

from clinosim.modules.output.fhir_r4.demographics.patient import (
    _build_patient,
    _build_us_core_birthsex_extension,
    _build_us_core_ethnicity_extension,
    _build_us_core_race_extension,
)


class TestRaceExtension:
    @pytest.mark.parametrize(
        "slug,expected_code,expected_display",
        [
            ("white", "2106-3", "White"),
            ("black", "2054-5", "Black or African American"),
            ("asian", "2028-9", "Asian"),
            ("native_american", "1002-5", "American Indian or Alaska Native"),
            ("pacific_islander", "2076-8", "Native Hawaiian or Other Pacific Islander"),
            ("other", "2131-1", "Other Race"),
        ],
    )
    def test_known_slug_emits_omb_extension(self, slug: str, expected_code: str, expected_display: str) -> None:
        ext = _build_us_core_race_extension(slug)
        assert ext is not None
        assert ext["url"] == "http://hl7.org/fhir/us/core/StructureDefinition/us-core-race"
        omb = next(sub for sub in ext["extension"] if sub["url"] == "ombCategory")
        assert omb["valueCoding"]["system"] == "urn:oid:2.16.840.1.113883.6.238"
        assert omb["valueCoding"]["code"] == expected_code
        assert omb["valueCoding"]["display"] == expected_display
        text = next(sub for sub in ext["extension"] if sub["url"] == "text")
        assert text["valueString"] == expected_display

    def test_unknown_slug_returns_none(self) -> None:
        assert _build_us_core_race_extension("multiracial") is None

    def test_empty_slug_returns_none(self) -> None:
        assert _build_us_core_race_extension("") is None


class TestEthnicityExtension:
    @pytest.mark.parametrize(
        "slug,expected_code,expected_display",
        [
            ("hispanic", "2135-2", "Hispanic or Latino"),
            ("not_hispanic", "2186-5", "Not Hispanic or Latino"),
        ],
    )
    def test_known_slug_emits_omb_extension(self, slug: str, expected_code: str, expected_display: str) -> None:
        ext = _build_us_core_ethnicity_extension(slug)
        assert ext is not None
        assert ext["url"] == "http://hl7.org/fhir/us/core/StructureDefinition/us-core-ethnicity"
        omb = next(sub for sub in ext["extension"] if sub["url"] == "ombCategory")
        assert omb["valueCoding"]["code"] == expected_code

    def test_empty_slug_returns_none(self) -> None:
        assert _build_us_core_ethnicity_extension("") is None


class TestBirthsexExtension:
    @pytest.mark.parametrize("sex,expected", [("M", "M"), ("F", "F"), ("m", "M"), ("f", "F")])
    def test_male_female_emit_valuecode(self, sex: str, expected: str) -> None:
        ext = _build_us_core_birthsex_extension(sex)
        assert ext is not None
        assert ext["url"] == "http://hl7.org/fhir/us/core/StructureDefinition/us-core-birthsex"
        assert ext["valueCode"] == expected

    def test_unknown_sex_returns_none(self) -> None:
        assert _build_us_core_birthsex_extension("") is None
        assert _build_us_core_birthsex_extension("other") is None


class TestPatientBuilderWiring:
    """End-to-end: _build_patient emits the extensions on US, omits on JP."""

    def _base_patient(self, race: str = "white", ethnicity: str = "not_hispanic", sex: str = "F") -> dict:
        return {
            "patient_id": "POP-000001",
            "name": {"family_name": "Doe", "given_name": "Jane"},
            "sex": sex,
            "date_of_birth": "1970-01-01",
            "race": race,
            "ethnicity": ethnicity,
        }

    def test_us_patient_has_all_three_extensions(self) -> None:
        result = _build_patient(self._base_patient(), country="US")
        exts = result.get("extension") or []
        urls = {e["url"].rsplit("/", 1)[-1] for e in exts}
        assert "us-core-race" in urls
        assert "us-core-ethnicity" in urls
        assert "us-core-birthsex" in urls

    def test_jp_patient_has_none_of_the_us_core_extensions(self) -> None:
        result = _build_patient(self._base_patient(), country="JP")
        exts = result.get("extension") or []
        urls = {e["url"].rsplit("/", 1)[-1] for e in exts}
        assert "us-core-race" not in urls
        assert "us-core-ethnicity" not in urls
        assert "us-core-birthsex" not in urls

    def test_us_patient_with_empty_race_only_emits_birthsex(self) -> None:
        # Newborn / pediatric records where race sampler has not yet fired
        # still get birthsex (from `sex`) but no race / ethnicity.
        result = _build_patient(self._base_patient(race="", ethnicity=""), country="US")
        exts = result.get("extension") or []
        urls = {e["url"].rsplit("/", 1)[-1] for e in exts}
        assert "us-core-race" not in urls
        assert "us-core-ethnicity" not in urls
        assert "us-core-birthsex" in urls

    def test_us_patient_with_unknown_race_slug_omits_ext(self) -> None:
        # Fabricating an OMB code from an unmapped slug would be worse than
        # omitting per feedback_empty_vs_wrong_assertion — verify silent skip.
        result = _build_patient(self._base_patient(race="klingon"), country="US")
        exts = result.get("extension") or []
        urls = {e["url"].rsplit("/", 1)[-1] for e in exts}
        assert "us-core-race" not in urls
