# Tier 1 #2 — Imaging metadata-only chain(α-min)

**Date:** 2026-06-30
**Branch:** `feature/tier1-imaging-chain`
**Tier 1 #2** — EHR/EMR sample dataset 拡張(memory `project_ehr_sample_dataset_roadmap`)
**Precedent base:** PR1 ServiceRequest for Lab Orders(`docs/superpowers/specs/2026-06-29-pr1-servicerequest-lab-design.md`, AD-61)

## 0. Purpose

clinosim を **EHR/EMR sample data generator** として再定義した Tier 1 roadmap の第 2 拡張。CIF Order(OrderType.IMAGING)を起点に FHIR R4 の 4 resource(`ServiceRequest` + `ImagingStudy` + `DiagnosticReport`(radiology variant)+ `Endpoint`)を emit する **imaging metadata-only chain** を確立する。

clinosim は本 PR でも **text data + metadata + WADO-RS placeholder のみ生成**、DICOM pixel data 生成は外部画像生成 AI(後付け)に委譲。`Endpoint.address` を実 PACS / DICOMweb サーバに差し替え可能な statement-of-record interface を保持する。

EHR/EMR evaluation target — radiology NLP / IE、CDSS(imaging order workflow)、revenue cycle(imaging CPT / JP K-code billing)、imaging vendor migration、quality reporting(turnaround time / critical findings notification)— が依存する imaging metadata foundation を確立する。後続 Tier 1 拡張(Appointment / CarePlan)も ServiceRequest(imaging) を ref する点で本 chain が precondition。

## 1. Scope decisions(6 軸評価)

評価軸:データ品質 / 臨床整合性 / FHIR-JP Core 準拠 / メンテナンス性 / モジュール責任分解 / EHR-EMR sample dataset goal(memory `feedback_recommendation_evaluation_axes`)

### 1.1 Vertical slice 境界: **Disease 限定 slice**(初回 PR = 2 disease)

PR1 LAB の「全 disease × 全 panel 一括」とは異なり、imaging は modality と clinical indication が密結合 = disease 単位の slice が自然。初回 PR = **pneumonia(bacterial + aspiration)+ hemorrhagic stroke の 2 disease**、modality = **CR(平面 X-ray)+ CT** 限定。後続 PR で disease + modality 同時 sweep。

### 1.2 Architecture: **Approach A — Module + `extensions["imaging"]`**(always-on near-essential cascade)

| 軸 | A (Module + ext) | B (Base + field) | C (OrderResult variant) |
|---|---|---|---|
| データ品質 | ◎ | ◎ | ○ (scalar vs payload mismatch) |
| 臨床整合 | ◎ (order→study→report flow 一致) | ◎ | ○ |
| FHIR / JP Core | ◎ (ImagingStudy + DR + SR + Endpoint clean) | ◎ | △ (SR↔Study link gnarly) |
| メンテ性 | ◎ (extensions slot、self-contained) | ○ (CIF field 増、ripple) | △ (OrderResult schema 拡大) |
| モジュール責任 | ◎ (near-essential Module precedent) | ○ (Base 設計増) | △ (LAB / imaging 境界曖昧) |
| EHR/EMR goal | ◎ (imaging full unlock) | ◎ | ○ |
| **総合** | **6◎ ★** | 4◎+2○ | 2◎+2○+2△ |

**Approach A 採用根拠**:
1. AD-55 PR3b-1 supplement「always-on Module = near-essential clinical cascade」pattern と完全整合(device → hai → antibiotic で 3 例実証済、imaging が 4 例目)
2. `extensions["imaging"]` slot で `CIFPatientRecord` を変更しない = ripple ゼロ
3. PR1 ServiceRequest polymorphic builder を流用(`_fhir_service_request.py` の `OrderType.LAB` 条件を polymorphic category 拡張 = imaging も同 builder 経由)
4. Order と Study が分離 = AD-32 snapshot semantics 整合(SR=active + ImagingStudy 不在)

### 1.3 Design dimension defaults

| Dim | Choice | 採択 | 根拠 |
|---|---|---|---|
| D1 Report content depth | structured findings + impression template | ★ | Tier 1 #5 LLM 統合への入口、deterministic、disease YAML 駆動 |
| D2 Endpoint URL 形式 | `hospital_config.imaging.wado_base_url` 駆動 | ★ | 後付け実 PACS への切替点 clear、JP/US で異なる base URL 設定可 |
| D3 SR builder 拡張方針 | `_fhir_service_request.py` polymorphic category 拡張 | ★ | PR1 で確立した skeleton 流用、shared writer↔reader constant pattern |

### 1.4 Module structure: **新 module `clinosim/modules/imaging/` + 既存 builder 拡張**

```
clinosim/types/imaging.py                                       ← 新
  ImagingStudyRecord (dataclass)
  ImagingSeries (dataclass)
  RadiologyReport (dataclass)

clinosim/modules/imaging/                                        ← 新 always-on Module
  ├── __init__.py            — exports
  ├── engine.py              — POST_ENCOUNTER enricher entry + study generation
  ├── audit.py               — ModuleAuditSpec + lift_firing_proof(10 equality_checks)
  ├── README.md
  └── reference_data/
      ├── modalities.yaml          — CR + CT (PR1 scope)
      ├── body_sites.yaml          — chest + head SNOMED + LOINC + CPT + JP-K
      └── impression_templates.yaml — pneumonia + stroke × normal/abnormal

clinosim/modules/output/                                         ← 拡張
  ├── _fhir_service_request.py     — polymorphic LAB / IMAGING dispatch
  ├── _fhir_imaging_study.py       ← 新
  ├── _fhir_diagnostic_report.py   — radiology variant 拡張
  └── _fhir_endpoint.py            ← 新

clinosim/modules/order/engine.py                                 ← 拡張
  disease.yaml.imaging_orders[] → Order(OrderType.IMAGING)

clinosim/modules/disease/reference_data/                         ← imaging_orders[] 追加
  ├── bacterial_pneumonia.yaml
  ├── aspiration_pneumonia.yaml
  └── hemorrhagic_stroke.yaml

clinosim/simulator/seeding.py                                    ← 拡張
  ENRICHER_SEED_OFFSETS["imaging"] = 0x494D  ("IM")
```

責任分解:
- `types/imaging.py` = CIF schema(builder から read-only)
- `modules/imaging/engine.py` = Order(IMAGING)→ ImagingStudyRecord 生成 enricher
- `modules/order/engine.py` = disease YAML imaging_orders[] → CIF Order(IMAGING) emission(既存 LAB と並列)
- `modules/output/_fhir_*` = CIF → FHIR R4 resource
- `modules/imaging/audit.py` = AD-60 plug-in

