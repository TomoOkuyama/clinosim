# ★★★ この文書を信じる前に実測せよ

session 68 → 76 と 9 セッション連続で resume-prompt と実測が乖離した実績がある。
**必ず以下を叩き、実測と本文を突合せよ。差分があれば実測が正、本文は破棄。**

```bash
cd /Users/tokuyama/workspace/clinosim
git fetch --prune origin
git log --oneline -5 origin/master
git rev-parse --abbrev-ref HEAD          # ★ 共有 worktree。branch が master とは限らない
git status --short
git branch -v                            # ★ 残置 branch が 6 本ある。必ず見ること
gh pr list --state open
gh issue list --state open | wc -l
```

### session 76 wrap 時点の実測値 (突合対象)

```
origin/master  23f565bec7  fix(disease): move dose prose to note, keeping YAML
                           comments intact (#480)
直前            e705dc7031  fix(fhir): localize MedicationAdministration.dosage.text
                           on JP output (#475)
                64d9806cfa  docs(session): session 76 resume prompt (#471)

open PR    0 本
open Issue 29 本
  378 415 417 418 425 428 430 431 433 436 437 439 440 442 445 452 458 460 462
  465 466 467 468 473 474 476 477 479 481

★ local master は origin より 2 commit 遅れている (session 76 中 worktree に触れないため
  意図的に pull しなかった)。STEP 0 の `git pull --ff-only` で解消する。

local branch 7 本 (master 含む) — 6 本が残置
  feat/445-discharge-rx-fhir              b742cd66ba   session 75 の外来。merge 禁止
  feat/ci-jp-clins-gate                   60af96ee8d   PR #424 で上位版が着地済。merge すると退行
  fix/469-disease-dose-prose              31ebedda27   PR #478 の中身。close 済。merge 禁止
  fix/469-dose-prose-comment-safe         114f6b2550   merge 済 (#480)。削除可
  fix/472-ma-dosage-text-localize         56586078ae   merge 済 (#475)。削除可
  fix/v3-role-code-nsib-canonical-display d4dc7f4674   PR #368 で着地済。冗長
```

### `git status` に出る untracked について

```
.measure-s74/  .measure-s75/  .measure-s76/     ← 3 世代分の測定ファイル
.resume-prompt-organizer.md  .resume-prompt.md  resume-prompt.md
```

session 74 / 75 / 76 が実測出力を置いた作業ファイル。**内容は各 session の根拠**だが、
tracked にする運用にはなっていない。**不要なら削除してよい。**

⚠️ **これらは `.gitignore` に入っていない** — `git add` されていないから untracked なだけ。
**`git add -A` を叩くと 3 世代分が丸ごと混入する。** path を明示して `git add` すること。

### 参考: resume-prompt の置き場所

canonical は `docs/session-NN-resume-prompt.md` (session 49 以降の慣行)。
本文書は `docs/session-77-resume-prompt.md`。

⚠️ **`CLAUDE.md` の quick-navigation は `docs/session-resume/next.md` を指しているが、
そのファイルは master に存在しない** (実測: `git cat-file -e` で不在)。
`.session-resume-prompt.md` も session 45 のもので stale。
**cold-start でそこを読もうとすると空振りする。** 直すなら別 PR (1 PR = 1 論点)。

---

# ★★★★ §1 進行中の事案 — 最初に読むこと

## 未解決なのは「未管理プロセス」だけ。PR #478 は処理済み

| 事案 | 状態 |
|---|---|
| PR #478 (コメント 364 行消失) | **close 済み**。`#480` で作り直して merge |
| cwd=clinosim を共有する未管理 claude プロセス | **未解決**。下記参照 |
| `31ebedda27` の作成主体 | **未特定**。断定しないこと |

## 済んだ方の記録 — PR #478 で何が起きたか (再発防止のため残す)

`fix/469-disease-dose-prose` (`31ebedda27`) は disease YAML 4 本を
`yaml.safe_load` → `yaml.dump` で round-trip しており、**コメントが全滅していた**。

