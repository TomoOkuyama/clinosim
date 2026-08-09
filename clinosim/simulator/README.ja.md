# `clinosim.simulator` — メインシミュレーションエンジン + CLI

## 目的

`clinosim.simulator` は population 定義と有効化された module 群を、
完全な合成 EHR コホートに変換する最上位エントリポイントです。
population 生成、日次患者トラジェクトリ、encounter シミュレーション
(inpatient / outpatient / ED)、enricher pass、出力シリアライズ、
`clinosim` CLI を統括します。

## スコープ

- **In scope**: エンドツーエンドのシミュレーション統括、CLI サブコマンド
  (`generate` / `test-disease` / `validate` / `list-diseases` / `dataset`
  / `eval`)、disease protocol ロード、encounter 単位の DES-lite イベント
  スケジューリング、退院判定ロジック、enricher 統括。
- **Out of scope**: 個別疾患の生理モデル
  ([`clinosim/modules/physiology/` (English)](../modules/physiology/README.md))、
  臨床コンテンツの authoring (`clinosim/modules/*/reference_data/`)、
  FHIR / CIF / CSV シリアライズ
  ([`clinosim/modules/output/` (English)](../modules/output/README.md))、
  監査ゲート ([`clinosim/audit/`](../audit/README.ja.md))、
  評価ゲート ([`clinosim/eval/`](../eval/README.ja.md))。

## 公開 API

```python
from clinosim.simulator import run_alpha, run_beta, run_forced, main

# メインの population 駆動シミュレーション (推奨エントリ)。
result = run_beta(config)

# テスト用の決定的単一シナリオ実行。
result = run_forced(scenario)

# 後方互換の単一患者実行。
result = run_alpha(config)

# `console_scripts` (`clinosim`) に紐付く CLI エントリ。
main()
```

`load_all_disease_protocols` と非推奨エイリアス
`_load_all_disease_protocols` (1 リリース間だけ維持、Issue #557) も
エクスポートされており、完全な実行を経ずにロード済 protocol registry
を取得するために利用できます。

## 依存

- `numpy` (呼び出し側から渡される `numpy.random.Generator` 経由でのみ使用
  — AD-16 決定性不変条件を参照)。
- `pyyaml` — reference-data ロード用。
- `clinosim.types` — `SimulatorConfig` / `PatientProfile` / `Encounter` 等。
- `clinosim.modules.*` — disease / observation / medication / encounter /
  output / … を公開レジストリ経由でロード。
- `clinosim.locale` — 国別データ。

## 定数と設定

- 実行時設定は [`SimulatorConfig`](../types/config.py) を通じて
  `clinosim/config/*.yaml` からロード。YAML スキーマは
  [`clinosim/config/README.ja.md`](../config/README.ja.md) を参照。
- CLI フラグのデフォルトは `cli.py` にインライン記述、ルート
  [`README.ja.md`](../../README.ja.md) の「設定」節に説明あり。
- 決定性不変条件 (AD-16): あらゆる乱数ドローは、渡された
  `numpy.random.Generator` のサブシードから派生させなければならない。
  `random.random()` や大域共有 RNG の導入は review-blocker。

## ディレクトリ構成

```
clinosim/simulator/
  __init__.py            公開 API
  cli.py                 argparse エントリ、トップレベルサブコマンド
  engine.py              run_alpha / run_beta / run_forced
  inpatient.py           入院 encounter simulator
  outpatient.py          外来 encounter simulator
  emergency.py           ED encounter simulator
  daily_loop.py          engine から抽出された日次ループ
  des_engine.py          (旧 discrete-event engine — 削除予定)
  discharge_rx.py        退院時処方 builder
  discharge_gate.py      退院タイミング判定ロジック
  enrichers.py           post_records enricher pass
  medication_pipeline.py 薬剤イベントパイプライン
  helpers.py             共有ヘルパー (RNG、protocol ロード)
  memoize.py             患者スコープメモ化
  log.py                 構造化シミュレーションログ
  cli_narrate.py         ナラティブ生成 CLI ヘルパー
  cli_common.py          CLI 共通ユーティリティ
  enumerate.py           患者・イベント列挙ヘルパー
```

## テスト

```bash
pytest tests/unit -k simulator -q                       # ユニットテスト (~10 s)
pytest tests/integration -q                             # E2E
```

`clinosim.simulator` を参照するテストファイルは約 77。integration
テストは pinned seed での完全実行 byte-diff 決定性をカバーします。

## オーナー

`maintainers@` — [`CONTRIBUTING.md`](../../CONTRIBUTING.md) 参照。
