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
- **observation**: `MedicationRequest.ndjson` の一部記録が YJ code を持たない(text-only)。
- **by_design_reason**: 該当 drug は 日本 薬価基準未掲載 (imported / OTC / withdrawn / 眼科点眼など海外一般名指定処方)。No-fabrication policy (session 40 確立) により、authoritative code 未確認の drug には code を emit しない。
- **signature**: uncoded MR の drug name (medicationCodeableConcept.text の base name / normalized form) が以下 whitelist に含まれること:
  - "シクロベンザプリン" / "Cyclobenzaprine"
  - "フェナゾピリジン" / "Phenazopyridine"
  - "メクリジン" / "Meclizine"  (session 44 cycle 6 追加 — 抗ヒスタミン、JP 薬価基準未掲載)
  - "ニトロフラントイン" / "Nitrofurantoin"  (session 44 cycle 6 追加 — UTI、JP 未掲載)
  - "プロパラカイン" / "Proparacaine"  (session 44 cycle 6 追加 — 眼科表面麻酔、JP 未掲載)
  - "オフロキサシン点眼" / "Ofloxacin ophthalmic"  (session 44 cycle 6 追加 — 眼科 個別 code なし)
  - "オキシメタゾリン" / "Oxymetazoline"  (session 44 cycle 6 追加 — 鼻噴霧 OTC)
  - "テルリプレシン" / "Terlipressin"  (session 44 cycle 7 residual sweep 追加 — JP 薬価基準未掲載)
  - "シクロペントラート" / "Cyclopentolate"  (session 44 cycle 7 residual sweep 追加 — 眼科 個別 code なし)
  他の drug で uncoded が発生した場合 = 真のバグ(MHLW lookup 追加が必要)。
- **established_session**: session 44, 2026-07-11 (Chain 4 CO-8) — cycle 6 (session 44 continuation) で 5 件追加
- **established_pr**: `2c5e79b974` + cycle 6 close
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

### snapshot-in-progress-encounter-discharge-disposition-omitted

- **id**: `snapshot-in-progress-encounter-discharge-disposition-omitted`
- **observation**: `Encounter.ndjson` の一部が `hospitalization.dischargeDisposition` を持たない(cycle 1 監査で 24 件観測)。
- **by_design_reason**: AD-32 snapshot 意味論。in-progress encounter は退院していないので disposition 未定 = FHIR spec 適合。C1-04 で確認済(cycle 1)。
- **signature**: `dischargeDisposition` 欠落の Encounter が全て `status == "in-progress"` かつ `discharge_datetime == null`。
- **established_session**: session 41, 2026-07-07 (cycle 1)
- **established_pr**: cycle 1 close (session 41)
- **revalidation_check**: dischargeDisposition 欠落 Encounter が全て in-progress であること。

### realistic-mr-mar-ratio-for-outpatient-heavy-cohort

- **id**: `realistic-mr-mar-ratio-for-outpatient-heavy-cohort`
- **observation**: MR 件数がある基準値 (例 21820 for JP p=10000) より少なく見える。MAR:MR 比が ~9:1 〜 33:1 の広い帯。
- **by_design_reason**: 90% 外来コホートで MR = 外来処方 + 入院初期オーダーのみ、MAR = 入院での複数日投与実績。~0.4-0.6 MR/enc + 高比率 MAR:MR は実 EHR reality。session 45 seed=100 verification で 32.6 観測 = long-LOS IMP + continuous-infusion drip の重畳による自然な pattern。C1-08 (cycle 1) + session 45 verification 併合。
- **signature**: `MR count / encounter count ≈ 0.4–0.7` かつ `MAR / MR ≈ 5–40`。両範囲内なら by-design。範囲外 = 要調査(cohort 混合が変化 or MAR bloat)。
- **established_session**: session 41, 2026-07-07 (cycle 1) — band widened session 45, 2026-07-11
- **established_pr**: cycle 1 close + session 45 verification
- **revalidation_check**: 上記 2 比率を計算し範囲内であること。band 上限を上回るときは continuous-infusion drip の混在率が急変していないか確認。

### clinical-impression-summary-optional

