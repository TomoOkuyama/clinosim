# engine.py 診断テーブル YAML 駆動化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `clinosim/modules/diagnosis/engine.py` にハードコードされた 3 つの診断テーブル定数を単一 reference_data YAML へ移し、表示名を `codes.lookup` 解決にする (YAML 駆動原則 + AD-30 準拠)。

**Architecture:** 現 Python 定数 (`DIFFERENTIALS` / `DIAGNOSIS_PROGRESSION` / `LR_TABLE`) を機械生成スクリプトで `reference_data/builtin_differentials.yaml` へ値同一に書き出し、engine.py 側はインポート時に 1 度ロードして同名の module-level 変数を populate する。`name` フィールドはデータから削除し、`DiagnosisCandidate.display_name` と `get_current_diagnosis_code` の返り値を `codes.lookup("icd-10-cm", code, "en")` で解決する。

**Tech Stack:** Python 3.11+, PyYAML (`yaml.safe_load`), pytest, ruff/mypy。

## Global Constraints

- 決定論 (AD-16): RNG は一切触らない。YAML ロードは import 時 1 回、`sort_keys=False` で挿入順保存 (正規化後ソートのタイブレークを現状一致させる)。
- 値同一性: priors / LR 値 / progression の `(threshold, code)` を現 Python 定数と byte/value identical に保つ。golden / e2e 出力は不変でなければならない。
- AD-30: CIF はコードのみ保持。display はハードコードせず `codes.lookup` で出力時解決。
- 内部表示は英語固定・`icd-10-cm` システム (engine は country コンテキストを持たない)。
- コメント/docstring は英語、行長 100、ruff フォーマット、mypy strict。
- スコープ外: disease YAML (`modules/disease/reference_data/*.yaml`) の `diagnostic` セクションは変更しない。LR/prior/progression の臨床的見直しはしない (値完全保存)。
- git: master から branch。commit 末尾に下記トレーラ。push/PR/merge はユーザー指示時のみ。

```
Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01PAVRbWqciawmAyKriJFsL1
```

---

### Task 1: 現定数から YAML を機械生成し値同一性を検証

現 engine.py の 3 定数 (まだハードコード状態) を読み、`name` を削った YAML を生成して
コミットする。engine.py 本体はこのタスクではまだ変更しない (中間状態でも動作する)。

**Files:**
- Create: `clinosim/modules/diagnosis/reference_data/builtin_differentials.yaml` (生成物)
- (一時, 非コミット) Create: `/tmp/gen_builtin_differentials.py` — 生成 + 検証スクリプト

**Interfaces:**
- Consumes: 現 `engine.DIFFERENTIALS` (`list[{disease,icd,name,prior}]`), `engine.DIAGNOSIS_PROGRESSION` (`list[(float,str,str)]`), `engine.LR_TABLE` (`dict[str,dict[str,dict[str,float]]]`)。
- Produces: `builtin_differentials.yaml` with top-level keys `differentials` (`{id: [{disease,icd,prior}]}`), `diagnosis_progression` (`{id: [[float,str]]}`), `lr_table` (`{finding: {dx: {pos,neg}}}`)。

- [ ] **Step 1: 生成 + 検証スクリプトを書く**

```python
# /tmp/gen_builtin_differentials.py
import os
import yaml
from clinosim.modules.diagnosis import engine

OUT = os.path.join(
    os.path.dirname(engine.__file__), "reference_data", "builtin_differentials.yaml"
)

# name を削いだ差分リスト / 2 要素 progression を構築 (insertion order 保存)
differentials = {
    dx: [{"disease": e["disease"], "icd": e["icd"], "prior": e["prior"]} for e in rows]
    for dx, rows in engine.DIFFERENTIALS.items()
}
progression = {
    dx: [[t, c] for (t, c, *_name) in rows]
    for dx, rows in engine.DIAGNOSIS_PROGRESSION.items()
}
lr_table = engine.LR_TABLE

out = {
    "differentials": differentials,
    "diagnosis_progression": progression,
    "lr_table": lr_table,
}

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w") as f:
    f.write(
        "# Built-in Bayesian differential reference data (YAML-driven, AD-18 internal table).\n"
        "# Display names are NOT stored here — resolved at use time via clinosim.codes.lookup\n"
        "# (AD-30). This file is the 3rd emittable diagnosis-code source; keep every `icd` and\n"
        "# progression code registered per CLAUDE.md 'Diagnosis code coverage'.\n"
    )
    yaml.safe_dump(out, f, sort_keys=False, allow_unicode=True, default_flow_style=False)

# --- 値同一性の検証 (round-trip == in-memory, name 除く) ---
reloaded = yaml.safe_load(open(OUT))
assert reloaded["differentials"] == differentials, "differentials mismatch"
assert reloaded["diagnosis_progression"] == progression, "progression mismatch"
assert reloaded["lr_table"] == lr_table, "lr_table mismatch"
print("OK: YAML round-trips identically to in-memory constants (name-stripped)")
print(f"  differentials diseases: {len(differentials)}")
print(f"  progression diseases:   {len(progression)}")
print(f"  lr findings:            {len(lr_table)}")
```

