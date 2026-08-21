# clinosim 設計ガイドライン (JA 概要)

> **本ファイルは日本語話者向けの概要 + セクションガイド** です。
> 元の設計原則ドキュメント (英語、1000 行超) の canonical は
> [`design-principles.md`](design-principles.md)。以下は正典の構造を
> 保ちつつ主要な設計判断を日本語で凝縮したものです。詳細な例
> (コードスニペット・データ構造・cache キー設計・enricher フロー) は
> 英語版を参照してください。

---

## 1. 大原則: Realism Above All (リアリズム最優先)

clinosim の最高優先度は **リアリズム**。あらゆる設計判断・パラメータ
選択・モジュール挙動は 1 つの問いに対して評価される: 「**これは本物
の病院で起こるか?**」

- 数値の妥当性でなく臨床的整合性を基準とする。
- 統計分布は臨床経験と文献に裏付けられていなければならない。
- 「ありそうな数字」より「実際にそう発生するプロセス」をシミュレート
  する (state-transition ではなく physiology-driven)。
- 生成される全事実 (診断コード / 薬剤 / 検査 / 転帰) は妥当性を
  失わないよう相互に整合していなければならない。

## 2. モジュラーアーキテクチャ原則

- 単一責務: 各モジュールは 1 つの臨床/構造概念を所有する
  (`physiology` / `disease` / `encounter` / `output` …)。
- 依存方向: `types` は最下層、`modules/*` は横方向、`simulator` /
  `output` が最上位。逆依存禁止 (循環回避)。
- 拡張は **レジストリ経由** (AD-56): `register_enricher`,
  `register_output_adapter`, `register_bundle_builder`。コア dispatch
  を直接編集しない。
- YAML 駆動: 疾患・症例・reference range・code mapping はデータ
  ファイル。新規追加時のコード編集を最小化。

## 2. (別章) LLM 統合アーキテクチャ

- LLM 呼び出しは **`clinosim/modules/llm_service` に集約** (AD-11)。
  ビジネスロジック側から直接プロバイダ SDK を触らない。
- 3 モード: `template` (LLM 不使用、決定的) / `llm` (実 LLM) /
  `none` (テキスト空)。
- コスト制御: SHA256 プロンプトキャッシュ (system + user + model)。
  同一プロンプト再実行は無料。
- 決定性の分離: Stage 1 (シミュレーション) は完全決定的、Stage 2
  (narrate) のみ LLM プロバイダ非決定性を許容。
- narrative 圧縮パターン: 「入院初日 / 3 日目 / 7 日目 / 退院日」
  など key day のみ LLM 生成、中間日はテンプレート補完。
  詳細例は英語版 §2 の "Progress Note reuse" ブロック参照。

## 3. 2 つのシミュレーションモード

- **run_alpha**: 単一患者 (backward-compat)。
- **run_beta**: 集団駆動シミュレーション (メインエントリ)。
- **run_forced**: 特定 disease / archetype を強制発火するテスト用。

## 3. (別章) Population-Driven Simulation アーキテクチャ

- Layer 1 (Person Records): 世帯構造 + demographic + baseline chronic。
  ライフイベント (誕生 / 死亡 / 転居) を月次で駆動。
- Layer 2 (Patient Activation): 有病者を疾患プロトコルにマッチさせ
  encounter を生成。
- Layer 3 (Encounter Simulation): 日次ループで physiology + 診断 +
  order + procedure + MAR を進行。
- Layer 4 (Output): CIF → format adapters (FHIR / CSV / …)。

## 4. フォルダ構造

canonical レイアウトは
[`module-architecture.ja.md`](module-architecture.ja.md) 参照。要点:

- `clinosim/codes/` = 国際コードシステム (locale 非依存)。
- `clinosim/locale/` = 国別データ (氏名 / 住所 / reference range …)。
- `clinosim/modules/` = 33 機能モジュール、各々に README。
- `clinosim/simulator/` = トップレベルオーケストレーション + CLI。
- `clinosim/types/` = dataclass / StrEnum / TypedDict (依存グラフ
  最下層)。

### 各モジュールの README テンプレート

- Purpose / Inputs / Outputs / Dependencies / Confirmed
  Specifications / Open Questions / Design Notes の 7 セクション。
- 詳細スキーマは英語版 §4 の "Module Name / Purpose / Inputs / …"
  ブロック参照。

## 5. モジュール間 Interface 規約

- **CIF は唯一のシミュレーション出力** (AD-17)。format adapter は
  CIF のみを読み、シミュレーション内部を触らない。
- **Code is the truth** (AD-30): CIF は code のみ保持、display は
  出力時 `code_lookup()` で解決。
- **決定性** (AD-16): 同一 seed + 同一 config = byte-identical
  出力。`random.random()` 禁止、全乱数は sub-seed 由来の
  `numpy.random.Generator`。
- **Per-order lab RNG isolation** (AD-59): YAML 編集が無関係患者の
  cohort をシフトさせない。
- **Snapshot semantics** (AD-32): `--end` は snapshot 日、未来イベン
  ト生成なし、in-progress encounter を許容。

## 4. (別章) 設計ワークフロー

新規機能追加時の流れ:

1. spec → design note (`docs/design-notes/`)
2. 実装 + 単体テスト
3. `clinosim audit run` gate (AD-60): structural / clinical /
   jp_language / silent_no_op 4 軸
4. `scripts/reproduce.sh` gate (決定性)
5. PR review

## 5. 命名規則

- Python: PEP8 準拠 (`snake_case` 関数 / 変数、`PascalCase` クラス、
  `UPPER_SNAKE` 定数)。
- File: `snake_case.py`、YAML は `kebab-case.yaml` または
  `snake_case.yaml`。
- Test: `tests/unit/test_<module>.py`、`tests/integration/`、
  `tests/e2e/`。
- ADR: `AD-<番号>` として `docs/architecture/adr-history.md` に記録。

## Part 6 — アーキテクチャ更新 (v0.1-beta 以降)

英語版 §Part 6 以降は個別の architectural update を時系列で記録
します (AD-42 以降の localization / FHIR 準拠 / JP-CLINS 対応 /
JP-eCheckup 等)。日本語話者は [`adr-history.md`](adr-history.md) を
併読することを推奨。

---

## 完全な英語版

上記は骨子。**具体的なコード例・データ構造 dump・cache キー設計・
enricher 実装例・schema 検証コード等は
[`design-principles.md`](design-principles.md) を参照** してください。
本 JA 版と英語版に不整合を発見した場合は、英語版が canonical。JA 版
を修正すべきです。

**技術債務ノート**: この JA 版は完全な逐語訳ではなく、日本語話者
向けの構造化された概要 + 主要判断のサマリーです。将来的に完全翻訳
を希望する場合は、フォローアップとして計画してください。
