# Tier 1 #3 AD-65: Structural + Narrative CIF File Separation (Two-Pass Generation)

**Chain:** Tier 1 #3 α-min-2b — Stage 2 LLM Narrative Architecture Restoration + 3 Critical Clinical Bugs + CLI Silent Override Fix + Dev Iteration Facility

**Session:** 28

**Date:** 2026-07-02

**Status:** DRAFT — spec self-review pending

**Prior chain closure:** PR #130 merged 2026-07-01(α-min-2、Tier 1 #3 CareTeam + Outpatient/ED CT + Nursing、AD-64)

**Merge base:** `486eea6ddf`(master HEAD `9cc2ba0165`)

## 0. Purpose

α-min-1 Task 15(commit `2c09b6a099`)で `clinosim/modules/output/SPEC.md` の 元設計から drift した「構造化 CIF と narrative CIF の file-level 分離 + Stage 2 LLM 差替 architecture」を復元する。session 27 末 Clinical Integrity review で発覚した 3 Critical narrative bugs(US H&P Japanese contamination / Nurse Notes physician author / Triage Level 1+5 missing)+ session 28 追加発覚の CLI silent override bug(-p 10000 → US 40k silent 4x override)を同 chain で修正し、dev iteration facility(`test-disease --format` + `narrate` verb standalone)を追加して narrative bug 検証 cycle を 10 秒-30 秒に高速化する。

### Chain scope 5 pillar

1. **Architecture restoration**:Two-pass CIF generation(structural / narrative の physical + type 両面分離)
2. **Type refactor**:`ClinicalDocumentNarrative` wrapper 導入、`ClinicalDocument` を stub 化
3. **3 Critical bug fixes**:H&P locale routing / Nurse Note author / Triage Level 1+5
4. **1 Silent bug fix**:CLI `-p` sentinel override 撤廃
5. **Dev iteration facility**:`test-disease` / `test-encounter` に `--format` + `-o` 追加、`narrate` verb 復活

### Chain size

- **SDD tasks: 23**(architecture 6 + doc 7 + bug fix 7 + dev facility 2 + test 1、詳細は Appendix A)
- Expected session count: 1-1.5(session 28 内収束予定、adv-1 fan-out 別途)
- Test coverage delta: +50-60 unit / +10-15 integration / 39 e2e regenerate / +6 audit gates
- 比較 baseline:session 26 α-min-1 = 15 SDD task、session 27 α-min-2 = 15 SDD task、本 chain = 23(bug fix + dev facility + doc の 分の増分)

### User decision summary(brainstorming ログ)

| Decision | Answer | 根拠 |
|---|---|---|
| Stage 2 LLM scope | Infrastructure only(LLM 実 invocation は β-JP-1) | `LLMNarrativeGenerator` scaffold 既存 = infra 最小 |
| Backwards compat | No compat(scratchpad は fresh regen) | scratchpad の使い捨て前提 |
| Type split location | `ClinicalDocumentNarrative` wrapper 導入 | Stage 2 差替時 silent-no-op 最防護 |
| Stage 1 flow | Inline in `generate`(UX 不変) | pre-deletion `generate --narrative` pattern と同思想 |
| JP FHIR volume gap | 「同 data 量が理想 + dev cycle 加速 facility」 | Bug D fix + Dev facility を同 chain 内 fold |
| Dev facility scope | Option 2 Small(test-* に --format + -o)| 3 SDD task で 3-tier regen 完成、Option 3(fixture)は α-min-2c defer |

## 1. Architecture

### 1.1 Three-stage pipeline

```
┌──────────────────────────────────────────────────────────────────────┐
│ clinosim generate ...                                                │
│                                                                      │
│  Stage 1: Simulate + write structural CIF                            │
│  ──────────────────────────────────────                              │
│  simulator/run_beta                                                  │
│    └─ per patient: inpatient/emergency/outpatient simulate           │
│       └─ run_stage(POST_ENCOUNTER)                                   │
│           └─ document_enricher(★ revised)                           │
│               → append ClinicalDocument STUB(metadata + author +    │
│                 encounter_id + narrative=None) to record.documents   │
│           └─ triage_enricher / nursing_enricher(unchanged)           │
│  write_cif(dataset, cif_dir)                                         │
│    → cif/structural/patients/<enc_id>.json                           │
│                                                                      │
│  Stage 2: Template narrative pass(★ new)                            │
│  ──────────────────────────────────────                              │
│  TemplateNarrativePass.run(cif_dir, version_id="template")           │
│    ├─ scan structural CIF                                            │
│    ├─ collect (doc_stub, structural_ctx) pairs                       │
│    ├─ group by (doc_type, language) for Bedrock-cache friendliness   │
│    ├─ for each group:                                                │
│    │    for each patient:                                            │
│    │       build NarrativeContext(patient + encounter + labs +       │
│    │                              conditions + medications + ...)    │
│    │       TemplateNarrativeGenerator.generate(ctx, spec)            │
│    │       → NarrativeOutput(raw_text, sections, facts_used, meta)   │
│    │    write cif/narratives/template/documents/<enc>/<doc_id>.json  │
│    └─ write cif/narratives/template/manifest.json                    │
│    write cif/narratives/current_version.txt = "template"             │
│                                                                      │
│  Stage 3: FHIR export                                                │
│  ─────────────────                                                   │
│  get_adapter("fhir-r4").convert(cif_dir, output_dir, ctx)            │
│    ├─ CIFReader(cif_dir, narrative_version="current")               │
│    │    → merge structural + narrative → CIFPatientRecord            │
│    ├─ _bb_compositions(ctx)     [reads doc.narrative.sections]       │
│    ├─ _bb_document_references() [reads doc.narrative.text]           │
│    └─ writes fhir_r4/*.ndjson + manifest.json                        │
└──────────────────────────────────────────────────────────────────────┘

Later opt-in (β-JP-1):
┌──────────────────────────────────────────────────────────────────────┐
│ clinosim narrate --cif-dir ./output/cif --provider bedrock-sonnet-4 │
│                  --version-id "sonnet4-2026-07-02"                   │
│   → LLMNarrativePass.run(...) — drop-in on NarrativePass base class │
│   → cif/narratives/sonnet4-2026-07-02/documents/<enc>/<doc>.json    │
│                                                                      │
│ clinosim export-fhir --cif-dir ./output/cif                          │
│                      --narrative-version sonnet4-2026-07-02          │
│   → 同 structural CIF + 選択 narrative version で再 emit             │
└──────────────────────────────────────────────────────────────────────┘
```

### 1.2 Module responsibility split

| Module | 責任 | Stage 2 差替対称性 |
|---|---|---|
| `clinosim/modules/document/engine.py:document_enricher` | ClinicalDocument STUB(metadata + narrative=None)を生成、runtime state(author id, timestamps, encounter binding)を確定 | ★ 変更なし(narrative は runtime state に依存しない = Stage 2 は narrative subtree だけ書換) |
| `clinosim/modules/document/narrative/passes.py`(new) | `NarrativePass` base + `TemplateNarrativePass` 実装 | ★ 完全対称、`LLMNarrativePass` は drop-in |
| `clinosim/modules/document/narrative/template_generator.py` | `NarrativeContext` + `DocumentTypeSpec` → `NarrativeOutput`(text / sections / facts_used) | 変更なし + Bug A の H&P locale routing fix |
| `clinosim/modules/output/cif_writer.py` | structural CIF write のみ(narrative content strip) | ClinicalDocument.narrative=None を保持 |
| `clinosim/modules/output/cif_reader.py`(new) | structural + narrative version を merge → CIFPatientRecord | 全 FHIR builder の共通 entry point |
| `clinosim/modules/output/fhir_r4_adapter.py` | CIFReader 経由で load、既存 `_bb_*` builders は `doc.narrative.sections` / `doc.narrative.text` 経由(単一 refactor) | 変更なし |
| `clinosim/simulator/cli.py` | `generate`(auto Stage 2 template 起動)+ `narrate`(new)+ `export-fhir`(narrative_version arg)+ `test-disease/test-encounter`(--format + -o) | narrate 側で LLM provider dispatch(β-JP-1) |
| 全 canonical docs(CLAUDE.md + DESIGN.md + SPEC.md + MODULES.md + module READMEs + TODO.md + CONTRIBUTING-modules.md) | AD-65 two-pass invariant を全 canonical doc に横断反映、次 session drift 防止 | 継続 chain の設計思想固定 |

