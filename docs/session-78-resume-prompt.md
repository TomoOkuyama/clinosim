# Session 78 → 79 resume prompt

★★★ この文書を信じる前に実測せよ

session 68 以降、resume-prompt と実測が乖離した実績が続いている
(s76-s77 で複数件、s78 でも 2 件発見: `.measure-s73/` 消失、`gh pr merge`
の local master 更新挙動)。**必ず以下を叩き、実測と本文を突合せよ。**

```bash
cd /Users/tokuyama/workspace/clinosim
git fetch --prune origin
git log --oneline -5 origin/master
git rev-parse --abbrev-ref HEAD          # ★ 共有 worktree。branch が master とは限らない
git status --short
git branch -v                            # ★ 残置 branch を確認
gh pr list --state open
gh issue list --state open | wc -l       # ★ s78 wrap 時 28
```

### session 78 wrap 時点の実測値 (突合対象)

```
origin/master  f7d2eb893f  docs: fix dangling docs/session-resume/next.md pointer
                           + drop #483 refs (#487)
直前           10908416ba  fix(fhir): route.text follows dual-slot rule (Issue #479) (#484)
               cc6462ff77  docs(todo): point TODO.md at the issue tracker as the live backlog (#485)

open PR    0 本
open Issue 28 本  (s78 で 30 → delete #425/#483 → 28)
  378 415 417 418 428 430 431 433 436 437 439 440 442 445 452 458 460 462
  465 466 467 468 473 474 476 477 481 486
```

### `.gitignore` に入っていない untracked

```
.measure-s74/  .measure-s75/  .measure-s76/     ← 3 世代分の測定 (2.5 GB)
.resume-prompt-organizer.md  .resume-prompt.md  resume-prompt.md
```

**`.measure-s74/75/76/` は今は削除しない。** s78 supervisor 実測で
「open Issue の body 参照は s73 のみ」と分かっているが、**comment は未検査**。
「参照ゼロ」を主張するには comment 走査が要る。急ぐ話ではない、次セッターで判断。

⚠️ **これらは `.gitignore` に入っていない** — `git add -A` を叩くと丸ごと混入する。
path を明示して `git add` すること。

---

# ★★★★ §1 着手前 MUST — 2 件

## (a) #452 / #458 の根拠が消失している

```
#452 body: "詳細は .measure-s73/o-current-medications-*.txt"
#458 body: "詳細は .measure-s73/o-route-*.txt"

$ ls .measure-s73/
ls: .measure-s73/: No such file or directory  ← s76 で消失判明、誰も名乗り出ず放置
```

**両 Issue に「根拠消失」の comment を post 済み** (s78、supervisor 指示による):
- #452: https://github.com/TomoOkuyama/clinosim/issues/452#issuecomment-5175556647
- #458: https://github.com/TomoOkuyama/clinosim/issues/458#issuecomment-5175556782

comment に着手時の再測 recipe を書いた。**Issue 本文の数値を鵜呑みにせず、
着手時に必ず再測**。「Issue が古い」ではなく「**根拠が検証不能**」という
別種の劣化。s73 時点の数値を今の設計判断に流用すると、再現不能な前提の
上に実装が乗る。

## (b) Batch 分類は tentative、着手時に grep で verify

s78 supervisor が Issue タイトル base で作った仮の括り。実測で **2/4 発見**:
- Batch A 内: **#468 → #466** に依存 (両方 `inpatient.py` の「退院時刻の欄に入院時刻」)
- Batch B 周辺: **#458 ↔ #460** 交差 (`route: PROCEDURAL` 2 件は #460 の手技 entry 6 件と同一の可能性、未確認)

**残る Batch C も同様に未検証**。着手前に「同じファイル / 同じフィールドを触る Issue が他にないか」を grep で確認する。**タイトルだけで作った仮の括りを rubberstamp しない**。

具体例:
```bash
# ある Issue が触るシンボル (関数名 / field 名) を対象に
grep -rl "<symbol>" clinosim/
# それらが他 Issue の scope と重なるか
```

---

# ★★★ §2 進行中の事案 — 28 Issue の Batch 分類 (tentative、s78 supervisor)

## Batch A — 独立・低リスク

