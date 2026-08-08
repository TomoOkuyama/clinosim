# PR1 — ServiceRequest for Lab Orders (Panel-aware)

**Date:** 2026-06-29
**Branch:** `feature/pr1-servicerequest-lab`
**Tier 1 #1** — EHR/EMR sample dataset foundation (memory `project_ehr_sample_dataset_roadmap`)

## 0. Purpose

clinosim を **EHR/EMR sample data generator** として再定義した Tier 1 roadmap の First PR。CIF Order を FHIR R4 `ServiceRequest` resource として emit し、lab Observation / DiagnosticReport に `basedOn` linkage を付与する。

EHR/EMR evaluation target(CDSS / NLP / Revenue cycle / EHR migration / Quality reporting)が依存する order lifecycle foundation を確立する。後続全 Tier 1 拡張(Imaging / NutritionOrder / ADT / DocumentReference / Appointment / CarePlan)が ServiceRequest ref を持つため、本 PR の foundation 確立は precondition。

## 1. Scope decisions (6-axis evaluated)

評価軸: データ品質 / 臨床整合性 / FHIR-JP Core 準拠 / メンテナンス性 / モジュール責任分解 / EHR-EMR sample dataset goal (memory `feedback_recommendation_evaluation_axes`)

### 1.1 Module structure: **Order extension + new FHIR builder**(★ not a new functional module)

ServiceRequest = 既存 CIF Order の FHIR 表現。新 module 追加は AD-56 `register_bundle_builder` 拡張ポイントの趣旨に反するため不採用。`MedicationRequest` を `_fhir_medications.py` builder が `OrderType.MEDICATION` から派生させているのと完全同 pattern。

### 1.2 PR slice strategy: **Lab vertical slice**(α)

PR1 = LAB のみ end-to-end(入院 + ED + 外来 lab order 全部)。Procedure / Referral は PR2 / PR3 で別 PR(本 spec の panel-aware pattern を flow するか別 path かは別 spec で判断)。

### 1.3 Panel emission strategy: **Panel-aware grouping**(d)

CBC panel 等を 1 ServiceRequest にまとめ、子 Observation は同 SR を共有。`lab_panel_groups.yaml` を ordering engine 側でも再利用、CIF Order に `panel_key: str = ""` 1 field 追加で実現。実 EHR / JP Core 検査依頼 workflow に integrity 高。

### 1.4 ServiceRequest field choices

| Field | 採択値 | 根拠 |
|---|---|---|
| `id` | panel = `sr-{enc}-{panel_key}-{N}`, stand-alone = `sr-{order_id}` | AD-31 ID uniqueness 担保、prefix で disjoint |
| `identifier.type.coding` | HL7 v2-0203 `PLAC` (Placer Identifier) | JP Core ServiceRequest placerOrderNumber 準拠 |
| `identifier.system` | `urn:clinosim:placer-order-number` | `urn:clinosim:...` 慣習(memory「cross-module canonical URI constants」)|
| `identifier.value` | panel = `{enc}-{panel_key}-{N}`, stand-alone = `{order_id}` | logical placer order number |
| `intent` | `"order"`(hard-coded) | 全 order は definitive、proposal/plan ではない |
| `status` | OrderStatus 集約 rule(下記) | 混在 terminal state を正確に表現 |
| `category` | dual coding: SNOMED `108252007` + HL7 v2-0074 `LAB` | US Core / JP Core 両方 idiomatic、Epic/Cerner 普及度 |
| `priority` | `Order.urgency` 流用 (routine/urgent/stat/asap) | 既存 field、追加なし |
| `code` | LOINC: panel = panel LOINC(58410-2 CBC 等), stand-alone = individual LOINC | `lab_panel_groups.yaml` master 流用 |
| `subject` / `encounter` / `authoredOn` / `requester` | 既存 Order field から resolve | 既存 path |
| `reasonCode.text` | `Order.clinical_intent` 流用 | 既存 field |

### 1.5 Status aggregation rule(panel SR)

