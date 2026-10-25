"""JP-CLINS eDischargeSummary v1.13.0 Composition builder.

Extracted verbatim from ``composition.py::_build_jp_clins_discharge_summary_
composition`` (full-review Phase B2, CRITICAL C5a).

The builder reuses the generic Composition builder (lazy-imported from
``composition.py`` to break the circular dep: composition.py's dispatcher
imports the entry point from this module, and this module needs
``_build_composition_generic`` from composition.py). The lazy import is
inside the function body so module load is cycle-free.

Author policy, custodian / section tree, and entry-reference logic are
all per JP-CLINS 1.13.0 spec; see the function docstring and the inline
comments for the clause-by-clause mapping.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path
from typing import Any

import yaml

from clinosim.codes import lookup as code_lookup
from clinosim.modules._shared import get_attr_or_key as _o
from clinosim.modules.output.fhir_r4.encounters.encounter import resolve_encounter_id
from clinosim.modules.output.fhir_r4.lib.common import _escape_html, derive_meta_last_updated

# ---------------------------------------------------------------------------
# JP-CLINS eDS constants — the per-profile URIs / codes dispatched by the
# builder. Kept co-located with the function that uses them.
# ---------------------------------------------------------------------------
_JP_CLINS_DS_PROFILE = "http://jpfhir.jp/fhir/eDischargeSummary/StructureDefinition/JP_Composition_eDischargeSummary"
_JPFHIR_DOC_TYPECODES_SYSTEM = "http://jpfhir.jp/fhir/Common/CodeSystem/doc-typecodes"
_JP_EDS_VERSION_EXTENSION_URL = "http://hl7.org/fhir/StructureDefinition/composition-clinicaldocument-versionNumber"
_JPFHIR_DOC_SUBTYPECODES_SYSTEM = "http://jpfhir.jp/fhir/Common/CodeSystem/doc-subtypecodes"
_JP_EDS_CATEGORY_CODE = "DISCHARGE"
_JP_EDS_CATEGORY_DISPLAY_JA = "退院時文書"
_JP_EDS_TYPE_DISPLAY_JA = "退院時サマリー"
_JPFHIR_DOC_SECTION_SYSTEM = "http://jpfhir.jp/fhir/clins/CodeSystem/document-section"


# ---------------------------------------------------------------------------
# JP-CLINS eDS section slice registry — yaml-backed. Carries the section
# code, title, allowed multi-entry resource types, and the templated
# entry reference per slice.
# ---------------------------------------------------------------------------


@cache
def _jp_ds_sections() -> dict[str, dict[str, Any]]:
    """Load the JP-CLINS eDS section slice registry."""
    path = Path(__file__).resolve().parents[5] / "codes" / "data" / "jp-clins-eds-section-codes.yaml"
    with path.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    out: dict[str, dict[str, Any]] = {}
    for k, v in (raw.get("sections", {}) or {}).items():
        if isinstance(v, dict):
            out[str(k)] = v
    return out


def _jp_ds_section_code() -> dict[str, str]:
    return {k: str(row["code"]) for k, row in _jp_ds_sections().items() if "code" in row}


def _jp_ds_multi_entry_types() -> dict[str, tuple[str, ...]]:
    out: dict[str, tuple[str, ...]] = {}
    for k, row in _jp_ds_sections().items():
        types = row.get("multi_entry_types") or []
        if types:
            out[k] = tuple(str(rt) for rt in types)
    return out


def _jp_ds_section_entry_references() -> dict[str, tuple[str, str]]:
    out: dict[str, tuple[str, str]] = {}
    for k, row in _jp_ds_sections().items():
        ref = row.get("entry_ref")
        if isinstance(ref, list) and len(ref) == 2:
            out[k] = (str(ref[0]), str(ref[1]))
    return out


# ---------------------------------------------------------------------------
# Entry point: dispatched by composition.py::_bb_compositions.
# ---------------------------------------------------------------------------


def _build_jp_clins_discharge_summary_composition(
    doc: Any,
    sections: dict[str, str],
    lang: str,
    enc_to_free_text: dict[str, str] | None = None,
    enc_to_primary_cond: dict[str, str] | None = None,
    *,
    roster_map: dict[str, dict] | None = None,
    encounter_index: dict[str, dict[str, list[dict[str, str]]]] | None = None,
) -> dict[str, Any]:
    """JP-CLINS eDischargeSummary v1.13.0 準拠 Composition を emit する。

    汎用 Composition builder との差分:
      - meta.profile = [JP_Composition_eDischargeSummary]
      - type.coding[0].system = doc-typecodes(LOINC coding は US 互換の
        ため secondary として併存)
      - section は 1-level nested tree:300 構造情報 → 必須 5 子 section
        (312/322/342/352/360)。section.code.system は JP-CLINS 定義の
        document-section CodeSystem(URL:
        `http://jpfhir.jp/fhir/clins/CodeSystem/document-section`、LOINC
        section code ではない)。
    """
    # Lazy imports break the composition.py ↔ discharge_summary.py cycle.
    from clinosim.modules.output.fhir_r4.conditions.primary_ref import (
        encounter_primary_condition_id,
    )
    from clinosim.modules.output.fhir_r4.documents.composition import (
        _build_composition_generic,
        _section_title_from_section_display,
    )

    # 共通 field(id / subject / date / author / encounter / attester /
    # custodian / confidentiality 等)は汎用 builder を再利用し、type と
    # section のみ上書きする。
    comp = _build_composition_generic(doc, sections, lang, roster_map=roster_map)

    # meta.profile 追加(既に含まれていれば skip)
    meta = comp.setdefault("meta", {})
    profs = meta.setdefault("profile", [])
    if _JP_CLINS_DS_PROFILE not in profs:
        profs.append(_JP_CLINS_DS_PROFILE)

    # (Chain #9) `meta.lastUpdated` min=1 — reuse authoredOn / date. Emit
    # only when a source datetime exists so we never fabricate.
    if not meta.get("lastUpdated"):
        ts = derive_meta_last_updated(comp, ("date",)) or _o(doc, "authored_datetime", "")
        if ts:
            meta["lastUpdated"] = ts

    # `type` field:jpfhir doc-typecodes を primary。
    # v3 fix: eDS profile constrains type.coding to max=1, so
    # emit only the doc-typecodes coding — the LOINC copy (previously
    # emitted for interop) violated the profile slicing on 129 resources.
    # The LOINC value is preserved via type.text so downstream consumers
    # can still recover the same code as text.
    disp = code_lookup("jpfhir-doc-typecodes", "18842-5", lang) or _JP_EDS_TYPE_DISPLAY_JA
    comp["type"] = {
        "coding": [
            {"system": _JPFHIR_DOC_TYPECODES_SYSTEM, "code": "18842-5", "display": disp},
        ],
        "text": disp,
    }
    comp["title"] = disp

    # (Chain #9) `Composition.extension:version` min=1 — 文書バージョン番号。
    # The extension slice is discriminated by URL; value[x] is `valueString`
    # per spec `valueString`. clinosim emits "1" (initial issue) since no
    # revision history is tracked; downstream systems can update in place.
    exts = comp.setdefault("extension", [])
    if not any(isinstance(e, dict) and e.get("url") == _JP_EDS_VERSION_EXTENSION_URL for e in exts):
        exts.append({"url": _JP_EDS_VERSION_EXTENSION_URL, "valueString": "1"})

    # (Chain #9) `Composition.category` min=1 max=1 — fixed to DISCHARGE
    # under the doc-subtypecodes CodeSystem.
    comp["category"] = [
        {
            "coding": [
                {
                    "system": _JPFHIR_DOC_SUBTYPECODES_SYSTEM,
                    "code": _JP_EDS_CATEGORY_CODE,
                    "display": _JP_EDS_CATEGORY_DISPLAY_JA,
                }
            ]
        }
    ]

    # (Chain #9) `Composition.author` min=2 — 文書作成責任者 (Practitioner)
    # + 文書作成機関 (Organization). Generic builder already sets
    # author[0]=Practitioner from doc.author_practitioner_id. Append an
    # Organization reference.
    #
    # #330 eDS profile の Composition.author target は
    # JP_Organization_eCS 準拠を要求(spec verified)。Issue #746 の unify
    # 以後、`hospital-main` 自身が JP_Organization + JP_Organization_eCS を
    # 両宣言するため参照先を hospital-main に戻す(以前は
    # `hospital-main-ecs` 別 id を使う workaround で slice validation を
    # 通していたが、単一 org 案で自然解決)。
    authors = comp.setdefault("author", [])
    if not isinstance(authors, list):
        authors = []
        comp["author"] = authors
    if not any(isinstance(a, dict) and str(a.get("reference", "")).startswith("Organization/") for a in authors):
        authors.append({"reference": "Organization/hospital-main"})

    # #330 eDS profile の Composition.custodian target は
    # JP_Organization_eCS 準拠を要求。unify 済 hospital-main を参照。
    comp["custodian"] = {"reference": "Organization/hospital-main"}

    # (Chain #9) section tree — 300 parent + 10 required child sections.
    # yaml carries `構造情報セクション` (long form, matches spec `patternString`);
    # `_section_title_from_section_display` derives the short-form title
    # per spec `title.fixedString` (Chain #8 pattern).
    parent_disp = code_lookup("jpfhir-doc-section", "300", lang) or "構造情報セクション"
    parent_title = _section_title_from_section_display(parent_disp)
    # Chain #9 follow-up (#267): pre-compute the ids the
    # entry references need. hospital_course の deferral を
    # 解消 — `_bb_compositions` が enc → free-text DocumentReference id map
    # を precompute し `enc_to_free_text` として渡す。map hit しない場合は
    # `free_text_doc_id` を空文字で埋め、下の never-fabricate guard で drop。
    _enc_id = _o(doc, "encounter_id", "") or ""
    _free_text_doc_id = (enc_to_free_text or {}).get(_enc_id, "")
    # Fall back to the encounter-scoped opaque Condition.id when no map
    # was passed (unit tests exercise the builder directly). The real
    # caller (`_bb_compositions`) always supplies the map so chronic-
    # primary encounters resolve to the patient-scoped chronic Condition.
    # Issue #854 Bucket B (PR-condition): route through the shared
    # resolver so this reference stays byte-consistent with the emit.
    _primary_cond_id = ""
    if enc_to_primary_cond:
        _primary_cond_id = enc_to_primary_cond.get(_enc_id, "")
    if not _primary_cond_id and _enc_id:
        _fallback_patient_id = _o(doc, "patient_id", "") or ""
        _primary_cond_id = encounter_primary_condition_id(_fallback_patient_id, _enc_id)
    # Issue #854 PR-encounter: template needs opaque encounter id.
    _entry_ctx = {
        "encounter_id": resolve_encounter_id(_enc_id) if _enc_id else "",
        "free_text_doc_id": _free_text_doc_id,
        "primary_cond_id": _primary_cond_id,
    }

    child_sections: list[dict[str, Any]] = []
    for key, code in _jp_ds_section_code().items():
        disp_c = code_lookup("jpfhir-doc-section", code, lang) or key
        title_c = _section_title_from_section_display(disp_c)
        text_val = sections.get(key, "") or ""
        # Chain #9: section.code.text max=0 — drop `text` from `code`.
        section_obj: dict[str, Any] = {
            "title": title_c,
            "code": {
                "coding": [
                    {
                        "system": _JPFHIR_DOC_SECTION_SYSTEM,
                        "code": code,
                        "display": disp_c,
                    }
                ],
            },
            # Chain 8: JP-CLINS pins `text.status` to `additional`.
            "text": {
                "status": "additional",
                "div": (f'<div xmlns="http://www.w3.org/1999/xhtml">{_escape_html(text_val)}</div>'),
            },
        }
        # Chain #9 follow-up (#267): required `.entry` reference on
        # detailsOnAdmission / hospitalCourse / detailsOnDischarge /
        # diagnosesOnDischarge slices. Only emit when the referenced resource
        # id is derivable (encounter_id / document_id present); a missing
        # source leaves the entry off so we never fabricate a broken
        # reference.
        entry_spec = _jp_ds_section_entry_references().get(key)
        if entry_spec is not None:
            _, ref_template = entry_spec
            try:
                ref = ref_template.format(**_entry_ctx)
            except KeyError:
                ref = ""
            # Reject broken references — any format substitution that ended up
            # empty leaves the string looking like `Encounter/` or
            # `Condition/cond--primary`. Both are dead references so we drop
            # the entry rather than emit garbage.
            # #278:`DocumentReference/` (empty free_text_doc_id
            # fallback) too — same never-fabricate guard.
            if ref.endswith("/") or "//" in ref or "cond--primary" in ref:
                ref = ""
            if ref:
                section_obj["entry"] = [{"reference": ref}]
        # Issue #925: extend the eDS section entries beyond the fixed
        # single-ref slices in `_JP_DS_SECTION_ENTRY_REFERENCES`.
        # `_JP_DS_MULTI_ENTRY_TYPES` maps a section key to the
        # resourceType bucket in `encounter_resource_index`; when the
        # bucket has entries we append them (avoiding the primary
        # Condition ref already emitted above so 344 does not double).
        # 342 (admission_diagnoses) mirrors 344's primary Condition
        # when the eDS has no separately-tracked admission Condition
        # resource — clinosim's `clinical_diagnosis` typically carries
        # a single primary shared by admission and discharge.
        _multi_types = _jp_ds_multi_entry_types().get(key, ())
        if _multi_types and encounter_index is not None and _enc_id:
            _existing_refs = {e.get("reference") for e in section_obj.get("entry", [])}
            # The index is keyed on OPAQUE encounter ids (built from
            # `resource.encounter.reference`); `_enc_id` here is the
            # raw CIF encounter id. Look up under the opaque form
            # first, with a fall-through to the raw id so unit tests
            # that pre-key the index with the raw id still resolve.
            _resolved_enc = resolve_encounter_id(_enc_id)
            _bucket = encounter_index.get(_resolved_enc) or encounter_index.get(_enc_id) or {}
            _extra: list[dict[str, str]] = []
            for _rtype in _multi_types:
                for _ref_entry in _bucket.get(_rtype, []):
                    if _ref_entry.get("reference") in _existing_refs:
                        continue
                    _extra.append(_ref_entry)
                    _existing_refs.add(_ref_entry.get("reference"))
            if _extra:
                section_obj.setdefault("entry", []).extend(_extra)
        # 342 (入院時診断) mirrors 344 primary Condition when the index
        # is not consulted (unit tests) — keeps parity between
        # admission/discharge dx sections so a document-first consumer
        # sees a Condition on both slices instead of only 344.
        if key == "admission_diagnoses" and "entry" not in section_obj and _primary_cond_id:
            section_obj["entry"] = [{"reference": f"Condition/{_primary_cond_id}"}]
        child_sections.append(section_obj)
    # Parent structuredSection — Chain #9: drop `code.text` (max=0) and use
    # title-short / display-long split.
    comp["section"] = [
        {
            "title": parent_title,
            "code": {
                "coding": [
                    {
                        "system": _JPFHIR_DOC_SECTION_SYSTEM,
                        "code": "300",
                        "display": parent_disp,
                    }
                ],
            },
            "section": child_sections,
        }
    ]
    return comp