```
                          master -> commit 31ebedda27
asthma_exacerbation        64 -> 0      (750 -> 1068 行)
copd_exacerbation          93 -> 0      (994 -> 1450 行)
diabetic_ketoacidosis     138 -> 0      (997 -> 1379 行)
pulmonary_embolism         69 -> 0      (807 -> 1155 行)
                         ----------
                          364 行消失
```

失われるものに **Issue #455 の再発防止注記**が含まれる:

```yaml
# master: asthma_exacerbation.yaml:382
route: "INH"   # session 73 Issue #455: matches chronic_medications.yaml
               # convention for inhaled drugs; without this key the
               # `_append_item` fallback at inpatient.py:2039 fills
               # "PO" which falsely asserts oral administration.
```

**値は残るが「なぜ必要か」が消える。** 次に誰かがそのキーを消そうとしたとき、止める理由が無くなる。
他に出典表記 (ESC / JCS / PIOPED II 等) も全消失。

**★ semantic diff では検出できなかった。** YAML を読み込んで木構造で比較すると
**意味の変更は 14 件**しか出ない。コメントはデータではないため。
**編集ツール (`yaml.dump`) と検証ツール (semantic diff) が同じデータモデルの盲点を共有した。**

`git diff --stat` の **4,168/2,662 と意味の変更 14 件の乖離が手がかり**になる。
気付いたらコメント行を数えること。

## 意味の編集自体は正しく、そのまま引き継いだ

`dose:` の散文を `note:` へ移す方向、term 追加は Issue #469 の意図と一致していた。
**PR 全体を捨てる必要はなかった。**

`#480` で master を base に、該当行だけを手編集して作り直した (round-trip 不使用)。
`#478` の 14 件 + `pulmonary_embolism.yaml` の Warfarin (同 class、当該コホートでは未発火) 2 件
+ `as prescribed` の term 1 件 = **17 件**。

## ★ そして `#478` には別の未達もあった — gate が初回で捕まえた

`#478` は `dose: "As prescribed"` を placeholder にしていたが、**これは JP 出力に英語のまま出る**
(4 行)。Issue #469 の目標「JP 出力の英語残渣が消える」を満たしていなかった。
**コメント破壊とは独立した欠陥**で、誰も気付いていなかった。

`#480` では `as prescribed: 指示どおり` を term table に追加して解消し、
**discharge path の Latin 残渣 9 行 → 0 行**を実測している。

## cwd=clinosim を共有する未管理の claude プロセスがある

**確定事実**:

```
episodic-memory plugin 1.4.2 の Claude Agent SDK
  .../plugins/cache/superpowers-marketplace/episodic-memory/1.4.2/node_modules/
  @anthropic-ai/claude-agent-sdk-darwin-arm64/claude --model haiku ...
  cwd    = /Users/tokuyama/workspace/clinosim
  parent = node .../episodic-memory/1.4.2/dist/sync-cli.js
```

**繰り返し spawn され PID が入れ替わる** (session 76 中に 99111 → 15450 → 17695 と観測)。
**PID 単位の kill では止まらない。** 対処は plugin 無効化 / sync 停止 / 権限設定 / cwd 分離 のいずれか。

**シロと判定したもの**: `~/.claude/hooks/vault-session-end.sh` が起動する
`claude -p --model claude-sonnet-5`。hook を読むと `claude` の出力はテキストとして捕捉され、
**書き込みは shell が `~/workspace/obsidian/daily/` に対して行う**。repo には書かない。

## ★ ただし `31ebedda27` の作成主体は未特定

```
31ebedda27 の trailer:
  Co-Authored-By: Claude Opus 5 (1M context)      ← haiku ではない
  Signed-off-by: Tomo Okuyama
  (Claude-Session: なし)
```

**episodic-memory は `--model haiku` なので一致しない。**
「plugin が稼働していた」と「この commit を作った」は別の主張で、**後者は証明されていない**。

session 76 では supervisor が一度「犯人を特定した」とユーザーに報告し、その後訂正している。
**同じ推論 (時間的併発 → 因果) を繰り返さないこと。**

---

# ★★★★ §2 帰属の判別子について (#425 の訂正内容)

