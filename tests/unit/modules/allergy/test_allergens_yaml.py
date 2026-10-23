"""YAML validator tests for allergens.yaml.

META #1805 Phase A: ``allergen_display_en`` / ``allergen_display_ja`` and
``manifestation_display_en`` / ``manifestation_display_ja`` fields were
retired. Displays live in ``clinosim/codes/data/snomed-ct.yaml`` and
resolve at emit time via ``code_lookup("snomed-ct", code, lang)``.
"""

from __future__ import annotations

import pytest

from clinosim.codes import lookup as code_lookup
from clinosim.modules.allergy.engine import _validate_allergens, load_allergens


def test_allergens_yaml_loads():
    a = load_allergens()
    assert isinstance(a, dict)


def test_each_entry_has_required_fields():
    """Post-#1805 Phase A: display fields retired; the structural
    fields (allergen_code pointer + prevalence + criticality +
    common_reactions) remain required."""
    a = load_allergens()
    for category, entries in a.items():
        for e in entries:
            assert "allergen_code" in e
            assert "prevalence" in e
            assert "criticality" in e
            assert "common_reactions" in e


def test_cached_lru():
    """@lru_cache(maxsize=1) — 2 calls same object."""
    assert load_allergens() is load_allergens()


def test_all_reaction_entries_have_required_fields():
    """Reaction entries carry manifestation_snomed + severity; the
    retired display fields no longer required."""
    a = load_allergens()
    for category, entries in a.items():
        for e in entries:
            for r in e.get("common_reactions", []):
                assert "manifestation_snomed" in r, f"{category}: missing manifestation_snomed"
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
            assert 0 <= adult <= 1, f"{category}[{e['allergen_code']}]: prevalence.adult={adult} out of range"


# ----------------------------------------------------------------------------
# META #1805 Phase A: display SoT invariant — every allergen_code and every
# manifestation_snomed resolves against the snomed-ct.yaml authority with
# EN+JA displays. This is the one-and-only source of truth; retiring the
# per-row display_en/display_ja fields means callers must not fall back to
# yaml-local strings.
# ----------------------------------------------------------------------------


def test_every_allergen_code_has_snomed_authority_display_en_ja():
    a = load_allergens()
    for category, entries in a.items():
        for e in entries:
            code = e["allergen_code"]
            en = code_lookup("snomed-ct", code, "en")
            ja = code_lookup("snomed-ct", code, "ja")
            assert en and en != code, f"{category}[{code}] missing EN display in authority"
            assert ja and ja != code, f"{category}[{code}] missing JA display in authority"


def test_every_manifestation_snomed_has_authority_display_en_ja():
    a = load_allergens()
    for category, entries in a.items():
        for e in entries:
            for r in e.get("common_reactions", []):
                code = r["manifestation_snomed"]
                en = code_lookup("snomed-ct", code, "en")
                ja = code_lookup("snomed-ct", code, "ja")
                assert en and en != code, f"{category}: manifestation {code} missing EN display"
                assert ja and ja != code, f"{category}: manifestation {code} missing JA display"


# ----------------------------------------------------------------------------
# Validator still fail-loud on unregistered authority codes
# ----------------------------------------------------------------------------


def test_validate_allergens_raises_on_unregistered_allergen_code():
    data = {
        "allergens": {
            "medication": [
                {
                    "allergen_code": "99999999999",  # not in snomed-ct.yaml
                    "prevalence": {"adult": 0.1},
                    "criticality": "low",
                    "common_reactions": [
                        {
                            "manifestation_snomed": "247472004",
                            "severity": "mild",
                        }
                    ],
                }
            ],
            "food": [],
            "environment": [],
        }
    }
    with pytest.raises(ValueError, match="99999999999"):
        _validate_allergens(data)


def test_validate_allergens_raises_on_unregistered_manifestation_snomed():
    data = {
        "allergens": {
            "medication": [
                {
                    "allergen_code": "764146007",  # Penicillin, registered
                    "prevalence": {"adult": 0.1},
                    "criticality": "low",
                    "common_reactions": [
                        {
                            "manifestation_snomed": "99999999999",  # not registered
                            "severity": "mild",
                        }
                    ],
                }
            ],
            "food": [],
            "environment": [],
        }
    }
    with pytest.raises(ValueError, match="99999999999"):
        _validate_allergens(data)