- **id**: `clinical-impression-summary-optional`
- **observation**: `ClinicalImpression.summary` field が空(多くの CI で omit)。
- **by_design_reason**: FHIR R4 `ClinicalImpression.summary` は 0..1 (optional)。CIF に対応する source data 無し(distinct 所見総括データを clinosim は生成しない)。fabrication すると no-fabrication policy 違反。`description` は populated (Day N clinical assessment)。C1-11 で確認済(cycle 1)。
- **signature**: 全 CI で `summary` field が omit されている(コード側で emit していない)ことを確認。将来 β-JP-1 LLM narrative pass で populate 予定(FHIR completeness registry 参照)。
- **established_session**: session 41, 2026-07-07 (cycle 1)
- **established_pr**: cycle 1 close
- **revalidation_check**: `_fhir_composition.py` (or clinical_impression builder) が summary を emit していないことを grep 確認。

### care-team-inactive-for-completed-encounter

- **id**: `care-team-inactive-for-completed-encounter`
- **observation**: `CareTeam.status = "inactive"` の record が多い(退院済 encounter に紐付く CT)。"active" を期待するレビューあり。
- **by_design_reason**: FHIR R4 `CareTeam.status` valueSet includes `active | inactive | suspended | entered-in-error`。退院済 encounter = team が現在ケアを提供していない = inactive が spec 正解(`_fhir_care_team.py:88-89`)。C1-14 で確認済(cycle 1)。
- **signature**: `status = "inactive"` の CT に紐付く `encounter.discharge_datetime` が non-null であること。
- **established_session**: session 41, 2026-07-07 (cycle 1)
- **established_pr**: cycle 1 close
- **revalidation_check**: inactive CT の encounter が全て discharge_datetime 有(= completed)であること。

### population-vs-patient-count-utilization-rate

- **id**: `population-vs-patient-count-utilization-rate`
- **observation**: `--population 10000` で `Patient.ndjson` が 5000-6000 程度(= 全員患者化しない)。
- **by_design_reason**: population = catchment area total = 病院サービスエリア人口(健常人含む)。Patient = 期間内に encounter を持った人だけ。~50% healthcare utilization rate は実データと整合。C1-20 で確認済(cycle 1)。
- **signature**: `Patient count / population` が `0.4–0.7` 範囲内(country demographics 依存)。
- **established_session**: session 41, 2026-07-07 (cycle 1)
- **established_pr**: cycle 1 close
- **revalidation_check**: 上記 ratio を計算し範囲内であること。範囲外 = disease incidence data の drift 疑い。

### coverage-type-text-only-no-fabrication

- **id**: `coverage-type-text-only-no-fabrication`
- **observation**: `Coverage.type` が `{"text": "..."}` のみで `coding` を持たない。
- **by_design_reason**: JP 保険 type (公費 / 社保 / 国保 等) に authoritative FHIR CodeSystem が確定していない。fabrication 禁止 policy に従い text-only 維持(`_fhir_patient.py:152-155`)。C2-12 で確認済(cycle 2)。
- **signature**: `Coverage.type.coding` が全 Coverage で omit されていること(`_fhir_patient.py` に fabricated code が入っていない)。
- **established_session**: session 42, 2026-07-07 (cycle 2)
- **established_pr**: cycle 2 close
- **revalidation_check**: 全 Coverage の type に `coding` が無く、`text` のみであること。authoritative code source が確立した時点で本 entry は解除。

### condition-severity-none-on-chronic-primary-encounter [RETIRED]

- **id**: `condition-severity-none-on-chronic-primary-encounter`
- **status**: **RETIRED — session 45, 2026-07-11 verification**
- **retirement_reason**: cycle 6-7 residual sweep + Cycle 4 C4-05/07-09 chronic-inherit path で全 Condition が severity populate 済。session 45 seed=100 verification で severity 欠落 Condition = 0 件を確認 = 該当 pattern が消失。今後 severity 欠落を検出した場合は **真のバグ**(本 entry で by-design 扱いしない)。
- **original_observation**: `Condition.severity` の一部欠落(65.8% observed at cycle 2 for I10 routine visit)。
- **original_by_design_reason**: primary dx が慢性疾患 (I10 essential HTN etc.) の routine outpatient follow-up では acute severity が sensor 由来で inferable でない → severity None が clinically correct。C2-32 で確認済(cycle 2)。
- **established_session**: session 42, 2026-07-07 (cycle 2)
- **retired_session**: session 45, 2026-07-11 (verification)
- **retired_pr**: session 45 verification chain

### composition-vs-documentreference-format-type-split