session 75 の記録は「**trailer を見れば帰属が判定できる**」としていたが、**これは誤り**。
session 76 で母集団に当てて訂正済み (`#425` に comment、詳細はそちら)。

```
master 全 1,520 commit のうち
  Claude-Session を持つ                            :  949
  Co-Authored-By: Claude* を持ち Claude-Session 欠落:  264   ← 判別子にならない
    うち Claude-Session 慣行の採用前 (2026-06-18〜)  :  220
    うち 採用後                                      :   44   ← 正規 merge。Opus 4.7 が大半
  Haiku 4.5 の co-author                            :    7   ← すべて正規 merge
```

採用後の 44 本には **α-min-2c の 13 連続**、**JP validator fix chain 23 本**が含まれる。
つまり「Claude-Session 欠落」は正規作業でも日常的に起きる。

**代替候補「対応 PR の不在」も、subject 文字列で測ると偽陽性 50%**。
直近 80 commit で subject に PR 番号が無いのは 2 本だが、うち `4a27a46c38` は
**PR #470 として正規 merge**されている (squash subject が別の接尾辞で終わっただけ)。
`gh api repos/<owner>/<repo>/commits/<sha>/pulls` で引くこと。
さらに Issue→PR→Merge 運用は `72e1b4db33` (2026-07-15) からなので、**時期スコープが要る**。

**実効的なのは「各アクターが何をしたか」を establish すること** — reflog の時刻、
worker の tool 実行記録、読んだ行番号が master と branch のどちらと一致するか。

---

# §3 session 76 の成果 (commit / merge で裏付けられるものだけ)

| 種別 | 内容 |
|---|---|
| **PR merged 2 本** | `#475` (MA localize) / `#480` (dose 散文、コメント保持で作り直し) |
| **PR closed 1 本** | `#478` — コメント 364 行消失のため。意味の編集は `#480` が引き継いだ |
| **Issue 起票 7 本** | 解決済み: `#472` `#469` / 未着手: `#473` `#474` `#476` `#477` `#479` `#481` |
| **Issue / PR comment 6 本** | `#425` 訂正 / `#452` Bundle 制約 / `#473` 設計調査 / `#478` 実測指摘 + 数値訂正 |
| auto-close 事故 | 0 (投稿の度に open Issue の番号列を実測) |
| master 直 push | 0 |

## PR #475 — MedicationAdministration.dosage.text の JP localize

MR builder は `_localize_dosage_terms` を通していたのに MA builder は素通しで、
**`dosage.text` を持つ 13,372 行すべてが英語**だった。CLAUDE.md が named precedent とする
**J5 pattern** (処理が 1 venue でしか配線されない)。修正は 1 行。

**同じ関数の中で部分的にだけ配線されていた**のが特徴 — 2 行上の rate note (`:1030`) は
localize 済みで、本体の `dose_text` (`:1032`) だけが放置されていた。

### ★ 回避した落とし穴

`dose_text` **変数そのもの**を localize すると、直下の
`if "CONTINUOUS" in dose_text.upper() or "DRIP" in dose_text.upper()` が
`持続` / `点滴静注` に match しなくなり、**`dosage.rateQuantity` が 488 行から黙って消える**。
代入点だけで localize すること。gate の「他フィールド差分 0」がこれを裏付けている。

### gate (この形を次も使うこと)

```
US 出力  : 25/25 NDJSON byte-identical  ← guard を読むだけでなく US コホートを実生成
JP 出力  : 25/26 byte-identical、差分は MedicationAdministration のみ
同 file  : 行数・id 列一致、dosage.text 以外の差分 0
変化行数 : 13,372 (dosage.text を持つ行の 100%)
変換の質 : 日本語を含まない結果 0 / 単位以外の Latin 残り 0 / 用量値の改変 0
           57 distinct 変換を全件目視
```

---

# §4 起票した 7 Issue の位置づけと依存関係

