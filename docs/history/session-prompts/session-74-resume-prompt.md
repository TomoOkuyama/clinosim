# Session 74 resume prompt

## ★★★ この文書を信じる前に実測せよ

session 68 → 69 → 70 → 71 → 72 → 73 と 5 セッション連続で resume-prompt と実測が乖離した実績。**必ず以下を叩き、実測と本文を突合**:

```bash
cd /Users/tokuyama/workspace/clinosim
git checkout master
git fetch origin
git pull --ff-only
git log --oneline origin/master -8
gh pr list --state open --limit 10
gh issue list --state open --limit 20
```

## STEP 0 期待実測 (session 73 wrap 時点の見込み)

- master HEAD (session 73 の PR #454 merge 時点 + session 73 follow-up PR #457 追加後 + 本 resume-prompt update PR merge 想定): 次セッションが `git log --oneline -8` を叩いた実測ハッシュが真値。session 73 の follow-up (#457 + #458 + この resume-prompt update PR) を含めて 3 個追加された最新 master が session 74 の起点
- 直前 6 (session 73 wave 実 hash):
  - この resume-prompt update PR (hash は次セッションが `git log` で確認、self-reference のため埋め不能)
  - `34524ba148` PR #457 = fix(disease) discharge_oral 非経口薬に route "INH" / "SC" 明示 (Closes #455)
  - `8090d373c9` PR #456 = docs(session) session 74 resume prompt 初版
  - `6413708927` PR #454 = fix(inpatient) chronic-transcribe route hardcode 撤廃
  - `ccebf924b4` PR #451 = fix(csv,outpatient) drug_name fallback + shape 統一
  - `a9f04f4daa` PR #453 = chore(lint) ruff==0.16.0 pin + .md exclude
- **open PR**: session 73 wrap 直後は 0 想定 (#454 merge 済み + resume-prompt PR merged 想定)
- **open Issue**: 17 想定。導出 (session 73 開始時 supervisor 5v0qgryj 実測 = 16 を基準に順次適用):
  - `16` (session 73 開始)
  - `+#450` (session 73 起票) → 17
  - `+#452` (session 73 起票) → 18
  - `-#449` (session 73 PR #453 の Closes で close) → 17
  - `-#450` (session 73 PR #451 の Closes で close) → 16
  - `+#455` (session 73 起票) → 17
  - `#454` は `Refs` のみで close 動詞なし → 変化なし
  - `-#455` (session 73 follow-up PR #457 の Closes で close) → 16
  - `+#458` (session 73 follow-up 起票、`_ROUTE_SNOMED` canonical mismatch) → 17
  - **=17** (session 73 wrap 実測、#457 merge 後の値)
  - 実測が正、本文の想定は破棄せよ
  - open list 予想: 455 / 452 / 445 / 442 / 440 / 439 / 437 / 436 / 433 / 431 / 430 / 428 / 425 / 418 / 417 / 415 / 378

差分あれば実測を優先、本文の「session 73 wrap 時点」前提を破棄せよ。

## ★★★ 最優先候補: Phase 2 (#445) 本体 PR-A

### 前提

**session 73 で proposal step-2 まで完了 (実装ゼロ)**。route 設計問題も **選択肢 (c) で監督承認済み**。次セッションが再導出せず着手できる合意事項を以下に pin する。

### 合意事項 (session 73 supervisor 5v0qgryj 承認)

#### Q1: builder 構成

- **選択肢 B**: 新 helper `_build_discharge_medication_request(item, ...)` を `_fhir_medications.py` に追加。共通 helper (`_localize_drug_name` / `_resolve_jp_drug_system_uri` / `_build_medication_request_meta` / `_build_medication_request_identifiers` / `_build_dosage_instruction`) を既存 `_build_medication_request` と共有 (helper level DRY)
- **`register_bundle_builder()` 経由 (AD-56)** で新 `_bb_discharge_prescription_requests(ctx)` を追加。**`_build_bundle()` 直接編集は禁止**
- 選択肢 A (既存 `_build_medication_request` に adapt) は却下: adapt 側の空値パスが増える (Order 特有 field `clinical_intent`, `status`, `urgency` 等) = session 66 #379 profile cascade regression と同 class の温床

#### Q2: id / identifier 設計

- id 命名:
  - inpatient discharge: `rxdc-{encounter_id}-{seq:02d}`
  - outpatient renewal: `rxopd-{encounter_id}-{seq:02d}`
- 既存 `ORD-*` prefix と衝突なし (session 73 G-3 で通常 cohort 実測、`.measure-s73/q2-existing-ids.txt` に 487 rows 全 `ORD-*` prefix 確認済み)
- identifier[] slice (JP_MedicationRequest_eCS 要求):
  - `rpNumber = "1"` (spec 引用: 「処方箋における剤グループ番号」、discharge_prescription は inpatient Order とは別処方箋、Rp = 1 から振り直しが素直な解釈)
  - `orderInRp = seq` (1-based)
  - `requestIdentifier` (min=1、system=`http://jpfhir.jp/fhir/core/IdSystem/resourceInstance-identifier`) = `PrescriptionRecord.prescription_id` を round-trip (RX-{pid}-DC / RX-{pid}-OPD)

#### Q3: RNG 不変性 (最重要 gate)

**期待**: 既存 CIF から追加 emit するだけで乱数を消費しない。したがって:

- 既存 25 NDJSON = **byte-identical**
- MedicationRequest.ndjson = 既存 `ORD-*` 行が byte-identical、`rxdc-` / `rxopd-` 行だけが追加

**検証手順**:
```bash
mkdir -p .measure-s74/phase2_baseline .measure-s74/phase2_new
# master から baseline
git stash push clinosim/modules/output/{_fhir_medications.py,fhir_r4_adapter.py} 2>/dev/null
clinosim simulate -p 300 -s 42 --country JP -o .measure-s74/phase2_baseline --start 2025-01-01 --end 2026-01-01 --format fhir-r4
git stash pop
# new
clinosim simulate -p 300 -s 42 --country JP -o .measure-s74/phase2_new --start 2025-01-01 --end 2026-01-01 --format fhir-r4
# diff
for f in .measure-s74/phase2_baseline/fhir_r4/*.ndjson; do
  b=$(basename $f); n=".measure-s74/phase2_new/fhir_r4/$b"
  hb=$(shasum $f | awk '{print $1}'); hn=$(shasum $n | awk '{print $1}')
  [ "$hb" = "$hn" ] && echo "IDENTICAL $b" || echo "DIFF $b"
done
# rxdc/rxopd id の追加行が MR.ndjson のみに現れることを assert
diff <(grep -oE '"id":"ORD-[^"]+"' .measure-s74/phase2_baseline/fhir_r4/MedicationRequest.ndjson | sort) \
     <(grep -oE '"id":"ORD-[^"]+"' .measure-s74/phase2_new/fhir_r4/MedicationRequest.ndjson | sort)
# = empty (ORD-* set unchanged)
```

**他リソースが動いたら意図しない乱数消費 → 止めて監督報告**。

#### Q4: JP profile 宣言 → **phased approach**

- **PR-A では `meta.profile` に JP_MedicationRequest_eCS を宣言しない**。text-only dosage + nocoded fallback + expectedSupplyDuration + minimal identifier だけで base FHIR level 通過を目指す
- **PR-B**: PR-A merge 後、実 validator (fhir-jp-validator 等) で validate → pass 確認後に `meta.profile` に JP_MedicationRequest_eCS を追加

**根拠**: session 66 rule 「profile 完成度 verify 後宣言」+ PR #379 反復回避 (v26 で +30k errors、#383 revert 事例)

**JP_MedicationRequest_eCS profile の全 slice inventory は `.measure-s73/q4-ecs-slices.txt` に verbatim** (60 行、67 element 全件)。特に注意:
- extension slice `eCS_InstitutionNumber` / `eCS_Department` = min=0 (optional) だが MustSupport=True — CIF から埋められるかは **未確認** (要調査)
- `medication[x].coding` min=1 required binding VS (codingYJ / codingGeneralName / nocoded) — 既存 `_resolve_jp_drug_system_uri` + `nocoded` fallback を流用可能 (session 59 #291 で実装済み)
- `dispenseRequest.expectedSupplyDuration` の value/unit/system/code 4 field 全て min=1 MS=True — `duration_days` から埋める
- `dosageInstruction` min=1 MS=True — **text-only で通るかは validator 実測必須** (未検証)

#### Q5: dose 自由文字列 → text-only Dosage (parse なし、silent-drop 禁止)

`_build_dosage_instruction` (`_fhir_common.py:542`) は structured field (`dose_quantity` / `dose_unit` / `frequency`) が全 None なら `{text: display_name}` fallback。discharge_rx item はこれらの field を持たないため text-only fallback で emit、regex parse は行わない (session 60 #315 の text-only fallback fail 教訓と同 class 回避)。

Adapter (Q1 選択肢 B の helper 内):
```python
dosage_stub = {
    "display_name": f"{item['drug_name']} {item.get('dose','')} {item.get('route','')}".strip()
}
_build_dosage_instruction(dosage_stub, country=country)
# → {text: "..."} fallback
```

#### Q6: outpatient shape 欠損 vs #450 順序 → **Phase 1 (#450) 先 landing 済**

session 73 で PR #451 (Phase 1) merge 済み。outpatient item shape は `{drug_name, dose, route, duration_days}` に統一済み (dose="" / route="" for chronic sources)。Phase 2 は Phase 1 の上に landing。

#### Q7: 3 PR chain

- Phase 1 (完了、session 73 PR #451): csv_adapter fallback + outpatient shape 統一
- Phase 2 = PR-A: `_build_discharge_medication_request` helper + `_bb_discharge_prescription_requests` bundle builder (profile 宣言なし)
- Phase 2 = PR-B: validator 実測 pass 後に `meta.profile` 追加

### route の取り扱い (session 73 で合意、監督承認)

- **item.route 非空** = disease YAML 由来 (discharge_oral / continue_at_discharge PO-only) → SNOMED coding + text 両方 emit (`_ROUTE_SNOMED[item.route.upper()]` lookup)
- **item.route 空** = 上流損失 or hardcode 撤廃済 (chronic-transcribe / outpatient、session 73 PR #451 + #454 で対応) → `dosageInstruction.route` 要素を emit しない (FHIR R4 の 0..1 に依拠、JP_MR_eCS profile も追加制約なし)

**判定基準**: "空欄は無知だが、誤った断言は虚偽" (#451 で採用済み、CIF layer + FHIR layer に一貫適用)

**副作用**: session 73 wrap 時点の `asthma_exacerbation.yaml` の `discharge_oral` ICS/LABA inhaler 4 行が protocol-authored で route="PO" 継続していたが、**session 73 追加 PR #457 (Issue #455 の (a) YAML fix)** で `route: "INH"` × 2、`diabetic_ketoacidosis.yaml` の Insulin glargine 2 行に `route: "SC"` × 2 を明示追加、解消済み。副次発見として **Issue #458 = `_ROUTE_SNOMED` map に `NEB` / `INH` が無く silent fallback** を起票、Phase 2 前に (4) validation + alias で対応推奨

## Session 73 の教訓 (実際に判断を変えたもの)

### (e) 成果物への転記段でエビデンスに手を入れない

Issue #450 と Phase 2 proposal の code fence で 3 回、私は grep 出力を「読者に説明する形」に加工しました (注釈追加 / 行順再構成)。session 内 3 回連続の pattern。監督が「経路を外す」判断で **`.measure-s73/` 方式** = 出力を file に直リダイレクト、peer message はファイル名と結論のみ、を確立。以後、証拠 fence への転記は避け、file を Read で提示。

### (f) 「自明」を書かず実測を書く

Phase 2 proposal で `FHIR NDJSON 26/26 byte-identical (自明: discharge_prescription を読む FHIR builder なし)` と書いたことに監督が反応: 「正しそうな推論を実測が裏切る」事例が session 内 3 件 (narrative は route を読まない主張 → LLM 経路では読む / head cut 原因説 → 途中欠落は説明できない / #450 read 側 2 箇所説 → 実測 5 箇所)。**「予想通りだった」と書けばよく、「自明」は情報量が違う**。以後、実測してから書く。

### (g) 支持できない機序を書かない、却下案の理由も pin する

route reverse-lookup 案の却下理由 (second SoT / #442 直撃 / #452 Option A で dead code / canonical single source of truth 違反) を commit message と PR body の両方に「Why NOT reverse-lookup」節として明記。将来の読者が同じ検討を一から繰り返さないよう pinned。

### (h) 空欄は無知、誤った断言は虚偽 — CIF + FHIR 2 層一貫適用

session 73 PR #451 (outpatient) と PR #454 (inpatient chronic-transcribe) で採用、Phase 2 の FHIR builder rule (item.route 非空のみ SNOMED emit) にも同基準を適用予定。Phase 3 以降の CIF→FHIR emit で route/dose/frequency を扱う際もこの criterion を継承。

### (i) worktree 共有 = branch 切替は事前通告

session 73 中盤で supervisor と worker が同一 working tree を共有していることが判明 (`/Users/tokuyama/workspace/clinosim`)。branch 切替が supervisor の grep 対象に影響。以後:
- worker が `git checkout` する前に peer message で事前通告
- supervisor は `git show master:<path>` で checkout 回避
- 共有ツリー前提の運用ルールを継続

## 未確認事項 (このセッションで確かめきれなかったこと)

session 68 以降必須節。「調査済み誤解」を避けるため実測で書く:

- **PR-A 実装ゼロ**。proposal 合意まで、実装は次 session。branch も未 create
- **route 設計は合意済みだが FHIR 側の実装は未着手**。session 73 で CIF 層 (PR #451 / #454) は 2 段 fix 完了、FHIR builder への流し方 (item.route 非空のみ SNOMED emit) は proposal で監督承認済みだが code は書いていない
- **`dosageInstruction` text-only が JP_MR_eCS profile validator を通るかは未検証**。PR-B の gate。ローカルでは fhir-jp-validator の binary + tx-server が要り、session 73 では実行していない
- **`eCS_InstitutionNumber` / `eCS_Department` extension を CIF から埋められるかは未確認**。両者 optional (min=0) だが MustSupport=True。CIF `encounter.department` / hospital metadata から埋める設計要 (`.measure-s73/q4-ecs-slices.txt:9-14` に slice 詳細)
- **Issue #455 (discharge_oral asymmetry)** は (a) YAML fix で解決済み (PR #457 merged、`asthma_exacerbation.yaml` に `route: "INH"` × 2、`diabetic_ketoacidosis.yaml` に `route: "SC"` × 2)。派生して **Issue #458 = `_ROUTE_SNOMED` canonical mismatch** を起票、live 6 rows の text-only fallback (NEB) + latent 9 箇所 (INH) が silent drop、CLAUDE.md `Import-time canonical-constants validation` rule 違反。修正案 (1) `_ROUTE_SNOMED` に alias 追加 / (2) YAML 語彙正規化 / (4) route 値の import-time validation、worker 推奨 = (4) + (1) 組合せ、ただし (1) vs (2) は (4) 実装後に選択可能。**未決、監督/user 判断待ち**
- **Issue #452 Option A (current_medications dataclass 化) の実装難度と phasing**: 3-4 PR 予想、影響範囲 (types + activator + inpatient/outpatient + FHIR + memoize snapshot + narrative + test 全 5 test file)、実装コストは #445 完了後の中期 backlog

## 参照ファイル (`.measure-s73/`、untracked、コミットしない選択)

session 73 の全実測ファイル。**次セッションが必要になったら以下のコマンドで再生成可能**:

```bash
# Q1-Q7 proposal 材料
mkdir -p .measure-s73
python3 -c "
import json
sd = json.load(open('/Users/tokuyama/workspace/fhir-jp-validator/tx-server-build/terminology/fhir-server/clinical-information-sharing#1.12.0/package/StructureDefinition-JP-MedicationRequest-eCS.json'))
for e in sd.get('differential',{}).get('element',[]):
    ms = e.get('mustSupport'); m = e.get('min')
    if ms is True or (m is not None and m >= 1):
        print(f\"{e.get('path','')} min={m} max={e.get('max','')} MS={ms} slice={e.get('sliceName','')} fixedUri={e.get('fixedUri','')}\")
" > .measure-s73/q4-ecs-slices.txt

# id 衝突 baseline (通常 cohort)
clinosim simulate -p 300 -s 42 --country JP -o .measure-s73/g3_cohort --start 2025-01-01 --end 2026-01-01 --format fhir-r4
```

または `.measure-s73/` を保持したいなら次 session で `git add -f .measure-s73/` して自作 branch に持ち込み、判断は session 74 worker + supervisor。**session 73 は commit していない**。

## Session 73 の PR / Issue 数値サマリ (実測、merge 反映後)

| Metric | Value | 説明 |
|---|---|---|
| PR merged this session | 4 (#453 `a9f04f4daa` / #451 `ccebf924b4` / #454 `6413708927` / #457 `34524ba148`) + session 74 起点 resume-prompt (#456 `8090d373c9`) + 本 update PR = 6 | ruff pin / drug_name fallback / route hardcode / discharge_oral 非経口薬 route + docs |
| PR opened this session | 4 (#453, #451, #454, resume-prompt PR) | 上記 3 個 + session 74 起点 |
| Issue filed this session | 4 (#450, #452, #455, #458) | csv silent-drop / current_medications root cause / discharge_oral asymmetry / _ROUTE_SNOMED canonical mismatch (session 73 follow-up) |
| Issue appended this session | 0 | |
| open Issue at wrap | 17 想定 | 導出は STEP 0 節参照。実測が正 |
| Auto-close 事故 | 0 | Refs 遵守 |
| 外部 session commit 事故 | 0 | branch checkout 事前通告 rule 適用 |
| Skill / Agent / Workflow 呼び出し | 0 | Bash / Read / Edit / Write / mcp__claude-peers__* のみ |
| session 内で私 (worker) が訂正した監督実測誤り | 3 (`csv_adapter:383`→384 / prescriptions.csv 未出力の誤疑 / `activator.py` パス決め打ちで Issue #452 を誤って疑った件) | supervisor の主張を worker が実測で覆した事例 |
| session 内で監督が指摘した私 (worker) の誤り | 4 (Q6 outpatient MR 誤機序 / `prescription_id` 行番号 2089→2153 / evidence 転記加工 3 回 / Q4 slice inventory 欠落 = extension ブロック 6 行落ちで充足表不完全) | 逆方向 |
| supervisor 自認の追加誤り (指摘は supervisor 自身) | 1 (`discharge_oral` fallback 妥当承認 = `:2148` コメントを別 loop に一般化) | worker の「4 rows out of scope」報告を受けて supervisor が気付き、自己訂正 |
| 新規教訓 | 5 (e)-(i) | 上記記載 |

## Session 74 の監督へ

同じ落とし穴を踏まないための運用事項 (session 73 supervisor 5v0qgryj → session 74 supervisor へ引き継ぎ):

- **worktree 共有**: 監督とワーカーが同一ディレクトリなら working tree を共有する (session 73 で判明: `/Users/tokuyama/workspace/clinosim`)。監督の `grep` は**ワーカーが `git checkout` した branch の内容を読む**。master の内容を見たいなら `git show master:<path>`、branch を跨いだ検証は `gh pr diff` 等の tree 非依存 API を優先。ワーカー側は `git checkout` 前後に peer message で事前通告する運用ルール (session 73 で確立)
- **実測ファイル方式**: ワーカーは `.measure-s73/` のようにリポジトリ内 untracked へ出力を直接リダイレクトし、監督が `Read` で読む。**peer message の code fence への転記はさせない** (session 73 で 3 回連続の加工が起きた: (1) 注釈追加 + 行番号誤り、(2) 行順再構成、(3) `head -10` で 5 行しか出ない cut)。`/tmp` は sandbox 境界で監督から見えないことがあるので repo 内が確実
- **ctx 申告**: 体感% は当てにならない (session 70 で 65-70% 申告 → 実測 35%、session 73 では逆に切迫申告のまま長く走れて 4 PR + 3 Issue を完走)。**「測れるなら実数、測れないなら『不明』」**で運用する。体感% は書かせない
- **worker 誤りと監督誤りの帰属を混同しない**: session 73 で resume-prompt draft の数値サマリで worker と supervisor の誤りが 1 件ずつ入れ替わった。**誤りの帰属が入れ替わった記録が残ると、次セッションが誤った信頼度で相手を評価する**。metrics 表の項目は事実ベースで、書いた側が「誰の誤りか」を実測 (peer log を辿る) で確認してから記載する
- **Refs / Closes の破壊力**: session 71 で「Refs #439」と書いたつもりが GitHub parser が `#439` を close 動詞直後と誤認して auto-close した事故。session 72 (f) rule で「Closes 動詞なし」を Refs-only PR に徹底、session 73 で 4 Issue (#450 / #452 / #455) を Refs-only で起票 auto-close 事故 0。PR body / commit message の草稿は必ず `close|closes|closed|fix|fixes|fixed|resolve|resolves|resolved` の直後の `#NNN` を grep 検算してから push

## Session 74 起点 checklist

1. **STEP 0 コマンドで master + open PR + open Issue 実測、期待値と突合**
2. 想定外あれば止めて監督報告
3. **`git checkout -b feat/discharge-rx-fhir-medicationrequest`** or 適切な名前で branch create、事前通告 (共有 worktree)
4. **PR-A 実装** — 上記合意事項を順守
   - Q1 選択肢 B (helper level DRY + register_bundle_builder)
   - Q2 id 命名 `rxdc-{eid}-{seq}` / `rxopd-{eid}-{seq}`、rpNumber="1"、requestIdentifier=prescription_id round-trip
   - Q3 RNG 不変性 gate = 他 25 NDJSON byte-identical、他が動けば止めて監督報告
   - Q4 profile 宣言なし、PR-B で validator pass 後
   - Q5 text-only dosage、silent-drop 禁止
   - route: item.route 非空のみ SNOMED emit
5. Push 前に監督に事前通告

## メタ (session 73 全体)

session 72 wrap の #445 最優先候補が session 73 で proposal step-2 まで進み、副次的に #442 / #452 / #455 の 3 Issue と Phase 1 (#451) 完了。**Phase 2 本体 PR-A** は session 74 の中核タスク、fresh ctx で proposal 合意事項を単一 branch で完走する想定。

---

**Session 73 wrap 時点** (session 73 follow-up + resume-prompt update 反映後): session 73 中に merged PR は `#453 / #451 / #454 / #457` の 4 個 + `#456` (session 74 起点 resume-prompt 初版) + 本 resume-prompt update PR = 6 個 (実 hash 上記直前 6 リスト参照)。open Issue 17 (実測、内訳は STEP 0 節)。session 74 起点 = **PR-A 実装、合意事項の再導出不要**。session 73 が clean な起点と wrap 後の follow-up を分けて記録している状態。