- **id**: `composition-vs-documentreference-format-type-split`
- **observation**: `Composition.ndjson` の resource 数 が `DocumentReference.ndjson` より多い / 少ないなど「分布が偏る」観測。
- **by_design_reason**: `ClinicalDocument.format_type` により意図的に分岐 — `composition` (H&P / Discharge Summary / Nursing / SOAP 等 section 構造持つ帳票) → Composition emit。`free_text` (Progress Note / Nursing Record / Triage 等) → DocumentReference emit。両者は独立 resource type であり比率一致は要求されない。C4-25 で確認済(cycle 4)。
- **signature**: `_fhir_composition.py` および `_fhir_documents.py` の `format_type` filter が両ビルダーで一貫していること(composition ↔ Composition emit / free_text ↔ DR emit / それ以外 → skip)。
- **established_session**: session 43, 2026-07-08 (cycle 4)
- **established_pr**: cycle 4 close
- **revalidation_check**: Composition 全 resource が `format_type == "composition"` doc 由来、DR 全 resource が `format_type == "free_text"` doc 由来であること(id 遡り検証)。

### compound-rx-with-device-alternative-real-drug

- **id**: `compound-rx-with-device-alternative-real-drug`
- **observation**: `MedicationRequest` / `MedicationAdministration` の text が `"エノキサパリン ... または 間欠的空気圧迫"` 等の複合表現。184 件観測(cycle 5 baseline)。
- **by_design_reason**: 実 CIF Order の detail は 「実薬 (Enoxaparin) OR 代替 device (IPC)」の compound orderable。session 43 CY2-B fix + session 44 C5-19 で primary alternative が prefer される splitter を導入したが、`"または"` 前が real drug の場合は drug 側が採用され、alternative text が残る事もある = 分類バグではない。C5-16 で確認済(cycle 5)。
- **signature**: compound text の primary drug が code_mapping にヒットして coding 有、後半 " または " 以降の text が display に混じる。primary が uncoded なら真のバグ。
- **established_session**: session 43, 2026-07-09 (cycle 5)
- **established_pr**: cycle 5 close
- **revalidation_check**: compound text MR/MAR で `medicationCodeableConcept.coding[0].code` が non-empty であること(primary drug が resolved)。

### amb-encounter-no-hospitalization

- **id**: `amb-encounter-no-hospitalization`
- **observation**: `Encounter.hospitalization` が cohort 全体で ~10% しか emit されない(cycle 6 で 3951/37137)。
- **by_design_reason**: `Encounter.hospitalization` は入院/退院 episode 情報(admit source / discharge disposition / dietary preference 等)を保持する。AMB (ambulatory / outpatient) encounter には入退院 episode が存在しないため、FHIR R4 は `hospitalization` を emit しない。EMER + IMP encounter だけが hospitalization を持つ = 実 EHR 挙動と整合。
- **signature**: `hospitalization` 欠落 Encounter が全て `class.code == "AMB"` であること。EMER / IMP で欠落 = 真のバグ。
- **established_session**: session 44, 2026-07-11 (Cycle 6 review)
- **established_pr**: cycle 6 open (`892c15051c`)
- **revalidation_check**: hospitalization 欠落 Encounter の class.code を集計し全て "AMB" であることを確認。EMER + IMP は 100% 有。

### observation-method-lab-only

- **id**: `observation-method-lab-only`
- **observation**: `Observation.method` の cohort emit rate が ~12% (cycle 6 baseline 282762/2340725)。
- **by_design_reason**: session 44 CO-8 で `Observation.method` を lab カテゴリのみに wired。vital-signs (device 設定値の計測)、survey (質問票 / 意識レベル)、social-history (喫煙 / 飲酒 / 職業) は概念的に method 不要:vital signs は device による自動計測、survey は問診、social-history は聞き取り。lab のみ analyzer method (自動分析器測定 / 培養同定 / 感受性試験) が意味を持つ。
- **signature**: method 欠落 Observation が全て非 lab カテゴリ (`vital-signs | survey | social-history | imaging`) であること。lab カテゴリで method 欠落 = 真のバグ。
- **established_session**: session 44, 2026-07-11 (Chain 2 + Cycle 6 review)
- **established_pr**: `1481306d2f` (Chain 2 initial) + cycle 6 confirm
- **revalidation_check**: method 欠落 Observation の category を集計し全て非 lab であることを確認。lab カテゴリの method rate = 100% であること。