```
#472  解決済み  MA dosage.text localize          → PR #475
#469  解決済み  dose: の散文                      → PR #480 (実測 9 行 → 0 行)

── 独立して着手できる ──────────────────────────────
#479  route.text が dual-slot rule に反する       13,920 行。単一編集点の見込み
#477  timing.code.text に用量文字列                重複の解消。text 側は不変
#474  Procedure.code.text が英語                   71 件。procedure 名 table が要る (scope 中)
#481  未発火の dose 散文 6 distinct / 9 sites      #469 の残余。★ 下記の注意を読むこと

── 依存あり ───────────────────────────────────
#473  jp_language 軸が Observation しか見ない      設計調査済 (comment 参照)。
                                                   #479 #474 を検出する軸。修正は各 Issue 側
#476  dose_ja field                                #469 の後始末。着手可能になった
```

**`#473` は「検出する仕組み」であって「直す作業」ではない。** 軸を作っても
`#479` `#474` の中身は直らない。段階導入 (既知違反 61,600 件を baseline に持ち
新規増加のみ FAIL) が必須。

## ★★ `#481` と `#473` の関係 — 軸では捕まらない

`#473` の軸は**生成された FHIR を見る**。`#481` の 6 distinct / 9 sites は
**YAML に残っているが p=300 seed=42 では 1 行も出力されない**ので、
**軸をいくら強化しても検出できない**。

`#481` には **YAML 側の静的検査** (全 `dose:` 値を `_localize_dosage_terms` に通し、
英語の機能語が残るものを列挙する) が要る。

session 67 の「非準拠かつ**不可視**」の、さらに一段奥 — **発火しないものは、
出力を見る仕組みでは原理的に見えない**。

**`#452` (`current_medications` の dataclass 化) は依然として本丸**だが 3-4 PR 規模。

---

# §5 未確認事項

- **`#478` をどう処理するかは未決** — 指摘 comment を投稿しただけ。close も revert もしていない
- **`31ebedda27` の作成主体** — 未特定。断定しないこと
- **`Observation.category[].text = 'Survey'` 18,704 件** — `#473` の調査で見つけたが
  **Issue 化していない**。最大の未カバー
- **`ServiceRequest.code.text` / `reasonCode[].text` 計 16,879 件** — 同上、Issue 化していない
- **`ServiceRequest.code.coding[].display` に `'ABG_or_VBG'` `'Total_bilirubin'`** —
  JP 固有 CS に**内部名がアンダースコア付きで漏れている**。code_mapping の穴。Issue 化していない
- **`INHALED` / `NEB` / `NEBULIZED` の 3 表記併存** — `#458` 領域として `#479` 本文に記載のみ
- **`#452` の eCS bucket 移動数** — `dose: ""` にしたとき何行が eCS 保留側へ移るかは**未測定**。
  asthma の 3 行は `route: "INH"` を持つので `dosageInstruction` が emit され続ける可能性がある

---

# ★★★ §6 session 76 の教訓 (実際に判断を変えたもの)

## (y) ★★★★ 測ったつもりのものと、実際に測ったものが違う

session 76 で **6 回**発生。個人の不注意ではなく**型**として扱うこと。

| # | 測ったつもり | 実際に測っていたもの | 誤差 |
|---|---|---|---|
| 1 | 帰属の判別子 (trailer) | 陽性例 2 件の特徴 | 母集団に 264 本の偽陽性 |
| 2 | 「対応 PR の不在」 | subject 文字列 | 偽陽性 50% (2 本中 1 本) |
| 3 | commit 数 | **行数** (`%b` が複数行に展開) | 723 vs 686 |
| 4 | 影響行数 | 正規表現による近似 | 11,298 / 11,318 vs 実測 **13,372** |
| 5 | `extra="forbid"` の適用範囲 | model のトップレベル | **危険の向きが逆** (fail-loud ではなく silent-drop) |
| 6 | dual-slot の先例 | `coding[0]` だけ | Procedure は coding[1] が CPT |

**対策は 1 つ**: proxy を作ったら、**実処理を通した結果と突合する**。
`#472` の影響行数は「localizer を実際に通して text が変化する行を数える」で確定した。

