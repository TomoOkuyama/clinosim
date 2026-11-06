# 受診のライフサイクル・スナップショット・出力 — 仕様

位置づけ: **規範**。受診を作る/終える・死亡を記録する・スナップショット(`--end`)で何を見せるかを決める・FHIR リソースを仕上げる変更は、すべて本書に従う。従えない変更は、同じ PR で理由とともに本書を改訂する。

英語版: [`encounter-lifecycle-and-export-spec.md`](encounter-lifecycle-and-export-spec.md)。

関連仕様: 出力時の薬剤・検査の状態([`medication-lifecycle-spec.ja.md`](medication-lifecycle-spec.ja.md) §6、[`lab-orders-and-results-spec.ja.md`](lab-orders-and-results-spec.ja.md) §4)、フェーズの乱数ストリーム([`determinism-and-rng-spec.ja.md`](determinism-and-rng-spec.ja.md) §3)、AD-32 のスナップショット原則([`implementation-rules.ja.md`](implementation-rules.ja.md) §2)。

## 1. 原則

1. **受診の開き方・閉じ方は一つ。** どの受診種別も同じ補助関数でオーダーを結び付け、経路の項目を設定し、診断を作る。救急・外来・入院・分娩が同じ形になる。
2. **時間の流れは一つ。** シミュレーションは一つの月次前進ループで進み、各人の死亡は高々一つ(最も早いもの)。
3. **スナップショットは出力時に当てる。** CIF は起きたことを格納する。スナップショット日に何が見えるか(入院継続中、日付より後の記録の除外、まだ有効な保険・処方)は FHIR を書く時に計算するので、一つの CIF をどのスナップショットでも出力できる。
4. **リソースの仕上げは一つの経路。** 施設バンドルと各患者バンドルのあらゆる FHIR リソースは、同じ順序の仕上げ処理(プロファイル、表示の除去、識別子、付随する検体)を通る。あらゆる Condition は一つの骨組みから始まる。
5. **規則には必ずガードがある。** 各規則はそれを強制するテストを示す。テストの無い規則は §6 に挙げる。

## 2. 受診

| 規則 | 正準コード | ガード |
|---|---|---|
| どの受診シミュレータ(救急・入院・外来・周産期・不明疾患)も、`ClinicalDiagnosis` を `encounter_diagnosis` で作り、受診の無いオーダーを `attach_orders` で結び付ける。種別で経路が決まる受診(救急・外来・周産期)は、入院経路・転帰・優先度・入退院担当医を `finalize_encounter` で設定する。入院(入院・不明疾患)は、入院経路と退院判断からそれらを導く。 | `simulator/encounter_setup.py`(`attach_orders`, `finalize_encounter`, `encounter_diagnosis`) | `tests/unit/test_encounter_setup.py`, `tests/unit/test_encounter_export_spec_guards.py`(`…builds_its_diagnosis_through_encounter_setup`, `…links_its_orders_through_encounter_setup`, `…clinical_diagnosis_is_constructed_only_in_encounter_setup`) |
| シミュレーションは一つのループで月ごとに進む: 年の境目(人口の前進、医療カレンダー)、月次のライフイベント、救急枠、その月に積まれた事象の日付順の実行。 | `simulator/phases/_forward_loop.py` | `tests/unit/simulator/test_forward_loop_2169.py` |
| 死亡は一つのメソッドで一度だけ記録し、最も早いものを採る(後日の事前抽選の地域死亡は、それより早い院内死亡で置き換える)。 | `types/population.py::PersonRecord.record_death` | `tests/unit/test_death_record_2166.py` |

## 3. 出力時のスナップショット

| 規則 | 正準コード | ガード |
|---|---|---|
| スナップショットをまたぐ入院は入院継続中として出す(`period.end` なし、転帰なし)。スナップショットより後の日付の記録は暦日で除外し、スナップショット当日は残す。 | `fhir_r4/builder.py`(`_reconcile_encounters_at_snapshot` の後に `_drop_entries_after_snapshot`) | `tests/unit/output/test_fhir_after_snapshot_filter.py`, `tests/unit/output/test_fhir_encounter_hospitalization_941.py` |
| 保険の状態は期間とスナップショットから導く。 | `fhir_r4/demographics/patient.py::_derive_coverage_status` | `tests/unit/test_fhir_coverage.py`, `tests/unit/output/test_fhir_coverage_after_death_1278.py` |
| 退院処方の状態は、バンドル作成の前にその患者の全記録にわたって計算する。 | `order/prescription_supersede.py::prescription_closures` | 薬剤の仕様を参照 |

## 4. FHIR の仕上げ

| 規則 | 正準コード | ガード |
|---|---|---|
| 施設バンドルと各患者バンドルのあらゆるリソースは、一つの関数が決まった順序で仕上げる: JP Core / JP-CLINS または US Core のプロファイル、JP の Observation カテゴリ、英語のみの体系での表示の除去、eCS の用法項目、Observation の識別子、参照範囲の拡張の除去、付随する Specimen …。これらの処理を builder の他の場所から呼ばない。 | `fhir_r4/builder.py::_finalize_resource` | `tests/unit/test_encounter_export_spec_guards.py::test_finishing_passes_run_only_in_finalize_resource` |
| あらゆる Condition リソースは一つの骨組みから始まる: 識別子、JP 出力では JP Core プロファイルと JP eCS の診断種別、状態、カテゴリ、コード、対象者。 | `fhir_r4/conditions/conditions.py::_condition_skeleton` | `tests/unit/test_encounter_export_spec_guards.py::test_condition_resources_start_from_the_skeleton` |

## 5. コホートの読み取り

| 規則 | 正準コード | ガード |
|---|---|---|
| 評価と監査は、出力済みコホートを一つの NDJSON リーダーで読む。 | `audit/types.py::Cohort` | `tests/unit/test_audit_cohort_reader_2518.py` |

## 6. 未対応

| 未対応 | 場所 |
|---|---|
| 入院・不明疾患の入院は経路の項目を自前のコードで設定し、共通の補助関数は無い。 | `simulator/inpatient.py`, `simulator/unknown_condition.py` |
