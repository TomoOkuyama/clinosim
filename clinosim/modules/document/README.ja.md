# `clinosim.modules.document` — 臨床文書 stub + ClinicalImpression

## 概要

Tier 1 #3 α-min-1 always-on AD-55 module。POST_ENCOUNTER enricher
(`document_enricher`) が **stub の `ClinicalDocument` record**
(admission H&P / progress note / discharge summary /
operative note / procedure note / referral note / nurse note /
ED_NOTE / ED_TRIAGE_NOTE / HEALTH_CHECKUP_REPORT 等) と、
inpatient / ICU / rehab encounter に対する `ClinicalImpression`
日次 record を emit する。各 stub は `narrative=None`。narrative content
は 2-pass の [`narrative`](narrative/README.ja.md) subpackage が Stage 2
pass で populate する (AD-65)。全 consumer が import する canonical
FHIR resource ID prefix も所有する。

## Scope

- **In scope**: `document_enricher` (POST_ENCOUNTER order=95、
  always-on)、`DocumentTypeSpec` と spec loader / filter
  ([`narrative/registry`](narrative/registry.py) 由来)、
  `clinosim.types.document` からの document-type + format-type
  再 export、canonical ID prefix 定数 (`DOC_REFERENCE_ID_PREFIX =
  "doc-"`, `COMPOSITION_ID_PREFIX = "comp-"`, `ALLERGY_ID_PREFIX =
  "allergy-"`, `CLINICAL_IMPRESSION_ID_PREFIX = "ci-"`)、
  `NURSING_LOINCS` frozenset (AD-65 Bug B — 看護師 author の文書は
  `attending_physician_id` ではなく `encounter.primary_nurse_id` に
  dispatch)、reference data loader
  ([`reference_data_loaders.py`](reference_data_loaders.py) —
  `load_physical_exam_findings`, `load_discharge_instructions` に
  6-layer validator、他に `load_hpi_pertinent_negatives`,
  `load_chief_complaint_variant_rules`, `load_bedside_procedure_codes`,
  `load_nursing_content`)、per-encounter document-type dispatch
  (`_pick_document_author`, `_referral_note_fires`,
  `_enc_type_value`, `_enc_status_value`, `_compute_los_days`,
  `_PLANNERS` per generation frequency + `_build_documents`)。
- **In scope (audit)**: [`audit.py`](audit.py) — 5 番目の
  per-module AD-60 plug-in (hai / antibiotic / order / imaging の次)。
  49-check `lift_firing_proof` が canonical 定数
  (`DOC_REFERENCE_ID_PREFIX` / `COMPOSITION_ID_PREFIX` /
  `ALLERGY_ID_PREFIX` / `CLINICAL_IMPRESSION_ID_PREFIX` /
  `CARE_TEAM_ID_PREFIX`)、emission count、ID-prefix invariant、
  CIF → FHIR no-drop matrix (Section 3.4)、LOINC 54094-8 dispatch
  gate、AD-65 Bug A の `us_admission_hp_zero_ja_chars` invariant、
  α-min-3 の 3-shift 拡張を guard。`clinical_acceptance` は
  per-encounter doc count + ClinicalImpression 日次 emission +
  AllergyIntolerance 分布 + CareTeam / triage / nursing / outpatient
  / ED の per-encounter target (計 13 key) をカバー。
- **Out of scope**: narrative content 組立 / template rendering
  ([`narrative`](narrative/README.ja.md) subpackage が Stage 2 pass と
  LLM/template dispatch を所有)、LLM gateway
  ([`llm_service`](../llm_service/README.ja.md))、FHIR
  `DocumentReference` / `Composition` / `ClinicalImpression` /
  `CareTeam` emission
  ([`output/fhir_r4/documents/`](../output/fhir_r4/documents/README.ja.md))。

## Public API

```python
from clinosim.modules.document import (
    # 型 (clinosim.types.document から再 export)
    DocumentType,
    FormatType,
    NarrativeContext,
    NarrativeOutput,

    # Registry
    DocumentTypeSpec,
    load_document_type_specs,       # () -> list[DocumentTypeSpec]
    # clinosim.modules.document.narrative.registry.document_loinc(doc_type) -> str
    #   the document type's LOINC code (its one definition; Issue #2344)
    specs_for_country,              # (country) -> list[DocumentTypeSpec]
    specs_for_encounter_type,       # (encounter_type) -> list[DocumentTypeSpec]

    # Reference-data loader
    load_physical_exam_findings,    # () -> dict (@lru_cache, 6-layer validated)
    load_discharge_instructions,    # () -> dict (@lru_cache, 6-layer validated)
    load_hpi_pertinent_negatives,   # () -> {disease: [HpiPertinentNegative]} (@lru_cache)

    # Canonical ID prefix
    DOC_REFERENCE_ID_PREFIX,        # "doc-"
    COMPOSITION_ID_PREFIX,          # "comp-"
    ALLERGY_ID_PREFIX,              # "allergy-"
    CLINICAL_IMPRESSION_ID_PREFIX,  # "ci-"

    # Author dispatch
    NURSING_LOINCS,                 # frozenset (AD-65 Bug B)
)
from clinosim.modules.document.engine import document_enricher
```