### 1.3 Narrative directory layout

```
output/cif/
├── metadata.json                    (unchanged)
├── hospital.json                    (unchanged)
├── structural/
│   └── patients/
│       ├── <enc_id_1>.json          (★ ClinicalDocument stubs + narrative=None)
│       └── ...
├── narratives/
│   ├── current_version.txt          (★ pointer file、"template" or LLM version id)
│   ├── template/                    (★ Stage 1 default)
│   │   ├── manifest.json            (NarrativeVersionManifest serialized)
│   │   └── documents/
│   │       ├── <enc_id_1>/
│   │       │   ├── admission_hp.json         (ClinicalDocumentNarrative serialized)
│   │       │   ├── progress_note_day_1.json
│   │       │   ├── discharge_summary.json
│   │       │   └── ...
│   │       └── ...
│   └── sonnet4-2026-07-02/          (opt-in、β-JP-1 で narrate verb 経由)
│       ├── manifest.json
│       └── documents/
│           └── ...
```

- `current_version.txt` = plain text pointer(symlink 不使用、Windows compat + git friendly)
- Filename convention:pre-deletion pattern 継承 = `<task_type>[_suffix].json`
  - `admission_hp.json`, `progress_note_day_{n}.json`, `discharge_summary.json`, `nursing_shift_note_{shift_key}.json`, `operative_note_{nnn}.json`, `outpatient_soap.json`, `ed_note.json`, `ed_triage_note.json`, etc.
- 1 encounter = 1 dir、複数 doc/encounter 並列格納
- narrative file content = `ClinicalDocumentNarrative` の JSON serialize(document_id + encounter_id をも carry で 1:1 merge key)

### 1.4 Bedrock cache-friendly walk order contract

`NarrativePass` base class の walk 順序:

```python
class NarrativePass:
    def run(self, cif_dir: str, version_id: str) -> None:
        specs = load_document_type_specs()
        # ★ Bedrock cache 対応 walk 順:
        #   1. Group by (doc_type, language) — 同 prompt template 共有
        #   2. Group 内 patient 逐次 → prefix cache warm 継続
        for spec in specs:
            for language in spec.languages_supported:
                for patient_file in sorted(...):
                    ctx = build_narrative_context(patient, spec, language)
                    output = self._generate(ctx, spec)
                    self._write(narrative_dir, ctx.encounter_id, spec, output)
```

- **Bedrock prompt cache = 5 分 TTL(default)**、group 内 serial 処理で prefix cache warm 継続
- LLMNarrativePass(β-JP-1)は base class 継承 = 自動的 cache-friendly
- 本 chain では walk 順序契約を base class で確定、cache 実効は β-JP-1 で verify

## 2. Type Changes

### 2.1 Current state refresher

**`ClinicalDocument`(`clinosim/types/clinical.py:108-154`)** — 現行 flat mixed(structural + narrative 混在):

```python
@dataclass
class ClinicalDocument:
    # structural
    document_id: str = ""
    task_type: str = ""
    loinc_code: str = ""
    patient_id: str = ""
    encounter_id: str = ""
    author_practitioner_id: str = ""
    related_procedure_id: str = ""
    authored_datetime: str = ""
    period_start: str = ""
    period_end: str = ""
    language: str = "en"
    content_type: str = "text/plain; charset=utf-8"
    format_type: str = ""

    # ★ narrative(Stage 2 差替対象、flat mixed = AD-65 で分離)
    text: str = ""
    sections: dict[str, str] = field(default_factory=dict)
    text_source: str = "none"
    llm_model: str = ""
    llm_provider: str = ""
    llm_input_tokens: int = 0
    llm_output_tokens: int = 0
    prompt_version: int = 0
    cache_hit: bool = False
    generated_at: str = ""
    fallback_reason: str = ""
```

**`NarrativeOutput`(`clinosim/types/document.py:82-95`)** — generator 直接返り値 = temporary intermediate、AD-65 でも保持。

### 2.2 New: `ClinicalDocumentNarrative` wrapper

追加場所:`clinosim/types/clinical.py`

```python
@dataclass
class ClinicalDocumentNarrative:
    """Narrative subtree of a ClinicalDocument — Stage 2 差替対象の全 field を集約。

    Serialization boundary:
      - Written to cif/narratives/<version>/documents/<enc>/<doc_type>.json
      - NEVER written to structural CIF file(cif_writer.py が strip)
      - Loaded by CIFReader when narrative_version が selected

    Stage 1(template)と Stage 2(LLM)で共通の shape。generator 差異は
    generator + generator_metadata で区別、text/sections は同じ semantics。
    """

    # Content(FHIR emit の source of truth)
    text: str = ""                    # FREE_TEXT / joined-sections fallback
    sections: dict[str, str] = field(default_factory=dict)   # COMPOSITION 用
    structured: dict = field(default_factory=dict)            # QUESTIONNAIRE_RESPONSE 用

    # Provenance
    generator: str = "none"           # "template" | "llm-<provider>-<model>" | "none"
    generator_metadata: dict = field(default_factory=dict)
    # e.g. {"prompt_version": 3, "prompt_template_id": "admission_hp_v3",
    #       "llm_input_tokens": 1250, "llm_output_tokens": 480,
    #       "cache_hit": true, "fallback_reason": ""}
    generated_at: str = ""

    # Fact grounding(★ Stage 2 LLM ハルシネーション防御)
    facts_used: list[str] = field(default_factory=list)
    # NarrativeContext から抽出した facts の tag list。
    # 例: ["patient.age=65", "diagnosis.primary=I63.9",
    #      "lab.creatinine.day0=2.4", "med.aspirin.dose=81mg"]
    # β-JP-1 で LLMNarrativePass が validate に使用。
    # Stage 1 template も generator 使用 field を記録推奨(将来 gate 有効化用)。
```

### 2.3 `ClinicalDocument` stub 化

```python
@dataclass
class ClinicalDocument:
    """A clinical document intended for FHIR DocumentReference / Composition output.

    Two-pass lifecycle(AD-65):
      1. Stage 1 (simulator run_stage POST_ENCOUNTER):
         document_enricher creates this as a STUB with narrative=None.
      2. Stage 2 (post-simulation, in-generate or via `narrate` verb):
         TemplateNarrativePass / LLMNarrativePass populates `narrative`.
      3. Stage 3 (FHIR adapter):
         CIFReader merges structural + selected narrative version.
    """

    document_id: str = ""
    task_type: str = ""
    loinc_code: str = ""
    patient_id: str = ""
    encounter_id: str = ""
    author_practitioner_id: str = ""
    related_procedure_id: str = ""
    authored_datetime: str = ""
    period_start: str = ""
    period_end: str = ""
    language: str = "en"
    content_type: str = "text/plain; charset=utf-8"
    format_type: str = ""

    # ★ Narrative subtree(AD-65 で分離)
    # None = enricher stub 生成直後(Stage 2 未実行)
    # Non-None = Stage 2 で populate 済(FHIR emit 可)
    narrative: ClinicalDocumentNarrative | None = None
```

**削除される fields**(narrative に移管):`text`, `sections`, `text_source`, `llm_model`, `llm_provider`, `llm_input_tokens`, `llm_output_tokens`, `prompt_version`, `cache_hit`, `generated_at`, `fallback_reason`

### 2.4 `NarrativeOutput` → `ClinicalDocumentNarrative` adaptation

`NarrativePass` 内で:

```python
def _narrative_output_to_wrapper(
    output: NarrativeOutput,
    generator: str,
    ctx: NarrativeContext,
) -> ClinicalDocumentNarrative:
    return ClinicalDocumentNarrative(
        text=output.raw_text,
        sections=output.sections,
        structured=output.structured,
        generator=generator,
        generator_metadata=output.metadata,
        generated_at=_now_iso(),
        facts_used=output.facts_used,
    )
```

