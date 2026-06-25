# Phase 3b-1 — HAI Empirical Antibiotic Regimen (Design Spec)

**Date**: 2026-06-25
**Status**: Approved (brainstorming complete; ready for `writing-plans`)
**Author**: clinosim
**Related**:
- Phase 3a HAI WBC + CRP forward-delta lift (`docs/reviews/2026-06-25-phase3a-hai-lab-lift-data-quality-review-post-fix.md`)
- AD-60 audit framework Phase 1 (`docs/reviews/2026-06-25-clinosim-audit-baseline.md`)
- AD-55 Module pattern (PR-A device, PR-B HAI)

---

## §1. Phase 3b Overview + PR3b-1 Scope

### Phase 3b 全体 (4 PR 逐次)

HAI 発症後の臨床抗菌薬 chain:

```
HAI onset (Phase 3a, shipped)
  ↓
PR3b-1 (this spec): empirical antibiotic 開始 (organism-agnostic, IDSA guideline-based)
  ↓
PR3b-2: culture S/I/R metadata 充足 (antibiogram × per-isolate sampling)
  ↓
PR3b-3: narrow への de-escalation (S 判明後、新 MedicationRequest + 旧 stop)
  ↓
PR3b-4: WBC/CRP forward-delta decay (antibiotic start_day → exponential decay back to baseline)
```

### PR3b-1 scope (本 spec が cover する範囲)

In-scope:
- HAI event (CLABSI / CAUTI / VAP) を契機とした IDSA guideline ベースの経験的抗菌薬投与
- `record.orders` に MedicationRequest 用 `Order(OrderType.MEDICATION)` を append
- `record.medication_administrations` に daily MAR (`MedicationAdministration`) を append
- `extensions["antibiotic"] = list[AntibioticRegimen]` を書き、後続 PR3b-2/3/4 の cross-module consumption 起点とする
- 新 `modules/antibiotic/` Module (AD-55 **always-on Module = near-essential clinical cascade**、`extensions["hai"]` 不在時は完全 no-op)
- 新 `modules/antibiotic/audit.py` = AD-60 framework 本格運用 2 例目

### Why always-on (not opt-in)

PR-A device + PR-B hai は `enabled=lambda c: True` の always-on pattern を採用済。HAI 発症 → empirical antibiotic は IDSA guideline で「即時開始」が標準で、**「HAI を生成するが抗菌薬は生成しない」状態は臨床的に存在しない**。Spec §1 を opt-in と書いた当初の意図は AD-55 Module 枠組みの安全性確保だったが、4 軸評価(`feedback_decision_axes`)の結果、**臨床的にコヒーレント**な状態を生成する CLAUDE.md 原則に従えば always-on が正しい。

これを AD-55 の **「always-on Module = near-essential clinical cascade」** カテゴリとして明示化する(DESIGN.md 補足 ADR に記載予定)。device / hai / antibiotic(本 PR)/ 将来の narrow / decay は同カテゴリ。

Out-of-scope (Phase 3b 後続 PR or later):
- Organism-targeted narrowing (PR3b-2/3)
- Susceptibility S/I/R metadata 充足 (PR3b-2)
- WBC/CRP decay coupling (PR3b-4)
- Renal adjustment (eGFR-based dose modification, future)
- Severity tier 別 escalation (future)
- Allergy override (future)
- Antifungal / antiviral (future)

### Why empirical only

PR3b-1 の "empirical" 定義 = culture 結果を**知らない**段階の経験的処方。これは臨床ワークフローの本物の最初の決定点であり、後続 PR の narrow が de-escalation できる baseline regimen が必須。Organism-agnostic な処方は IDSA guideline で per-HAI-type 1 種類に collapse できる(下記 §3.1)。

---

## §2. Module 構造とデータフロー

### 新ディレクトリ