- [ ] **Step 2: 実行して値同一性を確認**

Run: `source .venv/bin/activate && python /tmp/gen_builtin_differentials.py`
Expected: `OK: YAML round-trips identically ...` が出力され、`differentials diseases: 26`,
`progression diseases: 25`, `lr findings: 4` 程度 (現定数の実数)。AssertionError が出ないこと。

- [ ] **Step 3: 生成 YAML の中身をスポット確認**

Run: `grep -n "bacterial_pneumonia\|J18.9\|chest_xray_consolidation" clinosim/modules/diagnosis/reference_data/builtin_differentials.yaml | head`
Expected: `differentials` に `bacterial_pneumonia` / `icd: J18.9 / prior: 0.45`、`lr_table` に
`chest_xray_consolidation` が存在。`name:` キーが 1 件も無いこと
(`grep -c "name:" .../builtin_differentials.yaml` → `0`)。

- [ ] **Step 4: コミット** (ブランチ作成後、push はしない)

```bash
git checkout -b refactor/diagnosis-engine-yaml
git add clinosim/modules/diagnosis/reference_data/builtin_differentials.yaml
git commit  # メッセージ本文 + Global Constraints のトレーラ
```

コミットメッセージ:
```
refactor(diagnosis): externalize built-in differential tables to YAML

Generate reference_data/builtin_differentials.yaml from the current
hard-coded DIFFERENTIALS / DIAGNOSIS_PROGRESSION / LR_TABLE constants,
value-identical (name dropped per AD-30). engine.py wiring follows.
```

---

### Task 2: engine.py を YAML ローダ駆動に切り替え + display を lookup 解決

3 定数のハードコードを削除し、`builtin_differentials.yaml` からロード。`DIAGNOSIS_PROGRESSION`
は 2 要素タプルに、`display_name` は `codes.lookup` 解決に変更する。

**Files:**
- Modify: `clinosim/modules/diagnosis/engine.py` (L34-394 の 3 定数定義を置換、L412-435 / L492-530 の display 解決を変更)
- Test: `tests/unit/test_diagnosis.py` (既存、変更不要 — 緑のままを確認)

**Interfaces:**
- Consumes: `builtin_differentials.yaml` (Task 1)、`clinosim.codes.lookup`。
- Produces: module-level `DIFFERENTIALS: dict[str, list[dict]]` (`{disease,icd,prior}`)、
  `DIAGNOSIS_PROGRESSION: dict[str, list[tuple[float, str]]]`、
  `LR_TABLE: dict[str, dict[str, dict[str, float]]]`、
  `DEFAULT_PNEUMONIA_DIFFERENTIAL`。公開関数シグネチャ不変。

- [ ] **Step 1: 既存 unit テストが現状緑であることを確認 (ベースライン)**

Run: `source .venv/bin/activate && python -m pytest tests/unit/test_diagnosis.py -q`
Expected: PASS (全ケース緑)。

- [ ] **Step 2: import 群とローダを追加**

`engine.py` 冒頭 (L7-10 付近) を以下に置換:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import yaml

from clinosim.codes import lookup

_REFERENCE_DATA = Path(__file__).parent / "reference_data" / "builtin_differentials.yaml"