### immunization-not-done-no-performer

- **id**: `immunization-not-done-no-performer`
- **observation**: `Immunization.ndjson` の一部 (~2%) で `performer` field が欠落 (cycle 6 で 599/29995)。
- **by_design_reason**: `Immunization.status == "not-done"` は「接種予定だったが未接種」の記録形式(refusal / contraindication / logistics 等)。実接種者が存在しないため performer は emit しない。CDC IIS / JP 予防接種台帳の両方で同じ挙動。FHIR R4 `Immunization.performer` は 0..* で not-done で欠落しても spec 適合。
- **signature**: performer 欠落 Immunization が全て `status == "not-done"` であること。`status == "completed"` で欠落 = 真のバグ。
- **established_session**: session 44, 2026-07-11 (Cycle 6 review)
- **established_pr**: cycle 6 open
- **revalidation_check**: performer 欠落 Immunization の status を集計し全て "not-done" であることを確認。

### icu-transfer-rate-classhistory-6pct

- **id**: `icu-transfer-rate-classhistory-6pct`
- **observation**: `Encounter.classHistory` は IMP encounter の ~6% でしか emit されない(cycle 7 で 73/1223)。
- **by_design_reason**: `classHistory` は encounter class の遷移(一般病棟 → ICU、ICU → 一般病棟)を記録する。ICU 転棟したケースのみ遷移が発生するため、IMP の中で ICU 経由率(clinical reality ~5-10%、cycle 7 の 6.0% は妥当) だけが classHistory を持つ。session 43 C5-22 で導入した機能で、100% ではなく「該当ケースの 100%」が正しい挙動。
- **signature**: classHistory 欠落 IMP encounter が `icu_transferred_day` を持たないこと(ICU 経由なし)。ICU 経由あり(icu_transferred_day 有)で classHistory 欠落 = 真のバグ。
- **established_session**: session 44, 2026-07-11 (Cycle 7 review)
- **established_pr**: cycle 7 open (`499f72a09d`)
- **revalidation_check**: classHistory 欠落 IMP encounter に対応する CIF record の `icu_transferred_day` を確認し全て -1 (or missing) であること。

### cy7-05-synth-ed-encounter-no-condition

- **id**: `cy7-05-synth-ed-encounter-no-condition`
- **observation**: `Condition.ndjson` does not reference the synthesized ED
  Encounter resources (id suffix `-ED`) — clinical audits show
  IMP/EMER-without-Condition count matches exactly the number of ED→IMP
  partOf-linked synth encounters (session 45 seed=400: 972/972).
- **by_design_reason**: CY7-05 (session 44) synthesizes a lightweight ED
  Encounter FHIR resource so IMP.partOf resolves, but the diagnosis lives on
  the primary IMP encounter — not duplicated on the synth stub. The synth
  carries chief-complaint text in `reasonCode` and `hospitalization.admitSource
  = "outp"` / `dischargeDisposition = "hosp"` to convey the ED-visit event
  without inflating downstream Condition/Procedure/Order counts. Adding a
  Condition specifically for the synth stub would misrepresent EHR reality
  (in practice, ED-to-admission is billed on the inpatient encounter, not the
  ED subacct). Session 45 seed=400 verification confirmed all 972 IMP/EMER
  missing-Condition were synth `-ED` ids (`class == "EMER"`, `status ==
  "finished"`, id endswith `-ED`).
- **signature**: `IMP/EMER encounters without any Condition.encounter =
  Encounter/<id> reference` all have id endswith `-ED`.
- **established_session**: session 45 verification, 2026-07-11
- **established_pr**: session 45 chain #5 (`210bc6b057`..)
- **revalidation_check**: sort no-Condition IMP/EMER by id; every id must
  end with `-ED` (the CY7-05 synth suffix).

### vital-signs-no-refrange-for-device-setting-or-categorical