## 2. Architecture

### 2.1 全体 data flow

```
[Pass 1: ordering engine] (modules/order/engine.py 拡張)
  disease.yaml.imaging_orders[].{modality, body_site, views, urgency, day, clinical_indication}
    ↓ ordering engine reads imaging_orders[] (parallel to existing labs:)
  per entry → Order(
      order_type=OrderType.IMAGING,
      order_code = <procedure code resolved from modality + body_site>,
      display_name = <localized procedure name>,
      clinical_intent = <indication text>,
      urgency = <urgency>,
      imaging_modality = <CR/CT>,
      imaging_body_site_code = <SNOMED>,
      imaging_views = [view1, view2, ...],
  )
    ↓
  CIF: record.orders[] 内に OrderType.IMAGING entries

[Pass 2: imaging enricher] (POST_ENCOUNTER order=90, after device=70 / hai=80 / antibiotic=85)
  for order in record.orders where order_type == IMAGING and status != CANCELLED:
    sub_seed = derive_sub_seed(master, ENRICHER_SEED_OFFSETS["imaging"], order.order_id)
    rng = numpy.random.Generator(...sub_seed)

    study_uid = deterministic_uid_from(sub_seed)
    series = []
    for i, view in enumerate(order.imaging_views or default_views_for(modality, body_site)):
      instance_count = rng.integers(*modality_yaml[modality].typical_instances_per_series_range)
      series.append(ImagingSeries(series_uid=..., instance_count=instance_count, ...))

    is_abnormal = rng.random() < disease_yaml.imaging_abnormal_rate(severity)
    template = impression_templates_yaml[disease_id][modality][normal/abnormal]
    report = RadiologyReport(findings_text=..., impression_text=...)

    record.extensions["imaging"].append(ImagingStudyRecord(
      study_id, study_instance_uid, order_id, series, report,
      endpoint_id=f"endpoint-{study_uid}", ...
    ))

[Pass 3: FHIR builders]
  _fhir_service_request   → ServiceRequest(category=imaging, code=procedure)
  _fhir_imaging_study     → ImagingStudy(StudyInstanceUID, series, endpoint ref, basedOn SR)
  _fhir_diagnostic_report → DiagnosticReport(category=radiology, basedOn SR, imagingStudy ref, conclusion)
  _fhir_endpoint          → Endpoint(WADO-RS URL placeholder, connectionType=dicom-wado-rs)
```

### 2.2 builder 登録順(reference 解決順、`fhir_r4_adapter.py`)

```
Patient → Encounter → Practitioner → ServiceRequest →
  Endpoint → ImagingStudy(basedOn SR + endpoint ref) →
  DiagnosticReport(basedOn SR + imagingStudy ref + radiology variant) → ...
```

### 2.3 責任分解 + 影響行数

| Layer | 責務 | 影響行数 |
|---|---|---|
| `clinosim/types/encounter.py:Order` | `imaging_modality` + `imaging_body_site_code` + `imaging_views` 3 field 追加 | 3 |
| `clinosim/types/imaging.py`(新) | `ImagingStudyRecord` + `ImagingSeries` + `RadiologyReport` dataclass | ~80 |
| `clinosim/modules/order/engine.py` | imaging_orders[] → Order(IMAGING) emission(既存 LAB と並列 path) | ~120 |
| `clinosim/modules/imaging/engine.py`(新) | enricher + study UID + series 展開 + report template 解決 | ~250 |
| `clinosim/modules/imaging/reference_data/*.yaml`(新) | 3 YAML + 3 validators | ~300 + ~200 |
| `clinosim/modules/output/_fhir_service_request.py` | LAB / IMAGING polymorphic dispatch + 共通 skeleton(`category_codings` / `code_coding` 引数化) | ~120 |
| `clinosim/modules/output/_fhir_imaging_study.py`(新) | Study + Series resource emission | ~200 |
| `clinosim/modules/output/_fhir_diagnostic_report.py` | radiology variant 拡張(`_build_radiology_dr`) | ~80 |
| `clinosim/modules/output/_fhir_endpoint.py`(新) | Endpoint resource + WADO-RS connectionType | ~80 |
| `clinosim/simulator/seeding.py` | `ENRICHER_SEED_OFFSETS["imaging"] = 0x494D` | 1 |
| `clinosim/modules/imaging/audit.py`(新) | `ModuleAuditSpec` + `lift_firing_proof`(10 equality_checks) | ~280 |
| `clinosim/config/hospital_*.yaml` | `imaging.wado_base_url` field 追加(3 hospital config) | 3 |
| `clinosim/modules/disease/reference_data/*.yaml`(3 disease) | `imaging_orders:[]` field 追加 + Pydantic schema 拡張 | ~40 + 10 |

## 3. Data structures

### 3.1 CIF data type(`clinosim/types/imaging.py`)

```python
@dataclass
class ImagingSeries:
    series_uid: str = ""                # DICOM Series UID(後付け実 PACS 統合点)
    series_number: int = 1
    modality_code: str = ""             # DCM modality(CR/CT/MR/US/NM)
    body_site_snomed: str = ""
    body_site_display: str = ""         # locale 解決前(en/ja 共通 key)
    description: str = ""               # "PA view" / "axial 5mm" 等
    instance_count: int = 0             # DICOM instance 数(placeholder、後付け統合先)


@dataclass
class RadiologyReport:
    report_id: str = ""                 # "imgrpt-{enc}-{n}"
    status: str = "final"               # FHIR registered/preliminary/final/amended
    findings_text: str = ""             # 構造化 findings narrative(disease + modality 駆動 template)
    impression_text: str = ""           # clinical impression / conclusion
    findings_codes: list[str] = field(default_factory=list)  # 任意 SNOMED finding codes(将来拡張)


@dataclass
class ImagingStudyRecord:
    study_id: str = ""                  # "imgst-{enc}-{n}"
    study_instance_uid: str = ""        # DICOM Study UID(後付け実 PACS lookup key)
    encounter_id: str = ""
    patient_id: str = ""
    order_id: str = ""                  # source Order.order_id(basedOn 解決)

    status: str = "available"           # FHIR ImagingStudy.status
    started_datetime: datetime | None = None

    modality_code: str = ""             # DCM modality
    body_site_snomed: str = ""
    series: list[ImagingSeries] = field(default_factory=list)

    endpoint_id: str = ""               # back-ref to Endpoint.id(1 study : 1 Endpoint)

    report: RadiologyReport | None = None  # snapshot mid-study = None
```

