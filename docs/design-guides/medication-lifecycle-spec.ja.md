# 薬剤のライフサイクル — 仕様

位置づけ: **規範**。薬剤をオーダー・保留・投与・中止・処方・再処方・コード化する変更は、すべて本書に従う。従えない変更は、同じ PR で理由とともに本書を改訂する。

英語版: [`medication-lifecycle-spec.md`](medication-lifecycle-spec.md)。

関連仕様:
- 薬剤の同定(`drug_ref`, `same_drug`, `has_drug`, `medication_matches`)とコード・名称の解決: [`code-mapping-and-localization-spec.ja.md`](code-mapping-and-localization-spec.ja.md) §4.1 / §9。
- 乱数と、乱数をずらさない変更: [`determinism-and-rng-spec.ja.md`](determinism-and-rng-spec.ja.md)。

## 1. 原則

1. **一つの規則は一か所に。** 薬剤に関する各判断は、一つのデータファイルを読む一つの関数が行う。その判断を要するすべての段階が、その関数を呼ぶ。段階とは、入院時・日次ループ・投与記録(MAR)・退院時・在宅薬の有効化・経年履歴・FHIR 出力である。独自の写しを持つ段階は無い。
2. **記録は一つの経過を語る。** 1 薬剤につき有効なオーダーは高々一つ。置き換えられたオーダーは中止され、その投与もそこで終わる。終わった入院のオーダーは退院時に閉じる。投与があるオーダーには必ずオーダーがある。有効なオーダーは投与されているか、されない理由を持つ。
3. **シミュレーションで決め、出力時に導く。** オーダーと投与の事実は CIF に格納する。スナップショットや後の記録に依存する状態は FHIR 出力時に計算する(§6)。例えば、退院処方がまだ有効か、どの処方がそれを置き換えたか、である。
4. **規則には必ずガードがある。** 各規則はそれを強制するテストを示す。テストの無い規則は §8 に挙げる。

## 2. ライフサイクル

```
プロトコル / 在宅薬 ──► オーダー(入院時・日次ループ・enricher)
        │                      │ 薬剤安全ゲート(§3)
        │                      ▼
        │               投与記録(MAR、§4)
        │                      │ 置換中止 / 退院時の終了(§5)
        ▼                      ▼
退院処方(§6) ──► 在宅薬 ──► 次回以降の受診・経年履歴
                         │
                         ▼
          FHIR MedicationRequest / MedicationAdministration(§6, §7)
```

## 3. オーダー: 安全ゲートと保留

| 規則 | 正準コード | ガード |
|---|---|---|
| 日次ループと入院時の薬剤オーダー候補は、置く前に薬剤安全ゲート(禁忌・相互作用・属性ゲート)を通る。 | `simulator/medication_pipeline.py::apply_drug_safety_gate_to_orders`(入院時は `apply_drug_safety_gate_to_admission_orders`)。規則は `modules/drug_safety/reference_data/contraindications.yaml`, `demographic_gates.yaml` | `tests/unit/modules/drug_safety/`, `tests/integration/test_drug_safety_gate_post_admission.py` |
| 有効な記録済みアレルギー(「アレルギー歴なし」・resolved・refuted を除く)に反する薬剤はオーダーも処方もしない。アレルゲンごとの薬剤系統を回避する(ペニシリンアレルギー: アミノペニシリンを含む全ペニシリン系、アスピリンアレルギー: 非選択的・COX-2 優先的 NSAID とアスピリン、サルファ剤アレルギー: サルファ剤系抗菌薬)か、注意 note 付きで出す(セフェム系、選択的 COX-2 阻害薬、サルファ剤アレルギーでのサイアザイド系・ループ利尿薬とセレコキシブ)。回避した薬剤は safety-skip log に記録し、規則の適応に代替薬があれば置き換える。入院時・日次ループのオーダー、ED のオーダーと持ち帰り処方、慢性薬の抽選と持ち越した在宅薬、退院処方、外来の継続処方、分娩バンドルで確認する。 | `modules/drug_safety/engine.py`(`check_candidate_against_allergies`, `allergy_entries`, `allergy_skip_verdict`)、`simulator/medication_pipeline.py`(`apply_drug_safety_gate_to_orders`, `allergy_blocked`)。呼び出し元 `simulator/emergency.py`, `simulator/discharge_rx.py`, `simulator/outpatient.py`, `simulator/perinatal.py`, `modules/patient/activator.py`, `modules/longitudinal/engine.py`。規則は `modules/drug_safety/reference_data/allergy_contraindications.yaml` | `tests/unit/modules/drug_safety/test_allergy_gate_2924.py` |
| 保留規則は入院時・投与時・退院時で一つの出所から読む(薬剤ごとの腎機能対応、バイタルの保留条件、メトホルミンの腎機能閾値)。 | `medication_pipeline.py`(`renal_medication_rules`, `mar_vital_hold_reason`, `metformin_admission_hold_threshold`)、`discharge_rx.py::renal_hold_drugs`。データ `simulator/reference_data/renal_medication_rules.yaml`, `locale/shared/chronic_medications.yaml` | `tests/unit/test_hold_rules_one_source_2296.py`, `tests/unit/test_medication_holds_acute_illness_1335.py` |
| 薬剤の判断はカタログ上の同一性で行い、名前の部分文字列では行わない。 | `clinosim/codes/drugs.py`(コードマッピング仕様参照) | `tests/unit/test_has_drug_logic_2377.py` |

