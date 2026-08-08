# ナトリウム (dysnatremia) 生理軸 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 疾患駆動の低/高 Na 血症を生理モデルに追加する — 慢性 HF/肝硬変でベースライン低 Na、脱水で高 Na、SIADH/HF 増悪で低 Na。Na 検査値を基礎疾患・疾患シナリオと整合させる(監査で Na 131-144 と判明したギャップを是正)。

**Architecture:** 既存ラボ軸(`glucose_status`/`acid_base_type`/`anemia_level`)と同型。`PhysiologicalState` に `sodium_status` 軸を追加し、`initialize_state`(慢性ベースライン)・`apply_coupling_rules`(脱水→高Na 結合)・`derive_lab_values`(Na 写像)で駆動。急性 SIADH/増悪は疾患 YAML の `initial_state_impact` でデータ駆動。

**Tech Stack:** Python 3.11+, `physiology` モジュール, pytest。

## Global Constraints

- **モジュール/プラグイン構造を厳守(ユーザー指示)**: 変更は `physiology` モジュール(`clinosim/modules/physiology/engine.py`)+ 型(`clinosim/types/clinical.py`)+ 疾患/encounter の `reference_data/*.yaml` のみに閉じる。新規モジュール・クロスモジュールのハードコード結合を作らない。physiology の依存グラフ(README の Dependencies)を逸脱しない。
- **データ駆動**: 疾患シナリオの Na 駆動は YAML `initial_state_impact` の `sodium_status` キー(`apply_disease_onset` が汎用適用)。engine 側にアドホックな疾患別 if を増やさない(慢性ベースラインは既存 I50/K74 分岐に追記)。
- **決定論 (AD-16)**: sodium 軸は rng/主乱数列を一切使わない(baseline/coupling/写像すべて決定論)。
- **既存出力**: Na 値は**意図的に変化**(リアリティ修正)。他ラボ(troponin/glucose/Hb/K/CRP/BNP 等)・vitals・診断は数式上不変。正常患者(sodium_status≈0)の Na は ~138-140 で従来同等。全 Na は clamp(120, 160) 内。
- **型は `clinosim/types/`**(`PhysiologicalState`)。コメント/docstring 英語、行長 100、ruff、mypy strict 方針。
- git: master から branch。commit 末尾に下記トレーラ(空行の後)。push/PR/merge はユーザー指示時のみ。`git add` は特定パスのみ(`-A` 禁止、`output/` を巻き込む)。venv: 各コマンド前 `source .venv/bin/activate`。

```
Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01PAVRbWqciawmAyKriJFsL1
```

---

### Task 1: `sodium_status` 状態軸の追加(型 + range)

**Files:**
- Modify: `clinosim/types/clinical.py`(`PhysiologicalState` にフィールド)
- Modify: `clinosim/modules/physiology/engine.py`(`_variable_range` の ranges dict)
- Test: `tests/unit/test_physiology.py`(スモーク)

**Interfaces:**
- Produces: `PhysiologicalState.sodium_status: float`(-1.0..+1.0)、`_variable_range("sodium_status") == (-1.0, 1.0)`。

- [ ] **Step 1: 型フィールドを追加**

`clinosim/types/clinical.py` の `PhysiologicalState` で、`glucose_status` の近くに追加:
```python
    sodium_status: float = 0.0  # -1.0–+1.0  (neg = hyponatremia, pos = hypernatremia)
```

- [ ] **Step 2: range を登録**

`clinosim/modules/physiology/engine.py` の `_variable_range` の `ranges` dict、`"glucose_status": (-1.0, 1.0),` の隣に追加:
```python
        "sodium_status": (-1.0, 1.0),
```

- [ ] **Step 3: スモークテストを追加**

`tests/unit/test_physiology.py` に追加(既存の import スタイルに合わせる):
```python
def test_sodium_status_field_and_range():
    from clinosim.types.clinical import PhysiologicalState
    from clinosim.modules.physiology.engine import _variable_range
    s = PhysiologicalState()
    assert s.sodium_status == 0.0
    assert _variable_range("sodium_status") == (-1.0, 1.0)
```

