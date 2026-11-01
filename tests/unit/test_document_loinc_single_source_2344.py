"""Each document type's LOINC code is defined once, in
document_type_specs.yaml (Issue #2344)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

import clinosim
from clinosim.modules.document.narrative.registry import document_loinc, load_document_type_specs
from clinosim.modules.llm_service import DOCUMENT_LOINC, LLMTaskType

pytestmark = pytest.mark.unit

_ROOT = Path(clinosim.__file__).parent
_CODES = sorted({spec.loinc_code for spec in load_document_type_specs().values()})


def test_accessor_reads_the_specs() -> None:
    for doc_type, spec in load_document_type_specs().items():
        assert document_loinc(doc_type.value) == spec.loinc_code
    with pytest.raises(ValueError):
        document_loinc("not_a_document_type")


def test_llm_task_codes_come_from_the_specs() -> None:
    for doc_type, spec in load_document_type_specs().items():
        assert DOCUMENT_LOINC[LLMTaskType(doc_type.value)] == spec.loinc_code
    raw = yaml.safe_load((_ROOT / "modules/llm_service/reference_data/task_loincs.yaml").read_text(encoding="utf-8"))
    assert not set(raw["loincs"]) & {d.value for d in load_document_type_specs()}


@pytest.mark.parametrize("code", _CODES)
def test_no_document_loinc_literal_in_python(code: str) -> None:
    """No quoted document LOINC literal in Python source (comments aside)."""
    pattern = re.compile(rf"""["']{re.escape(code)}["']""")
    offenders = []
    for path in _ROOT.rglob("*.py"):
        for line in path.read_text(encoding="utf-8").splitlines():
            code_part = line.split("#", 1)[0]
            if pattern.search(code_part):
                offenders.append(path.relative_to(_ROOT).as_posix())
    assert not offenders, offenders