CIF storage: `record.extensions["imaging"]: list[ImagingStudyRecord]`(AD-55 Module pattern、device / hai / antibiotic precedent)。

### 3.2 Order 拡張(`clinosim/types/encounter.py`)

既存 Order に 3 field 追加(medication 用 `dose_quantity` / `dose_unit` 等の precedent と同):

```python
@dataclass
class Order:
    # 既存 field ...
    panel_key: str = ""                       # PR1 LAB panel grouping
    # PR2(本 PR)imaging 拡張
    imaging_modality: str = ""                # DCM code(CR/CT/MR/US/NM/...)
    imaging_body_site_code: str = ""          # SNOMED body structure
    imaging_views: list[str] = field(default_factory=list)  # ["PA", "Lateral"] 等
```

### 3.3 Multi-series grouping(panel-equivalent for imaging)

LAB の panel-aware grouping(1 SR + 4 Observation)に対し、imaging は **1 SR + 1 ImagingStudy + N series + N×instance_count instances** という階層が異なる:

- pneumonia CXR PA + Lateral = 1 Order(views=[PA, Lateral])= 1 SR + 1 Study(2 series, 各 1 instance)
- stroke CT head non-contrast = 1 Order = 1 SR + 1 Study(1 series, ~250 axial instances)
- 同一 study 内の multi-series は enricher が `imaging_views` から expand
- `Order.panel_key` は LAB only、imaging は `Order.imaging_views` で series 展開(異なる mechanism)

## 4. Reference data + disease YAML

### 4.1 `modalities.yaml`(PR1 scope = CR + CT)

```yaml
modalities:
  CR:                                      # Computed Radiography(平面 X-ray)
    dicom_code: "CR"
    display_en: "Plain X-ray"
    display_ja: "単純X線撮影"
    typical_instances_per_view_range: [1, 1]   # 1 view = 1 instance
    default_views_by_body_site:
      chest: ["PA", "Lateral"]
  CT:                                      # Computed Tomography
    dicom_code: "CT"
    display_en: "Computed Tomography"
    display_ja: "コンピュータ断層撮影"
    typical_instances_per_series_range:
      head: [180, 280]                     # axial 5mm = ~200 slices
      chest: [220, 340]                    # axial 1mm = ~280 slices
    default_views_by_body_site:
      head: ["axial"]
      chest: ["axial"]
```

`_validate_modalities()` で:
- empty top + per-modality bucket guards(Layer 3)
- DCM modality canonical set vs YAML keys(Layer 4 reverse-coverage)
- typical_instances_per_series_range が `[low, high]` 形式 + low <= high(Layer 5 range check)

### 4.2 `body_sites.yaml`

```yaml
body_sites:
  chest:
    snomed: "51185008"
    display_en: "Thoracic structure"
    display_ja: "胸部"
    procedure_codes:
      CR_PA_Lateral:
        loinc: "36572-6"
        cpt: "71046"
        jp_k_code: "E001"
        display_en: "Chest X-ray PA and Lateral"
        display_ja: "胸部単純X線撮影 正面・側面"
      CT_non_contrast:
        loinc: "30794-3"
        cpt: "71250"
        jp_k_code: "E200"
        display_en: "CT Chest without contrast"
        display_ja: "胸部CT 単純"
  head:
    snomed: "69536005"
    display_en: "Head structure"
    display_ja: "頭部"
    procedure_codes:
      CT_non_contrast:
        loinc: "30799-1"
        cpt: "70450"
        jp_k_code: "E200"
        display_en: "CT Head without contrast"
        display_ja: "頭部CT 単純"
```

Code 権威照合(memory `reference_jlac10_source` + `reference_tx_fhir_terminology`):
- LOINC = NLM clinicaltables.nlm.nih.gov + JCCLS-JSLM v137
- CPT = AMA 公式
- JP K-code = MHLW 診療報酬告示 + jpfhir.jp profile
- SNOMED = tx.fhir.org `$lookup`
- 不確実は `# TODO: verify` 残し

### 4.3 `impression_templates.yaml`

```yaml
templates:
  bacterial_pneumonia:
    CR_chest:
      normal:
        findings_en: "Lungs are clear bilaterally. No focal consolidation."
        findings_ja: "両肺野にconsolidationを認めず、明らかな異常所見なし。"
        impression_en: "No acute cardiopulmonary process."
        impression_ja: "急性心肺疾患を示唆する所見なし。"
      abnormal:
        findings_en: "Focal opacity in the {lobe} consistent with consolidation."
        findings_ja: "{lobe_ja}に浸潤影を認める。"
        impression_en: "Findings consistent with pneumonia."
        impression_ja: "肺炎像。"
    CT_chest:
      normal: ...
      abnormal: ...
  aspiration_pneumonia:
    CR_chest: ...
    CT_chest: ...
  hemorrhagic_stroke:
    CT_head:
      abnormal:
        findings_en: "Acute parenchymal hemorrhage in the {region}."
        findings_ja: "{region_ja}に急性期出血を認める。"
        impression_en: "Acute intracerebral hemorrhage."
        impression_ja: "急性脳出血。"
```

template variables(`{lobe}` / `{region}` 等)= disease severity + RNG 駆動の deterministic 解決。Tier 1 #5 LLM 統合点(template を LLM prompt seed として使用)。

`_validate_impression_templates()` で:
- empty top + per-disease + per-modality bucket guards(Layer 3)
- disease_id × modality forward-coverage:disease YAML imaging_orders[] と impression_templates の cross-match(Layer 6 symmetric)
- normal / abnormal sub-key 必須

### 4.4 disease YAML `imaging_orders[]` schema 拡張

```yaml
# clinosim/modules/disease/reference_data/bacterial_pneumonia.yaml
imaging_orders:
  - modality: CR
    body_site: chest
    views: [PA, Lateral]
    urgency: routine
    clinical_indication: "Suspected pneumonia, evaluate consolidation"
    day: 0
    abnormal_rate_by_severity:
      mild: 0.85
      moderate: 0.95
      severe: 1.0
  - modality: CT
    body_site: chest
    contrast: false
    urgency: routine
    clinical_indication: "Confirm extent of consolidation"
    day: 1
    only_if_severity: [moderate, severe]
    abnormal_rate_by_severity:
      moderate: 0.9
      severe: 1.0
```