- [ ] **Step 4: 実行 + lint**

Run: `source .venv/bin/activate && python -m pytest tests/unit/test_physiology.py::test_sodium_status_field_and_range -q && ruff check clinosim/types/clinical.py clinosim/modules/physiology/engine.py`
Expected: PASS、新規行 lint クリーン。

- [ ] **Step 5: コミット**

```bash
git add clinosim/types/clinical.py clinosim/modules/physiology/engine.py tests/unit/test_physiology.py
git commit
```
メッセージ: `feat(physiology): add sodium_status state axis (dysnatremia)`

---

### Task 2: 慢性ベースライン + 脱水 coupling + Na 写像(TDD)

**Files:**
- Modify: `clinosim/modules/physiology/engine.py`(`initialize_state` 慢性分岐 / `apply_coupling_rules` / `derive_lab_values` の Na 行)
- Test: `tests/unit/test_physiology.py`

**Interfaces:**
- Consumes: Task 1 の `sodium_status` 軸。
- Produces: 慢性 HF/肝硬変で `sodium_status` 負、脱水(`volume_status < -0.35`)で `sodium_status` 正、
  `derive_lab_values(...)["Na"] == clamp(140 + sodium_status*14 - (1-renal)*3, 120, 160)`。

- [ ] **Step 1: 失敗テストを書く**

`tests/unit/test_physiology.py` に追加。`derive_lab_values` / `initialize_state` / `apply_coupling_rules`
の既存呼び出し方を冒頭で確認し、最小構築で:
```python
def test_na_mapping_from_sodium_status():
    from clinosim.types.clinical import PhysiologicalState
    from clinosim.modules.physiology.engine import derive_lab_values
    # normal: sodium_status 0, renal 1.0 -> Na ~140
    s = PhysiologicalState(renal_function=1.0, sodium_status=0.0)
    assert abs(derive_lab_values(s)["Na"] - 140.0) < 0.01
    # hyponatremia: sodium_status -1 -> ~126
    s_lo = PhysiologicalState(renal_function=1.0, sodium_status=-1.0)
    assert 124 <= derive_lab_values(s_lo)["Na"] <= 128
    # hypernatremia: sodium_status +1 -> ~151 (>145)
    s_hi = PhysiologicalState(renal_function=1.0, sodium_status=1.0)
    assert derive_lab_values(s_hi)["Na"] >= 148


def test_dehydration_coupling_raises_sodium():
    from clinosim.types.clinical import PhysiologicalState
    from clinosim.modules.physiology.engine import apply_coupling_rules
    s = PhysiologicalState(volume_status=-0.6, sodium_status=0.0)
    apply_coupling_rules(s)
    assert s.sodium_status > 0.0  # dehydration concentrates Na


def test_chronic_hf_cirrhosis_baseline_hyponatremia():
    from clinosim.modules.physiology.engine import initialize_state
    from clinosim.types.patient import PhysiologicalProfile  # adjust to real profile type if needed
    # Build chronic-condition inputs the way initialize_state expects (see existing tests).
    # HF (I50) and cirrhosis (K74) should drive sodium_status negative.
    # (Use the same ChronicCondition construction as other initialize_state tests in this file.)
    pass
```
(注: `test_chronic_hf_cirrhosis_baseline_hyponatremia` は `initialize_state` の実シグネチャと
`ChronicCondition` 構築を**既存テストfrom this file**に倣って具体化する。`initialize_state(profile,
conditions, patient_id)` で I50/K74 を severity_score>0.3 で与え、結果 `state.sodium_status < 0` を assert。
雛形が無ければ `apply_disease_onset` 経由ではなく `initialize_state` を直接呼ぶ既存テストを参照。)

- [ ] **Step 2: 失敗を確認**

Run: `source .venv/bin/activate && python -m pytest tests/unit/test_physiology.py -k "na_mapping or dehydration_coupling or baseline_hyponatremia" -q`
Expected: FAIL(Na 写像が未更新 / coupling 未実装)。

- [ ] **Step 3: Na 写像を更新**

