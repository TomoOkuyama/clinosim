# `clinosim.modules.document.narrative` — Stage 2 narrative 生成 pipeline

## 概要

AD-65 Stage 2 narrative pass の実装。`NarrativePass` が
([`clinosim.modules.document`](../README.md) が stub として
`narrative=None` で emit した) 構造化 CIF を (doc_type, language) group
順に walk し、各 document を `NarrativeGenerator` に渡す。generator は 2 種:

- **`TemplateNarrativeGenerator`** — Stage 1 決定論的 renderer。
  default の `TemplateNarrativePass` が使い、LLM path でも base
  layer として動作する。
- **`LLMNarrativeGenerator`** — template generator を wrap し、
  `DocumentTypeSpec.llm_enabled_sections` を `LLMService.complete_prompt`
  経由で LLM 出力に置換する (AD-11 — 全 LLM 呼び出しは
  [`clinosim.modules.llm_service`](../../llm_service/README.md) 経由)。
  provider 失敗時は per-document で template 出力に fallback。opt-in は
  明示的 CLI `clinosim narrate --provider bedrock|ollama|mock` — env
  gate は無し。

`NarrativeCache` は layer-1 in-memory cache (clinical-context +
template-seed-hash key、患者跨ぎ section 再利用用)。layer-2 disk
`PromptCache` は `llm_service` 内。

## Scope

- **In scope**: 2-pass アーキテクチャ (`NarrativePass` 抽象 +
  `TemplateNarrativePass` + `LLMNarrativePass`)、2 generator、
  `apply_replacement_strategy` per-section dispatch (`template_only`
  / LLM driven)、prompt 構築 pipeline (`context.py` CIF→ctx
  factory、`scenario_spine.py` DiseaseProtocol → NarrativeSpine、
  `fact_extractor.py` FactTag materialisation (AD-65 E2 — β-JP-1 が
  `materialized_facts` に無い数値を emit 拒否)、`section_extractor.py`
  per-COMPOSITION section slicing (AD-65 E3))、`template_generator.py`
  placeholder engine (大 — vitals / discharge / home-med / hedging
  placeholder 解決)、慢性疾患 SOAP resolver (`_chronic_soap.py` — 32
  disease YAML は急性入院のみカバーするため慢性疾患は ICD-10 のみで
  現れ、独立 SOAP template library を必要とする)、hedging phrase
  pool (`_hedging.py` — 「Template = 単体で adequate density」原則を
  強制)、narrative-interpretation threshold
  (`_narrative_interpretation_thresholds.py`)、narrative cache
  (`cache.py`)、semantic-check gate (`semantic_check.py` — byte-diff
  が効かない非決定論的 LLM 出力に対する検証 gate)、`DocumentTypeSpec`
  registry ([`registry.py`](registry.py) — 6-layer validated
  document-type spec loader + `specs_for_country` +
  `specs_for_encounter_type` filter + `AD-64` の
  `encounter_types_supported` 空 tuple gotcha)。
- **Out of scope**: LLM provider I/O
  ([`llm_service`](../../llm_service/README.md))、stub emission
  ([`document`](../README.md))、FHIR
  `Composition` / `DocumentReference` serialization
  ([`output/fhir_r4/documents/`](../../output/fhir_r4/documents/README.md))。

## Public API

Package `__init__.py` が 4 symbol を再 export、それ以外は必要な
caller が submodule から直接 import:

```python
from clinosim.modules.document.narrative import (
    TemplateNarrativeGenerator,   # Stage 1 決定論的
    LLMNarrativeGenerator,        # template base + per-section LLM 置換
    NarrativeCache,               # layer-1 in-memory cache
    apply_replacement_strategy,   # section 単位 replacement dispatch
)
from clinosim.modules.document.narrative.passes import (
    NarrativePass,                # 抽象
    TemplateNarrativePass,        # default (Stage 1)
    LLMNarrativePass,             # narrate --provider {bedrock|ollama|mock}
)
from clinosim.modules.document.narrative.registry import (
    DocumentTypeSpec,
    load_document_type_specs,     # () -> {DocumentType: DocumentTypeSpec}
    specs_for_country,            # (country) -> list[DocumentTypeSpec]
    specs_for_encounter_type,     # (encounter_type) -> list[DocumentTypeSpec]
)
from clinosim.modules.document.narrative.context import build_context     # (CIF, encounter, doc) -> NarrativeContext
from clinosim.modules.document.narrative.scenario_spine import build_spine  # (protocol, day) -> NarrativeSpine
from clinosim.modules.document.narrative.fact_extractor import materialize_facts
from clinosim.modules.document.narrative.section_extractor import extract_section_facts
from clinosim.modules.document.narrative.semantic_check import check_narratives
```

## 決定論

- **`TemplateNarrativeGenerator` は byte-deterministic** — Stage 1
  全出力は構造化 CIF + template seed の純粋関数。default の
  `TemplateNarrativePass` が run 跨ぎ byte-diff を保つ。
- **`LLMNarrativeGenerator` は実 backend で非決定論的**。
  `semantic_check.check_narratives(cif_dir, version_id, …)` が
  LLM path で byte-diff を代替する β-JP-1 検証 gate。
- **NarrativeCache seed_hash** (N-chain adv-1 C-1) — cache key に
  template seed text の `sha256` を含めるため、患者跨ぎ再利用が
  構造的に健全 (誤患者 hit は seed hash が変わり cache miss になる)。
- **Group walk 順** (AD-65) — `NarrativePass` は文書を
  (doc_type, language) 単位で group し、同 prompt prefix を batch 内で
  再利用 → Bedrock の prompt-cache 5 分 TTL hit 最大化。
  `LLMNarrativePass` は drop-in の cache-friendliness のため同 walk 順を
  継承する。