```
clinosim/modules/antibiotic/
  __init__.py            # ANTIBIOTIC_DRUGS canonical tuple
  engine.py              # 純粋関数 (build_regimen / generate_mar_doses / YAML loader)
  enricher.py            # POST_ENCOUNTER stage, order=85
  audit.py               # AD-60 plug-in
  reference_data/
    hai_empirical.yaml   # IDSA 2009 / 2016 guideline ベース
  README.md              # JP, .github/TEMPLATE_MODULE_README.md 準拠
```

### 新タイプ

`clinosim/types/antibiotic.py`:

```python
@dataclass
class AntibioticRegimen:
    """One empirical antibiotic regimen attached to a single HAI event."""

    regimen_id: str           # "abx-{hai_event_id}-{drug_key_slug}"
    hai_event_id: str         # PR-B HAIEvent.hai_id 連結 (cross-module consumption 起点)
    encounter_id: str
    drug_key: str             # canonical name in ANTIBIOTIC_DRUGS (locale neutral)
    dose: str                 # e.g. "1g", "3.375g" (locale neutral string per disease YAML convention)
    route: str                # "IV" (PR3b-1 は全 IV)
    frequency: str            # "q12h" / "q6h" / "q24h" (既存 _FREQ_PER_DAY parser 互換)
    start_datetime: datetime  # HAI onset_date の 08:00 (empirical = same day, morning round)
    duration_days: int        # IDSA: CLABSI/VAP=14, CAUTI=7
    intent: str               # "empirical" (PR3b-3 で "narrowed" 追加予定)
```

`CIFPatientRecord.extensions["antibiotic"] = list[AntibioticRegimen]` で保持。Base typed field には**追加しない**(opt-in Module = extensions のみ、CLAUDE.md "Modules must NOT edit `CIFPatientRecord`")。

### `clinosim/modules/antibiotic/__init__.py`

```python
ANTIBIOTIC_DRUGS = (
    "Vancomycin",
    "Piperacillin/Tazobactam",
    "Ceftriaxone",
)
```

PR-90 教訓 = single source of truth for string keys、YAML loader が import 時 cross-validate して `ValueError` raise。

### データフロー

```
POST_ENCOUNTER stage (encounter simulator 内、daily loop 完了直後、AD-56)
  ├── enricher.device       order=70  → ext["device"]
  ├── enricher.hai          order=80  → ext["hai"] + record.microbiology.append()
  └── enricher.antibiotic   order=85  ← 本 PR (NEW)
        ↓
        for ev in ext["hai"]:                      # consume PR-B output
            regimen = build_regimen(ev)
            ext["antibiotic"].append(regimen)
            record.orders.append(Order.MEDICATION)
            record.medication_administrations.extend(generate_mar_doses(regimen, encounter, snapshot_dt))

(順序非依存に並走: apply_hai_lab_lift もこの後 POST_ENCOUNTER 内で fires、ext["hai"] のみ読む)
```

---

## §3. 設計判断と確立 patterns 踏襲

### §3.1 Per-HAI-type single empirical regimen (IDSA guideline)

| HAI type | Empirical regimen | Duration | Source |
|---|---|---|---|
| CLABSI | Vancomycin q12h + Piperacillin/Tazobactam q6h | 14 days | IDSA 2009 Clinical Practice Guidelines for the Diagnosis and Management of Intravascular Catheter-Related Infection |
| CAUTI | Ceftriaxone q24h | 7 days | IDSA 2009 International Clinical Practice Guidelines for the Diagnosis and Treatment of Catheter-Associated UTI |
| VAP | Vancomycin q12h + Piperacillin/Tazobactam q6h | 7 days | IDSA/ATS 2016 Management of Adults With HAP/VAP |

Dose は IDSA + UpToDate に基づく average adult ICU dosing (renal adjustment は PR3b-1 では行わない):
- Vancomycin: 1g IV q12h (load 25-30 mg/kg は簡略化、固定 1g)
- Piperacillin/Tazobactam: 3.375g IV q6h
- Ceftriaxone: 1g IV q24h

