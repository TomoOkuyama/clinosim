"""Emitter LOINC codes come from codes/data/loinc-maps.yaml (Issue #2392)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import clinosim
from clinosim.codes.loinc import loinc_display, loinc_for, loinc_map
from clinosim.datafiles import load_data_yaml

pytestmark = pytest.mark.unit

_ROOT = Path(clinosim.__file__).parent
_KINDS = sorted(load_data_yaml(_ROOT / "codes/data/loinc-maps.yaml"))


@pytest.mark.parametrize("kind", _KINDS)
def test_every_mapped_code_is_registered(kind: str) -> None:
    for key, code in loinc_map(kind).items():
        assert loinc_display(code, "en"), (kind, key, code)


def test_apgar_minutes() -> None:
    assert loinc_display(loinc_for("apgar", "1"), "en") == "1 minute Apgar Score"
    assert loinc_display(loinc_for("apgar", "5"), "en") == "5 minute Apgar Score"


def test_unknown_kind_and_key_raise() -> None:
    with pytest.raises(KeyError):
        loinc_map("no_such_kind")
    with pytest.raises(KeyError):
        loinc_for("apgar", "10")


@pytest.mark.parametrize(
    "rel",
    [
        "modules/output/fhir_r4/labs/anthropometrics.py",
        "modules/output/fhir_r4/labs/blood_type.py",
        "modules/output/fhir_r4/labs/microbiology.py",
        "modules/output/fhir_r4/encounters/care_level.py",
        "modules/output/fhir_r4/documents/composition.py",
        "modules/newborn/fhir_emit.py",
        "modules/newborn/engine.py",
    ],
)
def test_no_loinc_literal_in_emitter(rel: str) -> None:
    src = (_ROOT / rel).read_text(encoding="utf-8")
    code_lines = [line.split("#", 1)[0] for line in src.splitlines()]
    hits = [line for line in code_lines if re.search(r"""["']\d{3,5}-\d["']""", line)]
    assert not hits, hits
