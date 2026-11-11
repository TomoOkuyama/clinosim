"""Guard: FHIR output passes the record's country, never a literal one
(Issue #3216).

``docs/design-guides/country-profile-spec.md`` §1: the common flow asks the
country profile; a builder that hands ``"JP"`` / ``"US"`` to a helper
(``hospital_institution_code("JP")``, ``pick_external_hospital(...,
country="JP")``) decides the country itself, which the shrink-only ratchet
(Issue #3137) does not see because it is a call argument, not a comparison.
This test walks every Python file under ``clinosim/modules/output/fhir_r4/``
and fails on a call argument (positional or keyword) that is a supported
country code or a legacy country spelling.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from clinosim.country_profile import supported_countries

pytestmark = pytest.mark.unit

_FHIR_ROOT = Path(__file__).resolve().parents[3] / "clinosim" / "modules" / "output" / "fhir_r4"
# Legacy spellings the profile loader maps to a country code.
_LEGACY = {"japan", "usa", "united states"}


def _country_literals() -> set[str]:
    codes = set(supported_countries())
    return {c for code in codes for c in (code, code.lower())} | _LEGACY


def literal_country_arguments(source: str, literals: set[str]) -> list[tuple[int, str]]:
    """``(line, call)`` of each call that passes a literal country code."""
    found: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        values = [*node.args, *(k.value for k in node.keywords)]
        if any(isinstance(v, ast.Constant) and isinstance(v.value, str) and v.value in literals for v in values):
            func = node.func
            name = func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else "?"
            found.append((node.lineno, name))
    return found


def test_the_guard_finds_literal_country_arguments() -> None:
    src = (
        'a = hospital_institution_code("JP")\n'
        'b = pick_external_hospital(pid, eid, country="jp")\n'
        "c = hospital_institution_code(country)\n"
        'd = lang_for("ja")\n'  # a language, not a country
    )
    assert literal_country_arguments(src, _country_literals()) == [
        (1, "hospital_institution_code"),
        (2, "pick_external_hospital"),
    ]


def test_fhir_output_passes_no_literal_country() -> None:
    literals = _country_literals()
    offenders = {
        f"{path.relative_to(_FHIR_ROOT)}:{line} {name}"
        for path in sorted(_FHIR_ROOT.rglob("*.py"))
        for line, name in literal_country_arguments(path.read_text(encoding="utf-8"), literals)
    }
    assert not offenders, (
        "Pass the record's country (ctx.country / the country argument) instead of a literal; "
        f"values that differ by country come from the country profile and locale YAML: {sorted(offenders)}"
    )