### §3.2 Storage strategy = dual write

| 書き先 | 目的 | 読み手 |
|---|---|---|
| `record.orders.append(Order)` | FHIR MedicationRequest 自動 emit | 既存 `_fhir_medications.py:_build_medication_request` |
| `record.medication_administrations.append(MAR)` | FHIR MedicationAdministration 自動 emit | 既存 `_fhir_medications.py:_build_medication_administration` |
| `extensions["antibiotic"]` | Module-internal cross-PR consumption | PR3b-2/3/4 enricher |

責任分離: Base typed field = FHIR-facing emission target / extensions[] = internal module state (cross-module read 経路)。

### §3.3 確立 patterns 踏襲

| 設計軸 | 採用 pattern | source |
|---|---|---|
| sub-rng offset | `ENRICHER_SEED_OFFSETS["antibiotic"] = 0x4142` ("AB"), per-patient sub-seed via `derive_sub_seed(master, 0x4142, pid)` | `simulator/seeding.py` 既存 9 module, hex-ASCII convention |
| canonical constants | `ANTIBIOTIC_DRUGS` tuple in `modules/antibiotic/__init__.py`, YAML loader が import 時 `ValueError` raise | HAI_TYPES (PR-90 教訓) |
| cross-module consumption | `AntibioticRegimen.hai_event_id = HAIEvent.hai_id` で一方向紐付け | device → hai pattern (PR-A → PR-B) |
| FHIR builder | **新規ゼロ** = 既存 `_fhir_medications.py` が再利用 | HAI culture pattern (PR-B reuses `_fhir_microbiology`) |
| coding | US: RxNorm via `code_mapping_drug/us.yaml` / JP: YJ via `code_mapping_drug/jp.yaml` | 既存 drug mapping (Ceftriaxone / Pip-Tazo 既存、Vancomycin 新規追加) |
| stage / order | POST_ENCOUNTER, order=85 (after hai=80) | AD-56, Phase 3a enricher 順序 |
| enablement | `enabled=lambda c: True` (always-on、HAI 不在時 no-op) | device + hai と pattern 統一 |
| snapshot truncation | MAR 生成時に `mar_dt > snapshot_dt` を切り捨て | AD-32, Phase 3a 既設計 |
| locale fields | `_localize_drug_name`, `_strip_protocol_prefix`, `_ROUTE_SNOMED` を `_fhir_medications.py` が既に処理 | FA-1 既設計 |

### §3.4 Code authoritative verification (impl time, never fabricate)

| Code | Source to verify against |
|---|---|
| `Vancomycin` RxNorm CUI | NLM RxNav API: `rxnav.nlm.nih.gov/REST/rxcui/<cui>/property.json?propName=RxNorm%20Name` |
| `Vancomycin` YJ code | MEDIS-DC HOT/YJ master (`medis.or.jp`) |
| `Ceftriaxone` (既存 RxNorm 2193 / YJ 6132413) | spot-check NLM RxNav + MEDIS HOT during impl |
| `Piperacillin/Tazobactam` (既存 RxNorm 139462 / YJ 6131700) | spot-check NLM RxNav + MEDIS HOT during impl |
| IDSA duration 14 / 7 / 7 days | IDSA 2009 CLABSI / IDSA 2009 CAUTI / IDSA-ATS 2016 HAP/VAP guideline docs |

仮値で書いて `# TODO: verify` を残すのは不可(`feedback_verify_before_asserting`)。impl 時に上記 source で照合し、見つからない場合は別のレジメンへ切替するか impl 停止して再相談する。

---

## §4. AD-60 audit framework 本格運用 2 例目 — `modules/antibiotic/audit.py`

### ModuleAuditSpec(HAI 同型)

