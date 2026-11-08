# 検査オーダーと結果 — 仕様

位置づけ: **規範**。検査をオーダーする・検査値を導く/生成する・結果にフラグを付ける・結果をオーダーに結び付ける・評価のために検査結果を読む変更は、すべて本書に従う。従えない変更は、同じ PR で理由とともに本書を改訂する。

英語版: [`lab-orders-and-results-spec.md`](lab-orders-and-results-spec.md)。

関連仕様(本書では繰り返さずリンクする):
- 検査コード(LOINC / JLAC10)、検査名と別名、表示名: [`code-mapping-and-localization-spec.ja.md`](code-mapping-and-localization-spec.ja.md) §3.9 / §4.1。
- オーダーごとの乱数ストリーム(検体・ノイズ): [`determinism-and-rng-spec.ja.md`](determinism-and-rng-spec.ja.md) §3。
- 検査項目とその定数(単位・CV・限界・基準値): [`configuration-and-reference-data-spec.ja.md`](configuration-and-reference-data-spec.ja.md)。

## 1. 原則

1. **患者と時点ごとに真値は一つ。** 各項目の真値(ノイズ前の値)は一つの関数が決める。入力は患者の生理状態・病態・薬剤・経年履歴である。あらゆる受診種別がこの関数を呼ぶので、同じ患者は救急でも外来でも病棟でも同じように測られる。
2. **一つの検査に一つの同一性。** あらゆる境界で、判断の前に検査名を正準の検査名に直す。別名や綴りの違いで一つの検査が二つに割れない。
3. **オーダーには結果が、結果にはオーダーがある。** 結果の出た検査オーダーはその結果で完了し、結果の無いものは退院時に取り消される。培養の結果は、それを生んだ培養オーダーを報告する。
4. **生成側と評価側は限界を共有する。** 評価は、生成側が値をクランプするのと同じ生理的限界でコホートを検査する。
5. **規則には必ずガードがある。** 各規則はそれを強制するテストを示す。テストの無い規則は §6 に挙げる。

## 2. 真値

| 規則 | 正準コード | ガード |
|---|---|---|
| あらゆる受診種別(入院の日次ループ・救急・外来・不明疾患・薬剤モニタリング)は、一つの関数から検査の真値を得る。関数には性別・年齢・糖尿病と脂質異常症(値集合)・その年の経年 HbA1c・シナリオと薬剤のフラグを渡す。 | `simulator/lab_pipeline.py::patient_true_labs`(内部で `physiology/engine.py::derive_lab_values`) | `tests/unit/test_lab_spec_guards.py::test_true_lab_values_only_through_patient_true_labs`, `tests/unit/modules/monitoring/test_monitoring_true_labs_2735.py` |
| 生理モデルが扱わない項目は基準値(`baseline_normals`)にフォールバックする。 | `observation/engine.py::BASELINE_LAB_NORMALS` | `tests/unit/test_phosphate_magnesium_co2_2687.py` |
| ワルファリン服用中かどうかは一度だけ判断し、それが INR の値・フラグ・治療域を決める。 | `observation/engine.py`(`medications_in_effect`, `therapeutic_range`)、`physiology/engine.py::medication_flags_from_context` | `tests/unit/test_warfarin_status_2293.py` |
| 急性冠症候群でない患者のトロポニン I は、健常成人では正常に留まる(加齢による予備能低下だけでは上昇しない)。慢性的な上昇は心不全・CKD ステージ 4-5・超高齢から生じ、MI レベルの値は ACS フラグのときだけになる。 | `physiology/engine.py::_add_cardiac_labs`、`physiology/_lab_derivation_thresholds.py`(`TROPONIN_*`) | `tests/unit/test_troponin_chronic_calibration_2903.py`、`tests/unit/test_blood_markers.py` |

## 3. 同一性とパネル

| 規則 | 正準コード | ガード |
|---|---|---|
| あらゆる境界(シミュレータ、FHIR ServiceRequest / Observation、入院経過の抽出、健診、ベンチマーク)は、検査名を正準の検査名と別名表で解決する。 | `observation/engine.py::canonical_lab_name`, `observation/reference_data/lab_aliases.yaml` | `tests/unit/test_lab_identity_2299.py`, `tests/unit/test_checkup_canonical_labs_2300.py` |
| パネルは一度だけ定義し、オーダー時は一つの分類関数で検査をパネルと単独検査に分ける。 | `observation/reference_data/lab_panels.yaml`, `order/panel_grouping.py::classify_lab_specs` | `tests/unit/test_lab_bounds_panels_2332.py`, `tests/unit/test_lab_panel_registry.py` |

## 4. 結果とオーダー

| 規則 | 正準コード | ガード |
|---|---|---|
| 培養の結果は培養オーダーから生む。入院中の培養オーダーの採取 1 回ごとに結果が一つ出る。どのプロトコルのオーダーも置いていないプロファイル上の培養は、入院時にオーダーする。FHIR は一つの照合関数で各培養結果をそのオーダーに結び付ける。 | `observation/microbiology.py`(`culture_draws`, `culture_results`)、`fhir_r4/labs/microbiology.py::culture_orders_for` | `tests/unit/test_cultures_from_orders_2640.py` |
| 検査の ServiceRequest は結果(DiagnosticReport または培養)で完了し、結果の無いまま入院が終われば取り消す。 | `fhir_r4/labs/service_request.py` | `tests/unit/test_lab_orders_resulted_or_cancelled_2661.py::test_an_unresulted_order_of_a_discharged_stay_is_revoked`, `tests/unit/output/test_fhir_microbiology_links_2585.py::test_the_orders_a_culture_reports_are_completed_and_the_others_are_not`, `tests/integration/test_servicerequest_snapshot.py` |
| 輸血前検査(type and screen)のオーダーは、それが報告する血液型と不規則抗体スクリーニングで結果とする。 | `simulator/lab_pipeline.py::TYPE_AND_SCREEN`, `fhir_r4/labs/blood_type.py` | `tests/unit/output/test_type_and_screen_2587.py` |

## 5. 評価の範囲

| 規則 | 正準コード | ガード |
|---|---|---|
| clinosim が出す単位についての評価の生理範囲は、生成側の `physiologic_limits` を US の検査コード対応で LOINC に写したもの。`lab-plausibility-bounds.yaml` はそれ以外の単位表記(他社コホート用)だけを足す。 | `eval/axes/clinical.py::_lab_bounds_from_yaml`, `observation/reference_data/lab_constants.yaml` | `tests/unit/test_lab_bounds_panels_2332.py` |

## 6. 未対応

既知のものは無い。新たな例外は、それを許すガードとともにここに記す。
