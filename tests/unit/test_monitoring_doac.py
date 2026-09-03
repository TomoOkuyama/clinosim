"""B5 (#1070): DOAC → eGFR monitoring mapping unit tests."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

_MAPPING_YAML = (
    Path(__file__).resolve().parents[2]
    / "clinosim"
    / "modules"
    / "monitoring"
    / "reference_data"
    / "medication_monitoring.yaml"
)


@pytest.fixture(scope="module")
def mappings() -> dict:
    with _MAPPING_YAML.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)["mappings"]


@pytest.mark.parametrize("doac", ["Apixaban", "Rivaroxaban", "Dabigatran", "Edoxaban"])
def test_doac_has_egfr_monitoring_entry(mappings: dict, doac: str) -> None:
    entry = mappings.get(doac)
    assert entry is not None, f"{doac} missing from medication_monitoring.yaml"
    monitoring = entry.get("monitoring", [])
    egfr_entries = [m for m in monitoring if m.get("lab") == "eGFR"]
    assert len(egfr_entries) == 1, f"{doac} must have exactly one eGFR monitoring row"
    assert egfr_entries[0]["loinc"] == "77147-7"


@pytest.mark.parametrize("doac", ["Apixaban", "Rivaroxaban", "Dabigatran", "Edoxaban"])
def test_doac_has_jp_display(mappings: dict, doac: str) -> None:
    assert mappings[doac].get("drug_ja"), f"{doac} missing drug_ja"


@pytest.mark.parametrize(
    "doac, alias",
    [
        ("Apixaban", "アピキサバン"),
        ("Apixaban", "eliquis"),
        ("Rivaroxaban", "リバーロキサバン"),
        ("Rivaroxaban", "xarelto"),
        ("Dabigatran", "ダビガトラン"),
        ("Edoxaban", "エドキサバン"),
        ("Edoxaban", "リクシアナ"),
    ],
)
def test_doac_aliases_present(mappings: dict, doac: str, alias: str) -> None:
    assert alias in mappings[doac]["aliases"]


@pytest.mark.parametrize("doac", ["Apixaban", "Rivaroxaban", "Dabigatran", "Edoxaban"])
def test_doac_rationale_bilingual(mappings: dict, doac: str) -> None:
    entry = mappings[doac]["monitoring"][0]
    assert entry.get("rationale"), f"{doac} missing EN rationale"
    assert entry.get("rationale_ja"), f"{doac} missing JA rationale"
    # Sanity check: JP rationale should contain kana / kanji (drug names or 腎)
    assert any(0x3040 <= ord(c) <= 0x9FFF for c in entry["rationale_ja"])


@pytest.mark.parametrize(
    "doac, drug_string",
    [
        ("Apixaban", "Apixaban 5mg PO BID"),
        ("Apixaban", "アピキサバン 5mg 1日2回"),
        ("Rivaroxaban", "Rivaroxaban 20mg PO daily"),
        ("Rivaroxaban", "リバーロキサバン 15mg 1日1回"),
        ("Dabigatran", "Dabigatran 150mg PO BID"),
        ("Dabigatran", "プラザキサ 110mg 1日2回"),
        ("Edoxaban", "Edoxaban 60mg PO daily"),
        ("Edoxaban", "リクシアナ 30mg 1日1回"),
    ],
)
def test_match_drugs_picks_up_doac_prescriptions(mappings: dict, doac: str, drug_string: str) -> None:
    """match_drugs resolves DOAC drug strings with dose/route suffix +
    JP brand-name variants."""
    from clinosim.modules.monitoring.mapping import match_drugs

    class _Med:
        drug_name = drug_string

    result = match_drugs([_Med()], mappings)
    assert doac in result, f"substring resolver did not identify {doac} from {drug_string!r}"
