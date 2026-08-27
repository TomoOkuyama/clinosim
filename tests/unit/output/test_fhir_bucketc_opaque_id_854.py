"""Issue #854 Bucket C: opaque id + identifier round-trip for the four
patient-scoped stand-alone resources (rows 14-17 of the plan).

Post-#854 shapes (fixed length):
- ``Immunization.id``          = ``imm-<12hex>``     (16 chars)
- ``FamilyMemberHistory.id``   = ``fmh-<12hex>``     (16 chars)
- ``Coverage.id``              = ``cov-<12hex>``     (16 chars)
- ``AllergyIntolerance.id``    = ``allergy-<12hex>`` (20 chars)

All four are stand-alone in the FHIR reference graph (no downstream
cross-ref cascade). Each carries its pre-#854 structural key on
``.identifier[]`` under its per-kind
``urn:clinosim:identifier:{kind}-key`` system.

Patient.id (row 18) is deferred — it is the external identity used by
downstream consumers (iris4h-ai, HAPI validator, integration tests) and
migration requires a maintainer design call.
"""

from __future__ import annotations

import re

import pytest

from clinosim.modules.output.fhir_r4.conditions.allergy_intolerance import (
    ALLERGY_KEY_SYSTEM,
    _resolve_allergy_id,
)
from clinosim.modules.output.fhir_r4.demographics.family_history import (
    FAMILY_MEMBER_HISTORY_KEY_SYSTEM,
    _resolve_family_member_history_id,
)
from clinosim.modules.output.fhir_r4.demographics.patient import (
    COVERAGE_KEY_SYSTEM,
    _resolve_coverage_id,
)
from clinosim.modules.output.fhir_r4.procedures.immunization import (
    IMMUNIZATION_KEY_SYSTEM,
    _resolve_immunization_id,
)

pytestmark = pytest.mark.unit


# === Resolver contracts ===


@pytest.mark.parametrize(
    "resolver, prefix, length",
    [
        (_resolve_immunization_id, "imm-", 16),
        (_resolve_family_member_history_id, "fmh-", 16),
        (_resolve_coverage_id, "cov-", 16),
        (_resolve_allergy_id, "allergy-", 20),
    ],
)
def test_resolver_shape_and_length(resolver, prefix, length) -> None:
    key = "POP-000001-0"
    result = resolver(key)
    assert result.startswith(prefix), f"{result!r} missing prefix {prefix!r}"
    assert re.match(rf"^{re.escape(prefix)}[0-9a-f]{{12}}$", result), f"non-opaque: {result!r}"
    assert len(result) == length


@pytest.mark.parametrize(
    "resolver",
    [_resolve_immunization_id, _resolve_family_member_history_id, _resolve_coverage_id, _resolve_allergy_id],
)
def test_resolver_deterministic(resolver) -> None:
    key = "POP-000001-0"
    assert resolver(key) == resolver(key)


@pytest.mark.parametrize(
    "resolver",
    [_resolve_immunization_id, _resolve_family_member_history_id, _resolve_coverage_id, _resolve_allergy_id],
)
def test_resolver_distinct_inputs_distinct_outputs(resolver) -> None:
    assert resolver("POP-000001-0") != resolver("POP-000001-1")


# === KEY_SYSTEM URIs ===


def test_immunization_key_system_uri() -> None:
    assert IMMUNIZATION_KEY_SYSTEM == "urn:clinosim:identifier:immunization-key"


def test_family_member_history_key_system_uri() -> None:
    assert FAMILY_MEMBER_HISTORY_KEY_SYSTEM == "urn:clinosim:identifier:family-member-history-key"


def test_coverage_key_system_uri() -> None:
    assert COVERAGE_KEY_SYSTEM == "urn:clinosim:identifier:coverage-key"


def test_allergy_intolerance_key_system_uri() -> None:
    assert ALLERGY_KEY_SYSTEM == "urn:clinosim:identifier:allergy-intolerance-key"
