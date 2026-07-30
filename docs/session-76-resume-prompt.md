# Session 76 resume prompt

## ★★★ この文書を信じる前に実測せよ

session 68 → 75 と 8 セッション連続で resume-prompt と実測が乖離した実績がある。
**必ず以下を叩き、実測と本文を突合せよ。差分があれば実測が正、本文は破棄。**

```bash
cd /Users/tokuyama/workspace/clinosim
git checkout master
git fetch --prune origin
git pull --ff-only
git log --oneline -6 origin/master
git rev-parse --abbrev-ref HEAD          # ★ 共有 worktree。branch が master とは限らない
git status --short
gh pr list --state open
gh issue list --state open | wc -l
git branch -v                            # ★ 他セッションの残置 branch を確認
```

### session 75 wrap 時点の実測値 (突合対象)

```
master HEAD  4a27a46c38  feat(fhir): emit discharge / outpatient-renewal prescriptions
                         as MedicationRequest (Refs #445)
             ※ 本 resume-prompt の PR が merge されるとその 1 commit が上に乗る

直前 5 (subject 中の close 参照は本 PR が誤リンクを作らないよう**断片ごと削除**している。
        verbatim は STEP 0 の `git log --oneline -6` で取れる):
  499e40e895  docs(session): session 75 resume prompt (#464)
  65e41a19f6  fix(fhir): map authored route abbreviations to SNOMED via a single
              helper (Refs #458) (#463)
  a15a6c1677  fix(disease): guard drug-block route fallback against contradicting
              dose strings (#461)
  f1a7315206  docs(session): update session-74 resume prompt ... (#459)
  34524ba148  fix(disease): declare route "INH" / "SC" on non-oral discharge_oral
              entries (#457)

open PR      0 (本 resume-prompt PR を除く)
open Issue   24
  469 468 467 466 465 462 460 458 452 445 442 440 439 437 436 433 431 430 428 425
  418 417 415 378
```

**local branch `feat/445-discharge-rx-fhir` (`b742cd66ba`) が残置されている。**
これは session 75 の worker のものではない。詳細は「外来 commit」節と Issue #425 の
session 75 comment を読むこと。**merge してはならない。**

`.measure-s74/` `.measure-s75/` `.resume-prompt*.md` `resume-prompt.md` はいずれも
untracked のまま。次セッターが不要と判断すれば削除して構わない。

---

## プロジェクトコンセプト (再開前の primer)

**clinosim** = **population-driven, physiology-based synthetic EHR data simulator**。

```
population 生成 → per-patient physiology state → per-encounter simulation
    → CIF (Clinical Interoperability Format, structural + narrative 2 層)
    → format adapters (FHIR R4 Bulk Data / CSV / narrative)
```

### 設計原則 (CLAUDE.md 参照、超重要)

- **CIF is the only simulation output** (AD-17)。format adapter は CIF のみ読む
- **CIF stores codes only, not display text** (AD-30)。表示は `clinosim.codes` で resolve
- **Two-pass CIF generation** (AD-65): structural = Stage 1 immutable / narrative = Stage 2
- **Base vs Module** (AD-55): near-essential = always-on / specialized = opt-in module
- **Deterministic with seed** (AD-16)、per-order lab RNG isolation (AD-59)
- **LLM calls only via `llm_service`** (AD-11)
- **Silent-no-op 防御 triplet**: canonical constants + `_validate_*` at YAML load +
  `normalize_probabilities(fallback="raise")`
- **Register-based extension** (AD-56): 新 FHIR resource = `register_bundle_builder()`
  または `_BUNDLE_BUILDERS` への追加。**`_build_bundle()` 直接編集は禁止**

必読: `CLAUDE.md` / `docs/design-guides/project-concept-and-design.md` /
`docs/design-guides/implementation-rules.md`

---

## Session 75 の成果 (commit / merge で裏付けられるものだけ)

| 種別 | 内容 |
|---|---|
| **PR merged 1 本** | `#470` → squash `4a27a46c38` |
| **Issue 起票 4 本** | `#466` `#467` `#468` `#469` |
| **Issue comment 1 本** | `#425` に外来 commit の記録 (検出署名つき) |
| auto-close 事故 | 0 (投稿前後で open Issue 24 を実測) |
| master 直 push | 0 |
| Skill / Agent / Workflow 呼び出し | 0 |