```python
register_audit_module(ModuleAuditSpec(
    name="antibiotic",
    canonical_constants={
        "hai_type": HAI_TYPES,
        "drug_key": ANTIBIOTIC_DRUGS,
    },
    yaml_keys_to_validate={
        str(_HAI_EMPIRICAL_YAML): ("hai_empirical",),
    },
    structural_obs_codes={},  # antibiotic は Observation でなく MedicationRequest/MAR なので空、PR3b-2 で susceptibility Observation 追加時に拡張
    clinical_acceptance={
        "clabsi": {
            "icd10_code": "T80.211A",
            "expected_drugs": ("Vancomycin", "Piperacillin/Tazobactam"),
            "expected_duration_days": 14,
            "min_mar_per_event": 14*4 + 14*2,  # Pip-Tazo q6h × 14d + Vanc q12h × 14d
        },
        "cauti": {
            "icd10_code": "T83.511A",
            "expected_drugs": ("Ceftriaxone",),
            "expected_duration_days": 7,
            "min_mar_per_event": 7,
        },
        "vap": {
            "icd10_code": "J95.851",
            "expected_drugs": ("Vancomycin", "Piperacillin/Tazobactam"),
            "expected_duration_days": 7,
            "min_mar_per_event": 7*4 + 7*2,
        },
    },
    lift_firing_proof=_build_synthetic_proof,
))
```

### `lift_firing_proof` = load-bearing PR-90 type silent no-op gate

合成 record で end-to-end enricher path を drive し、期待される副作用を closed-form で照合:

```python
def _build_synthetic_proof():
    # Construct minimal record with 1 CAUTI HAIEvent at known onset_date
    encounter = SimpleNamespace(encounter_id="enc-1", admission_datetime=...)
    record = SimpleNamespace(
        patient=...,
        encounters=[encounter],
        orders=[],
        medication_administrations=[],
        microbiology=[],
        extensions={"hai": [HAIEvent(
            hai_id="h-cauti-1",
            encounter_id="enc-1",
            hai_type="cauti",       # HAI_TYPES[1] (canonical, NOT literal string)
            ...
            onset_date="2026-01-10",
        )]},
    )
    ctx = SimpleNamespace(records=[record], master_seed=42, country="US",
                          snapshot_datetime=datetime(2026, 2, 1))

    # Execute enricher
    from clinosim.modules.antibiotic.enricher import enrich_antibiotic
    enrich_antibiotic(ctx)

    # Closed-form expected
    return {
        "ext_antibiotic_count": 1,
        "ext_antibiotic_drug": "Ceftriaxone",
        "ext_antibiotic_duration_days": 7,
        "orders_medication_count": 1,
        "mar_count": 7,                                # q24h × 7d
        "mar_drug": "Ceftriaxone",
        "mar_first_dt": datetime(2026, 1, 10, 8, 0),   # onset 08:00
        "mar_last_dt":  datetime(2026, 1, 16, 8, 0),   # +6 days
    }
```

AD-60 silent_no_op 軸が `actual == expected` を per-field assert。PR-90 で欠落していた load-bearing 検証を framework 標準として組み込む。

### 4 軸の対応

| 軸 | 検査内容 |
|---|---|
| structural | (1) MedicationRequest.medicationCodeableConcept に有効な RxNorm/YJ code、(2) MedicationAdministration → MedicationRequest reference 整合、(3) display != code、(4) all MAR.effective_dt ∈ [encounter.admission_dt, snapshot_dt] |
| clinical | (1) HAI event 数 × min_mar_per_event ≤ MAR 数(cohort 集計、Poisson rare-event 受容)、(2) duration_days median = expected (per HAI type) |
| jp_language | JP で全 drug.display が日本語(`Vancomycin → バンコマイシン`、`Ceftriaxone → セフトリアキソン`、`Piperacillin/Tazobactam → ピペラシリン/タゾバクタム`)、route_snomed = `_ROUTE_SNOMED["IV"]` canonical |
| silent_no_op | canonical_constants cross-check + yaml_keys_to_validate + lift_firing_proof |

---

## §5. テスト方針

