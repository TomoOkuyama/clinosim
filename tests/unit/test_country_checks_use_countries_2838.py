"""Country decisions go through ``clinosim.countries`` (Issue #2838).

Hand-written comparisons (``country == "JP"``, ``.lower() == "us"``,
``in ("jp", "japan")``) each normalise the input differently, so an alias
accepted in one place was rejected in another. ``is_jp`` / ``is_us`` /
``country_code`` / ``country_slot`` are the one normalisation; ``is_jp``
also accepts the legacy locale key ``"japan"`` the simulator carries.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from clinosim.countries import country_code, country_slot, is_jp, is_us

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[2] / "clinosim"
_PATTERN = re.compile(r'(?:==|!=)\s*"(?:JP|US|jp|us|japan)"|in \("jp", "japan"\)')
# Comparisons that are not country normalisation.
_ALLOWED = {
    "countries/__init__.py",  # the canonical helpers
    "modules/imaging/engine.py",  # modality "US" = ultrasound
    "modules/identity/registry.py",  # internal provider key after is_jp / is_us
    "eval/axes/us_core_compliance.py",  # compares a detected-country result
    "eval/axes/structural.py",
    "eval/axes/jp_core_compliance.py",
    "eval/axes/locale.py",
    "eval/axes/jp_clins_lab_compliance.py",
}


def _code_lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if not line.lstrip().startswith("#") and "``" not in line]


def test_no_hand_written_country_comparison() -> None:
    offenders = []
    for path in _ROOT.rglob("*.py"):
        rel = path.relative_to(_ROOT).as_posix()
        if rel in _ALLOWED:
            continue
        for line in _code_lines(path.read_text(encoding="utf-8")):
            if _PATTERN.search(line):
                offenders.append(f"{rel}: {line.strip()}")
    assert not offenders, "use clinosim.countries (is_jp / is_us / country_code / country_slot):\n" + "\n".join(
        offenders
    )


@pytest.mark.parametrize("value", ["JP", "jp", " Jp ", "japan", "Japan"])
def test_japan_spellings(value: str) -> None:
    assert is_jp(value)
    assert country_code(value) == "JP"
    assert country_slot(value) == "jp"
    assert country_slot(value, scheme="legacy_japan") == "japan"


@pytest.mark.parametrize("value", ["US", "us", "", "XX"])
def test_non_japan_values(value: str) -> None:
    assert not is_jp(value)


@pytest.mark.parametrize("value", ["US", "us"])
def test_us_values(value: str) -> None:
    assert country_code(value) == "US"


@pytest.mark.parametrize("value", ["", "XX"])
def test_a_country_without_a_profile_has_no_code(value: str) -> None:
    # Issue #3143: it raises instead of becoming "US".
    with pytest.raises(KeyError):
        country_code(value)


def test_is_us_is_exact() -> None:
    assert is_us("us") and is_us("US") and not is_us("japan")
