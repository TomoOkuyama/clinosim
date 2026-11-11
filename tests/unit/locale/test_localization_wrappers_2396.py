"""Localization wrappers have no selection logic of their own (Issue #2396)."""

from __future__ import annotations

from pathlib import Path

import pytest

import clinosim
from clinosim.codes.procedures import procedure_type_display
from clinosim.locale.loader import load_llm_prompt_labels, narrative_label, prompt_label
from clinosim.modules.document.narrative._localization import _localize_proc_type
from clinosim.modules.document.narrative._replacement_localization import localize_oxygen_device, localize_token
from clinosim.modules.newborn import fhir_emit

pytestmark = pytest.mark.unit

_ROOT = Path(clinosim.__file__).parent


def test_one_label_function() -> None:
    assert fhir_emit._label is narrative_label
    defs = [p.name for p in _ROOT.rglob("*.py") if "\ndef _label(" in p.read_text(encoding="utf-8")]
    assert not defs, defs


def test_prompt_label_order() -> None:
    entry = load_llm_prompt_labels()["oxygen_device"]
    key = next(iter(entry))
    assert prompt_label("oxygen_device", key.upper(), "JP") == entry[key]["ja"]
    assert prompt_label("oxygen_device", key, "fr") == entry[key].get("en", "")
    assert prompt_label("oxygen_device", "no_such_device", "ja", fallback="x") == "x"


def test_oxygen_device_has_no_language_branch() -> None:
    key = next(iter(load_llm_prompt_labels()["oxygen_device"]))
    en = load_llm_prompt_labels()["oxygen_device"][key].get("en")
    assert localize_oxygen_device(key, "en") == (en or key)
    assert localize_oxygen_device(key, "ja") == localize_token(key, "oxygen_device", "ja")


@pytest.mark.parametrize("lang", ["ja", "JA", "JP"])
def test_procedure_type_follows_the_shared_order(lang: str) -> None:
    assert _localize_proc_type("urinary_catheter", lang) == procedure_type_display("urinary_catheter", "ja")
