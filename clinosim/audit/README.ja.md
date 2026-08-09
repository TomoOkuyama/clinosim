# `clinosim.audit` — module 単位の内部 PR 検証ゲート

## 目的

`clinosim.audit` は各 module の audit フックを差し込むための共有
フレームワークです。`clinosim/modules/*` の各 module は
`ModuleAuditSpec` を登録でき、生成済コホートに対して自 module の
不変条件 (構造 / 臨床 / コーディング) を検証します。`clinosim audit
run` CLI は登録済 spec を集約し、PR に対して単一の pass/fail 判定を
出力します。

これは module contributor が使う **内部** PR gate です。ダウンストリーム
研究者向けの **公開** コホート評価フレームワークは
[`clinosim.eval`](../eval/README.ja.md) を参照。

## スコープ

- **In scope**: audit registry、axis executor、cohort reader、severity
  ladder、集約結果 printer、`clinosim audit run` の CLI dispatcher。
- **Out of scope**: 個別の per-module audit spec (各 module が自分の
  `audit.py` を所有)、公開コホートスコアリング
  ([`clinosim.eval`](../eval/README.ja.md))、CI 連携 (`.github/workflows/`)。

## 公開 API

```python
from clinosim.audit import (
    ModuleAuditSpec,        # per-module 契約
    register_audit_module,  # modules/<name>/audit.py から呼び出し
    Severity,               # BLOCKING / WARNING / INFO
    AuditFinding,           # audit レポートの 1 行
    AxisResult,             # axis 単位の集約
    AuditResult,            # 実行全体の集約
    Cohort,                 # 遅延評価 NDJSON コホートリーダー
)
```

Module は import 時に audit spec を登録します:

```python
# clinosim/modules/<name>/audit.py
from clinosim.audit import register_audit_module, ModuleAuditSpec, Severity

register_audit_module(ModuleAuditSpec(
    name="<name>",
    axes=[...],
    severity_default=Severity.BLOCKING,
))
```

## 依存

- `clinosim.types` — `Cohort` 隣接データ形状。
- 個別 `clinosim/modules/*/audit.py` が本パッケージに登録するだけで、
  本パッケージから module を import することはない (逆依存なし)。

## 定数と設定

- Severity ladder (`Severity.BLOCKING` / `Severity.WARNING` /
  `Severity.INFO`) — `types.py` 参照。
- YAML 設定なし。登録は純粋にコードレベル。
- CLI フラグ (`--cohort` / `--axes` / `--fail-on-warning`) は
  `clinosim audit run --help` に記載。

## ディレクトリ構成

```
clinosim/audit/
  __init__.py           公開 API
  registry.py           module 登録 + spec 検索
  types.py              Cohort / Severity / AuditFinding / AxisResult / AuditResult
  executor.py           1 axis 実行、AxisResult 生成
  cli.py                `clinosim audit run` サブコマンド
  reporter.py           人間 + JSON 出力
  axes/                 module 間で共有される axis executor
    __init__.py
    <axis>.py           共有 axis 実装 (構造 / 臨床 / …)
```

## テスト

```bash
pytest tests/unit -k audit -q
```

`clinosim.audit` を参照するテストファイルは約 19。module 作者が従う
ワークフローは
[`docs/CONTRIBUTING-modules.md`](../../docs/CONTRIBUTING-modules.md)
「PR 検証ガイド」を参照。

## オーナー

`maintainers@` — [`CONTRIBUTING.md`](../../CONTRIBUTING.md) 参照。