### PR #470 — `discharge_prescription.items` を FHIR MedicationRequest として emit

`CIFPatientRecord.discharge_prescription` は CSV adapter と退院サマリ narrative には
届いていたが **FHIR builder が 1 つも読んでいなかった** = CIF→FHIR no-drop invariant 違反。

JP p=300 seed=42 実測: **3,542 items / 765 records** (inpatient 退院 248 / outpatient 更新 3,294)
が CIF に存在して MedicationRequest を 1 件も生んでいなかった。
`MedicationRequest.ndjson` は **487 → 4,029 行**。

**同一 PR に 2 つの gate が別々に効く形にした** (分割しなかった判断根拠は PR body に記載):

| gate | 対象 | 結果 |
|---|---|---|
| 抽出リファクタの正しさ | 既存 487 MedicationRequest 行 | byte-identical |
| feature の正しさ | 追加行 | 3,542 追加 / 想定外 pattern 0 / 他 resource type 不変 |

### session 73 の合意のうち 3 点が実測で無効化された

**次セッターは session 73/74 の Q1-Q7 を「合意済み」として鵜呑みにしないこと。**

| 項目 | session 73 の合意 | session 75 の確定版 |
|---|---|---|
| Q2 `requestIdentifier` | `prescription_id` を round-trip | **builder は書かない**。JP walker が `resource["id"]` から導出し、同 system URI があれば skip するので、手書きすると導出が止まる。なお `prescription_id` は patient-scoped で **137 個が 2-6 record に重複**しており instance 識別子に使えなかった |
| Q4 profile 宣言 | PR-A では宣言せず PR-B で | **builder では制御不能**だった。`_apply_jp_clins_profile` が resourceType キーで全 MedicationRequest に付けている。行単位の filter を足す形に変更 |
| Q5 dosage | `_build_dosage_instruction` に stub を渡す | **その経路は使わない**。`route` が非空だと text-only fallback を通らず structured 経路に入り、**dose 文字列が落ちる** |

`rpNumber` / `orderInRp` は逆に **builder が書く** (walker が作らず JP Core が min=1)。
「identifier は builder では書かない」を文字通り実行すると JP Core 違反になる。

### ★ eCS 主張率の分母 — 「準拠率が下がった」と読まないこと

PR #470 は eCS profile を**主張する行の比率**を下げるが、**実際に準拠している行は増えている**:

| | PR 前 | PR 後 |
|---|---|---|
| MedicationRequest 総数 | 487 | 4,029 |
| eCS を主張し、かつ**実際に準拠** | 487 | **548** (+61) |
| eCS を主張するが**準拠していない** | 0 | **0** |
| eCS を主張せず JP Core に準拠 | 0 | 3,481 |

比率が下がるのは**分母に 3,481 行が加わったから**で、その 3,481 行は PR 前は
**1 行も emit されていなかった**。比較すべきは「JP Core 準拠で emit する」と
「emit しない」であり、後者は主張率 100% を保つが**分母から外しているだけ**。
`feedback_validator_errors_not_quality_metric` (session 67) の
「非準拠かつ**不可視**」を作らない方針に従って可視側を選んだ。**偽の主張は前後で 0 件**。

---

## 未確認事項 (このセッションで確かめきれなかったこと)

### #445 は OPEN のまま (`Refs` で留めた)

主題 (no-drop) は満たしたが、**Issue 本文の提案 2 が未実装**:

> `_fhir_composition` の discharge_summary section で MedicationRequest への reference を持つ
> (`Composition.section.entry`)

実測でも `Composition.section.entry` の参照先は Encounter 54 / DocumentReference 27 /
Condition 27 / Organization 10 で **MedicationRequest 参照は 0**。

### ★ 3,481 行は eCS 非準拠のまま — 将来 Bundle を組む時点で顕在化する

用法情報 (dose / route) を持たない 3,481 行は eCS profile を主張していない。
**現時点では問題にならない**が、`JP_Bundle_CLINS` を組み立てるようになった時点で:

```
JP_Bundle_CLINS の Bundle.entry slicing (spec 実測):
  discriminator: [{ type: "profile", path: "resource" }]
  ordered: true
  rules: "closed"
  slice names: patient / allergyIntolerance / condition / medicationRequest / observationLaboResult
```