```yaml
# clinosim/modules/disease/reference_data/hemorrhagic_stroke.yaml
imaging_orders:
  - modality: CT
    body_site: head
    contrast: false
    urgency: stat
    clinical_indication: "Suspected intracranial hemorrhage"
    day: 0
    abnormal_rate_by_severity:
      any: 1.0          # `any:` = severity-agnostic catch-all (severity field 不在 / 全 severity で同 rate 適用); 他 severity key と共存不可 — exclusive
```

Pydantic validation:`DiseaseProtocol` に `imaging_orders: list[ImagingOrderSpec] = []`(optional default、既存 28 disease no-op safe)。

### 4.5 hospital_config Endpoint URL 駆動

```yaml
# clinosim/config/hospital_operations.yaml(default)
imaging:
  wado_base_url: "https://wado.clinosim.example/dicomweb"
# hospital_large.yaml / hospital_small.yaml も同 field 追加
```

```python
# clinosim/modules/output/_fhir_endpoint.py
def _resolve_wado_base_url(hospital_config: dict) -> str:
    imaging_cfg = hospital_config.get("imaging") or {}
    return imaging_cfg.get("wado_base_url") or "https://wado.clinosim.example/dicomweb"
```

未設定 hospital_config は default placeholder = no-op safe。

## 5. FHIR builder layer

### 5.1 `_fhir_service_request.py` polymorphic 拡張

```python
# === Canonical constants(既存 LAB 保持 + 新 IMAGING 追加)===
LAB_CATEGORY_SNOMED = "108252007"           # 既存
LAB_CATEGORY_V2_0074 = "LAB"                # 既存
IMAGING_CATEGORY_SNOMED = "363679005"       # 新 SNOMED "Imaging" (Procedure category)
IMAGING_CATEGORY_V2_0074 = "RAD"            # 新 HL7 v2-0074 "Radiology"

def _bb_service_requests(ctx: BundleContext) -> list[dict]:
    orders = ctx.record.get("orders", []) or []
    resources: list[dict] = []

    lab_orders = [o for o in orders if _o(o, "order_type") in (OrderType.LAB, "lab")]
    if lab_orders:
        resources.extend(_build_lab_service_requests(lab_orders, ctx))   # 既存 path

    imaging_orders = [o for o in orders if _o(o, "order_type") in (OrderType.IMAGING, "imaging")]
    if imaging_orders:
        resources.extend(_build_imaging_service_requests(imaging_orders, ctx))  # 新 path

    return resources
```

`_build_sr_skeleton` を `category_codings: list[dict]` + `code_coding: dict` + `body_site_coding: dict | None` 引数化、LAB / IMAGING 両 path 経由。silent-no-op defense Layer 2(shared writer↔reader constants)integrity 保持。

### 5.2 `_fhir_imaging_study.py`(新)

```python
IMAGING_STUDY_ID_PREFIX = "imgst-"
DICOM_UID_SYSTEM = "urn:dicom:uid"          # FHIR-spec 既知 system URI
ENDPOINT_ID_PREFIX = "endpoint-"

def _bb_imaging_studies(ctx: BundleContext) -> list[dict]:
    studies = ctx.record.get("extensions", {}).get("imaging") or []
    if not studies:
        return []
    return [_build_imaging_study(s, ctx) for s in studies]
```

Resource shape(主 field):
- `resourceType: "ImagingStudy"`
- `id: "imgst-{study_id}"`
- `identifier: [{system: DICOM_UID_SYSTEM, value: "urn:oid:{study_instance_uid}"}]`
- `status` / `modality[]` / `subject` / `encounter` / `started`
- `basedOn: [{reference: "ServiceRequest/sr-{order_id}"}]`(★ ref integrity)
- `endpoint: [{reference: "Endpoint/{endpoint_id}"}]`
- `numberOfSeries: len(series)`、`numberOfInstances: sum(series[].instance_count)`
- `series[]` with uid / number / modality / numberOfInstances / description / bodySite

### 5.3 `_fhir_diagnostic_report.py` radiology variant 拡張

```python
RADIOLOGY_DR_ID_PREFIX = "imgrpt-"
RADIOLOGY_CATEGORY_SNOMED = "394914008"     # "Radiology"
RADIOLOGY_CATEGORY_V2_0074 = "RAD"
```

既存 `_bb_diagnostic_reports` に LAB panel DR + Radiology DR の dispatch を追加:
- LAB panel DR: 既存 path
- Radiology DR: 各 ImagingStudy の `report` field から生成、category dual coding(SNOMED 394914008 + v2-0074 RAD)、`basedOn: ServiceRequest`、`imagingStudy: ImagingStudy`、`conclusion: impression_text`

### 5.4 `_fhir_endpoint.py`(新)

```python
ENDPOINT_ID_PREFIX = "endpoint-"
DICOM_WADO_RS_CONNECTION_TYPE = "dicom-wado-rs"
```

1 study : 1 Endpoint invariant。`payloadType: "any"` / `payloadMimeType: ["application/dicom"]` / `address: {base_url}/studies/{study_uid}`。後付け実 PACS 統合時に `Endpoint.address` を実 URL に差し替える単一 entry point。

## 6. Snapshot semantics(AD-32)

| 状況 | SR.status | ImagingStudy | DR(radiology) |
|---|---|---|---|
| ordered + study performed + report final | `completed` | `available` | `final` |
| ordered + study performed + report pending | `active` | `available` | `preliminary`(or absent) |
| ordered, study not started | `active` | 不在 | 不在 |
| cancelled | `revoked` | 不在 | 不在 |

snapshot 時点 truncation = ordering pipeline 既存の AD-32 path に乗る。

## 7. Edge cases

| ケース | 動作 |
|---|---|
| disease.yaml に `imaging_orders` field 不在 | 無発火、`Order(IMAGING)` 不生成、enricher no-op、no ImagingStudy emit |
| `imaging_orders[].only_if_severity` 不満足 | Order 不生成 |
| Order(IMAGING) + cancelled status | SR.status=revoked、ImagingStudy 不在(enricher は cancelled skip) |
| Order(IMAGING) + status=PLACED + snapshot mid-study | SR.status=active、ImagingStudy 不在 |
| view list 空 + modality CR | default view を `modalities.yaml[CR].default_views_by_body_site[body_site]` から fallback |
| modality 不在 in modalities.yaml | YAML loader 時 ValueError(silent-no-op defense Layer 3) |
| body_site 不在 in body_sites.yaml | 同上 ValueError |
| impression_templates に disease_id × modality 不在 | yaml loader 時 ValueError(forward-coverage Layer 6) |
| hospital_config.imaging.wado_base_url 未設定 | default placeholder fallback、no-op safe |
| LOINC ja translation 不在 | en fallback + audit warn list、PR1 内補完 |
| 既存 28 disease で imaging_orders 不在 | Pydantic optional default([]) で no-op safe |

