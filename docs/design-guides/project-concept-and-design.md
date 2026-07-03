# clinosim Project Concept & Design — キャッチアップ文書

**Status:** Active(2026-07-03、session 32 で確立)
**Audience:** 新規参加の開発者/実装 AI(Opus 4.7 等)が最初に読む「このプロジェクトは
何で、どう作られているか」の全体像。規則集は
[`implementation-rules.md`](implementation-rules.md)、詳細アーキテクチャは `DESIGN.md`(ADR 全集)。

---

## 1. プロジェクトコンセプト(ゴール)

**clinosim は高品質な EHR/EMR サンプルデータセットの生成器**である。
評価軸は常に **データ品質・臨床的整合性・データのリアリティ**。

ユーザー要求として確定している 9 項目(2026-07-02 グランドデザインレビューで検証済):

1. 高品質な EHR/EMR データセット生成がゴール(研究・開発・製品デモ用のサンプルデータ)
2. 出力は多フォーマット構想、**まず FHIR R4**(Bulk Data NDJSON)。将来 SS-MIX2 / CSV / HL7 v2
3. **人口動態 → 外来/疾患シナリオ → 病院訪問イベント発火 → 検査/問診/処置 →
   コンディション変化** という event-driven の forward simulation でデータが生まれる
4. メインパイプライン + モジュール構成。**モジュール責任分解を明確に**、モジュール追加
   だけで新しい種類のデータを生成できる
5. 中間表現 **CIF**(Clinical Intermediate Format)は **構造化 CIF + ナラティブ CIF の 2 層**。
   両方から FHIR を生成する
6. **ナラティブは差し替え可能**: template 生成 → 後から Bedrock / local LLM で再生成 →
   FHIR 再作成、が独立に回せる(narrative の version 化)
7. ナラティブは情報タイプ別 prompt を持ち、患者 profile / シナリオ / 構造化 CIF を入力と
   する**統一インターフェース**経由で生成する
8. **データドリブン**: バイタル値・コード等の静的定義を Python 内に書かない(YAML 駆動)
9. **多国対応**: US default + JP 実装済。国固有情報(マイナンバー、保険、診療慣習)は
   YAML/JSON で定義し、他国も追加可能な構造

## 2. パイプライン全体像

```
 population(人口動態・世帯)                        Layer 0-1: reference YAML
   └→ scenario 発火(disease 32種 / encounter 46種)   (disease/encounter protocols,
        └→ encounter simulation(inpatient/ED/outpatient) locale, codes)
             ├ physiology state 遷移(daily loop)
             ├ orders / labs / vitals / MAR / procedures
             ├ POST_ENCOUNTER enrichers(device→hai→antibiotic→imaging→triage→nursing→document)
             └→ POST_RECORDS enrichers(nursing flowsheet, immunization, …)
   ↓
 ★ CIF(唯一のシミュレーション出力、AD-17)
   ├ cif/structural/patients/<enc>.json   … Stage 1、構造化データ、immutable
   └ cif/narratives/<version>/documents/… … Stage 2、narrative、version 差替え可能(AD-65)
   ↓
 format adapters(CIF だけを読む)
   ├ FHIR R4 NDJSON(_fhir_* builder 群、registry 登録制)← 現在の主出力
   └ CSV / (将来: SS-MIX2, HL7 v2)
```

- **CLI 3-stage(AD-37)**: `clinosim generate`(→ structural CIF)→ `clinosim narrate
  --provider template|mock|ollama|bedrock`(→ narratives/<version>/)→
  `clinosim export-fhir --narrative-version X`。これがコンセプト 6(差し替え)の実体。
- **決定性(AD-16)**: 全乱数は階層 sub-seed。同 seed = byte 同一出力(wall-clock 残存
  2 フィールドを除く — determinism chain で解消予定)。

## 3. レイヤと責任分解

