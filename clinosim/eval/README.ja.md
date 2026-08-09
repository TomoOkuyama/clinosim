# `clinosim.eval` — 公開コホート評価フレームワーク

## 目的

`clinosim.eval` は生成済コホートを 3 axis (**構造** / **臨床** /
**locale**) でスコアリングし、axis 単位の数値スコアと違反リストを
出力します。ダウンストリームの研究者 / ML エンジニアが合成データを
利用する前にグレーディングするために使用します。

[`clinosim.audit`](../audit/README.ja.md) が clinosim コントリビュータ
のみが使う内部 module-単位 PR gate であるのに対し、`clinosim.eval` は
任意のコホートに対して誰でも実行できる公開 gate です。

## スコープ

- **In scope**: 3-axis コホートスコアリング (構造 / 臨床 / locale)、
  機械可読 JSON 出力、人間可読 Markdown 出力、`clinosim eval` CLI
  サブコマンド、拡張可能な `EvalCheck` レジストリ。
- **Out of scope**: 個別 module の不変条件
  ([`clinosim.audit`](../audit/README.ja.md))、臨床事前分布に対する
  リアリズムベンチマーク (`clinosim.modules.validator`)、早期警戒
  ベースライン指標 ([`clinosim.benchmarks`](../benchmarks/README.ja.md))。

## 公開 API

```python
from clinosim.eval import (
    EvalCheck,          # per-check dataclass (id / axis / description / callable)
    EvalAxisResult,     # axis 単位集約
    EvalReport,         # 実行全体集約
    EvalEngine,         # 統括器
    Outcome,            # PASS / WARN / FAIL
    Severity,           # BLOCKING / WARNING / INFO
    add_eval_subparser, # CLI 連携
    dispatch_eval,      # CLI ハンドラ
)
```

CLI 使用例:

```bash
clinosim eval --cohort ./my-cohort --axes structural clinical --format md
```

## 依存

- `clinosim.types` — コホートレコード形状。
- 外部評価ライブラリなし (全 check は自前実装)。

## 定数と設定

- Axis 別 check の登録はコードレベル。`axes/` 配下の各ファイルで
  `EvalCheck(id="..." , axis="..." , ...)` を宣言。
- Severity ladder: `Severity.BLOCKING` / `Severity.WARNING` /
  `Severity.INFO`。
- CLI デフォルトは `clinosim eval --help` に記載。
- [`docs/eval.md`](../../docs/eval.md) と
  [`docs/eval-rules.md`](../../docs/eval-rules.md) にドキュメント化。

## ディレクトリ構成

```
clinosim/eval/
  __init__.py           公開 API
  engine.py             EvalEngine / EvalReport / EvalAxisResult / EvalCheck
  cli.py                `clinosim eval` サブコマンド
  reporter.py           JSON + Markdown emitter
  registry.py           check 登録
  axes/                 axis 別 check 登録
    __init__.py
    structural.py       構造整合性 check
    clinical.py         臨床リアリズム check
    locale.py           locale 固有 check (JP 氏名 / 住所等)
    <axis>.py
```

## テスト

```bash
pytest tests/unit -k eval -q
```

`clinosim.eval` を参照するテストファイルは約 6。

## オーナー

`maintainers@` — [`CONTRIBUTING.md`](../../CONTRIBUTING.md) 参照。
