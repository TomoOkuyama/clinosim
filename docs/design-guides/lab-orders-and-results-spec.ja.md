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
| スタチンは強度に応じて未治療 LDL を下げる(2018 ACC/AHA Table 3: 低強度 < 30 %、中強度 30-49 %、高強度 ≥ 50 %)。範囲内の位置は患者ごとに固定(患者 id の SHA-256 分位、RNG を引かない)、TC は同じ mg/dL だけ下がる。強度はスタチンとその用量から決まり、両国で同じ表。服用中のエゼチミブ(薬効分類で検出)は残る LDL をさらに下げる: スタチン併用で 20-26 %(IMPROVE-IT)、単剤で 16-21 %(Pandor 2009 メタ解析)、範囲内の位置はスタチンと同じ患者ごとの位置。健診の LDL も同じ患者・同じ薬剤に同じ低下率を使う。 | `physiology/statin_response.py`(`statin_ldl_reduction`, `ldl_reduction`, `statin_treated_ldl`)を `physiology/engine.py::medication_flags_from_context`(`ldl_reduction`)と `lipid_panel`、および `health_checkup/engine.py::_derive_checkup_values` で使う。データ `physiology/reference_data/statin_ldl_response.yaml`(`ldl_reduction`, `add_on`) | `tests/unit/modules/test_statin_ldl_response_2917.py`, `tests/unit/modules/test_ezetimibe_ldl_response_2947.py`, `tests/unit/test_checkup_statin_response_2928.py` |
| 健診の LDL 真値は、入院・外来の検査値と同じ脂質パネルで患者の脂質状態(性別・糖尿病・脂質異常症・スタチンとエゼチミブの低下率)から得る。同じ患者の健診と外来の LDL は測定ノイズだけ異なる。健診は自身の測定ノイズと上下限を加える。 | `physiology/engine.py`(`lipid_panel`, `patient_lipid_panel`)、`health_checkup/engine.py::_derive_checkup_values` | `tests/unit/test_checkup_ldl_lipid_state_2941.py` |
| 急性冠症候群でない患者のトロポニン I は、健常成人では正常に留まる(加齢による予備能低下だけでは上昇しない)。慢性的な上昇は心不全・CKD ステージ 4-5・超高齢から生じ、MI レベルの値は ACS フラグのときだけになる。 | `physiology/engine.py::_add_cardiac_labs`、`physiology/_lab_derivation_thresholds.py`(`TROPONIN_*`) | `tests/unit/test_troponin_chronic_calibration_2903.py`、`tests/unit/test_blood_markers.py` |
| 小児(18 歳未満)は年齢帯の基準範囲で判定し、表は 1 つ: CIF フラグ、FHIR referenceRange とその text、真値(クレアチニン・Hb / Hct・WBC・ALP は年齢の基準範囲の中央に置く)。小児のバイタルサインも同じ表の年齢帯範囲を referenceRange・interpretation・text に使い、ベースラインバイタルは年齢帯の中央値に置く。小児の生成呼吸数の上限は成人の 45 ではなく同じ表の年齢帯上限(`physiological_max`: 1 歳未満 80 /分、5 歳まで 60、11 歳まで 50)。NEWS2 は 16 歳未満では算出しない。 | `observation/pediatric_ranges.py`、`observation/reference_data/pediatric_reference_ranges.yaml`、`physiology/engine.py::pediatric_lab_scale`、`physiology/engine.py::rr_clamp_max` | `tests/unit/test_pediatric_reference_ranges_2872.py`、`tests/unit/test_rr_clamp_by_age_2926.py` |

## 3. 同一性とパネル