```
panel SR.status =
  "active"        if ANY member ∈ {PLACED, ACCEPTED, IN_PROGRESS}
  "revoked"       if ALL members ∈ {CANCELLED, STOPPED}
  "completed"     otherwise (= ALL terminal AND not all-cancelled)
```

stand-alone SR.status = `OrderStatus → SR.status` map(PLACED/ACCEPTED/IN_PROGRESS → active, RESULTED/REVIEWED → completed, CANCELLED/STOPPED → revoked)。

### 1.6 AD-32 snapshot integration

snapshot 時点で:
- 完了: status=`completed`, Observation 出力
- in-progress: status=`active`, Observation 不在(ordered but not resulted)
- cancelled: status=`revoked`, Observation 不在

実 EHR snapshot と整合(変更なし、既存 AD-32 mechanic を flow)。

## 2. Architecture

```
disease.yaml / encounter.yaml: labs: [...]         ← (既存)
  ↓
ordering engine (modules/order/engine.py)           ← (修正) panel-aware grouping
  - lab_panel_groups.yaml 参照
  - 同 panel 内 tests に同 panel_key + 同 ordered_datetime 割当
  - per-encounter panel counter で N 序列
  ↓
CIF: Order[] + Order.panel_key (新 field) + Order.result (既存)
  ↓
FHIR builders:
  - _fhir_service_request.py (新) — Order → ServiceRequest (panel grouping + stand-alone)
  - _fhir_observations.py (修正) — Observation.basedOn = ServiceRequest ref
  - _fhir_diagnostic_report.py (修正) — DiagnosticReport.basedOn = panel SR ref(s)
  - fhir_r4_adapter.py (修正) — register_bundle_builder("ServiceRequest", build_service_requests)
  ↓
NDJSON output: ServiceRequest.ndjson + Observation.ndjson (basedOn 付加) + DiagnosticReport.ndjson (basedOn 付加)
  ↓
audit framework:
  - clinosim/modules/order/audit.py (新) — ModuleAuditSpec + lift_firing_proof (6+ equality_checks)
  - clinosim/audit/axes/clinical.py — basedOn coverage gate
```

### 2.1 責任分解

| Layer | 責務 | 影響行数 |
|---|---|---|
| `clinosim/types/encounter.py:Order` | `panel_key: str = ""` 1 field 追加 | 1 |
| `clinosim/modules/order/engine.py` | panel-aware datetime + panel_key 割当 + panel counter | ~80 |
| `clinosim/modules/output/_fhir_service_request.py`(新) | Order → ServiceRequest emission | ~300 |
| `clinosim/modules/output/_fhir_observations.py` | `basedOn` 追加 | ~20 |
| `clinosim/modules/output/_fhir_diagnostic_report.py` | `basedOn` 追加 | ~20 |
| `clinosim/modules/output/fhir_r4_adapter.py` | `register_bundle_builder` 1 行 | 1 |
| `clinosim/modules/order/audit.py`(新) | `ModuleAuditSpec` + `lift_firing_proof` | ~200 |
| 共通 helper(`_fhir_common.py` or 新 module) | `order_to_sr_id(order)` helper, canonical constants | ~50 |

## 3. Data flow detail

### 3.1 ordering engine の panel-aware 化

`place_admission_orders` / `place_daily_lab_orders` 内で labs リスト展開時:

