"""N-3 enum sync tests: DocumentType ↔ LLMTaskType ↔ DOCUMENT_LOINC ↔ YAML.

Canonical-constants pattern (PR-90 discipline): every DocumentType value must
be a narrative-category LLMTaskType (import-time validated in engine.py);
DOCUMENT_LOINC must agree with document_type_specs.yaml for shared members.
"""
from __future__ import annotations

import pytest

from clinosim.modules.document.narrative.registry import load_document_type_specs
from clinosim.modules.llm_service.engine import (
    DOCUMENT_LOINC,
    TASK_CATEGORY,
    LLMTaskCategory,
    LLMTaskType,
    _validate_document_task_sync,
)
from clinosim.types.document import DocumentType


@pytest.mark.unit
def test_every_document_type_is_a_narrative_llm_task_type() -> None:
    narrative_values = {
        t.value for t in LLMTaskType
        if TASK_CATEGORY[t] == LLMTaskCategory.NARRATIVE
    }
    missing = {d.value for d in DocumentType} - narrative_values
    assert not missing, f"DocumentType values without narrative LLMTaskType: {missing}"


@pytest.mark.unit
def test_task_category_covers_every_task_type() -> None:
    assert set(TASK_CATEGORY.keys()) == set(LLMTaskType)


@pytest.mark.unit
def test_coarse_nursing_note_removed() -> None:
    """NURSING_NOTE replaced by the 3 explicit nursing doc types (α-min-2/3)."""
    assert "nursing_note" not in {t.value for t in LLMTaskType}


@pytest.mark.unit
def test_document_loinc_matches_document_type_specs_yaml() -> None:
    """DOCUMENT_LOINC and document_type_specs.yaml must agree for every
    shared member (single-source cross-validation — the codes are stored in
    both places; drift = wrong LOINC on emitted FHIR resources)."""
    specs = load_document_type_specs()
    for doc_type, spec in specs.items():
        task = LLMTaskType(doc_type.value)
        assert task in DOCUMENT_LOINC, f"DOCUMENT_LOINC missing entry for {task}"
        assert DOCUMENT_LOINC[task] == spec.loinc_code, (
            f"LOINC drift for {doc_type.value}: "
            f"DOCUMENT_LOINC={DOCUMENT_LOINC[task]} yaml={spec.loinc_code}"
        )


@pytest.mark.unit
def test_document_loinc_keys_are_narrative_tasks() -> None:
    for task in DOCUMENT_LOINC:
        assert TASK_CATEGORY[task] == LLMTaskCategory.NARRATIVE, task


@pytest.mark.unit
def test_validate_document_task_sync_negative() -> None:
    """The import-time validator must raise when a DocumentType value has no
    narrative LLMTaskType counterpart."""
    with pytest.raises(ImportError, match="phantom_doc_type"):
        _validate_document_task_sync(
            document_type_values=frozenset({"admission_hp", "phantom_doc_type"}),
            narrative_task_values=frozenset({"admission_hp"}),
        )


@pytest.mark.unit
def test_validate_document_task_sync_positive() -> None:
    """Current enums pass the validator (the import-time call did not raise)."""
    _validate_document_task_sync()  # must not raise
