"""JP-eCheckup DocumentReference builder(P2-13 PR3 sub-PR-E, session 48).

HEALTH_CHECKUP_REPORT の Composition に対して、対応する DocumentReference を
併存させる。実 EHR での健診結果交換シナリオ(事業所 ⇄ 保険者 ⇄ 実施機関)で
標準的に用いられる wrapper。Composition は構造化 section を保持し、
DocumentReference は portable な attachment + relatesTo で Composition を参照する。

対象:
- `ClinicalDocument.task_type == "health_checkup_report"`
- `ClinicalDocument.format_type == "composition"`

emit しないケース:
- 他 task_type(discharge_summary / referral_note 等)は Composition のみで運用
- narrative が None(Stage 2 pass 未実行)は warn + skip

ID convention:
- DocumentReference.id = `drf-<document_id>`(Composition.id との衝突回避)
- masterIdentifier / identifier は clinosim canonical URI 名前空間

byte-diff invariant:
- `modules["health_checkup"]=True` の JP コホートでのみ emit。標準 reproduce.sh
  は opt-in を有効化しないため既存 byte-identical 出力を保つ。
"""

from __future__ import annotations

import base64
import logging
from typing import Any

from clinosim.codes import get_system_uri
from clinosim.codes import lookup as code_lookup
from clinosim.modules._shared import get_attr_or_key as _o
from clinosim.modules._shared import is_jp, resolve_lang
from clinosim.modules.output._fhir_common import BundleContext, _sha1_b64, to_fhir_instant


def _fhir_instant_or_empty(s: str) -> str:
    return to_fhir_instant(s) if s else ""


logger = logging.getLogger(__name__)

__all__ = ["_bb_document_references_checkup"]

# Composition と衝突しない DocumentReference id prefix
_DOCREF_ID_PREFIX = "drf-"

# 健診 category(HL7 v3 ActClass / IHE PCC は該当 code 無し、
# JP-eCheckup は独自 typecodes を採用)
_JP_CATEGORY = {
    "system": "http://jpfhir.jp/fhir/eCheckup/CodeSystem/doc-typecodes",
    "code": "eCheckupGeneral",
    "display": "健診結果報告書",
}


def _bb_document_references_checkup(ctx: BundleContext) -> list[dict[str, Any]]:
    """CHECKUP composition doc に対して DocumentReference wrapper を emit する。

    Called by `_BUNDLE_BUILDERS` registry。JP かつ record が
    HEALTH_CHECKUP_REPORT ClinicalDocument を持つ場合のみ非空を返す。
    US や opt-in 無効の JP コホートでは空 list を返し byte-diff を保つ。
    """
    country = ctx.country or "us"
    if not is_jp(country):
        return []

    raw_docs = _o(ctx.record, "documents", []) or []
    patient_id = _o(_o(ctx.record, "patient", {}), "patient_id", "")

    out: list[dict[str, Any]] = []
    for doc in raw_docs:
        if _o(doc, "task_type", "") != "health_checkup_report":
            continue
        if _o(doc, "format_type", "") != "composition":
            continue
        narrative = _o(doc, "narrative", None)
        if not narrative:
            logger.warning(
                "checkup DocumentReference skipped: doc %s has no narrative (Stage 2 pass not run)",
                _o(doc, "document_id", ""),
            )
            continue
        resource = _build_dref(doc, narrative, patient_id, country)
        if resource:
            out.append(resource)
    return out


def _build_dref(doc: Any, narrative: Any, patient_id: str, country: str) -> dict[str, Any] | None:
    """健診 DocumentReference を組み立てる。Composition を relatesTo で参照。"""
    loinc_code = _o(doc, "loinc_code", "") or "53576-5"
    lang = _o(doc, "language", "") or resolve_lang(country)

    # narrative から section text を合成(既存 free_text builder と同型式)
    text = _o(narrative, "text", "") or ""
    if not text:
        # section 集約 fallback:sections dict の値を join
        sections = _o(narrative, "sections", None) or {}
        if isinstance(sections, dict):
            text = "\n\n".join(str(v) for v in sections.values() if v)
    if not text:
        # 個別化 lab 判定文の最低限を確保できないため skip
        logger.warning(
            "checkup DocumentReference: doc %s narrative has neither text nor sections",
            _o(doc, "document_id", ""),
        )
        return None

    document_id = _o(doc, "document_id", "")
    resource_id = f"{_DOCREF_ID_PREFIX}{document_id}"
    encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
    type_display = code_lookup("loinc", loinc_code, lang) or loinc_code

    resource: dict[str, Any] = {
        "resourceType": "DocumentReference",
        "id": resource_id,
        "masterIdentifier": {
            "system": "urn:clinosim:documentreference-master",
            "value": resource_id,
        },
        "identifier": [
            {
                "system": "urn:clinosim:documentreference-id",
                "value": resource_id,
            }
        ],
        "status": "current",
        "docStatus": "final",
        "type": {
            "coding": [
                {
                    "system": get_system_uri("loinc"),
                    "code": loinc_code,
                    "display": type_display,
                }
            ],
            "text": type_display,
        },
        "category": [
            {
                "coding": [_JP_CATEGORY],
                "text": "健診結果報告書",
            }
        ],
        "securityLabel": [
            {
                "coding": [
                    {
                        "system": "http://terminology.hl7.org/CodeSystem/v3-Confidentiality",
                        "code": "N",
                        "display": "Normal",
                    }
                ],
            }
        ],
        "subject": {"reference": f"Patient/{patient_id}"},
        "date": _fhir_instant_or_empty(_o(doc, "authored_datetime", "") or _o(narrative, "generated_at", "")),
        "content": [
            {
                "attachment": {
                    "contentType": _o(doc, "content_type", "text/plain; charset=utf-8"),
                    "language": lang,
                    "data": encoded,
                    "title": type_display,
                    "size": len(text.encode("utf-8")),
                    "hash": _sha1_b64(text),
                },
                "format": {
                    "system": "urn:oid:1.3.6.1.4.1.19376.1.2.3",
                    "code": "urn:ihe:iti:xds:2017:mimeTypeSufficient",
                    "display": "MIME type sufficient (contentType is authoritative)",
                },
            }
        ],
        # 対応する Composition への参照(実 EHR で Composition = 構造化、
        # DocumentReference = portable な wrapper として運用される二重発行)
        "relatesTo": [
            {
                "code": "transforms",
                "target": {"reference": f"Composition/{document_id}"},
            }
        ],
    }

    # encounter context(健診 encounter)
    encounter_id = _o(doc, "encounter_id", "")
    if encounter_id:
        resource["context"] = {
            "encounter": [{"reference": f"Encounter/{encounter_id}"}],
        }

    # author / custodian(session 47 patterns per)
    author_id = _o(doc, "author_practitioner_id", "")
    if author_id:
        resource["author"] = [{"reference": f"Practitioner/{author_id}"}]
    resource["custodian"] = {"reference": "Organization/hospital-main"}

    return resource