```
#465  CI docs job の名前と実装の不一致 (--strict が無い)              1 行、独立
#486  mypy strict 6 errors (test file、pre-existing)                  小、独立
#468  discharge_datetime が admission + dc_hour の加算 (7-15 日ずれ)  ★ #466 と同根
#466  退院処方の issue_date が入院時刻                                ★ #468 の後
```

### ★ Batch A 内部依存: #468 → #466 (順序固定)

```
inpatient.py:2165   issue_date = admission_time                       (#466 の実体)
inpatient.py:2417   discharge_datetime = admission_time + timedelta(days=target_los, hours=14)
                                                                      (#468 の実体)
fhir_r4_adapter.py:722  authored_on = discharge_dt or issue_date      (adapter 回避策)
```

- **両 Issue とも「退院時刻の欄に入院時刻を使う」class**
- FHIR adapter は既に `discharge_dt` を優先しており、**FHIR 出力は正しい可能性が高い** (壊れているのは CIF 側)
- **AD-17 違反ではない** (AD-17 は 3 段パイプライン定義、adapter が CIF 補正禁止とは書いていない)
- **実害は AD-58 の前提が崩れる**: 「adapter を 1 つ足すだけで新フォーマットが出せる」= CIF の値が正しいこと。SS-MIX2 / HL7 v2 の adapter を足した人が `issue_date` を素直に読んで入院時刻を出力し、**気付けない**
- 現時点で誤った値を受け取っている消費者は 0 (`csv_adapter` は `issue_date` を使っていない、s78 supervisor 実測)。緊急度は低い、が adapter が増えるたびに罠が発火

**順序**:
1. **#468 (discharge_datetime) を先**: 直さないと #466 が参照する discharge_datetime 自体が誤り
2. **#466 (issue_date) を後**: 同 PR で `authored_on = discharge_dt or issue_date` の回避策撤去まで含める (CIF が正しくなれば adapter が個別補正する理由が消える)

## Batch B — 本丸 (Batch A 完了後、supervisor 相談してから)

```
#452  current_medications list[str] が route/frequency/dose を silent に落とす
      → #442 / #445 / #436 の root (症状先修正は手戻り)
      → 3-4 PR 規模
      → 着手時 proposal 先出し、supervisor 承認後実装
```

`current_medications` の `list[str]` silent drop = Batch B の本丸。
`#442` (name-with-dose)、`#445` (discharge_rx 未 emit)、`#436` (STOP intent)
はすべて症状で、root は `#452`。**症状を先に直すと手戻り**。

## Batch B 周辺: #458 ↔ #460 交差 (未確認、着手時 verify)

`route: PROCEDURAL` (YAML 2 件) は **#460「`drugs.escalation` の手技 entry が
MedicationRequest として emit される」の 6 件と同一である可能性が高い**。
#460 を先に解決すると `PROCEDURAL` が route 語彙から消えるため、
**#458 の by-design 集合が変わる**。

**#458 の実装は #460 の結論後に**。両 Issue の comment に交差情報を post 済み。

## #458 の状態 (5 区分 pin、comment に post 済み)

```
【解決済み・検証済み】 NEB が SNOMED coding を持たない (旧 6/487 rows) →
                       PR #484 の _ROUTE_ALIASES で解消、test で pin (unit 検証済み)

【未検証】             cohort 全体で text-only route が 0 か
                       ★ by-design text-only は PROCEDURAL / CATHETER / NASAL の
                          3 値 / 5 出現のみ (docstring 省略記号は網羅列挙ではない、
                          YAML 実データで埋め直した)
                       「text-only 残 = 欠陥」ではない

【未解決 = 残 scope】  YAML の route 値が import 時 canonical set と照合されて
                       いない。新 route 値を書けば silent に text-only へ落ちる。
                       実装先候補: _validate_route_maps() (PR #484 で新設) の拡張

【★ 依存関係】         #460 との交差 (上記)。#460 の結論後に着手

【副次事項】           _ROUTE_JA["NG"] = "経鼻" は現データで到達不能
                       (route: NG が YAML に 0 件、s78 supervisor 実測)。
                       削除 or 布石として残す判断は着手時
```

## Batch C 以降