さらに **background の完了通知も proxy**だった — `nohup ... &` をツールの background 内で
起動したため、通知は**ラッパの終了**であって生成本体の終了ではなく、
**書き込み途中のファイルを読んで 2,684 行という誤った値**を得た。
完了条件は mtime 停止 + プロセス不在で確認すること。

## (z) ★★★★ 述語は「無いこと」ではなく「有ること」で書く

`#473` の設計で、当初「Latin 単語が無いか」で JP 出力を検査しようとして破綻した。
`'意識レベル (AVPU)'` `'血清クレアチニン(Cre)'` `'外来経過記録（SOAP）'` はいずれも
**正しいのに Latin を含む**。allow-list を無限に育てることになる。

**正しい述語**: `violation ⇔ (Latin 単語を含む) ∧ (日本語文字を 1 つも含まない)`

allow-list が不要になる。**同じ形が (y) にも通じる** — 「Latin が無い」は
「日本語である」の proxy にすぎない。

## (aa) ★★★ 除外は CodeSystem 単位では粗すぎる

dual-slot rule (`coding.display` = EN canonical / `text` = JP) があるため、
`.display` を一律検査すると仕様どおりの要素が違反に混ざる (実測 97,426 要素)。
かといって **CS 単位で除外すると今度は取りこぼす** — CoreLabo CS は
`coding[].display='Cre'` が by design だが、**同じ analyte の `code.text='Cre'` は defect**。

**slot (`.text` / `.display`) × CodeSystem の 2 軸**で判定すること。

## (bb) ★★★ 「侵入された」と「成果物が使えない」は別

PR #478 は形式が破壊的だが**意味の編集 12 件は正しい**。全部捨てる判断は誤り。
**何が使えて何が使えないかを切り分けてから**処理を決めること。

## (ee) ★★★★ 意図でなく総効果を測る

**PR #478 の事故の本質**: `yaml.dump` はコメントを落とす。**コメントは YAML の
データモデルに存在しない**から。そして検証に使う semantic diff (parse 結果の木構造比較)
**も同じデータモデルで動く**。

⇒ **編集ツールと検証ツールが同じ盲点を共有した。** semantic diff は「変更 14 件」と
**正しく**報告し、作業者は「意図どおり」を確認**できてしまった**。

```
              意図した変更   実際の diff (insertions + deletions)   比
#478  (round-trip)   14 件   4,168 + 2,662 = 6,830 行            488 倍
#480  (手編集)       17 件        44 +    13 =    57 行            3.4 倍
```

**比較の base を間違えると数字が変わる。** 上表は `#478` を**その実際の base**
(`64d9806cfa`) と比べたもの。`origin/master` と比べると `#475` の分が混ざって
`8 files / 4,169 / 2,756` になる。**diff を引用するときは base を明示すること。**

**「意図の検証」は「効果の検証」の代わりにならない。** 何をするつもりだったかを確認しても、
**ついでに何をしたか**は出てこない。

### 標準手順 (機械的にファイルを書き換えたとき)

```
総効果を測る:
  git diff --stat の行数 / ファイル行数 / コメント行数 / 空行数
  ← コメント行数は構造比較からは原理的に消える。別途数えるしかない
  意図した変更点数と桁が合わなければ止まる。

検証は編集と別の表現で行う:
  parse 結果を編集したなら raw text を検証する
  text を編集したなら parse 結果を検証する
  同じ表現で両方やると盲点を共有する。

YAML の機械編集:
  ruamel.yaml の round-trip mode、または該当行だけの手編集。
  yaml.safe_load → yaml.dump は「値を変える」道具ではなく
  「ファイルを作り直す」道具である。
```

### この手順は最初の適用でいきなり成果を出した

`#480` の gate を回したとき、**`dose: "As prescribed"` が JP 出力に英語のまま出る**
ことが分かった (4 行)。**`#478` は Issue #469 の目標を満たしていなかった** —
コメント破壊とは独立した未達で、誰も気付いていなかった。

**gate を先に回していなければ、英語残渣を残したまま「解決」として ship していた。**

### gate の「不変」は proxy — 真の不変則を書くこと

