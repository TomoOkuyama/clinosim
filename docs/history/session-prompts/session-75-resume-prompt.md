# Session 75 resume prompt

## ★★★ この文書を信じる前に実測せよ

session 68 → 74 と 7 セッション連続で resume-prompt と実測が乖離した実績がある。**必ず以下を叩き、実測と本文を突合せよ。差分があれば実測が正、本文は破棄。**

```bash
cd /Users/tokuyama/workspace/clinosim
git checkout master
git fetch --prune origin
git pull --ff-only
git log --oneline -6 origin/master
gh pr list --state open
gh issue list --state open | wc -l
git status --short
```

### session 74 wrap 時点の実測値 (突合対象)

```
master HEAD  65e41a19f6  fix(fhir): map authored route abbreviations to SNOMED
                         via a single helper (Refs #458) (#463)
             ※ 本 resume-prompt の PR が merge されるとその 1 commit が上に乗る

直前 5 (subject 末尾の close 参照は本 PR が誤リンクを作らないよう `…` で省略。
        verbatim は STEP 0 の `git log --oneline -6` で取れる):
  a15a6c1677  fix(disease): guard drug-block route fallback against contradicting
              dose strings (Closes …) (#461)
  f1a7315206  docs(session): update session-74 resume prompt ... (#459)
  34524ba148  fix(disease): declare route "INH" / "SC" on non-oral discharge_oral
              entries (Closes …) (#457)
  8090d373c9  docs(session): session 74 resume prompt (#456)
  6413708927  fix(inpatient): drop hardcoded route="PO" from chronic-transcribe (#454)

open PR      0 (本 resume-prompt PR を除く)
open Issue   19
  #462 #460 #458 #452 #445 #442 #440 #439 #437 #436 #433 #431 #430 #428 #425
  #418 #417 #415 #378
```

`.measure-s74/` は **untracked のまま残置**。commit していない。扱いは後述。

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
- **Silent-no-op 防御 triplet**: canonical constants + `_validate_*` at YAML load + `normalize_probabilities(fallback="raise")`
- **Register-based extension** (AD-56): 新 FHIR resource = `register_bundle_builder()`、**`_build_bundle()` 直接編集は禁止**

必読: `CLAUDE.md` / `docs/design-guides/project-concept-and-design.md` / `docs/design-guides/implementation-rules.md`

---

## Session 74 の成果 (commit / merge で裏付けられるものだけ)

| 種別 | 内容 |
|---|---|
| **PR merged 2 本** | `#461` `a15a6c1677` / `#463` `65e41a19f6` |
| **Issue 起票 2 本** | `#460` escalation 非投薬 entry / `#462` duration_days fallback |
| **Issue reopen 1 本** | `#455` — PR #457 が取り落とした同 class 3 entries を発見、`#461` で完全解決して再 close |
| **Issue 追記 3 comment** | `#458` に dual-route 曖昧性 / canonical 置き場所の選択肢 / 語彙 6 系統 |
| **live degenerate 解消** | **text-only route 172 件 → 0 件** (JP p=300 seed=42 実測) |
| auto-close 事故 | 0 |
| master 直 push | 0 |
| Skill / Agent / Workflow 呼び出し | 0 |

### PR #461 — `discharge_oral` の fallback が dose 文字列と矛盾する 3 entries

**#455 は PR #457 で close されていたが、同 class が 3 entries 残っていた。** PR #457 の sibling sweep が **薬剤名に含まれる経路語** (`inhal` / `insulin` / `inject` / `patch` / …) を軸にしていたため、薬剤名から経路が読めない薬を取り落としていた。**経路情報は dose 文字列側にあった。**

| file | country | drug | dose | 修正前 | 修正後 |
|---|---|---|---|---|---|
| `hip_fracture.yaml` | japan | Enoxaparin | `2000IU SC daily` | PO (fallback) | `SC` |
| `hip_fracture.yaml` | us | Enoxaparin | `40mg SC daily` | PO (fallback) | `SC` |
| `vertebral_compression_fracture.yaml` | japan | Denosumab | `60mg SC q6months` | PO (fallback) | `SC` |

再発防止として `clinosim/modules/disease/protocol.py` に **load 時の fallback-relative validation** を追加:

```python
DRUG_BLOCK_ROUTE_FALLBACKS = {"discharge_oral": "PO", "escalation": "IV"}
dose_route_tokens(dose)                   # 単語境界で経路略号を抽出
dose_contradicts_fallback(dose, fallback) # fallback がその集合に含まれないか
_validate_drug_route_consistency(...)     # fail-loud ValueError、loader に配線
```

**設計上の要点 3 つ (次セッターが変更する前に読むこと)**:

1. **load 時であって runtime ではない** — データは全て YAML 由来なので患者 1 人目の生成前に全件判定できる。`_append_item` 内に置くと該当疾患が抽選された時点で初めて落ちる
2. **fallback 相対判定** — `escalation` は `IV` を代入し、**38 entries は dose も `IV` で正しい**。「非経口トークンの有無」で判定すると 38 件が誤発火する。判定は「dose が名指しする経路集合が fallback を除外しているか」のみ
3. **単語境界必須** — 部分一致だと `PRN` 内の `PR` (9 件) と `remaining` 内の `NG` (1 件) で **10 件誤検出**。これは `_determine_route` の `"IV" in "Rivaroxaban"` と同じクラス

検査対象は **reader + fallback がある block のみ**。`first_line` は代入値が `""` (断言していない)、`post_op` / `alternative_penicillin_allergy` / `mrsa_coverage` / `hyperkalemia_management` / `alternative_beta_blocker_contraindicated` は **Python reader が 0** (Refs #437) なので除外。含めると出力に到達しないデータのために build が落ちる。

### PR #463 — route 略号を SNOMED に写像する単一 helper

**live 実測: text-only route 172 件** (MedicationAdministration 166 + MedicationRequest 6、すべて `NEB`)。`166 : 6` の偏りは偶然ではなく、`_ROUTE_SNOMED.get(...)` の lookup が **2 箇所に独立して存在**し同じ欠陥が両方に載ったため。

```python
# clinosim/modules/output/_fhir_reference_data.py
_ROUTE_ALIASES = {"INH": "INHALED", "INHALATION": "INHALED", "NEB": "NEBULIZED"}

# clinosim/modules/output/_fhir_common.py
build_route_concept(raw_route) -> dict | None   # ★ route → SNOMED の単一 lookup 点
```

呼出 2 箇所 (`_build_dosage_instruction` = MR / `_build_medication_admin` = MAR) を helper 経由に統一、`.upper()` を helper 内に取り込み。

**新規 SNOMED code は 0** — alias の target は全て既存 canonical key。`INH`/`NEB`/`INHALATION` は `447694001` "Respiratory tract route (qualifier value)" に着地し、この display は `50ee345b9a` (session 58, chain 4) で tx-server 実測済み。

**`route.text` は作者の値を保持** (`NEB` は `NEB` のまま)。根拠は FHIR 意味論 — `CodeableConcept.text` は元システム自身の表現を置く場所で、`coding` が標準的意味を運ぶ。`INH`/`NEB` は実在の臨床略号なので、合成 EHR としては実際の診療記録に含まれる表記を持つ方が忠実。

---

## ★ route 語彙の現状 (PR-2a 後、master `65e41a19f6` 実測)

**語彙は 6 系統ある。** #458 の残件を把握するのに必要なので、sweep を再実行せずに使えるよう実測値を貼る。

| | 語彙源 | 場所 | 内容 | SNOMED |
|---|---|---|---|---|
| V1 | YAML の `route:` | disease / encounter / locale YAML | 21 種 | — |
| V2 | `parse_dose_string` regex | `clinosim/modules/order/engine.py` | `IM INHALED IV NEBULIZED NG PO PR SC SL TOPICAL` | — |
| V3 | `_determine_route` 返り値 | `clinosim/simulator/helpers.py` | `IM IV PO SC` | — |
| **V4** | **`_ROUTE_SNOMED` key** | `clinosim/modules/output/_fhir_reference_data.py` | `IM INHALED IV NEBULIZED PO PR SC SL TOPICAL` (9) | **✅** |
| V5 | `_parse_dose_for_mar` regex | `clinosim/modules/output/_fhir_common.py` | 上記 V2 から **`NEBULIZED` を欠く** | — |
| V6 | `_ROUTE_JA` key | `clinosim/modules/output/_fhir_localization.py` | `IM INH INHALED IV NG PO PR SC SL TOPICAL` (10) | — |

```
_ROUTE_ALIASES = {'INH': 'INHALED', 'INHALATION': 'INHALED', 'NEB': 'NEBULIZED'}

V1 (21 種) の解決状況:
  coding に解決 (11): IM INH INHALATION INHALED IV NEB PO PR SC SL TOPICAL
  text-only     (10): CATHETER EXTRACORPOREAL LOCAL N/A NASAL
                      NON-PHARMACOLOGIC OTHER PROCEDURAL PROCEDURE TRANSDERMAL

canonical に無い値:
  V2 \ resolvable = ['NG']      ← parser が吐けるが coding が無い
  V5 \ resolvable = ['NG']
  V6 \ resolvable = ['NG']
  V3 \ resolvable = []          ← heuristic は安全
```

### text-only 10 種のうち FHIR に到達するのは 4 種のみ

session 74 の block 別 reader 追跡の結論 (再導出不要):

| YAML block | reader | FHIR 到達 |
|---|---|---|
| `drugs.first_line.<country>[]` | `order/engine.py:358` → `Order.route` | ✅ LIVE |
| `drugs.escalation.<country>[]` | `inpatient.py:1217` → `Order.route` | ✅ LIVE |
| `drugs.discharge_oral.<country>[]` | `inpatient.py:2039` → `discharge_prescription.items[]` | ⚠ CIF のみ (#445 で FHIR 到達予定) |
| encounter `treatment[]` | `emergency.py:240` が `route=` を渡さない | ❌ dead |
| encounter `discharge_prescriptions[]` / `prescriptions[]` | reader 皆無 | ❌ dead |
| `chronic_medications.yaml <ICD>.medications[]` | `_derive_home_medications` が `list[str]` を返す | ❌ route 破棄 (#452) |
| `drugs.post_op` 他 5 block | Python 参照 0 | ❌ dead (#437) |

**LIVE / LIVE-capable な text-only**: `NASAL` (`vertebral_compression_fracture` first_line us) / `CATHETER` (`deep_vein_thrombosis` escalation) / `PROCEDURAL` (`vertebral_compression_fracture` escalation)。いずれも p=300 では未発火 = latent。残りは dead block。

---

## 未確認事項 (このセッションで確かめきれなかったこと)

**「調査済み誤解」を避けるため実測で書く。**

### #445 PR-A — 実装ゼロ、ただし route blocker は解消済み

- 設計合意は **session 73 の Q1-Q7** (`docs/session-74-resume-prompt.md` に完全版)。再導出不要
- **route blocker は session 74 で解消**: PR-A が新規に FHIR 到達させる `INH` は now coded (`build_route_concept('INH')` → `coding=True`)
- **branch 未 create、コード 0 行**
- `dosageInstruction` text-only が JP_MR_eCS validator を通るかは **未検証** (PR-B の gate)
- `eCS_InstitutionNumber` / `eCS_Department` extension を CIF から埋められるかは **未確認** (両者 min=0 だが MustSupport=True)

### #458 残件

- **V1 の import-time validation** 未実装 (reader のある block に限定すること — PR #461 と同じ制約)
- **V2 / V5 の token 突合** 未実装。**`modules/output` ↔ `modules/order` の相互依存を作れない** (CLAUDE.md module independence rule) ため、token を名前付き定数に hoist し **突合は test 層**で行う方針が session 74 で合意済み
- **`NG` が canonical に無い** — V2 / V5 / V6 が知っているのに V4 にない。現状 dose 文字列に単独 `NG` は 0 件で到達不能。**SNOMED code は権威 verify が必要**
- **★ route 日本語表記の SoT が未決** — `_ROUTE_JA` と `_localize_dosage_terms` の 2 経路がある。実測: `NEBULIZED` は `_ROUTE_JA` に entry が無いのに `dosage.text` は正しく「ネブライザー」になる (効いているのは後者)。どちらが single source of truth か決まっていない
- **`_ROUTE_SNOMED` を `clinosim/codes/` へ移す案** — 概念的には正しい置き場所 (国際 code system) だが import を広く触る refactor。#458 に選択肢として記録、未決
- **`_parse_dose_for_mar` の `nebulized` 欠落** (V5 の非対称)。docstring が "avoids importing order engine in adapter" と明記しており **複製は意図的な設計判断**。欠陥は複製が非対称なことであって複製そのものではない

### 新 canonical route の SNOMED code — 権威 verify 未実施

`EXTRACORPOREAL` / `NASAL` / `TRANSDERMAL` / `LOCAL` / `CATHETER` / `PROCEDURAL` / `PROCEDURE` / `NON-PHARMACOLOGIC` / `OTHER` / `N/A` / `NG`

**推測 code を置いてはならない。** fhirserver / tx.fhir.org `$lookup` での per-code 実測が必要 (session 66 で 80288-4 に 4 サイクル消費した教訓)。近い既存 code に寄せるのは silent code substitution で、`SL` に `37161004` (Rectal) を使っていた #311 と同じクラス。

### #460 / #462 — いずれも設計論点、未決

- **#460**: `drugs.escalation` に非投薬 (手技) entry 6 件。**主題は route ではなく resource type** (`Order(MEDICATION)` → `MedicationRequest` として emit される)。6 件は drug code field に `"procedure"` / `"N/A"` marker を持ち、この軸で全 disease YAML を掃引すると該当は 6 件で閉じる。**route だけ直すと「正しい route を持つ手技の MedicationRequest」になってかえって妥当に見える** (session 66 の profile 宣言事例と同型) ので、resource type の設計判断が先
- **#462**: `discharge_oral` の `duration_days` fallback (7) が dose の投与間隔と矛盾する 2 件 (`q6months` の Denosumab / `weekly` の Alendronate)。PR #461 の fallback-relative 検査が一般化できるが、期間表現のパースは route 略号より難しい (実装案 4 つを列挙、未決)

---

## ★ #445 PR-A の gate 仕様 (実装できる粒度)

PR-A は **既存 CIF から追加 emit するだけで乱数を消費しない**はずなので、それを測る。

```
既存 25 NDJSON            → byte-identical (sha256)
MedicationRequest.ndjson  → 既存 ORD-* 行は byte-identical、rxdc-/rxopd- 行のみ追加
```

**検査の形 (これが仕様。件数だけ見る実装は不可)**:

1. **件数比較ではなく `(resource_id, element_index) → value` の写像を集合として突合する** — 件数一致だけを見ると「A が消えて B が増えた」が通る
2. **baseline の集合が new の集合に包含されることを別途 assert する** (`baseline ⊆ new`)
3. **変化を「期待したパターン / 想定外のパターン」に分類し、想定外 0 を assert する** — 「何件変わった」ではなく「期待した種類の変化しか起きていない」を示す
4. **対象外フィールドの不変も確認する** — PR-2a では route 以外の dosage フィールドを JSON 正規化して突合し 0 を確認した
5. **id prefix 別に行集合を分割する** — `ORD-*` の集合が不変、`rxdc-*` / `rxopd-*` が純増であることを別々に見る
6. **他が 1 file でも動いたら止めて報告** — 意図しない乱数消費のサイン

**実例**: PR #461 body (26/26 byte-identical + CIF 1 行のみ変化 + 想定外 0) / PR #463 body (24/24 identical + 172 件の coding 追加 + 既 coded 13,687 件不変、算術 `13206+166=13372` / `481+6=487` も明示)。

コホート生成コマンド:
```bash
clinosim simulate -p 300 -s 42 --country JP -o <DIR> \
  --start 2025-01-01 --end 2026-01-01 --format fhir-r4
```
CSV も必要なら `--format csv` で別 dir に。

---

## ★ 測定スクリプトを commit しなかった理由 (同じ検討を繰り返さないため)

session 74 は `.measure-s74/` に 8 本の `.py` 測定スクリプトを作ったが、**`scripts/` への promote は 0 本**と判断した。次セッターが「測定スクリプトがあれば便利では」と考えて同じ検討を繰り返さないよう、理由を記録する。

### 判断の骨子: **durable な資産は仕様であって harness ではない**

`gate_pr1a.py` (コホート差分 harness) が唯一 promote 候補だったが、分解すると:
- 全 NDJSON の sha256 突合 → 10 行程度の自明なコード
- id 集合の突合・分類 → 中程度

**難しいのはコードではなく「何を検査するか」の知識**で、それは上の「gate 仕様」節に書ける。書けば次セッターは fresh な実装をし、hardcode パスも `discharge_prescription` 固有部分も継承しない。

### スクリプト個別の理由

- **`sweep1_yaml_routes.py` / `sweep5_vocabulary_consistency.py` は STALE**。`_ROUTE_ALIASES` を見ないため、master で走らせると **`INH`(9) `NEB`(4) `INHALATION`(2) を今も unmatched と報告する** (真の値は `45-15=30`)。exit 0 で正しそうな出力が出るので、**壊れているより厄介**。**別 branch 等で入手しても信じないこと**
- **`sweep4_route_key_absence.py` / `sweep10b_regex_boundary.py` は production に取り込み済み**。しかも `sweep4` は独自の token regex を持っており、commit すると同じ検査に語彙源が 2 つできる = **#458 で文書化した「語彙が 6 系統あって誰も突合していない」問題の 7 系統目を自分で作る**ことになる
- **`sweep9_escalation_route.py`** の非投薬判定は heuristic 正規表現。#460 本文の機械的な軸 (drug code field の `"N/A"` / `"procedure"` marker) の方が確実で、script は劣った実装
- **結論はすべて GitHub artifact に残っている** — #458 (3 comment) / #460 / #462 / PR #461 / #463 の body に実測値と表が記載済み。script が提供するのは「再測定」だけ

### `.measure-s74/` の扱い

untracked のまま残置している (session 74 では削除しなかった)。**次セッターが不要と判断すれば削除して構わない。** 中身は 50-150 行のスクリプトと出力 `.txt`、および JP p=300 コホート 3 本 (`route_cohort` / `route_cohort_new` / `route_cohort_pr2a` / `csv_new`)。コホートはディスクを食うので削除候補。

---

## Session 74 の教訓 (実際に判断を変えたもの)

### (j) ★ 裸の `#N` は close 動詞が無くても cross-reference を作る

commit / PR body に `chain #<n>` / `phase #<n>` のような**序数表記**を書くと、GitHub は `#<n>` を issue 番号への参照として解釈し、**無関係な issue のタイムラインに我々の PR が現れる**。close 動詞より踏みやすい。

**実測で確認済み**: `#311` を PR #463 body で「先例」として引いたが、`gh api .../issues/311/timeline` で `closedAt: 2026-07-19` (merge の 11 日前) / `commit_id: null` (手動 close) を確認し、**state は変わっていない**ことを検証した。裸の `#N` は言及だけ作り state は変えない。

運用:
- **序数・識別子には `#` を付けない** (`chain 4` / `phase 2`)
- `#N` を書くのは実際にその issue / PR を指すときだけ
- **書いたら `grep -oE '#[0-9]+'` で全番号を列挙し、1 つずつ意図したものか確認する**
- **close 動詞近接も検査する**: `grep -inE '(clos(e|es|ed)|fix(es|ed)?|resolv(e|es|ed))[^.]{0,30}#[0-9]+'`

### ★★ この rule の説明文自体がこの rule を破る

session 74 で **3 回**起きた:

1. この rule の説明文で、裸の `#N` を**実例の数字で**書いた (issue 2 件への spurious 参照)
2. `git log` の subject を引用したら **close 動詞 + 番号の組**が入った (この文書の「直前 5」ブロック)
3. **(2) を PR body で説明する文が、同じ組を再導入した**

**「気をつける」では防げない。** 番号や close 動詞に言及する文書を書いたら、**書いた後に必ず**上記 2 つの grep を回すこと。

**3 回すべて検算で捕まっており、意図では 1 度も防げていない。** 自分は気をつけるから大丈夫、とは考えないこと — 書いている最中は見えない。事後検算が唯一の防御。

(session 71 の教訓「原則を書くとき自身にも適用する」の一段先。あれは「適用を忘れた」だが、ここで分かったのは **適用しようとしても書いている最中は見えない** という構造。)

### (k) ★ merge 前の 2 段確認 — 「待てば安全」を「なぜ待ち終わったと言えるか」に変える

`gh pr checks` のスナップショットには**まだスケジュールされていない下流 job が写らない**。`integration` は `needs: unit` で gate されているため、Unit が pass するまで check list に存在し得ない。

session 74 で監督が「Unit が pass したら merge」と指示し、それをそのまま実行すると CLAUDE.md の merge blocker 規則 (Integration を含む) に違反する状態だった。

運用:
1. **merge 条件は「CI 全 job pass」と書く。job を部分列挙しない**
2. **依存グラフで期待 check 数を導出し、待機条件に入れる**
```bash
grep -n "needs:" .github/workflows/ci.yml
grep -n "needs:.*integration" .github/workflows/*.yml   # → なし ⇒ integration が最後
# ⇒ 期待 check 数 14 (この workflow の場合)
until [ "$(gh pr checks <N> --json name,bucket | \
  python3 -c 'import json,sys; d=json.load(sys.stdin); print(1 if (len(d)>=14 and sum(1 for x in d if x["bucket"]=="pending")==0) else 0)')" = "1" ]; do sleep 30; done
```
規律に頼らず機構が保証する形。**「pending == 0」だけの待機は Unit pass 直後の窓で抜ける。**

### (l) 監督の指示が CLAUDE.md に反したら CLAUDE.md が勝つ

上記 (k) の merge 条件がまさにこれ。session 74 では worker が止めて報告し、監督が誤りを認めて運用ルールを変更した。**指示をそのまま実行せず、プロジェクト規則との整合を確認する。**

### (m) 単一の観測窓で結論しない — session 74 で 3 回効いた

1. **`git branch -a` に remote branch が残って見えた** → `git ls-remote --heads origin` で実測 → remote 上は削除済み、local の tracking ref が stale だけ。`--prune` で解消。「削除されていない」と誤報告する寸前だった
2. **background 待機 task が「CI 完了」を報告** → task の出力を信用せず `gh pr checks` で再実測してから merge
3. **`#311` の state が CLOSED** → timeline API で closedAt と mergedAt を突合 → 11 日前の手動 close

**自分の道具の出力に対しても「報告を信じない、実測を信じる」を適用する。**

### (n) 測定器バグは 3 種類とも「集計スクリプトの書き方」から出た

session 74 で worker が出した測定器バグ:
1. **glob 重複読み** — `clinosim/locale/*/x.yaml` と `clinosim/locale/shared/x.yaml` を並べ、同一ファイルを 2 回 grep して**全カウントが 2 倍** (`INH` を 8 と報告、実際 4)
2. **country-key 階層の descend 漏れ** — `discharge_oral` を country 別 dict と認識せず全件を `<absent>` と出力 (報告前に自己捕捉)
3. **heredoc 二重 escape** — `python3 - <<'PY'` 内で `r'\\bPR\\b'` と書き、regex が literal backslash になって検証が無効化

**対策**: (1) glob は `ls | sort -u` で展開結果を確認 / (2) YAML は再帰 walk で書く / (3) **regex を含むスクリプトは heredoc でなくファイルに書いて実行する**

### (o) 「重複 = 欠陥」で片付けない

`_parse_dose_for_mar` は `parse_dose_string` の複製だが、docstring が "avoids importing order engine in adapter" と明記しており **module independence を守るための設計判断**。欠陥は複製そのものではなく **複製が非対称になっていること** (`nebulized` 欠落)。同じ場所にある 2 つの問題を分離する。

### (p) 中身が誤っているまま正しさの見た目を足さない

#460 の Hemodialysis は `drugs.escalation` にあるため `MedicationRequest` として emit される。ここで route だけ `EXTRACORPOREAL` に直すと「**正しい route を持つ血液透析という薬剤の MedicationRequest**」になり、**かえって妥当に見える**。現状の `IV` / text-only は欠陥を可視化しており、route だけの修正はその可視性を失わせる。

session 66 で `meta.profile` を MustSupport / slice 充足の verify 前に宣言して cascade regression を招いた事例と同型。**完成度 verify の前に正しさを宣言しない。**

---

## Session 75 の監督へ

session 74 supervisor `5v0qgryj` → session 75 supervisor への引き継ぎ。

- **worktree 共有**: 監督と worker が同一ディレクトリなら working tree を共有する。監督の `grep` は **worker が `git checkout` した branch の内容を読む**。master を見たいなら `git show master:<path>`、branch 跨ぎは `gh pr diff` 等の tree 非依存 API。**worker は `git checkout` 前に peer message で事前通告する**
- **実測ファイル方式**: worker はリポジトリ内 untracked (`.measure-s7N/`) へ出力を直接リダイレクトし、監督が `Read` で読む。**peer message の code fence への転記はさせない** (session 73 で 3 回連続の加工が起きた)。`/tmp` は sandbox 境界で監督から見えないことがあるので repo 内が確実
- **ctx 申告**: **「測れるなら実数、測れないなら『不明』」**。体感 % は書かせない (session 70 で 65-70% 申告 → 実測 35%)
- **merge 前の 2 段確認** — 上記 (k)。**merge 条件に job を部分列挙しない**
- **裸の `#N`** — 上記 (j)。commit / PR body / Issue comment を書いたら全番号を列挙して意図確認させる
- **監督の主張は検証対象** — session 74 では監督の入力の訂正が **6 件** (live 影響 6→172 / route 欠落 43→221 / map 命名説の機序 / PR 分割軸の前提 / 判定式の PO 包含 / merge 条件)、制約の指摘が **1 件** (module independence)、検証中の副産物発見が **1 件** (`INHALED`/`NEBULIZED` の code 同一)。**否定してくれた方が助かる、を明示的に伝える**
- **worker 自身の誤りは 4 件** (根拠記述 1 + 測定器バグ 3、うち 1 件は報告前に自己捕捉)。**worker が自己申告で集計を上方修正した**ので、この数は worker 側の申告を採っている。**誤りの帰属を混同しない** — 混同した記録が残ると次セッションが誤った信頼度で相手を評価する
- **規模の大きい task に入る前に状態を確認する** — session 74 は #445 PR-A (最大の変更) を選ばず wrap した。判断根拠は「ctx 実数が取れないため『あと何ができるか』を根拠づけられず、その状態で最大の変更に入るのは半端に切れるリスクが高い」。**「まだいけます」を期待しない**

---

## Session 75 起点 checklist

1. **STEP 0 コマンドで master + open PR + open Issue を実測、本文の想定と突合**
2. 想定外があれば止めて監督報告
3. `CLAUDE.md` + `docs/design-guides/implementation-rules.md` を読む
4. 次候補から選ぶ (下記) — **branch 切替は事前通告**
5. `--signoff` 必須 / push 前に **`uvx ruff@0.16.0 format --check`** (後述)
6. **merge は監督承認後**

### 次候補

| 候補 | 内容 | 規模 | 価値 |
|---|---|---|---|
| **(1) #445 PR-A** | `discharge_prescription.items` を FHIR MedicationRequest として emit | **大** | **CIF→FHIR no-drop invariant 違反の解消**。route blocker は解消済み、設計合意も揃っている |
| (2) #458 PR-2b | V1 import-time validation + V2/V5 token hoist と test 層突合 + `NG` の扱い | 小 | 再発防止 (live なデータは PR-2a で解消済み) |
| (3) #460 | escalation の非投薬 entry の resource type 設計 | 中 | modeling の正しさ |
| (4) #462 | duration_days fallback | 小-中 | #461 の一般化 |

**session 74 の監督は (1) に傾いていた** (価値が最も高い)。fresh ctx で PR-A 単独に集中するのが想定。

### 開発環境の注記 (コード側の問題ではない)

**local の ruff が 0.15.9、`pyproject.toml` の pin は `ruff==0.16.0`** という乖離がある。`pip install -e '.[dev]'` の再実行が必要な状態。session 74 では `uvx ruff@0.16.0 format --check <paths>` で検証した。

**`ruff format --check .`** をリポジトリ全体に掛けると 0.15.9 では 29 files が reformat 対象と報告されるが、これは version 差由来の既存差分。**自分が触ったファイルだけを pin 版で検査すること。**

なお zsh は unquoted な変数を単語分割しないので、`ruff format $FILES` は 1 パスとして渡って失敗する。**パスは明示列挙する。**

---

## メタ

session 73 wrap 時点の最優先候補だった #445 PR-A は、session 74 では着手していない。代わりに **その blocker だった route 語彙問題を完全に片付けた** (live degenerate 172 → 0、#455 の未解決分を発見して解決、#458 の scope を 13 種 → 実質 5 種に確定)。

session 74 は **PR 2 本 merged / Issue 2 本起票 / #455 の再発見と完全解決 / #458 の scope 確定** で、成果は自立している。#445 PR-A は **設計合意 (session 73 Q1-Q7) + route blocker 解消 (session 74)** が揃った状態で session 75 に引き継がれる。

---

**Session 74 wrap 時点**: master `65e41a19f6` (+ 本 resume-prompt PR)。open Issue 19、open PR 0。auto-close 事故 0、master 直 push 0、Skill / Agent / Workflow 呼び出し 0。**実測が本文に勝つ。**
