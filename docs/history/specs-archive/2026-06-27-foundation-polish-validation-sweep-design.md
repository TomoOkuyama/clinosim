# Foundation polish — silent uniform fallback defense (validation sweep)

Date: 2026-06-27
Status: Draft → for user review
Related: PR-A (#99) + Fix #100 + Fix #101 — silent-no-op defense triplet completion
Parent issue: memory `project_ehr_enrichment` の「セッション19 終了状態」次手候補 #8 + #1 のうち #8

---

## 1. Overview

PR-A → Fix #100 → Fix #101 で確立した **silent-no-op 防御 3 層**(`_validate_*` 上流 / `fallback="raise"` 後方 / canonical constants)のうち、`fallback="raise"` 後方防御を **YAML-sourced 確率サンプリングの全 callsite** に適用し、合わせて主要な YAML loader 4 つに `_validate_*` 上流防御を追加する。

これにより、YAML 編集事故で確率分布が `[0, 0, 0, ...]` 等の zero-sum / 全 0 になった場合に:
- **import 時**(simulation 開始前): `_validate_*` が `ValueError` を raise(fail-loud 最速化)
- **runtime**(最初のサンプリング呼出): `normalize_probabilities(..., fallback="raise")` が `ValueError` を raise(後方防御)

両者は補完的に機能し、PR-90 class silent-no-op の構造的解消をもたらす。

**Foundation polish 完成 PR(その 1)**(次の予定 PR は #1 PR-B = MOD-1 / lru_cache 統一)。

### 1.1 Goals

- 残存する `fallback`-未指定 callsite **10 件**を `fallback="raise"` 化(PR-A Fix #101 F-A2 incomplete 教訓「same function を grep して全 callsite を fix」の completion)
- 主要 YAML loader **4 つ**に `_validate_*(data) -> None` を追加(`_validate_microbiology` 同型)
- 機能変更ゼロ(byte-diff invariant 保持)
- silent-no-op 防御 3 層の hai / population / locale 全面完成を docs に encode

### 1.2 Non-goals

- #1 PR-B(global `_cache` → `@lru_cache` + 空 `__init__.py` MOD-1 exports)= 別 PR
- `clinical_course/engine.py:101` の上流 protocol YAML loader validation = `disease/loader.py` 改修必要、別 PR で natural
- `population/engine.py:145` の blood_type sampling(`rng.choice(p=list(bt.values()))` で直接、`normalize_probabilities` 経由でない)= 本 PR の scope は `normalize_probabilities` 経由の callsite のみ。blood_type 含む直接 `rng.choice(p=)` callsite の `normalize_probabilities` 化は別 PR で natural
- 新機能追加なし、臨床 model 変更なし、AD-55/56/60 拡張なし

---

## 2. Scope

### 2.1 後方防御: `fallback="raise"` 10 callsites

10 件を一括で `fallback="raise"` 化。**ピンポイント編集 + 既存 guard はそのまま温存**(機能変更ゼロ、byte-diff invariant 保持)。

| Group | callsite | source YAML |
|---|---|---|
| A1 | `hai/engine.py:85` | `hai/reference_data/organisms.yaml` |
| A2 | `population/engine.py:170` | `locale/{country}/demographics.yaml` smoking_dist |
| A3 | `population/engine.py:180` | `locale/{country}/demographics.yaml` alcohol_dist |
| A4 | `population/engine.py:485` | `locale/{country}/names.yaml` surnames |
| A5 | `population/engine.py:509` | `locale/{country}/demographics.yaml` 各種 dist |
| A6 | `population/engine.py:517` | `locale/{country}/names.yaml` first_names |
| A7 | `population/engine.py:664` | `locale/{country}/addresses.yaml` cities |
| B1 | `clinical_course/engine.py:101` | physiology profile + disease protocol(各値≥0.001 強制で safe、意図明示) |
| B2 | `hai/enricher.py:152` | `hai/reference_data/organisms.yaml`(PR-95 RNG mirror、upstream guard 温存) |
| B3 | `hai/enricher.py:225` | `hai/reference_data/hai_antibiogram.yaml`(upstream guard 温存) |

**Key constraint(B グループ)**:
- B2/B3 は PR-95 で確立した **AD-16 RNG mirror exact sequence** の load-bearing 部分。
- upstream guard(`if ... and sum() > 0:` / `if probs_arr.sum() <= 0: continue`)は **削除せず温存**。
- `fallback="raise"` は意図明示のみ(到達不能 path、機能変更ゼロ)。

### 2.2 上流防御: `_validate_*` 4 loaders

| commit | 対象 loader | `_validate_*` 関数 | catch する cross-references(実装) |
|---|---|---|---|
| 2 | `hai/engine.py:load_hai_organisms` | `_validate_hai_organisms(data)` | (a) top-level shape(dict)、(b) keys ⊆ HAI_TYPES、(c) organism list が list 型 + non-empty、(d) 各 entry が dict、(e) 各 weight numeric + 非負、(f) sum > 0、(g) snomed が non-empty string |
| 3 | `locale/loader.py:load_demographics` | `_validate_demographics(data)` | optional `lifestyle_distribution` block を検証 — (a) lifestyle が dict、(b) `smoking`/`alcohol` が dict、(c) 各 sex 配下が dict、(d) 各 weight numeric + 非負、(e) sum > 0(weight 列が存在する場合)。blocks/keys 自体は absent 許容 |
| 4 | `locale/loader.py:load_names` | `_validate_names(data)` | optional `surnames` / `given_names_male` / `given_names_female` list を検証 — (a) top-level dict、(b) 各 key が list 型、(c) 各 entry が dict、(d) 各 weight numeric + 非負、(e) sum > 0(weight 列が存在する場合)。list 自体は absent / empty 許容(上流 `normalize_probabilities` が empty で raise) |
| 4 | `locale/loader.py:load_addresses` | `_validate_addresses(data)` | optional `cities` を検証 — (a) top-level dict、(b) `cities` が list 型、(c) 各 entry が dict、(d) 各 weight numeric + 非負、(e) sum > 0。`cities` 自体は absent / empty 許容(上流 caller が `if not cities: return` で guard) |

**設計判断**: 各 validator は **structural shape + numeric / non-negative weight + non-zero-sum** の **3 種類** を catch する。一方、(i) optional block の absent、(ii) optional list の empty、(iii) "canonical key 集合" の enforcement は **実装しない**。理由:
- 上流 caller が `if not X: ...` などの guard を持つ場合、empty は実害ゼロ
- canonical key 集合(例:smoking levels = `{never, former, current}`)は YAML 駆動の柔軟性を損なうため、**zero-sum 検出のみ**で silent uniform fallback を防ぐ方が合理的
- spec の以前の "non-empty / canonical set" claim は overshoot — 実装は安全側でこれらを skip(adversarial review 2026-06-27 Agent 2 [Important] #2/#3 に対応した spec 修正)

**配置原則**:
- `_validate_*` は `load_*` 内部から呼ぶ(1 回目の load で 1 回 validate、`@lru_cache` 済の loader はパフォーマンス影響なし)
- 既存 `load_*` 関数 signature 不変(byte-diff invariant 保持)
- `_validate_microbiology` と同じ命名規約

### 2.3 Out of scope

- `clinical_course/engine.py:101` の上流 = disease protocol YAML loader validation。`disease/loader.py` は本 PR では touch しない
- `_load_demographics`(`population/engine.py:40` の thin wrapper)= 1 行 forwarding なので変更不要
- 他の `normalize_probabilities` 既存 callsite で既に `fallback="raise"` 済のもの(PR-A Fix #100 で migrate 済)

---

## 3. Architecture

### 3.1 commit 構成(C hybrid themed approach)

| commit | scope | byte-diff invariant 検証 |
|---|---|---|
| **1** | 10 callsites を `fallback="raise"` 化(A1-A7 + B1-B3) | commit 単独で seed=42 byte-diff |
| **2** | `_validate_hai_organisms` 追加 + `load_hai_organisms` 内 1 行 wiring | 同 |
| **3** | `_validate_demographics` 追加 + `load_demographics` 内 1 行 wiring | 同 |
| **4** | `_validate_names` + `_validate_addresses` 追加 + 各 loader 1 行 wiring(構造同型 = batch) | 同 |
| **5** | docs sync(CLAUDE.md / CONTRIBUTING-modules.md / TEMPLATE / 関連 README) | byte-diff 不要(pure docs) |
| **final** | byte-diff Full(US p=10000 + JP p=5000、seed=42)で 78/78 NDJSON IDENTICAL を最終確認 | gate |

PR-A `commit 1: A1 path constants + commit 2: A2 lru_cache + ...` と同型。

### 3.2 `_validate_*` の構造(共通テンプレート)

```python
def _validate_<name>(data: dict) -> None:
    """Validate <YAML> structure — raise ValueError on cross-reference violation."""
    if not isinstance(data, dict):
        raise ValueError(f"_validate_<name>: expected dict, got {type(data).__name__}")
    # Check 1: required keys present
    # Check 2: list non-empty
    # Check 3: each weight ≥ 0
    # Check 4: sum > 0 (zero-sum 防御)
    # Check 5: cross-references resolve (SNOMED / canonical set etc.)
```

呼出例:

```python
@lru_cache(maxsize=2)
def load_hai_organisms() -> dict[str, Any]:
    data = yaml.safe_load((_REF_DIR / "organisms.yaml").read_text())
    _validate_hai_organisms(data)  # ← import 時 = 1 回目の load で validate
    return data
```

### 3.3 機能変更ゼロの保証

- `normalize_probabilities` の `fallback="raise"` は **valid (non-zero-sum) input には影響なし**(既存 YAML はすべて valid なので runtime 動作不変)
- `_validate_*` も valid input に対しては no-op(返り値 None、副作用なし)
- `fallback="raise"` で初めて raise する path は **既存テストでも到達不能**(YAML 編集事故は test 中に発生しない)
- byte-diff Full(US p=10000 + JP p=5000)で実証

---

## 4. Verification

### 4.1 Unit test(commit ごと)

| test file | scope | 期待 |
|---|---|---|
| `tests/unit/test_fallback_raise_callsites.py`(新規) | 各 callsite(10 件)で zero-sum YAML を monkeypatch inject → `ValueError` 発火 | 10 件すべて `ValueError` |
| `tests/unit/test_yaml_loader_validation.py`(新規) | 各 `_validate_*`(4 件)に malformed YAML を渡して `ValueError` 発火: empty list / negative weight / unknown key / missing SNOMED 等 | 4 loaders × ~5 negative tests = ~20 件 |

### 4.2 既存 test 回帰

- `pytest -x` で unit 695+ / integration 139+ / e2e 39 全緑

### 4.3 byte-diff invariant(最終 gate)

- seed=42 で US p=10000 + JP p=5000 を master vs branch で生成
- `sha256(*.ndjson)` を比較、**78/78 NDJSON IDENTICAL** が ship gate

### 4.4 audit framework smoke

- `clinosim audit run` を smoke 実行、`silent_no_op` axis が新 validator を catch するか確認
- 必須ではないが framework がさらに堅牢化される(harness self-check の機会)

---

## 5. Docs sync(commit 5)

| Doc | 更新内容 |
|---|---|
| `CLAUDE.md` AD-55 セクション | "silent-no-op 防御 3 層"(セッション19 確立 pattern)を「全 10 callsites + 4 主要 loader で完備」に更新、本 PR への参照追加 |
| `docs/CONTRIBUTING-modules.md` | "Import-time canonical-constants validation" セクションに「4 主要 loader で完備」を明記、新規 loader 追加時のチェックリストに `_validate_*` 必須を強化 |
| `.github/TEMPLATE_MODULE_README.md` | Fix #101 で `_validate` stub fail-loud 化済 — 変更なし(現状確認のみ) |
| `clinosim/modules/hai/README.md` | `_validate_hai_organisms` の cross-references(HAI_TYPES / SNOMED / weight)を列挙 |
| `clinosim/locale/README.md`(存在確認済) | `_validate_demographics` / `_validate_names` / `_validate_addresses` の cross-references を列挙 |
| `clinosim/modules/_shared.py` docstring | `fallback="raise"` を YAML-sourced callsites の標準として明示(Fix #100 の docstring を強化) |

---

## 6. PR + adversarial fan-out 戦略

1. **PR 起票**:
   - branch: `feat/foundation-polish-validation-sweep`(または `fix/...`)
   - title 候補: `fix(validation): fallback="raise" sweep + 4 YAML loader _validate_*`
   - body: 「silent-no-op 防御 3 層完成 PR(その 1)」+ commit list + byte-diff 結果(78/78 IDENTICAL)+ memory `feedback_iterative_adversarial_review` Stopping criteria 参照
2. **merge 後 adversarial fan-out**: 4-agent fan-out(memory `feedback_iterative_adversarial_review` 適用)。focus:
   - (a) 同関数内 sibling callsite 漏れ(F-A2 incomplete 教訓 = 「same function を grep」ルール)
   - (b) test coverage gap(positive と negative test の対称性)
   - (c) PR-95 AD-16 RNG mirror exact sequence への副作用ゼロ確認
   - (d) docs accuracy(callsite カウント、cross-reference 列挙が実コードと一致)
3. **必要なら Fix PR**: 通常 1-2 段で converged
4. **Stopping criteria**: Critical/Important 0 + finding converging + 残 cosmetic only + 次段 expected size tiny = converged

---

## 7. Risk / mitigation

| Risk | 影響 | Mitigation |
|---|---|---|
| `_validate_*` が valid YAML を誤って reject | 既存 test 回帰 + 実環境 crash | 各 `_validate_*` に positive test(現行 YAML が pass)を追加 |
| `fallback="raise"` がテストで意図せず raise | unit test 落ち | テストが zero-sum input を意図的に inject していないか事前確認、必要なら test 側を adjust |
| B2/B3 の upstream guard を誤って削除 | PR-95 RNG sequence 変化 → AD-16 violation | guard は touch せず、`fallback="raise"` を **追加のみ**。byte-diff invariant が最終 gate |
| docs と実コードの乖離 | adversarial review で finding | docs sync commit を最後に置き、実 commit 完了後に書く |
| byte-diff Full の disk/time 消費 | ~3-10GB / 20 min × 2 | scratchpad で実行、完了後 `rm -rf scratchpad/foundation_*` |

---

## 8. Acceptance criteria

- [ ] 10 callsites すべて `fallback="raise"`
- [ ] 4 loader すべて `_validate_*` で wire 済
- [ ] `tests/unit/test_fallback_raise_callsites.py` に 10 件の `ValueError` 発火テスト
- [ ] `tests/unit/test_yaml_loader_validation.py` に 4 loaders × ~5 negative tests
- [ ] `pytest -x` 全緑(unit + integration + e2e、~970+ collected)
- [ ] byte-diff Full(US p=10000 + JP p=5000、seed=42)で **78/78 NDJSON IDENTICAL**
- [ ] docs sync(CLAUDE.md / CONTRIBUTING-modules.md / 関連 module README)
- [ ] PR 起票 + body に byte-diff 結果 + adversarial fan-out 戦略明示

---

## 9. Open questions

- なし(brainstorming Q1-Q5 で確定済)

---

## 10. Implementation order(`writing-plans` skill 入力)

順序:
1. commit 1: `fallback="raise"` 10 callsites(A1-A7 + B1-B3)
2. commit 2: `_validate_hai_organisms` + `load_hai_organisms` wiring
3. commit 3: `_validate_demographics` + `load_demographics` wiring
4. commit 4: `_validate_names` + `_validate_addresses` + 各 loader wiring
5. commit 5: docs sync
6. final gate: byte-diff Full 実行 + PR 起票

TDD: 各 commit 内で test → 実装 → byte-diff(commit 単独) → 次 commit。