### TDD plan の枠組み

| 種別 | 内容 | rationale |
|---|---|---|
| unit | `engine.build_regimen(hai_event_dict) → list[AntibioticRegimen]` (3 HAI type × 期待 regimen) | 核ロジック |
| unit | `engine.generate_mar_doses(regimen, encounter, snapshot_dt) → list[MedicationAdministration]` (snapshot truncation 含む) | 核ロジック + AD-32 |
| unit | YAML loader = import 時 unknown HAI key → `ValueError`、unknown drug_key → `ValueError` | PR-90 教訓 |
| unit | `_FREQ_PER_DAY` parser 互換 (`q6h` → 4, `q12h` → 2, `q24h` → 1) | 既存 parser 信頼 |
| integration | **forced-scenario test** = 合成 record(direct ext["hai"] inject)→ `enrich_antibiotic(ctx)` 呼出 → orders / MAR / ext["antibiotic"] が期待通り生成 | PR-90 enricher path drive 教訓 |
| integration | per-patient sub-rng 独立性: 同一 patient 異なる master_seed → 異なる結果、同一 seed → 同一結果 (idempotency) | AD-16 |
| integration | byte-diff invariant: opt-in module OFF → 既存 NDJSON byte-IDENTICAL / ON → opt-in NDJSON のみ delta、他 NDJSON 既存記録不変 | AD-16 / AD-59 同型 |
| audit | `clinosim audit run --module antibiotic` で 4 軸 + lift_firing_proof PASS | AD-60 |
| e2e | 既存 e2e golden は opt-in OFF default なので変化なし、新 e2e (forced-scenario property test 1 件) 追加可能 (任意) | regression 防御 |

### byte-diff スコープ

- master `5401cc37` (HEAD) vs branch、p=2000 seed=42、US + JP
- 期待: `medication_administrations.ndjson` + `medication_requests.ndjson` のみ delta (HAI 発症患者の cohort)、他 NDJSON は byte-IDENTICAL
- HAI rare-event なので絶対量は小 (p=2000 で ~1-2 event 期待、p=10k で ~4-6)
- p=10k DQR で完全 clinical_acceptance 検証 (rare-event WARN 受容、`silent_no_op` axis lift_firing_proof は p=2000 でも load-bearing)

### TDD task 順序 (writing-plans skill で詳細化)

1. `clinosim/types/antibiotic.py:AntibioticRegimen` + `ANTIBIOTIC_DRUGS` canonical (新)
2. `hai_empirical.yaml` + loader (`@lru_cache`, import 時 validation)
3. `engine.build_regimen(hai_event)` + unit tests (3 HAI type)
4. `engine.generate_mar_doses(regimen, encounter, snapshot_dt)` + unit tests (snapshot truncation 含む)
5. `Vancomycin` RxNorm/YJ 追加 (`rxnorm.yaml` + `yj.yaml` + `code_mapping_drug/us.yaml` + `code_mapping_drug/jp.yaml`) — NLM RxNav + MEDIS HOT 照合
6. `enricher.enrich_antibiotic(ctx)` + `ENRICHER_SEED_OFFSETS["antibiotic"] = 0x4142` 登録 + `register_builtin_enrichers` 配線
7. integration tests (forced-scenario + sub-rng + opt-in OFF/ON byte-diff)
8. `modules/antibiotic/audit.py` + AD-60 plug-in test
9. README.md (テンプレ準拠、Consumers セクション)
10. docs sync: MODULES.md (新 module カウント)、SCENARIO_FLAGS.md (該当なし)、TODO.md (Phase 3b-1 完了)、CLAUDE.md (必要なら)、DESIGN.md (AD-55 Module ロードマップ進捗)
11. byte-diff (master vs branch, p=2000) + audit run + post-merge xhigh review (PR-90 教訓)

---

## §6. 既存コード改善提案