### 2.5 `NarrativeVersionManifest`

```python
@dataclass
class NarrativeVersionManifest:
    """cif/narratives/<version>/manifest.json の shape。"""

    version_id: str
    generator: str
    generator_config: dict
    generated_at: str
    encounter_count: int
    document_count: int
    document_counts_by_type: dict[str, int]
    doc_types_enabled: list[str]
    languages_used: list[str]
    llm_cost_report: dict   # Stage 1 template は {}
```

`cif/narratives/current_version.txt` = plain text pointer file、1 行 = version_id 文字列。

### 2.6 Refactor sites(mechanical edits)

| File | 変更 | 概算行数 |
|---|---|---|
| `clinosim/types/clinical.py` | ClinicalDocument stub 化 + ClinicalDocumentNarrative + NarrativeVersionManifest 追加 | +60/-11 |
| `clinosim/modules/document/engine.py:_emit_doc`(4 branch) | narrative flat fields 書込 → `doc.narrative=None` stub 化 | -60/+8 |
| `clinosim/modules/document/engine.py:_narrative_to_text` | 削除(不要、pass 側担当) | -13 |
| `clinosim/modules/output/_fhir_composition.py:_bb_compositions` | `doc.sections` → `doc.narrative.sections`(None なら skip + warn) | +5/-1 |
| `clinosim/modules/output/_fhir_documents.py:_build_dref_from_clinical_doc` | `doc.text` → `doc.narrative.text` | +3/-1 |
| `clinosim/modules/document/audit.py` narrative field 参照 | 同 refactor | ~10 sites |
| 既存 tests(narrative field 直接参照) | wrapper 経由に置換 | ~20 sites |

### 2.7 Serialization examples

**structural CIF: `cif/structural/patients/<enc>.json`(抜粋)**

```json
{
  "patient": { "patient_id": "POP-000001", ... },
  "encounters": [ { "encounter_id": "ENC-POP-000001-0001", ... } ],
  "documents": [
    {
      "document_id": "doc-ENC-POP-000001-0001-admission_hp",
      "task_type": "admission_hp",
      "loinc_code": "34117-2",
      "patient_id": "POP-000001",
      "encounter_id": "ENC-POP-000001-0001",
      "author_practitioner_id": "DR-000042",
      "authored_datetime": "2026-01-15T09:32:00",
      "language": "ja",
      "format_type": "composition",
      "narrative": null
    }
  ]
}
```

**narrative CIF: `cif/narratives/template/documents/ENC-POP-000001-0001/admission_hp.json`**

```json
{
  "document_id": "doc-ENC-POP-000001-0001-admission_hp",
  "encounter_id": "ENC-POP-000001-0001",
  "narrative": {
    "text": "",
    "sections": {
      "chief_complaint": "胸部圧迫感、発症 3 時間",
      "hpi": "65 歳男性。本日 6 時起床時に...",
      "past_medical_history": "高血圧、2 型糖尿病(コントロール不良)",
      "physical_examination": "意識清明、血圧 156/94...",
      "assessment_and_plan": "急性冠症候群疑い、Troponin 上昇..."
    },
    "structured": {},
    "generator": "template",
    "generator_metadata": {
      "prompt_template_id": "admission_hp_v3",
      "cache_hit": false
    },
    "generated_at": "2026-07-02T14:30:15",
    "facts_used": [
      "patient.age=65", "patient.sex=M",
      "diagnosis.primary_icd=I21.4",
      "lab.troponin_i.day0=0.12", "lab.troponin_i.day1=1.85",
      "med.aspirin=81mg_qd", "med.clopidogrel=75mg_qd"
    ]
  }
}
```

## 3. New Modules

### 3.1 Generation logic:Base + 3 Enhancement

**過去 pattern(Task 15 削除前)**:`patient_summary + event_data + language` = 3 input で LLMTaskType 別に切替。**AD-65 で継承**、以下 3 enhancement 追加。

| Logic | 説明 | Data quality | 臨床整合性 |
|---|---|---|---|
| **Base**:Per-doc-type independent generation | patient_summary + encounter_summary + doc-specific event_data で毎回独立生成 | Baseline | Baseline |
| **★ E1**:Scenario-driven anchoring | DiseaseProtocol / EncounterProtocol YAML の `narrative.*` を **narrative spine** として、template/LLM が患者固有 detail で肉付け | ★★ | ★★★ |
| **★ E2**:Fact-first generation + `facts_used` tag | Generator が先に `facts_used = [tag]` list を deterministic materialize → narrative は facts_used のみ input constraint | ★★★(数値ハルシネーション遮断)| ★★★ |
| **★ E3**:Section-level extraction for COMPOSITION | 各 section を独立 extractor 関数化(`_extract_hpi(ctx) → SectionFacts`)→ section-specific template/prompt。llm_enabled_sections と native 適合 | ★★ | ★★ |

**Deferred to β-JP-1**:Chain-of-thought cross-doc consistency / Longitudinal chart summary。

### 3.2 `NarrativeContext` extension

`clinosim/types/document.py` に追加:

```python
@dataclass
class NarrativeContext:
    # ... 現行 field はそのまま
    narrative_spine: NarrativeSpine | None = None        # E1
    materialized_facts: list[FactTag] = field(default_factory=list)  # E2
    section_facts: dict[str, "SectionFacts"] = field(default_factory=dict)  # E3


@dataclass(frozen=True)
class FactTag:
    key: str          # "lab.troponin_i.day0"
    value: str        # "0.12 ng/mL"
    source: str       # "structural.observations" | "profile.demographics" | "scenario.archetype"


@dataclass
class NarrativeSpine:
    """DiseaseProtocol.narrative.* / EncounterProtocol.narrative.* を canonical spine 化。"""
    archetype: str
    key_events: list[str]
    complications_expected: list[str]
    outcome_benchmark: str
    disease_narrative_hints: dict[str, str]


@dataclass
class SectionFacts:
    """1 section 分の extract 結果。generator が section-specific template/prompt を組む source。"""
    section_key: str
    facts: list[FactTag]
    scenario_hint: str
    llm_replaceable: bool     # DocumentTypeSpec.llm_enabled_sections 由来
```

### 3.3 New module: `clinosim/modules/document/narrative/passes.py`

```python
"""NarrativePass base class + TemplateNarrativePass 実装(AD-65 two-pass の Stage 2 workhorse)。

責任:
  - Structural CIF を read → per-patient/encounter/doc_type で NarrativeContext 構築
  - doc_type × language group で walk(Bedrock cache-friendly 契約)
  - Generator(TemplateNarrativeGenerator or LLMNarrativeGenerator)で NarrativeOutput 生成
  - cif/narratives/<version>/documents/<enc>/<doc_type>.json 書出
  - manifest.json + current_version.txt 書出
"""

class NarrativePass(ABC):
    def __init__(self, cif_dir: str, version_id: str, country: str,
                 tasks: list[str] | None = None):
        self.cif_dir = cif_dir
        self.version_id = version_id
        self.country = country
        self.tasks_filter = set(tasks) if tasks else None

    def run(self) -> NarrativeVersionManifest:
        """Walk 順 = (doc_type, language) group serial (Bedrock cache-friendly)."""

    @abstractmethod
    def _generate(self, ctx: NarrativeContext, spec: DocumentTypeSpec) -> NarrativeOutput:
        """Provider-specific generation。"""

    def _build_context(self, patient_dict, spec, language) -> NarrativeContext:
        """3 enhancement 適用:
           - narrative_spine を DiseaseProtocol / EncounterProtocol から build
           - materialized_facts を fact_extractor で deterministic 抽出
           - section_facts を section extractor で populate(COMPOSITION 時)
        """

    def _write(self, narrative_dir, encounter_id, spec, output) -> None:
        """filename = spec-specific pattern(admission_hp.json, progress_note_day_{n}.json 等)"""


class TemplateNarrativePass(NarrativePass):
    def __init__(self, cif_dir, version_id="template", country="US", tasks=None,
                 rng_seed: int | None = None):
        super().__init__(cif_dir, version_id, country, tasks)
        self.generator = TemplateNarrativeGenerator(rng_seed=rng_seed)

    def _generate(self, ctx, spec):
        return self.generator.generate(ctx, spec)
```

