# ADR 履歴 (JA 概要)

> **本ファイルは日本語話者向けの ADR 索引 + 短縮要約** です。
> 元の ADR 履歴 (英語、670 行超) の canonical は
> [`adr-history.md`](adr-history.md)。以下は AD-42 から AD-70 までの
> 各判断の要点を日本語で凝縮したものです。詳細な理由・代替案・実装
> 例は英語版を参照してください。

## Part 9: 日本語 narrative localization (2026-04-13)

### AD-42: 日本語 locale のコード側単位変換

CIF は SI 単位で lab を保持 (CRP は mg/L)。日本の臨床慣習は mg/dL。
LLM に変換を依頼する代わりにコードで変換 (一貫性のため)。

### AD-43: 日本語 narrative プロンプト品質規則

- 医療用語は英語直訳でなく日本の医学用語 (例: "呼吸困難" not
  "息苦しさ")。
- 用量は "5 mg BID" のような英語省略を避け "5 mg 1 日 2 回" と書く。
- LLM プロンプトに JA 医療用語辞書を組み込む。

## Part 10: FHIR 標準準拠 + 労災 (2026-04-19)

### AD-44: enrichment は言語中立

Enricher は言語別 fork せず、CIF に構造化データのみを書き込む。
localization は出力時。

### AD-45: 職業モデル

`PatientProfile.occupation` を国別コード (JP 標準職業分類 / US
Occupation Categories) で保持。

### AD-46: 多言語 FHIR coding

`coding[].display` に英語 + 日本語両方を含める `coding[]` array で
出力 (locale-preferred coding first)。

### AD-47: Observation referenceRange + interpretation 一貫性

`interpretation` (N/H/L) は必ず `referenceRange` を持たなければなら
ない (spec 準拠)。逆も然り。

### AD-48: `procedure_name` を CIF から除去

`procedure_type` (structural) + `code` + `display lookup` で十分。
`procedure_name` の重複は drift の温床だった。

## AD-61 以降 (session 40 以降)

### AD-61: Lab ServiceRequest emission、panel-aware grouping

Lab order は panel (CBC / metabolic panel 等) 単位で ServiceRequest
を emit、傘下の Observation を `basedOn` で参照。

### AD-62: 画像 metadata-only chain + WADO-RS プレースホルダ

- ImagingStudy + Endpoint + 放射線科 DR + imaging SR の 4 resource
  emit。
- 実 pixel データは emit せず WADO-RS URL プレースホルダのみ。
- always-on Module (POST_ENCOUNTER order=90)。

### AD-63: Document narrative + 構造化イベント密度基盤

- always-on Module = `document` (Tier 1 #3)。
- `extensions["document"]` + `extensions["clinical_impressions"]` に
  ClinicalDocument / ClinicalImpressionRecord を書き込み。
- 3 FHIR builder (`_fhir_document_reference.py` /
  `_fhir_composition.py` / `_fhir_clinical_impression.py`) が emit。

### AD-64: Nursing + Outpatient + ED + CareTeam 密度基盤

- `nursing_assignment` (POST_ENCOUNTER order=94): primary nurse を
  encounter に assign。
- `triage` (POST_ENCOUNTER order=93): ED encounter に JTAS/ESI + arrival_mode + acuity_score を割り当て。
- CareTeam に primary nurse を participant[1] として追加。

### AD-65: Structural + Narrative CIF ファイル分離 (two-pass generation)

- Stage 1 (`simulate`) = structural CIF (immutable)。
- Stage 2 (`narrate`) = versioned narrative CIF
  (`cif/narratives/<version>/`)。
- Stage 3 (`export-fhir`) は両者を消費。
- canonical spec は
  [`../../clinosim/modules/output/SPEC.md`](../../clinosim/modules/output/SPEC.md)。

### AD-66 · narrative 回帰用の canonical patient profile fixture library

- `tests/fixtures/patient_profiles/<id>.yaml` に固定 fixture、
  対応 golden は `<id>.golden.json`。
- YAML 変更時は必ず golden 再生成 + 同時 commit。

### AD-67 · Severity single source of truth (disease YAML canonical、hybrid c2)

- severity 定義は disease YAML に集約、archetype_modifiers 経由で
  上書き。code side に severity 定数を持たない。

### AD-68 · archetype_modifiers 配線 (AD-67 の兄弟)

- 過去に dead YAML だった `archetype_modifiers:` を有効化。severity
  ×  archetype の cross-product を YAML で表現。

### AD-69 · DiseaseProtocol extra="forbid" (author-time silent-drop defense)

- Pydantic `extra="forbid"` で YAML の typo による silent drop を
  防止。ただし nested dict は forbid guard を回避することに注意
  (memory feedback `feedback_pydantic_extra_forbid_nested_dicts` 参照)。

### AD-70 · JP-CLINS lab コーディング: JLAC10 primary + LOINC secondary

- JP コホートの lab Observation.code.coding は JLAC10 first (JP-CLINS
  eCS の required binding)、LOINC second (国際 interop)。
- 英語版 §AD-70 に具体的な coding[] shape あり。

---

## 完全な英語版

各 AD の詳細な理由・代替案検討・実装例・関連 issue リンクは
[`adr-history.md`](adr-history.md) を参照。**JA 版と英語版に不整合を
発見した場合は、英語版が canonical**。

**技術債務ノート**: この JA 版は日本語話者向けの ADR 索引 + 短縮
要約であり、完全逐語訳ではありません。完全翻訳はフォローアップで
計画してください。
