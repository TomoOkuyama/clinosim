"""Issue #343 — Attachment.contentType は bare mime type("text/plain")のみ、
HTTP Content-Type header の charset parameter は含まない。

## Rationale (FHIR R4 spec)

FHIR R4 `Attachment.contentType` の binding = **required** to
`http://hl7.org/fhir/ValueSet/mimetypes`。ValueSet 由来 CodeSystem =
`urn:ietf:bcp:13`(IANA Media Types Registry)= **bare media type のみ**
収録(charset 等 HTTP Content-Type parameter は登録されない)。

v14gen (2026-07-21) validation で `"text/plain; charset=utf-8"` が
MimeType VS 外で 23,600 件 error 発火。fix: bare `"text/plain"` へ変更、
UTF-8 は FHIR 全体の default 前提で semantic loss なし。

## 対象 field

- `DocumentReference.content.attachment.contentType`
- `DiagnosticReport.presentedForm.contentType`

## 対象 emitter (全 6 箇所)

- `clinosim/types/clinical.py` — `ClinicalDocument.content_type` default
- `clinosim/modules/output/_fhir_common.py` — presentedForm builder
- `clinosim/modules/output/_fhir_documents.py` — DocumentReference builder fallback
- `clinosim/modules/output/_fhir_document_reference_checkup.py` — checkup DR fallback
- `clinosim/modules/document/audit.py` — audit proof literals(2 箇所)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from clinosim.modules.output._fhir_common import build_presented_form
from clinosim.types.clinical import ClinicalDocument

pytestmark = pytest.mark.unit


_REPO_ROOT = Path(__file__).resolve().parents[2]


# === default + emitter behavior pin ===


def test_clinical_document_default_content_type_is_bare_text_plain() -> None:
    """CIF type default が bare mime type であることを pin。"""
    doc = ClinicalDocument(
        document_id="doc-test",
        task_type="progress_note",
        loinc_code="11506-3",
        patient_id="pt-1",
        encounter_id="enc-1",
    )
    assert doc.content_type == "text/plain", (
        f"Issue #343: ClinicalDocument.content_type default must be bare "
        f"'text/plain' (IANA Media Types VS 準拠)。got: {doc.content_type!r}"
    )


def test_presented_form_content_type_is_bare_text_plain() -> None:
    """DiagnosticReport.presentedForm builder が bare mime type を emit。"""
    forms = build_presented_form(text="Sample lab summary.", title="Lab Report", lang="en")
    assert len(forms) == 1
    assert forms[0]["contentType"] == "text/plain", (
        f"Issue #343: presentedForm.contentType must be bare 'text/plain'、got {forms[0]['contentType']!r}"
    )


def test_presented_form_empty_text_returns_empty_list() -> None:
    """Regression: empty text で [] を返す挙動は不変。"""
    assert build_presented_form(text="", title="", lang="en") == []


# === grep-based no-charset invariant(sibling drift 検知)===


def test_no_charset_parameter_in_source_content_type_literals() -> None:
    """全 source code に `text/plain; charset=` literal が残存していないこと。
    将来の追記で charset parameter を再導入した場合、この test が fail して
    Issue #343 の教訓を思い出せる仕組み(sibling drift 検知)。

    scope:
    - clinosim/types/*.py
    - clinosim/modules/output/*.py
    - clinosim/modules/document/*.py

    tests/ 配下は除外(regression 説明の docstring で歴史的 literal を使う)。
    """
    forbidden = "text/plain; charset"
    scan_dirs = [
        _REPO_ROOT / "clinosim" / "types",
        _REPO_ROOT / "clinosim" / "modules" / "output",
        _REPO_ROOT / "clinosim" / "modules" / "document",
    ]
    offenders: list[str] = []
    for d in scan_dirs:
        for py in d.rglob("*.py"):
            src = py.read_text()
            for i, line in enumerate(src.splitlines(), 1):
                # コメント/docstring 内の言及(Issue #343 説明で使用)は許容
                stripped = line.lstrip()
                if stripped.startswith("#") or stripped.startswith('"'):
                    continue
                if forbidden in line:
                    offenders.append(f"{py.relative_to(_REPO_ROOT)}:{i}: {line.strip()}")
    assert not offenders, (
        "Issue #343 sibling drift: `text/plain; charset` literal が source に "
        "再導入されている(全て bare 'text/plain' へ):\n" + "\n".join(offenders)
    )