### 3.4 New module: `clinosim/modules/output/cif_reader.py`

```python
"""CIFReader — Two-pass CIF の合成 loader。

全 FHIR builder は本 reader 経由で record を取得(AD-65)。
narrative_version を選択して structural + narrative dir を merge。
"""

class CIFReader:
    def __init__(self, cif_dir: str, narrative_version: str | Literal["current"] = "current"):
        self.cif_dir = cif_dir
        self.structural_dir = os.path.join(cif_dir, "structural", "patients")

        if narrative_version == "current":
            pointer_file = os.path.join(cif_dir, "narratives", "current_version.txt")
            if os.path.exists(pointer_file):
                with open(pointer_file) as f:
                    narrative_version = f.read().strip()
            else:
                narrative_version = "template"
        self.narrative_version = narrative_version
        self.narrative_docs_dir = os.path.join(
            cif_dir, "narratives", narrative_version, "documents"
        )
        self._narrative_available = os.path.isdir(self.narrative_docs_dir)

    def iter_patients(self) -> Iterator[CIFPatientRecord]:
        for filename in sorted(os.listdir(self.structural_dir)):
            if not filename.endswith(".json"):
                continue
            with open(os.path.join(self.structural_dir, filename)) as f:
                record = json.load(f)
            self._merge_narrative_into(record)
            yield _record_from_dict(record)

    def _merge_narrative_into(self, record: dict) -> None:
        """narrative dir → record.documents[i].narrative merge。

        Silent-no-op 防護:
          - narrative dir 無し → record.documents 全て narrative=None のまま
                                → FHIR builders が warn/skip
          - narrative file 見つからず → 1 stub 分だけ narrative=None、warn log
          - 過剰 narrative file(structural に stub なし)→ warn log、drop
        """
```

### 3.5 CLI:`narrate` verb 復活

```python
# clinosim/simulator/cli.py
nr = sub.add_parser(
    "narrate",
    help="Generate narrative CIF from structural CIF (Stage 2 of AD-65 pipeline)",
)
nr.add_argument("--cif-dir", required=True)
nr.add_argument("--provider", default="template",
                choices=["template"],   # β-JP-1 で ["template", "bedrock", "ollama"] 拡張
                help="Narrative generator")
nr.add_argument("--version-id", default=None,
                help="narrative version dir name (default: <provider>[-<model>-<timestamp>])")
nr.add_argument("--tasks", default=None,
                help="Comma-separated LLMTaskType filter (default: all)")
nr.add_argument("--country", default="US")
nr.add_argument("--set-current", action=argparse.BooleanOptionalAction, default=True)
nr.add_argument("--seed", type=int, default=42)


def _run_narrate(args) -> None:
    from clinosim.modules.document.narrative.passes import TemplateNarrativePass

    version_id = args.version_id or "template"
    tasks = args.tasks.split(",") if args.tasks else None

    if args.provider == "template":
        pass_impl = TemplateNarrativePass(
            cif_dir=args.cif_dir, version_id=version_id, country=args.country,
            tasks=tasks, rng_seed=args.seed,
        )
    else:
        raise NotImplementedError(f"provider={args.provider} deferred to β-JP-1")

    manifest = pass_impl.run()
    if args.set_current:
        with open(os.path.join(args.cif_dir, "narratives", "current_version.txt"), "w") as f:
            f.write(version_id)
    print(f"narrate: wrote {manifest.document_count} narrative documents across "
          f"{manifest.encounter_count} encounters → narratives/{version_id}/")
```

### 3.6 `generate` verb auto-invoke(inline UX 維持)

`clinosim/simulator/cli.py` の `main()` 関数内、`write_cif(dataset, cif_dir)` 呼出 直後 + `_run_exports(...)` 呼出 直前 に以下を挿入:

```python
from clinosim.modules.document.narrative.passes import TemplateNarrativePass
pass_impl = TemplateNarrativePass(
    cif_dir=cif_dir, version_id="template", country=args.country, rng_seed=args.seed,
)
pass_impl.run()
with open(os.path.join(cif_dir, "narratives", "current_version.txt"), "w") as f:
    f.write("template")
# 以降 _run_exports(...) が narrative_version="current" 経由で読込
```

`--no-narrative` flag は追加しない(user Q4 answer = auto-invoke default)。

### 3.7 Determinism

- Template pass の RNG:`derive_sub_seed(master_seed, ENRICHER_SEED_OFFSETS["narrative_template"], patient_id + doc_type)` 経由
- Offset 予約:`ENRICHER_SEED_OFFSETS["narrative_template"] = 0x4e54`(= "NT"、既存 offset との duplicate check は import 時 assert)
- Same seed + same structural CIF → byte-identical narrative CIF、e2e golden で pin
- LLM pass(β-JP-1)は本質的 non-deterministic → cache 経由で reproducibility

### 3.8 Module 追加 summary

| Module | 追加 file | 概算行数 |
|---|---|---|
| `clinosim/modules/document/narrative/passes.py`(new) | NarrativePass base + TemplateNarrativePass | +180 |
| `clinosim/modules/document/narrative/fact_extractor.py`(new) | E2 = materialized_facts 抽出 | +120 |
| `clinosim/modules/document/narrative/section_extractor.py`(new) | E3 = section_facts 抽出 | +200 |
| `clinosim/modules/document/narrative/scenario_spine.py`(new) | E1 = NarrativeSpine 構築 | +90 |
| `clinosim/modules/output/cif_reader.py`(new) | CIFReader = structural + narrative merge | +130 |
| `clinosim/simulator/seeding.py`(edit) | ENRICHER_SEED_OFFSETS 追加 | +2 |
| `clinosim/simulator/cli.py`(edit) | narrate verb + generate auto-invoke + test-* --format + export-fhir --narrative-version | +130/-30 |
| `clinosim/modules/document/engine.py`(edit) | narrative content populate 削除、stub 化 | +30/-100 |
| `clinosim/modules/document/narrative/template_generator.py`(edit) | fact-first refactor + section 連携 + Bug A locale 修正 | +40/-30 |

## 4. Bug Fixes

### 4.1 Bug A: US H&P Japanese contamination(4,507 doc / 全 US inpatient)

**Symptom:** US p=10k cohort の全 ADMISSION_HP の HPI + Physical Examination section が日本語 emit。

**Root cause:** `clinosim/modules/document/narrative/template_generator.py` の複数 builder が `_ja` field を unconditional access:
- `_build_hpi(360)`:ED_NOTE 分岐で `ed_tmpl.hpi_ja`(378)
- `_build_physical_examination(533)` → `_resolve_physical_exam(1135)`
- `_build_ed_physical_exam(1065)`:`physical_exam_ja`(1076)
- `_build_ed_workup(1106)`:`ed_workup_summary_ja`
- `_build_ed_disposition(1124)`:`disposition_ja`
- `_build_chief_complaint(330)`:ED_NOTE で `chief_complaint_ja`
- ADMISSION_HP path も同様の `ja_only_fallback`(918)経路(SDD task で確定)
- Disease YAML narrative 側で en field 未 populate → ja fallback → US cohort silently ja 化

**Fix strategy:**

- Code layer:`_pick_localized(tmpl, key_base, lang) -> str` helper 導入、`<key>_en` / `<key>_ja` を lang dispatch、片方 missing なら explicit warn log + empty string(silent ja fallback 撤廃)
- Data layer:全 32 disease YAML の narrative field(hpi_en / physical_examination_en / assessment_and_plan_en)を audit + missing en 補填
- E2 fact-first との整合:`_pick_localized` を `SectionFacts.scenario_hint` 経由に refactor で bug fix + enhancement 同時実装