discriminator が **profile** なので slice 一致は `meta.profile` で決まり、**closed** なので
どの slice にも一致しない entry は違反。したがって eCS を持たない MedicationRequest は
**closed-slicing 違反**になる (`dosageInstruction min=1` 違反が別の違反に置き換わるだけ)。

その時点の選択肢は **(a) #452 を直して 3,481 行に実 route/dose を持たせる**、
**(b) 用法なし MR を CLINS bundle に入れない** の 2 つ。
**今の方式はこの判断を将来に繰り延べている。**

現時点で到達不能である根拠 (実測): clinosim は **Bundle を 1 つも emit していない**
(Bulk Data NDJSON, AD-31。全出力ファイル走査で Bundle resource 0)。

### 起票した 4 Issue はいずれも未着手

- **#466** CIF の `issue_date` が inpatient で入院時刻 (退院処方の発行日として 7-15 日ずれ)。
  PR #470 は `encounter.discharge_datetime` を使って回避済み。修正案 3 つを Issue 本文に記載
- **#467** `_build_dosage_instruction` の `display_name` fallback が MedicationRequest 経路で
  **到達不能かつ未 localize**。踏むと JP 出力に英語 + 用法欄に薬剤名複製
- **#468** `discharge_datetime` が `admission + dc_hour` の**加算**で算出されており
  (`dc_hour` は 9-16 に clamp されているが時刻でなくオフセットとして使用)、
  退院時刻 **00:56 / 03:44** が出ている
- **#469** disease YAML の `dose:` に散文が混在し JP 出力で部分翻訳になる。
  **実測 9/61 行** (`あたり established regimen` 等)。PR #470 が可視化した残渣

### 外来 commit の実行主体は未特定

local branch `feat/445-discharge-rx-fhir` の 2 commit は session 75 の worker のものではない
(trailer が `Claude Haiku 4.5`、`Claude-Session:` 欠落)。**誰が実行したかは特定できていない。**
peer list の観察は Issue #425 の comment に**推測として明示**してある。断定しないこと。

**この branch を merge してはならない** — commit body に close 動詞 + issue 番号の組が入っており、
merge すると issue が意図せず閉じる。

### 測っていないこと

- **JP-CLINS Bundle 側の spec** は `JP_Bundle_CLINS` / `JP_Bundle_eDischargeSummary` /
  `JP_Composition_eDischargeSummary` の 3 本しか読んでいない。他の Bundle profile は未確認
- **`#469` の修正が既存出力に与える影響** — `med_terms_ja.yaml` は
  `_localize_dosage_terms` / `_localize_drug_name` / `_fhir_procedures` が共有するので、
  entry 追加は byte-diff を伴う。未測定
- **`#468` の修正が LOS / snapshot 境界に与える影響** — RNG 消費順は変わらないと予想したが
  **未検証**

---

## ★ gate 仕様 (次に同種の PR を書くときの形)

「件数だけ見る」実装は不可。PR #470 で使った形:

1. **`(resource_id, field) → value` の写像を集合として突合する** — 件数一致だけだと
   「A が消えて B が増えた」が通る
2. **`baseline ⊆ new` を別途 assert する**
3. **変化を「期待したパターン / 想定外」に分類し、想定外 0 を assert する**
4. **id prefix 別に行集合を分割する**
5. **他 resource type が 1 file でも動いたら止めて報告** — 意図しない乱数消費のサイン

実装例は `.measure-s75/gate_pr_a.py` (untracked)。結果は `.measure-s75/gate-pr-a-result.txt`。
**ただし script を再利用するより仕様から書き直す方がよい** — session 74 が
「durable な資産は仕様であって harness ではない」として promote を却下した判断は今も有効。

コホート生成:
```bash
clinosim simulate -p 300 -s 42 --country JP -o <DIR> \
  --start 2025-01-01 --end 2026-01-01 --format fhir-r4
```

---

## Session 75 の教訓 (実際に判断を変えたもの)

### (q) ★★★ 共有 worktree では「自分が触っていない」から「状態が変わっていない」は導けない

session 75 の worker は STEP 0 (12:21) で master を確認し、13:32 の peer message で
「branch は master のまま」と書いた。その間の 13:26:52 に**別セッションが branch を切っていた**。

worker の**行動**としては真だったが、**tree 状態の主張としては偽**。
共有 worktree では前者から後者は導けない。