`clinosim/modules/physiology/engine.py` の `derive_lab_values` 内、Na 2 行(現状
`labs["Na"] = 140.0 - (1 - renal) * 5 + state.volume_status * (-3)` と clamp)を置換:
```python
    # Na driven by the dysnatremia axis (chronic HF/cirrhosis hypo, dehydration hyper, SIADH).
    # The old volume term is subsumed by the volume->sodium coupling (apply_coupling_rules).
    labs["Na"] = 140.0 + state.sodium_status * 14.0 - (1 - renal) * 3.0
    labs["Na"] = clamp(labs["Na"], 120, 160)
```

- [ ] **Step 4: 脱水 coupling を追加**

`apply_coupling_rules` の末尾付近(`return` の前、他の coupling と同じスタイル)に追加:
```python
    # Dehydration (free-water deficit) concentrates serum sodium -> hypernatremia.
    if state.volume_status < -0.35:
        state.sodium_status = clamp(
            state.sodium_status + (abs(state.volume_status) - 0.35) * 1.2, -1.0, 1.0
        )
```

- [ ] **Step 5: 慢性ベースラインを追加**

`initialize_state` の慢性疾患ループで、既存の I50(HF)分岐に希釈性低 Na を追記し、肝硬変
(K74)分岐にも追記:
```python
        elif code.startswith("I50"):  # Heart failure
            state.cardiac_function *= 1.0 - s * 0.4
            if s > 0.3:
                state.volume_status += s * 0.3
            state.sodium_status -= s * 0.30   # dilutional hyponatremia
        elif code.startswith("K74"):  # Cirrhosis
            state.hepatic_function *= 1.0 - s * 0.5
            state.coagulation_status += s * 0.2
            state.sodium_status -= s * 0.40   # dilutional hyponatremia
```
(既存行は保持し、`sodium_status` 行のみ追加。`clamp` は `apply_coupling_rules`/`apply_disease_onset`
側で担保されるが、`initialize_state` 末尾で coupling を呼んでいない場合は直接 `clamp` で挟む —
既存コードの作法に合わせる。)

- [ ] **Step 6: 全テスト緑 + lint**

Run: `source .venv/bin/activate && python -m pytest tests/unit/test_physiology.py -q && ruff check clinosim/modules/physiology/engine.py`
Expected: 全 PASS、lint クリーン。

- [ ] **Step 7: コミット**

```bash
git add clinosim/modules/physiology/engine.py tests/unit/test_physiology.py
git commit
```
メッセージ: `feat(physiology): sodium baseline (HF/cirrhosis), dehydration coupling, Na mapping`

---

### Task 3: 疾患 YAML の sodium_status ドライバ(SIADH / HF 増悪)

**Files:**
- Modify: `clinosim/modules/disease/reference_data/heart_failure_exacerbation.yaml`
- Modify: `clinosim/modules/disease/reference_data/bacterial_pneumonia.yaml`
- Modify: `clinosim/modules/disease/reference_data/aspiration_pneumonia.yaml`
- Test: `tests/integration/`(新規 or 既存 physiology integration に追記)

**Interfaces:**
- Consumes: `apply_disease_onset` の汎用 `initial_state_impact` 適用(Task 1 の range 登録で
  `sodium_status` が clamp 適用される)。
- Produces: 当該シナリオで `state.sodium_status` 負 → Na 低値。

- [ ] **Step 1: HF 増悪に急性低 Na を追加**

`heart_failure_exacerbation.yaml` の `initial_state_impact` 各 severity に `sodium_status` を追加
(既存キーは保持):
```yaml
  mild:
    ...
    sodium_status: -0.20
  moderate:
    ...
    sodium_status: -0.35
  severe:
    ...
    sodium_status: -0.50
```

- [ ] **Step 2: 肺炎(SIADH)に低 Na を追加**

