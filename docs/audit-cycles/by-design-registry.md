# By-Design Registry — Audit-Cycle Detection Exclusions

このドキュメントは、過去の audit cycle で「バグに見えるが実際は仕様通り
(by-design)」と確定した観測を機械可読な形で記録するレジストリです。
次サイクル以降の監査で同じ観測を再度「問題」として提起しないための一次
参照とし、**cycle-N.md へ挙げる前にここを確認**することが必須です。

## 使い方(監査担当への指示)

1. 監査中に「N/total = X%」形の欠損 / 未 coding / 未 populate を検出したら、
   まず本ドキュメントの entry を検索する。
2. Entry の `Signature` に一致する場合は問題として登録しない。cycle-N.md
   に別途 "By-design confirmed (see by-design-registry.md#<slug>)" と一行
   だけ note する(全数を再監査した記録として残す)。
3. Entry の `Signature` に一致しないが同一分野の観測を発見した場合、
   本レジストリの entry を更新するか新規追加を検討する。By-design 判定を
   変更するには **理由 (Signature 変化 / 新臨床要件 / etc.) を明記した
   PR + 元 session PR への back-link** を必須とする(silent drift 防止)。
4. Session 43 以降追加された `docs/design-notes/2026-07-06-fix-point-registry.md`
   の "resolved" 項目と本レジストリは別役割:
   - fix-point-registry = 過去のバグ fix の台帳(歴史)
   - by-design-registry = 現在の by-design 観測の除外リスト(現行仕様)

## エントリ書式

各エントリは以下 6 フィールドを持つ:

```yaml
- id: <short-kebab-case-slug>
  observation: <監査時に見えるもの: "X ndjson has N missing Y">
  by_design_reason: <なぜバグでないか (仕様書 / clinical practice / AD-XX への言及)>
  signature: <この観測を機械的に判定する pattern (regex / count comparison / etc.)>
  established_session: <session N, YYYY-MM-DD>
  established_pr: <commit / PR ref>
  revalidation_check: <次回、依然として by-design であることを確認する簡易 check>
```

---

## Entries

### snapshot-truncated-in-progress-encounter-length

- **id**: `snapshot-truncated-in-progress-encounter-length`
- **observation**: `Encounter.ndjson` の 1 件以上で `length` field 欠落。
- **by_design_reason**: AD-32 スナップショット意味論。`--end` を過ぎた入院は
  `status = "in-progress"`、`discharge_datetime = None` となり、
  ISO 8601 `length` を計算できないため意図的に省略。FHIR R4
  `Encounter.length` は 0..1 で、in-progress encounter で欠落しても spec 適合。
- **signature**: `sum(1 for e in encounters if "length" not in e and e.get("status") == "in-progress")` が **全 length 欠落の総数と一致**。もし `status != "in-progress"` かつ length 欠落があれば本レジストリ対象外 = 真のバグ。
- **established_session**: session 44, 2026-07-11 (Chain 1 verify)
- **established_pr**: `2dcde6497d` chain 1 wrap
- **revalidation_check**: JP p=200 seed=42 で `Encounter.length missing` 全件が `status = in-progress` であることを確認。

### inpatient-mr-substitution-omitted

- **id**: `inpatient-mr-substitution-omitted`
- **observation**: `MedicationRequest.ndjson` で `substitution.allowedBoolean` が 一部(概ね 45–55%)欠落。
- **by_design_reason**: JP 病棟 dispensing 慣行 = 銘柄指定・後発品置換不可。
  `_fhir_medications.py` は `intent == "instance-order"` (慢性外来処方) のみ
  `substitution` を emit、`intent == "order"` (入院オーダー) では意図的に
  omit。FHIR R4 `MedicationRequest.substitution` は 0..1。
- **signature**: 欠落した MR の `intent` field を全数集計し、**全て `"order"`**(すなわち `"instance-order"` を持つ MR は 100% substitution 付き)であること。
- **established_session**: session 44, 2026-07-11 (Chain 1 verify)
- **established_pr**: `2dcde6497d`
- **revalidation_check**: `intent == "instance-order"` の MR で substitution 欠落 = 0 件、`intent == "order"` の MR で substitution 有 = 0 件。

### coverage-class-plan-omitted-for-late-elderly-insurer

- **id**: `coverage-class-plan-omitted-for-late-elderly-insurer`
- **observation**: `Coverage.ndjson` の一部 (概ね 15–25%) が `class[].type.coding[].code == "plan"` の entry を持たない。
- **by_design_reason**: JP 後期高齢者医療広域連合 (75 歳以上) は保険者番号 (group) のみで **記号 (symbol / plan) を持たない**(制度上)。`_fhir_patient.py:170-200` は `symbol` が truthy の時のみ plan entry を emit するため、後期高齢者 coverage には plan が付かない。
- **signature**: plan 欠落の Coverage を全数抽出し、その `payor` / class[0].name が「後期高齢者医療広域連合」を含むこと。他の insurer type で plan 欠落があれば本レジストリ対象外。
- **established_session**: session 44, 2026-07-11 (Chain 1 verify)
- **established_pr**: `2dcde6497d`
- **revalidation_check**: plan 欠落 Coverage の class[0].name が全て「〇〇後期高齢者医療広域連合」pattern に一致。

