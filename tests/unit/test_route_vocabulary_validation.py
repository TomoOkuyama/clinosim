"""Import-time route-vocabulary validation guards (Issue #458).

Pre-fix: a YAML author could add `route: TRANSDERMAL` (or a typo like
`route: PPO`) to any disease / encounter / chronic-medications YAML and the
simulation would ship green. Runtime `_ROUTE_SNOMED.get(route)` returned
None and the FHIR builder silently emitted `{"text": VALUE}` with no
`coding` — the exact silent-no-op class CLAUDE.md documents under
"Import-time canonical-constants validation".

These tests pin three properties:
  1. Every current disease / encounter / chronic-medications YAML has route
     values that pass the validator (guards against regression when the
     recognized set is tightened by mistake).
  2. Unknown route values are rejected loudly, per loader (guards against
     the validator being removed or a walker regression).
  3. `KNOWN_ROUTE_VOCABULARY` is the union of the three source sets — no
     silent membership drift.
"""

from __future__ import annotations

import pytest

from clinosim.locale.loader import load_chronic_medications
from clinosim.modules.disease.protocol import (
    _iter_route_values as disease_iter_routes,
)
from clinosim.modules.disease.protocol import (
    load_all_disease_protocols,
)
from clinosim.modules.encounter.protocol import (
    _iter_route_values as encounter_iter_routes,
)
from clinosim.modules.encounter.protocol import (
    load_all_encounter_conditions,
)
from clinosim.modules.output.fhir_r4.reference_data import (
    _ROUTE_ALIASES,
    _ROUTE_SNOMED,
    _ROUTE_TEXT_ONLY_BY_DESIGN,
    KNOWN_ROUTE_VOCABULARY,
    validate_yaml_route_value,
)

pytestmark = pytest.mark.unit


def test_known_route_vocabulary_is_union_of_the_three_sources():
    """The exported vocabulary must equal canonical ∪ aliases ∪ by-design.
    A drift (e.g. `_ROUTE_ALIASES` extended without the vocabulary being
    rebuilt) would let unknown values sneak through the validator."""
    expected = set(_ROUTE_SNOMED.keys()) | set(_ROUTE_ALIASES.keys()) | set(_ROUTE_TEXT_ONLY_BY_DESIGN)
    assert set(KNOWN_ROUTE_VOCABULARY) == expected


def test_all_disease_yaml_route_values_are_recognized():
    """Import-time validation runs during `load_all_disease_protocols` —
    if that call succeeds, every route in every disease YAML is on
    KNOWN_ROUTE_VOCABULARY. This test double-guards by enumerating the
    values so a future regression that skips the validator (but keeps
    load_all_disease_protocols wired) is still caught."""
    protocols = load_all_disease_protocols()
    for disease_id in protocols:
        # protocols[] holds the DiseaseProtocol; we re-load the raw YAML via a
        # protocol-level walker over Pydantic .model_dump(). Simpler: read the
        # YAML file directly since the loader cached it.
        from clinosim.modules.disease.protocol import _REF_DIR

        with open(_REF_DIR / f"{disease_id}.yaml") as f:
            import yaml

            data = yaml.safe_load(f)
        for raw in disease_iter_routes(data):
            # A raise here would be a regression in the validator + the loader
            # (loader path already returned) — the tests catch either.
            validate_yaml_route_value(raw, source=f"disease {disease_id!r}")


def test_all_encounter_yaml_route_values_are_recognized():
    """Sibling of the disease test — same guard for encounter YAMLs."""
    conditions = load_all_encounter_conditions()
    for cid, data in conditions.items():
        for raw in encounter_iter_routes(data):
            validate_yaml_route_value(raw, source=f"encounter {cid!r}")


def test_chronic_medications_route_values_are_recognized():
    """Same guard for the chronic-medications YAML (single file)."""
    from clinosim.locale.loader import _iter_route_values as chronic_iter_routes

    data = load_chronic_medications()
    for raw in chronic_iter_routes(data):
        validate_yaml_route_value(raw, source="chronic_medications.yaml")


def test_unknown_route_value_raises():
    """Direct guard on the validator — an unknown token must fail loudly.
    Uses a value chosen to never plausibly become canonical."""
    with pytest.raises(ValueError, match="unknown route value"):
        validate_yaml_route_value("PPO_TYPO", source="test")


def test_validator_is_case_insensitive():
    """`.upper()` matches the runtime normalization in build_route_concept."""
    validate_yaml_route_value("po", source="test")  # canonical
    validate_yaml_route_value("neb", source="test")  # alias
    validate_yaml_route_value("procedural", source="test")  # by-design
    # sanity: unknown value still rejected regardless of case
    with pytest.raises(ValueError):
        validate_yaml_route_value("bogus", source="test")


def test_validator_accepts_by_design_text_only_values():
    """The by-design text-only set (PROCEDURAL / CATHETER / NASAL etc.)
    intentionally emits `text` without coding — they must not fail
    validation just because they lack a SNOMED code."""
    for value in _ROUTE_TEXT_ONLY_BY_DESIGN:
        validate_yaml_route_value(value, source="test")