def _load_reference_data() -> tuple[
    dict[str, list[dict]],
    dict[str, list[tuple[float, str]]],
    dict[str, dict[str, dict[str, float]]],
]:
    """Load built-in differential tables from YAML (AD-18 internal reference table).

    Display names are not stored; they are resolved at use time via clinosim.codes.
    """
    with open(_REFERENCE_DATA) as f:
        data = yaml.safe_load(f) or {}
    differentials = data.get("differentials", {})
    progression = {
        dx: [(float(row[0]), str(row[1])) for row in rows]
        for dx, rows in data.get("diagnosis_progression", {}).items()
    }
    lr_table = data.get("lr_table", {})
    # Sanity: every differential entry must carry disease/icd/prior
    for dx, rows in differentials.items():
        for e in rows:
            if not {"disease", "icd", "prior"} <= e.keys():
                raise ValueError(f"builtin_differentials.yaml: bad entry in {dx!r}: {e!r}")
    return differentials, progression, lr_table


def _display(icd_code: str) -> str:
    """Resolve an ICD code's English display via the code system (AD-30)."""
    return lookup("icd-10-cm", icd_code, "en")
```

- [ ] **Step 3: 3 定数のハードコード定義を YAML ロード結果に置換**

`DIFFERENTIALS = {...}` (L34-241)、`DIAGNOSIS_PROGRESSION = {...}` (L243-370)、
`LR_TABLE = {...}` (L375-394) の 3 ブロックを丸ごと削除し、`DEFAULT_PNEUMONIA_DIFFERENTIAL`
の定義位置 (旧 L372-373) も含めて以下 1 ブロックに置換する:

```python
DIFFERENTIALS, DIAGNOSIS_PROGRESSION, LR_TABLE = _load_reference_data()

# Keep backward compatibility
DEFAULT_PNEUMONIA_DIFFERENTIAL = DIFFERENTIALS["bacterial_pneumonia"]
```

- [ ] **Step 4: `initialize_differential` の display_name を lookup 解決に変更**

`initialize_differential` 内の candidate 構築 (旧 L418-423) を置換:

```python
        candidates.append(DiagnosisCandidate(
            disease_code=dx["disease"],
            icd_code=dx["icd"],
            display_name=_display(dx["icd"]),
            probability=prior,
        ))
```

(built-in / protocol 両経路とも `dx["name"]` を読まず、`_display(dx["icd"])` で解決する。
protocol differential エントリの `name` は無視される。)

- [ ] **Step 5: `get_current_diagnosis_code` を 2/3 要素両対応 + lookup に変更**

関数末尾の no-progression フォールバックと progression ループ (旧 L518-530) を置換:

```python
    if not progression:
        # No progression — fall back to top candidate's icd_code
        top = diff.top_candidate
        if top and top.icd_code:
            return (top.icd_code, _display(top.icd_code))
        return "R69", "Illness, unspecified"

    confidence = diff.candidates[0].probability if diff.candidates else 0
    code = progression[0][1]
    for row in progression:
        if confidence >= row[0]:
            code = row[1]
    return code, _display(code)
```

(`row[0]`/`row[1]` 添字アクセスにより、built-in の 2 要素タプルと disease YAML の
3 要素リスト `[threshold, code, name]` の両方を扱える。)

- [ ] **Step 6: 残存する `name` 参照が無いことを確認**

Run: `grep -n '"name"\|\[.name.\]\|display_name=dx' clinosim/modules/diagnosis/engine.py`
Expected: 出力なし (engine 内で differential `name` を読む箇所が消えている)。

- [ ] **Step 7: lint / 型チェック**

Run: `source .venv/bin/activate && ruff check clinosim/modules/diagnosis/engine.py && ruff format clinosim/modules/diagnosis/engine.py && mypy clinosim/modules/diagnosis/engine.py`
Expected: エラーなし (mypy はリポジトリ設定に従う)。

- [ ] **Step 8: unit テストが緑であることを確認**

Run: `source .venv/bin/activate && python -m pytest tests/unit/test_diagnosis.py -q`
Expected: PASS (Task 2 Step 1 と同じ結果 = 出力不変)。

- [ ] **Step 9: ロード値が Task 1 の YAML と一致することを確認 (回帰)**

Run:
```bash
source .venv/bin/activate && python -c "
from clinosim.modules.diagnosis import engine
import yaml, os
y = yaml.safe_load(open(os.path.join(os.path.dirname(engine.__file__),'reference_data','builtin_differentials.yaml')))
assert engine.DIFFERENTIALS == y['differentials']
assert engine.LR_TABLE == y['lr_table']
assert engine.DIAGNOSIS_PROGRESSION == {k:[tuple([float(r[0]),str(r[1])]) for r in v] for k,v in y['diagnosis_progression'].items()}
assert engine.DEFAULT_PNEUMONIA_DIFFERENTIAL is engine.DIFFERENTIALS['bacterial_pneumonia']
print('OK: engine constants match YAML')
"
```
Expected: `OK: engine constants match YAML`。

- [ ] **Step 10: コミット**

```bash
git add clinosim/modules/diagnosis/engine.py
git commit
```
メッセージ:
```
refactor(diagnosis): load differential tables from YAML, resolve names via codes