**Test:**
- Unit:`_pick_localized(tmpl, "hpi", "en")` → en field / `"ja"` → ja field / missing → warn+empty
- Integration:US p=100 cohort の全 ADMISSION_HP section に日本語 char range(`぀-ヿ一-鿿`)0
- Audit gate:`us_admission_hp_zero_ja_chars = 0`

**SDD tasks:** 3(T1 refactor / T2 YAML audit / T3 integration test)

### 4.2 Bug B: Nurse Notes に Physician が author(23,279 doc / 全 nursing)

**Symptom:** LOINC 34746-8(NURSING_SHIFT_NOTE)+ 78390-2(ADMISSION_NURSING_ASSESSMENT)+ 34119-8(NURSING_DISCHARGE_SUMMARY)全て `author = attending_physician_id`。primary_nurse_id 無視。

**Root cause:** `clinosim/modules/document/engine.py:204` `attending_id = encounter.attending_physician_id` を 4 branch(245, 281, 313, 347)全てで hardcode。`primary_nurse_id`(α-min-2 nursing_assignment enricher populated)未参照 → AD-64 CareTeam ↔ Composition.author mismatch。

**Fix strategy:** `_pick_document_author(spec, encounter) -> str` helper 導入:

```python
def _pick_document_author(spec: DocumentTypeSpec, encounter: Encounter) -> str:
    NURSING_LOINCS = {"34746-8", "78390-2", "34119-8"}
    if spec.loinc_code in NURSING_LOINCS:
        nurse = getattr(encounter, "primary_nurse_id", "")
        if nurse:
            return nurse
        logger.warning("nursing doc %s falling back to attending", spec.loinc_code)
    return encounter.attending_physician_id
```

4 branch 内 `attending_id` 直接使用を **全て helper 経由に置換**(single edit point、J5 pattern prevention)。

**Test:**
- Unit:helper が 3 nursing LOINC + 3 physician LOINC で correct id
- Integration:cohort の 34746-8 doc 全て `author == primary_nurse_id`
- Audit gate:`nursing_doc_author_is_nurse_ratio = 1.0`

**SDD tasks:** 2(T4 helper + refactor / T5 integration test)

### 4.3 Bug C: Triage Level 1 + Level 5 完全欠落(14,531 doc / 全 ED)

**Symptom:** US 13,994 + JP 537 = 14,531 の全 ED encounter が Level 2-4 のみ。Level 1(Resuscitation)/ Level 5(Non-Urgent)0 件。

**Root cause 候補 2 案(SDD task で 1 案確定):**

- **候補 (i) Severity 上流 collapse(有力仮説)**:YAML `severity_to_triage_distribution` に `mild → 5: 0.30` + `severe → 1: 0.20` は既に存在。全 ED が Level 2-4 → severity 全 encounter で "moderate" collapse → `emergency.py` の severity 生成 logic or `encounter_conditions/*.yaml:severity_distribution` の bug
- **候補 (ii) Distribution が clinically 狭すぎる**:現行 各 severity で 3 レベルのみ、mild でも稀に severe surprise / severe でも慢性増悪 = Level 4/5 少数はあるべき → 各 severity で 5 レベル全て non-zero(dominant + tail)に broaden

**SDD task 1(T6)= Diagnosis:** US p=100 debug cohort で `Encounter.severity` distribution + `Encounter.triage_level` distribution を collect → 候補確定

**SDD task 2(T7)= Fix:**
- 候補 (i):46 ED condition YAML の `severity_distribution` audit + `emergency.py` sampling logic 修正
- 候補 (ii):`triage_protocols.yaml` の distribution 5 レベル拡張、AHRQ ESI + JTAS 2017 実測 refer

**Test:**
- Integration:US + JP p=500 cohort で triage_level 全 5 レベル non-zero(> 0.5% each)
- Audit gate:`triage_levels_1_and_5_ratio_min > 0.005`

**SDD tasks:** 2(T6 diagnosis / T7 fix、T8 audit gate は共通)

### 4.4 Bug D: CLI `--population` silent override(JP FHIR data 8x thin の主因)

**Symptom:** `-p 10000 --country US` → 実 pop 40,000 に silent override。`-p 5000 --country JP` → override 発火せず。US FHIR / JP FHIR = ~10:1 gap の主因。

**Root cause:** `clinosim/simulator/engine.py:83-93`:
```python
if config.catchment_population == 10_000:  # CLI default sentinel
    pop_size = recommended    # ← 10000 と一致すると sentinel 判定で override
```

- `-p 10000` 明示指定でも sentinel 一致 → hospital_operations.yaml の `recommended_population.US: 40000` に override
- User 指定 10000 は消失、silent 4x

**Fix strategy:**
- CLI `-p` を default=argparse.SUPPRESS(explicit 指定判定)
- `SimulatorConfig.catchment_population: int | None = None` に revise
- `engine.py`:`if config.catchment_population is None: use recommended`
- Fail-loud:override 発火時 stderr に explicit 通知

**Test:**
- Unit:`-p 10000 --country US` → SimulatorConfig.catchment_population == 10000
- Unit:CLI 未指定 → recommended_population 使用 + info log
- Integration:US p=500 + JP p=500 で Patient count が同 order of magnitude

**Audit gate:** `explicit_population_respected = True`

**SDD tasks:** 1(T8 CLI + config + integration test)

### 4.5 Dev iteration facility(全 bug verify path 加速)

3-tier regen scope:

| 変更対象 | 最短 regen | 想定時間 |
|---|---|---|
| Simulator engine / enricher | `clinosim generate -p N -o /tmp/cX` | 5-50 min |
| Template narrative generator | `clinosim narrate --cif-dir /tmp/cX --version-id template` + `export-fhir` | ~30 sec + 5 min |
| FHIR builder | `clinosim export-fhir --cif-dir /tmp/cX` | ~5 min |
| Locale display | `export-fhir` | ~5 min |
| 1 disease scenario | `clinosim test-disease acute_mi -n 5 --format all -o /tmp/verify` | ~10 秒 |
| 1 encounter condition | `clinosim test-encounter chest_pain_noncardiac --format all -o /tmp/verify` | ~5 秒 |

**SDD tasks(3 個):**

- **T9**:`test-disease` に `--format cif|fhir-r4|all` + `-o` 追加、内部で write_cif + TemplateNarrativePass + FHIR adapter を invoke(既存 pipeline を 1-N 患者向けに単純呼出)。既存 stdout debug は `-o` 未指定時 backwards compat 動作(+50 行)
- **T10**:`test-encounter` に同拡張(+40 行)
- **T11**:`docs/CONTRIBUTING-modules.md` に Regen scope matrix + 使用例 3 個追加(+50 行 doc)

**Post-AD-65 defer(α-min-2c 別 chain)**:patient profile fixture library(10-15 canonical YAML)、`--patient-profile <yaml>` 対応、narrative regression CI suite integration。

### 4.6 SDD task breakdown

Bug fix + dev facility 系 tasks の詳細は Appendix A(全 chain SDD task 統合表)を参照。本節では bug 別の task 数のみ summary:

| Bug / Category | SDD task 数 | 概算総行数 |
|---|---|---|
| Bug A(H&P locale)| 3(refactor + YAML audit + integration test)| +110/-40 + 100 YAML edits + 30 script |
| Bug B(nurse author)| 1(helper + refactor + audit gate + test 同 commit)| +55/-15 |
| Bug C(triage L1/5)| 2(diagnosis script + fix)| +10 script + 30-200 fix |
| Bug D(CLI silent)| 1(CLI + config + engine.py + test 同 commit)| +45/-15 |
| Dev facility(test-* --format + doc)| 3(test-disease / test-encounter / CONTRIBUTING doc)| +90 + 50 doc |
| Audit gate 追加(6 gate)| 1(`document/audit.py:lift_firing_proof`)| +25 |

## 5. Testing & Migration

### 5.1 Existing test impact