JP localization クラスタ (`#473 #474 #476 #477 #481`)、データ品質
(`#467 #462 #460`)、調査系 (`#417 #430 #431 #437 #439 #440 #415 #418 #378
#428 #433`)。**Batch A/B の後に組み直す**。**タイトル base の分類は着手時に
grep で verify** (§1(b) rule)。

---

# ★★★ §3 session 78 の成果

## PR merge / Issue delete / comment post

```
PR #487 MERGED  f7d2eb893f  docs: fix dangling docs/session-resume/next.md
                            pointer + drop #483 refs
                            CLAUDE.md:21 + TODO.md の 4 箇所
                            dangling 完全解消 (CLAUDE.md 11/0, TODO.md 3/0)

Issue delete (revert 不可能 action)
  #425  運用事故記録 (共有 tree 帰属推論、trailer 署名) → memory に集約済み
  #483  CLAUDE.md dangling pointer → PR #487 で欠陥自体は修復
  open Issue 30 → 28

Issue comment post (根拠消失警告)
  #452  Batch B 本丸、着手時再測必須
  #458  5 区分 pin、#460 交差警告

local branch cleanup
  docs/todo-tracking-pointer  (s77 supervisor 誤作成の孤児、cherry-pick 済み)
```

## 番号衛生 / 事故

- auto-close 事故 0 (PR body / commit / comment に `Closes|Fixes|Resolves` 0 実測)
- master 直 push 0
- 共有 tree の branch は動かさず (隔離 worktree で作業)

---

# ★★★★ §4 session 78 の教訓 — 8 規律

s77 の教訓 (定義併記の萌芽) を supervisor が拡張し、s78 で 8 規律に定式化。
**次セッターはこれを default 化する。**

**全体の位置づけ (supervisor formalization)**: 8 規律はすべて
「**相手が独立に確かめられる形にする**」の下位実装。定義併記 → 相手が同じ
定義で数え直せる、足し算検算 → 相手が検算できる、規則の目的 → 反証可能、等。
**検証可能に書くことと、検証されることはセット**。片方だけでは成立しない。

## (1) 定量的主張の直前に「(定義: X)」を添える

例: `link count 3` → `link count 3 (定義: relative path link のみ、
http/anchor/mailto 除外)`。相手が別定義で検算して食い違う (s78 で発生)。

## (2) 数を複数出したら足し算・引き算が合うか確認

例: `4165 + 2661 = 6826 ≠ 6830` (path 限定と全体を並べて誤った、s76)。

## (3) 集計の差を実体の主張に変換しない、変換したければ個別分解

例: `pgrep 6 - list_peers 2 → 未管理プロセス 4` は誤り (s77)。個別に
cwd/親/経過時間を出す。**「原因が 1 つ分かっていて、それで差が全部
説明できるなら、他の原因を探さない」** (s78 supervisor 補足)。

## (4) 規則の目的の適用 (rule でなく rule が守る性質を transitive に)

例: 番号衛生 rule (`Closes` 禁止) の目的は「参照が解決すること」。
参照先 Issue が delete 予定なら `Refs #N` も付けない (s78、rule 適用と
目的適用の分岐点)。

## (5) 省略記号を数として転記しない、実データで埋め直す

例: docstring の `NASAL, NG, CATHETER, …` を「8 値」として転記 → 実測 3 値
(s78、私が (e) 型再発)。**「…」を含む記述を引用するときは、その場で実データ**。

## (6) 「未検証」と書く前に最小検証手段のコストを見積もる

例: 「cohort 生成しないと分からない」→ unit test 30 秒で pin できた
(s78 supervisor 自己訂正)。**「時間かけて cohort 生成」と「unit で 30 秒」を
混同して「未検証」で片付けない**。

## (7) 欠陥告知は「読まれるかもしれない場所」でなく「着手時に必ず通る場所」に置く

例: 「引き継ぎ PR に comment を書けば十分」← 弱い fallback。**引き継ぎ PR の
merge 失敗 / 読まれない risk がある**。Issue comment に post する = 着手時に
必ず通る (s78 supervisor 指示)。

## (8) 掃引の hit は文脈確認してから真偽判定