`bacterial_pneumonia.yaml` と `aspiration_pneumonia.yaml` の `initial_state_impact` 各 severity に
SIADH 由来の軽度〜中等度低 Na を追加(既存キー保持。肺炎は volume_status が -0.1〜-0.3 で
脱水 coupling 閾値 -0.35 未満=非発火のため、SIADH 低 Na が優位):
```yaml
  mild:
    ...
    sodium_status: -0.10
  moderate:
    ...
    sodium_status: -0.25
  severe:
    ...
    sodium_status: -0.40
```

- [ ] **Step 3: YAML ロード健全性 + 統合テスト**

`tests/integration/test_sodium_axis.py` を新規作成。disease protocol をロードして
`apply_disease_onset` を通し、Na が低下することを検証:
```python
import pytest

pytestmark = pytest.mark.integration


def test_hf_exacerbation_lowers_sodium():
    from clinosim.modules.disease.protocol import load_disease_protocol
    from clinosim.modules.physiology.engine import (
        apply_disease_onset, derive_lab_values,
    )
    from clinosim.types.clinical import PhysiologicalState
    p = load_disease_protocol("heart_failure_exacerbation")
    s = PhysiologicalState(renal_function=1.0)
    s = apply_disease_onset(s, "severe", p.initial_state_impact)
    assert s.sodium_status < 0
    assert derive_lab_values(s)["Na"] < 138   # hyponatremia


def test_pneumonia_siadh_lowers_sodium():
    from clinosim.modules.disease.protocol import load_disease_protocol
    from clinosim.modules.physiology.engine import apply_disease_onset, derive_lab_values
    from clinosim.types.clinical import PhysiologicalState
    p = load_disease_protocol("bacterial_pneumonia")
    s = PhysiologicalState(renal_function=1.0)
    s = apply_disease_onset(s, "severe", p.initial_state_impact)
    assert s.sodium_status < 0
    assert derive_lab_values(s)["Na"] < 139
```
(注: `apply_disease_onset` の実引数順/`load_disease_protocol` の返り型を実装前に確認し合わせる。)

- [ ] **Step 4: 実行**

Run: `source .venv/bin/activate && python -m pytest tests/integration/test_sodium_axis.py -q`
Expected: PASS。

- [ ] **Step 5: コミット**

```bash
git add clinosim/modules/disease/reference_data/heart_failure_exacerbation.yaml clinosim/modules/disease/reference_data/bacterial_pneumonia.yaml clinosim/modules/disease/reference_data/aspiration_pneumonia.yaml tests/integration/test_sodium_axis.py
git commit
```
メッセージ: `feat(disease): sodium_status drivers (HF exacerbation, pneumonia SIADH)`

---

### Task 4: ドキュメント + フル回帰 + 生成監査

**Files:**
- Modify: `clinosim/modules/physiology/README.md`(sodium 軸を記述)

- [ ] **Step 1: physiology/README.md を更新**

`sodium_status` 軸の節を追加(他軸の記述スタイルに合わせる): 意味(-1=低Na/+1=高Na)、駆動源
(慢性 HF/肝硬変ベースライン、脱水 coupling、疾患 YAML `initial_state_impact` の SIADH/増悪)、
Na 写像式、決定論。監査で是正したギャップ(Na 131-144)に言及。

- [ ] **Step 2: コミット**

```bash
git add clinosim/modules/physiology/README.md
git commit
```
メッセージ: `docs(physiology): document sodium_status axis`

- [ ] **Step 3: unit + integration 全体**

Run: `source .venv/bin/activate && python -m pytest -m "unit or integration" -q`
Expected: 全 PASS(既存 + 新規 sodium テスト)。

- [ ] **Step 4: e2e 回帰**

Run: `source .venv/bin/activate && python -m pytest -m e2e -q`
Expected: 全 PASS(37)。e2e はプロパティ/決定論ベース。Na は clamp(120,160) 内・決定論を維持。
CPU 競合で稀に途中 exit → 再実行で確認([[feedback_clinosim_workflow]])。

- [ ] **Step 5: 生成監査(Na 分布が疾患追従に分離することを確認)**