engine.py no longer hard-codes DIFFERENTIALS/DIAGNOSIS_PROGRESSION/LR_TABLE
nor display names. Tables load from reference_data/builtin_differentials.yaml;
display resolved via clinosim.codes.lookup (AD-30). Output unchanged (names
were discarded at inpatient.py:292; CIF stores codes only).
```

---

### Task 3: カバレッジテストを YAML パースに更新

第 3 emittable 源を engine.py 正規表現走査から YAML パースへ切り替える。

**Files:**
- Modify: `tests/unit/test_diagnosis_code_coverage.py:63-70` (`_engine_differential_codes`)

**Interfaces:**
- Consumes: `builtin_differentials.yaml`。
- Produces: `_engine_differential_codes() -> set[str]` (ICD コード集合)。`ALL_EMITTABLE` 経由で
  既存テスト 4 本が利用 (シグネチャ不変)。

- [ ] **Step 1: 現状のカバレッジテストが緑であることを確認 (ベースライン)**

Run: `source .venv/bin/activate && python -m pytest tests/unit/test_diagnosis_code_coverage.py -q`
Expected: PASS (4 テスト緑)。

- [ ] **Step 2: `_engine_differential_codes` を YAML パースに置換**

`tests/unit/test_diagnosis_code_coverage.py` の `_engine_differential_codes` (L63-70) を置換:

```python
def _engine_differential_codes() -> set[str]:
    """ICD codes in the built-in differential/progression tables (3rd emittable source:
    working/discharge diagnoses) loaded from diagnosis/reference_data."""
    fp = os.path.join(
        ROOT, "clinosim/modules/diagnosis/reference_data/builtin_differentials.yaml"
    )
    data = yaml.safe_load(open(fp)) or {}
    codes: set[str] = set()
    for rows in data.get("differentials", {}).values():
        for entry in rows:
            if entry.get("icd"):
                codes.add(entry["icd"])
    for rows in data.get("diagnosis_progression", {}).values():
        for row in rows:
            if len(row) >= 2 and row[1]:
                codes.add(row[1])
    return codes
```

(`re` import が他で未使用になる場合は削除する。`grep -n "re\." tests/unit/test_diagnosis_code_coverage.py`
で確認 — `_WHO_FORMAT = re.compile(...)` が残るため `import re` は維持。)

- [ ] **Step 3: 収集コード集合が移行前後で同一であることを確認**

Run:
```bash
source .venv/bin/activate && python -c "
import importlib.util, os
spec = importlib.util.spec_from_file_location('cov','tests/unit/test_diagnosis_code_coverage.py')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
codes = m._engine_differential_codes()
print('engine differential codes:', len(codes))
assert codes, 'empty set — YAML parse failed'
print(sorted(codes)[:8])
"
```
Expected: `engine differential codes:` が 60 件以上 (follow-up #1 で ~65 件登録済)。空集合でないこと。

- [ ] **Step 4: カバレッジテストが緑であることを確認**

Run: `source .venv/bin/activate && python -m pytest tests/unit/test_diagnosis_code_coverage.py -q`
Expected: PASS (4 テスト緑 = 不変条件維持)。

- [ ] **Step 5: コミット**

```bash
git add tests/unit/test_diagnosis_code_coverage.py
git commit
```
メッセージ:
```
test(codes): read engine differential codes from YAML, not source regex

