# `fhir_r4/documents/` — Composition + DocumentReference FHIR R4 builder

## 概要

臨床文書ファミリの FHIR R4 resource 全てを emit: `Composition`
(構造化文書 — section は AD-65 Stage 2 narrative pass が populate
した `ClinicalDocument.narrative.sections` 由来)、標準臨床文書用の
`DocumentReference` (narrative text への metadata pointer)、および
JP-eCheckup 事業者健診レポート用の特化 `DocumentReference` builder。

Composition の dispatch は **format-type 駆動**:
`format_type == "composition"` の `ClinicalDocument` のみが
Composition を emit、残りは `DocumentReference` を emit する。
JP-CLINS Composition variant (DISCHARGE_SUMMARY / REFERRAL_NOTE /
eCheckup) は各々 [`jp_clins/`](jp_clins/) に template 特化 builder を
持つ (`composition.py` から dispatch)。`imaging_report.py` は
`RadiologyReport` ごとに section 構造の画像検査報告書 Composition を
emit し、`referral_orgs.py` は JP 診療情報提供書 (LOINC 57133-1) の
外部紹介元 / 紹介先 `Organization` を供給する。

## Scope

- **In scope**: `_bb_compositions` dispatch (`record.documents` を
  `format_type == "composition"` で walk、`narrative` が `None`
  な stub は Stage 2 pass 未実行として空 Composition を出さず警告で
  skip);`_build_composition` root builder + `_build_composition_generic`
  fallback;`jp_clins/` の JP-CLINS 特化 builder 3 種
  (`_build_jp_clins_discharge_summary_composition`,
  `_build_jp_clins_referral_note_composition`,
  `_build_jp_echeckup_general_composition`) と `composition.py` 内の
  JP 死亡診断書 (LOINC 64297-5) / 死亡退院サマリー builder;
  `_bb_imaging_report_compositions` (`imaging_report.py`);
  `_localize_section_title` + `_section_title_from_section_display`
  (title は `clinosim/modules/document/reference_data/section_catalog.yaml`
  から解決);
  `_bb_document_references` + `_build_dref_from_clinical_doc` +
  `_build_prior_doc_chain` (`DocumentReference` builder と prior 文書
  chain);`_bb_document_references_checkup` + `_build_dref`
  (eCheckup 特化 `DocumentReference`);`_fhir_instant_or_empty`
  (安全な ISO-instant 変換)。
- **Out of scope**: `ClinicalDocument` stub emission
  ([`clinosim.modules.document`](../../../document/README.ja.md));
  narrative content 生成
  ([`clinosim.modules.document.narrative`](../../../document/narrative/README.ja.md));
  narrative version 管理 (CIF writer が担当);
  `ClinicalImpression` (emit は
  [`../conditions/clinical_impression.py`](../conditions/clinical_impression.py))。

## Public API

各 builder は親 facade (`_BUNDLE_BUILDERS` in
[`../builder.py`](../builder.py)) に登録済み。

```python
from clinosim.modules.output.fhir_r4.documents.composition import (
    _bb_compositions,                            # bundle-builder (ctx: BundleContext)
    _build_composition,                          # root Composition builder (特化 builder に dispatch)
    _build_composition_generic,                  # 汎用 fallback
    _build_jp_clins_discharge_summary_composition,   # 定義は jp_clins/discharge_summary.py
    _build_jp_clins_referral_note_composition,       # 定義は jp_clins/referral_note.py
    _build_jp_echeckup_general_composition,          # 定義は jp_clins/echeckup_general.py
    _localize_section_title,                     # (section_title, lang) -> section_catalog.yaml で localised title
    _section_title_from_section_display,
)
from clinosim.modules.output.fhir_r4.documents.documents import (
    _bb_document_references,                     # 標準 DocumentReference bundle-builder
    _build_dref_from_clinical_doc,               # record 別 DocumentReference
    _build_prior_doc_chain,                      # prior 文書 chain 解決
)
from clinosim.modules.output.fhir_r4.documents.document_reference_checkup import (
    _bb_document_references_checkup,             # eCheckup 特化 bundle-builder
    _build_dref,                                 # eCheckup record 別 DocumentReference
    _fhir_instant_or_empty,                      # 安全な ISO-instant 変換 (documents.py にも定義)
)
from clinosim.modules.output.fhir_r4.documents.imaging_report import _bb_imaging_report_compositions
```

## 決定論

該当なし — 各 builder は入力 CIF record + merge 済み narrative の
pure 関数。Stage 2 narrative pass は template path で決定論的
(byte-identical)、LLM path では semantic-check gate が byte-diff を
代替する
([`document/narrative`](../../../document/narrative/README.ja.md) 参照)。

