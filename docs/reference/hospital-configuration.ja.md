<!-- README.md から抽出 (Issue #568 PR A2)。本ファイルの見出しが変更されたら README のポインタを更新。 -->

# Hospital 設定

`clinosim/config/hospital_*.yaml` は病院物理レイアウトと運用パラメー
タを定義:

```yaml
# 国別 catchment (CLI が --country で resolve、`default` は fallback)
recommended_population:
  US: 40000     # 50 床 ÷ 130 床/100K ≈ 38K、80% 稼働で 40K に丸め
  JP: 10000     # 50 床 × 365 × 0.80 / 14d LOS ≈ 1,043 入院/年; JP 100/1000/年 → 10K catchment
  default: 40000

available_departments:           # 利用可能な診療科
  - internal_medicine
  - cardiology
  - gastroenterology
  - general_surgery
  - orthopedics
  - emergency_medicine
  - primary_care

department_rollup:              # サブ専門科 → 利用可能な診療科
  pulmonology: internal_medicine
  neurology: internal_medicine
  neurosurgery: general_surgery

wards:                          # 診療科ごとの病棟
  internal_medicine: ["4E", "4W"]
  cardiology: ["5E"]
  general_surgery: ["3E"]
  orthopedics: ["3W"]
  emergency_medicine: ["ER"]
  primary_care: ["OPD"]

ward_capacity:                  # 病棟ごとのベッド数
  "4E": 10
  "4W": 10
  "5E": 8
  "3E": 8
  "3W": 6

resource_capacity:              # 検査/画像 capacity
  lab_analyzers: 2
  ct_scanners: 1
  mri_scanners: 0
  inpatient_beds: 50

staffing:                       # シフトごとのスタッフ比率
  day:    {hours: [8, 16],  lab_staff: 1.0, nursing_staff: 1.0}
  evening:{hours: [16, 0],  lab_staff: 0.5, nursing_staff: 0.7}
  night:  {hours: [0, 8],   lab_staff: 0.2, nursing_staff: 0.5}
```

これにより:
- 自動的な 疾患 → 診療科 → 病棟 → ベッド ルーティング
- 動的検査結果遅延を持つ M/M/1 待ち行列モデル
- 病棟ごとの看護師割り当て (PractitionerRole.location)
- 切り替え可能な病院テンプレート (大 / 中 / クリニック)

`clinosim/modules/facility/README.md` 参照。

---
