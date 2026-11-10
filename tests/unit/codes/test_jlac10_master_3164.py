"""JLAC10 analyte codes are checked against the JSLM master (Issue #3164)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from clinosim.codes import lookup as code_lookup
from clinosim.locale.loader import load_code_mapping

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[3] / "clinosim" / "codes"
_MASTER = {c["code"]: c for c in json.loads((_ROOT / "authoritative" / "jlac10_jslm_137.json").read_text())["concept"]}


def test_every_registered_analyte_code_is_in_the_master() -> None:
    codes = yaml.safe_load((_ROOT / "data" / "jlac10.yaml").read_text(encoding="utf-8"))["codes"]
    for code, names in codes.items():
        assert code in _MASTER, f"{code} not in the JSLM JLAC10 master"
        # The registry may spell out an abbreviation the master uses (CK-MB, AST ...).
        assert _MASTER[code]["display"] in names["ja"], (code, names["ja"], _MASTER[code]["display"])


def test_jp_hba1c_is_the_ngsp_analyte() -> None:
    code = load_code_mapping("lab", "JP")["HbA1c"]
    assert code == "3D046"
    assert code_lookup("jlac10", code, "ja") == _MASTER[code]["display"] == "グリコヘモグロビンA1c(NGSP)"
