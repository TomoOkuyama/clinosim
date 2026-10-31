"""Issue #2261: JP lab CodeSystems are registered and JLAC10 resolves through
one accessor."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from clinosim.codes import get_system_uri, jlac10_display, jp_clins_lab_system, system_key_for_uri
from clinosim.locale.loader import lab_code, load_code_mapping
from clinosim.modules.output.fhir_r4.labs import coding_package
from clinosim.modules.output.fhir_r4.labs.coding_strategy import _uncoded_analyte_ja_display

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2] / "clinosim"
_KINDS = (
    "corelabo_jlac10",
    "corelabo_jlac11",
    "infectionlabo_jlac10",
    "infectionlabo_jlac11",
    "uncoded",
    "localcode",
    "jlac10_17digits",
    "specimen_material",
)


@pytest.mark.parametrize("kind", _KINDS)
def test_every_jp_lab_system_is_registered(kind: str) -> None:
    uri = jp_clins_lab_system(kind)
    assert system_key_for_uri(uri), uri


def test_coding_package_reads_the_registry() -> None:
    defined = coding_package.jp_clins_defined_system_uris()
    assert defined == {jp_clins_lab_system(k) for k in _KINDS if k != "specimen_material"}


def test_every_mapped_jp_lab_resolves_and_has_a_jlac10_display() -> None:
    for lab_name, code in load_code_mapping("lab", "JP").items():
        assert lab_code(lab_name, "JP") == ("jlac10", code)
        assert jlac10_display(code, "ja"), (lab_name, code)


def test_uncoded_analyte_displays_come_from_data() -> None:
    displays = _uncoded_analyte_ja_display()
    assert displays["pH"] == "動脈血pH"
    assert all(displays.values())


def test_no_jp_lab_uri_or_oid_literal_outside_codes() -> None:
    literals = {jp_clins_lab_system(k) for k in _KINDS} | {get_system_uri("jlac10")}
    offenders = []
    for path in sorted(_ROOT.rglob("*.py")):
        rel = path.relative_to(_ROOT).as_posix()
        if rel.startswith("codes/") or rel == "audit/axes/jp_language.py":  # prefix list of URI families
            continue
        text = path.read_text(encoding="utf-8")
        offenders += [f"{rel}: {u}" for u in literals if re.search(rf'"{re.escape(u)}"', text)]
    assert not offenders, offenders
