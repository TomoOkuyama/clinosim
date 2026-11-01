"""One lab display table for every output (Issue #2267).

Narrative, LLM context, ``DiagnosticReport.conclusion`` and the FHIR text of
uncoded analytes all read ``locale/shared/lab_display.yaml`` through
``clinosim.locale.loader.lab_display``.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from clinosim.codes.ucum import ucum_prose
from clinosim.locale.loader import lab_display, load_lab_display
from clinosim.modules.document.narrative._replacement_localization import _localize_lab_names_in_text_ja
from clinosim.modules.output.fhir_r4.labs.diagnostic_report import _build_lab_panel_conclusion

pytestmark = pytest.mark.unit

_REF = Path(__file__).resolve().parents[2] / "clinosim" / "modules" / "observation" / "reference_data"


def _emitted_lab_names() -> set[str]:
    constants = yaml.safe_load((_REF / "lab_constants.yaml").read_text(encoding="utf-8"))
    panels = yaml.safe_load((_REF / "lab_panels.yaml").read_text(encoding="utf-8"))["panels"]
    aliases = yaml.safe_load((_REF / "lab_aliases.yaml").read_text(encoding="utf-8"))
    return set(constants["units"]) | set(panels) | set(aliases.values())


def test_every_entry_has_english_and_japanese() -> None:
    for key, entry in load_lab_display().items():
        assert entry.get("en"), key
        assert entry.get("ja"), key


def test_every_lab_the_simulator_emits_has_an_entry() -> None:
    table = load_lab_display()
    missing = sorted(n for n in _emitted_lab_names() if n.lower() not in table)
    assert not missing


def test_every_protocol_order_name_has_an_entry() -> None:
    aliases = yaml.safe_load((_REF / "lab_aliases.yaml").read_text(encoding="utf-8"))
    table = load_lab_display()
    assert not sorted(k for k in aliases if k.lower() not in table)


@pytest.mark.parametrize("lang", ["en", "ja"])
def test_no_canonical_lab_name_renders_as_a_slug(lang: str) -> None:
    for name in sorted(_emitted_lab_names()):
        if "_" in name:
            assert "_" not in lab_display(name, lang), name


def test_formal_style_prefers_the_full_name() -> None:
    assert lab_display("pH", "ja") == "pH"
    assert lab_display("pH", "ja", style="formal") == "動脈血pH"
    # No formal name in the requested language: the short form, not English.
    assert lab_display("T_Bil", "ja", style="formal") == "総ビリルビン"
    assert lab_display("eGFR", "fr") == "eGFR"


def test_lookup_ignores_case_and_spacing() -> None:
    assert lab_display("Total bilirubin", "ja") == lab_display("T_Bil", "ja") == "総ビリルビン"
    assert lab_display("TROPONIN I", "ja") == "トロポニンI"


def test_unknown_token_is_humanised_or_given_fallback() -> None:
    assert lab_display("novel_marker", "ja") == "novel marker"
    assert lab_display("novel_marker", "ja", fallback="X") == "X"


def test_llm_guard_reads_the_same_table() -> None:
    assert _localize_lab_names_in_text_ja("Total bilirubin 3.0 mg/dL, BUN 25") == "総ビリルビン 3.0 mg/dL, BUN 25"
    assert _localize_lab_names_in_text_ja("Urine drug screen negative") == "尿中乱用薬物スクリーニング negative"


def _order(name: str, value: float, unit: str, flag: str = "") -> dict:
    return {
        "order_type": "lab",
        "display_name": name,
        "result": {"lab_name": name, "value": value, "unit": unit, "flag": flag},
    }


class _Group:
    def __init__(self, n: int) -> None:
        self.obs_idxs = list(range(n))


@pytest.mark.parametrize("lang", ["en", "ja"])
def test_dr_conclusion_uses_the_narrative_name_and_prose_unit(lang: str) -> None:
    orders = [
        _order("T_Bil", 2.4, "mg/dL", "H"),
        _order("PT_INR", 2.6, "{INR}", "H"),
        _order("pCO2", 52.0, "mm[Hg]", "H"),
        _order("pH", 7.31, "[pH]", "L"),
    ]
    text, abnormal = _build_lab_panel_conclusion(_Group(len(orders)), orders, "enc-1", lang)
    assert abnormal
    for name in ("T_Bil", "PT_INR", "pCO2"):
        assert name not in text
    assert lab_display("T_Bil", lang) in text
    assert "{INR}" not in text and "mm[Hg]" not in text and "mmHg" in text
    assert not re.search(r"pH 7\.31 pH", text)


def test_ucum_prose() -> None:
    assert ucum_prose("mL/min/{1.73_m2}") == "mL/min"
    assert ucum_prose("mm[Hg]") == "mmHg"
    assert ucum_prose("{INR}") == ""