`feedback_propose_improvements_to_existing` に従い、本 PR 実装中に発見しうる/既知の改善候補を列挙(本 PR で対処 / 別 PR / TODO のいずれかをユーザー判断):

| # | 改善 | 4 軸評価 | 推奨 |
|---|---|---|---|
| 1 | `_FREQ_PER_DAY` parser を `clinosim/modules/_shared.py` に昇格(antibiotic + 既存 order engine + 将来 PR3b-2/3/4 で再利用) | メンテ性 ◎ / DRY | 本 PR で同時昇格 |
| 2 | `OrderType.MEDICATION` の dose / route / frequency が現状 `Optional[str]`、antibiotic enricher は全フィールド populate するので Validator で `MEDICATION → required` 化を提案 | データ品質 ◎ | 別 PR (validator scope) |
| 3 | HAI organism snomed が `hai_organisms.yaml` で重複している (`other` fallback が同じ snomed を別エントリで持つ) を Phase 3b-2 で antibiogram lookup する前に dedupe | データ品質 ◎ / 臨床整合 ◎ | Phase 3b-2 で対処 (organism-targeted narrow が必要) |

---

## §7. リスクと緩和

| リスク | 緩和 |
|---|---|
| PR-90 同型 silent no-op (canonical string mismatch) | (1) ANTIBIOTIC_DRUGS + HAI_TYPES canonical constants、(2) YAML loader import-time validation、(3) lift_firing_proof for end-to-end enricher path drive、(4) forced-scenario integration test |
| RxNorm/YJ Vancomycin code fabrication | impl 時 NLM RxNav + MEDIS HOT で必須照合、失敗時は impl 停止 |
| IDSA duration の出典明示不足 | YAML に `# Source: IDSA 2009 CLABSI ...` コメント、README に出典記載 |
| always-on でも既存 golden 不変・regression なし | (1) `record.extensions["hai"]` が空のときは早期 return = no-op、(2) e2e golden に impact ある場合は spike で確認後 golden 更新を PR で透明化(Task 7c)、(3) byte-diff scope = master(antibiotic コード不在)vs branch(antibiotic 追加)で MedicationRequest/Administration NDJSON のみ delta、他全 IDENTICAL |
| AD-32 future-onset HAI に対する orphan 抗菌薬 Order | `inpatient.py:464-490` の AD-32 truncation は POST_ENCOUNTER **後**に走るため、antibiotic enricher は内部で `onset_date > snapshot_date` の HAI events を skip(Task 7 step 1 unit test で gate) |
| Phase 3b-2/3/4 が `extensions["antibiotic"]` の shape に依存 → 将来 schema 変更で破損 | `AntibioticRegimen` は dataclass で typed、PR3b-1 時点で `intent` フィールドを含めて将来拡張(`empirical` → `narrowed`)を予約 |
| MAR 大量生成で byte-diff の Observation NDJSON が膨らむ | HAI rare-event なので p=2000 で 20-100 MAR 増加 (許容範囲)。Observation は不変。clinical_acceptance で MAR 数を per-HAI-event verify |

---

## §8. Success Criteria

- [ ] Unit tests 全 pass + integration tests 全 pass (forced-scenario が enricher path を end-to-end drive)
- [ ] `clinosim audit run --module antibiotic` で 4 軸 + lift_firing_proof 全 PASS
- [ ] byte-diff (master vs branch, p=2000, US + JP, opt-in OFF) = 既存 NDJSON 全 byte-IDENTICAL
- [ ] byte-diff (opt-in ON) = `medication_requests.ndjson` + `medication_administrations.ndjson` のみ delta、HAI cohort 期待値で説明可能
- [ ] DQR レポート `docs/reviews/2026-06-25-phase-3b-1-antibiotic-empirical-data-quality-review.md` 作成
- [ ] All docs synced: MODULES.md / TODO.md / DESIGN.md (AD-55 Module ロードマップ) / `modules/antibiotic/README.md` (新)
- [ ] PR body に audit + byte-diff サマリ + doc リンク
- [ ] Vancomycin RxNorm + YJ 認証可能 source で照合済(commit message に source URL)
- [ ] Post-merge xhigh review (PR-90 教訓 = test 緑 + byte-diff PASS でも ship-ready ではない)

