"""YAML validator tests for allergens.yaml."""

from __future__ import annotations

import pytest

from clinosim.modules.allergy.engine import _validate_allergens, load_allergens


def test_allergens_yaml_loads():
    a = load_allergens()
    assert isinstance(a, dict)


def test_each_entry_has_required_fields():
    a = load_allergens()
    for category, entries in a.items():
        for e in entries:
            assert "allergen_code" in e
            assert "allergen_display_en" in e
            assert "allergen_display_ja" in e
            assert "prevalence" in e


def test_cached_lru():
    """@lru_cache(maxsize=1) — 2 calls same object."""
    assert load_allergens() is load_allergens()


def test_all_reaction_entries_have_required_fields():
    a = load_allergens()
    for category, entries in a.items():
        for e in entries:
            for r in e.get("common_reactions", []):
                assert "manifestation_snomed" in r, f"{category}: missing manifestation_snomed"
                assert "manifestation_display_en" in r, (
                    f"{category}: missing manifestation_display_en"
                )
                assert "severity" in r, f"{category}: missing severity"
                assert r["severity"] in ("mild", "moderate", "severe"), (
                    f"{category}: invalid severity {r['severity']!r}"
                )


def test_prevalence_adult_in_range():
    a = load_allergens()
    for category, entries in a.items():
        for e in entries:
            prev = e.get("prevalence", {})
            adult = prev.get("adult", -1)
            assert 0 <= adult <= 1, (
                f"{category}[{e['allergen_display_en']}]: prevalence.adult={adult} out of range"
            )


def test_validate_allergens_raises_on_unregistered_allergen_code():
    data = {
        "allergens": {
            "medication": [{
                "allergen_code": "99999999999",  # not in snomed-ct.yaml
                "allergen_display_en": "Fake Drug",
                "allergen_display_ja": "偽薬",
                "prevalence": {"adult": 0.1},
                "criticality": "low",
                "common_reactions": [{
                    "manifestation_snomed": "247472004",
                    "manifestation_display_en": "Rash",
                    "manifestation_display_ja": "発疹",
                    "severity": "mild",
                }],
            }],
            "food": [],
            "environment": [],
        }
    }
    with pytest.raises(ValueError, match="99999999999"):
        _validate_allergens(data)


def test_validate_allergens_raises_on_unregistered_manifestation_snomed():
    data = {
        "allergens": {
            "medication": [{
                "allergen_code": "387207008",  # Penicillin, registered
                "allergen_display_en": "Penicillin",
                "allergen_display_ja": "ペニシリン",
                "prevalence": {"adult": 0.1},
                "criticality": "low",
                "common_reactions": [{
                    "manifestation_snomed": "99999999999",  # not registered
                    "manifestation_display_en": "Fake",
                    "manifestation_display_ja": "偽",
                    "severity": "mild",
                }],
            }],
            "food": [],
            "environment": [],
        }
    }
    with pytest.raises(ValueError, match="99999999999"):
        _validate_allergens(data)