## 決定論

- `document_enricher` は乱数を引かない。唯一の確率的に見える選択
  (適格な退院で referral note を出すか、`REFERRAL_NOTE_FIRE_RATE =
  0.20`) は `sha256(f"{encounter_id}::{patient_id}")` の安定 threshold
  (`_referral_note_fires`) で決まり、RNG stream を消費しない (AD-16)。
- サブ seed オフセット `0x444F` (`"DO"`) が
  [`clinosim/seeding.py`](../../seeding.py) の
  `ENRICHER_SEED_OFFSETS["document"]` に登録されているが、読む code は
  無い。
- 2-pass 契約 (AD-65): `document_enricher` は `narrative=None` の
  stub を生成する。同 simulation pass で narrative を populate すると
  Stage 2 differ が silent no-op になる。契約は
  `tests/unit/test_document_enricher_stub_only.py`
  (`test_enricher_produces_stub_with_narrative_none`) で guard。

## 依存

- `clinosim.modules._shared` — `get_attr_or_key`。
- `clinosim.countries` — `lang_for`、`clinosim.locale.i18n` — `t`。
- `clinosim.codes.loinc` — `loinc_display`、
  `clinosim.codes.snomed_concepts` — `SURGICAL_PROCEDURE`。
- `clinosim.modules.document.narrative.registry` — spec loader +
  filter + `document_loinc`。
- `clinosim.modules.document.reference_data_loaders` — physical
  exam finding + discharge instruction + 他の cached loader。
- `clinosim.datafiles` — `load_data_yaml`, `load_validated_yaml`、
  `clinosim.reference_data` — `load_reference_yaml`。
- `clinosim.types.document` — `DocumentType`, `FormatType`,
  `NarrativeContext`, `NarrativeOutput`。
- `clinosim.types.clinical` — `ClinicalDocument`,
  `ClinicalImpressionRecord`。
- `clinosim.types.encounter` — encounter 型 + `primary_nurse_id`
  / `attending_physician_id` field。
- `pydantic` — reference-data YAML model。
- `audit.py` のみ: `clinosim.audit.registry` (AD-60 audit 登録)、
  `clinosim.modules.output.cif_reader`
  (`resolve_current_narrative_dir`)、`clinosim.modules.output.cif_writer`、
  `clinosim.modules.output.fhir_r4.*` (`CARE_TEAM_ID_PREFIX` と
  CIF → FHIR no-drop matrix 用の `_bb_*` bundle builder)、
  `clinosim.modules.triage.audit` (`_build_triage_severity_proof`)、
  `clinosim.modules.document.narrative.passes`
  (`TemplateNarrativePass`)。

## 定数と設定

- **Canonical ID prefix** (writer 所有、全 FHIR builder が import):
  `DOC_REFERENCE_ID_PREFIX`, `COMPOSITION_ID_PREFIX`,
  `ALLERGY_ID_PREFIX`, `CLINICAL_IMPRESSION_ID_PREFIX`。
  `output/fhir_r4/documents/` (`documents.py`, `composition.py`) と
  `output/fhir_r4/conditions/` (`allergy_intolerance.py`,
  `clinical_impression.py`) の FHIR builder がこれらを
  `derive_opaque_id` に渡す。
- **`NURSING_LOINCS`** (frozenset、`engine.py` の
  `_load_nursing_loincs` 経由で load) — 看護師 author 文書の LOINC
  code。`_pick_document_author` は文書 LOINC が本集合に含まれるとき
  `encounter.primary_nurse_id` に dispatch、含まれない場合は
  `attending_physician_id` (AD-65 Bug B fix)。
- **Document-type spec**
  ([`reference_data/document_type_specs.yaml`](reference_data/document_type_specs.yaml))
  — 文書種別ごとの registry entry (`clinosim/types/document.py` の
  `DocumentTypeSpec`)。`loinc_code`、`format_type` (`"free_text"` /
  `"composition"` / `"questionnaire_response"`)、
  `countries_supported`、`generation_frequency`、composition section、
  `stage2_strategy`、`encounter_types_supported` allowlist (AD-64
  α-min-2 — 空 tuple は「全 encounter type と一致」を意味するため、
  inpatient 限定文書の spec は必ず `[inpatient, icu, rehab_inpatient]`
  を明示して outpatient / ED へ leak しないようにする) を保持。author
  dispatch は spec field ではなく LOINC (`NURSING_LOINCS`) で決まる。
