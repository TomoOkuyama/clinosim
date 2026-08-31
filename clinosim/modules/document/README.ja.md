# `clinosim.modules.document` — 臨床文書 stub + ClinicalImpression

## 概要

Tier 1 #3 α-min-1 always-on AD-55 module。POST_ENCOUNTER enricher
(`document_enricher`) が **stub の `ClinicalDocument` record**
(admission H&P / progress note / discharge summary /
operative note / procedure note / referral note / nurse note /
ED_NOTE / ED_TRIAGE_NOTE / HEALTH_CHECKUP_REPORT 等) と、
inpatient / ICU / rehab encounter に対する `ClinicalImpression`
日次 record を emit する。各 stub は `narrative=None`。narrative content
は 2-pass の [`narrative`](narrative/README.md) subpackage が Stage 2
pass で populate する (AD-65)。全 consumer が import する canonical
FHIR resource ID prefix も所有する。

## Scope

- **In scope**: `document_enricher` (POST_ENCOUNTER order=95、
  always-on)、`DocumentTypeSpec` と spec loader / filter
  ([`narrative/registry`](narrative/registry.py) 由来)、
  `clinosim.types.document` からの document-type + format-type
  再 export、canonical ID prefix 定数 (`DOC_REFERENCE_ID_PREFIX =
  "doc-"`, `COMPOSITION_ID_PREFIX = "comp-"`, `ALLERGY_ID_PREFIX =
  "allergy-"`, `CLINICAL_IMPRESSION_ID_PREFIX = "ci-"`)、
  `NURSING_LOINCS` frozenset (AD-65 Bug B — 看護師 author の文書は
  `attending_physician_id` ではなく `encounter.primary_nurse_id` に
  dispatch)、reference data loader
  ([`reference_data_loaders.py`](reference_data_loaders.py) —
  `load_physical_exam_findings`, `load_discharge_instructions` に
  6-layer validator)、per-encounter document-type dispatch
  (`_pick_document_author`, `_referral_note_fires`,
  `_enc_type_value`, `_enc_status_value`, `_compute_los_days`,
  `_make_doc_stub`)。
- **In scope (audit)**: [`audit.py`](audit.py) — 5 番目の
  per-module AD-60 plug-in (hai / antibiotic / order / imaging の次)。
  49-check `lift_firing_proof` が canonical 定数
  (`DOC_REFERENCE_ID_PREFIX` / `COMPOSITION_ID_PREFIX` /
  `ALLERGY_ID_PREFIX` / `CLINICAL_IMPRESSION_ID_PREFIX` /
  `CARE_TEAM_ID_PREFIX`)、emission count、ID-prefix invariant、
  CIF → FHIR no-drop matrix (Section 3.4)、LOINC 54094-8 dispatch
  gate、AD-65 Bug A の `us_admission_hp_zero_ja_chars` invariant、
  α-min-3 の 3-shift 拡張を guard。`clinical_acceptance` は
  per-encounter doc count + ClinicalImpression 日次 emission +
  AllergyIntolerance 分布 + CareTeam / triage / nursing / outpatient
  / ED の per-encounter target (計 13 key) をカバー。
- **Out of scope**: narrative content 組立 / template rendering
  ([`narrative`](narrative/README.md) subpackage が Stage 2 pass と
  LLM/template dispatch を所有)、LLM gateway
  ([`llm_service`](../llm_service/README.md))、FHIR
  `DocumentReference` / `Composition` / `ClinicalImpression` /
  `CareTeam` emission
  ([`output/fhir_r4/documents/`](../output/fhir_r4/documents/README.md))。

## Public API

```python
from clinosim.modules.document import (
    # 型 (clinosim.types.document から再 export)
    DocumentType,
    FormatType,
    NarrativeContext,
    NarrativeOutput,

    # Registry
    DocumentTypeSpec,
    load_document_type_specs,       # () -> list[DocumentTypeSpec]
    specs_for_country,              # (country) -> list[DocumentTypeSpec]
    specs_for_encounter_type,       # (encounter_type) -> list[DocumentTypeSpec]

    # Reference-data loader
    load_physical_exam_findings,    # () -> dict (@lru_cache, 6-layer validated)
    load_discharge_instructions,    # () -> dict (@lru_cache, 6-layer validated)
    load_hpi_pertinent_negatives,   # () -> dict (@lru_cache)

    # Canonical ID prefix
    DOC_REFERENCE_ID_PREFIX,        # "doc-"
    COMPOSITION_ID_PREFIX,          # "comp-"
    ALLERGY_ID_PREFIX,              # "allergy-"
    CLINICAL_IMPRESSION_ID_PREFIX,  # "ci-"

    # Author dispatch
    NURSING_LOINCS,                 # frozenset (AD-65 Bug B)
)
from clinosim.modules.document.engine import document_enricher
```

## 決定論