| カテゴリ | 修正 | 概算 test 数 |
|---|---|---|
| `ClinicalDocument.text` / `.sections` 直接 access | `doc.narrative.text` / `.sections` に置換 | ~20 sites |
| `_narrative_to_text` 存在前提 | 削除、pass 側 test に統合 | 3 tests |
| e2e golden(NDJSON hash) | **全 regenerate**(39 file、no compat 前提) | 39 goldens |
| FHIR builder direct test | wrapper 経由 adaptation | 8 tests |
| `document_enricher` stub 化 assert | `doc.narrative is None` after enricher / `doc.narrative fill` after pass に分離 | 6 tests |
| `test-*` CLI test | `--format` + `-o` args test 拡張 | 2 → 6 tests |

### 5.2 New unit test coverage(concrete list)

- `tests/unit/test_clinical_document_narrative.py`(wrapper lifecycle、facts_used populated)
- `tests/unit/test_template_narrative_pass.py`(walk order、determinism、no-op、scenario_spine、section_facts)
- `tests/unit/test_cif_reader.py`(merge、missing narrative dir warn、orphan file、current pointer default)
- `tests/unit/test_narrate_cli.py`(template provider write、current pointer update、tasks filter、bedrock NotImplementedError)
- `tests/unit/test_narrative_locale_routing.py`(Bug A:`_pick_localized` behavior)
- `tests/unit/test_document_author_selection.py`(Bug B:nursing / physician dispatch)
- `tests/unit/test_triage_severity_distribution.py`(Bug C:all 5 levels non-zero)
- `tests/unit/test_cli_population_no_sentinel.py`(Bug D:explicit not overridden、omitted uses recommended、explicit-conflict warn)
- `tests/unit/test_cli_test_disease_format.py`(dev facility:FHIR emit、CIF+FHIR emit、backwards-compat stdout)
- `tests/unit/test_narrative_pass_walk_order.py`(★ Bedrock cache walk order pinning、`_RecordingPass` で group boundary count)

### 5.3 New integration test coverage

- `tests/integration/test_narrative_two_pass.py`(generate 2 file 生成 / narrate byte-identical regen / new version leaves structural / export-fhir current & selector)
- `tests/integration/test_bug_fixes_end_to_end.py`(US H&P zero ja chars in FHIR / nursing doc author=nurse / triage L1 L5 present / -p 100 → 100 persons)
- `tests/integration/test_dev_facility.py`(test-disease full pipeline < 15 sec / deterministic across runs)

### 5.4 e2e golden regeneration strategy