- **fact-first 制約** (AD-65 E2) — β-JP-1 `LLMNarrativePass` は
  `materialized_facts` に含まれない数値を emit 拒否するため、LLM が
  検査値を hallucinate できない。

## 依存

- `clinosim.modules.llm_service` — `LLMService.complete_prompt` +
  `LLMTaskType` / `LLMResponse` (LLM path のみ)。
- `clinosim.modules.document` — canonical ID prefix +
  `NURSING_LOINCS` (定数のみ逆参照、enricher 本体は import しない)。
- `clinosim.modules.disease.protocol` — scenario spine 抽出用の
  `DiseaseProtocol`。
- `clinosim.modules.encounter.protocol` — 外来 / ED template 用の
  `EncounterConditionProtocol`。
- `clinosim.types.document` — `NarrativeContext`, `NarrativeOutput`,
  `DocumentType`, `FormatType`、`NarrativeGenerator` Protocol。
- `clinosim.types.clinical` — `ClinicalDocument`,
  `ClinicalDocumentNarrative`。
- `hashlib.sha256` — cache key 導出。
- `yaml`。

## 定数と設定

- **`_narrative_interpretation_thresholds.py`** — template generator
  が lab / vital 値を narrativise する際に使う全 scalar
  (`"BP is slightly elevated"` vs `"markedly elevated"`) を臨床引用
  付きで lift 済み (Issue #637 sweep)。
- **`_hedging.py`** — 「SCENARIO 由来 (未確定) 情報」契約の hedging
  phrase pool: 直接観測していない値は必ず hedge する。
- **Document-type spec YAML** —
  [`../reference_data/document_type_specs.yaml`](../reference_data/document_type_specs.yaml)
  (親 `document` package が所有、本 subpackage から load)。registry
  loader `_validate_document_type_specs` が標準 6-layer 防御を実行。
- **`DocumentTypeSpec.stage2_strategy`** — `"template_only"` は LLM
  を完全に skip。それ以外は section ごとに
  `apply_replacement_strategy` に dispatch。
- **`DocumentTypeSpec.llm_enabled_sections`** — LLM path が置換許可
  される section key の allowlist。list 外の section は template
  出力のまま。
- **`DocumentTypeSpec.encounter_types_supported`** — AD-64 α-min-2
  の空 tuple gotcha: 空 tuple は「全 encounter type と一致」を意味
  するため、inpatient 限定 spec は必ず
  `[inpatient, icu, rehab_inpatient]` を明示して outpatient / ED
  leak を防ぐ。

## ディレクトリ構造

```
clinosim/modules/document/narrative/
  __init__.py                              4 symbol を再 export (2 generator + NarrativeCache + apply_replacement_strategy)
  passes.py                                NarrativePass ABC + TemplateNarrativePass + LLMNarrativePass
  registry.py                              DocumentTypeSpec + loader + filter (6-layer validated)
  context.py                               build_context (CIF → NarrativeContext)
  scenario_spine.py                        build_spine (protocol → NarrativeSpine、AD-65 E1)
  fact_extractor.py                        materialize_facts (FactTag list、AD-65 E2 β-JP-1 制約)
  section_extractor.py                     extract_section_facts (COMPOSITION section 別、AD-65 E3)
  template_generator.py                    TemplateNarrativeGenerator + placeholder engine (~4300 LOC)
  llm_generator.py                         LLMNarrativeGenerator (template base + per-section LLM 置換)
  replacement_strategy.py                  apply_replacement_strategy dispatch (~1300 LOC)
  cache.py                                 NarrativeCache (layer-1 in-memory、seed_hash keyed)
  semantic_check.py                        check_narratives (β-JP-1 検証 gate)
  _hedging.py                              hedging phrase pool
  _chronic_soap.py                         慢性疾患 SOAP resolver (v9 density fix)
  _narrative_interpretation_thresholds.py  interpretation cutoff scalar (Issue #637)
```

**`audit.py` / `enricher.py` / `reference_data/` は存在しない** —
reference data は親 `document` package。

## Enricher 配線

該当なし — pass は encounter loop 完了後に CLI (`narrate` subcommand)
から呼ばれる。`register_builtin_enrichers` 経由でない。stub は親
`document` package の `document_enricher` が生成し、pass は それを
消費する。

## Output surface (consumers)

| Consumer | 場所 | 役割 |
|---|---|---|
| CLI `narrate` subcommand | [`clinosim/simulator/cli_narrate.py`](../../../simulator/cli_narrate.py) | default で `TemplateNarrativePass`、`--provider` 指定時は `LLMNarrativePass` を instantiate し `.run(cif_dir, version_id)` を呼び出す。 |
| Document package | [`clinosim/modules/document/__init__.py`](../__init__.py) | `registry` から `DocumentTypeSpec` + spec loader / filter を再 export。 |
| FHIR document builder | [`clinosim/modules/output/fhir_r4/documents/`](../../output/fhir_r4/documents/README.md) | 本 pass が populate した `ClinicalDocumentNarrative.sections` / `text` を `Composition.section[].text.div` に流し込む。 |
| Semantic-check CLI | (`clinosim narrate --check`) | `check_narratives` を呼び LLM 出力を fact 制約に対して verify。 |

## テスト

```bash
pytest tests/unit -k narrative -q
pytest tests/unit -k template_narrative -q
pytest tests/integration -k document_chain -q
```

Fixture golden narrative は
`tests/fixtures/patient_profiles/*.llm-mock.golden.json` に配置。
mock provider が決定論的に replay するため、`LLMNarrativePass` test
は I/O-free に保たれる。

## Ownership

`maintainers@` — 詳細は
[`CONTRIBUTING.md`](../../../../CONTRIBUTING.md)。

英語版: [`README.md`](README.md)。