## 4. 投与

| 規則 | 正準コード | ガード |
|---|---|---|
| 日次ループが置いたオーダーの投与は、オーダーの頻度と患者状態(保留・拒否・頓用の契機)からループ内で作る。 | `medication_pipeline.py::_generate_mar`, `generate_prn_administrations`, `prn_category` | `tests/unit/test_prn_from_state.py`, `tests/unit/test_prn_inhaler_cadence_1318.py` |
| ループ外で置いたオーダー(VTE 予防 enricher、分娩バンドル)の投与は、乱数を引かない一組の補助関数で作る。投与時刻は日次の固定時刻で、看護師は安定ハッシュで選ぶ。投与時刻を自前で決める enricher(HAI の抗菌薬、新生児の出生入院時の予防投与)も、投与した看護師は同じ `stable_nurse` で名指す。 | `modules/order/placed_order_mar.py`(`daily_times`, `stable_nurse`, `administrations_for`) | `tests/unit/modules/order/test_placed_order_mar_spec.py`, `tests/unit/test_hai_abx_giving_nurse_2823.py`, `tests/unit/modules/newborn/test_newborn_giving_nurse_2824.py` |
| オーダーの FHIR timing は頻度を一度だけ述べる。範囲指定("q4-6h")と頓用の上限は一つの解決関数から得る。用量テキストに既にある頻度は繰り返さない。 | `modules/output/fhir_r4/lib/dosage.py`(`resolve_timing_repeat`, `frequency_in_text`) | `tests/unit/output/test_prn_timing_2613.py` |

## 5. オーダーの中止

| 規則 | 正準コード | ガード |
|---|---|---|
| 1 薬剤につき有効なオーダーは一つ。同じ薬剤、または置き換える系統の薬剤(カルバペネム切替など)の新オーダーは、前のオーダーを中止する。前のオーダーは status stopped・終了時刻ありとなり、以後の投与は無い。新オーダーは前のオーダーを先行オーダーとして記録する。 | `modules/order/supersede.py::supersede_orders`。規則は `modules/order/reference_data/medication_supersede.yaml` | `tests/unit/test_supersede_medication_orders_2615.py` |
| 終わった入院の薬剤オーダーは退院(または死亡)時に閉じる。投与があれば completed、無ければ stopped とし、終了時刻を付ける。 | `supersede.py::close_orders_at_discharge` | `tests/unit/test_close_orders_at_discharge_2606.py` |
| 両者はオーダーを置くすべてのモジュールの後、一つの POST_ENCOUNTER enricher で動く。 | `supersede.py::enrich_supersede_orders` | `tests/unit/test_supersede_medication_orders_2615.py` |

## 6. 退院処方と在宅薬