| Layer | 内容 | 場所 |
|---|---|---|
| 0 | 国際コード体系(LOINC/ICD/RxNorm/JLAC10…、EN-first) | `clinosim/codes/` |
| 1 | 参照データ YAML(疾患・検査・locale・病院設定) | `modules/*/reference_data/`, `locale/`, `config/` |
| 2 | loader(cached + fail-loud validation) | 各 module 内 |
| 3 | CIF 生成(simulator + 30 modules) | `simulator/`, `modules/` |
| 4 | 出力 adapter(FHIR builders ほか) | `modules/output/` |

- **module は 30 個**(`MODULES.md` が地図)。always-on(臨床カスケード上必須:device →
  hai → antibiotic / imaging / document / triage / nursing_assignment 等)と opt-in がある。
- module 間依存は README の Dependencies 宣言 + `types/` / `codes/` / `locale/` のみ。
  CIF への書込みは `extensions[<module>]`(typed field 追加は Base のみ)。
- **拡張は 3 つの registry**(AD-56/58): FHIR resource 追加 = `register_bundle_builder`、
  出力 format 追加 = `register_output_adapter`、生成 pass 追加 = `register_enricher`。
  dispatch 本体は編集しない。

## 4. ナラティブ生成の設計(コンセプト 5-7 の実体)

```
 Stage 1(simulation 内, document module):
   ClinicalDocument stub のみ生成(metadata + author + encounter binding, narrative=None)

 Stage 2(post-simulation, narrate CLI):
   NarrativePass(ABC; walk = (doc_type, language) → sorted patients = LLM cache 最適)
     ├ TemplateNarrativePass … generator = TemplateNarrativeGenerator
     └ LLMNarrativePass      … generator = LLMNarrativeGenerator
           └ apply_replacement_strategy(spec.stage2_strategy)
                ├ template_only  → template 出力そのまま
                └ template_seed  → spec.llm_enabled_sections の section だけ
                                   template 文を seed に LLM が書換え(戦略 D+B)
                     └ LLMService.complete_prompt()  ← LLM 呼出しの唯一の seam(AD-11)
                          ├ prompt: llm_service/prompts/{en,ja}/*.yaml(AD-40)
                          ├ retry + PromptCache(disk, prompt-hash)
                          └ NarrativeCache(in-memory, 臨床キー+seed hash)
```

- **入力の統一 IF** = `NarrativeContext`(patient / encounter / labs / vitals / meds /
  diagnoses / disease_protocol / severity / archetype / day_index / narrative_spine /
  materialized_facts)。Stage 2 が structural CIF から組み立てる(chain 1a で実 schema 配線済)。
- **generator 契約** = `NarrativeGenerator` Protocol(`types/document.py`)、Pass へ注入。
- **document type** は `document_type_specs.yaml`(YAML 駆動、LOINC / sections /
  encounter_types_supported / generation_frequency / stage2_strategy)。現在 9 doc type
  (H&P、progress、discharge、看護 3 種(3 交代 shift note 含む)、外来 SOAP、ED 2 種)。
- **検証**: template/mock = golden byte-diff(AD-66)。実 LLM = `check-narratives`
  (semantic check 5 軸: 構造 / facts_used / 禁止 pattern / 期待 phrase / 数値)。
- **実 LLM 生成は別サーバで実行する運用**(2026-07-03 決定)。手順書 =
  `docs/design-notes/2026-07-03-remote-llm-narrative-workflow.md`。

## 5. 多国対応の設計(コンセプト 9)

- `codes/`(国際標準、locale 非依存、EN 必須)と `locale/<country>/`(名前・住所・
  基準値・code_mapping)を厳密分離(AD-35)。
- CIF は言語中立(code のみ、AD-30)。表示は出力時に `code_lookup(system, code, lang)`。
- 国判定は `is_jp()` / `resolve_lang()`、国→コード体系は `system_key_for()`(単一 source)。
- JP 固有: 保険/マイナンバー(identity module, opt-in)、要介護度、JLAC10/YJ/K-code、
  JP Core 準拠 FHIR。**US 出力に日本語 0 / JP 出力は全 display 日本語**が監査される。