```python
def expand_labs_with_panel_grouping(lab_specs, panels_yaml, encounter_id, ordered_by,
                                     base_time, rng, panel_counter):
    """labs リストを panel に grouping し、panel members に同じ datetime + panel_key 割当.

    panel_counter: dict[(encounter_id, panel_key), int] — encounter-scoped panel
                   index(同 encounter 内同 panel 複数回発注時の序列)
    """
    # --- Pass 1: panel detection (2-step deterministic algorithm) ---
    # Step A: 各 panel について「lab_specs 中の matching test 数」を count
    panel_match_counts = {}    # {panel_name: [(lab_spec, ...)]}
    for lab_spec in lab_specs:
        test_name = lab_spec["test"]
        for panel_name in PANEL_PRIORITY_ORDER:  # ABG > CBC > BMP > LFT > Lipid > Coag > UA
            if test_name in panels_yaml[panel_name]["components"]:
                panel_match_counts.setdefault(panel_name, []).append(lab_spec)
                break    # priority order で先勝ち = HCO3 は ABG が match なら ABG のみ加算

    # Step B: 各 panel について min_components を満たすかで採否、否ならその panel の matches は stand-alone へ
    panel_groups = {}    # {panel_name: [lab_spec, ...]}
    assigned_specs = set()
    for panel_name, matches in panel_match_counts.items():
        min_components = panels_yaml[panel_name]["min_components"]
        if len(matches) >= min_components:
            panel_groups[panel_name] = matches
            assigned_specs.update(id(s) for s in matches)
    stand_alones = [s for s in lab_specs if id(s) not in assigned_specs]

    # --- Pass 2: Order 生成 ---
    orders = []
    for panel_name in sorted(panel_groups.keys()):    # deterministic
        members = panel_groups[panel_name]
        panel_time = base_time + timedelta(minutes=int(rng.normal(5, 3)))
        panel_counter[(encounter_id, panel_name)] = panel_counter.get(
            (encounter_id, panel_name), 0) + 1
        for i, lab_spec in enumerate(members):
            orders.append(Order(
                order_id=f"ORD-{patient_id}-{phase}-L{seq:02d}",
                panel_key=panel_name,
                ordered_datetime=panel_time,
                # 他 field 既存
            ))

    for lab_spec in stand_alones:
        orders.append(Order(
            panel_key="",
            ordered_datetime=base_time + timedelta(minutes=int(rng.normal(5, 3))),
            # 他 field 既存
        ))

    return orders
```

**HCO3 dual membership の解決(priority order 先勝ち)**:
- ABG components = `[pH, pCO2, pO2, HCO3]`、BMP components = `[Na, K, Cl, HCO3, BUN, Creatinine, Glucose, Ca]`
- HCO3 は priority order ABG > BMP に従い、step A で ABG にのみ加算 = BMP の panel_match_counts には HCO3 は含まれない
- 結果: ABG が min_components 満足なら ABG、ABG 不到達(例 pH のみ)なら HCO3 は ABG group から消える(panel 不成立で stand-alone に降りる)、BMP は HCO3 を欠いた状態で min_components 判定
- これは保守的だが deterministic + 説明可能。代替(HCO3 を「ABG 優先、ABG 不成立なら BMP に fallback」)はやや複雑化、PR2 以降で必要なら拡張

Panel matching priority(`lab_panel_groups.yaml` 既存定義): `ABG > CBC > BMP > LFT > Lipid > Coag > UA`。HCO3 dual membership(ABG ∧ BMP)は priority order で ABG 優先(両 panel が min_components 満足するとき)。

### 3.2 SR id 解決(writer ↔ reader 共有)

```python
# clinosim/modules/output/_fhir_common.py (新)
SR_ID_PREFIX = "sr-"
PLACER_ORDER_NUMBER_SYSTEM = "urn:clinosim:placer-order-number"
LAB_CATEGORY_SNOMED = "108252007"
LAB_CATEGORY_V2_0074 = "LAB"
PANEL_PRIORITY_ORDER = ("ABG", "CBC", "BMP", "LFT", "Lipid", "Coag", "UA")  # lab_panel_groups.yaml header と一致(import-time assert で同期検証)

def order_to_sr_id(order: Order, panel_counter: dict) -> str:
    """Order から ServiceRequest.id を決定的に算出.

    panel_counter は SR builder と Observation/Report builder で共有(同 encounter 内 panel
    instance の序列を一意に決める stateless 計算).
    """
    if order.panel_key:
        idx = panel_counter[(order.encounter_id, order.panel_key, order.ordered_datetime)]
        return f"{SR_ID_PREFIX}{order.encounter_id}-{order.panel_key}-{idx}"
    return f"{SR_ID_PREFIX}{order.order_id}"
```