**対処**: tree 状態を主張する文を書いたら、**送信直前に**
`git rev-parse --abbrev-ref HEAD` + `git status --short` を実行してから書く。

この誤りは、gate baseline を **branch 由来のコホートで取ってしまう**という実害を生んだ
(master 想定 487 行のはずが 4,029 行だった)。

### (r) ★★★★ 帰属は trailer で確かめる — branch や commit の存在では誰がやったか分からない

supervisor は「branch が切られ commit がある」という**正しい実測**から
「worker が実装した」と**誤って推論**した。共有 worktree ではその推論は成立しない。

**commit trailer が決定的**:

```
外来  : Co-Authored-By: Claude Haiku 4.5 / Claude-Session: なし
正規  : Co-Authored-By: Claude Opus 5 (1M context) / Claude-Session: https://claude.ai/code/session_...
```

`author` / `committer` はどちらも git config 由来なので**区別に使えない**。

補強として「読んだ行番号がどちらの版と一致するか」も使える (branch では構造的に出得ない
行番号を引用していれば、その時点で master を読んでいた証拠になる)。

### (s) ★★★ merge 前の待機は「pending==0 かつ check 数が 2 回連続不変」

期待 check 数を依存グラフから導出する方法 (session 74 の (k)) は、**導出自体が仮定**。
session 75 では 13 と導出したが実際は **14 行**だった (`Deploy to gh-pages` = skipping)。
`len>=13 かつ pending==0` は 13 行の時点で成立し得るので早抜けする。

**不変性の確認の方が頑健**。実装は `.measure-s75/wait_ci_470.sh`。

### (t) ★★★★ spec 実測は builder より下流も見る

session 73 の Q4 は「PR-A では `meta.profile` を宣言しない」だったが、**宣言は builder ではなく
下流の walker が resourceType 単位で行っていた**ので実現不能だった。
**誰も builder より下流を見ていなかった。**

同様に「eCS を外せば制約から逃げられる」も、**base profile (JP Core) を読むまで判定できなかった**
(`dosageInstruction` が JP Core で min=0 だったから成立した。もし min=1 なら不成立)。

**制約を論じるときは、その要素に効く profile を全部読む。**

### (u) ★★★ test が落ちたら、まず判断そのものを再点検する

integration test 1 件が変更前の invariant を符号化していて落ちた。
**「test が落ちたから test を直す」との違いは、代替案を並べ直したかどうか**。

修正するときは:
- **同一ファイル内の先例に合わせる** (このケースでは `_is_lab_observation` による pool 絞り込み)
- **production の predicate を import する** — test 側に第 2 の判定ロジックを作ると語彙が分かれる
- **両側を pin する** — 「除外された」だけを assert すると、除外行が親 profile も失っていても通る
- **除外 pool が空でないことを assert する** — 空になったら経路が無検証になったことが分かる

### (v) ★★★★ ルールを説明する文が、そのルールを破る (session 74 (j) の再確認)

session 75 でも **1 回**発生。Issue #425 の comment に `git reflog` を verbatim 引用したところ、
subject 中の `fix(#N)` が close 動詞 + 番号の組になっていた。
**投稿前の grep 検算で捕まえた。意図では防げていない。**

「証拠を加工しない」原則と衝突するので、**伏せたことを明示する**形で解決した
(無言の再構成はしない)。

書いたら必ず:
```bash
grep -oE '#[0-9]+' <file>
grep -inE '(clos(e|es|ed)|fix(es|ed)?|resolv(e|es|ed))[^.]{0,30}#[0-9]+' <file>
```
投稿後に **open Issue 数が変わっていないこと**も実測する。

### (w) ★★ 測定器バグは「道具の挙動を仮定した」ところから出る

session 75 で 2 件:

1. **zsh の unquoted 変数**: `ruff check $FILES` は単語分割されず 1 パスとして渡って失敗する
   (session 75 の resume prompt に**記録されていたのに踏んだ**)。パスは明示列挙する
2. **macOS の `pgrep -fa`**: command line を出さず bare PID を返す。
   これで「headless claude が稼働中」と誤認しかけた。
   `ps -ax -o pid=,command= | grep ...` で測り直して否定した

**道具の出力形式を仮定せず、1 度は目で確認する。**

### (x) ★★ 「除外できた」の検査範囲を明示する