例: `grep -n "AD-17" resume-prompt.md → 1 hit`
- 一次判定: 「文書に AD-17 の言及がある」← 不十分
- 二次判定: 「その言及が『使用』か『訂正・撤回』か」を context を読んで確認
- 一次だけで報告すると偽陽性

s78 実例: supervisor が resume-prompt の `AD-17` を grep hit で「訂正が反映されて
いない」と報告しかけた。読んだら訂正そのものだった。**掃引結果を content
確認せずに使うと、正しく訂正されているものを「未対応」と扱ってしまう**。

## ★ 補足 — 監督の memory は repo 外にあり、worker からは参照できない

s78 supervisor が「(掃引 hit 文脈確認は) 既存ルール `feedback_check_sibling_bugs_across_modules.md` にある」として worker の提案 (規律 8 追加) を一時的に却下したが、**その根拠は監督の private memory (`~/.claude/projects/-Users-tokuyama-workspace-clinosim/memory/`) にあり、repo (CLAUDE.md / docs/) には存在しなかった**。

構造的注意:
- **監督の memory は repo 外** (`~/.claude/projects/.../memory/`、144 ファイル)、**worker から grep できない**
- **worker / 次セッターが参照できるのは repo だけ** (CLAUDE.md / docs / TODO.md / DESIGN.md / MODULES.md 等)
- **監督が「確立ルール」を引用するときは、repo 内にあるかを確認**する
- **repo に無いなら、それは共有知識ではない** — worker が「再発明しようとする」のは正しい反応

s78 supervisor は自らこの構造的問題を発見し、規律 8 を追加すべきと撤回、amend で本文に入った。**次セッター (別 supervisor と組む場合や、supervisor memory 更新前 state と作業する場合) も同種の混同が起きうる**。「監督が引用したルール、repo に無ければ「共有知識ではない」」を default に。

---

# ★★★ §5 監督 ↔ ワーカーの運用フロー (s77-s78 で確立)

s78 supervisor 実測: これらは規律として repo に記載がなく、監督の memory
のみに存在していた。**記録されない規律は次セッションで再発明されるか失われる**
(s78 で 2 例確認)。ここに pin する。

## 承認は commit hash に紐付く

**supervisor の承認は「その時点の HEAD」に対して出る。** amend / 追加 commit で
hash が変われば、**前の承認は自動的に無効**。再度独立検証と承認が要る。

```
✗ 承認 → amend → 前の承認で merge          ← レビューされていない内容が入る
✓ 承認 → amend → 新 HEAD で再検証 → 再承認 → merge
```

s78 実例: PR #488 で `97307ce3db` 承認後に amend (`c0dbb12d08`) したため、
worker が自ら「前回承認は無効」と申告し、supervisor が新 HEAD で測り直した。

## 実行の主語を明示

```
worker     : 実装 → push → CI 確認 → 「全 pass」を報告
supervisor : 独立検証 (報告を信じず自分で測る) → 承認
worker     : 承認後に merge + Issue close + cleanup
```

**supervisor は merge しない。worker は承認前に merge しない。**
指示文には**実行の主語を明示**する (s76 で同じ行き違いが 5 回発生、
全て指示の書き方が原因)。

## 取り消せない操作は second confirmation

`gh issue delete` / force push / master への直接操作は、**承認と実行の間に
状態が変わっていないこと**を実行直前にもう一度測る。

s78 実例: Issue 削除の直前に supervisor が (1) PR merged (2) master の内容が
検証対象と一致 (3) open Issue 数 (4) **削除対象がまだ存在し、タイトルが一致**
の 4 点を測った。**番号だけでなく中身の同一性を確認する。**

## worker からの質問は supervisor が判断して答える (ユーザー確定、s78)

> ワーカーCCの質問は、監督CCに確認し、監督CCが判断し回答するように。

ユーザーに上げない。**ただし supervisor の判断も検証対象**で、
実測と食い違えば worker が止めてよい (s78 で実際に 4 件、
「gh pr merge が local master を更新しない」「私の Batch 分類は独立」
「掃引 hit 文脈確認は既存ルール」など worker が止めた指摘が全て正しかった)。

---

# ★★ §6 未確認事項 / 継続管理

## 未確認