当初の gate は「コメント行数が **64/93/138/69 のまま不変**」だった。しかし `#480` は
変更理由のコメントを追加するので、この形では PASS しない。
**真の不変則は「既存コメントが 1 行も失われていない」** (集合の包含関係)。
行数一致はその proxy にすぎない。

## (cc) ★★ 有利な訂正も訂正として扱う

supervisor の挙げた Procedure の先例は、実測すると**指摘に有利な方向**に誤っていた
(display は日本語ではなく CPT の英語で、dual-slot の例としてより強固だった)。
**自分の主張を補強する方向の誤りも、誤りとして明示する。**

## (dd) ★★ 検証できない主張は出所を書く

`#479` に session 74 の経緯を書く際、当時の議論を直接確認していないため
「supervisor の自己申告に基づく。私は当時の議論を直接確認していない」と明記した。
**将来ログを読める人が検証できる形にする。**

---

# §7 session 77 の監督へ

- **worktree 共有**。監督の `grep` は worker が checkout した branch を読む。
  master を見たいなら `git show master:<path>`。**worker は checkout 前に事前通告する**
- **帰属を推論しない** — §2。session 76 で監督が「犯人を特定した」と報告し、その後訂正している
- **実測ファイル方式** — worker は `.measure-s7N/` へリダイレクトし、監督が `Read` で読む。
  peer message の code fence への転記はさせない
- **merge 前の待機は「pending==0 かつ check 数が 2 回連続不変」**。
  session 76 では 10 check の時点で pending==0 になり得たが、Integration は `needs: unit` で
  後から 14 に増えた。**期待 check 数の導出は仮定**
- **`gh pr merge` は remote 側で完結し worktree に触れない**。branch 切替は不要
- **番号衛生の事後 grep** — 書いた後に close 動詞 + 番号の近接を検算。
  session 74-76 で**説明文自体が違反する再帰**が繰り返し起きている
- **監督の主張も検証対象**。session 76 では監督の入力に 6 件の誤りがあり、すべて worker の
  実測で訂正された。**双方向に機能した**

---

# §8 session 77 起点 checklist

1. **STEP 0 コマンドで実測、本文と突合** (`git branch -v` を含めること)
2. **`#478` の状態を最初に確認** — merge 済みなら §1 は無効、復旧 PR が必要
3. `CLAUDE.md` + `docs/design-guides/implementation-rules.md`
4. 次候補から選ぶ — **branch 切替は事前通告**
5. `--signoff` / push 前 `uvx ruff@0.16.0 format --check <明示列挙したパス>`
6. **merge は監督承認後**、待機は不変性条件で

## 次候補

| 候補 | 内容 | 規模 | 価値 |
|---|---|---|---|
| **(1) #479** | `route.text` を dual-slot rule に合わせる | 小 | 13,920 行。単一編集点の見込み。**#452 と独立**。gate は `#475` `#480` と同型が使える |
| **(2) #481** | 未発火の dose 散文 6 distinct / 9 sites + `per` の文頭誤訳 | 小 | `#469` の残余。**YAML 静的検査**が要る (軸では捕まらない) |
| (3) #477 | `timing.code.text` の重複解消 | 小 | 情報は失われない |
| (4) 未 Issue 化分 | `Observation.category[].text` 18,704 件ほか | 中 | まず Issue 化から |
| (5) #473 | 軸の実装 (段階導入) | 中 | 検出の仕組み。直す作業ではない |
| (6) #452 | `current_medications` の dataclass 化 | **大** (3-4 PR) | **本丸**。ただし環境が安定してから |

**(1) を推奨**。独立していて効果が大きく、gate は `#475` `#480` で 2 回使った形がそのまま流用できる。
(2) は `#469` の残余で小さく、静的検査を test 化すれば同 class の再発を止められる。

---

**Session 76 wrap 時点**: origin/master は `#480` merge 後の実ハッシュ (STEP 0 で確認)、
open PR **0**、open Issue 29。PR merged 2 / PR closed 1 / Issue 起票 7 / comment 6。
auto-close 事故 0、master 直 push 0。**未解決は「未管理プロセス」のみ**。
**実測が本文に勝つ。**