| 規則 | 正準コード | ガード |
|---|---|---|
| あらゆる境界(シミュレータ、FHIR ServiceRequest / Observation、入院経過の抽出、健診、ベンチマーク)は、検査名を正準の検査名と別名表で解決する。 | `observation/engine.py::canonical_lab_name`, `observation/reference_data/lab_aliases.yaml` | `tests/unit/test_lab_identity_2299.py`, `tests/unit/test_checkup_canonical_labs_2300.py` |
| スタチン服用中の脂質異常症の患者は、処方更新の受診で脂質パネル全体(TC, LDL, HDL, TG)を測る(単独項目にしない)。最初のモニタリング受診、スタチン変更から 4 週以上後、それ以外は約 6 か月ごと(2018 ACC/AHA: 変更後 4〜12 週、以後 3〜12 か月ごと)。 | `simulator/statin_monitoring.py`(`lipid_panel_due`, `lipid_panel_labs`)。データ `simulator/reference_data/statin_monitoring.yaml` | `tests/unit/simulator/test_statin_monitoring_2877.py` |
| パネルは一度だけ定義し、オーダー時は一つの分類関数で検査をパネルと単独検査に分ける。 | `observation/reference_data/lab_panels.yaml`, `order/panel_grouping.py::classify_lab_specs` | `tests/unit/test_lab_bounds_panels_2332.py`, `tests/unit/test_lab_panel_registry.py` |

## 4. 結果とオーダー