_engine_differential_codes() now parses builtin_differentials.yaml
(differentials[*].icd + diagnosis_progression[*][1]) instead of
regex-scanning engine.py. Same invariant, more robust.
```

---

### Task 4: ドキュメント更新

**Files:**
- Modify: `clinosim/modules/diagnosis/README.md` (3 定数セクション L149-227、依存関係 L288-292、修正ガイド)
- Modify: `CLAUDE.md` (「Diagnosis code coverage」の第 3 源の記述)

- [ ] **Step 1: diagnosis/README.md を更新**

以下を反映 (該当セクションを編集):
- `DIFFERENTIALS` / `LR_TABLE` / `DIAGNOSIS_PROGRESSION` の各説明を「`reference_data/builtin_differentials.yaml` から
  ロードされる」に変更。サンプルから `name` キーを削除、progression は `[threshold, code]` の 2 要素に。
- 「既知の負債」注記 (L178-180 付近、`DIFFERENTIALS` 表と表示 name を Python にハードコード…) を
  「**解消済 (2026-06)**: `reference_data/builtin_differentials.yaml` に外部化。display は
  `codes.lookup` 解決」に更新。
- 第 3 emittable 源の警告 (L172-176) の参照先を engine.py → `builtin_differentials.yaml` に更新。
- 「依存関係」(L288-292) を「標準ライブラリ + PyYAML + `clinosim.codes` (display 解決)」に更新。
- 「修正ガイド > 関連モジュール」の `codes` 行は維持。

- [ ] **Step 2: CLAUDE.md「Diagnosis code coverage」を更新**

`(3) the DIFFERENTIALS table + likelihood-ratio tuples hard-coded in modules/diagnosis/engine.py`
の記述を
`(3) the built-in differential/progression tables in modules/diagnosis/reference_data/builtin_differentials.yaml (differentials[*].icd + diagnosis_progression codes)`
に更新する。

- [ ] **Step 3: コミット**

```bash
git add clinosim/modules/diagnosis/README.md CLAUDE.md
git commit
```
メッセージ:
```
docs(diagnosis): record YAML-driven differential tables, clear hardcode debt
```

---

### Task 5: フル回帰検証 (unit + integration + e2e)

**Files:** なし (検証のみ)

- [ ] **Step 1: 関連 unit + integrity テスト**

Run: `source .venv/bin/activate && python -m pytest tests/unit/test_diagnosis.py tests/unit/test_diagnosis_code_coverage.py tests/unit/test_codes_integrity.py -q`
Expected: 全 PASS。

- [ ] **Step 2: unit + integration 全体**

Run: `source .venv/bin/activate && python -m pytest -m "unit or integration" -q`
Expected: 全 PASS (unit 243 / integration 16 規模)。

- [ ] **Step 3: e2e golden 回帰 (出力不変の確認)**

Run: `source .venv/bin/activate && python -m pytest -m e2e -q`
Expected: 全 PASS (37)。**golden 比較が緑 = 出力不変。** CPU 競合で稀に途中 exit (FAILED なし) →
パイプなしで再実行して確認 ([[feedback_clinosim_workflow]])。

- [ ] **Step 4: 一時生成物の掃除**

Run: `rm -f /tmp/gen_builtin_differentials.py`
Expected: 削除完了 (`output/` は触らない)。

- [ ] **Step 5: 完了報告とユーザー確認**

ブランチ `refactor/diagnosis-engine-yaml` に 4 コミット。全テスト緑・golden 不変を報告し、
push / PR 作成の可否をユーザーに確認する (push/PR/merge はユーザー指示時のみ)。

---

## Self-Review

**Spec coverage:**
- データファイル (spec §1) → Task 1。
- ローダ plain dict + サニティチェック (spec §2) → Task 2 Step 2。
- name の lookup 解決 (spec §3) → Task 2 Steps 4-5。
- カバレッジテスト更新 (spec §4) → Task 3。
- ドキュメント (spec §5) → Task 4。
- 検証: 値同一性 (Task 1 Step 2 + Task 2 Step 9) / unit / e2e (spec §6) → Task 5。
- 受け入れ基準 1-5 すべてに対応タスクあり。

**Placeholder scan:** TBD/TODO 無し。各コード手順は実コードを記載。

**Type consistency:** `_load_reference_data` の返り型 (`dict`, `dict[str,list[tuple[float,str]]]`, `dict`)、
`_display(icd_code: str) -> str`、`DIAGNOSIS_PROGRESSION` の 2 要素タプル — Task 2/3 で一貫。
`get_current_diagnosis_code` の `row[0]/row[1]` 添字は 2/3 要素両対応。
`_engine_differential_codes() -> set[str]` シグネチャ不変。