- サブ seed オフセット `0x444F` (`"DO"`, Tier 1 #3 α-min-1 PR1) —
  [`clinosim/seeding.py`](../../seeding.py) の
  `ENRICHER_SEED_OFFSETS["document"]` に登録済み。
- Per-encounter サブ RNG:
  `derive_sub_seed(master_seed, offset, encounter_id)` — 患者主
  RNG 未消費 (AD-16)。
- 2-pass 契約 (AD-65): `document_enricher` は `narrative=None` の
  stub を生成する。同 simulation pass で narrative を populate すると
  Stage 2 differ が silent no-op になる。契約は
  `test_narrative_populates_only_stage2` で guard。

## 依存

- `clinosim.modules._shared` — `get_attr_or_key`,
  `set_attr_or_key`, `is_jp`。
- `clinosim.modules.document.narrative.registry` — spec loader +
  filter。
- `clinosim.modules.document.reference_data_loaders` — physical
  exam finding + discharge instruction。
- `clinosim.seeding` — `ENRICHER_SEED_OFFSETS`, `derive_sub_seed`。
- `clinosim.audit.registry` (`audit.py` 経由) — AD-60 audit 登録。
- `clinosim.types.document` — `DocumentType`, `FormatType`,
  `NarrativeContext`, `NarrativeOutput`。
- `clinosim.types.clinical` — `ClinicalDocument`,
  `ClinicalDocumentNarrative`。
- `clinosim.types.encounter` — encounter 型 + `primary_nurse_id`
  / `attending_physician_id` field。
- `yaml`, `numpy`。

## 定数と設定

- **Canonical ID prefix** (writer 所有、全 FHIR builder が import):
  `DOC_REFERENCE_ID_PREFIX`, `COMPOSITION_ID_PREFIX`,
  `ALLERGY_ID_PREFIX`, `CLINICAL_IMPRESSION_ID_PREFIX`。
  `fhir_r4/demographics/patient.py` は `allergy-{patient_id}-{index:02d}` を inline
  で書き込んでいるが、本 prefix 定数は Task 9 FHIR builder のために
  canonicalise する (concern logged。統一は追跡中)。
- **`NURSING_LOINCS`** (frozenset、`engine.py` の
  `_load_nursing_loincs` 経由で load) — 看護師 author 文書の LOINC
  code。`_pick_document_author` は文書 LOINC が本集合に含まれるとき
  `encounter.primary_nurse_id` に dispatch、含まれない場合は
  `attending_physician_id` (AD-65 Bug B fix)。
- **Document-type spec**
  ([`reference_data/document_type_specs.yaml`](reference_data/document_type_specs.yaml))
  — 文書種別ごとの registry entry。LOINC、`format_type`
  (`"free_text"` / `"composition"`)、`encounter_types_supported`
  allowlist (AD-64 α-min-2 — 空 tuple は「全 encounter type と一致」
  を意味するため、inpatient 限定文書の spec は必ず
  `[inpatient, icu, rehab_inpatient]` を明示して outpatient / ED へ
  leak しないようにする)、国 gate、author-role hint を保持。
- **6-layer reference-data validator** (Task 5 pattern) —
  `_validate_physical_exam_findings` と
  `_validate_discharge_instructions` が empty-top / missing-key /
  per-bucket / required-key / pre-use 順序 / per-entry required-field
  を検査。YAML typo は import 時に raise。
- **Chronic SOAP + hedging** reference YAML
  (`chronic_soap_templates.yaml`, `hedging_phrases.yaml`) は
  [`narrative`](narrative/README.md) 側 submodule から read されるが、
  本 package の `reference_data/` に配置されている。

## ディレクトリ構造

```
clinosim/modules/document/
  __init__.py                        公開 API + canonical ID prefix
  engine.py                          document_enricher + doc-stub helper + NURSING_LOINCS
  reference_data_loaders.py          load_physical_exam_findings + load_discharge_instructions (6-layer)
  audit.py                           AD-60 audit plug-in #5 — 49-check lift_firing_proof
  reference_data/
    document_type_specs.yaml         文書種別 registry
    physical_exam_findings.yaml      per-disease PE 所見 (baseline + override)
    discharge_instructions.yaml      per-disease 退院指示
    chronic_soap_templates.yaml      慢性疾患 SOAP note template
    hedging_phrases.yaml             narrative hedging phrase pool
  narrative/                         narrative subpackage (Stage 2 pipeline) — narrative/README.md 参照
```

## Enricher 配線

[`clinosim/simulator/enrichers.py`](../../simulator/enrichers.py)
(`L340-348` 付近) で登録:

- `name="document"`, `stage=POST_ENCOUNTER`, `order=95`,
  `enabled=lambda c: True`。POST_ENCOUNTER 最後 (imaging=90、
  triage=93、nursing_assignment=94 の後) に走り、全上流 extension
  slot を消費できる。
- `audit.py` は import 時に AD-60 audit framework に登録される。

## Output surface (consumers)

| Consumer | 場所 | 役割 |
|---|---|---|
| Enricher registry | [`clinosim/simulator/enrichers.py:344`](../../simulator/enrichers.py) | POST_ENCOUNTER order=95 登録。 |
| Audit registry | [`clinosim/modules/document/audit.py`](audit.py) | AD-60 audit plug-in — 49-check lift_firing_proof + clinical_acceptance。 |
| Narrative Stage 2 | [`clinosim/modules/document/narrative/passes.py`](narrative/passes.py) | 本モジュールが emit した全 stub に `narrative.sections` を populate。 |
| FHIR document builder | [`clinosim/modules/output/fhir_r4/documents/`](../output/fhir_r4/documents/README.md) | stub + populate 済み narrative から `DocumentReference` / `Composition` / `ClinicalImpression` を emit。 |

## テスト

```bash
pytest tests/unit -k "document" -q
pytest tests/integration -k "document_chain" -q
clinosim audit run -d <cohort_dir> --module document
```

Coverage は大量 — `tests/unit -k document` で per-spec / per-encounter
/ per-country test を検索、end-to-end CIF → FHIR chain guard は
`tests/integration/test_document_chain.py`。

## Ownership

`maintainers@` — 詳細は
[`CONTRIBUTING.md`](../../../CONTRIBUTING.md)。

英語版: [`README.md`](README.md)。
