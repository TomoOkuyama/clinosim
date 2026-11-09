# `clinosim.modules.drug_safety`

クラスベースの禁忌併用ゲート + 代替薬 substitution。

## 1. 目的

実 EHR の CPOE (Computerized Physician Order Entry) が処方時点で禁忌
併用を防ぐのと同様に、生成される CIF/FHIR 記録に禁忌併用が現れないよう
にする。 修正前は US p=10,000 コホートで ~150 件の禁忌ペア
(warfarin+aspirin、warfarin+NSAID、β遮断薬+非DHP CCB、ACEi/ARB+K 補充)
が発生していたが、simulator の処方経路 (入院時 / daily loop / ED /
退院処方 / 予防投与) と `patient` activator から呼び出される class ベースの
rule engine によって 0 件に低減する。薬剤 × 疾患状態
(`check_candidate_against_disease_state`)、薬剤 × 年齢/性別
(`check_demographic_gate`)、薬剤 × 記録済みアレルギー
(`check_candidate_against_allergies`、Issue #2924) の禁忌 gate も併せて提供する。

## 2. スコープ

**含まれる**:
- Rule engine: class × class 禁忌 lookup と severity 判定
  (allowed / minor / moderate / major / contraindicated)。
- 薬剤 class × 慢性疾患状態 rule (`disease_contraindications.yaml`、
  Issue #1392 / #1350、stage 条件 `stage_in` は Issue #1769)。
- 年齢 / 性別 gate (`demographic_gates.yaml`、Issue #1316 / #1328)、
  ICD prefix の `exception_indications` で bypass。
- 薬剤 class × 記録済みアレルギー rule (`allergy_contraindications.yaml`、
  Issue #2924): `modules/allergy/reference_data/allergens.yaml` の各医薬品
  アレルゲンを、回避 (block) または注意 (caution) とする class に対応付け、
  交差反応は現行エビデンスに従う。
- 入院中の高カリウム血症対応 (`hyperkalemia.py`、
  `hyperkalemia_response.yaml`、Issue #2981): 血清 K >= 6.0 mmol/L の
  結果が出たら、その時刻以降退院までの ACE 阻害薬・ARB・K 保持性利尿薬の
  投与をすべて休薬 (MAR の status `held`、理由 `K <値> mmol/L`、経過記録の
  計画に `休薬: ...` / `Held: ...` と記載) とし、閾値に達した日ごとに
  国別の治療オーダーセット (グルコン酸カルシウム、レギュラーインスリン +
  50% ブドウ糖、K 吸着薬) を単回投与で出す (翌日以降も閾値以上が続く間は
  K 吸着薬のみ再オーダー)。入院 daily loop から呼ばれ、
  RNG は消費しない。
- 代替薬 substitution: Issue #437 の dead-data `alternative_*` block
  を revive + 新規 `modules/drug_safety/reference_data/drug_substitution.yaml`。
- CIF trace (`PatientProfile.safety_skip_log`)。
- Narrative 統合 (4 layer 全て)。
- MedicationRequest.note[] passthrough (moderate DDI caution)。
- AD-60 スタイルの audit 関数 (stand-alone、audit registry には未登録)。

**含まれない (post-MVP)**:
- `DetectedIssue` FHIR リソースの emit (実 CPOE は skip した order の
  痕跡を残さない; DetectedIssue は薬剤師 review workflow の産物)。
- `allow_if_indication` whitelist (post-PCI+AF、機械弁例外)。
- `antibiotic` モジュール統合。
- 慢性薬の substitution (activator は skip-only)。
- LLM production 評価 (H100 clinician-eye review)。

## 3. 公開 API

```python
from clinosim.modules import drug_safety

# ペア判定 — 順序非依存、RNG 非消費
verdict = drug_safety.check_pair("Warfarin", "Aspirin")
# → SafetyVerdict(severity="contraindicated", rule_id="vka-plus-antiplatelet", ...)

# 複数 active 薬との判定 — caller の loop から使用
verdicts = drug_safety.check_candidate_against_active(
    "Ibuprofen", ["Warfarin", "Amlodipine"],
)  # → [SafetyVerdict(...)] (allowed 以外のペアごとに 1 件)

# 代替薬選択 — disease_ctx 優先、次に共有 pool
alt = drug_safety.suggest_alternative(
    "Ibuprofen", "pain_management",
    active_meds=["Warfarin"], disease_ctx=protocol, country="us",
    allergen_codes=codes,  # アレルギーのある代替薬は選ばない
)  # → AlternativeDrug(drug="Acetaminophen", ...)

# 薬剤 × 慢性疾患状態 — entry は ICD 文字列または (code, stage) tuple
verdicts = drug_safety.check_candidate_against_disease_state(
    "Ibuprofen", ["I50.9"],
)  # → [SafetyVerdict(rule_id="nsaid-in-heart-failure", ...)]

# 薬剤 × 記録済みアレルギー — entry は有効なアレルギー記録の allergen code
# (NKA、resolved、refuted は除く)
codes = drug_safety.allergy_entries(patient.allergies)   # → ["764146007"]
verdicts = drug_safety.check_candidate_against_allergies("Amoxicillin", codes)
# → [SafetyVerdict(rule_id="penicillin-allergy-penicillins", severity="contraindicated", ...)]
drug_safety.allergy_skip_verdict("Ibuprofen", patient.allergies)  # 回避 verdict か None
drug_safety.conflict_display(verdict)  # → ("Penicillin allergy", "ペニシリンアレルギー")

# 年齢 / 性別 gate
dv = drug_safety.check_demographic_gate(
    "Aspirin 325mg", patient_age=8, patient_sex="M", indication_codes=None,
)  # → DemographicVerdict(severity="contraindicated", rule_id="aspirin-pediatric-reyes", ...)

# 退院処方で reconcile する rule id (contraindications.yaml)
drug_safety.discharge_reconciliation_rules()  # → frozenset[str]

# Utility
drug_safety.resolve_classes("warfarin")   # → ["anticoagulant.vka", "anticoagulant"]
drug_safety.canonical_name("ワルファリン")  # → "Warfarin"
drug_safety.japanese_display("Aspirin")   # → "アスピリン"
```

`__all__` の全体: 関数 `check_pair`,
`check_candidate_against_active`,
`check_candidate_against_disease_state`, `check_demographic_gate`,
`check_candidate_against_allergies`, `allergy_entries`,
`allergy_skip_verdict`, `conflict_display`, `condition_entries`,
`suggest_alternative`, `discharge_reconciliation_rules`,
`resolve_classes`, `canonical_name`, `japanese_display`,
`rule_kind` (verdict の `rule_id` が allergy / disease / interaction の
どの種別か)、型
`SafetyVerdict`, `SafetySkipEntry`, `Severity`, `SEVERITY_RANK`
(`clinosim.types.drug_safety` を `verdict.py` 経由で再 export)、
`AlternativeDrug` (`engine.py`)、`DemographicVerdict`
(`demographic.py`)。

## 4. Determinism

- **判定は pure YAML lookup** — RNG 非消費、超越関数・libm 呼び出し
  なし。
- **Substitution は YAML 順で最初の conflict-free 候補を選ぶ** —
  seed に依らず決定論的。選択を変えるには YAML の順序を入れ替える。
- **RNG shape shift**: skip された候補は通常の MR emit が消費した
  はずの RNG を消費せず、代替薬は別の site で emit される。影響患者の
  RNG stream がずれるコホート規模の変化として文書化済み。Version
  bump = MINOR。
- **Cross-platform bit-reproducibility**: `_DeterministicRngProxy`
  regime 下で安全 — dict lookup と文字列比較のみ。

## 5. 依存

- `clinosim.codes.drugs` — 薬剤カタログ (`drug_classes`,
  `drug_display`, `identify_drug`, `resolve_drug`。`_models.py` は
  class / drug id を `all_drug_ids` / `get_drug` でも検証)。
- `clinosim.datafiles` — `load_validated_yaml` (全 reference YAML を
  `_models.py` の Pydantic model 経由で load)。
- `clinosim.locale.localized` — `language_slot`。
- `clinosim.types.drug_safety` — `SafetyVerdict`, `SafetySkipEntry`,
  `Severity`, `SEVERITY_RANK`, `EventType` (`verdict.py` が再 export)。
- `clinosim.modules.disease.protocol` (`alternatives_by_indication`
  の lazy import — disease_ctx を渡した場合のみ)。
- サードパーティ: `pydantic` (YAML スキーマ検証)。
- **それ以外の clinosim 内 runtime 依存はなし。**

## 6. 定数と設定

YAML 6 ファイル + 薬剤カタログ:

- 薬剤 class と alias: 薬剤カタログ
  (`clinosim/codes/data/drugs.yaml`、`clinosim.codes.drugs` 経由で読む)。
- `reference_data/contraindications.yaml` — class × class rule
  (18 rule: VKA+抗血小板薬、DOAC+P2Y12、抗凝固薬+NSAID、
  β遮断薬+非DHP CCB、P2Y12+P2Y12、statin+statin、DOAC+VKA、
  ACEi+ARB、ACEi/ARB+K、ACEi/ARB+K 保持性利尿薬、statin+強力
  CYP3A4 阻害薬、allopurinol+thiopurine、SSRI+MAOI、SSRI+SNRI、
  NSAID 重複、lithium+利尿薬、lithium+ACEi/ARB、lithium+NSAID)、
  加えて `discharge_reconciliation_rules` list と
  `triple_therapy_after_acs` 抗血栓療法 plan。
- `reference_data/disease_contraindications.yaml` — 薬剤 class ×
  慢性疾患 rule (7 rule: 心不全 / 肝硬変 / CKD stage 4-5 (ICD prefix) /
  CKD stage 4-5 (stage 指定) での NSAID、CKD stage 3b-5 での
  metformin、G6PD 欠乏症でのスルホンアミドとニトロフラントイン)。
  慢性薬の抽選時に加え、Issue #2855 以降はすべての新規オーダー
  (`apply_drug_safety_gate_to_orders`) と ED のオーダー・持ち帰り処方にも適用。
- `reference_data/demographic_gates.yaml` — 年齢 / 性別 rule (3 rule:
  aspirin 小児 (Reye 症候群)、nitroglycerin 成人のみ、tamsulosin
  成人男性)。
- `reference_data/allergy_contraindications.yaml` — 薬剤 class ×
  記録済みアレルギー rule (7 rule、Issue #2924)。ペニシリンアレルギーは
  全ペニシリン系 (アミノペニシリン含む) を回避、セフェム系は注意のみ、
  カルバペネムは rule なし (AAAAI/ACAAI 薬物アレルギー practice
  parameter 2022)。アスピリンアレルギーは非選択的・COX-2 優先的 NSAID
  (代替: `pain_management`) とアスピリン自体 (鎮痛薬の代替なし) を回避し、
  選択的 COX-2 阻害薬は注意 (EAACI/ENDA NSAID 過敏症分類)。サルファ剤
  アレルギーはサルファ剤系抗菌薬を回避し、サイアザイド系・ループ利尿薬と
  セレコキシブは注意のみ (Strom, NEJM 2003)。
- `modules/drug_safety/reference_data/drug_substitution.yaml` — 汎用
  indication → 代替薬 pool (カタログ `drug_id` で key 付け。
  pain_management → acetaminophen、hypertension_or_rate_control →
  amlodipine / candesartan)。
- `reference_data/hyperkalemia_response.yaml` — K の治療閾値
  (6.0 mmol/L。KDIGO 2024 CKD、2022 AHA/ACC/HFSA 心不全、UK Kidney
  Association 2020 急性高カリウム血症ガイドライン)、休薬する class
  (`acei`、`arb`、`diuretic.k_sparing`)、US / JP の治療オーダーセット
  (Issue #2981)。オーダー時刻のオフセットは `_hyperkalemia_thresholds.py`。

各ファイルは load 時に `_models.py` の `extra="forbid"` Pydantic
model (`ContraindicationsFile`, `DiseaseContraindicationsFile`,
`DemographicGatesFile`, `DrugSubstitutionFile`,
`AllergyContraindicationsFile`, `HyperkalemiaResponseFile`) で検証される。薬剤 class / drug id は
カタログと照合、rule id は一意、reconciliation list は既存 rule を指し、
アレルギー rule の `allergen_code` は `allergens.yaml` の医薬品
アレルゲンである必要がある。

また Issue #437 の dead-data `alternative_*` block を 15 疾患 YAML
で `_indication_tag` marker 経由で活用する。

## 7. ディレクトリ構造

```
clinosim/modules/drug_safety/
├── __init__.py            # 公開 API 再 export
├── verdict.py             # SafetyVerdict + SafetySkipEntry + Severity + SEVERITY_RANK
├── classifier.py          # 薬剤名 → class[] resolver
├── engine.py              # check_pair / check_candidate_against_active / check_candidate_against_disease_state / check_candidate_against_allergies / suggest_alternative / discharge_reconciliation_rules
├── demographic.py         # check_demographic_gate + DemographicVerdict
├── hyperkalemia.py        # K による休薬 + 高カリウム血症オーダーセット (Issue #2981)
├── _hyperkalemia_thresholds.py  # オーダー時刻のオフセット
├── _models.py             # reference YAML 6 種の Pydantic model
├── audit.py               # audit_drug_safety(patients) → list[AuditFinding]
├── reference_data/
│   ├── contraindications.yaml
│   ├── disease_contraindications.yaml
│   ├── demographic_gates.yaml
│   ├── allergy_contraindications.yaml
│   ├── drug_substitution.yaml
│   ├── hyperkalemia_response.yaml
│   ├── README.md          # YAML スキーマ
│   └── README.ja.md
├── README.md
└── README.ja.md           # 本ファイル
```

## 8. Enricher 配線

**なし** — enricher ではなく library。以下から同期的に呼ばれる:

- `clinosim.simulator.medication_pipeline.apply_drug_safety_gate_to_orders`
  — DDI + 疾患状態 + アレルギー gate + substitution。`simulator/inpatient.py` から
  (`apply_drug_safety_gate_to_admission_orders` wrapper 経由で) 統合
  済み入院時 order に、`simulator/daily_loop.py` から新規 daily-loop
  order に適用。同モジュールの `allergy_blocked` / `log_allergy_skip`
  は代替を出さない処方 (外来 renewal、`simulator/perinatal.py` の産後
  持ち帰り処方と帝王切開の鎮痛薬) をアレルギーで gate する。
- `clinosim.modules.patient.activator._derive_home_medications`
  — 慢性薬選択 loop (DDI + 疾患状態 + アレルギー gate)。skip-only、
  substitution なし。activator は、持ち越した常用薬のうち現在
  アレルギーのあるものも中止する。
- `clinosim.simulator.emergency` — ED order dispatch と持ち帰り処方
  (`check_demographic_gate` + `check_candidate_against_active` +
  疾患状態 + アレルギー rule)。
- `clinosim.simulator.discharge_rx` — active 薬に対する `check_pair`、
  プロトコル薬・継続薬へのアレルギー check (substitution あり)。
- `clinosim.modules.prophylaxis.engine` — VTE 予防投与候補 vs active 薬。
- `clinosim.modules.longitudinal.engine` — 持ち越した常用薬の
  reconcile (`discharge_reconciliation_rules` +
  `check_candidate_against_active`)、記録済みアレルギーで禁忌となる
  追加薬は追加しない。
- `clinosim.simulator.outpatient` と
  `clinosim.modules.order.discontinue_flip` — safety-skip entry 記録
  のため verdict 型を import。

## 9. Output surface

- **FHIR MedicationRequest.note[]**: moderate DDI caution を
  `authorReference.display = "clinosim drug_safety v1"` で付与。
  それ以外は空。DetectedIssue リソースは emit しない。
- **CIF `PatientProfile.safety_skip_log`**: 内部 / audit trace。
  FHIR 構造化リソースには emit しない — 却下された CPOE order が
  カルテに痕跡を残さない実 EHR に合わせる。
- **Narrative (Layer 2)**:
  `clinosim/modules/document/narrative/_template_helpers.py::_render_safety_skips_line`
  が A&P / Plan section に決定論的な bullet 文を追記。
- **Narrative (Layer 3)**: `narrative_seed_bundle.yaml` (v14 以降) が
  `considered_but_not_prescribed` context key
  (`document/narrative/_extra_context_builder.py::_build_extra_context`
  が構築) と REQUIRED INCLUSION rule を持つ。
- **Narrative (Layer 4)**: 予約済み個別 prompt 6 本に将来昇格用の
  sync note を記載。

## 10. テスト

- `tests/modules/drug_safety/test_verdict.py` — SafetyVerdict +
  severity ranking + default_action mapping (8 tests)。
- `tests/modules/drug_safety/test_classifier.py` — alias / 大小文字 /
  JA / 用量 suffix / class 体系 (13 tests)。
- `tests/modules/drug_safety/test_ssri_snri_serotonin_gate.py` —
  SSRI+SNRI / SSRI+MAOI セロトニン gate (28 tests)。
- `tests/modules/drug_safety/test_engine_check_pair.py` — rule hit +
  順序非依存 + RNG 非消費 gate (13 tests)。
- `tests/modules/drug_safety/test_engine_suggest_alternative.py` —
  共有 pool + disease_ctx 分岐 + JP country (10 tests)。
- `tests/modules/drug_safety/test_cif_field_flow.py` — dataclass
  field + narrative context filter (5 tests)。
- `tests/modules/drug_safety/test_audit.py` — AD-60 audit plug-in
  (5 tests)。
- `tests/integration/test_drug_safety_order_hook.py` — order module
  gate + substitution (6 tests)。
- `tests/integration/test_drug_safety_patient_hook.py` — activator
  gate skip-only (3 tests)。
- `tests/integration/test_drug_safety_gate_post_admission.py` —
  daily-loop order gate (5 tests)。
- `tests/integration/test_drug_safety_fhir_emit.py` — MR.note
  passthrough (3 tests)。
- `tests/integration/test_narrative_avoidance_template.py` — Layer 2
  renderer (5 tests)。
- `tests/integration/test_narrative_avoidance_consistency.py` —
  CIF↔narrative 名称追跡 (2 tests)。
- `tests/integration/test_llm_prompt_seed_bundle.py` — Layer 3 prompt
  version + rule + `_build_extra_context` (13 tests)。
- 疾患状態 / 年齢性別 gate と caller 配線:
  `tests/unit/test_drug_safety_disease_state_1350.py`,
  `tests/unit/drug_safety/test_metformin_ckd_contraindication_1769.py`,
  `tests/unit/modules/drug_safety/test_demographic_gate.py`,
  `tests/unit/test_ed_order_drug_safety_1347.py`,
  `tests/unit/test_discharge_rx_drug_safety_1334.py`。
- アレルギー gate: `tests/unit/modules/drug_safety/test_allergy_gate_2924.py`
  (rule、NKA / 無関係アレルギー、order / ED / 退院処方 / activator 配線、
  YAML model)。

コホート検証は `scripts/verify_medical_stats.py` で行い、
`contraindicated_pair_count` (目標: 0) を報告する。

## 11. Ownership

- 2026-09-03 — 初期実装。
- Spec: `docs/superpowers/specs/2026-09-03-drug-safety-module-design.md`。
- Plan: `docs/superpowers/plans/2026-09-03-drug-safety-module.md`。
- Issue: #1066。
