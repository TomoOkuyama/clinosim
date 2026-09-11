"""Regression guard for the OPH (ophthalmic) route SNOMED coding on
MedicationAdministration/MedicationRequest (#1265).

The MAR/MR builder routes through `build_route_concept`, which looks
the raw route up in `_ROUTE_SNOMED`. `OPH` (used by the newborn
erythromycin ophthalmic prophylaxis, #1252 N7 US) was missing from
the table, so `.dosage.route` shipped as `{"text": "OPH"}` with no
`coding` for every US baby.

SNOMED CT 54485002 "Ophthalmic route" — verified 2026-09-11 via
tx.fhir.org `$lookup` (module=core, active, "Ophthalmic route"
registered as SNOMED Synonym; FSN is "Ophthalmic route (qualifier
value)").
"""

from __future__ import annotations

import pytest

from clinosim.modules.output.fhir_r4.lib.common import build_route_concept
from clinosim.modules.output.fhir_r4.lib.localization import _ROUTE_JA
from clinosim.modules.output.fhir_r4.lib.reference_data import _ROUTE_SNOMED

pytestmark = pytest.mark.unit


def test_oph_present_in_route_snomed_table() -> None:
    entry = _ROUTE_SNOMED.get("OPH")
    assert entry is not None, "OPH must be registered in _ROUTE_SNOMED"
    assert entry["code"] == "54485002"
    assert entry["display"] == "Ophthalmic route"


def test_oph_has_jp_translation() -> None:
    """`_validate_route_maps` invariant: every _ROUTE_SNOMED key needs a JA."""
    assert _ROUTE_JA.get("OPH") == "点眼"


def test_build_route_concept_us_oph_returns_snomed_coding() -> None:
    concept = build_route_concept("OPH", "US")
    assert concept is not None
    codings = concept.get("coding") or []
    assert codings, f"OPH must resolve to SNOMED coding on US emit; got {concept!r}"
    assert codings[0]["code"] == "54485002"
    assert codings[0]["display"] == "Ophthalmic route"
    assert codings[0]["system"].endswith("snomed.info/sct")
    assert concept.get("text") == "OPH"  # US keeps author wording


def test_build_route_concept_jp_oph_returns_snomed_coding_and_ja_text() -> None:
    """JP path is symmetric — even though JP does not administer
    ophthalmic prophylaxis in the newborn workup, any other JP scenario
    that authors OPH must emit the same SNOMED + JP-localized text.
    """
    concept = build_route_concept("OPH", "JP")
    assert concept is not None
    codings = concept.get("coding") or []
    assert codings and codings[0]["code"] == "54485002"
    assert concept.get("text") == "点眼"


def test_build_route_concept_lowercase_oph_upper_cases() -> None:
    """Author lower-case still resolves — case is normalized inside the helper."""
    concept = build_route_concept("oph", "US")
    assert concept is not None
    assert (concept.get("coding") or [{}])[0].get("code") == "54485002"