## 8. Silent-no-op 防御 7-layer(memory `feedback_xhigh_review_lessons`)

| Layer | 適用 |
|---|---|
| 1 Canonical URI equality | `DICOM_UID_SYSTEM`, `DICOM_WADO_RS_CONNECTION_TYPE` を constant 定義、builder/audit/test 共有 import |
| 2 Shared id-prefix writer↔reader | `IMAGING_STUDY_ID_PREFIX` / `ENDPOINT_ID_PREFIX` / `RADIOLOGY_DR_ID_PREFIX` を writer module 内 owner 定義、reader が import |
| 3 YAML loader empty + per-bucket | `_validate_modalities` / `_validate_body_sites` / `_validate_impression_templates` で empty top + per-bucket guards |
| 4 Reverse-coverage forward + staleness | modalities.yaml DCM modality 集合 ↔ disease YAML imaging_orders[].modality forward-coverage + 逆 staleness |
| 5 Pre-`register_audit_module` validator ordering | 全 `_validate_*` を register call BEFORE に hoist |
| 6 Symmetric forward-coverage | body_sites.yaml SNOMED ↔ disease YAML imaging_orders[].body_site forward-coverage + impression_templates の disease_id × modality coverage |
| 7 Cross-module canonical URI(`urn:dicom:uid`)| FHIR-spec 既知 URI、独自 namespace ではない |

## 9. Testing strategy

### 9.1 Unit tests(`pytest -m unit`、<30s)

| ファイル | 内容 |
|---|---|
| `tests/unit/modules/imaging/test_engine.py` | enricher:study UID determinism / series 展開 / report template / abnormal_rate_by_severity |
| `tests/unit/modules/imaging/test_modalities.py` | YAML validator:unknown modality / missing body_site → ValueError |
| `tests/unit/modules/imaging/test_impression_templates.py` | template loader + disease × modality coverage |
| `tests/unit/output/test_fhir_imaging_study.py` | resource shape + identifier `urn:dicom:uid` + basedOn / endpoint ref / numberOfSeries 等 invariant |
| `tests/unit/output/test_fhir_endpoint.py` | Endpoint shape + wado_base_url override + payloadType + connectionType |
| `tests/unit/output/test_fhir_radiology_dr.py` | radiology DR shape + category dual coding + conclusion 日本語 |
| `tests/unit/output/test_fhir_service_request_imaging.py` | polymorphic dispatch:LAB / IMAGING 両 cohort で SR 出力 |
| `tests/unit/audit/test_imaging_audit.py` | `lift_firing_proof` 10 equality_checks fire + stub-proof self-check |

**dataclass + dict 両 path test 必須**(PR1 教訓 = production CIF は `json.load()` → dict、test は dataclass)。

### 9.2 Integration tests(`pytest -m integration`、<5min)

| ファイル | 内容 |
|---|---|
| `tests/integration/test_imaging_chain.py` | US + JP cohort で 4 resource type 全 emission + ref integrity |
| `tests/integration/test_imaging_basedon_coverage.py`★ silent-no-op gate | 全 ImagingStudy が basedOn SR を持ち resolve / 全 DR(radiology)が basedOn + imagingStudy を持ち resolve / 全 ImagingStudy.endpoint resolve |
| `tests/integration/test_imaging_determinism.py` | seed 固定 2 回 = ImagingStudy / Endpoint / radiology DR ndjson sha256 一致(AD-16) |
| `tests/integration/test_imaging_snapshot.py` | snapshot mid-encounter / cancelled order の resource emission |
| `tests/integration/test_imaging_subprocess_fullpipeline.py`★ PR1 教訓 | subprocess で run-beta → json.load → builder の production dict path verify |
| `tests/integration/test_imaging_jp_localization.py` | JP cohort で modality / bodySite / DR.conclusion 全 ja display |

### 9.3 E2E golden(`tests/e2e/golden/`)

新 resource type 4 つ追加 → golden 再生成必要(byte-diff 意図的変化)。本 PR base 起点で reseed として記録。determinism は integration test で別途担保。

### 9.4 AD-60 audit module(★ primary gate)

```python
# clinosim/modules/imaging/audit.py
register_audit_module(ModuleAuditSpec(
    name="imaging_chain",
    structural_checks=[
        "every ImagingStudy.id starts with IMAGING_STUDY_ID_PREFIX",
        "every ImagingStudy.identifier[0].system == DICOM_UID_SYSTEM",
        "every ImagingStudy.basedOn resolves to existing ServiceRequest",
        "every ImagingStudy.endpoint resolves to existing Endpoint",
        "every DiagnosticReport (radiology category) has basedOn + imagingStudy refs",
        "every Endpoint.id starts with ENDPOINT_ID_PREFIX",
        "every Endpoint.connectionType.code == DICOM_WADO_RS_CONNECTION_TYPE",
        "ImagingStudy.numberOfSeries == len(series), numberOfInstances == sum(series[].numberOfInstances)",
    ],
    clinical_acceptance={
        "pneumonia_cxr_emission_rate": ">= 0.95 for pneumonia encounters (n<30 WARN)",
        "stroke_cthead_emission_rate":  ">= 0.95 for hemorrhagic stroke encounters (n<30 WARN)",
        "abnormal_finding_rate_by_severity": "matches imaging_orders[].abnormal_rate_by_severity (±0.1, n<30 WARN)",
        "multi_series_cxr_rate": ">= 0.5 for pneumonia CXR (PA + Lateral both present)",
    },
    jp_language_checks=[
        "ImagingStudy.modality.display in ja for JP cohort",
        "ImagingStudy.series[].bodySite.display in ja for JP cohort",
        "DiagnosticReport.code.coding[].display in ja for JP cohort",
        "DiagnosticReport.conclusion (impression_ja) in ja for JP cohort",
        "ServiceRequest.code.coding[].display in ja for JP cohort (CPT→JP-K resolution)",
    ],
    lift_firing_proof={
        "equality_checks": [
            "IMAGING_CATEGORY_SNOMED == '363679005'",
            "IMAGING_CATEGORY_V2_0074 == 'RAD'",
            "DICOM_UID_SYSTEM == 'urn:dicom:uid'",
            "DICOM_WADO_RS_CONNECTION_TYPE == 'dicom-wado-rs'",
            "ImagingStudy count > 0 when imaging Order count > 0",
            "Endpoint count == ImagingStudy count (1:1 invariant)",
            "Radiology DR count == ImagingStudy count with non-None report",
            "every basedOn → ServiceRequest ref resolves in NDJSON",
            "every ImagingStudy.endpoint → Endpoint ref resolves in NDJSON",
            "ImagingStudy.id prefix disjoint from Endpoint.id prefix (no collision)",
        ],
    },
))
```