### fmh-onsetstring-omitted-for-healthy-relatives

- **id**: `fmh-onsetstring-omitted-for-healthy-relatives`
- **observation**: `FamilyMemberHistory.ndjson` の一部 (概ね 15–20%) で `condition[].onsetString` が欠落。
- **by_design_reason**: `_fhir_family_history.py:81-91` は relative の `condition_codes` が空の場合 `condition[]` を emit しない。従って onsetString を attach する対象自体がない。健常な relative(疾患履歴無し) = clinically-realistic。FHIR R4 `FamilyMemberHistory.condition` は 0..*。
- **signature**: onsetString 欠落 FMH で `"condition" not in resource`(そもそも condition array が存在しない)であること。`condition` array があるのに onsetString が欠落 = 真のバグ(本レジストリ対象外)。
- **established_session**: session 44, 2026-07-11 (Chain 2 verify)
- **established_pr**: `1481306d2f`
- **revalidation_check**: onsetString 欠落全 FMH で `"condition" not in resource` を確認。

### co8-non-jp-marketed-drugs

- **id**: `co8-non-jp-marketed-drugs`
- **observation**: `MedicationRequest.ndjson` の 4 前後の記録が YJ code を持たない(text-only)。
- **by_design_reason**: 該当 drug (2026-07-11 時点で Cyclobenzaprine / Phenazopyridine) は 日本 薬価基準未掲載 (imported / OTC / withdrawn)。No-fabrication policy (session 40 確立) により、authoritative code 未確認の drug には code を emit しない。
- **signature**: uncoded MR の drug name (medicationCodeableConcept.text の base name / normalized form) が以下 whitelist に含まれること:
  - "シクロベンザプリン" / "Cyclobenzaprine"
  - "フェナゾピリジン" / "Phenazopyridine"
  他の drug で uncoded が発生した場合 = 真のバグ(MHLW lookup 追加が必要)。
- **established_session**: session 44, 2026-07-11 (Chain 4 CO-8)
- **established_pr**: `2c5e79b974`
- **revalidation_check**: uncoded MR の text が全て上記 whitelist の subset に一致することを確認。増減があれば registry を update。

### hba1c-value-as-stage-text

- **id**: `hba1c-value-as-stage-text`
- **observation**: `Condition.ndjson` の糖尿病 (E11 / E10) で `stage.summary.text` が `"HbA1c X.Y%"` 形式 (例: `"HbA1c 7.5%"`) で `coding` を持たない。
- **by_design_reason**: HbA1c 値そのものが「stage」の記述で、CKD Gx / NYHA I-IV のような **標準化された stage system ではない**。SNOMED CT に "HbA1c 7.5%" のような値ベース concept は存在しない。テキストで値を保持する方が meaningful。
- **signature**: coding 欠落 stage.summary の text が `HbA1c \d+\.\d+%` regex に一致。他 pattern (CKD / NYHA / GOLD / CCS / asthma / HTN Stage) で coding 欠落があれば真のバグ。
- **established_session**: session 44, 2026-07-11 (Chain 4 CO-6 verify)
- **established_pr**: `69f4cae082`
- **revalidation_check**: coding 欠落 stage.summary が全て `HbA1c \d+\.\d+%` regex に一致することを確認。

### snapshot-in-progress-clinical-impression-status

- **id**: `snapshot-in-progress-clinical-impression-status`
- **observation**: `ClinicalImpression.ndjson` の 1 件以上で `status = "in-progress"`(`"completed"` を期待する tests がある)。
- **by_design_reason**: 同 encounter が AD-32 スナップショットで in-progress 打切りとなる患者。encounter status に連動して ClinicalImpression status も in-progress となる = FHIR spec 適合 (both are valid `EventStatus` codes)。既存 unit test `test_jp_clinical_impression_structural_fields_present` は `status == "completed"` を厳密要求しており、この test は snapshot 挙動を考慮していない = pre-existing test-side gap (session 44 で確認済)。
- **signature**: `status = "in-progress"` の CI に紐付く `encounter.status` も `in-progress` であること。
- **established_session**: session 44, 2026-07-11
- **established_pr**: `544fd40d18` (session 43 wrap で observed / not yet formalized)
- **revalidation_check**: 全 in-progress CI に対し、その encounter が同じく in-progress であることを確認。将来的には test を snapshot-aware に緩和する予定(FHIR completeness registry 参照)。

---

## Non-Entries (真のバグ、Registry 対象外)

以下は **登録禁止**。監査中に検出した場合は cycle 問題として登録し fix する。

- 全 stage system(CKD/NYHA/GOLD 1-4/asthma 4-tier/HTN Stage 1-2/CCS I-IV) → 全 stage.summary.coding **有** を要求。coding 欠落あれば bug。
- MicrobiologyResult 由来 Observation(mb-org-*/mb-sus-*) の `method` field 欠落 → session 44 CO-8 で全 populate 済、欠落あれば bug。
- CareTeam.telecom / DR.presentedForm の 100% populate → session 44 Chain 1/3 で確立、欠落あれば bug。

---

## 更新履歴

- 2026-07-11 (session 44): 初版。Chain 1-4 で確定した 7 by-design entry を登録。
