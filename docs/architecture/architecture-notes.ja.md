# アーキテクチャノート (JA 概要)

> **本ファイルは日本語話者向けの概要 + セクションガイド** です。
> 元のアーキテクチャノート (英語、860 行超) の canonical は
> [`architecture-notes.md`](architecture-notes.md)。以下は正典の
> セクション構造を保ちつつ、各 ADR / モジュール判断を日本語で
> 凝縮したものです。具体的な YAML スキーマ・コード例・API 詳細は
> 英語版を参照してください。

---

## 6.1 コードシステムモジュール (`clinosim/codes/`)

**問題**: 元々は `clinosim/locale/jp/terminology_diagnosis.yaml` の
ように locale 配下に terminology が散在。ICD/LOINC/RxNorm/JLAC10 の
ような国際コードが複数 locale に重複していた。

**解決**: `clinosim/codes/` に単一集約。CIF はコードのみ保持
(`code` + `system`)、display は出力時に `lookup(system, code, lang)`
で解決。詳細は
[`../../clinosim/codes/README.ja.md`](../../clinosim/codes/README.ja.md)。

## 6.2 FHIR Bulk Data Export NDJSON (AD-31)

- Bulk Data Access spec 準拠 (`_type` per file、1 行 1 resource)。
- `manifest.json` に `transactionTime` + `output[]` を記録。
- `_type` fanout: `fhir_r4/Patient.ndjson`, `Encounter.ndjson`,
  `Observation.ndjson`, … の per-ResourceType ファイル。

## 6.3 Snapshot 日付セマンティクス (AD-32)

- `--end` は snapshot 日、未来のライフイベントは生成しない。
- 退院予定日が snapshot 以降の入院患者は `discharge_datetime=None`
  で `Encounter.status = "in-progress"`、labs / vitals / MAR は
  snapshot 日まで partial。
- **現在入院中の患者を含む** リアリスティックな EHR snapshot を生成。

## 6.4 Hospital Configuration-Driven Layout (AD-34)

- 病院形状 (ベッド数 / ward 構成 / スタッフ roster) は
  `clinosim/config/hospital_*.yaml` から決定。
- ward / department / OR / ED / clinic の配置は YAML 駆動。
- 詳細は
  [`../../clinosim/config/README.ja.md`](../../clinosim/config/README.ja.md)
  参照。

## 6.5 更新モジュール一覧

- 執筆時点のスナップショット。canonical な一覧は
  [`../../MODULES.md`](../../MODULES.md)。現在 33 モジュール。

## 6.6 現実的な vital sign 測定パターン

- 検温 / 血圧 / SpO2 の cadence は encounter type × 診療科ごとに定義
  (`clinosim/modules/monitoring/`)。
- ICU vs 一般病棟で頻度が大きく異なる。
- vitals は physiology から導出、noise 付き。

## 6.7 NEWS2 / early warning vital data

- NEWS2 (英国 Royal College of Physicians の early warning score) を
  vital sign から自動計算。
- 詳細スコアリング表は英語版 §6.7 参照。

## 6.8 更新 ADR 一覧 (Part 6 追加分)

- AD-31 (Bulk NDJSON) / AD-32 (Snapshot) / AD-34 (Hospital config)
  など。詳細な条項本文は
  [`adr-history.ja.md`](adr-history.ja.md) 参照。

## 6.9 住民識別子 & 保険番号 (AD-54)

- JP: マイナンバー / 国民健康保険番号 / 被保険者番号。
- `clinosim/modules/identity/` (opt-in) で生成、FHIR `Coverage` +
  `Patient.identifier` に emit。
- `SimulatorConfig.modules["identity"]` で ON/OFF。

## 6.10 EHR データ拡充分割 — Base vs Module (AD-55)

- **Base** = always-on、CIF 中核型に組み込み (`Patient` demographics、
  `Encounter` 基本情報)。
- **opt-in Module** = `SimulatorConfig.modules` でゲート
  (`identity`、`immunization`、`family_history` 等)。
- **always-on Module = near-essential clinical cascade**
  (`device`、`hai`、`antibiotic`、`imaging` 等 — 上流 extensions の
  存在を前提に clinically coherent な拡張を出す)。

## 6.11 拡張性基盤 — Phase 0 (AD-56)

- 3 レジストリ経由の拡張:
  - `register_enricher()` — post-population / post-encounter /
    post-records パス。
  - `register_output_adapter()` — 新規出力形式。
  - `register_bundle_builder()` — FHIR bundle level のリソース emit。
- コア dispatch を直接編集しない。詳細は
  [`../CONTRIBUTING-modules.ja.md`](../CONTRIBUTING-modules.ja.md)
  参照。

## 7. FHIR DocumentReference 経由の臨床文書

- 5 文書種別 (Admission H&P / Discharge Summary / Death Note /
  Operative Note / Procedure Note) を Stage 2 (`narrate`) で生成。
- `docStatus = "final" | "preliminary"` で LLM vs テンプレートを
  区別。
- 詳細は [`../clinical_documents.ja.md`](../clinical_documents.ja.md)。

## 8. LLM サービスアーキテクチャ: pluggable providers + YAML prompts

- `clinosim/modules/llm_service/`:
  - `engine.py` — LLMService、LLMTaskType、PatientSummary。
  - `providers/` — Ollama / Bedrock / Mock / Sakura Cloud。
  - `prompts/` — 言語別 / タスク別 YAML テンプレート。
  - `cache.py` — SHA256 disk cache (system + user + model キー)。
- 詳細は英語版 §8 + 各 provider の実装参照。

---

## 完全な英語版

上記は骨子。**具体的な YAML スキーマ・コード例・API 詳細・cascade
拡張の概念モデル・provider インターフェース定義等は
[`architecture-notes.md`](architecture-notes.md) を参照** してくださ
い。本 JA 版と英語版に不整合を発見した場合は、英語版が canonical。

**技術債務ノート**: この JA 版は日本語話者向けの構造化された概要
+ 主要判断のサマリー。完全逐語訳が必要なら、フォローアップで計画
してください。