### 9.5 DQR(production cohort、PR/Merge 前必須)

```
clinosim run-beta --country US --population 10000 --seed 42 --output scratchpad/imaging_pr1_us10k/
clinosim run-beta --country JP --population 5000  --seed 42 --output scratchpad/imaging_pr1_jp5k/
clinosim audit run scratchpad/imaging_pr1_us10k/ --module imaging_chain
clinosim audit run scratchpad/imaging_pr1_jp5k/  --module imaging_chain
```

DQR doc:`docs/reviews/2026-06-30-tier1-imaging-chain-dqr.md`、4 軸評価:
- 構造:NDJSON 整合 + reference 解決 + identifier `urn:dicom:uid` 完備
- 臨床整合:pneumonia CXR 発火率 / stroke CT head 発火率 / abnormal_rate distribution / multi-series rate
- JP language:全 modality / body_site / conclusion display ja
- EHR/EMR goal:Study count / unique modality coverage / Endpoint URL placeholder count

### 9.6 Pre-merge gate(★ memory「Pre-merge gate」セッション22 教訓)

`pytest tests/unit tests/integration -m "unit or integration"` の **full sweep** を pre-merge で必ず実行(feature-specific test files のみは不十分、unrelated monkeypatch fixture が新 validator に hit する古典盲点)。

### 9.7 Determinism note(AD-16)

`ENRICHER_SEED_OFFSETS["imaging"] = 0x494D` で imaging enricher 専用 sub-seed 確立、master stream 隔離(device / hai / antibiotic precedent と同)= 既存 NDJSON byte-identical 保持。

ordering engine に新 path 追加(imaging_orders[] 読み込み)= LAB の draws に影響しない if existing disease YAML が `imaging_orders:[]` のまま(optional default)。本 PR で 3 disease に imaging_orders 追加 → これら disease のみ既存 cohort で imaging Order が増え、ImagingStudy / Endpoint / radiology DR ndjson 新規 emit、他 NDJSON は byte-identical(LAB Order の draws 数不変)。

## 10. Risks & Mitigation

| Risk | 影響 | Mitigation |
|---|---|---|
| Determinism break(新 sub-seed 導入)| 既存 cohort の draws 数変動 | `ENRICHER_SEED_OFFSETS["imaging"] = 0x494D` で master stream 隔離 |
| Study UID collision | `urn:dicom:uid` namespace 内 collision | sub-seed + deterministic hash で UID 生成、collision test 追加 |
| Multi-modality coding mismatch | DCM modality vs SNOMED procedure mismatch | modalities / body_sites / impression_templates の 3-way cross-validation |
| 既存 disease YAML(28 disease)で imaging_orders 不在 | Pydantic validation 失敗 | `imaging_orders: list = []` optional default、no-op safe |
| ServiceRequest polymorphic dispatch bug | LAB SR 回帰 | unit test で LAB / IMAGING 両 cohort 出力検証、PR1 既存 test full run |
| panel-aware grouping mechanism 分離 | LAB(panel_key)/ Imaging(imaging_views)で 2 path に分岐 | spec section 3.3 で mechanism 明示、共通 skeleton(`_build_sr_skeleton`)で integrity 保持 |
| Endpoint URL hardcoding 漏れ | 後付け実 PACS 統合時の差替点 unclear | `_resolve_wado_base_url(hospital_config)` 単一 entry point |
| LOINC / CPT / JP-K coverage 不在 | JP cohort で procedure display fallback | reference data YAML 必須 entry、validator forward-coverage、PR1 内 audit 補完 |
| DR(radiology)と DR(lab panel)の category 混同 | downstream consumer の filter break | category dual coding(SNOMED + v2-0074)が両 path 異なる、test verify |
| 既存 test monkeypatch 干渉 | pre-merge gate 見逃し | full sweep `pytest tests/unit tests/integration` pre-merge 必須 |
| ImagingStudy.numberOfInstances band production scale で不適切 | downstream NLP / IE が unrealistic instance density | typical_instances_per_series_range は radiology 文献 driven、Phase 2 audit で band verify(out-of-scope) |

## 11. Out-of-scope(★ TODO.md formal entry 必須)

| 項目 | 後続予定 | 理由 |
|---|---|---|
| Disease scope 拡張(MI / HF / PE / GI bleed / trauma / sepsis 等) | Tier 1 #2 PR2-N(disease 単位 sweep) | 初回 vertical slice = 2 disease minimal |
| Modality 拡張(MR / US / Echo / Mammography / Endoscopy / Fluoroscopy / NM) | Tier 1 #2 PR2-N(modality + disease 同時 sweep) | 初回 = CR + CT のみ |
| Encounter YAML(46 ED conditions)への imaging_orders 拡張 | Tier 1 #2 別 sub-chain | encounter scope は別 schema(disease 駆動と異なる) |
| Contrast media tracking(造影剤投与 → MedicationAdministration link) | Tier 2(safety realism) | 別 chain、AdverseEvent と一緒 |
| Imaging order の filler order number(`FILL` identifier) | Tier 2 imaging interface specifics | PLAC 単独で PR 範囲十分(LAB precedent 一致) |
| DICOM Structured Report(DICOM SR)native emission | Tier 2 deep imaging | 本 PR は metadata + narrative のみ、SR は専門 spec |
| 実 DICOM pixel data 生成 | 外部画像生成 AI 委譲(永続的 OOS) | clinosim purpose = text + metadata + WADO placeholder |
| Imaging report Stage 2 narrative(LLM-driven 詳細所見) | Tier 1 #5 DocumentReference Stage 2 | 別 chain、本 PR の template が seed として活用 |
| Radiology procedure CPT / JP-K の comprehensive 拡張 | Tier 2 revenue cycle / billing | 本 PR = pneumonia/stroke 関連 procedure code のみ |
| Critical findings notification(`CommunicationRequest`) | Tier 2 quality reporting | 別 resource |
| Imaging order の `requisition` Identifier(複数 Order 束) | Tier 1 #6 Appointment + batch ordering | 単一 Order = SR 1 件で表現可能 |
| `ImagingStudy.numberOfSeries`/`numberOfInstances` clinical-acceptance band 詳細 | Phase 2 audit | n<30 WARN guard 運用、production scale で band verify |
| Cross-encounter imaging follow-up linkage(prior study reference) | Tier 1 #7 CarePlan + EpisodeOfCare | episode-level continuity 別 chain |

