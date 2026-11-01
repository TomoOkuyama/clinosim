"""The dosage-term table holds no procedure name; procedure names are
translated by the procedure table only (Issue #2446)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

import clinosim
from clinosim.locale.free_text import localize_drug_name, localize_procedure_name

pytestmark = pytest.mark.unit

_ROOT = Path(clinosim.__file__).parent


def _term_keys(node: object) -> set[str]:
    if isinstance(node, dict):
        keys = {str(k).lower() for k, v in node.items() if isinstance(v, dict) and "ja" in v}
        return keys | {k for v in node.values() if isinstance(v, dict) and "ja" not in v for k in _term_keys(v)}
    return set()


def test_no_procedure_name_in_med_terms() -> None:
    terms = _term_keys(yaml.safe_load((_ROOT / "locale/shared/med_terms.yaml").read_text(encoding="utf-8")))
    procedures = yaml.safe_load((_ROOT / "codes/data/clinosim-procedure-phrase.yaml").read_text(encoding="utf-8"))
    overlap = sorted(terms & {str(k).lower() for k in procedures["procedures"]})
    assert not overlap, overlap


def test_procedure_name_is_translated_by_the_procedure_table() -> None:
    assert localize_procedure_name("Hemodialysis", "ja") == "血液透析"
    assert localize_procedure_name("Suture closure", "ja") == "縫合閉創"
    assert localize_drug_name("Tissue adhesive", "ja") != "組織接着剤"
