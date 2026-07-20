"""Issue #332 — admit-source fallback code is authoritative.

Pins that:
1. `hl7-admit-source.yaml` no longer defines `hosp` (which is NOT in
   authoritative HL7 admit-source CS r4 7.2.0), and
2. `other` is defined instead (authoritative fallback for unspecified source),
3. the `_fhir_encounter.py` IMP hospitalization fallback emits `other`,
   not `hosp`.

authoritative HL7 admit-source concepts (r4 7.2.0):
hosp-trans/emd/outp/born/gp/mp/nursing/psych/rehab/other.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.unit


_REPO_ROOT = Path(__file__).resolve().parents[2]
_ADMIT_SOURCE_YAML = _REPO_ROOT / "clinosim" / "codes" / "data" / "hl7-admit-source.yaml"


def _load_codes() -> dict[str, dict[str, str]]:
    return yaml.safe_load(_ADMIT_SOURCE_YAML.read_text())["codes"]


def test_admit_source_yaml_removes_invalid_hosp_code() -> None:
    codes = _load_codes()
    assert "hosp" not in codes, (
        "Issue #332: 'hosp' は authoritative HL7 admit-source CS(r4 7.2.0)に無い。"
        "hl7-admit-source.yaml から削除済みであること。"
    )


def test_admit_source_yaml_has_authoritative_other_fallback() -> None:
    codes = _load_codes()
    assert "other" in codes, (
        "Issue #332: 'other' は IMP encounter admit_source 欠落時の "
        "semantic-honest な fallback として YAML に登録されていること。"
    )
    assert codes["other"].get("en"), "'other' must carry en display"
    assert codes["other"].get("ja"), "'other' must carry ja display"


def test_fhir_encounter_default_admit_source_code_is_other() -> None:
    src = (_REPO_ROOT / "clinosim" / "modules" / "output" / "_fhir_encounter.py").read_text()
    assert '_default_code = "other"' in src, (
        "Issue #332: _fhir_encounter.py の IMP admit_source fallback は "
        '"other" を emit すること('
        '"hosp" は authoritative CS 未収録で validation error 発火)'
    )
    assert '_default_code = "hosp"' not in src, 'Issue #332: 従来の invalid `_default_code = "hosp"` は残存禁止。'
