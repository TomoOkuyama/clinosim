# `clinosim.eval` — 公開コホート評価フレームワーク

## 目的

`clinosim.eval` は生成済コホートを 3 軸 (**structural** /
**clinical** / **locale**) + オプションで国固有軸 (現状 JP 向け
`jp_clins_lab_compliance`) に対してスコア化します。軸ごとの数値
スコアと違反リストを生成し、ダウンストリーム研究者・ML エンジニア
が合成データを消費前に評価するために使います。

[`clinosim.audit`](../audit/README.ja.md) が clinosim コントリビュ
ータのみが呼び出す内部 per-module PR gate であるのに対し、
`clinosim.eval` は誰でも任意のコホートに対して実行できる公開 gate
です。Synthea 等のサードパーティジェネレータの出力も (組み込み
`synthea_adapter` 経由で) 評価可能。

## スコープ

- **In scope**: 3 軸コホートスコアリング (structural / clinical /
  locale) — PASS / WARN / FAIL の重み付き outcome、JSON + Markdown
  レポート renderer、`clinosim eval` CLI サブコマンド、
  Synthea → clinosim NDJSON アダプタ、国別オプション軸。
- **Out of scope**: 個別 module の不変条件
  ([`clinosim.audit`](../audit/README.ja.md))、臨床事前分布に対する
  リアリズムベンチマーク (`clinosim.modules.validator`)、早期警戒
  ベースライン指標
  ([`clinosim.benchmarks`](../benchmarks/README.ja.md))、シミュレータ
  そのものの実行 ([`clinosim.simulator`](../simulator/README.ja.md))。

## 公開 API

```python
from clinosim.eval import (
    EvalCheck,          # per-check dataclass (id / axis / outcome / weight …)
    EvalAxisResult,     # 軸単位集約 (checks + score)
    EvalReport,         # 実行全体集約 (axis results + overall score)
    EvalEngine,         # オーケストレータ
    Outcome,            # PASS / WARN / FAIL (StrEnum)
    Severity,           # BLOCKING / WARNING / INFO
    add_eval_subparser, # CLI 配線
    dispatch_eval,      # CLI ハンドラ (プロセス exit code を返す)
)
```

CLI 使用:

```bash
clinosim eval --cohort ./my-cohort --format md
```

`axes/` 配下の各軸は素の関数を公開:

```python
def run(cohort: Cohort, country: str) -> list[EvalCheck]
```

エンジンは axis score = `100 × Σ(合格重み) / Σ(全重み)` を計算
(WARN は 0.5 合格として扱う)、overall score は軸スコアの算術平均。
コホートレイアウトは `<root>/<country>/fhir_r4/` (多国籍) と
`<root>/fhir_r4/` (単一国フラット) の両方を直接読み込み可能。

## 決定性

該当なし — 評価は生成済コホートに対する read-only パスです。乱数
生成なし、壁時計参照はレポートメタデータに刻印する
`EvalReport.generated_at` のみ。同一コホート入力に対して軸ごとの
チェック集合と outcome はバイト同一。実行間 diff はタイムスタンプ
のみ。

## 依存

- `clinosim.audit.types.Cohort` — NDJSON コホートリーダーを再利用
  (両パッケージが同じ lazy-reader 実装を共有)。
- それ以外は標準ライブラリのみ (`json` / `pathlib` / `datetime` /
  `enum` / `dataclasses`)。

## 定数と設定

- **Outcome ladder** — `Outcome.PASS` / `Outcome.WARN` /
  `Outcome.FAIL` (StrEnum)。スコアリング: PASS = weight、WARN =
  0.5 × weight、FAIL = 0。
- **Severity ladder** — `Severity.BLOCKING` / `Severity.WARNING` /
  `Severity.INFO`。CI ゲート判定用に `EvalCheck` に付随。
- **Axis 発見** — エンジンは 4 つの組み込み軸モジュール
  (`structural` / `clinical` / `locale` + JP 固有の
  `jp_clins_lab_compliance`) を直接 import。新規軸追加は
  `axes/<name>.py` を書いて `engine.py` で配線。
- **国別発火** — `jp_clins_lab_compliance` は `country == "JP"` の
  ときのみ実行。
- CLI デフォルトは `clinosim eval --help`。
  [`docs/eval.md`](../../docs/eval.md) と
  [`docs/eval-rules.md`](../../docs/eval-rules.md) 参照。

## ディレクトリ構成

```
clinosim/eval/
  __init__.py                     公開 API (8 export)
  engine.py                       Outcome / Severity / EvalCheck /
                                  EvalAxisResult / EvalReport / EvalEngine
  cli.py                          `clinosim eval` サブコマンド
                                  (add_eval_subparser / dispatch_eval)
  report.py                       JSON + Markdown emitter
  synthea_adapter.py              Synthea (Bundle per patient) →
                                  clinosim NDJSON レイアウト変換 (P1-10)
  axes/                           軸別チェック runner
    __init__.py
    structural.py                 構造整合性チェック
    clinical.py                   臨床リアリズムチェック
    locale.py                     locale 固有チェック (JP 氏名 /
                                  住所 / コーディング、US 相当)
    jp_clins_lab_compliance.py    JP-CLINS 検体検査コンプライアンス軸
                                  (country=JP でのみ起動)
```

## テスト

```bash
pytest tests/unit -k eval -q
```

`clinosim.eval` を参照するテストファイルは 6。軸スコアリング、
Synthea アダプタラウンドトリップ、CLI dispatch を網羅。

## オーナー

`maintainers@` — [`CONTRIBUTING.md`](../../CONTRIBUTING.md) 参照。

英語版: [`README.md`](README.md)。