Run:
```bash
source .venv/bin/activate && rm -rf /tmp/na_chk && \
clinosim generate -o /tmp/na_chk -p 8000 -s 7 --country US --format cif csv --end 2026-06-20 >/dev/null 2>&1 && \
python3 - <<'PY'
import csv, collections, statistics
# join lab Na to encounter diagnosis (patient_id) and report Na median by disease group
na=collections.defaultdict(list)
dx={}
import glob, json
for fp in glob.glob("/tmp/na_chk/cif/structural/patients/*.json"):
    d=json.load(open(fp))
    def walk(o,k):
        r=[]
        if isinstance(o,dict):
            if k in o: r.append(o)
            for v in o.values(): r+=walk(v,k)
        elif isinstance(o,list):
            for v in o: r+=walk(v,k)
        return r
    # discharge dx code
    cd=walk(d,"discharge_diagnosis_code")
    code=cd[0]["discharge_diagnosis_code"] if cd else ""
    for lab in walk(d,"lab_name"):
        if lab.get("lab_name")=="Na":
            try: na[code[:3]].append(float(lab["value"]))
            except: pass
import numpy as np
def med(codes):
    vals=[v for c in codes for v in na.get(c,[])]
    return (round(np.median(vals),1), len(vals)) if vals else (None,0)
print("HF (I50):", med(["I50"]))
print("Cirrhosis (K70/K74):", med(["K70","K74"]))
print("Pneumonia (J18/J13/J15/J69):", med(["J18","J13","J15","J69"]))
allv=[v for vs in na.values() for v in vs]
print("ALL Na: median", round(np.median(allv),1), "min", min(allv), "max", max(allv), "n", len(allv))
print("hypo<130 frac:", round(sum(v<130 for v in allv)/len(allv),3), "hyper>145 frac:", round(sum(v>145 for v in allv)/len(allv),3))
PY
rm -rf /tmp/na_chk
```
Expected: HF / cirrhosis の Na 中央値が全体中央値より**低い**(低 Na 出現)、脱水系で高 Na、
全体で `hypo<130 frac > 0` かつ `hyper>145 frac > 0`(監査前はどちらも 0 だった)、全 Na が 120-160 内、
正常域中央値 ~138-140。分離が出なければ Task 2 の写像係数 / Task 3 の YAML 値 / coupling 閾値を調整。
**`output/` は触らない**(生成は `/tmp/na_chk` のみ、監査後削除)。

- [ ] **Step 6: 報告とユーザー確認**

ブランチのコミット一覧・全テスト結果・Na 分布監査の数値を報告し、push / PR 作成の可否を確認する。

---

## Self-Review

**Spec coverage:**
- `sodium_status` 軸 + range(spec §1)→ Task 1。
- 慢性ベースライン HF/肝硬変(spec §2)→ Task 2 Step 5。
- 脱水 coupling(spec §3 脱水→高Na)→ Task 2 Step 4。
- SIADH/増悪 YAML ドライバ(spec §3 SIADH/増悪)→ Task 3。
- Na 写像 `140 + sodium_status*14 - (1-renal)*3`(spec §4)→ Task 2 Step 3。
- 決定論・正常患者不変・clamp(spec §決定論/受け入れ基準3,4)→ Task 2 テスト + Task 4 Step 5 監査。
- ドキュメント(spec §受け入れ基準5)→ Task 4。
- モジュール構造厳守(ユーザー指示)→ Global Constraints + 全タスクが physiology/types/reference_data に限定。

**Placeholder scan:** TBD/TODO 無し。Task 2 Step 1 の chronic テストと Task 3 の統合テストは「実
シグネチャを既存テストに倣う」と明示(具体 assert は記載済、構築のみ既存作法参照)= 正当な実装手順。

**Type consistency:** `sodium_status: float`、`_variable_range("sodium_status")→(-1.0,1.0)`、
`derive_lab_values(state)["Na"]`、`apply_coupling_rules(state)->None`、`initialize_state(...)`、
`apply_disease_onset(state, severity, initial_state_impact)` — Task 1/2/3 で一貫。Na 写像係数
(14.0 / 3.0)と coupling 閾値(-0.35)・係数(1.2)は Task 2 で定義し Task 4 監査で検証。