# clinosim

> **Clinically Realistic Hospital Data Simulator**

[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![FHIR](https://img.shields.io/badge/output-HL7%20FHIR%20R4-orange)](https://hl7.org/fhir/)
[![Status](https://img.shields.io/badge/status-in%20development-yellow)]()

**clinosim** is a Python framework that simulates the full clinical journey of synthetic patients — from symptom onset and care-seeking behavior, through diagnosis, hospitalization, treatment, and discharge — generating realistic electronic health record (EHR) data grounded in physiology, clinical guidelines, and healthcare system rules.

---

## Why clinosim?

Real patient data is legally restricted, expensive to access, and nearly impossible to share across borders. Most synthetic data generators produce static, template-based records that lack the clinical coherence found in actual hospital data.

clinosim takes a different approach: rather than generating lab values at random, it maintains a **hidden physiological state** for each patient and derives all observations from that state. The result is data where CRP, WBC, and procalcitonin move together in physiologically consistent ways, where a physician's antibiotic switch on Day 3 is traceable to a lack of fever resolution, and where a Japanese patient stays hospitalized for 14 days while their American counterpart is discharged in 5.

---

## Key Features

- **Physiology-driven lab generation** — Lab values are derived from hidden state variables (`inflammation_level`, `renal_function`, `cardiac_function`, etc.), ensuring cross-marker consistency and realistic time-series trajectories.
- **Diagnostic reasoning engine** — Differential diagnosis lists are maintained as probability distributions and updated via Bayes' theorem as test results arrive. Trial-and-error diagnostic patterns leave traceable footprints in the data.
- **Clinical course archetypes** — Patient trajectories follow clinically validated patterns: smooth recovery, dip-then-recovery, plateau, treatment resistance, gradual deterioration, and sudden deterioration.
- **Individual physiological profiles** — Each patient is assigned hidden parameters (immune reactivity, drug metabolism rate, organ reserve, treatment sensitivity) that govern how they respond to illness and treatment throughout their stay.
- **Dual healthcare system support** — Japan (NHI, DPC, long LOS) and the US (private insurance, DRG, early discharge, readmission penalties) are modeled as configurable parameter sets.
- **Realistic data imperfections** — Missing values, measurement noise, timing delays, hemolyzed samples, and post-prandial effects are all generated in context-dependent, non-random ways.
- **HL7 FHIR R4 output** — Generated data is exported as standards-compliant FHIR bundles, with optional CSV and relational DB output.

---

## How It Works

clinosim generates data through a layered simulation pipeline:

```
┌─────────────────────────────────────────┐
│  Patient Profile Generator              │
│  Demographics · Comorbidities ·         │
│  Physiological Profile (hidden params)  │
└────────────────┬────────────────────────┘
                 ↓
┌─────────────────────────────────────────┐
│  Disease Event Scheduler                │
│  Seasonality · Hazard functions ·       │
│  Acute-on-chronic triggers              │
└────────────────┬────────────────────────┘
                 ↓
┌─────────────────────────────────────────┐
│  Diagnostic Reasoning Engine            │
│  Differential Dx list (probability) →  │
│  Bayesian update on each test result →  │
│  Therapeutic trials · Diagnosis drift   │
└────────────────┬────────────────────────┘
                 ↓
┌─────────────────────────────────────────┐
│  Clinical Course Engine                 │
│  State variable time series ·           │
│  Clinical archetype selection ·         │
│  Complication cascade                   │
└────────────────┬────────────────────────┘
                 ↓
┌─────────────────────────────────────────┐
│  Lab & Vital Signs Generation Engine    │
│  Layer 1: Physiological state space     │
│  Layer 2: State → observed values       │
│  Layer 3: Noise · missingness · timing  │
└────────────────┬────────────────────────┘
                 ↓
┌─────────────────────────────────────────┐
│  Consistency Validator                  │
│  Rate-of-change limits ·                │
│  Mutual exclusion checks ·              │
│  Causal ordering constraints            │
└────────────────┬────────────────────────┘
                 ↓
        FHIR R4 / CSV / DB Output
```

---

## Supported Diseases

### Phase 1 (implemented)

| Disease | Type | Japan avg LOS | US avg LOS |
|---|---|---|---|
| Bacterial Pneumonia | Acute / short-stay | ~14 days | ~4–5 days |
| Heart Failure Exacerbation | Chronic acute-on-chronic | ~14–21 days | ~4–6 days |
| Hip Fracture (surgical) | Surgical intervention | ~30 days | ~5 days |

### Phase 2 (planned)

| Disease | Type |
|---|---|
| Acute Myocardial Infarction | Emergency intervention |
| Sepsis | ICU / critical |
| COPD Exacerbation | Chronic acute-on-chronic |
| Diabetic Ketoacidosis | Chronic acute-on-chronic |

---

## Physiological State Variables

Each patient's clinical state is represented by a set of continuous hidden variables that drive all generated observations:

| Variable | Range | Description |
|---|---|---|
| `inflammation_level` | 0.0 – 1.0 | 0 = normal, 1 = critical inflammation |
| `renal_function` | 0.0 – 1.0 | 1 = eGFR > 90, 0 = anuria |
| `cardiac_function` | 0.0 – 1.0 | 1 = EF > 60%, 0 = cardiogenic shock |
| `hepatic_function` | 0.0 – 1.0 | Hepatic function score |
| `anemia_level` | 0.0 – 1.0 | 0 = normal, 1 = severe anemia |
| `coagulation_status` | 0.0 – 1.0 | 0 = normal, 1 = DIC |
| `volume_status` | -1.0 – +1.0 | -1 = severe dehydration, +1 = severe fluid overload |
| `perfusion_status` | 0.0 – 1.0 | 1 = normal, 0 = shock |
| `ph_status` | -1.0 – +1.0 | -1 = severe acidosis, +1 = alkalosis |

Lab values are derived from these variables using physiologically validated mappings. For example, renal impairment propagates to elevated creatinine, BUN, potassium, and bicarbonate changes — all consistent with each other and with the patient's volume status.

---

## Diagnostic Reasoning

Unlike most synthetic data generators that assign diagnoses upfront, clinosim simulates the **process** of diagnosis:

```
Day 0  →  Differential Dx:  Pneumonia 45%,  Influenza 20%,  Viral URI 15%,  Other 20%
           Orders:           CBC, CRP, CXR, urinary antigen
           ↓
Day 1  →  CXR: lobar consolidation (LR+ 8.0 for bacterial pneumonia)
           Differential Dx:  Pneumonia 78%,  Viral URI 8%,  Other 14%
           ↓
Day 1  →  Procalcitonin: 2.5 ng/mL (LR+ 6.0 for bacterial)
           Differential Dx:  Pneumonia 97%,  Other 3%
           → Diagnosis confirmed. Antibiotic initiated.
           ↓
Day 4  →  No fever resolution. Culture: no growth.
           → Atypical organism or resistance suspected.
           → Antibiotic escalated. CT ordered.
```

This produces data where:
- Test ordering has traceable intent
- Diagnosis codes evolve over time ("Pneumonia, unspecified" → "Pneumonia due to Streptococcus pneumoniae")
- Treatment changes are tied to observable clinical triggers
- Diagnostic errors and incidental findings occur at realistic rates

---

## Healthcare System Configuration

The same disease module runs under different national parameter sets:

```python
# Japan: NHI, DPC reimbursement, low discharge pressure
system_japan = HealthcareSystem(
    country="JP",
    gatekeeper=False,
    lab_frequency_multiplier=1.3,
    target_los_multiplier=1.0,
    discharge_criteria="lab_normalization",
    readmission_penalty=False,
    coding_system="ICD-10 + K-code + JLAC10 + YJcode"
)

# US: Private insurance, DRG reimbursement, strong early-discharge pressure
system_us = HealthcareSystem(
    country="US",
    gatekeeper="plan_dependent",   # HMO vs PPO
    lab_frequency_multiplier=0.8,
    target_los_multiplier=0.35,
    discharge_criteria="oral_tolerability",
    readmission_penalty=True,      # ACA 30-day penalty
    coding_system="ICD-10-CM + CPT + LOINC + RxNorm"
)
```

---

## Data Standards

| Item | Japan | US / International |
|---|---|---|
| Diagnosis codes | ICD-10 | ICD-10-CM / ICD-11 |
| Drug codes | YJ code | RxNorm |
| Lab codes | JLAC10 | LOINC |
| Procedure codes | K-code | CPT |
| Output format | HL7 FHIR R4 | HL7 FHIR R4 |

---

## Realism Validation Targets

The following real-world statistics are used as quality benchmarks. A generated population should reproduce these rates within acceptable margins:

| Metric | Target | Source |
|---|---|---|
| 30-day readmission (HF) | 20–25% | CMS, MHLW |
| 30-day readmission (Pneumonia) | 15–20% | CMS, MHLW |
| In-hospital mortality (Sepsis) | 30–40% | Surviving Sepsis Campaign |
| Initial misdiagnosis rate | ~15% | Published literature |
| Dual pathology rate (elderly) | ~20% | Published literature |
| Unresolved diagnosis at discharge | ~10% | Published literature |

---

## Installation

```bash
# Clone the repository
git clone https://github.com/your-org/clinosim.git
cd clinosim

# Install dependencies
pip install -e ".[dev]"
```

**Requirements:** Python 3.10+

---

## Quick Start

```python
from clinosim import Simulator
from clinosim.systems import JapanHealthcareSystem
from clinosim.diseases import BacterialPneumonia

# Initialize simulator
sim = Simulator(
    healthcare_system=JapanHealthcareSystem(),
    disease_modules=[BacterialPneumonia()],
    random_seed=42
)

# Generate 100 patients
population = sim.generate(n_patients=100)

# Export as FHIR R4 bundles
population.export_fhir(output_dir="./output/fhir/")

# Export as CSV (one row per lab result)
population.export_csv(output_dir="./output/csv/")
```

### Sample output (single patient timeline)

```
Patient: 72yo Female  |  Dx: Bacterial Pneumonia  |  System: Japan
──────────────────────────────────────────────────────────────────
Day 0  08:00  Admission vitals: Temp 38.9°C  HR 102  BP 118/72  SpO2 94%
       08:30  Labs ordered: CBC, CRP, PCT, Blood culture x2, CXR
       10:15  CXR result: Right lower lobe consolidation
       10:45  Labs: WBC 14,800  CRP 89  PCT 1.8  Alb 3.1
       11:00  Differential Dx updated: Bacterial pneumonia 91%
       11:30  ABPC/SBT 3g IV q6h initiated

Day 1  06:00  Vitals: Temp 38.4°C  HR 94  BP 122/74  SpO2 96%
       09:00  Labs: WBC 13,100  CRP 112  Cr 0.82  K 3.9
              [Note: CRP still rising — expected Day 1-2 lag]

Day 3  06:00  Vitals: Temp 37.2°C  HR 78  BP 126/76  SpO2 98%
       09:00  Labs: WBC 9,400  CRP 54
              [Trigger: Fever resolved. Antibiotic response confirmed.]

Day 7  09:00  Labs: WBC 7,200  CRP 12  CXR: Partial resolution
Day 14 09:00  Labs: CRP 4  CXR: Near-complete resolution
       14:00  Discharge. Oral AMPC 250mg TID x5 days prescribed.
              Follow-up outpatient at Day 28.
```

---

## Project Structure

```
clinosim/
├── clinosim/
│   ├── core/
│   │   ├── patient.py           # Patient profile & physiological parameters
│   │   ├── state.py             # Physiological state variables
│   │   ├── simulator.py         # Main simulation loop
│   │   └── validator.py         # Consistency validation engine
│   ├── engines/
│   │   ├── lab_engine.py        # Lab value generation (Layer 1-3)
│   │   ├── vital_engine.py      # Vital signs generation
│   │   ├── diagnostic_engine.py # Differential diagnosis & Bayesian update
│   │   ├── treatment_engine.py  # Drug selection, dosing, response
│   │   └── event_scheduler.py   # Disease event timing & seasonality
│   ├── diseases/
│   │   ├── base.py              # Disease module base class
│   │   ├── pneumonia.py         # Bacterial pneumonia module
│   │   ├── heart_failure.py     # Heart failure exacerbation module
│   │   └── hip_fracture.py      # Hip fracture / surgical module
│   ├── systems/
│   │   ├── base.py              # Healthcare system base class
│   │   ├── japan.py             # Japan NHI / DPC system
│   │   └── us.py                # US private insurance / DRG system
│   ├── output/
│   │   ├── fhir.py              # HL7 FHIR R4 export
│   │   └── csv.py               # CSV / tabular export
│   └── config/
│       ├── diseases/            # YAML disease protocol definitions
│       └── systems/             # YAML system parameter definitions
├── tests/
├── examples/
├── docs/
├── pyproject.toml
└── README.md
```

---

## Comparison with Other Tools

| Feature | clinosim | Synthea | google/simhospital |
|---|---|---|---|
| Physiology-driven lab values | ✅ | ✗ | ✗ |
| Diagnostic reasoning process | ✅ | ✗ | ✗ |
| Unknown trajectory modeling | ✅ | ✗ | ✗ |
| Individual physiological profiles | ✅ | △ | ✗ |
| Japan healthcare system | ✅ | ✗ | ✗ |
| DPC / K-code support | ✅ | ✗ | ✗ |
| Therapeutic trial simulation | ✅ | ✗ | ✗ |
| Context-dependent missingness | ✅ | ✗ | △ |
| FHIR R4 output | ✅ | ✅ | ✗ (HL7v2) |
| Language | Python | Java | Go |

---

## Roadmap

### v0.1 — Foundation
- [ ] Patient profile generator
- [ ] Physiological state variable engine
- [ ] Bacterial pneumonia disease module
- [ ] Japan healthcare system
- [ ] FHIR R4 export

### v0.2 — Core Expansion
- [ ] Heart failure exacerbation module
- [ ] Hip fracture / surgical module
- [ ] US healthcare system
- [ ] CSV export
- [ ] Consistency validator

### v0.3 — Diagnostic Reasoning
- [ ] Differential diagnosis engine
- [ ] Bayesian update on lab results
- [ ] Therapeutic trial simulation
- [ ] Diagnostic drift & misdiagnosis patterns

### v0.4 — Realism Refinement
- [ ] Context-dependent missingness model
- [ ] Explainable anomaly patterns (hemolysis, line contamination)
- [ ] Complication cascade (DVT, delirium, hospital-acquired infection)
- [ ] 30-day readmission model

### v1.0 — Full Release
- [ ] Acute myocardial infarction module
- [ ] Sepsis / ICU module
- [ ] COPD exacerbation module
- [ ] Validation report against real-world benchmark statistics
- [ ] Documentation site

---

## Design Philosophy

### 1. State before observation
Lab values are never generated independently. Every observation is derived from an underlying physiological state, ensuring that related markers move in biologically consistent ways.

### 2. Unknown ≠ random
When the mechanism of a patient's trajectory is not explicitly modeled, clinosim uses **constrained stochastic generation**: changes are bounded by physiological rate limits, must not violate mutual exclusion rules, and must have a plausible contextual explanation.

### 3. Process before outcome
Diagnoses are not assigned at admission. The simulation runs the same reasoning process a clinician would follow — generating a differential, ordering tests, updating probabilities, trying treatments, and revising the working diagnosis as evidence accumulates.

### 4. Institution shapes behavior
The same disease produces different data depending on the healthcare system. Reimbursement structure, gatekeeper rules, discharge criteria, and cultural norms are first-class parameters, not afterthoughts.

---

## Contributing

Contributions are welcome, especially from clinicians and medical informaticists who can review the realism of disease modules and physiological mappings.

```bash
# Set up development environment
git clone https://github.com/your-org/clinosim.git
cd clinosim
pip install -e ".[dev]"
pytest
```

Please see [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines on adding new disease modules and healthcare system configurations.

---

## Disclaimer

clinosim generates entirely **synthetic** data. No real patient information is used or produced. The generated data is intended for software development, algorithm research, and system testing only. It should not be used for clinical decision-making or as a source of medical advice.

---

## 開発・修正ガイドライン

### モジュール間依存マトリクス

各モジュールを修正した場合、以下の「整合チェック対象」のモジュールとの整合性を必ず確認してください。

| 修正したモジュール | 整合チェック対象 | チェック内容 |
|---|---|---|
| **healthcare_system** | population, facility, patient, encounter, order, treatment, observation, nursing | 国別パラメータ（保険、検査頻度、退院基準、コード体系等）を参照する全モジュールの整合 |
| **facility** | staff, order, encounter, procedure | 診療科構成・ベッド数・機器キャパシティがスタッフ配置、オーダー処理時間、遭遇ワークフローに影響 |
| **population** | patient, encounter, disease | 人口レジストリ属性（PersonRecord）の変更は、Layer2活性化、エンカウンター生成、疾患発症率計算に波及 |
| **patient** | physiology, treatment, nursing, encounter, observation | 患者プロファイル（生理パラメータ、アレルギー、ADL等）はベースライン状態、薬剤選択、看護リスク評価、バイタル基準値に影響 |
| **disease** | diagnosis, clinical_course, treatment, order, encounter, observation, population | 疾患プロトコルYAMLの変更は、鑑別診断（事前確率・尤度比）、経過アーキタイプ、投薬、オーダーセット、退院基準、検査頻度、発症率に波及 |
| **physiology** | observation, nursing, clinical_course, validator | 状態変数の定義・導出式・coupling ruleの変更は検査値生成、バイタル生成、経過評価、整合性検証に影響 |
| **encounter** | diagnosis, clinical_course, treatment, order, nursing, procedure, staff, output | ワークフロー状態遷移やdaily cycleの変更は全臨床モジュールの呼び出しタイミングに影響 |
| **order** | observation, nursing, staff, facility | オーダーのタイミングモデル・展開ロジックの変更は検査値生成タイミング、看護実施、スタッフ割当に影響 |
| **diagnosis** | treatment, order, encounter, clinical_course | 鑑別診断の更新ロジック変更は治療選択、追加検査オーダー、退院判定、経過評価に影響 |
| **treatment** | clinical_course, order, nursing, physiology | 治療変更ロジックは臨床経過（治療効果）、薬剤オーダー、投薬実施、即時介入効果に影響 |
| **clinical_course** | physiology, encounter, treatment | アーキタイプ・状態遷移の変更は生理状態更新、退院/ICU移送判定、治療効果評価に影響 |
| **observation** | validator, output, diagnosis | 検査値生成（Layer3ノイズ・欠損）の変更は整合性検証、出力データ、診断への結果フィードバックに影響 |
| **nursing** | observation, validator, output | バイタル・MAR・アセスメント生成の変更は検査値タイムライン、整合性検証、出力レコードに影響 |
| **procedure** | physiology, encounter, treatment, output | 手術ワークフローの変更は術中生理変化、遭遇遷移、術後指示、記録出力に影響 |
| **staff** | encounter, order, nursing, procedure, validator | スタッフ配置ルールの変更は全臨床イベントのスタッフ帰属に影響 |
| **validator** | observation（自動修正時） | バリデーションルールの変更は検査値の自動修正に影響 |
| **llm_service** | diagnosis, treatment, encounter, nursing, validator | プロンプトテンプレート・モデル設定・レスポンスパーサーの変更は全ナラティブ生成と臨床判断に影響 |
| **output** | （下流なし） | 出力フォーマットの変更は他モジュールに影響しない |
| **simulator** | （オーケストレーター） | パイプライン実行順序の変更は全モジュールの呼び出しタイミングに影響 |

### モジュール依存の方向図

```
    healthcare_system
    (config root: all modules depend on this)
    |
    +-------------+----------------------------+
    |             |                            |
    v             v                            v
  facility ---> staff                     population
    |                                         |
    |                                     patient
    |                                     (L1->L2)
    |                                         |
    +-------------------+---------------------+
                        |
                        v
  disease ---------> encounter
    |              (workflow driver)
    |                 |
    |       +---------+-----------+
    |       |         |           |
    |       v         v           v
    +-> diagnosis   order <--> nursing
    |       |         |           |
    |       v         v           |
    +-> treatment     |           |
    |       |         |           |
    |       v         v           v
    +-> clinical   physiology  observation
        _course       |           |
                      |    procedure
                      |           |
                      +-----+-----+
                            |
                            v
                        validator
                            |
                            v
                          output

  llm_service (cross-cutting service: used by all, no reverse dependency)
```

### 修正時の手順

1. **修正対象モジュールのSPEC.mdを読む** — 現在の仕様を確認
2. **修正を加える**
3. **上の依存マトリクスを参照** — チェック対象モジュールを特定
4. **各チェック対象のSPEC.mdを確認** — 整合性が崩れていないか検証
5. **必要に応じてチェック対象モジュールのSPEC.mdも更新**
6. **INTERFACES.mdを確認** — データ型の変更が必要な場合は必ずINTERFACES.mdを先に更新し、全モジュールに波及

### 重要ルール

- **INTERFACES.md は全モジュールの契約** — ここの型定義を変更したら、その型を使う全モジュールの整合確認が必須
- **disease プロトコルYAML の変更は影響範囲が最大** — 診断、治療、オーダー、経過、退院基準の全てに波及する
- **healthcare_system の変更は全モジュールに影響** — 国別パラメータは全ての振る舞いの基盤
- **physiology の導出式変更は検査値の全数値に影響** — 変更後は必ずvalidatorで検証
- **llm_service のプロンプト変更は出力テキストの品質に影響** — プロンプト変更時は生成サンプルの品質確認を行うこと

---

## License

MIT License. See [LICENSE](LICENSE) for details.

---

## Citation

If you use clinosim in your research, please cite:

```bibtex
@software{clinosim,
  title  = {clinosim: Clinically Realistic Hospital Data Simulator},
  year   = {2025},
  url    = {https://github.com/your-org/clinosim}
}
```
