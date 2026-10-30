# 評価ルール

このページは `clinosim eval` が実行する全 check、その severity、
スコアリング式、および (clinical coherence check については) 期待帯
の文献ソースをカタログ化します。CLI 使用は [Evaluation](eval.ja.md)
参照。

## 軸レベル rollup

各軸について:

- **スコア** = 100 × Σ(check pass-weight × check weight) / Σ(check weight)
- **Check weight** = severity: CRITICAL = 3、MAJOR = 2、MINOR = 1
- **Pass-weight** = PASS 1.0、WARN 0.5、FAIL 0.0、N/A 0.0

**Overall score** = レポート中の全軸結果 (軸 × 国サブディレクトリごと
に 1 件) のうち該当する軸のスコアの算術平均。コホートの locale に該当
しない国条件軸は check を返さず status `N/A` となり、平均に含めない。
**Overall status** = 軸横断で FAIL / WARN / PASS の最悪。

---

## Structural 軸 (5 checks)

コンテンツ品質にかかわらず FHIR R4 不変条件を破るコホートを拒否。

| Name | Severity | Passes when |
| --- | --- | --- |
| `resource_id_uniqueness` | CRITICAL | 同一 resourceType 内で `id` 重複なし |
| `reference_integrity` | CRITICAL | 全内部 `reference` (`Type/id`) が emit 済リソースに解決 |
| `required_fields_present` | MAJOR | Patient.identifier / Encounter.status / Condition.subject が非空 |
| `meta_profile_declared` | MAJOR (JP) | 全 JP Core primary resourceType が `meta.profile` を宣言; 非 JP は N/A |
| `resource_type_consistency` | MINOR | 全 NDJSON 行の `resourceType` がファイル名と一致 |

---

## Clinical 軸 (7 checks)

**MVP** (P1-8) — schema レベルの生理学的妥当性を守る 5 checks:

| Name | Severity | Passes when |
| --- | --- | --- |
| `lab_values_physiological_range` | MAJOR | LOINC コード付き検査値が生理範囲内 (WBC 0–500、Hb 0–25、Cr 0–30 …) |
| `age_condition_consistency` | MAJOR | 小児患者 (< 12 歳) に adult-only ICD コード (I10 / I25 / I48 / I50 / E11 / N18 / N40 / F03) なし |
| `medication_date_sanity` | MAJOR | MedicationRequest.authoredOn ≥ Patient.birthDate |
| `encounter_temporal_ordering` | MAJOR | Encounter.period.start ≤ .end |
| `condition_encounter_link` | MINOR | Condition.encounter が設定されている場合、emit 済 Encounter に解決 |

**Coherence** (P1-9) — schema-valid だが **臨床的に非妥当** なデータを
フラグする 2 checks — 「敗血症だが lactate 上昇なし」系。

### `condition_lab_coherence` (MAJOR)

以下のペアリング条件のいずれかにマッチする各 Condition について、
同一患者の関連検査を Condition 発症の **±7 日** 内で探索。検査値が
期待帯外なら違反としてカウント。全ペアリングで集約:

- 違反率 ≤ **5%** → PASS
- 5% – 25% → WARN
- > 25% → FAIL

5% 未満は自然な生物学的ばらつきと小さいウィンドウのミスマッチを
反映。25% 超は生理学モデルが診断ラベルから乖離していることを示唆。