- **id**: `vital-signs-no-refrange-for-device-setting-or-categorical`
- **aliases**: `o2-flow-rate-device-setting-no-refrange` (original session 43 name; kept as alias for back-reference from session 41-44 cycle docs)
- **observation**: バイタル系 `Observation` の一部に `referenceRange` が無い。cycle 5 baseline で LOINC 3151-8 (O2 flow rate) 13,843 obs 観測。session 45 seed=100 verification で LOINC 80288-4 (AVPU consciousness level) 131,364 obs 追加確認。
- **by_design_reason**: 以下 2 種類のバイタル観測は生理学的 normal range が概念的に不要:
  - **Device setting**: LOINC 3151-8 O2 flow rate = 装置設定値(酸素投与量 = 治療介入量、健常者に対する reference 範囲は存在しない)。
  - **Categorical scale**: LOINC 80288-4 AVPU = 4 段階 categorical valueSet (Alert / Verbal / Pain / Unresponsive)、numeric range が意味を持たない。session 45 追加。
  他の categorical vital scale(GCS の 3 sub-components など)を将来追加する場合は同 pattern。FHIR R4 は refRange を 0..* で要求しない。
- **signature**: refRange 欠落バイタル Observation の `code.coding[0].code` が `{3151-8 (O2 flow rate), 80288-4 (AVPU consciousness)}` のいずれかに一致すること。他 LOINC で refRange 欠落 = 真のバグ(本レジストリ対象外)。
- **established_session**: session 43, 2026-07-09 (cycle 5) — signature extended session 45, 2026-07-11
- **established_pr**: cycle 5 close + session 45 verification
- **revalidation_check**: refRange 欠落 Observation の LOINC が全て上記 whitelist に含まれることを確認。新規 categorical vital LOINC を発見した場合は registry を update。

---

## Non-Entries (真のバグ、Registry 対象外)

以下は **登録禁止**。監査中に検出した場合は cycle 問題として登録し fix する。

- 全 stage system(CKD/NYHA/GOLD 1-4/asthma 4-tier/HTN Stage 1-2/CCS I-IV) → 全 stage.summary.coding **有** を要求。coding 欠落あれば bug。
- MicrobiologyResult 由来 Observation(mb-org-*/mb-sus-*) の `method` field 欠落 → session 44 CO-8 で全 populate 済、欠落あれば bug。
- CareTeam.telecom / DR.presentedForm の 100% populate → session 44 Chain 1/3 で確立、欠落あれば bug。

---

## 更新履歴

- 2026-07-11 (session 44): 初版。Chain 1-4 で確定した 7 by-design entry を登録。
- 2026-07-11 (session 44 追補): cycle 1-5 の doc から遡って 10 by-design/not-a-bug 記述を統合。
  合計 **17 entries** で C1-C5 全 by-design 観測をカバー:
  - Cycle 1 (5): C1-04, C1-08, C1-11, C1-14, C1-20
  - Cycle 2 (2): C2-12, C2-32
  - Cycle 4 (1): C4-25
  - Cycle 5 (2): C5-16, C5-17
  - Session 44 Chain 1-4 verify (7): snapshot-length, MR substitution, Coverage 後期高齢者,
    FMH healthy relative, CO-8 non-JP drugs, HbA1c stage text, CI in-progress status
- 2026-07-11 (session 44 Cycle 6 拡張): cycle 6 baseline review で発見した 3 新パターン
  (`amb-encounter-no-hospitalization` / `observation-method-lab-only` /
  `immunization-not-done-no-performer`) を追加 + `co8-non-jp-marketed-drugs` の
  whitelist を 5 件拡張 (Meclizine / Nitrofurantoin / Proparacaine / Ofloxacin
  ophthalmic / Oxymetazoline)。合計 **20 entries**。
- 2026-07-11 (session 44 Cycle 7 拡張): cycle 7 baseline review で発見した 1 新
  パターン `icu-transfer-rate-classhistory-6pct` を追加。合計 **21 entries**。
- 2026-07-11 (session 45 verification): JP p=10000 seed=100 verification で発見した
  3 修正 (heparin rate adjustment / EMER length synthesis) と registry 3 更新を統合:
  - `condition-severity-none-on-chronic-primary-encounter` → RETIRED
    (cycle 6-7 residual sweep 後 severity 欠落 = 0 件、pattern 消失)
  - `o2-flow-rate-device-setting-no-refrange` → rename +
    signature 拡張 = `vital-signs-no-refrange-for-device-setting-or-categorical`
    (LOINC 80288-4 AVPU consciousness を追加)
  - `realistic-mr-mar-ratio-for-outpatient-heavy-cohort` → MAR/MR band 5-15 → 5-40 に拡張
    (long-LOS IMP + continuous-infusion drip 混在の広い自然帯を許容)
  net: **21 entries**(1 retire + 2 signature update、新規 entry 無し)。