`pgrep -f "claude -p"` が 0 件でも「他の claude が居ない」ことにはならない。
実測時点で IDE 拡張がホストする claude process が稼働していた。
**検査が何を除外し、何を除外しないかを書く。**

---

## Session 76 の監督へ

- **worktree 共有**: 監督と worker が同一ディレクトリなら working tree を共有する。
  監督の `grep` は **worker が `git checkout` した branch の内容を読む**。master を見たいなら
  `git show master:<path>`。**worker は `git checkout` 前に peer message で事前通告する**
  (session 75 では機能した)
- **帰属を推論しない** — 上記 (r)。**session 75 で監督がこれを誤り、worker が trailer で反証した**。
  「tree に変更がある」から「この worker がやった」は共有 worktree では導けない
- **実測ファイル方式**: worker はリポジトリ内 untracked (`.measure-s7N/`) へ出力を直接
  リダイレクトし、監督が `Read` で読む。**peer message の code fence への転記はさせない**
- **ctx 申告**: 「測れるなら実数、測れないなら『不明』」。session 75 の worker は
  一貫して「不明」と申告した (実数を測る手段がない)
- **merge 条件に job を部分列挙しない**。待機は上記 (s) の不変性条件で
- **番号衛生の事後 grep** — 上記 (v)
- **監督の主張は検証対象**。session 75 では監督の入力の訂正が 3 件
  (commit 帰属 / identifier が walker 由来と builder 由来の 2 系統に分かれる点 / headless 検査の範囲)、
  監督からの訂正・補強が 3 件 (待機条件 / eCS 分母の整理 / #425 を記録先とする判断)。
  **双方向に機能した**
- **規模の大きい task に入る前に状態を確認する** — session 75 は開始 1 時間を
  帰属の解決に使った。実装に入れたのはその後

---

## Session 76 起点 checklist

1. **STEP 0 コマンドで master + open PR + open Issue + branch を実測、本文の想定と突合**
2. 想定外があれば止めて監督報告
3. `CLAUDE.md` + `docs/design-guides/implementation-rules.md` を読む
4. 次候補から選ぶ — **branch 切替は事前通告**
5. `--signoff` 必須 / push 前に **`uvx ruff@0.16.0 format --check <明示列挙したパス>`**
6. **merge は監督承認後**、待機は不変性条件で

### 次候補

| 候補 | 内容 | 規模 | 価値 |
|---|---|---|---|
| **(1) #469** | disease YAML の `dose:` 散文を `note:` に移す + term table 補完 | 小-中 | **PR #470 が可視化した残渣**。JP 出力の英語残渣 9 行が消える。共有 table を触るので byte-diff 確認が要る |
| (2) #445 の残り | `Composition.section.entry` から MedicationRequest への reference | 中 | #445 を閉じられる |
| (3) #466 | CIF `issue_date` の修正 (RNG shift を避ける案 3 が有力) | 小-中 | CIF が誤った値を持たなくなる |
| (4) #467 | `_build_dosage_instruction` の fallback | 小 | 到達不能なので実害 0、再発防止 |
| (5) #468 | 退院時刻 00:56 問題 | 中 | 臨床整合性。LOS / snapshot 境界への影響測定が要る |
| (6) #452 | `current_medications` の dataclass 化 | **大** (3-4 PR) | **本丸**。3,481 行に実 route/dose が乗り、eCS 準拠になり、将来の Bundle 制約も消える |

**(6) が本筋**だが規模が大きい。(1) は session 75 が作った借りを返す形で、
かつ独立して価値がある。

---

## メタ

session 75 は **PR 1 本 merged + Issue 4 本起票 + #425 への記録** で、成果は自立している。
ただし**開始から約 1 時間を、別セッションが同じ worktree で同じ Issue を実装していた事実の
発見と帰属の解決に使った**。この時間は無駄ではなく、
**gate baseline の汚染を実測で発見した**のと、
**trailer による検出署名を確立した**のがその産物。

#445 は `Refs` で留めたので **OPEN のまま**。本丸の #452 は手つかず。

---

**Session 75 wrap 時点**: master `4a27a46c38` (+ 本 resume-prompt PR)。
open Issue 24、open PR 0。auto-close 事故 0、master 直 push 0、
Skill / Agent / Workflow 呼び出し 0。**実測が本文に勝つ。**
