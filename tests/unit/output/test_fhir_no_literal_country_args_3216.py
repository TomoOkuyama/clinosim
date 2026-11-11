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

Issue #3219: it also fails on a parameter default that is a literal country,
and on any constant default of a ``country`` / ``country_code`` /
``country_key`` parameter
(``country: str = "US"`` or ``= ""``): a caller that forgets the country must
fail (spec §3.3: an unknown country raises, never falls back silently), not
get US structure. Issue #3221 extends the default rule to all of
``clinosim/``; the call-argument rule stays on ``fhir_r4/`` (other modules
still pass literal countries where the code is country-specific, e.g. the
``clinosim/countries/jp`` package).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from clinosim.country_profile import supported_countries

pytestmark = pytest.mark.unit

_SOURCE_ROOT = Path(__file__).resolve().parents[3] / "clinosim"
_FHIR_ROOT = _SOURCE_ROOT / "modules" / "output" / "fhir_r4"
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


_COUNTRY_PARAMETERS = {"country", "country_code", "country_key"}


def literal_country_defaults(source: str, literals: set[str]) -> list[tuple[int, str]]:
    """``(line, "function(parameter)")`` of each parameter whose default is a
    literal country, or a constant default of a country parameter."""
    found: list[tuple[int, str]] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        a = node.args
        positional = [*a.posonlyargs, *a.args]
        pairs = [
            *zip(positional[len(positional) - len(a.defaults) :], a.defaults),
            *((arg, d) for arg, d in zip(a.kwonlyargs, a.kw_defaults) if d is not None),
        ]
        for arg, default in pairs:
            if not isinstance(default, ast.Constant):
                continue
            literal = isinstance(default.value, str) and default.value in literals
            if literal or arg.arg in _COUNTRY_PARAMETERS:
                name = getattr(node, "name", "<lambda>")
                found.append((node.lineno, f"{name}({arg.arg})"))
    return found


def test_the_guard_finds_literal_country_defaults() -> None:
    src = (
        'def a(order, country: str = "US"): ...\n'
        'def b(resource, country: str = ""): ...\n'
        'def c(x, *, origin: str = "jp"): ...\n'
        "def d(order, country: str): ...\n"
        'def e(lang: str = "en"): ...\n'  # a language, not a country
    )
    assert literal_country_defaults(src, _country_literals()) == [
        (1, "a(country)"),
        (2, "b(country)"),
        (3, "c(origin)"),
    ]


def test_clinosim_declares_no_default_country() -> None:
    """Issue #3221: the default rule covers every module under ``clinosim/``
    (Issue #3219 started with ``fhir_r4/``)."""
    literals = _country_literals()
    offenders = {
        f"{path.relative_to(_SOURCE_ROOT)}:{line} {name}"
        for path in sorted(_SOURCE_ROOT.rglob("*.py"))
        for line, name in literal_country_defaults(path.read_text(encoding="utf-8"), literals)
    }
    assert not offenders, f"Make the country a required parameter (Issues #3219, #3221): {sorted(offenders)}"


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
