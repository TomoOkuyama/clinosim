# Session 72 Resume Prompt

**Date wrapped**: 2026-07-28
**Master HEAD at wrap**: `d84d2af81c` (PR #443 merge commit)
**Session 71 output PR**: #443 (A' Phase 1 patient_cache sync + discharge_rx dedup) — merged.

---

## ★★★ この文書を信じる前に実測せよ

`.resume-prompt.md` 系の resume-prompt は session 68→69 / 69→70 / 70→71 の 3 セッション連続で実測と乖離した事故が続いています。session 71 でも外部セッションによる意図せぬ commit + push が発生しました。**次 session 冒頭で必ず以下を叩き、実測と本文を突合**:

```bash
cd /Users/tokuyama/workspace/clinosim
git checkout master
git fetch origin
git pull --ff-only
git log --oneline origin/master -6
gh pr list --state open --limit 10
gh issue list --state open --limit 20
```

## STEP 0 期待実測 (session 71 wrap 時点、実測値)

- master HEAD: `d84d2af81c feat(simulator): A' Phase 1 — patient_cache.current_medications sync + discharge_rx dedup (Refs #440 / #442 / #439) (#443)`
- 直前 3: `d84d2af81c` (#443) / `8bcb5b09ae` (#441 session 71 resume prompt) / `9a30156fd5` (#435 anticoag exclusive)
- **open PR: 0** (PR #443 merged, session 72 resume-prompt PR は追加予定)
- **open Issue: 14** (実測): `442 / 440 / 439 / 437 / 436 / 433 / 431 / 430 / 428 / 425 / 418 / 417 / 415 / 378`
  - #439 は PR #443 merge 時に **意図せず auto-close された**が、即 reopen 済 (下記「教訓 (f)」参照)

差分あれば実測を優先、本文の「session 71 wrap 時点」前提を破棄せよ。

## ★★★ 最優先タスク: PR B (#417 段 1)

Session 70 の resume-prompt から継承の 2 段構造。**段 2 (patient_cache 同期) は PR #443 (session 71) で解決済み**。段 1 が残タスク。

### #417 の実論点

`_build_discharge_rx` (`clinosim/simulator/inpatient.py:1987`) は現状:
1. protocol の `discharge_oral` の drugs を append
2. `patient.current_medications` の chronic 転記を append

段 1 の欠陥: **入院中に開始された chronic-適応薬** (例 warfarin for atrial_fibrillation_rvr の急性期治療 → 退院後も継続) が (1) にも (2) にも入らない疾患がある:
- `discharge_oral` 未定義な 8 疾患: `cerebral_infarction` / `crush_injury_hand` / `electrical_injury` / `fall_from_height` / `industrial_burn_severe` / `subdural_hematoma` / `traffic_accident_severe` / `wrist_fracture_surgical`
- 別カテゴリの薬 (例 `anticoagulation` として disease YAML に定義されるが `discharge_oral` の書式では書かれない)

### 段 1 実装方針 (単一編集点、C1 = J5 pattern 予防)

**推奨**: `_build_discharge_rx` に「in-hospital 開始の chronic 適応薬 (anticoagulation category 等) を継承する」ロジックを追加。

- **単一編集点**: 新疾患・新薬追加時に 8 疾患 YAML を編集して回らずに済む
- 実装位置は `_build_discharge_rx` の (2) chronic 転記 loop の隣、新しい (1.5) or (3) として
- 検出源: 入院期間中の `record.orders` (medication category) を走査して、chronic-適応の drug_class (anticoagulation / statin / beta-blocker 等) に該当するものを拾う
- 拾う条件: 「discharge_oral に既に載っていない」+「patient.current_medications に元から入っていない」= 新規開始

**却下案 (C5)**: 8 疾患それぞれの `discharge_oral` に薬を追加 = 疾患ごと継ぎ足し = J5 pattern (session 70 で明示的却下)

### 実装後の検証観点

- POP-000257 (session 71 で発掘した atrial_fibrillation_rvr → acute_mi 患者) を含む cohort で:
  - Warfarin 継承率が 1/28 (in-hospital 新規開始 / 段 2 なし) → 大幅改善するか実測
  - Day 31+ の sub-therapeutic INR rate 61% の変化 (Issue #417 body で言及)
- Warfarin+DOAC 併存が発生しないか (session 70 の #435 で修正、退行防止)
- 3+ admission patient (session 71 でスキャン、POP-000773 の 7 admission × 16 items) で累積が起きないか (dedup が既に入っているので理論上ゼロ、実測で確認)

---

## ★★ 外部セッション由来の commit / push 対策

**Session 70 → 71 で 2 セッション連続、無調整の外部 commit + push が発生**。

- session 70→71: 私が resume-prompt を書いてる間に別 CC session が別 branch commit
- session 71 中: **私が作業していた branch (feat/patient-cache-current-meds-sync) に、私が明示的に create していないのに外部 Haiku 4.5 session が commit + push した** (`3987e787e0`、Signed-off-by 無しで DCO fail、force push で復旧が必要になった)

### 運用ルール (session 71 で確立、次 session 以降必須)

1. **作業再開の冒頭**: `git fetch && git log origin/<branch>` で足元確認 (自分の知らない commit が乗っている可能性)
2. **push 直前**: 同 fetch + log で確認、想定外 commit があれば止めて監督報告
3. **想定外の commit を見つけたら**: reflog / commit 内容 / Co-Authored-By / Signed-off-by を確認 → 監督判断待ち (私による rewrite / force push は必ず事前承認)
4. **Force-push は `--force-with-lease` を使う** (`--force` NG、外部の再 push を silent 上書きしうる)
5. **squash + signoff で history rewrite する場合、force push の前に PR body に "commit history note" 節を append** (原 hash は force push で orphan 化、証拠を PR body に残す)

## ★★ Session 71 教訓 (実際に判断を変えたもの)

### (a) 「別 bug、scope 外」と切り分ける前に、自分の変更が原因でないか確かめる

Session 71 前半で「Insulin 重複は A' 前から存在する既存問題、別 Issue で切り出す」と判断しかけた。監督が `_build_discharge_rx` の 2 経路 (protocol + chronic 転記) を実測し、**A' でこそ発生 (2 admission → 2 個、入院ごとに累積、7 admission で 7 個になる)** と反論。dedup を PR A scope 内で実施することが決定。

**教訓**: 副次発見を「既存問題っぽい」で流す前に、grep / 実測で「自分の変更が原因ではないか」を確認する。session 71 では 7 入院までスキャンして累積を実測、監督基準遵守。

### (b) 5 seed の偏りは 10 seed で確認する

Procedure -1 の seed 探索で、最初 5 seed (42/100/200/500/1234) 実測、IMP `{0,-1,0,-3,-1}` / EMER `{0,-7,0,-5,-4}` = 「4 dec / 1 zero / 0 inc」を「系統的減少」と誤判定しかけた。監督指示で 5 seed 追加 (7/77/999/2024/55555)、seed 77 (+1/+8/+3) と 2024 (+4/+24/+22) で明確な増加確認、**5 seed の偏りは cohort size 小の偶然と判明**。

**教訓**: n=5 で片側 5/5 は二項確率 ~3% で「怪しい」だが確定できない。n=10 まで拡張してから系統性を判定。

### (c) 停止基準に当てはめる前に、測っている対象が基準の対象と一致しているか確かめる

「Life event 集合が違う → A' が population 層に到達 → 停止」判定を、**emit された encounter (readmission/ED/calendar 由来含む)** で行い、監督から「それは loop 内の派生 event であって population 層じゃない」と訂正された。生 `generate_monthly_events` (`engine.py:206`) の出力を fingerprint 化して sha256 比較 → 完全一致で population 層 unchanged を確認。

**教訓**: 停止基準のような重要判定は、基準が指す対象と自分の測定対象が同じかを疑う。engine flow を精読し、どのレイヤで測っているか明確にする。

### (d) 支持できない機序を書かない

Procedure IMP/EMER 減の説明として「A' で治療継続効果、readmission 減る」を書きたくなったが、`_evaluate_readmission` grep で medication 参照ゼロと判明。**clinosim では治療継続効果は modeling されていない**。「治療継続効果」と書けば PR body に嘘を書くことになる。代わりに:
- 反証した仮説を反証した事実ごと記録 (「grepped and reviewed, so we could not credit ...」)
- 支持できる観察のみ書く (「方向は対称、10 seed で確認」)

**教訓**: 都合の良い機序が思いつく → まず grep / code trace / 実測で反証確認 → 反証されたら反証済として記録、機序として書かない。

### (f) ★ GitHub auto-close: `keyword` + 直後 `#N` のみ発火、否定形無視、カンマ列は先頭のみ

**PR #443 merge 直後、`Refs #439` にしていたにも関わらず #439 が auto-close された**。真の原因は PR body line 169:

```
Do NOT close #439, #440, or #442 with this PR.
```

GitHub の [linked issue keyword parser](https://docs.github.com/en/issues/tracking-your-work-with-issues/linking-a-pull-request-to-an-issue) は:

1. `close|closes|closed|fix|fixes|fixed|resolve|resolves|resolved` の **直後** の `#N` のみを見る (前後の文脈は無視)
2. **否定形 (`Do NOT`, `does not`) を理解しない**
3. **カンマ区切りの 2 番目以降は解釈しない**

**決定的証拠**: 上記 line 169 は 3 個の Issue (`#439, #440, or #442`) を列挙したが、**#439 だけ close された**。全体 body context で判定していれば #440 と #442 も close されるはず。**非対称の close = parser が `close #439` (keyword 直後の最初の 1 個) のみ捕捉した証拠**。

当初は line 5 の `documented and does not close. A downstream ... instance of #439` を疑ったが、これは keyword と `#439` の間に文が挟まっており parser の captured 対象ではなく、**#439 だけ close の非対称も説明できない** (line 5 説なら 5 と 169 で #440/#442 に効く close もあるはず) — 反証。

対処: 即 reopen (`gh issue reopen 439`)、Issue と PR #443 に correction 済 audit comment 投稿、PR body line 169 を `Issues #439, #440, #442 stay open after this PR` に書き換え。

**Rule (session 69 R9 の一般化)**:

```
✗  Do NOT close #439, #440, or #442        (closes #439; #440/#442 unaffected)
✗  This does not close #442                 (closes #442)
✗  Fix later: #NNN                          (closes #NNN)
✓  #439, #440, #442 stay open
✓  These issues remain open: #439 / #440 / #442
✓  Follow-up work tracked in #NNN
```

- **キーワード直後に close させたくない `#N` を絶対に書かない**。否定形 (`Do NOT close`, `does not close`) も NG (parser 無視)
- カンマ区切りで `#440, #442` を書いても 2 番目以降は捕捉されない = **これは保証ではなく、たまたま助かった** (先頭 `#439` の close で予算消化した副作用)
- **事後策**: merge 直後に `gh issue list --state open` で数え、期待値と乖離があれば即 reopen (`gh issue reopen NNN` + 経緯 comment)

★★ **Rule 化における教訓 (メタ)**: 上記の rule 自体、当初「"close" 単体 keyword + 後続 #NNN で発火」と推定していた。監督が実測で「keyword **直後** の `#N` のみ + カンマ列 2 番目以降無視、#439 だけ close された非対称が証拠」と特定した。**機序の推定は rule 化 phase でも検証対象**。教訓 (d) 「支持できない機序を書かない」を rule 起草時にも適用する。

### (e) 内部 state で testing すると gate が守れない

A' 検証 test の当初案 `assert patient_cache[pid].current_medications` を監督が却下。「patient_cache 実装機構に密着 → 将来 Option C schema 分離で振る舞い正しくても test 落ちる、逆に cache 更新でも consumer 見なければ test 通る」。代わりに **`_generate_home_medication_orders` の出力 (Order.display_name)** を assert、engine 経由 (D 案) で cache-passing gate として機能。

**教訓**: 検証は「出力/観測可能な振る舞い」で。内部 state 検証は「実装機構が変わったら gate 破壊」の脆さと「gate 通過してるが実効なし」の silent-pass 両方を招く。

## Session 71 で発掘・close した状態

### merge 済 PR: 1

| PR | Title | 概要 |
|---|---|---|
| **#443** | `feat(simulator): A' Phase 1 — patient_cache.current_medications sync + discharge_rx dedup` | 3 files 修正 (helpers.py / engine.py / inpatient.py) + 3 test 追加 (unit + integration 2)、+560 lines |

### 新規起票 Issue: 1

| Issue | Title | 状態 |
|---|---|---|
| **#442** | `chore(data-quality): drug_name field mixes bare-name and dose-appended variants (Atorvastatin vs Atorvastatin 10mg) — A' Phase 1 (#440) increases occurrence +67% / +41%` | OPEN、修正案 α/β/γ 併記 (γ には med-reconciliation semantics の caution) |

### 既存 Issue への追記: 1

| Issue | 追記内容 |
|---|---|
| **#440** | Phase 1 完了 (#443 merge)、Phase 2 (memoize-side Layer 2 restoration) 残作業を明記 |

## Open Issue 14 の次アクション (session 72 起点)

| Issue | 次アクション | Priority |
|---|---|---|
| **#417** | ★★ **PR B (段 1) 実装 → PR create** | 最優先 |
| **#440** | Phase 2 = memo run で前 CIF から current_medications 復元 (別 PR) | Backlog、実装は他 PR 依存 |
| **#442** | (a) chronic_medications.yaml 再構造化 or (b) `_derive_home_medications` で dose strip、いずれ選択 | Priority-Low、実害小 |
| **#439** | Drug selection sub-rng 分離 (A' Phase 1 で実害初出、PR #443 body で `Refs #439` 明記) | Backlog、大 golden 影響 |
| **#437** | Dead code (`disease.drugs.anticoagulation`) audit | Backlog |
| **#436** | MAJOR: STOP order intent が CIF→FHIR で損失、既存 `OrderStatus.STOPPED` 適用 | Priority MID |
| **#433** | current_medications lacks re-start after renal-hold (structural risk 記録のみ) | Design 判断 |
| **#431** | POP-000105 hyperglycemia continuation investigation | Investigation |
| **#430** | BNP baseline 30.0 vs JP healthy ref (α/β/γ 案から user 判断待ち) | Design 判断 |
| **#428** | llm-mock regression + regenerate-goldens --all variant hint | UX 改善 |
| **#425** | 記録 (2712c3d28c 外部 push + orphan branch 顕在化) | 対応不要 |
| **#418** | JP-CLINS pkg 不在時 legacy 5 桁 JLAC10 silent 劣化 | Design 判断 |
| **#415** | yj.yaml HOT7+YJ12 混在 (実害小、cleanup Priority Low) | Priority Low |
| **#378** | JP_Patient_eCS profile missing | pre-session 66 backlog |

## Lint (informational) — session 70 の未修正負債 (session 72 候補)

Session 71 の PR #443 CI で `Lint (informational)` が fail。切り分け結果:

```
F541 [*] f-string without any placeholders
   --> tests/integration/test_document_3shift_chain.py:164:13
   --> tests/integration/test_document_3shift_chain.py:165:13
```

**この 2 件は session 70 の PR #438 が持ち込んだもの**であって、無関係な master の負債ではない。Lint が informational であるために merge を通り、session 71 の PR #443 が同じ CI 上で赤いままになった。session 70 の resume-prompt が予告していた「informational Lint を放置すると CI シグナル全体の信頼を損なう」の実証。

PR #443 の scope には含めず、session 72 の候補として明記:
- `f"..."` のうち placeholder が無い 2 行を `"..."` に変更 (ruff `--fix` で自動修正可)
- 併せて他 `test_document_3shift_chain.py` の informational-only fail を掃除
- ruff 0.16.0 で新たに検出される可能性がある他 rule (F541 等) も同時 sweep

optional: 対応時に一発 chore PR で `ruff check clinosim/ tests/` を full clean 状態に戻す (session 71 では時間切れで実施できず)。

## Push 前 checklist (session 71 で成立、次 session でも遵守)

1. `git fetch && git log origin/<branch>` で足元確認
2. `pytest tests/unit tests/integration` で該当変更 + 全 unit+integration 通過
3. `ruff check <changed_files>` + `ruff format --check <changed_files>` = clean
4. commit message に `--signoff` + `Co-Authored-By: Claude <model> <noreply@anthropic.com>` + `Claude-Session:` line
5. `Refs #NNN` (`Closes` は使わない、close させたくない Issue には Refs)
6. Push 前に監督に事前通し (feature branch push でも event 記録の意味で通す)

## Session 71 数値サマリ (実測)

| Metric | Value | Evidence |
|---|---|---|
| PR merged this session | 1 | #443 (`d84d2af81c`) |
| PR opened this session | 1 | #443 |
| Issue filed this session | 1 | #442 |
| Issue appended this session | 1 | #440 (Phase 2 note) |
| open Issue at wrap | 14 | 実測: 442 / 440 / 439 / 437 / 436 / 433 / 431 / 430 / 428 / 425 / 418 / 417 / 415 / 378 (`gh issue list --state open`) |
| Auto-close incidents | 1 | #439 auto-closed by #443 merge, reopened |
| New rules distilled | 6 | 上記「教訓」節 (a)-(f) |
| Unit + integration tests | 2467 passed / 8 skipped / 1 xpassed | pytest -m "unit or integration"、実測 26 min |
| Regression golden tests | 12/12 PASS | tests/regression/、AD-66 rule 1 未適用 |
| External-session commit incidents | **1** (`3987e787e0` on feat/patient-cache-current-meds-sync) | 対策 rule 制定済 |

## Session 72 起点 checklist

1. **STEP 0 コマンドで master + open PR + open Issue 実測、期待値と突合**
2. 想定外あれば止めて監督報告
3. **PR B (#417 段 1) に着手**:
   - Branch: `feat/inpatient-anticoag-continuation` or similar
   - `_build_discharge_rx` に in-hospital 開始 chronic 適応薬継承ロジック追加
   - **単一編集点、C1 一般解** (C5 = 疾患ごと YAML 追加は J5 pattern、却下)
   - 検証: warfarin 継承率大幅改善 / 併存なし / 3+ admission 累積なし
4. **push 前に監督に通す** (session 71 rule)

---

**Session 71 wrap 時点**: master `d84d2af81c`、open PR 0、open Issue 14、session 71 で 1 PR merged (#443) + 1 Issue filed (#442) + 1 Issue appended (#440)。**外部 session commit 事故 1 件 + Refs-only auto-close 事故 1 件、両方復旧、対策 rule 制定 ((f) 追加)**。次 session 起点 = **PR B (#417 段 1) 最優先タスク**。