- **Reference-data YAML model** (Task 5 pattern) —
  `reference_data_loaders.py` の Pydantic model `PhysicalExamFindings`、
  `DischargeInstructions`、`ChiefComplaintVariants`、
  `BedsideProcedureCodes`、`NursingContent` が loader の返却前に
  empty-top / missing-key / per-bucket / required-key / per-entry
  required-field を検査。YAML typo は load 時に raise。
- **Chronic SOAP + hedging** reference YAML
  (`chronic_soap_templates.yaml`, `hedging_phrases.yaml`) は
  [`narrative`](narrative/README.ja.md) 側 submodule から read されるが、
  本 package の `reference_data/` に配置されている。

## ディレクトリ構造

```
clinosim/modules/document/
  __init__.py                        公開 API + canonical ID prefix
  engine.py                          document_enricher + doc-stub helper + NURSING_LOINCS
  reference_data_loaders.py          load_physical_exam_findings + load_discharge_instructions (6-layer) + 他の cached loader
  audit.py                           AD-60 audit plug-in #5 — 49-check lift_firing_proof
  reference_data/
    document_type_specs.yaml         文書種別 registry (ed_note は authored_at: period_end で ED 受診の終了時点に記載し、その時点で存在したものだけを書く。nutrition_care_plan は入院8時間後、初日の食事オーダー後に作成し、食事内容と補給方法は有効な食事オーダーに従う: narrative/_progress_course.py diet_order_at)
    section_catalog.yaml             Composition section slug catalog (narrative/registry.py, composition.py)
    physical_exam_findings.yaml      per-disease PE 所見 (baseline + 新生児セット + override)
    clinosim-discharge-instruction.yaml  退院指導 (load_discharge_instructions、旧 discharge_instructions.yaml、#1862)。各項目に `applies_when` 条件 (性別・喫煙/飲酒状況・疾患群・退院処方薬、該当薬は `{drugs}` に展開) を付けられ、renderers/_resolvers.py resolve_discharge_instructions が評価し重複文を除く (#3254)
    clinosim-nursing-content.yaml    急性疾患別 (看護診断・目標と OP/TP/EP の看護計画・教育) と慢性 ICD-10 併存疾患別の看護記録内容 (load_nursing_content)
    clinosim-discharge-instruction.yaml  退院指導 (load_discharge_instructions、旧 discharge_instructions.yaml、#1862)。各項目に `applies_when` 条件 (性別・喫煙/飲酒状況・疾患群・退院処方薬、該当薬は `{drugs}` に展開、最終クレアチニンが AKI 定義を満たす `aki_at_discharge` (#3281)) を付けられ、renderers/_resolvers.py resolve_discharge_instructions が評価し重複文を除く (#3254)
    clinosim-nursing-content.yaml    急性疾患 / 慢性 ICD-10 別の看護記録内容 (load_nursing_content)
    cc-pe-consistency-keywords.yaml  主訴 ↔ 身体所見の整合 rail (narrative/_narrative_utils.py)
    clinosim-discharge-instruction.yaml  退院指導。項目は `applies_when` (性別・喫煙・飲酒・疾患・退院薬、および喘息増悪のピークフロー・長期管理薬・コントロール評価文の `age_min` / `age_max`; Issue #3264) で絞れる
    asthma-control-instruments.yaml  年齢別の喘息コントロール評価 (12 歳以上 ACT、4-11 歳 C-ACT、4 歳未満は保護者への症状聴取; Issue #3264, GINA 2024)
    chronic-med-class-hints.yaml     慢性疾患 assessment の薬効分類 hint (narrative/renderers/section_builders/outpatient_soap.py)
    disease_exam.yaml                疾患ごとの入院時身体所見 (疾患が及ぶ系統の所見、英語・日本語)、AVPU による意識の句、心房細動の脈の規則、急性期脳卒中の局所神経症状と NIHSS の範囲、分娩入院の分娩様式別の産科所見 (分娩処置の終了前は分娩前、終了後は産褥の所見、Issue #3403) (load_disease_exam)
    ed_note_admitted.yaml            ED 経由入院の ED 記録: 来院時バイタルの成人の判定範囲とバイタルを述べる所見語 (来院時の測定値と矛盾する day-0 身体所見の句は書かない)、トリアージの来院手段と照合する救急搬入の HPI 表現 (load_ed_note_admitted)
    hpi_pertinent_negatives.yaml     HPI pertinent negative、疾患ごとに言語別の文言と否定する症状語 (hpi_pertinent_negatives(disease_id, lang)、英語にフォールバック)。主訴の症状を否定する negative は出力しない
    bedside_procedure_codes.yaml     bedside procedure code (load_bedside_procedure_codes)
    death_cause_chain.yaml           死亡診断書の死因の連鎖: 直接死因になりうる合併症・終末期経過の機序・検査値で定義する発症時刻・続発コード・影響を及ぼした傷病名の区分 (load_death_cause_chain)
    death_course.yaml                死亡退院サマリーの死亡時状況と経過: 蘇生処置を行わない方針のコード・死亡時の生命維持・心肺蘇生の判定・列挙数・日/週の境界 (load_death_course)
    narrative_extras_whitelists.yaml narrative extra-context whitelist (narrative/_extra_context_builder.py)
    ja_only_fallback_sections.yaml   US H&P の JA 文字 audit 対象外 section (audit.py)
    chronic_soap_templates.yaml      慢性疾患 SOAP note template (受診の診断コードの項目、指示ではなく所見を記載)
    visit_reason_soap.yaml           受診理由別の外来 SOAP: 受診種別、種別ごとの S/O/A/P 文、バイタル異常の所見と計画、接種記録、乳幼児健診の発達と保健指導 (narrative/_visit_reason.py)
    interval_events.yaml             外来 SOAP が前回受診以降の事象として記載する入院・救急受診 (narrative/_interval_events.py)
    (プランの次回受診は narrative/_next_visit.py が読む)
    outpatient_results.yaml          外来 SOAP の検査結果: 過去の検査を引く項目、CKD G 分類、スクリーニングスコア (narrative/_outpatient_results.py)
    hedging_phrases.yaml             narrative hedging phrase pool
    drug_plan_priority.yaml          経過記録の計画の薬剤の優先順位・単回投与の頻度・一覧の上限 (narrative/_medication_plan.py)
    progress_vitals.yaml             経過記録のバイタル要約: 経過の閾値・自己申告可能な AVPU・表示する極値・疼痛部位 (narrative/renderers/_composers.py)
    progress_exam.yaml               経過記録の身体所見をバイタルに合わせる: バイタルの判定範囲 (小児の収縮期血圧の下限は PALS の低血圧閾値)・バイタルを述べる語・異常値に加える所見・経過の項目・後句を落とした文の文末形 (terminal_forms)・患者別の下限の上書き (COPD の SpO2 下限 88 %)・「現在」の記述は最新値で判定 (narrative/_progress_exam.py)
    progress_course.yaml             経過記録の経過: 処置後の処置種別・主要検査の件数・退院調整の期間 (narrative/_progress_course.py)
    hospital_course.yaml             退院時サマリーの入院経過: 治療薬の一覧の上限・異常検査値の対応薬・薬剤変更の上限 (narrative/_hospital_course.py)
  narrative/                         narrative subpackage (Stage 2 pipeline) — narrative/README.md 参照
```

