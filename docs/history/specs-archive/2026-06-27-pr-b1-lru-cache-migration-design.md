# Foundation polish — PR-B1: global cache migration + disease YAML silent-skip fix

Date: 2026-06-27
Status: Draft → for user review
Related: PR-A → PR #102 (silent-no-op 防御 3 層完成) → 本 PR (foundation polish その 2)
Parent: memory `project_ehr_enrichment` セッション20 終了状態 次手候補 #1 = PR-B

---

## 1. Overview

PR #102 で完成した「silent-no-op 防御 3 層」(canonical constants + upstream `_validate_*` + backward `fallback="raise"`)に続く、foundation polish 完成 PR その 2。本 PR は 2 themed area:

1. **3 file の global mutable cache を `@lru_cache(maxsize=1)` に標準化**(PR-A 確立の lru_cache maxsize 規約適用)
2. **`helpers.py:_load_all_disease_protocols` の disease YAML load silent skip を fail-loud に修正**(silent-no-op 防御強化、PR-A 教訓「silent `dict.get(key)` fall-through は PR-90 class」と整合)

機能変更ゼロ、byte-diff invariant 保持。

### 1.1 Goals

- 3 file の `global X; if X is None: ... else return X` pattern を撤廃
- `@lru_cache(maxsize=1)` 統一(PR-A lru_cache maxsize 規約 100% 適用)
- `try ... except Exception: pass` による silent skip を fail-loud(raise)に修正
- silent-no-op 防御の **追加層完成**(YAML load 失敗時の silent skip も catch する)

### 1.2 Non-goals

- **PR-B2 = 16 module `__all__` exports**(別 PR、MOD-1 柔軟解釈で `__init__.py` に re-export 追加、callers 不変)
- `encounter/protocol.py:load_encounter_condition` (single) cache 追加 = YAGNI(現状 cache なしで実害なし、新機能)
- `helpers.py` 関数内 `from pathlib import Path` の module top 移動 = 無関係 cleanup
- 16 module の `__init__.py` 編集(PR-B2 で対応)

---

## 2. Scope

### 2.1 Global cache migration(3 files)

| File:Line | Current pattern | After |
|---|---|---|
| `clinosim/modules/encounter/protocol.py:14` `_cache: dict[str, dict[str, Any]] \| None = None` | `def load_all_encounter_conditions(): global _cache; if _cache is not None: return _cache; ... _cache = conditions; return conditions` (lines 50-65) | `@lru_cache(maxsize=1)` decorator + 関数本体から global / sentinel 除去 |
| `clinosim/simulator/helpers.py:17` `_protocol_cache: dict[str, DiseaseProtocol] \| None = None` | `def _load_all_disease_protocols(): global _protocol_cache; if _protocol_cache is not None: return _protocol_cache; ... _protocol_cache = protocols; return protocols` (lines 20-35) | 同 |
| `clinosim/modules/output/_fhir_diagnostic_report.py:25` `_PANELS_CACHE: dict[str, dict] \| None = None` | `def load_panel_groups(): global _PANELS_CACHE; if _PANELS_CACHE is None: ... _PANELS_CACHE = data.get(...); return _PANELS_CACHE` (lines 28-39) | 同 |

すべて no-param 関数 → PR-A 規約「no-param → maxsize=1」適用。Signature 不変、caller 影響なし。

### 2.2 Silent skip 解消(1 file)

`clinosim/simulator/helpers.py:30-33`:

```python
# BEFORE
for yaml_file in sorted(ref_dir.glob("*.yaml")):
    disease_id = yaml_file.stem
    try:
        protocols[disease_id] = load_disease_protocol(disease_id)
    except Exception:
        pass  # ← silent skip = PR-A 教訓と相反

# AFTER
for yaml_file in sorted(ref_dir.glob("*.yaml")):
    disease_id = yaml_file.stem
    protocols[disease_id] = load_disease_protocol(disease_id)
    # production の全 disease YAML が valid である前提
    # invalid なら ValueError raise(fail-loud)
```

byte-diff invariant 保持の前提: production の全 disease YAML が valid に load 可能(byte-diff Full 検証で実証)。

### 2.3 Out of scope(明示)

- 16 module `__all__` exports = **別 PR(PR-B2)**
- `encounter/protocol.py:load_encounter_condition` single cache = YAGNI
- 関数内 import の module top 移動 = 無関係 cleanup
- 他の `try/except Exception: pass` の sweep(本 PR は `helpers.py:_load_all_disease_protocols` のみに focus)

---

## 3. Architecture

### 3.1 Commit 構成(C hybrid themed approach)

| commit | scope | byte-diff invariant 検証 |
|---|---|---|
| **1** | 3 file の global cache → `@lru_cache(maxsize=1)`(構造同型 batch、PR-A path constants 同型) | commit 単独で seed=42 byte-diff |
| **2** | `helpers.py:_load_all_disease_protocols` silent skip 解消(`try/except pass` 削除) | 同 |
| **3** | docs sync(CLAUDE.md / CONTRIBUTING-modules.md) | byte-diff 不要(pure docs) |
| **final** | byte-diff Full(US p=10000 + JP p=5000、seed=42)で 37/37 NDJSON IDENTICAL を最終確認 | gate |

PR-A `A1 path constants migration`(12 modules 1 commit)同型。

### 3.2 `@lru_cache(maxsize=1)` migration pattern