| 規則 | 正準コード | ガード |
|---|---|---|
| 退院処方は、プロトコルの退院薬と継続する在宅薬から作り、腎機能で保留する薬剤を除く。 | `simulator/discharge_rx.py::build_discharge_rx` | `tests/unit/test_build_discharge_rx_continue_at_discharge.py`, `tests/unit/test_discharge_rx_drug_safety_1334.py`, `tests/unit/test_discharge_oral_route_integrity.py` |
| 退院時・在宅薬の有効化・経年履歴は一つの規則リストで突き合わせる。リストの規則が名指す系統の 2 剤目は加えない(スタチン 1 剤、P2Y12 阻害薬 1 剤、抗凝固薬 1 剤、ACE 阻害薬と ARB の併用なし)。 | `modules/drug_safety/engine.py::discharge_reconciliation_rules`。呼び出し元 `discharge_rx.py`, `modules/patient/activator.py`, `modules/longitudinal/engine.py` | `tests/unit/test_discharge_reconciliation_2713.py` |
| 経口抗凝固薬があれば、退院時と在宅薬の有効化で、抗血小板 2 剤を抗凝固薬+クロピドグレルにし、アスピリンを短期にする。 | `discharge_rx.py::limit_triple_antithrombotic`。計画は `contraindications.yaml` `triple_therapy_after_acs` | `tests/unit/test_limit_triple_therapy_2717.py` |
| 退院処方の有限の投与期間(1〜14 日)は在宅薬に引き継がない。0 や期間なしは無期限として引き継ぐ。 | `simulator/helpers.py::is_finite_course`、`simulator/_stay_thresholds.py::ACUTE_COURSE_MAX_DAYS` | `tests/unit/test_finite_course_2757.py` |
| 脂質異常症の患者のスタチンは、LDL が国の閾値以上(US 2018 ACC/AHA: 190 mg/dL、臨床的 ASCVD があれば 70。JP 動脈硬化性疾患予防ガイドライン 2022: 患者のリスク区分の LDL 管理目標値。下のエゼチミブ追加と同じ)だった脂質パネルの次の処方更新の受診で 1 段階増量し、新しい用量で更新する。新しい処方はその薬の前の処方を置き換える。増量した用量は翌年以降のプロファイルでも保つ。スタチンの増量はこれだけで、経年履歴は未治療 LDL の潜在値でスタチンを切り替えない(`lipid_escalate_high_intensity_e78` は年ごとの抽選を残したまま rate 0 で廃止)。 | `simulator/statin_monitoring.py`(`titrate_statin`, `restore_titrated_statin`)。データ `simulator/reference_data/statin_monitoring.yaml` | `tests/unit/simulator/test_statin_monitoring_2877.py` |
| スタチンを増量しない処方更新の受診で、最大スタチン療法中(US: 高強度、アトルバスタチン ≥ 40 mg / ロスバスタチン ≥ 20 mg。JP: 通常最大量、アトルバスタチン 20 mg / ロスバスタチン 10 mg)の脂質異常症の患者は、そのスタチン服用中に採った直近の脂質パネルの LDL が追加の閾値以上(US 2018 ACC/AHA: 臨床的 ASCVD があれば 70 mg/dL、それ以外は 100。JP 動脈硬化性疾患予防ガイドライン 2022: 患者のリスク区分の LDL 管理目標値 — 冠動脈疾患または虚血性脳卒中の既往で 100、糖尿病・CKD・末梢動脈疾患で 120、それ以外は 140)なら、エゼチミブ 10 mg 1 日 1 回を開始する。既に服用中か、記録済みのアレルギーで除外される場合は開始しない。4 週以上後にパネルを再検し、追加した薬は翌年以降のプロファイルでも保つ。エゼチミブの追加はこれだけで、`lipid_escalate_ezetimibe_e78` は年ごとの抽選を残したまま rate 0 で廃止。 | `simulator/statin_monitoring.py`(`add_lipid_add_on`, `restore_lipid_add_on`)。データ `simulator/reference_data/statin_monitoring.yaml` | `tests/unit/test_ezetimibe_measured_ldl_2942.py` |
| 退院処方の状態(active / completed / stopped)、終了日、置き換えた処方は、その患者の全記録とスナップショットにわたって一度だけ計算する。計算はバンドル作成の前に行う。 | `modules/order/prescription_supersede.py::prescription_closures`、`BundleContext.rx_closures` で渡す | `tests/unit/test_prescription_renewal_2610.py` |

## 7. 製品コード

| 規則 | 正準コード | ガード |
|---|---|---|
| JP: YJ 製品コードは、オーダーの投与経路区分で薬剤カタログ(経路区分ごとの `codes.yj`)から選ぶ。その経路の製品が無い薬剤は eCS のコードなしスライスにする。 | `codes/drugs.py::jp_drug_code`, `jp_drug_code_table` | `tests/unit/test_jp_drug_codes_2347.py` |
| US: RxNorm の臨床薬(SCD)は、薬剤・投与経路区分・用量で選ぶ(用量 = 一つの規格の 1〜4 単位)。成分コードをその後に続ける。用量に合う製品が一つに決まらなければ SCD は付けない。 | `codes/drugs.py::rxnorm_scd_code`、表 `codes/data/rxnorm_scd.yaml`(NLM RxNav から取得。取得元と取得日は同ファイルの `metadata` に記載。更新スクリプトはリポジトリに無い)。適用は `fhir_r4/medications/medications.py::_apply_rxnorm_scd` | `tests/unit/codes/test_rxnorm_scd_2614.py` |

## 8. 未対応

既知のものは無い。新たな例外は、それを許すガードとともにここに記す。
