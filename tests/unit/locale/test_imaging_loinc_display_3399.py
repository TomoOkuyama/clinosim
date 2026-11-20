"""Imaging exam names resolve to the target language (Issue #3399): a
structured imaging order stores the English LOINC long name, and
``imaging_exam_display`` maps it (or the LOINC code) to the registry display."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from clinosim.codes import display
from clinosim.locale.loader import imaging_exam_display

_ROOT = Path(__file__).resolve().parents[3] / "clinosim"
_ASCII_WORD = re.compile(r"[A-Za-z]{3,}")
_ALLOWED = re.compile(r"CT|MRI|MR|X-ray|FAST|PET|SPECT|DSA|ERCP|MRCP|MRA|CTA|DXA|PA|DVT")


def _procedure_loincs() -> list[str]:
    raw = yaml.safe_load((_ROOT / "modules/imaging/reference_data/body_sites.yaml").read_text(encoding="utf-8"))
    return sorted(
        {str(p["loinc"]) for s in raw["body_sites"].values() for p in (s.get("procedure_codes") or {}).values()}
    )


def _imaging_test_keys() -> set[str]:
    keys: set[str] = set()

    def walk(o: object) -> None:
        if isinstance(o, dict):
            for k, v in o.items():
                if k == "imaging" and isinstance(v, list):
                    for e in v:
                        if isinstance(e, dict) and "test" in e:
                            keys.add(str(e["test"]))
                        elif isinstance(e, str):
                            keys.add(e)
                else:
                    walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    for f in _ROOT.glob("**/*.yaml"):
        if "/locale/" in str(f):
            continue
        try:
            walk(yaml.safe_load(f.read_text(encoding="utf-8")))
        except yaml.YAMLError:
            continue
    return keys


def _leaks(text: str) -> bool:
    return bool(_ASCII_WORD.search(_ALLOWED.sub("", text)))


@pytest.mark.parametrize("code", _procedure_loincs())
def test_loinc_name_and_code_resolve_to_japanese(code):
    en = display("loinc", code, "en")
    ja = display("loinc", code, "ja")
    assert ja and ja != en
    assert imaging_exam_display(en, "ja") == ja
    assert imaging_exam_display(code, "ja") == ja


def test_known_leaks_from_issue():
    assert imaging_exam_display("US Abdomen", "ja") == "腹部超音波検査"


def test_every_protocol_imaging_key_resolves_to_japanese():
    bad = [
        (k, imaging_exam_display(k, "ja"))
        for k in sorted(_imaging_test_keys())
        if _leaks(imaging_exam_display(k, "ja"))
    ]
    assert not bad, bad
