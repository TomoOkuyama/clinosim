"""CSV rows carry the same code and code system as the FHIR output (Issue #2303)."""

from __future__ import annotations

import pytest

from clinosim.modules.output import csv_adapter as csv

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(("country", "system"), [("US", "http://loinc.org")])
def test_lab_coding_matches_fhir_strategy(country: str, system: str) -> None:
    code, uri = csv._lab_coding({"lab_name": "CRP", "value": 5.0, "unit": "mg/L"}, country)
    assert code == "1988-5" and uri == system


def test_jp_lab_coding_is_jlac10_family() -> None:
    code, uri = csv._lab_coding({"lab_name": "WBC", "value": 6.0, "unit": "10*3/uL"}, "JP")
    assert code and uri and "loinc" not in uri


@pytest.mark.parametrize(("country", "fragment"), [("US", "rxnorm"), ("JP", "")])
def test_drug_coding_uses_the_fhir_resolver(country: str, fragment: str) -> None:
    code, uri = csv._drug_coding("Acetaminophen 500mg PO", "", country)
    assert code and uri and fragment in uri


def test_procedure_name_follows_country_language_and_system() -> None:
    # A SNOMED-coded procedure resolves through its own system, in the
    # country's language (387713003 is registered: "Surgical procedure" / 手術).
    proc = {"procedure_code": "387713003", "procedure_system_key": "snomed-ct", "procedure_type": "surgery"}
    assert csv._procedure_name_and_system(proc, "JP") == ("手術", "http://snomed.info/sct")
    assert csv._procedure_name_and_system(proc, "US") == ("Surgical procedure", "http://snomed.info/sct")