```python
# Common BEFORE pattern (3 files)
_cache: dict[str, X] | None = None

def load_X() -> dict[str, X]:
    global _cache
    if _cache is not None:
        return _cache
    # ... build dict ...
    _cache = result
    return result


# Common AFTER pattern
from functools import lru_cache

@lru_cache(maxsize=1)
def load_X() -> dict[str, X]:
    # ... build dict ...
    return result
```

各 file で:
- `global X` 文を削除
- sentinel `None` check を削除
- module-level `_cache` 変数を削除
- `from functools import lru_cache` を import(既存 import に追加)
- `@lru_cache(maxsize=1)` decorator を関数に追加

### 3.3 機能変更ゼロの保証

- `@lru_cache(maxsize=1)` は **1 回目 = full evaluation, 2 回目以降 = cached return** で、global sentinel pattern と同じセマンティクス
- `try/except Exception: pass` 削除は **valid YAML 前提**で発火しない path = production 動作不変
- 本 PR で raise する path = "production で invalid YAML がある"場合のみ = byte-diff Full で実証
- byte-diff Full(US p=10000 + JP p=5000、seed=42)= 37/37 NDJSON IDENTICAL を最終確認

---

## 4. Verification

### 4.1 Unit test(新規)

| test file | scope | 期待 |
|---|---|---|
| `tests/unit/test_lru_cache_migration.py`(新規) | 3 loader 各々で (a) 2 回目呼出 `cache_info().hits > 0`、(b) `cache_clear()` 後の hits=0 確認 | 3 loader × 2 件 = 6 PASS |
| `tests/unit/test_silent_skip_fix.py` 同 file or 別 | monkeypatch で disease YAML loader が `ValueError` を投げる状態を作り、`_load_all_disease_protocols()` が raise することを確認 | 1 PASS |

### 4.2 既存 test 回帰

- `pytest -x` で unit 715+ / integration 139+ / e2e 39 全緑(計 1020+)

### 4.3 byte-diff invariant(最終 gate)

- seed=42 で US p=10000 + JP p=5000 を master vs branch で生成
- `sha256(*.ndjson)` 比較、**37/37 NDJSON file pairs sha256 IDENTICAL** が ship gate
- 機能変更ゼロ(`@lru_cache` migration + silent skip 解消の two-fold)を実証

---

## 5. Docs sync(commit 3)

| Doc | 更新内容 |
|---|---|
| `CLAUDE.md` AD-55 セクション("lru_cache maxsize 規約") | 「global mutable `_cache` pattern を撤廃済、3 file 全て `@lru_cache(maxsize=1)` 統一」を追記。silent skip 解消も追記 |
| `docs/CONTRIBUTING-modules.md` 正規 boilerplate | 同。新規 module の cache pattern は `@lru_cache(maxsize=1)` 必須を明記 |
| (オプション) `clinosim/simulator/README.md` (存在すれば) | `_load_all_disease_protocols` の silent skip 解消明記 |

---

## 6. Risk / mitigation

| Risk | 影響 | Mitigation |
|---|---|---|
| Production に invalid disease YAML が潜んでいる | 本 PR で生成 fail | byte-diff Full で実証。fail なら invalid disease 特定 + 修正 or specific exception に絞る |
| `@lru_cache(maxsize=1)` 移行で test 内 monkeypatch が破綻 | test 落ち | 既存 test で `_cache = None` 直接代入する test がないか事前確認、必要なら `load_X.cache_clear()` に置換 |
| `_PANELS_CACHE` が他箇所で参照されている | NameError | grep `_PANELS_CACHE\|_protocol_cache\|_cache` で全 reference 確認 |

---

## 7. Acceptance criteria

- [ ] 3 file 全てで global mutable `_cache` 撤廃 + `@lru_cache(maxsize=1)` 適用
- [ ] `helpers.py:_load_all_disease_protocols` で `try/except pass` 削除
- [ ] `tests/unit/test_lru_cache_migration.py`(新規)で 7 件以上の test pass
- [ ] `pytest -x` 全緑(1020+ 件)
- [ ] byte-diff Full(US p=10000 + JP p=5000、seed=42)で **37/37 NDJSON sha256 IDENTICAL**
- [ ] docs sync(CLAUDE.md / CONTRIBUTING-modules.md)
- [ ] PR 起票 + body に byte-diff 結果 + adversarial fan-out 戦略明示

---

## 8. PR + adversarial fan-out 戦略

1. branch: `refactor/pr-b1-lru-cache-migration`
2. title: `refactor(cache): global mutable cache → @lru_cache + disease YAML silent-skip fix`
3. body: 「foundation polish 完成 PR その 2」+ commit list + byte-diff 結果 + memory `feedback_iterative_adversarial_review` Stopping criteria 参照
4. merge 後 4-agent adversarial fan-out:
   - (a) 同 pattern の `global X; if X is None: ...` callsite 漏れ
   - (b) `@lru_cache(maxsize=1)` 規約適用の正確性
   - (c) silent skip 解消による副作用
   - (d) docs accuracy(callsite カウント、3 file 列挙)
5. 必要なら Fix PR、Stopping criteria(Critical/Important 0 + finding converging + 残 cosmetic only + 次段 expected size tiny)で converged 判定

---

## 9. Open questions

なし(brainstorming Q1-Q5 で確定済)

---

## 10. Implementation order(`writing-plans` skill 入力)

1. commit 1: 3 file の `global X; if X is None: ...` → `@lru_cache(maxsize=1)`
2. commit 2: `helpers.py:_load_all_disease_protocols` の `try/except pass` 削除
3. commit 3: docs sync
4. final gate: byte-diff Full 実行 + PR 起票

TDD: 各 commit 内で test → 実装 → byte-diff(commit 単独) → 次 commit。