panel counter は Orders を一度 walk して `(enc, panel_key, datetime)` ごとに序列を計算。これは builder 内 stateless computation(global state なし)。

### 3.3 ServiceRequest resource(panel 例)

```yaml
resourceType: ServiceRequest
id: "sr-enc-pt001-001-CBC-1"
identifier:
  - type:
      coding:
        - system: "http://terminology.hl7.org/CodeSystem/v2-0203"
          code: "PLAC"
          display: "Placer Identifier"
    system: "urn:clinosim:placer-order-number"
    value: "enc-pt001-001-CBC-1"
status: "active"
intent: "order"
category:
  - coding:
      - system: "http://snomed.info/sct"
        code: "108252007"
        display: "Laboratory procedure"        # JP: "臨床検査"
      - system: "http://terminology.hl7.org/CodeSystem/v2-0074"
        code: "LAB"
        display: "Laboratory"
priority: "routine"
code:
  coding:
    - system: "http://loinc.org"
      code: "58410-2"
      display: "Complete blood count (hemogram) panel - Blood by Automated count"
  text: "CBC"
subject:
  reference: "Patient/pt001"
encounter:
  reference: "Encounter/enc-pt001-001"
authoredOn: "2026-06-29T08:05:00+09:00"
requester:
  reference: "Practitioner/staff-doc-001"
reasonCode:
  - text: "Admission workup: CBC"
```

### 3.4 basedOn linkage

```python
# _fhir_observations.py — lab Observation 出力時
sr_id = order_to_sr_id(order, panel_counter)
observation["basedOn"] = [{"reference": f"ServiceRequest/{sr_id}"}]

# _fhir_diagnostic_report.py — panel report 出力時
sr_ids = sorted({order_to_sr_id(o, panel_counter) for o in panel_orders})
report["basedOn"] = [{"reference": f"ServiceRequest/{sid}"} for sid in sr_ids]
```

panel SR が grouping されている場合、panel members 4 Order 全てが同 SR を指す = `sr_ids` 1 entry。

## 4. Edge cases

### 4.1 Panel detection 境界

| ケース | 動作 |
|---|---|
| disease.yaml `labs:` に CBC 4 components 全部 | `panel_key="CBC"`、4 Orders 同 datetime |
| disease.yaml `labs:` に CBC 3 components(min_components=3 満足)| `panel_key="CBC"`、3 Orders 同 datetime |
| disease.yaml `labs:` に CBC 2 components(min_components 不足)| 全 stand-alone(`panel_key=""`)|
| daily monitoring `[CRP, WBC, Cr]`(各 panel ばらけ)| 全 stand-alone |
| HCO3 dual membership(ABG ∧ BMP)| priority order 先勝ち: HCO3 は常に ABG に加算試行 → ABG 不成立なら HCO3 は stand-alone(BMP に fallback しない conservative rule、PR2 拡張余地)|
| 同 encounter 同 panel 複数回(admission CBC + day3 CBC)| panel counter 序列で `sr-{enc}-CBC-1` / `sr-{enc}-CBC-2` |

### 4.2 status 集約 edge cases

| Members status | panel SR.status |
|---|---|
| {RESULTED, RESULTED, RESULTED, RESULTED} | `completed` |
| {RESULTED, RESULTED, RESULTED, CANCELLED} | `completed`(部分 result + 部分 cancel)|
| {CANCELLED, CANCELLED, CANCELLED, CANCELLED} | `revoked` |
| {RESULTED, PLACED, RESULTED, RESULTED} | `active`(non-terminal あり)|
| {IN_PROGRESS, IN_PROGRESS, IN_PROGRESS, IN_PROGRESS} | `active` |

### 4.3 silent-no-op 防御 4 層(memory `feedback_xhigh_review_lessons` PR-90 教訓)