- No compat 前提 → 全 39 goldens `--update-goldens` で一括再生成
- Diff review:
  - manifest.json:`request` 文字列 変化のみ
  - Composition.ndjson:同 count、section content = English fixed(Bug A)
  - DocumentReference.ndjson:34746-8 author = nurse(Bug B)
  - Encounter.ndjson:triage extension で L1/5 present(Bug C)
  - fhir_r4/*.ndjson 数 = same(narrative dir 分離は count に影響しない)
- Golden diff human eyeball review(session 26/27 process 踏襲)

### 5.5 Audit gate 追加(`clinosim/modules/document/audit.py:lift_firing_proof`)

`equality_checks` に 6 追加(既存 25 + AD-65 6 = **31**):

```python
"narrative_pass_populated_narrative_ratio": <float>,   # 1.0(全 stub に narrative fill)
"structural_cif_zero_narrative_content": <bool>,       # True(structural に narrative 混入 0)
"us_admission_hp_zero_ja_chars": <int>,                # 0(Bug A regression)
"nursing_doc_author_is_nurse_ratio": <float>,          # 1.0(Bug B regression)
"triage_levels_1_and_5_ratio_min": <float>,            # > 0.005(Bug C regression)
"explicit_population_respected": <bool>,               # True(Bug D regression)
```

各 gate は `n < 30` WARN 保護、`clinosim audit run` で全 chain 検証。

### 5.6 Bedrock cache walk order test(β-JP-1 forward compat)

`tests/unit/test_narrative_pass_walk_order.py`:base class 経由で walk 順序を pin。LLMNarrativePass 継承時に breaking change 検知。

### 5.7 Migration(no legacy cohort compat)

- Legacy scratchpad cohort(doc_alpha1_* / doc_alpha2_* / imaging_pr1_* / pr1_* / pr3b* etc.)は削除推奨 or 保管(user 判断)
- 新 layout 混在させない(chain 開始時 scope discipline)
- 既存 test fixtures:narrative 前提の少数 fixture JSON を new layout に mechanical replace、structural fixture は影響なし

### 5.8 CI pipeline changes

`.github/workflows/ci.yml` 追加:

```yaml
- name: audit gates
  run: |
    clinosim generate -p 500 --country US -o /tmp/us500
    clinosim generate -p 500 --country JP -o /tmp/jp500
    clinosim audit run --cif-dir /tmp/us500 --cif-dir /tmp/jp500
- name: dev facility smoke test
  run: |
    clinosim test-disease acute_mi --format all -o /tmp/test_mi
    test -f /tmp/test_mi/fhir_r4/Composition.ndjson
    clinosim test-encounter chest_pain_noncardiac --format all -o /tmp/test_cp
    test -f /tmp/test_cp/fhir_r4/Composition.ndjson
```

CI 時間見積:現行 ~15 min → new ~20-25 min。

### 5.9 Test coverage target

| Coverage | Session 27 | AD-65 chain 完了後 |
|---|---|---|
| Unit tests | 1728 pass | ~1780-1790 pass |
| Integration | 27 pass | ~40-45 pass |
| e2e golden | 39 pass | 39 全 regenerate + 3 new = ~42 pass |
| Audit gate equality_checks | 25 | **31** |
| Bug regression gate | 0 | **4**(A/B/C/D)|

Chain 完了時 test suite = **~1900+ pass、regressions 0、audit gate 100% pass**。

### 5.10 Test 実行時間 target

| Suite | 現行 | 目標 |
|---|---|---|
| Unit | ~2 min | ~2.5 min |
| Integration | ~5 min | ~6 min |
| e2e golden | ~8 min | ~10 min |
| Audit sample cohort | N/A | ~5 min(-p 500 × 2) |
| **CI 全体** | ~15 min | ~20-25 min |

## 6. Documentation Updates

### 6.1 更新対象 doc 一覧

| # | Doc | 更新 task | 概算行数 |
|---|---|---|---|
| 1 | `CLAUDE.md` | T_DOC1(chain 中盤)| +25 |
| 2 | `DESIGN.md` | T_DOC2(chain 中盤)| +80 |
| 3 | `clinosim/modules/output/SPEC.md` | T_DOC3(chain 中盤)| +40 |
| 4 | `MODULES.md` | T_DOC4(chain 終盤)| +15 |
| 5 | `clinosim/modules/document/README.md` | T_DOC5 | +60 |
| 6 | `clinosim/modules/output/README.md` | T_DOC5 | +30 |
| 7 | `TODO.md` | T_DOC6(chain 終盤)| +20/-15 |
| 8 | `docs/CONTRIBUTING-modules.md` | T_DOC7(= T11)| +50 |
| 9 | memory `project_session_28_end_state.md` | chain 完了 final | 新規 ~150 |

**Task 集約:** T_DOC1(CLAUDE.md)は AD-65 refactor commit と同時 land、T_DOC2/3 は chain 中盤、T_DOC4-7 は chain 終盤、memory は最終 commit 直前。

### 6.2 `CLAUDE.md` 新 rule 5 個(掲載位置 = "### Data flow & ownership" 末尾)

```markdown
### Two-pass CIF generation invariant(AD-65, 2026-07-02, session 28)

- **CIF は structural + narrative の 2 層 file 分離**:`cif/structural/patients/<enc>.json`
  (構造化データ、Stage 1 で immutable)と `cif/narratives/<version>/documents/<enc>/<doc>.json`
  (narrative、Stage 2 で version 化可能)を **必ず file-level 分離**。inline 混在禁止。
  session 25/26/27 で drift した過去実装から復元、SPEC.md `Stage 2: Narrative Generation`
  節が canonical。
- **`document_enricher`(POST_ENCOUNTER)は `ClinicalDocument` stub のみ生成**:metadata +
  author + encounter binding + `narrative=None`。narrative content(text / sections /
  facts_used)を populate 禁止。populate すると Stage 2 差替時 silent-no-op risk。
  test 上で stub 直後 `doc.narrative is None` を assert。
- **narrative は post-simulation two-pass で生成**:`TemplateNarrativePass.run(cif_dir,
  version_id)` は structural CIF を read → patient profile + labs + conditions +
  medications + scenario_spine を input として narrative を導出 →
  `narratives/<version>/documents/<enc>/<doc>.json` 書出。simulation loop 中の
  narrative content 生成禁止。α-min-1 Task 15 で SPEC.md 元設計から drift、
  AD-65(session 28)で復元。
- **`NarrativePass` walk 順序は (doc_type, language) group 単位**:同 prompt prefix を
  共有する batch 単位で patient を逐次処理 → Bedrock prompt cache(5 分 TTL)hit rate
  最大化。LLMNarrativePass(β-JP-1)は同 base class を継承 = drop-in で cache-friendly。
  walk order invariant は `tests/unit/test_narrative_pass_walk_order.py` で pin。
- **FHIR builders は `doc.narrative.sections` / `doc.narrative.text` 経由必須**:
  `ClinicalDocument` の flat field(`doc.text` / `doc.sections`)は AD-65 で削除、
  wrapper `ClinicalDocumentNarrative` に集約。`CIFReader(narrative_version="current")`
  が structural + narrative を merge して `doc.narrative` を fill、builders は
  wrapper 経由のみ。
```

### 6.3 `DESIGN.md` の 新 ADR = AD-65

**Context:**
- clinosim の initial architecture(`clinosim/modules/output/SPEC.md`)は 3 段階 pipeline を定義:structural CIF Stage 1 immutable / narrative Stage 2 separate version dir / Stage 3 adapter merge。
- α-min-1 Task 15(commit `2c09b6a099`)で legacy narrative subsystem(`document_generator.py` 951 行、`narrative_generator.py` 205 行)削除し、narrative 生成を `document_enricher` に統合。当時の Stage 1 default emission gap 閉鎖には正しかったが、long-term Stage 2 差替 architecture として premature 削除、SPEC.md Stage 2 節と drift。
- Session 27 末 Clinical Integrity review で 3 Critical narrative bugs 発覚、inline pattern では full cohort regen 必要 = dev cycle 破綻。
- User 明示指摘(session 27→28):元設計は構造化 CIF と narrative CIF は別ファイル分離 = SPEC.md 元設計への restoration。

**Decision:**
1. `ClinicalDocument` を stub + `narrative: ClinicalDocumentNarrative | None` field に refactor
2. Two-pass CIF generation pipeline を復元(SPEC.md 元設計 と 完全一致)
3. `clinosim narrate` verb 復活(template mode fallback あり、LLM 実 invocation は β-JP-1)
4. Bedrock prompt cache 対応の walk 順序契約 = `(doc_type, language)` group 単位 serial を `NarrativePass` base class で確定
5. `NarrativeContext` に 3 enhancement 追加:NarrativeSpine / materialized_facts / section_facts
6. Silent CLI override(Bug D)修正
7. Dev iteration facility(`test-disease --format` + `narrate` verb)追加

**Consequences:**
- narrative bug 検証 = `narrate --tasks <task>` 30 秒(structural = `test-disease --format all` 10 秒)= dev cycle 100x 高速化
- FHIR builder は `doc.narrative.*` 経由必須 = single source of truth
- β-JP-1 で LLMNarrativePass が base class + Bedrock walk order に drop-in
- 既存 e2e goldens 39 file 全 regenerate
- CLAUDE.md AD-65 rules 5 個追加、次 session drift 防止

**Alternatives considered:**
- Inline populate + writer split(Approach A、session 28 初期案):silent-no-op risk 小、Stage 2 差替対称性弱 → 却下
- Explicit two-pass without inline generate:UX 変化大 → 却下(inline default 選択)
- Wrapper なし flat field 継続 + physical split:defense in depth 弱 → 却下

**Related ADRs:** AD-30 / AD-55 / AD-56 / AD-60 / AD-63 / AD-64

### 6.4 `clinosim/modules/output/SPEC.md` の 2 節追記

**冒頭に "## Current Implementation Status":**

| SPEC section | Status | Notes |
|---|---|---|
| Stage 1: CIF Writer | ✅ IMPLEMENTED | `cif_writer.py`、structural only |
| Stage 2: Narrative Generation | ✅ IMPLEMENTED(AD-65)| `document/narrative/passes.py:TemplateNarrativePass` |
| Stage 3: Format Adapters | ✅ IMPLEMENTED | `fhir_r4_adapter.py`(via `cif_reader.py`)、`csv_adapter.py` |
| Folder structure | ✅ MATCHES SPEC | `cif/{structural,narratives/{template,<v>}}` |
| CIFReader | ✅ IMPLEMENTED | AD-65 で `cif_reader.py` 新規、`narrative_version="current"` selector |

**章末に "## Change Log":** AD-65 restoration + 過去主要変更を chronological entry。

### 6.5 `MODULES.md` document module section revise

`document` module を 2 role(enricher + narrative_pass)に分離記述、23 modules 一覧に narrative_pass = POST_SIMULATION stage 新規追加。

### 6.6 `clinosim/modules/document/README.md`

3 節追加:Architecture(2-pass 図)/ LLMNarrativeGenerator Roadmap(β-JP-1)/ Bug fix log。

### 6.7 `docs/CONTRIBUTING-modules.md` に Regen scope matrix

Regen scope matrix + 3 使用例(Case 1 template bug / Case 2 structural bug / Case 3 FHIR bug)を追加。開発者オンボード + 忘却防止。

### 6.8 `TODO.md` の update

- 削除:Stage 2 LLM 統合(β-JP-1 chain defer)従来 entry
- 追加:β-JP-1 = LLMNarrativePass 実装 + Bedrock cache 実測 verify + facts_used gate + docStatus 4 状態 + AI-assisted extension + section-level LLM replacement
- 追加:Post-AD-65 fixture library(α-min-2c or β-2 chain)

### 6.9 memory `project_session_28_end_state.md`(chain 完了時)

Session 27 format 継承。完了事項 / Gap closure verified / 特筆事項 / 次 session 起点 / Deferred TODO を記載。

### 6.10 CLAUDE.md rule 追加のタイミング

**T_DOC1(chain 序盤、T1 と同 commit)**:AD-65 rules を rule と実装同時 land = drift 発生前に固定。

### 6.11 Documentation verification

Chain 完了直前 sanity check:

```bash
# Every AD-65 rule in CLAUDE.md is grep-able from at least 1 source file.
# All grep targets are English tokens intentionally.
for rule in "TemplateNarrativePass" "ClinicalDocumentNarrative" \
            "cif/narratives" "narrate --provider" "narrative_version"; do
    grep -rn "$rule" clinosim/ tests/ docs/ CLAUDE.md DESIGN.md MODULES.md \
        || echo "MISSING: $rule"
done
```

## Appendix A: Complete SDD Task Breakdown

**単一 canonical task table**(全 chain 実行 order、各 task に依存 phase 記載):

| # | Task | Category | Phase | Section 参照 |
|---|---|---|---|---|
| T1 | `ClinicalDocumentNarrative` wrapper + `ClinicalDocument` stub refactor + `NarrativeVersionManifest` 追加 + CLAUDE.md AD-65 rules 5 個追加(同 commit) | Architecture + Doc | 1 | 2, 6.2 |
| T2 | `cif_writer.py` structural-only(narrative content strip)+ `_narrative_to_text` 削除 | Architecture | 1 | 3 |
| T3 | `passes.py`(NarrativePass base + TemplateNarrativePass)+ `fact_extractor.py` + `section_extractor.py` + `scenario_spine.py` 追加 | Architecture | 1 | 3.3, 3.2 |
| T4 | `cif_reader.py` + `_fhir_composition.py` / `_fhir_documents.py` を wrapper 経由に refactor | Architecture | 1 | 3.4 |
| T5 | `narrate` CLI verb 復活 + `export-fhir --narrative-version` + `generate` auto-invoke | Architecture | 1 | 3.5, 3.6 |
| T6 | `ENRICHER_SEED_OFFSETS["narrative_template"] = 0x4e54` 追加 + determinism unit test | Architecture | 1 | 3.7 |
| T7 | `DESIGN.md` AD-65 ADR 追加 | Doc | 2 | 6.3 |
| T8 | `SPEC.md` Current Implementation Status + Change Log 追加 | Doc | 2 | 6.4 |
| T9 | Bug A `_pick_localized` helper + 8 builder refactor + unit test | Bug A | 3 | 4.1 |
| T10 | Bug A Disease YAML en field audit + CI script + missing en 補填 | Bug A | 3 | 4.1 |
| T11 | Bug A integration test(US p=100 zero ja chars)+ audit gate | Bug A | 3 | 4.1, 5.5 |
| T12 | Bug B `_pick_document_author` helper + 4 branch refactor + `NURSING_LOINCS` 定数 + unit + integration + audit gate | Bug B | 3 | 4.2, 5.5 |
| T13 | Bug C diagnosis(severity distribution 実測 script)| Bug C | 3 | 4.3 |
| T14 | Bug C fix(T13 依存)+ integration test + audit gate | Bug C | 3 | 4.3, 5.5 |
| T15 | Bug D CLI(argparse SUPPRESS)+ config(catchment_population Optional)+ engine.py sentinel 撤廃 + unit + integration + audit gate | Bug D | 3 | 4.4, 5.5 |
| T16 | `test-disease` に `--format cif\|fhir-r4\|all` + `-o` 追加 + unit test | Dev facility | 4 | 4.5 |
| T17 | `test-encounter` に同拡張 + unit test | Dev facility | 4 | 4.5 |
| T18 | `docs/CONTRIBUTING-modules.md` に Regen scope matrix + 使用例 3 個追加 | Doc / Dev facility | 4 | 6.7 |
| T19 | e2e goldens 39 全 regenerate + human eyeball review | Test | 5 | 5.4 |
| T20 | `MODULES.md` document module 2 role 記述 + narrative_pass 一覧追加 | Doc | 6 | 6.5 |
| T21 | `clinosim/modules/document/README.md` + `output/README.md` 3 節追加 | Doc | 6 | 6.6 |
| T22 | `TODO.md` update(β-JP-1 + α-min-2c fixture library entry)| Doc | 6 | 6.8 |
| T23 | memory `project_session_28_end_state.md` 作成 + PR body draft | Doc / memory | 6 | 6.9 |

**合計 SDD tasks: 23**(architecture 6 + doc 7 + bug fix 7 + dev facility 2 + test 1)。

Phase mapping:
- **Phase 1**(T1-T6)= Architecture + CLAUDE.md rule land(rule と実装同時 land = drift 防止)
- **Phase 2**(T7-T8)= Doc mid(DESIGN.md AD-65 + SPEC.md sync)
- **Phase 3**(T9-T15)= Bug fixes(A/B/C/D)
- **Phase 4**(T16-T18)= Dev facility
- **Phase 5**(T19)= Test regeneration
- **Phase 6**(T20-T23)= Doc final + session memory

## Appendix B: Chain execution flow

```
┌───────────────────────┐
│  Chain start          │
│  master 486eea6ddf    │
└─────────┬─────────────┘
          │
          ▼
┌──────────────────────────────────────────┐
│ Phase 1: Architecture(T1-T6)            │
│  - T1 Wrapper + stub refactor +          │
│       CLAUDE.md AD-65 rules(同 commit)  │
│  - T2 cif_writer.py structural-only      │
│  - T3 passes.py + fact/section/spine     │
│  - T4 cif_reader.py + FHIR builder ref   │
│  - T5 narrate verb + generate auto       │
│  - T6 determinism setup + walk order test│
└─────────┬────────────────────────────────┘
          │
          ▼
┌──────────────────────────────────────────┐
│ Phase 2: Doc mid(T7-T8)                 │
│  - T7 DESIGN.md AD-65 ADR                │
│  - T8 SPEC.md status + change log        │
└─────────┬────────────────────────────────┘
          │
          ▼
┌──────────────────────────────────────────┐
│ Phase 3: Bug fixes(T9-T15)              │
│  - T9-T11 Bug A(H&P locale)             │
│  - T12   Bug B(nurse author)            │
│  - T13-T14 Bug C(triage L1/5)           │
│  - T15   Bug D(CLI silent)              │
│  ★ audit gate 6 個は T11/T12/T14/T15 内  │
└─────────┬────────────────────────────────┘
          │
          ▼
┌──────────────────────────────────────────┐
│ Phase 4: Dev facility(T16-T18)          │
│  - T16 test-disease --format             │
│  - T17 test-encounter --format           │
│  - T18 CONTRIBUTING regen scope matrix   │
└─────────┬────────────────────────────────┘
          │
          ▼
┌──────────────────────────────────────────┐
│ Phase 5: Test regeneration(T19)         │
│  - T19 e2e goldens 39 全 regenerate      │
└─────────┬────────────────────────────────┘
          │
          ▼
┌──────────────────────────────────────────┐
│ Phase 6: Doc final(T20-T23)             │
│  - T20 MODULES.md revise                 │
│  - T21 module READMEs                    │
│  - T22 TODO.md update                    │
│  - T23 memory project_session_28_end +   │
│         PR body                          │
└─────────┬────────────────────────────────┘
          │
          ▼
┌───────────────────────┐
│ Chain end             │
│ PR open → adv-1 later │
└───────────────────────┘
```

## Appendix C: Risks + Mitigation

| Risk | Mitigation |
|---|---|
| `document_enricher` stub 化で narrative populate site が漏れ、Stage 2 未実行 CIF が silent 発行 | Audit gate `narrative_pass_populated_narrative_ratio = 1.0` + `structural_cif_zero_narrative_content = True` |
| FHIR builder が `doc.narrative is None` を silent 通過し empty Composition emit | `_bb_compositions` / `_bb_document_references` で explicit warn log、integration test で empty resource 検出 |
| e2e golden regenerate 時に unintended content 変化を human review が見逃し | Golden diff review checklist:manifest / Composition / DocumentReference / Encounter の 4 資源 diff を必ず確認 |
| Bug C の root cause 候補 (i) が正しい場合、46 ED condition YAML audit で clinical validation が scope 外 | T6 diagnosis で候補確定後、候補 (ii) fix と judgment。scope 内 fix 可能な最小 hit のみ scope に |
| Bedrock walk order 契約が LLMNarrativePass 実装時に破綻 | Base class test で walk order 契約を pin、β-JP-1 で LLM 実装 fail-fast |
| Session 27 で発覚した Ambulatory DM 患者に DM 薬なし / SOAP 100% generic 等の Important issues が同時解決を求められる | Scope discipline:本 chain は 3 Critical + Bug D + facility に限定、Important issues は α-min-2c / β-JP-1 defer |

## Appendix D: References

- `docs/design-notes/2026-06-30-tier1-document-and-event-density-master-plan.md` §3(narrative architecture)
- `clinosim/modules/output/SPEC.md` §Stage 2: Narrative Generation
- `docs/superpowers/specs/2026-07-01-tier1-3-document-density-alpha-min-1-design.md`
- `docs/superpowers/specs/2026-07-01-tier1-3-document-density-alpha-min-2-design.md`
- `docs/reviews/2026-07-01-tier1-3-document-density-alpha-min-2-dqr.md`
- memory `project_session_27_end_state.md`(3 Critical bugs findings)
- memory `project_document_density_master_plan.md`
- memory `feedback_scope_discipline.md`
- memory `feedback_cif_to_fhir_no_drop.md`
- memory `feedback_xhigh_review_lessons.md`
- Task 15 deletion commit `2c09b6a099`(reference 前後 diff)
