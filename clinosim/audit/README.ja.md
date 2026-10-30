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
    Severity,               # FAIL / WARN / INFO
    AuditFinding,           # audit レポートの 1 行
    AxisResult,             # axis 単位の集約
    AuditResult,            # 実行全体の集約
    Cohort,                 # 遅延評価 NDJSON コホートリーダー
)
```

Module は import 時に audit spec を登録します (`ModuleAuditSpec` の
`name` 以外のフィールドは全て任意。module は opt-in する軸の分だけ
埋める):

```python
# clinosim/modules/<name>/audit.py
from clinosim.audit import register_audit_module, ModuleAuditSpec

register_audit_module(ModuleAuditSpec(
    name="<name>",
    canonical_constants={...},     # silent_no_op: 許可キー集合
    yaml_keys_to_validate={...},   # silent_no_op: yaml -> キーパス
    lift_firing_proof=...,         # silent_no_op: 引数なし proof factory
    structural_obs_codes={...},    # structural: 検査対象コード
    clinical_acceptance={...},     # clinical: アクセプタンス閾値
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
登録順 (`discover()` が `clinosim/modules/*/audit.py` をソート順に
走査する順序) で反復するため、同一コホート + 同一登録 module 集合は
常に同じ `AuditResult` を生成します。

## 依存

- `pyyaml` — `silent_no_op` が `yaml_keys_to_validate` の YAML を
  ロード。
- `clinosim.audit.axes.*` — 4 つの組み込み axes。
- 登録は副作用: module 側が自身の `audit.py` を import する時点で
  フレームワークに登録し、フレームワークは `discover()` で
  `clinosim/modules/*/audit.py` を走査して発見します。フレームワーク
  中核 (`registry.py` / `types.py` / `engine.py`) は
  `clinosim.modules.*` を import しませんが、`axes/clinical.py` は
  import します (`clinosim.codes` / `clinosim.modules.antibiotic` /
  `clinosim.modules.hai` / `clinosim.modules.output.fhir_r4` の定数)。

## 定数と設定

- **Severity ladder** — `Severity.FAIL` / `Severity.WARN` /
  `Severity.INFO` (`types.py` 参照)。`AxisResult` は最悪の finding に
  より `FAIL` / `WARN` / `PASS` (finding も info も無ければ `N/A`)。
  `clinosim audit run` / `smoke` は全体ステータスが `FAIL` のときのみ
  exit 1。`WARN` は exit code を失敗にしない。
- **組み込み axes** — `("structural", "jp_language", "clinical",
  "silent_no_op")` (`engine.py::_BUILTIN_AXES` 参照)。エンジンが実行
  できる axes はこれのみで、`--axis` で部分集合を選択。
- **Per-module runner と cohort-level runner** — `engine.py` は
  `_PER_MODULE_RUNNERS` (`structural` / `clinical` / `silent_no_op`。
  `(module × axis)` ごとに 1 回呼び出し) と `_COHORT_RUNNERS`
  (`jp_language`。cohort 1 回、reporter grid の矩形性を保つため
  synthetic `_cohort_` module 行に付随) を区別します。
- **YAML 設定なし。** 登録は純粋にコードレベル。
- CLI: `clinosim audit run -d/--cohort-dir DIR [--module NAME]...
  [--axis AXIS]... [--report PATH]` (Markdown を stdout に、
  `--report` 指定時はファイルにも出力)。`clinosim audit smoke -d DIR`
  は `silent_no_op` のみ。`clinosim audit list` は登録 module と
  そのチェックを表示。

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
  cli.py                `clinosim audit run` / `smoke` / `list` サブコマンド
  reporter.py           Markdown レポート (render_markdown / write_markdown)
  axes/                 組み込み axis runner
    __init__.py
    structural.py       構造整合性チェック
    clinical.py         臨床リアリズムチェック
    jp_language.py      JP 言語カバレッジチェック
    silent_no_op.py     silent-no-op 検出 (canonical constants
                        クロスチェック + lift-firing proof)
```

## テスト

```bash
pytest tests/unit -k audit -q
```

`clinosim.audit` を参照するテストファイルは約 20。module 作者が従う
ワークフローは
[`docs/CONTRIBUTING-modules.md`](../../docs/CONTRIBUTING-modules.ja.md)
「PR 検証ガイド」を参照。

## オーナー

`maintainers@` — [`CONTRIBUTING.md`](../../CONTRIBUTING.ja.md) 参照。

英語版: [`README.md`](README.md)。
