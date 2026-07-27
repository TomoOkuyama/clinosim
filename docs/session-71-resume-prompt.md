# Session 71 Resume Prompt

**Date wrapped**: 2026-07-27
**Master head at wrap**: `9a30156fd5` (feat(chronic-meds, discharge-rx): mutually exclusive anticoagulant selection (#435))
**Session 70 confidence**: verified by supervisor CC independent measurement at each PR merge and Issue post.

## ★★★ この文書を信じる前に実測せよ

`.resume-prompt.md` に書かれた内容と実測が乖離する事故が session 68→69 / 69→70 で連続発生しています。**次 session 冒頭で以下を叩き、実測と本文を突合**:

```bash
cd /Users/tokuyama/workspace/clinosim
git checkout master
git fetch origin
git pull --ff-only
git log --oneline origin/master -6
gh pr list --state open --limit 10
gh issue list --state open --limit 20
```

### 期待実測 (session 70 wrap 時点、2026-07-27)

- master HEAD: `9a30156fd5 feat(chronic-meds, discharge-rx): mutually exclusive anticoagulant selection (#435)`
- 直前 3: `59ef91c877` (#438 test 3shift fix) / `594a267a71` (#434 CC0 license 訂正) / `d8971de308` (#429 session 70 resume prompt)
- **open PR: 0**
- **open Issue: 13** (#440 / #439 / #437 / #436 / #433 / #431 / #430 / #428 / #425 / #418 / #417 / #415 / #378)

差分あれば実測を優先、本文の「session 70 wrap 時点」前提を破棄せよ。

## ★★★ 最優先タスク (Session 71 起点で着手)

### #440 A' Phase 1 (patient_cache `current_medications` 同期) + #417 段 1 (in-hospital 開始薬継承)

**user 判断で「進める」と決定済み**。以下の依存順で 2 PR に分割:

```
PR A (Refs #440):  patient_cache A' 同期 (memoize.py 限界追記 + stress test 追加)
PR B (Refs #417):  in-hospital 開始 warfarin を discharge_prescription.items に載せる (段 1)

PR A → merge → PR B → merge
```

**理由**: PR A が先でないと PR B の効果が出ない。PR B 単独では `_generate_home_medication_orders` が current_medications loop に変わっても、後続 encounter で cache された古い PatientProfile を返すため意味的に何も動かない (Session 70 監督 CC 独立検証で確定)。

### PR A の実装要件 (#440 A' Phase 1)

**Throwaway 実測済み (Session 70)**: `git checkout master; pytest tests/unit/test_engine_memoize.py::test_memoize_hit_bit_identical -v` で default config は PASS (2.80s、実測)。ただし memoize.py 限界 1 と同 pattern で **大 config で発現する**:

- **memoize.py:271-273 の記述**: 限界 1 (`_IMPLIED_CHRONIC_BY_DISEASE` accretion) は `p=100/seed=42/1 か月 advance` で未顕在化、`p=600/seed=123/2 か月 advance` で発現
- **A' も同 pattern**: `current_medications` accretion も default config では発現しないが、大 config で `_canonical_cmp` 全 field 比較で cold vs memo 乖離検出しうる

PR A の必須要素:
1. **`_deactivate_to_layer1` に `patient_cache: dict[str, PatientProfile] | None = None` optional kwarg 追加**
2. **`current_medications` 同期**: `patient_cache[pid].current_medications = list(person.current_medications)` を discharge_prescription 反映後 に追加
3. **呼び出し側 (`engine.py:441` + `525`) で `patient_cache=patient_cache` を渡す**
4. **memoize.py 限界セクションに新項目追加**: `current_medications` accretion (A' 由来)、限界 1 と同 pattern であり大 config で発現する旨明記
5. **大 config での stress-test config での実測**: 別 test or `test_memoize_hit_bit_identical` の parametrize (fail する場合の除外 patient 数を測って報告、pass する場合はそのまま)
6. **goldens 再生成 + AD-66 rule 準拠** (`clinosim regenerate-goldens --all` + `--provider mock` の 2 回、AD-66 の同一 commit)

**変更行数見込み**: `_deactivate_to_layer1` + engine.py の call sites = ~10 行、memoize.py docstring 追記 = ~15 行、test 追加 or parametrize = ~30 行。golden 再生成が最大の作業。

### PR B の実装要件 (#417 段 1)

Session 70 前段 (comment 5086705355, 5086753000) で 2 段構造の段 1 として認識済み。

**8 疾患が `discharge_oral` 未定義**: `cerebral_infarction` / `crush_injury_hand` / `electrical_injury` / `fall_from_height` / `industrial_burn_severe` / `subdural_hematoma` / `traffic_accident_severe` / `wrist_fracture_surgical`。

**修正候補 (Session 70 で C5 却下、C1 一般解が推奨)**:
- **C1 (推奨)**: `_build_discharge_rx` に「in-hospital 開始の慢性適応薬 (anticoagulation category から発行された warfarin 等)」継承ロジックを追加。単一編集点、新疾患・新薬追加時に自動波及 (J5 pattern 予防)
- C5 (却下): 8 疾患に `discharge_oral` 追加 = 疾患ごと継ぎ足し = J5 pattern
- C2 / C3 (axis 側修正): 別方向、参考

C1 実装後、cohort 全体で以下が変わる:
- Warfarin 継承 rate: 現状 1/28 (in-hospital 新規開始) → 大幅改善 (実測値報告、100% にならなくてよい)
- Day 31+ の sub-therapeutic rate 61% がどう動くか実測

## Session 70 サマリ (実測付き)

### merge 済 PR: 3

| PR | commit | Title |
|---|---|---|
| **#434** | `594a267a71` | fix(docs): correct JP-CLINS pkg license CC BY-ND → CC0-1.0 (Closes #423) |
| **#435** | `9a30156fd5` | feat(chronic-meds, discharge-rx): mutually exclusive anticoagulant selection (Closes #432) |
| **#438** | `59ef91c877` | test(integration): rewrite 3-shift invariant to per-encounter LOS-conditional (Issue #337 alignment) |

### 起票 Issue: 6 (うち 1 close)

| Issue | 状態 | Title | 次アクション |
|---|---|---|---|
| **#432** | CLOSED (#435 で auto-close) | population 生成の Warfarin+DOAC 併用 | - |
| **#433** | OPEN | current_medications lacks re-start after renal-hold | design 判断、structural risk のみ (cohort 未発現) |
| **#436** | OPEN (MAJOR) | CIF→FHIR STOP intent 損失 | 既存 `OrderStatus.STOPPED` (PR3b-3) を STOP order 一般に適用、no-drop invariant 違反 |
| **#437** | OPEN (MID) | `disease.drugs.anticoagulation` は dead code | cerebral_infarction 内 grep=0、未 wired YAML field audit も含む |
| **#439** | OPEN (LOW-MID) | sub-rng 分離 (AD-16 pattern for drug selection) | 「今回の解決策ではない、将来 perturbation 防止」、実装時 golden 再生成必須 |
| **#440** | OPEN (MID-HIGH) | patient_cache class of defect (memoize.py 限界 1 と同 class) | **★ 最優先、PR A 起点、A'/A 分割済み、throwaway 実測結果あり** |

### 追記 Issue: 4

| Issue | 追記内容 |
|---|---|
| **#417** | 副次発見 3 (STOP 損失 / dead code / helpers.py 上書き) + (b) 確定 + 2 段構造 + #440 リンク |
| **#418** | offline / local caching (Option C1-C4)、外部サイト可用性 CI 依存 |
| **#428** | 完全書き換え: title / body 全刷新 (LOS 期待値誤認識 → 実論点 (a) UX + (b) discovery gap) |
| **#415** | 実 cohort 実測: HOT7 → medis URI, YJ12 → capstandard URI, mismatch 0 |

## Open Issue 13 の次アクション

| Issue | 次アクション |
|---|---|
| **#440** | ★★ 最優先、user 判断で「進める」= PR A 起点 |
| **#417** | ★ #440 merge 後、PR B 起点 (段 1 fix) |
| **#439** | 実装 PR 時 golden 再生成 (large scope)、緊急性 LOW-MID |
| **#437** | dead code + 未 wired field audit、priority MID |
| **#436** | MAJOR、既存 `OrderStatus.STOPPED` 適用、priority 上 |
| **#433** | structural risk のみ、design 判断 |
| **#431** | POP-000105 hyperglycemia 400+ mg/dL 継続、DKA scenario vs 治療反応 modeling bug 切り分け |
| **#430** | BNP baseline 30.0 vs JP healthy ref、案 α/β/γ の user 判断待ち |
| **#428** | UX 改善 (F1: message 改善 + docs 補強) + discovery gap (F5-F7) |
| **#425** | orphan branch 記録 (session 68 経緯)、対応不要 |
| **#418** | pkg 不在時 silent 劣化 + offline caching + CI 可用性、design 判断 |
| **#415** | 実害なし (per-code dispatch 防波堤)、論理 cleanup は Priority Low 維持 |
| **#378** | JP_Patient_eCS profile missing、Pattern B (3,096 errors)、pre-session 66 backlog |

## Session 70 で得た教訓 (次 session で実際判断を変えるもの)

### ★ 検証は「出力」で測る (内部 state で測ると通ってしまう)

Session 70 中で監督 CC が P3 (「activator + inpatient 両方に排他制約」) を却下した根拠。**内部 list (`patient.current_medications`) で測れば併存 0%、FHIR 出力では warfarin + DOAC が同患者に出る** = 指標は緑、データは壊れている。同種の失敗を防ぐには **emit された FHIR / CIF で測る**。

### ★ 「観測されなかった」は「欠陥が無い」ではない

Session 70 中で私 (worker) が「PE 発現なし」と書いたのを監督が撤回要請。PE 入院が p=3000 seed=300 で 1 件のみ、実 emit 追跡で `discharge_prescription.items` に Warfarin + Edoxaban 両方が入っていることが確認された。**cohort に 0-1 件しか無い場合、「発現なし」は「試験されていない」だけ**の可能性が高い。撤回判断は監督が明示。

### ★ Refactor の証明は byte-identical

PR #435 の refactor commit (`select_with_exclusive_classes` helper 抽出) を独立検証するとき、JP p=3000 seed=300 の NDJSON 5/5 file が byte-identical であることを実測。**数値が動いたら意味が変わっている**、動かないことを実測できない refactor は refactor と呼べない。

### ★ Test 修正は 2 つのコホートで両方 pass すること

PR #438 で test 修正した際、**master と #435 branch (LOS=1 が 0 件 / 2 件) の両方で pass を実測**。片方に合わせて調整したら他方で落ちる = 「実装の意味を捉えた test」でなく「片方コホートに fit させた」ことになる。監督明示の基準、実測完了で送信。

### ★ Throwaway 実装で判定 → discard → clean 確認

Session 70 で #440 A' の judgment 用に `_deactivate_to_layer1` に patient_cache kwarg 追加を throwaway で実装、`pytest` 実行後 `git reset --hard` + branch delete、`git status --short` で clean 確認。**実装は捨てる前提で「判定材料を得るためだけの実装」を積極的に使う**、判定精度が上がる。

## 「記録されているのに放置されていた」欠陥が 3 例

**評価軸が違うと、記録があっても実質的に見えていない** — 次 session でも同じ罠を踏みうるので警戒。

1. **JP-CLINS lab coding 移行項目 #9** (Session 47 記録済み、Session 67 で認識): 移行計画に書いてあるのに実行されなかった
2. **chronic_medications.yaml:105-112 の「benign」コメント** (Session 70 #432 で発掘): `_derive_home_medications` が独立 Bernoulli draw で warfarin+apixaban 併存し得る、YAML 著者は認識しつつ「warfarin-detection purpose では benign」と別評価軸で放置
3. **memoize.py:271-273 の既知の限界 1** (Session 70 #440 で発掘): `_simulate_patient` の chronic in-place mutation が cache hit で消える、test は該当患者を除外して対処、根本 fix は backlog

「YAML に書いてある / docstring に書いてある / test コメントに書いてある」は「認識されている」であって「解決されている」ではない。**次 session で「comment / docstring / notes に記録がある」を見つけたら、それが currently active な問題として扱われているか確認する習慣**を持つ。

## Stray file 2 件の扱い

`.resume-prompt.md` / `resume-prompt.md` の 2 untracked file は Session 69 wrap 時点から存在、作者不明。**Session 70 で私は触っていない、放置**。次 session でも触らない方針を継続してよい (作者不明の file を触らない原則、`session_69_end_state` memo に precedent あり)。

`git status` で毎回 `?? .resume-prompt.md / resume-prompt.md` の 2 行が出るが、これは無視して構わない。commit しない、削除しない。

## Session 70 で得た「作業運用の実践知」

### Ctx 判定は監督 CC 側で行う

私 (worker) が「ctx X% です」と自己申告する手段がない。監督明示「正確に測れないなら不明で構いません、推測値は判断を誤らせる」。次 session でも wrap-up タイミングは監督判断が最終、self-report しない。

### `Refs #NNN` vs `Closes #NNN`

Session 69 R9 (`Closes` は後続語があっても auto-close 発火) 継続有効。**Issue 参照時に close させたくない場合は必ず `Refs #NNN`**。PR A / PR B で #440 / #417 を参照するとき、依存関係の記述で使う `Refs`。

### stress-test config の記録場所

memoize.py:271-273 の「p=600/seed=123/2 か月 advance で発現」の記述が「限界 1 で認識された発現閾値」= 参考実測、A' PR で同 config を使うと類似 stress を試験できる (発現しなかった場合も 「大 config でも pass」を PR body に書く価値あり)。

## 未確認事項

1. **`test_memoize_hit_bit_identical` の p=600/seed=123/2 か月 advance での A' pass/fail**: Session 70 では default config (p=100/seed=42) で throwaway 実測のみ、大 config は未実測。PR A 実装時に実測要
2. **CI Lint (informational) 恒常 fail**: Session 69 で言及済み、master 全体 ruff format 一発 PR を立てる価値あり (別 chore PR、scope discipline 遵守で機能変更ゼロ、内容 format のみ)
3. **#417 段 2 の PR B 単独効果**: PR A merge 前に PR B を実装した場合、cohort 上変化が観測されないことは確認できる (cache が古い profile 返却する)。PR A 未merge で PR B の効果を測ろうとすると誤誘導される
4. **#432 の副次発見 (POP-000593 / POP-000662 等の Warfarin+Apixaban 併用 4 名)**: chronic_medications YAML の population 段階で発生していたが、#432 close で解消 (実測要)。次 cohort 生成時に確認

## PR 作成テンプレート (session 71 用)

PR A / PR B 作成時の body 骨格:

```markdown
## Summary

<PR 目的 1-2 文>

Refs #NNN  ← 参照のみ、close しない
Closes #MMM ← close する場合のみ

## Root cause / 実装内容

...

## Verification

- 実 cohort or unit test の出力を貼る
- byte-identical であれば diff-stat 実測
- pytest -v の tail

## Follow-up

- 別 PR で扱う件
- Documentation 更新
```

**Session 70 で確定**: `Closes #MMM investigation.` のように後続語があっても auto-close 発火する (Session 70 で私が Issue #416 を意図せず close した事故が session 69 wrap 中に発生、resume-prompt R9 として制定)。

## 数値サマリ (Session 70、実測)

| Metric | Value | Evidence |
|---|---|---|
| PR merged this session | 3 | #434 (594a267a71) / #435 (9a30156fd5) / #438 (59ef91c877)、実 git log 一致 |
| Issue filed this session | 6 | #432 (auto-closed by #435) / #433 / #436 / #437 / #439 / #440 |
| Issue appended this session | 4 | #417 / #418 / #428 / #415 |
| open Issue at wrap | 13 | 実測 `gh issue list --state open` |
| Unit tests at HEAD 9a30156fd5 | (未実測、実 pytest 走行時要実測) | 前 PR merge 時 3341 pass |
| Master direct-push detected | 0 | Session 70 内で違反なし |
| New rules distilled | 5 | 上記「教訓」節 |

## Next session start checklist

1. STEP 0 コマンドで master + open PR + open Issue 実測、期待値と突合
2. **PR A (#440 A' Phase 1) に着手**:
   - Branch: `feat/patient-cache-current-meds-sync` 等
   - `_deactivate_to_layer1` に patient_cache 引数追加、10 行変更
   - memoize.py docstring 限界セクションに新項目追記
   - **大 config での stress test** 追加 or 既存 test parametrize
   - `pytest tests/unit/test_engine_memoize.py -v` 実測、大 config が fail する場合は除外 patient 数を実測
   - **AD-66 rule 準拠 goldens 再生成** (`clinosim regenerate-goldens --all` + `--provider mock`)
   - PR body に `Refs #440` (close しない、A' Phase 1 のみ、A / Phase 2/3 は残す)
3. PR A merge 後、**PR B (#417 段 1) に着手**:
   - Branch: `feat/inpatient-anticoag-continuation` 等
   - `_build_discharge_rx` に C1 継承ロジック
   - JP p=3000 seed=300 cohort で warfarin 継承率、day 31+ sub-therapeutic の変化実測
   - PR body に `Refs #417` (close する場合 `Closes #417`、user 判断)

---

**Session 70 wrap 時点**: master `9a30156fd5`、open PR 0、open Issue 13、session 70 で 3 PR merged + 6 Issue filed + 4 Issue appended。#440 A' Phase 1 (PR A) → #417 段 1 (PR B) が session 71 起点最優先タスク。