- 新しい国 = locale dir + codes への言語キー追加 + demographics YAML で追加可能な構造。

## 6. 品質保証の仕組み(このプロジェクトの特徴)

| 仕組み | 役割 |
|---|---|
| `pytest -m unit / integration / e2e` | 通常のテスト 3 層(1000+ / 264 / 35) |
| `pytest -m regression`(opt-in) | 6 canonical patient profile の narrative goldens byte-diff(template + llm-mock、AD-66) |
| byte-diff | refactor PR の gate(FHIR NDJSON + narratives sha256 一致) |
| `clinosim audit run`(AD-60) | 4 軸監査: structural / clinical / jp_language / **silent_no_op**(lift_firing_proof = 「機能が実際に発火した」証明) |
| `check-narratives` | 実 LLM narrative の semantic gate |
| adversarial review | PR ごとに 5-lens レビュー(finding は実証必須)→ fix → merge の chain 文化 |

**silent no-op(動いているように見えて実は発火していない)がこのプロジェクト最大の敵**。
歴史的事故(PR-90 / J5 / C-1)から fail-loud validation・canonical constants・発火 counter
の 3 層防御が全域に張られている。詳細 = `implementation-rules.md` §9。

## 7. 現在地とロードマップ(2026-07-03 時点)

- **version**: v0.2。US p=10k / JP p=5k の production cohort が audit 全 PASS で生成可能。
  32 疾患 + 46 外来/ED 条件、30 modules、FHIR R4 で 25+ resource type を emit。
- **直近の完了**(session 31-32): 共通ロジック統一(#133)、nursing 3 交代(#134)、
  **N-chain = narrative IF 統一**(#135)、**context 配線**(#136)、
  **LLM golden + semantic check + リモート実行支援**(#137)。
- **現在フェーズ = β-JP-1**(Document & Event Density Master Plan の第 3 phase、
  `docs/design-notes/2026-06-30-tier1-document-and-event-density-master-plan.md` が正):
  - 済: LLM 基盤一式(あとは別サーバでの実 LLM 実行・prompt 品質)
  - 残: **厚労省 4 帳票**(入院診療計画書 / 看護必要度 D 表 / 栄養管理計画書 /
    リハ計画書、QuestionnaireResponse active 化)+ 多職種 CareTeam
- **その後の chain**(優先順、`docs/design-notes/2026-07-02-grand-design-review-and-roadmap.md` §4):
  determinism chain(wall-clock 全除去)→ AD-30 chain(display-in-CIF 残骸除去)→
  display-dict → codes YAML 移行 → β-2(手術/麻酔)→ γ/δ/ε → SS-MIX2。
- **deferred の正**: `TODO.md` の各 "deferred" section(chain ごとに文脈付き entry あり)。
  作業開始前に `.session-resume-prompt.md`(最新セッションの引き継ぎ)を必ず読む。

## 8. 用語ミニ辞書

| 用語 | 意味 |
|---|---|
| CIF | Clinical Intermediate Format。シミュレーションの唯一の出力(structural + narrative 2 層) |
| chain | 1 テーマの作業単位(spec → 実装 → adv review → merge、通常 1 PR) |
| adv-1 / 5-lens | merge 前の adversarial review(silent no-op / data unification / FHIR·JP Core / determinism / spec 整合の 5 観点) |
| golden | canonical patient profile の期待出力 JSON(byte-diff regression 用) |
| DQR | Data Quality Review(構造/臨床整合/JP 言語の 3 軸レビュー文書、`docs/reviews/`) |
| lift_firing_proof | audit の silent_no_op 軸で「機能が発火した」ことを等式で証明する仕組み |
| PR-90 / J5 / C-1 | 歴史的 silent-no-op 事故の名前(implementation-rules.md §9 参照) |
| scenario spine / facts | narrative 生成用に structural CIF から抽出した事実タグ群(hallucination 防止の基礎) |