| Layer | 防御 |
|---|---|
| 1. canonical constants | `SR_ID_PREFIX` / `PLACER_ORDER_NUMBER_SYSTEM` / `LAB_CATEGORY_SNOMED` / `LAB_CATEGORY_V2_0074` を `_fhir_common.py` module-level 定義 |
| 2. shared id-prefix writer↔reader | `_fhir_service_request.py`(writer)= `_fhir_observations.py`(reader)で同 `order_to_sr_id()` helper を共有 |
| 3. import-time YAML validation | `find_panel_for_test()` が panel name → LOINC code を resolve、resolve 失敗時 `ValueError`(silent fallback 禁止)|
| 4. audit framework gate | `clinosim/audit/axes/clinical.py` で「全 LAB Observation に basedOn 存在 ∧ ref ServiceRequest が NDJSON に存在」を verify、`n<30 WARN` 受容 |

### 4.4 Other edge cases

- **`ordered_by` 空**: `requester` field 出力 skip(FHIR Optional)
- **HAI culture(MicrobiologyResult)**: PR1 範囲外、SR 未出力(Tier 2 で対応)
- **OrderType.IMAGING**: PR1 範囲外、Tier 1 #2 で対応(builder を polymorphic category 設計、IMAGING も同 builder で対応予定)
- **OrderType.MEDICATION**: FHIR `MedicationRequest`(既存)= SR 不要
- **LOINC display ja 不在**: lookup fallback to en + audit で不足 list 出力 → PR1 内補完

## 5. Testing strategy

### 5.1 Unit tests(`pytest -m unit`、<30s)

| ファイル | 内容 |
|---|---|
| `tests/unit/modules/order/test_panel_grouping.py`(新) | panel detection 全境界 |
| `tests/unit/output/test_fhir_service_request.py`(新) | resource 構造、id naming、identifier PLAC、category dual coding、status 集約 8 cases、locale display |
| `tests/unit/output/test_fhir_observations_basedon.py`(既存拡張)| Observation.basedOn 存在 + panel/stand-alone 各 case |
| `tests/unit/audit/test_order_audit.py`(新) | `lift_firing_proof` 6+ equality_checks fire 確認 + stub-proof self-check |

### 5.2 Integration tests(`pytest -m integration`、<5min)

| ファイル | 内容 |
|---|---|
| `tests/integration/test_servicerequest_chain.py`(新) | US + JP cohort で ServiceRequest.ndjson 非空、JP display 存在 |
| `tests/integration/test_servicerequest_basedon_coverage.py`(新)★ silent-no-op gate | 全 LAB Observation basedOn 存在 + 全 ref resolve + panel SR 共有 |
| `tests/integration/test_servicerequest_determinism.py`(新) | seed 固定で 2 回実行、ServiceRequest.ndjson sha256 一致(AD-16)|
| `tests/integration/test_servicerequest_snapshot.py`(新) | snapshot mid-day 未完 Order の SR.status="active" + Observation 不在 |
| `tests/integration/test_individual_lab_isolation.py`(既存) | regression: panel-aware datetime 変更が他 cohort shift しないか |

### 5.3 E2E golden

既存 golden は ServiceRequest.ndjson 追加 + Observation/DiagnosticReport.ndjson の `basedOn` 追加で **更新必須**。PR1 で新 golden 生成・コミット(byte-diff regression は意図的)。

### 5.4 audit framework(★ primary gate)

`clinosim/modules/order/audit.py` に `ModuleAuditSpec`:

```python
ModuleAuditSpec(
    name="order_service_request",
    structural_checks=[...],     # SR/identifier/basedOn 構造
    clinical_acceptance={
        "panel_sr_share_rate": ">= 0.5 if cohort contains CBC/BMP/LFT orders",
        "basedon_coverage": "all LAB Observations have basedOn (n<30 WARN)",
    },
    jp_language_checks=[...],    # JP cohort で ja display
    lift_firing_proof={
        "equality_checks": [
            # 7 canonical-constant proofs
            "PLACER_ORDER_NUMBER_SYSTEM == 'urn:clinosim:placer-order-number'",
            "SNOMED 108252007 'Laboratory procedure' present in category[0].coding",
            "v2-0074 'LAB' present in category[0].coding",
            "ServiceRequest count > 0 when lab Order count > 0",
            "panel SR count > 0 when panel_key non-empty Orders exist",
            "every basedOn ref resolves in NDJSON",
            "SR id schemes are disjoint (sr-{enc}-... ∩ sr-ORD-... = ∅)",
        ],
    },
)
```

### 5.5 DQR(production cohort、PR/Merge 前必須)

```
clinosim run-beta --country US --population 10000 --seed 42 --output scratchpad/pr1_us10k/
clinosim run-beta --country JP --population 5000  --seed 42 --output scratchpad/pr1_jp5k/
clinosim audit run scratchpad/pr1_us10k/ --module order_service_request
clinosim audit run scratchpad/pr1_jp5k/  --module order_service_request
```

DQR doc: `docs/reviews/2026-06-29-pr1-servicerequest-lab-dqr.md`、4 軸評価:
- 構造: NDJSON 整合 + reference 解決 + identifier PLAC 完備
- 臨床整合: panel grouping rate / status 集約 distribution / basedOn coverage 100%(or n<30 WARN)
- JP language: JP cohort 全 SR に ja display(`loinc_display_ja.yaml` 不足分 PR1 内補完済)
- EHR/EMR goal: panel order count / unique panel types / lab LOINC code coverage(interop 価値定量)

### 5.6 Determinism note(AD-16)

ordering engine panel-aware 化で `rng.normal(5, 3)` の draw 数が変化(全 lab test × 1 → panel ごと 1 + stand-alone × 1)。既存 e2e golden は **意図的 reseed**、PR1 base として新 golden 確立。physiology / vitals / disease state は無影響(別 sub-rng path)。

### 5.7 Pre-merge gate(★ memory「Pre-merge gate」セッション22 教訓)

`pytest tests/unit tests/integration -m "unit or integration"` の **full sweep** を pre-merge で必ず実行(feature-specific test files のみは不十分、unrelated monkeypatch fixture が新 validator に hit する古典盲点)。

## 6. Out-of-scope(★ TODO.md formal entry 必須)

| 項目 | 後続予定 | 理由 |
|---|---|---|
| ServiceRequest for PROCEDURE | PR2(ServiceRequest chain 第 2 段)| 別 path(`_fhir_procedures.py` + `ProcedureRecord`)|
| ServiceRequest for REFERRAL/CONSULTATION | PR3(ServiceRequest chain 第 3 段)| 新規データ生成必要(disease YAML 拡張)|
| ServiceRequest for IMAGING | Tier 1 #2 Imaging chain | Imaging metadata 全体設計と一緒に対応 |
| ServiceRequest for MEDICATION | 不要 | FHIR `MedicationRequest` 既存 |
| ServiceRequest for HAI microbiology culture | Tier 2 microbiology ordering | `MicrobiologyResult` 別 type |
| `ServiceRequest.requisition` Identifier | Tier 1 #6 Appointment + 検査依頼 batch | 単一 panel = SR 1 件で表現可能 |
| Lab requisition workflow narrative | Tier 1 #5 DocumentReference Stage 2 | 別 chain |
| `ServiceRequest.performer`(検査実施技師)| Tier 2 CareTeam | 検査実施部署 = 別 concept |
| Filler order number `FILL` identifier | Tier 2 lab interface specifics | placer 単独で PR1 範囲十分 |

## 7. Risks & Mitigation

