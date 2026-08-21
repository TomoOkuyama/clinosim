# `clinosim.audit` — module 単位の内部 PR 検証ゲート

## 目的

`clinosim.audit` は各 module の audit フックを差し込むための共有
フレームワークです。`clinosim/modules/*` の各 module は
`ModuleAuditSpec` を登録でき、生成済コホートに対して自 module の
不変条件 (構造 / 臨床 / コーディング / silent-no-op) を検証します。
`clinosim audit run` CLI は module registry を走査し、PR に対して
単一の pass/fail 判定を出力します。

これは module contributor が使う **内部** PR gate です。ダウンストリーム
研究者向けの **公開** コホート評価フレームワークは
[`clinosim.eval`](../eval/README.ja.md) を参照。

## スコープ

- **In scope**: audit registry、組み込み axes (structural / clinical /
  jp_language / silent_no_op)、`AuditEngine` オーケストレータ、
  Cohort NDJSON リーダー、severity ladder、集約結果 reporter、
  `clinosim audit run` の CLI dispatcher。
- **Out of scope**: 個別の per-module audit spec (各 module が自分の
  `audit.py` を所有)、公開コホートスコアリング
  ([`clinosim.eval`](../eval/README.ja.md))、CI 連携
  (`.github/workflows/`)、*何を* audit するかの発見 (各 module が
  `ModuleAuditSpec` を通じて自身の axes を宣言)。

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

エンジン (`clinosim/audit/engine.py::AuditEngine`) はパッケージレベル
では非公開 — `cli.py` からのみ呼ばれる private orchestrator です。
プログラマチックに audit を実行したい caller は `subprocess` で CLI
を呼ぶか、`clinosim.audit.engine` から直接 import する必要があります
(signature が変わり得ることを前提)。

## 決定性

該当なし — audit は生成済コホートに対する read-only パスです。乱数
生成も壁時計参照もありません。エンジンは `(module × axis)` 行列を
`sorted(get_registered().keys())` から派生する安定順序で反復するため、
同一コホート + 同一登録 module 集合は常にバイト同一の `AuditResult`
出力を生成します。

## 依存

- `clinosim.types` — `Cohort` 隣接データ形状。
- `clinosim.audit.axes.*` — 4 つの組み込み axes。
- **逆依存なし**: `clinosim.audit` は `clinosim.modules.*` から一切
  import しません。module 側が自身の `audit.py` を import する副作用
  でフレームワークに登録し、フレームワークは `discover()` で
  `clinosim/modules/*/audit.py` を走査して発見します。

## 定数と設定

- **Severity ladder** — `Severity.BLOCKING` / `Severity.WARNING` /
  `Severity.INFO` (`types.py` 参照)。デフォルトでは `BLOCKING`
  finding のみが CLI exit code を失敗にします。`--fail-on-warning`
  で `WARNING` も失敗扱いに昇格。
- **組み込み axes** — `("structural", "jp_language", "clinical",
  "silent_no_op")` (`engine.py::_BUILTIN_AXES` 参照)。この集合外の
  axes を登録する module は自前 runner を用意する必要あり。
- **Per-module runner と cohort-level runner** — `engine.py` は
  `_PER_MODULE_RUNNERS` (`(module × axis)` ごとに 1 回呼び出し) と
  `_COHORT_RUNNERS` (cohort 1 回、reporter grid の矩形性を保つため
  synthetic `_cohort_` module 行に付随) を区別します。
- **YAML 設定なし。** 登録は純粋にコードレベル。
- CLI フラグ (`--cohort` / `--axes` / `--fail-on-warning`、出力形式
  セレクタ) は `clinosim audit run --help` に記載。

## ディレクトリ構成

```
clinosim/audit/
  __init__.py           公開 API (7 export: ModuleAuditSpec,
                        register_audit_module, Severity, AuditFinding,
                        AxisResult, AuditResult, Cohort)
  registry.py           ModuleAuditSpec dataclass、register / discover /
                        get_registered
  types.py              Severity enum、AuditFinding / AxisResult /
                        AuditResult / Cohort dataclass
  engine.py             AuditEngine — (module × axis) 行列オーケストレータ
  cli.py                `clinosim audit run` サブコマンド
  reporter.py           人間 + JSON 出力
  axes/                 組み込み axis runner
    __init__.py
    structural.py       構造整合性チェック
    clinical.py         臨床リアリズムチェック
    jp_language.py      JP 言語カバレッジチェック
    silent_no_op.py     silent-no-op 検出 (空の enricher 出力検知)
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

英語版: [`README.md`](README.md)。
