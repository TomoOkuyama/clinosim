# `clinosim.simulator` — メインシミュレーションエンジンと CLI

## 目的

`clinosim.simulator` は集団定義と有効化モジュール集合を完全な合成
EHR コホートに変換するトップレベルエントリポイントです。集団生成、
日毎の患者軌跡、エンカウンターシミュレーション (入院 / 外来 / ED)、
検査 / vitals / 薬剤のパイプラインステップ、退院ゲートロジック、
enricher パス、出力シリアライズ、`clinosim` CLI サブコマンド (canonical は `simulate`。`generate` は
deprecation alias として残存。他: `test-disease` / `test-encounter` /
`validate` / `list-diseases` / `narrate` / `export-fhir` /
`enumerate` / `diff` / `regenerate-goldens` / `check-narratives`。
加えて、各パッケージから wire される委譲 subparser `audit` /
`dataset` / `eval` / `benchmark`) をオーケストレートします。

## スコープ

- **In scope**: エンドツーエンドのシミュレーションオーケストレー
  ション、CLI サブコマンド、疾患プロトコルロード、per-encounter
  DES-lite イベントスケジューリング、入院 / 外来 / 緊急シミュレータ、
  退院ゲートロジック、enricher オーケストレーション、per-behavior
  閾値定数、RNG seeding + memoize、構造化シミュレーションログ、
  unknown-condition ハンドリング。
- **Out of scope**: 個別疾患生理学
  ([`clinosim/modules/physiology/`](../modules/physiology/README.ja.md))、
  臨床コンテンツ作成 (`clinosim/modules/*/reference_data/`)、FHIR /
  CIF / CSV シリアライズ
  ([`clinosim/modules/output/`](../modules/output/README.ja.md))、
  audit ゲート ([`clinosim/audit/`](../audit/README.ja.md))、
  評価ゲート ([`clinosim/eval/`](../eval/README.ja.md))、プリセット
  データセットビルド ([`clinosim/dataset/`](../dataset/README.ja.md))。

## 公開 API

```python
from clinosim.simulator import (
    run_beta,                     # 集団駆動メインエントリ
    run_forced,                   # 決定的単一シナリオ実行
    run_alpha,                    # 後方互換単一患者実行
    main,                         # CLI エントリ (`clinosim` console_scripts)
    load_all_disease_protocols,   # プロトコルレジストリローダー
)
```

典型的使用:

```python
from clinosim.types.config import SimulatorConfig
from clinosim.simulator import run_beta

config = SimulatorConfig(country="JP", population=1000, seed=42, ...)
result = run_beta(config)
```

CLI 使用:

```bash
clinosim simulate -p 10000 -o ./output --format cif csv fhir
clinosim test-disease bacterial_pneumonia --archetype treatment_resistant -n 5
```

## 決定性

**AD-16 不変条件 — これはプロジェクト全体の load-bearing な決定性
保証です。** `clinosim.simulator` 内部の全乱数ドローは、渡された
`numpy.random.Generator` のサブ seed から派生しなければなりません。
呼び出し箇所での `random.random()` / `numpy.random.default_rng()`、
壁時計参照、グローバル共有 RNG の導入は review-blocker です。

具体的帰結:

- 同一の `SimulatorConfig` (country / population / seed / 日付範囲)
  + 同一の有効化モジュールレジストリに対して、`run_beta` は毎回、
  IEEE-754 semantics が一致する任意のプラットフォーム上で、バイト
  同一の CIF コホートを生成します。
- `seeding.py` はトップレベル RNG を構築し per-domain サブ RNG に
  分割する場所。`memoize.py` は患者スコープの memoize を提供
  (サブ RNG 規律の詳細ルールはメンテナメモリの
  `feedback_rng_shift_patient_cache_cascade.md` と
  `feedback_rng_neutral_additive_field.md` を参照)。
- `tests/integration/` 配下の統合テストが代表的集団の固定 seed で
  byte-diff 決定性を pin。

## 依存

- `numpy` — 渡された `numpy.random.Generator` 経由のみ (AD-16 参照)。
- `pyyaml` — 参照データロード用。
- `clinosim.types` — `SimulatorConfig` / `PatientProfile` /
  `Encounter` および他の全 CIF 形状。
- `clinosim.modules.*` — 公開レジストリ経由でロードされる疾患 /
  観察 / 薬剤 / エンカウンター / 出力 / … プロバイダ。
- `clinosim.locale` — 国別データ。
- `clinosim.codes` — emit 時のコード lookup。

## 定数と設定