| Risk | 影響 | Mitigation |
|---|---|---|
| Determinism break(rng draw 数変化)| 全 lab Order の ordered_datetime 変化、e2e golden 更新 | PR1 で golden 再生成、PR1 base 起点 reseed として記録 |
| LOINC ja translation 不在 | JP cohort で en 残存 | PR1 内で DQR audit、不足分補完 |
| Panel detection bug(HCO3 dual)| wrong panel assignment | unit tests 全境界条件 cover、priority 定数化 |
| Performance(p=10k で resources ~1.5x)| NDJSON size 増加 | DQR で実測、acceptable scale |
| panel counter race(dict ordering)| 同 panel 複数回の id 順序 unstable | sorted iteration + insertion-order-stable、unit test 検証 |
| silent-no-op fail | 全 basedOn 空のまま emit | `lift_firing_proof` 7 equality_checks + audit pre-merge gate |
| 既存 test monkeypatch 干渉 | pre-merge 見逃し | full test sweep を pre-merge で必ず実行 |

## 8. Adversarial chain plan

7 例の安定 pattern(PR-A / PR #102 / PR-B1 / PR3b-3-original / PR3b-3-D1+D2 / PR3b-5 / sibling sweep)に従う:

| 段階 | 内容 | converged 判定 |
|---|---|---|
| PR1-original | vertical slice 完成 | audit + full test + DQR 4 軸 PASS |
| adversarial-1 | 6 軸 + silent-no-op + AD-16 で fan-out review | findings 列挙、修正 PR |
| PR1-adv-1 | adversarial-1 findings fix | audit + full test PASS |
| adversarial-2 | adv-1 fix に同 6 軸 fan-out review(教訓自己適用)| 次段 findings 列挙 |
| PR1-adv-2 | adversarial-2 findings fix(必要なら) | audit + full test PASS |
| **converged** | Critical/Important 0 + finding converging + 残 cosmetic only + 次段 expected size tiny | chain CLOSED + memory precedent 記録 |

通常 2-4 段で converged。

## 9. PR sequencing

```
PR1: ServiceRequest for LAB(本 spec)
  ├─ PR1-adv-1: adversarial fix #1
  └─ PR1-adv-2: adversarial fix #2(or chain closed)
PR2: ServiceRequest for PROCEDURE(別 spec 必要)
  └─ adversarial fan-out
PR3: ServiceRequest for REFERRAL(別 spec 必要、新規データ生成含む)
  └─ adversarial fan-out
```

## 10. Docs sync(PR1 内で全更新、memory `feedback_pr_merge_dqr_required`)

- `README.md` / `README.ja.md`: ServiceRequest 言及追加
- `MODULES.md`: order module 責務追記(panel-aware ordering)
- `DESIGN.md`: 新 ADR `AD-61: Lab ServiceRequest emission, panel-aware grouping`(現在の最新 = AD-60)
- `docs/CONTRIBUTING-modules.md`: `register_bundle_builder` で ServiceRequest 例追加
- `clinosim/modules/order/README.md`: `panel_key` field semantic 追記
- `TODO.md`: out-of-scope 9 項目を formal entry 化
- `CLAUDE.md`: panel-aware ordering DRY rule 追加(`scenario_flags` / `medication_flags` sibling = `panel_grouping_helper`)

## 11. References

- memory: `project_ehr_sample_dataset_roadmap`(Tier 1 roadmap)
- memory: `feedback_recommendation_evaluation_axes`(6 軸評価)
- memory: `feedback_xhigh_review_lessons`(silent-no-op 防御 PR-90 教訓)
- memory: `feedback_iterative_adversarial_review`(adversarial chain pattern)
- memory: `feedback_pr_merge_dqr_required`(PR/Merge 前 DQR)
- 既存 precedent: `_fhir_medications.py`(MedicationRequest emission pattern)
- 既存 precedent: `_fhir_diagnostic_report.py`(panel grouping logic)
- 既存 yaml: `clinosim/modules/output/reference_data/lab_panel_groups.yaml`(panel definitions)
- FHIR R4: ServiceRequest resource(https://hl7.org/fhir/R4/servicerequest.html)
- US Core: ServiceRequest Profile
- JP Core: ServiceRequest Profile(placerOrderNumber via v2-0203 PLAC)