## 依存

- `clinosim.modules._shared` — `is_jp`, `resolve_lang`。
- `clinosim.modules.output.fhir_r4.lib.common` — `BundleContext`,
  `_escape_html`, `derive_meta_last_updated`, `to_fhir_instant`。
  `lib.ids` — opaque id。
- `clinosim.modules.output.fhir_r4.conditions.primary_ref` —
  Composition section から参照する encounter 別 primary Condition
  用の `primary_condition_ref`。
- `clinosim.modules.document` — `COMPOSITION_ID_PREFIX`、
  `DOC_REFERENCE_ID_PREFIX`。`clinosim.modules.document.narrative.registry`。
- `clinosim.codes` — 文書種別 LOINC lookup。
- 文書は (`CIFReader` で merge 済みの) CIF dict として読み、
  `clinosim.types` の class は import しない。

## 定数と設定

- **format-type dispatch** (`_bb_compositions`) — `format_type
  == "composition"` record のみが Composition を emit。
  `format_type == "free_text"` record は代わりに
  `_bb_document_references` 経由で `DocumentReference` を emit。
- **JP-CLINS Composition variant** — `_build_composition` 内で
  文書種別 LOINC で dispatch:
  - 死亡退院サマリー task type → death discharge-summary builder
    (全 locale、最初に判定)。
  - JP-CLINS 出力のみ: `18842-5` DISCHARGE_SUMMARY → JP-CLINS
    discharge-summary builder、`57133-1` REFERRAL_NOTE → JP-CLINS
    referral-note builder、`53576-5` eCheckup (JP 事業者健診) →
    JP-eCheckup general builder、`64297-5` → JP 死亡診断書 builder。
  - その他文書種別 (ADMISSION_HP `34117-2`,
    ADMISSION_NURSING_ASSESSMENT `78390-2`,
    NURSING_DISCHARGE_SUMMARY `34745-0`,
    OUTPATIENT_SOAP `34131-3`, ED_NOTE `34878-9`) → 汎用 builder。
- **Section title 言語** — `_localize_section_title` は言語別 display
  title を `document/reference_data/section_catalog.yaml` から解決。
  catalog に無い場合、JP は slug をそのまま返し US は humanise する。
- **Prior-doc chain** — `_build_prior_doc_chain` が `raw_docs` を
  walk して `DocumentReference.relatesTo` chain を構築 (progress
  note ↔ discharge summary、ADMISSION_HP ↔ DISCHARGE_SUMMARY 連鎖)。
- **Stub skip 契約** (AD-65): `narrative is None` の
  `ClinicalDocument` は必ず警告付き skip — 空 Composition emit は
  FHIR R4 `Composition.section` `.text` cardinality 違反であり、
  読めない文書が silent に ship されるため。

## ディレクトリ構造

```
clinosim/modules/output/fhir_r4/documents/
  __init__.py                        namespace stub (builder は ../builder.py / ../lib/inline_bb.py が import)
  composition.py                     _bb_compositions + _build_composition dispatch + 汎用 + 死亡診断書 / 死亡退院サマリー builder (~1,200 LOC)
  jp_clins/                          JP-CLINS profile 別 builder (discharge_summary / referral_note / echeckup_general)
  documents.py                       _bb_document_references + prior-doc chain
  document_reference_checkup.py      _bb_document_references_checkup (JP-eCheckup)
  imaging_report.py                  _bb_imaging_report_compositions (画像検査報告書 Composition、Issue #818)
  referral_orgs.py                   JP 診療情報提供書の外部紹介元 / 紹介先 Organization catalog
```

## テスト

```bash
pytest tests/unit -k "composition or document_reference or checkup" -q
pytest tests/integration -k "document_chain" -q
clinosim audit run -d <cohort_dir> --module document
```

`document` AD-60 audit plug-in
([`../../../document/audit.py`](../../../document/audit.py)) の
49-check `lift_firing_proof` が本ファミリの load-bearing gate。
canonical ID prefix (`DOC_REFERENCE_ID_PREFIX`,
`COMPOSITION_ID_PREFIX`, `CLINICAL_IMPRESSION_ID_PREFIX`,
`ALLERGY_ID_PREFIX`, `CARE_TEAM_ID_PREFIX`)、LOINC 54094-8
dispatch gate、CIF → FHIR no-drop matrix (Section 3.4) を
cross-verify する。

## Ownership

`maintainers@` — 詳細は
[`CONTRIBUTING.md`](../../../../../CONTRIBUTING.ja.md)。

英語版: [`README.md`](README.md)。