| 規則 | 正準コード | ガード |
|---|---|---|
| 培養の結果は培養オーダーから生む。入院中の培養オーダーの採取 1 回ごとに結果が一つ出る。どのプロトコルのオーダーも置いていないプロファイル上の培養は、入院時にオーダーする。FHIR は一つの照合関数で各培養結果をそのオーダーに結び付ける。 | `observation/microbiology.py`(`culture_draws`, `culture_results`)、`fhir_r4/labs/microbiology.py::culture_orders_for` | `tests/unit/test_cultures_from_orders_2640.py` |
| 検査の ServiceRequest は結果(DiagnosticReport または培養)で完了し、結果の無いまま入院が終われば取り消す。 | `fhir_r4/labs/service_request.py` | `tests/unit/test_lab_orders_resulted_or_cancelled_2661.py::test_an_unresulted_order_of_a_discharged_stay_is_revoked`, `tests/unit/output/test_fhir_microbiology_links_2585.py::test_the_orders_a_culture_reports_are_completed_and_the_others_are_not`, `tests/integration/test_servicerequest_snapshot.py` |
| 輸血前検査(type and screen)のオーダーは、それが報告する血液型と不規則抗体スクリーニングで結果とし、その DiagnosticReport の performer は病院 Organization、採血(オーダー)時刻を effective、院内検査の所要時間モデルで決まる結果時刻を issued とする。 | `simulator/lab_pipeline.py::TYPE_AND_SCREEN`, `fhir_r4/labs/blood_type.py` | `tests/unit/output/test_type_and_screen_2587.py`, `tests/unit/output/test_screen_report_performer_3357.py` |
| 溶血した検体 (flag `H*` / `L*`) のうち再採血の対象の項目 (カリウム) は、その `delay_minutes` 後に置く stat の検査オーダーで、上限 `max_redraws` まで繰り返す。再採血は真値からオーダーごとの独立した乱数ストリームで結果を作り、溶血した値を臨床上の契機に使うことはない (Issue #3452)。 | `modules/observation/hemolysis_redraw.py` (`is_hemolyzed`, `hemolysis_redraw_rules`)、`simulator/daily_loop.py::_redraw_hemolyzed`。データは `modules/observation/reference_data/hemolysis_redraw.yaml` | `tests/unit/drug_safety/test_hemolyzed_potassium_redraw_3452.py` |
| 入院中の連続採血の生物学的ノイズは、その項目に `serial_biological_cv` の項目があればそれを使う(CRP は 0.11。一般の被検者の個体内 CV 0.423 を毎回の独立ノイズにすると、真値が一定の CRP が連続する採血の間で 3 倍を超えて振れる組が 13% あった)。入院経過は生理状態が与える。どちらの場合も 2 回の正規乱数を引くので乱数ストリームは変わらず、他の項目は変わらない (Issue #3870)。 | `observation/engine.py::apply_realistic_variability` (`serial=`), `observation/reference_data/lab_constants.yaml` (`serial_biological_cv`), `simulator/lab_pipeline.py` | `tests/unit/test_crp_serial_variability_3870.py` |
| 一つの検査項目は一回の採血につき一度だけオーダーする。プロトコルの一覧がパネルとその構成項目(BMP と K)の両方を挙げていれば、項目は一度だけオーダーする。1 日 1 回の慢性疾患モニタリング検査と合併症モニタリング検査は、朝の採血にすでにその項目が含まれていれば置かない(パネルのオーダーはその構成項目として数える)。別のパネルと重なるパネル(ABG と BMP はどちらも HCO3 を含む)は別の検体なので残す。定時の繰り返し(qid / tid のモニタリング)、溶血による再採血、stat の追加検査は別の採血であり、まとめない。置いた各オーダーはそれぞれ独自のノイズで結果が出るため、同じ採血に二つ目のオーダーを置くと一つの検体に食い違う値が付いてしまう。乱数の引きは増減しない (Issue #3869)。 | `order/engine.py::drop_redundant_scalar_labs`, `observation/order_routing.py::placed_lab_analytes`, `simulator/medication_pipeline.py::_place_chronic_monitoring_orders`, `simulator/daily_loop.py::_place_complication_monitoring_orders` | `tests/unit/simulator/test_daily_lab_dedup_3869.py` |
| 患者の死亡時刻より後には、検査オーダーを置かず、検査結果の時刻も置かない。死亡後に置いたオーダーは除き、死亡後の時刻の結果は除いてそのオーダーを取り消す。乱数は引かない (Issue #3280)。 | `simulator/terminal_course.py::drop_results_after_death`。呼び出し元は `simulator/daily_loop.py` | `tests/unit/simulator/test_no_labs_after_death_3280.py` |
| 入院の検査所要時間は、病院状態の遅延モデルを病院 YAML の検査の `delay_limits` (stat と routine の `max_load_factor`・`max_delay_min`) で抑えたもので、routine の結果を汎用の上限まで押し上げない。`delay_limits` のない資源 (画像) は汎用の上限のままとする (Issue #3287)。 | `modules/facility/hospital_state.py` (`calculate_delay`)。データは `config/hospital_small.yaml`, `config/hospital_large.yaml`, `config/hospital_operations.yaml` | `tests/unit/test_lab_turnaround_3287.py` |
| 検査パネルの DiagnosticReport は一つの Encounter の結果を報告する: パネルの構成検査は、パネル・日・オーダーの Encounter (経由 ED 入院でオーダー時刻が ED 窓にあれば ED bridge、そうでなければ入院) で束ね、リソースを振り分けるのと同じ ED 窓の判定を使うので、報告の `result`・`basedOn`・`encounter`・`effective[x]` は一致する (Issue #3958)。 | `fhir_r4/labs/diagnostic_report.py::group_lab_orders` (`ed_window`)、`fhir_r4/lib/ed_reattribution.py` (`ed_window_of_record`, `time_in_ed_window`) | `tests/unit/output/test_fhir_panel_report_one_encounter_3958.py` |

## 5. 評価の範囲

| 規則 | 正準コード | ガード |
|---|---|---|
| clinosim が出す単位についての評価の生理範囲は、生成側の `physiologic_limits` を US の検査コード対応で LOINC に写したもの。`lab-plausibility-bounds.yaml` はそれ以外の単位表記(他社コホート用)だけを足す。 | `eval/axes/clinical.py::_lab_bounds_from_yaml`, `observation/reference_data/lab_constants.yaml` | `tests/unit/test_lab_bounds_panels_2332.py` |

## 6. 未対応

| 未対応 | 場所 |
|---|---|
| スタチンとエゼチミブの LDL 効果は初日から全量で効く。完全な効果までの 4〜6 週は模していない(変更後のパネルは 4 週以上後に採る)。 | `physiology/statin_response.py` |