- **実行時設定** は
  [`SimulatorConfig`](../types/config.py) 経由で
  `clinosim/config/*.yaml` からロード。YAML スキーマは
  [`clinosim/config/README.ja.md`](../config/README.ja.md) 参照。
- **CLI フラグデフォルト** は `cli.py` と各 `cli_*.py` サブコマンド
  ハンドラに存在。`clinosim <subcommand> --help` およびルート
  [`README.md`](../../README.md) の "Configuration" セクションで
  ドキュメント化。
- **Per-behavior 閾値** — 全運用閾値 (ADL スコアリング、MAR 投与
  ウィンドウ、日次ループタイミング、退院ゲート、ED トリアージ、
  forced-scenario ゲート、LOC 遷移、酸素療法トリガ、スケジューリング、
  LOS 形状、unknown-condition 挙動、vitals cadence) は専用の
  `_<area>_thresholds.py` モジュール (14 ファイル、下のディレクトリ
  構成参照) に抽出。単一の定数監査 sweep でシミュレーションロジック
  を歩くことなく全運用チューナブルを発見できる。

## ディレクトリ構成

シミュレーションオーケストレーション (13 ファイル):

```
clinosim/simulator/
  __init__.py            公開 API (5 export)
  cli.py                 argparse エントリ、トップレベルサブコマンド
                         dispatch
  engine.py              run_alpha / run_beta / run_forced
  daily_loop.py          engine から抽出した per-day ループ
  des_engine.py          DES-lite イベントエンジン (Issue #557: 削除
                         予定、1 リリースだけ残置)
  hospital_ops.py        病院運用オーケストレーション
  inpatient.py           入院エンカウンターシミュレータ
  outpatient.py          外来エンカウンターシミュレータ
  emergency.py           ED エンカウンターシミュレータ
  discharge_gate.py      退院タイミング判定ロジック
  discharge_rx.py        退院時処方ビルダー
  enrichers.py           post-records enricher パス
  unknown_condition.py   疾患プロトコルを持たない慢性疾患のハンドリング
```

パイプライン (3 ファイル):

```
  lab_pipeline.py        検査オーダー → サンプル → 結果パイプライン
  vitals_pipeline.py     vitals cadence + キャプチャパイプライン
  medication_pipeline.py 薬剤オーダー → 投与パイプライン
```

決定性とインストルメンテーション (4 ファイル):

```
  seeding.py             トップレベル RNG 構築 + サブ seed 分割
  memoize.py             患者スコープ memoize
  log.py                 構造化シミュレーションログ
  diff.py                テスト byte-diff 比較用 CIF diff ヘルパー
```

ヘルパー (2 ファイル):

```
  helpers.py             共有ヘルパー、load_all_disease_protocols 含む
  enumerate.py           患者 / イベント列挙ヘルパー
```

CLI サブコマンドハンドラ (7 ファイル):

```
  cli_common.py          共有 CLI ユーティリティ
  cli_enumerate.py       `clinosim enumerate` サブコマンド
  cli_export_fhir.py     `clinosim export-fhir` サブコマンド
  cli_narrate.py         `clinosim narrate` サブコマンド
  cli_regenerate.py      `clinosim regenerate-goldens` サブコマンド
  cli_test_disease.py    `clinosim test-disease` サブコマンド
  cli_test_encounter.py  `clinosim test-encounter` サブコマンド
```

抽出済閾値定数 (14 ファイル、`_<area>_thresholds.py`):

```
  _adl_thresholds.py
  _daily_io_thresholds.py
  _daily_loop_thresholds.py
  _discharge_gate_thresholds.py
  _ed_thresholds.py
  _forced_scenario_thresholds.py
  _loc_thresholds.py
  _mar_thresholds.py
  _outpatient_thresholds.py
  _oxygen_therapy_thresholds.py
  _scheduling_thresholds.py
  _stay_thresholds.py
  _unknown_condition_thresholds.py
  _vitals_schedule_thresholds.py
```

## テスト

```bash
pytest tests/unit -k simulator -q          # 単体テスト
pytest tests/integration -q                # エンドツーエンド + byte-diff
```

`clinosim.simulator` を参照するテストファイルは約 85。統合テストは
固定 seed でのフル走行 byte-diff 決定性を網羅。単体テストは個別
パイプラインステージ、退院ゲートエッジケース、閾値定数挙動が中心。

## オーナー

`maintainers@` — [`CONTRIBUTING.md`](../../CONTRIBUTING.md) 参照。

英語版: [`README.md`](README.md)。
