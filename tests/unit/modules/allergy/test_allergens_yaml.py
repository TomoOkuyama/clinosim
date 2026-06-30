"""YAML validator tests for allergens.yaml."""

from __future__ import annotations

from clinosim.modules.allergy.engine import load_allergens


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