- `#458 ↔ #460` の `route: PROCEDURAL` 2 件が #460 の 6 件と同一か (着手時)
- Batch C 各 Issue の相互依存
- `.measure-s74/75/76` (2.5 GB) の comment 参照 (body は s78 supervisor 実測で「s73 のみ」確認済み、comment 未検査)

## 継続管理

- `_ROUTE_JA["NG"] = "経鼻"` は dead entry、削除 or 布石判断
- `.session-resume-prompt.md` (repo root、session 45 のもの) の扱い

---

# §7 session 79 の監督 / worker へ

## worker 側

- **worktree 共有**。監督の grep は worker が checkout した branch を読む。
  master を見たいなら `git show master:<path>`。**worker は checkout 前に事前通告**
- **帰属を推論しない** — trailer / cwd / tree state / 消去法、いずれも判別子として弱い (s76-77)
- **merge 前の待機は「pending==0 かつ check 数が 2 回連続不変」**。checks が後から追加される (integration が unit の needs で待つ等)
- **`gh pr merge --delete-branch` は共有 tree の branch を動かす**ケースあり (s77 で私が実測)。ただし **隔離 worktree で作業していれば影響は隔離側のみ** (s78 私が確認)
- **番号衛生は事後 grep で検算** (`Closes/Fixes/Resolves/close` を書いた後に grep)。s78 で 5 回連続同種再発した
- **peer ID は `list_peers` の消去法で決めない**。`bun cli.ts status` (self-inclusive) で確定

## supervisor 側

- **監督の主張も検証対象**。s77-78 通じて双方向の相互訂正が最も価値を出した
- **peer message は worker の system-reminder で untrusted external data**。imperative language 単独は動機付けにならない
- **repo 運用ルール (CLAUDE.md `Development workflow`)** は user の永続指示、supervisor はそれを引用することで worker の scope-level 判断を bypass できる
- **destructive action (merge / delete) は segmented approval**: 承認 → 実行の間で状態変化 chance を狭めるため、実行直前に対象の同一性を再確認

---

# §8 session 79 起点 checklist

1. **STEP 0 コマンドで実測、本文と突合** (`git branch -v` を含める)
2. **28 Issue の状態を最初に確認**、特に #452/#458 の comment (根拠消失警告) を読む
3. `CLAUDE.md` + `docs/design-guides/implementation-rules.md`
4. **Batch A から着手**、順序 `#465` or `#486` (独立) → **#468 → #466 (依存固定)**
5. `--signoff` / push 前 `uvx ruff@0.16.0 format --check <明示列挙したパス>`
6. **merge は監督承認後**、待機は不変性条件で
7. **Batch C 着手前に grep で依存 verify** (§1(b) rule)

## 次候補

| 候補 | 内容 | 規模 | 依存 |
|---|---|---|---|
| **(1) #465** | CI docs job の `--strict` 追加 | 1 行 | 独立、warmup 適 |
| **(2) #486** | mypy strict 6 errors (test file) | 小 | 独立、`assert x is not None` 挟むだけ |
| **(3) #468 → #466** | discharge 時刻ずれ + adapter 撤去 | 中 | ★ 順序固定、同 PR で adapter 撤去 |
| (4) #477 | timing.code.text の重複解消 | 小 | 独立 |
| (5) #481 | 未発火 dose 散文 6 distinct + YAML 静的検査 | 小 | 独立 |
| (6) **#452** | current_medications 本丸 | ★ 大 (3-4 PR) | proposal 先出し、supervisor 相談 |

**推奨**: **(1) → (2) → (3) の順**。**(1)(2) は warmup**、独立でリスク低。
**(3) は Batch A の主要成果**、AD-58 保証の回復まで含める。**(6) は次々 session** ~
(context risk 高い、Batch A 完了後に proposal 段階)。

---

**Session 78 wrap 時点**: origin/master `f7d2eb893f` (STEP 0 で再確認)、
open PR **0**、open Issue **28**。PR merged 1 (#487) / Issue deleted 2 (#425 #483) /
comment post 2 (#452 #458) / branch cleanup 1 (`docs/todo-tracking-pointer` local)。
auto-close 事故 0、master 直 push 0。**未解決は継続管理事項 (§5) のみ**。
**実測が本文に勝つ。**
