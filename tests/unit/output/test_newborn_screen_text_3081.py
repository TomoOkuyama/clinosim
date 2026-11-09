"""Newborn screening Procedures are named in the output language (Issue #3081).

``code.text`` was the humanised classifier key ("Hearing screen AABR") in both
countries. It is the procedure catalog's name in the output language; the
SNOMED CT coding keeps its English display (code-mapping spec §5.3).
"""

from __future__ import annotations

import re

import pytest

from clinosim.codes import display, get_system_uri
from clinosim.modules.output.fhir_r4.procedures.procedures import _build_procedure

pytestmark = pytest.mark.unit

_CJK = re.compile(r"[぀-ヿ㐀-鿿]")
_SCREENS = {
    "hearing_screen_aabr": ("413083006", "新生児聴覚スクリーニング（AABR）", "Newborn hearing screening (AABR)"),
    "metabolic_screen_tandem_ms": (
        "428447008",
        "新生児マススクリーニング（タンデムマス法）",
        "Newborn metabolic screening (tandem mass spectrometry)",
    ),
}


def _screen(proc_type: str, country: str) -> dict:
    code = _SCREENS[proc_type][0]
    proc = {
        "procedure_id": f"PROC-B-{proc_type}",
        "patient_id": "POP-1-BABY",
        "encounter_id": "ENC-B",
        "procedure_type": proc_type,
        "procedure_code": code,
        "procedure_system_key": "snomed-ct",
        "category_code": "103693007",
        "start_datetime": "2026-06-01T11:00:00",
        "end_datetime": "2026-06-01T11:15:00",
    }
    return _build_procedure(proc, "POP-1-BABY", 0, country)


@pytest.mark.parametrize("proc_type", sorted(_SCREENS))
def test_jp_newborn_screen_text_is_japanese_and_snomed_display_english(proc_type: str) -> None:
    code, ja, _ = _SCREENS[proc_type]
    res = _screen(proc_type, "JP")
    assert res["code"]["text"] == ja
    (coding,) = [c for c in res["code"]["coding"] if c["code"] == code]
    assert coding["system"] == get_system_uri("snomed-ct")
    assert coding["display"] == display("snomed-ct", code, "en")
    assert not _CJK.search(coding["display"])


@pytest.mark.parametrize("proc_type", sorted(_SCREENS))
def test_us_newborn_screen_text_is_clinical_english(proc_type: str) -> None:
    code, _, en = _SCREENS[proc_type]
    res = _screen(proc_type, "US")
    assert res["code"]["text"] == en
    (coding,) = [c for c in res["code"]["coding"] if c["code"] == code]
    assert coding["display"] == display("snomed-ct", code, "en")