---

## Appendix A. データファイルのスケッチ

### `clinosim/modules/antibiotic/reference_data/hai_empirical.yaml`

```yaml
# IDSA guideline-based empirical antibiotic regimens for HAI (PR3b-1).
#
# Sources:
#   CLABSI:  Mermel LA et al. IDSA 2009 Clinical Practice Guidelines for the
#            Diagnosis and Management of Intravascular Catheter-Related Infection.
#            Clin Infect Dis 49(1):1-45.
#   CAUTI:   Hooton TM et al. IDSA 2009 Diagnosis, Prevention, and Treatment of
#            Catheter-Associated Urinary Tract Infection. Clin Infect Dis 50(5):625-63.
#   VAP:     Kalil AC et al. IDSA/ATS 2016 Management of Adults With HAP/VAP.
#            Clin Infect Dis 63(5):e61-e111.

hai_empirical:
  clabsi:
    duration_days: 14
    drugs:
      - drug_key: "Vancomycin"
        dose: "1g"
        route: "IV"
        frequency: "q12h"
      - drug_key: "Piperacillin/Tazobactam"
        dose: "3.375g"
        route: "IV"
        frequency: "q6h"
  cauti:
    duration_days: 7
    drugs:
      - drug_key: "Ceftriaxone"
        dose: "1g"
        route: "IV"
        frequency: "q24h"
  vap:
    duration_days: 7
    drugs:
      - drug_key: "Vancomycin"
        dose: "1g"
        route: "IV"
        frequency: "q12h"
      - drug_key: "Piperacillin/Tazobactam"
        dose: "3.375g"
        route: "IV"
        frequency: "q6h"
```

YAML loader は `set(hai_empirical.keys()) ⊆ HAI_TYPES` と `all(drug.drug_key ∈ ANTIBIOTIC_DRUGS)` を import 時 validate して `ValueError` raise。

---

## Appendix B. 後続 PR3b-2/3/4 が PR3b-1 から consume する surface

| 後続 PR | 読む field | 用途 |
|---|---|---|
| PR3b-2 (S/I/R) | `record.microbiology[i].susceptibilities` (空 list) → populate / `ext["antibiotic"]` の drug_key 集合 → antibiogram 引き当て | empirical で投与中の drug が S かどうかを susceptibility report で評価 |
| PR3b-3 (narrow) | `ext["antibiotic"]` の active regimen / `record.microbiology[i].organism_snomed + susceptibilities` | de-escalation の候補 narrow drug 選定 |
| PR3b-4 (decay) | `ext["antibiotic"][i].start_datetime` | WBC/CRP forward-delta decay の起点日 |

PR3b-1 で `intent: "empirical"` を予約しておけば PR3b-3 で `intent: "narrowed"` regimen を独立に追加できる(stop 日付管理は PR3b-3 で `discontinuation_datetime` フィールド追加で行う、PR3b-1 では不要)。

---

## Appendix C. 自己レビューチェックリスト (この spec 自体)

- [x] Placeholder scan — "TBD"/"TODO" なし(Vancomycin code 照合は impl タスクとして §3.4 / §5 / §8 に explicit)
- [x] Internal consistency — §3.1 (IDSA duration) と §4 (clinical_acceptance expected_duration_days) が完全整合
- [x] Scope check — PR3b-1 単独で実装可能、Phase 3b-2/3/4 は別 spec(§1 で明示)
- [x] Ambiguity check — dose 値 (1g / 3.375g / 1g)、frequency (q12h / q6h / q24h)、duration (14/7/7) が一意に決定
- [x] Authoritative source — IDSA guideline 3 件すべて出典明示、RxNorm/YJ は impl 時必須照合と明記
