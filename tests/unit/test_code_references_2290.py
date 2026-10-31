"""Issue #2290: one chronic-prefix code helper and YAML key, named SNOMED
concepts, and one cancer concept group."""

from __future__ import annotations

import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from clinosim.codes import display
from clinosim.codes import snomed_concepts as sc
from clinosim.codes.valuesets import code_by_chronic_prefix, concept_group
from clinosim.locale.loader import load_specialty_routing
from clinosim.modules.encounter.protocol import load_encounter_condition
from clinosim.simulator.emergency import ed_diagnosis_code
from clinosim.simulator.outpatient_dept import _specialty_for_visit
from clinosim.types.patient import ChronicCondition

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2] / "clinosim"


def test_code_by_chronic_prefix_reads_any_chronic_shape() -> None:
    mapping = {"F33": "F33.2"}
    assert (
        code_by_chronic_prefix(mapping, SimpleNamespace(chronic_conditions=[ChronicCondition(code="F33.1")])) == "F33.2"
    )
    assert code_by_chronic_prefix(mapping, SimpleNamespace(chronic_conditions=["F33"])) == "F33.2"
    assert code_by_chronic_prefix(mapping, SimpleNamespace(chronic_conditions=["F32.9"])) is None
    assert code_by_chronic_prefix(None, SimpleNamespace(chronic_conditions=["F33"])) is None


def test_ed_protocols_use_the_shared_key() -> None:
    data = load_encounter_condition("suicidal_ideation_depression")
    assert data.get("by_chronic_prefix")
    recurrent = SimpleNamespace(chronic_conditions=[ChronicCondition(code="F33.1")])
    assert ed_diagnosis_code(data, recurrent) == data["by_chronic_prefix"]["F33"]


def test_no_bare_snomed_literal_in_comparisons() -> None:
    literals = {sc.SURGICAL_PROCEDURE, sc.PROCEDURE_PARTIALLY_SUCCESSFUL, sc.PROCEDURE_UNSUCCESSFUL}
    literals |= {sc.FINDING_NORMAL, sc.FINDING_ABNORMAL}
    offenders = []
    for path in sorted(_ROOT.rglob("*.py")):
        rel = path.relative_to(_ROOT).as_posix()
        if rel.startswith("codes/"):
            continue
        for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            code_part = line.split("#", 1)[0]
            if any(re.search(rf'"{c}"', code_part) for c in literals):
                offenders.append(f"{rel}:{n}")
    assert not offenders, offenders


def test_named_concepts_are_registered() -> None:
    for name in ("SURGICAL_PROCEDURE", "PROCEDURE_PARTIALLY_SUCCESSFUL", "PROCEDURE_UNSUCCESSFUL"):
        assert display("snomed-ct", getattr(sc, name), "en")
    assert display("snomed-ct", sc.FINDING_NORMAL, "en") == "Normal"
    assert display("snomed-ct", sc.FINDING_ABNORMAL, "en") == "Abnormal"


@pytest.mark.parametrize("code", ["C15", "C18.9", "C34.1", "C50.9", "C61", "C71.9", "C90.0", "D05.1", "I10"])
def test_outpatient_and_specialty_routing_agree_on_cancer(code: str) -> None:
    oncology_route = next(r for r in load_specialty_routing() if r.get("specialty") == "oncology")
    routed = concept_group(oncology_route["requires_concept_group"]).contains(code)
    assert (_specialty_for_visit("chronic_followup", code) == "oncology") is routed
