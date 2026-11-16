"""Complication display names (Issue #3300).

A complication reaches the narrative as its internal token: a disease YAML
``complications[].name`` (daily loop), a ``cascade`` / ``parent_complication``
reference, or a disease id merged into an active stay
(``in_hospital_new_disease``). Each must have an English and a Japanese name
in ``locale/shared/narrative_complications.yaml`` so a JP note never shows
the English slug (code-mapping spec §6.2, §6.4: the humanised fallback is
allowed only because this test covers every emitted slug).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from clinosim.locale.loader import load_narrative_complications
from clinosim.modules.document.narrative._localization import _localize_complication

_DISEASE_DIR = Path(__file__).resolve().parents[3] / "clinosim" / "modules" / "disease" / "reference_data"


def _emitted_complication_keys() -> set[str]:
    keys: set[str] = set()
    for path in sorted(_DISEASE_DIR.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        keys.add(path.stem)  # a disease merged into an active stay
        for entry in data.get("complications") or []:
            if not isinstance(entry, dict):
                continue
            for name in [entry.get("name"), entry.get("parent_complication"), *(entry.get("cascade") or [])]:
                if name:
                    keys.add("_".join(str(name).strip().lower().split()))
    return keys


_KEYS = sorted(_emitted_complication_keys())


def test_keys_found() -> None:
    assert "thrombus_extension" in _KEYS
    assert "intubation_required" in _KEYS


@pytest.mark.parametrize("key", _KEYS)
def test_every_emitted_complication_has_en_and_ja(key: str) -> None:
    entry = load_narrative_complications().get(key)
    assert isinstance(entry, dict), f"{key}: no entry in narrative_complications.yaml"
    assert str(entry.get("en") or "").strip(), f"{key}: no English name"
    ja = str(entry.get("ja") or "").strip()
    assert ja, f"{key}: no Japanese name"
    # A Japanese name is not the English slug or its humanised form.
    assert not re.fullmatch(r"[a-z0-9_ ]+", ja), f"{key}: Japanese name {ja!r} is a slug"


def test_jp_progress_examples() -> None:
    assert _localize_complication("thrombus_extension", "ja") == "血栓進展"
    assert _localize_complication("bacterial superinfection", "ja") == "二次性細菌性肺炎"


def test_intubation_required_names_the_condition() -> None:
    # 「気管挿管管理を合併」 names a treatment, not a complication.
    ja = _localize_complication("intubation_required", "ja")
    assert "管理" not in ja and "呼吸不全" in ja
    assert _localize_complication("intubation_required", "en") == "respiratory failure requiring intubation"


def test_other_language_falls_back_to_english_name() -> None:
    assert _localize_complication("thrombus_extension", "fr") == "thrombus extension"
    assert _localize_complication("bacterial_superinfection", "fr") == "secondary bacterial pneumonia"