### 11.1 FHIR field-level OOS(★ implementation plan で emit しない optional fields を明示)

R4 spec で各 resource が持つ optional fields のうち、imaging-PR1 が **意図的に emit しない** ものを resource 別に列挙。implementation plan で「もしかして必要?」と迷ったときの判断基準として書面化する。

#### ImagingStudy(emit する: id / identifier / status / modality / subject / encounter / started / basedOn / endpoint / numberOfSeries / numberOfInstances / series[])

| OOS field | 理由 / 後続予定 |
|---|---|
| `modality[]` 複数値 | PR1 = 1 Study 1 modality(CR or CT)、modality 混在は Tier 2 で(例:nuclear medicine fused PET-CT) |
| `partOf` | 関連 Study chain(同患者の prior reference)= cross-encounter linkage(Section 11 #13) |
| `referrer` | overlaps with `basedOn.ServiceRequest.requester`、PR1 は SR 経由解決 |
| `interpreter` | 放射線科医による所見解釈者、radiology DR.performer と同 information = Tier 2 CareTeam で statement-of-record |
| `procedureReference` / `procedureCode` | imaging を Procedure resource として別途 emit はしない(PR1 は ImagingStudy 単独で完結)、Tier 2 で procedure linkage |
| `location` | 撮影場所 Location ref = Tier 2 facility extension |
| `reasonCode` / `reasonReference` | clinical_indication は `basedOn.ServiceRequest.reasonCode` 経由、ImagingStudy 側 reason 重複は冗長 |
| `note` | freetext 補足 = Tier 2 narrative |
| `description` | Study-level description = `code.text` 経由で十分 |

#### DiagnosticReport(radiology variant、emit する: id / status / category / code / subject / encounter / effectiveDateTime / issued / basedOn / imagingStudy / conclusion)

| OOS field | 理由 / 後続予定 |
|---|---|
| `performer` | 解釈放射線科医 = Tier 2 CareTeam |
| `resultsInterpreter` | 同上 |
| `specimen` | 病理 biopsy = Tier 2 deep imaging |
| `result` | tabular result = lab DR で使用、radiology DR では narrative conclusion で十分 |
| `imagingStudy[]` multi-study | 単一 Study リンク(本 PR scope)、multi-study DR は Tier 2 |
| `media` | thumbnail / sample image = 外部画像生成 AI 統合後の Tier 2 |
| `conclusionCode` | SNOMED-coded conclusion = Tier 2 NLP/IE 高度化 |
| `presentedForm` | PDF report attachment = Tier 1 #5 DocumentReference Stage 2 |

#### ServiceRequest(imaging category、emit する: id / identifier(PLAC)/ status / intent / category / priority / code / subject / encounter / authoredOn / requester / reasonCode / bodySite)

| OOS field | 理由 / 後続予定 |
|---|---|
| `requisition` Identifier(複数 SR 束ね) | 単一 Order = SR 1 件で表現可能、batch ordering は Tier 1 #6 Appointment |
| `replaces` / `basedOn`(chained orders) | revision / amendment workflow = Tier 2 |
| `doNotPerform` | negative orders 表現 = Tier 2 |
| `orderDetail` | sub-detail 追加 = Tier 2 contrast-specific instructions |
| `quantity[x]` | imaging では通常未使用、Tier 3 で |
| `occurrence[x]` | scheduled timing = Tier 1 #6 Appointment |
| `asNeeded[x]` | PRN imaging = Tier 2 |
| `performerType` / `performer` | 検査実施技師 = Tier 2 CareTeam |
| `locationCode` / `locationReference` | 撮影場所 = Tier 2 facility |
| `reasonReference` Condition ref | reasonCode.text で十分、Condition 直接 ref は Tier 2 |
| `insurance` | imaging billing 直接 ref = Tier 3 Claim |
| `supportingInfo` | clinical context refs = Tier 2 |
| `specimen` | biopsy SR で必要、PR1 imaging は specimen 不在 |
| `note` | freetext 補足 = Tier 2 |
| `patientInstruction` | 患者向け説明書 = Tier 1 #5 DocumentReference |
| `filler` identifier(`FILL`) | placer 単独で PR1 範囲十分(Section 11 #5) |

#### Endpoint(emit する: id / status / connectionType / payloadType / payloadMimeType / address)

| OOS field | 理由 / 後続予定 |
|---|---|
| `identifier[]`(additional)| WADO-RS URL は address で十分、追加 identifier は Tier 2 |
| `name` | Endpoint human-readable name = Tier 2 (例: "Main Hospital PACS") |
| `managingOrganization` | 管理組織 ref = Tier 2 facility |
| `contact` | endpoint 管理者 contact = Tier 2 facility |
| `period` | 有効期間 = Tier 2 lifecycle |
| `header` | HTTP header 設定 = Tier 2 endpoint integration |

#### 共通(全 resource):FHIR R4 extension mechanism

PR1 は **clinosim 独自 extension(`http://clinosim.io/fhir/StructureDefinition/...`)を emit しない**。標準 R4 field のみ使用 = JP Core / US Core の base profile に整合。独自 extension が必要になる時(例: imaging modality-specific custom field)は Tier 2 以降で `extension[]` array 経由、`url` は canonical URI 規約に従う。

#### 多言語 coding(AD-46)

ImagingStudy.modality と DiagnosticReport.category は **dual coding 不要**(R4 spec が単一 coding を期待、JP Core も同様)。一方 ServiceRequest.category と DiagnosticReport.category は `SNOMED + v2-0074` の **dual coding 採用**(PR1 LAB precedent 適用)。

---

## 12. Adversarial chain plan

8 例の安定 pattern(PR-A / PR #102 / PR-B1 / PR3b-3-original / PR3b-3-D1+D2 / PR3b-5 / sibling sweep / PR1-LAB)に従う **5-lens parallel fan-out**(stage 2 default):

| 段階 | 内容 | converged 判定 |
|---|---|---|
| imaging-PR1-original | vertical slice 完成 | audit + full test + DQR 4 軸 PASS |
| adversarial-1 | 5-lens fan-out review:silent-no-op deep / データ統一 / FHIR-JP Core / AD-16 + scale / spec compliance | findings 列挙、fix PR |
| imaging-PR1-adv-1 | adv-1 findings fix | audit + full test PASS |
| adversarial-2 | adv-1 fix に同 5-lens fan-out(教訓自己適用) | 次段 findings 列挙 |
| imaging-PR1-adv-2 | adv-2 findings fix(必要なら) | audit + full test PASS |
| **converged** | Critical=0 + Important=0 + 残 cosmetic only + 次段 expected size tiny | chain CLOSED + memory precedent 記録 |

通常 2-4 段で converged。

## 13. PR sequencing

```
imaging-PR1: Imaging chain α-min (本 spec) = Tier 1 #2 の first PR
  scope = pneumonia + stroke / CR + CT / 4 resource end-to-end
  ├─ Internal task slice(12 tasks):
  │   ├─ Task 1: types/imaging.py + dataclass + extensions slot 確立
  │   ├─ Task 2: modules/imaging/ skeleton + 3 YAML + 3 validators
  │   ├─ Task 3: ordering engine 拡張(disease YAML imaging_orders[] → Order(IMAGING))
  │   ├─ Task 4: imaging enricher(Order → ImagingStudyRecord + extensions["imaging"])
  │   ├─ Task 5: _fhir_imaging_study.py + _fhir_endpoint.py 新 builder
  │   ├─ Task 6: _fhir_service_request.py polymorphic + _fhir_diagnostic_report.py radiology variant
  │   ├─ Task 7: hospital_config.imaging.wado_base_url + Endpoint 解決
  │   ├─ Task 8: disease YAML(pneumonia × 2 + stroke × 1)imaging_orders[] 追加 + impression templates
  │   ├─ Task 9: audit.py + lift_firing_proof(10)+ clinical-axis gate
  │   ├─ Task 10: unit / integration / e2e / determinism / subprocess full-pipeline test
  │   ├─ Task 11: DQR(US 10k + JP 5k)+ audit run + docs sync
  │   └─ Task 12: golden 再生成 + final whole-branch review
  │
  ├─ Adversarial-1: 5-lens parallel fan-out
  │   ├─ Lens 1: silent-no-op deep dive(builder dict/dataclass、`_o()` 適用漏れ、audit gate 自己沈黙)
  │   ├─ Lens 2: データ統一 compliance(YAML 単一 loader、canonical constant single-site、helper 重複)
  │   ├─ Lens 3: FHIR R4 / US Core / JP Core 厳密性
  │   ├─ Lens 4: AD-16 determinism + scale invariants
  │   └─ Lens 5: spec compliance + memory + CLAUDE.md adherence
  │
  ├─ imaging-PR1-adv-1: adv-1 findings fix
  └─ imaging-PR1-adv-2: adv-2 fan-out → fix (or converged)

imaging-PR2-N: Tier 1 #2 後続 disease + modality sweep
  ├─ imaging-PR2: + MI / HF disease + Echo modality
  ├─ imaging-PR3: + PE / GI bleed + CTA / abdomen CT
  ├─ imaging-PR4: + trauma + plain X-ray multiple body sites
  └─ imaging-PRN: encounter YAML imaging_orders 拡張 sweep
```

## 14. Docs sync(PR1 内全更新、memory `feedback_pr_merge_dqr_required`)

- `README.md` / `README.ja.md`:Imaging chain 言及追加(ImagingStudy + radiology DR + WADO-RS placeholder)
- `MODULES.md`:`imaging` モジュール行追加 + Dependency Tree 更新(imaging → device / hai / antibiotic と同 stage)
- `DESIGN.md`:新 ADR `AD-62: Imaging metadata-only chain with WADO-RS placeholder + ImagingStudy + radiology DR + Endpoint`(現最新 AD-61)
- `docs/CONTRIBUTING-modules.md`:imaging を always-on Module 例として追加、reference data 3-way validation pattern を update
- `clinosim/modules/imaging/README.md`:新規(`.github/TEMPLATE_MODULE_README.md` boilerplate)
- `clinosim/modules/order/README.md`:Order.imaging_modality / imaging_body_site_code / imaging_views field 追記
- `TODO.md`:Out-of-scope 13 項目 formal entry 化(Tier 1 #2 PR2-N sweep 計画含む)
- `CLAUDE.md`:imaging Module 例 + 新 DRY rule(`imaging_views` ↔ series 展開 helper、sibling pattern with `scenario_flags` / `medication_flags` / `panel_grouping_helper`)
- `docs/design-guides/fhir-data-generation-logic.md`:imaging precedent を Application precedents 表に追加
- `SCENARIO_FLAGS.md`:no-op(imaging は disease YAML driven、scenario_flag mechanism と異なる)

## 15. References

- memory:`project_ehr_sample_dataset_roadmap`(Tier 1 #2 = Imaging metadata-only chain)
- memory:`feedback_recommendation_evaluation_axes`(6 軸評価)
- memory:`feedback_xhigh_review_lessons`(silent-no-op 防御 PR-90 教訓)
- memory:`feedback_iterative_adversarial_review`(8 例 adversarial chain pattern)
- memory:`feedback_unify_data_logic`(canonical single source)
- memory:`reference_jlac10_source`(LOINC + JLAC10 権威照合)
- memory:`reference_tx_fhir_terminology`(SNOMED 照合)
- 既存 spec precedent:`docs/superpowers/specs/2026-06-29-pr1-servicerequest-lab-design.md`(PR1 LAB ServiceRequest)
- 既存 builder precedent:`_fhir_service_request.py`(polymorphic 拡張先)/ `_fhir_device.py` / `_fhir_hai.py`(extensions-driven Module pattern)
- 既存 reference data:`clinosim/modules/output/reference_data/lab_panel_groups.yaml`(panel-aware pattern)
- FHIR R4:`ImagingStudy`(https://hl7.org/fhir/R4/imagingstudy.html)/ `Endpoint`(https://hl7.org/fhir/R4/endpoint.html)/ `ServiceRequest`(https://hl7.org/fhir/R4/servicerequest.html)/ `DiagnosticReport`(https://hl7.org/fhir/R4/diagnosticreport.html)
- 認証 sources:NLM clinicaltables(LOINC + CPT + ICD)/ AMA(CPT)/ MHLW(JP K-code)/ tx.fhir.org(SNOMED)/ JCCLS-JSLM v137(JLAC10)