| ペアリング名 | ICD プレフィックス | Lab (LOINC) | 期待帯 | ソース |
| --- | --- | --- | --- | --- |
| `sepsis_lactate` | A41.* | 2524-7 (静脈 lactate) | **≥ 2.0 mmol/L** | [Surviving Sepsis 2021](https://www.sccm.org/SurvivingSepsisCampaign/Guidelines/Adult-Patients) |
| `dka_hco3` | E10.10-11、E11.10-11 | 1963-8 (HCO₃) | **< 18 mEq/L** | [ADA DKA severity criteria](https://diabetesjournals.org/care/article/32/7/1335) |
| `acute_mi_troponin` | I21、I22 | 10839-9 (Troponin I) | **> 0.04 ng/mL** (99th %ile URL) | [Fourth Universal Definition of MI](https://www.jacc.org/doi/10.1016/j.jacc.2018.08.1038) |
| `ckd_stage_creatinine` | N18.3-N18.5 | 2160-0 (Cr) | **> 1.3 mg/dL** | [KDIGO 2012](https://kdigo.org/guidelines/ckd-evaluation-and-management/) |
| `t2dm_hba1c` | E11.9 (uncontrolled T2DM) | 4548-4 (HbA1c) | **≥ 6.5%** | [ADA 診断閾値](https://diabetesjournals.org/care/article/47/Supplement_1/S20/153954) |
| `bacterial_pneumonia_wbc` | J13、J14、J15 | 6690-2 (WBC) | **> 11.0 × 10⁹/L** | SIRS / 感染応答 |
| `anemia_hgb` | D50–D64 (D54–D61 除く) | 718-7 (Hb) | **< 12.0 g/dL** | [WHO 貧血 cutoff](https://www.who.int/publications/i/item/9789240088542) |
| `chf_bnp` | I50.* | 30934-4 (BNP) | **> 100 pg/mL** | Framingham / [ACC-AHA HF ガイドライン](https://www.acc.org/latest-in-cardiology/ten-points-to-remember/2022/04/06/12/57/2022-aha-acc-hfsa-guideline-for-the-management-of-hf) |

ペアリングは
[`clinosim/codes/data/condition-lab-pairings.yaml`](https://github.com/TomoOkuyama/clinosim/blob/master/clinosim/codes/data/condition-lab-pairings.yaml)
から読み込まれる (`lab_values_physiological_range` の範囲も同様に
`clinosim/codes/data/lab-plausibility-bounds.yaml` から)。ペアリング
追加はこの yaml の `pairings:` 配下にエントリを追加し、このページに
ソースを引用。

### `medication_lab_coherence_warfarin` (MAJOR)

患者が warfarin (RxNorm `11289` または YJ code プレフィックス
`3332001`) の MedicationRequest を持つ場合、最も早い warfarin
`authoredOn` から **5 日以上後** に採取された全 PT-INR observation
(LOINC `6301-6`) は **2.0–3.5** の範囲内でなければならない。最初の
5 日間 (INR がまだベースラインから上昇中の導入期) の採取は除外。
違反率はペアリングと同じ 5% / 25% 閾値。

このバンドは AF 脳卒中予防適応の 2.0–3.0 目標より広い。合併症
(肝硬変、DIC) が正当に INR を 3.0–3.5 側にシフトするため。生理
エンジン (AD-57) の Warfarin PT-INR カップリングはこれに合わせて
較正済み。

---

## Locale 軸 (5 checks)

コホート country は `<root>/<country>/fhir_r4/` レイアウトでは国
サブディレクトリ名、フラットな `<root>/fhir_r4/` レイアウトでは最初の
Patient の `address.country` または JP Core `meta.profile` の有無から
自動検出 (fallback: US)。`--country` は採点対象の国サブディレクトリを
選ぶもので、検出された locale を上書きはしない。

### JP コホート

| Name | Severity |
| --- | --- |
| `japanese_displays_on_condition` | MAJOR |
| `jlac10_or_loinc_on_lab` | MAJOR |
| `yj_code_on_medications` | MAJOR |
| `jp_core_profile_declared` | MAJOR |
| `jp_name_order` | MINOR |

### US コホート

| Name | Severity |
| --- | --- |
| `ascii_only_displays` | MAJOR |
| `rxnorm_present_on_medications` | MAJOR |
| `loinc_present_on_lab_observations` | MAJOR |
| `no_japanese_leakage` | CRITICAL |
| `us_practitioner_name_order` | MINOR |

## JP-CLINS lab compliance 軸 (JP コホートのみ)

`JP_Observation_LabResult_eCS` 準拠を検査 Observation の
`code.coding` で測定。閾値: 100 % at master invariant に対し strict 1.0
(eCS は `code.coding` が Open slicing で discriminator=system+display
なので validator pass 数単独では不十分 —
`clinosim/eval/axes/jp_clins_lab_compliance.py` 参照)。全 check は
MAJOR、検査 Observation が無いコホートでは各 check が N/A。

| Name | Passes when |
| --- | --- |
| `jp_clins_lab_cs_usage` | 全検査 Observation が JP-CLINS 定義の CodeSystem を持つ |
| `jp_clins_lab_fixed_display` | slice 型の全 coding が eCS の固定 display を持つ |
| `jp_clins_lab_rule_satisfaction` | 全検査 Observation が `localLaboCode` + typed coding 1 つを持つ |

## JP Core compliance 軸 (JP コホートのみ)

JP Core Patient / Encounter / MedicationRequest の must-support
element への narrow-gate 準拠測定。閾値 1.0 at 100 %-at-master
invariant のみ。Kana (SYL) 表現 coverage の拡張は別途管理。full HL7
FHIR Validator 走行 (`jp-validate.yml`) は on-demand の authoritative
compliance surface。`clinosim/eval/axes/jp_core_compliance.py` 参照。
Check (全て MAJOR): `jp_core_patient_profile_declared`、
`jp_core_patient_identifier_present`、`jp_core_patient_name_family_given`、
`jp_core_patient_kanji_representation`、`jp_core_encounter_class_present`、
`jp_core_encounter_period_present`、
`jp_core_medicationrequest_medication_coding_present`。

## US Core compliance 軸 (US コホートのみ)

US Core AllPatients / Encounter / Condition の must-support element
への narrow-gate 準拠測定。閾値 1.0 at 100 %-at-master invariant
のみ (race/ethnicity extension coverage のような拡張は別途管理)。
Phase 3 の full validator 走行 (`us-validate.yml`) は on-demand の
authoritative compliance surface。`clinosim/eval/axes/us_core_compliance.py` 参照。
Check (全て MAJOR): `us_core_patient_identifier_present`、
`us_core_patient_name_family_given`、`us_core_patient_birthsex_extension_valid`、
`us_core_patient_race_extension_shape`、`us_core_patient_ethnicity_extension_shape`、
`us_core_encounter_class_v3_actcode`、`us_core_condition_category_system`。

---

## ルール追加

1. [`clinosim/eval/axes/`](https://github.com/TomoOkuyama/clinosim/tree/master/clinosim/eval/axes/)
   配下の該当軸ファイルを開く。
2. `_check_<name>(cohort, country) -> EvalCheck` ヘルパーを追加。
   `Outcome.PASS` / `WARN` / `FAIL` / `NA` と `Severity` を持つ
   `EvalCheck` を返す。
3. 軸の `run()` 戻り値リストに append。
4. [`tests/unit/test_eval_axes.py`](https://github.com/TomoOkuyama/clinosim/blob/master/tests/unit/test_eval_axes.py)
   に FAIL outcome を発火する最小ミニコホートを組む単体テストを追加。
5. check が新しい臨床閾値を消費するなら、このページにソースを引用。
6. `CHANGELOG.md` を更新。

小さくスコープの明確な追加は一発リライトよりレビューが速い。