## Enricher 配線

[`clinosim/simulator/enrichers.py`](../../simulator/enrichers.py)
の `register_builtin_enrichers` で登録:

- `name="document"`, `stage=POST_ENCOUNTER`, `order=95`,
  `enabled=lambda c: True`。POST_ENCOUNTER 最後 (imaging=90、
  triage=93、nursing_assignment=94 の後) に走り、全上流 extension
  slot を消費できる。
- `audit.py` は import 時に AD-60 audit framework に登録される。

## Output surface (consumers)

| Consumer | 場所 | 役割 |
| --- | --- | --- |
| Enricher registry | [`clinosim/simulator/enrichers.py`](../../simulator/enrichers.py) `register_builtin_enrichers` | POST_ENCOUNTER order=95 登録。 |
| Audit registry | [`clinosim/modules/document/audit.py`](audit.py) | AD-60 audit plug-in — 49-check lift_firing_proof + clinical_acceptance。 |
| Narrative Stage 2 | [`clinosim/modules/document/narrative/passes.py`](narrative/passes.py) | 本モジュールが emit した全 stub に `narrative.sections` を populate。 |
| FHIR document builder | [`clinosim/modules/output/fhir_r4/documents/`](../output/fhir_r4/documents/README.ja.md) | stub + populate 済み narrative から `DocumentReference` / `Composition` / `ClinicalImpression` を emit。 |

## テスト

```bash
pytest tests/unit -k "document" -q
pytest tests/integration -k "document_chain" -q
clinosim audit run -d <cohort_dir> --module document_chain
```

Coverage は大量 — `tests/unit -k document` で per-spec / per-encounter
/ per-country test を検索、end-to-end CIF → FHIR chain guard は
`tests/integration/test_document_chain.py`。

## Ownership

`maintainers@` — 詳細は
[`CONTRIBUTING.md`](../../../CONTRIBUTING.ja.md)。

英語版: [`README.md`](README.md)。
