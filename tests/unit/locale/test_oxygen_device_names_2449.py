"""Oxygen devices are named in both languages, never shown as their slug
(Issue #2449)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

import clinosim
from clinosim.locale.i18n import t
from clinosim.modules.document.narrative._replacement_localization import localize_oxygen_device

pytestmark = pytest.mark.unit

_TABLE = Path(clinosim.__file__).parent / "locale/shared/llm_prompt_labels.yaml"


def test_every_device_has_english_and_japanese() -> None:
    devices = yaml.safe_load(_TABLE.read_text(encoding="utf-8"))["oxygen_device"]
    assert all(entry.get("en") and entry.get("ja") for entry in devices.values()), devices


def test_english_shift_note_names_the_device() -> None:
    device = localize_oxygen_device("nasal_cannula", "en")
    assert t("nursing_shift.o2_device_with_flow", "en", device=device, flow="3.2") == "nasal cannula 3.2 L/min"
    assert localize_oxygen_device("nasal_cannula", "ja") == "鼻カニューラ"
