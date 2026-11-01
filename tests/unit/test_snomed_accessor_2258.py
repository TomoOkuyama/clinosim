"""SNOMED CT codes and displays come from snomed-ct.yaml through one accessor (Issue #2258)."""

from __future__ import annotations

from pathlib import Path

import pytest

from clinosim.codes.snomed import snomed_display, snomed_for, snomed_map
from clinosim.modules.output.fhir_r4.lib.reference_data import _ROUTE_SNOMED, _SEVERITY_SNOMED

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("kind", ["route", "severity"])
def test_every_mapped_code_is_registered_with_en_and_ja(kind: str) -> None:
    for key, code in snomed_map(kind).items():
        assert snomed_display(code, "en"), (kind, key, code)
        assert snomed_display(code, "ja") != snomed_display(code, "en"), (kind, key, code)


def test_emitter_tables_are_derived_from_the_registry() -> None:
    for table, kind in ((_ROUTE_SNOMED, "route"), (_SEVERITY_SNOMED, "severity")):
        assert {k: v["code"] for k, v in table.items()} == snomed_map(kind)
        assert all(v["display"] == snomed_display(v["code"], "en") for v in table.values())


def test_snomed_for() -> None:
    assert snomed_for("route", "IM") == "78421000"
    assert snomed_for("severity", "moderate") == "6736007"
    assert snomed_for("route", "NASAL") is None
    with pytest.raises(KeyError):
        snomed_for("unknown-kind", "x")


def test_care_team_roles_use_registered_codes() -> None:
    src = (_ROOT / "clinosim/modules/output/fhir_r4/encounters/care_team.py").read_text(encoding="utf-8")
    assert "309362007" not in src  # not a SNOMED CT concept; 309360001 is the rehabilitation physician
    assert snomed_display("309360001", "en") == "Rehabilitation physician"


@pytest.mark.parametrize(
    "path",
    [
        "labs/diagnostic_report.py",
        "labs/microbiology.py",
        "procedures/immunization.py",
        "encounters/care_team.py",
    ],
)
def test_migrated_emitters_hold_no_snomed_uri_literal(path: str) -> None:
    src = (_ROOT / "clinosim/modules/output/fhir_r4" / path).read_text(encoding="utf-8")
    assert "http://snomed.info/sct" not in src
