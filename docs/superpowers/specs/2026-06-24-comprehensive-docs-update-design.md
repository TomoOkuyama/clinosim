# Comprehensive Documentation Update — clinosim Module Map + Module README Consumers + Doctrine Docs

**Date**: 2026-06-24
**Author**: Tomo Okuyama (with Claude Opus 4.7)
**Status**: APPROVED — ready for plan
**Series context**: G4 (originally "doctrine docs") **absorbed and expanded** into this comprehensive docs PR. Original 4-PR series → 5 PR series; the original G4 scope (typed field vs extensions decision tree) is folded in.
**Predecessor**: PR2 (G2 SDOH integrity, master `5189857e` merged)
**Successors**: PR3 (G3 `_fhir_observations.py` 31KB split) → device + HAI feature work

---

## 1. Motivation

A documentation audit (brainstorming session 15) of clinosim's 22 module READMEs + 10 top-level docs surfaced critical onboarding-integrity gaps despite high per-module completeness:

| Audit finding | Status |
|---|---|
| 22/22 module READMEs have `## Dependencies` section | ✓ 100% |
| 22/22 module READMEs have `## Consumers` (reverse dependency) section | **0%** — critical gap |
| Top-level "Module Map" doc showing all 22 modules at a glance | **Missing** |
| Scenario / medication flag central doc (causes_X / on_warfarin) | **Missing** |
| `output/README.md` documents the `register_bundle_builder` / `register_output_adapter` extension pattern | **Missing** — critical for FHIR contributors |
| `.github/TEMPLATE_MODULE_README.md` for new modules | **Missing** |
| Language consistency across module READMEs | 21/22 (sdoh has English line 1) |
| 7 weak READMEs lacking data-structure sections | disease / encounter / order / facility / procedure / validator / population |

User requirement (2026-06-24): *"ドキュメントを網羅的に更新して。初めて見る人にとってわかりやすいようにして。それぞれのモジュールが、どのモジュールと、あるいはどのファイルと関連しているかも記述するように。"*

Translation: **comprehensive update**, **first-time viewer friendly**, **describe each module's relationships to other modules / files**.

Map of finding → PR action:

| Finding | PR action |
|---|---|
| No reverse-dependency visibility | Add `## Consumers` section to all 22 module READMEs |
| No module-map single source | Create `MODULES.md` (top-level) |
| Scenario flag knowledge scattered | Create `SCENARIO_FLAGS.md` (top-level) |
| Output module extension pattern undocumented | Add Extensibility section to `output/README.md` |
| No template for new modules | Create `.github/TEMPLATE_MODULE_README.md` |
| Language inconsistency | Fix `sdoh/README.md` line 1 |
| Weak READMEs (7 files) | Add 「データ構造」section to each |
| Typed-field-vs-extensions decision unclear (G4 absorbed) | Extend `CONTRIBUTING-modules.md` existing section into decision-tree format |

### Scope decisions (from brainstorming)

| Decision | Choice | Rationale |
|---|---|---|
| Scope tier | **B (Standard)** | Satisfies "網羅的" requirement; byte-diff not needed (pure docs); type-consolidation refactor (Tier C) is code work and belongs in a separate PR |
| G4 disposition | **Absorb into this PR** | Original G4 was doctrine docs; this PR is its superset. PR series goes from 4 to 5 with G4 merged in |
| Type definitions consolidation (7 modules using engine.py types) | **Defer to separate PR** | This is code refactor with byte-diff risk; should not be mixed with pure docs work |
| identity enabled gate registry simplification (originally G4) | **Defer to TODO** | Code refactor, separate concern from docs |

### Hard guarantee

This is a **pure documentation update**. No code changes, no FHIR/CSV output changes, no byte-diff verification needed. The existing 704 unit + integration tests should remain green simply because no code paths are touched.

---

## 2. Architecture

```
                Before this PR
                ──────────────
   22 module READMEs (each has Dependencies, none has Consumers)
   10 top-level docs (no module-map; no scenario-flag central doc;
                       no contributor template; weak FHIR builder extensibility doc)

                After this PR
                ─────────────
   ┌────────────────────────────────────────────────────────────────┐
   │ MODULES.md (new, top-level)                                    │
   │   - 3-layer architecture diagram                               │
   │   - 22-module inventory table                                  │
   │   - dependency tree                                            │
   │   - 3 typical call chains                                      │
   │   - "Adding a new module" 5-step quick-start                   │
   └────────────────────────────────────────────────────────────────┘
   ┌────────────────────────────────────────────────────────────────┐
   │ SCENARIO_FLAGS.md (new, top-level)                             │
   │   - All current flags table                                    │
   │   - Helper architecture (scenario / medication)                │
   │   - Adding a new flag 5-step                                   │
   └────────────────────────────────────────────────────────────────┘
   ┌────────────────────────────────────────────────────────────────┐
   │ .github/TEMPLATE_MODULE_README.md (new)                        │
   │   - Standard sections in canonical order                       │
   │   - Used for all future module READMEs                         │
   └────────────────────────────────────────────────────────────────┘
   ┌────────────────────────────────────────────────────────────────┐
   │ Existing 22 module READMEs (modified)                          │
   │   - Add `## Consumers` section to each                         │
   │   - 7 weak READMEs gain `## データ構造` section                  │
   │   - sdoh/README.md line 1 language fix                          │
   │   - output/README.md gains Extensibility section               │
   └────────────────────────────────────────────────────────────────┘
   ┌────────────────────────────────────────────────────────────────┐
   │ Existing top-level docs (modified)                             │
   │   - README.md / README.ja.md: add MODULES.md cross-ref         │
   │   - DESIGN.md AD-56: cross-ref to MODULES.md                   │
   │   - CLAUDE.md: add Quick Navigation section                    │
   │   - CONTRIBUTING-modules.md: typed-field-vs-extensions         │
   │     decision tree (G4 absorbed)                                │
   └────────────────────────────────────────────────────────────────┘
```

**Invariants preserved**:
- No code changes
- No FHIR / CSV output changes
- 704 unit + integration tests remain green
- Existing docs content stays accurate (additions only, no rewrites that change meaning)

---

## 3. Component 1: `MODULES.md` (new top-level)

**Size target**: ~700 words. Purpose: first file a new contributor reads to understand "what is clinosim made of?"

### Structure

```markdown
# clinosim Module Map

## このドキュメントの読み方

| Goal | Read |
|---|---|
| 初めて見る | top to bottom |
| 特定モジュールを探す | "Module Inventory" table |
| 既存コードを変更する | "Typical Change Impact" |
| 新モジュールを足す | `docs/CONTRIBUTING-modules.md` + `.github/TEMPLATE_MODULE_README.md` |

## TL;DR

clinosim は合成 EHR データシミュレータ。22 module を 3 layer に組織化:

1. **Foundation** — `clinosim/codes/` + `clinosim/locale/` + `clinosim/types/` (no clinosim dependencies)
2. **Simulation** — physiology → observation → order → clinical_course → encounter
3. **Output** — `clinosim/modules/output/` adapters consume CIF, emit FHIR / CSV

データ流: `population → patient activation → encounter loop → CIF → output adapter`

## レイヤー構造

[ASCII / mermaid diagram with all 3 layers + 22 modules placed]

## Module Inventory (22)

| Module | 役割 | Layer | 主 Dependencies | 主 Consumers | Impact tier |
|---|---|---|---|---|---|
| codes | 国際コード体系 (LOINC/SNOMED/ICD/RxNorm/JLAC10/CVX) lookup | foundation | (none) | 全 module | foundational |
| locale | 国別文化データ (names, addresses, reference ranges) | foundation | (none) | patient/observation/output | foundational |
| physiology | 患者生理学状態 + lab/vital derivation | simulation | codes | observation, simulator/* | core |
| observation | lab/vital result generation | simulation | physiology, codes, locale | simulator/*, output | core |
| ... (22 行) | | | | | |

## Dependency Tree (text)

[ASCII tree]

## Typical Call Chains (3 examples)

### 1. Population → patient → encounter
[ASCII flow with actual function names]

### 2. Lab derivation
[ASCII flow: physiology state → derive_lab_values → order → MAR]

### 3. FHIR export
[ASCII flow: CIF → output/fhir_r4_adapter → register_bundle_builder]

## Typical Change Impact

| Change | Affects | Notes |
|---|---|---|
| Add scenario flag | physiology + 4 call sites (inpatient Pass-1, unknown-cond, emergency, outpatient) | See `SCENARIO_FLAGS.md` |
| Add code system | codes/data/ + locale code_mapping (2 countries) | See `clinosim/codes/README.md` |
| Add FHIR resource | New `_fhir_*.py` + `register_bundle_builder` (NO core edit) | See `clinosim/modules/output/README.md` |
| Add new module | TEMPLATE_MODULE_README.md + CONTRIBUTING-modules.md | |

## Adding a New Module (5-step quick-start)

1. Decide Base vs opt-in Module → `docs/CONTRIBUTING-modules.md` 「判断: Base か Module か」
2. Copy `.github/TEMPLATE_MODULE_README.md` to `clinosim/modules/<name>/README.md`
3. Create files per template: `__init__.py` + `engine.py` + `reference_data/*.yaml`
4. Register in `clinosim/simulator/seeding.py:ENRICHER_SEED_OFFSETS` if enricher
5. Update `MODULES.md` inventory table

## Where to Read Next

| Doc | Purpose |
|---|---|
| `README.md` / `README.ja.md` | User-facing overview |
| `DESIGN.md` | Architecture + ADR table (55+ entries) |
| `CLAUDE.md` | AI agent rules + project conventions |
| `docs/CONTRIBUTING-modules.md` | Module-author playbook (HOW-TO) |
| `SCENARIO_FLAGS.md` | Scenario / medication flag reference |
| Module `README.md` | Per-module API + Dependencies + Consumers |
```

---

## 4. Component 2: `SCENARIO_FLAGS.md` (new top-level)

**Size target**: ~400 words. Purpose: single source of truth for all scenario + medication flags that route through `derive_lab_values`, preventing J5-style wiring defects.

### Structure

```markdown
# Scenario & Medication Flags

## What are these?

clinosim's `physiology.derive_lab_values()` accepts boolean flags that lift
specific lab values at derive time. Disease YAMLs declare scenario flags
(`causes_X`); patient context provides medication flags (`on_X`). All flags
follow the BNP-pattern surgical principle (AD-57): no `PhysiologicalState`
mutation, formula-only override.

## All current flags

| Flag | Type | Set in | Read in | Effect |
|---|---|---|---|---|
| `myocardial_injury` | scenario (alias: `causes_myocardial_injury`) | `acute_mi.yaml` | `derive_lab_values` | Troponin_I → ACS-grade (~10-100 ng/mL); CK_MB elevation |
| `causes_vte` | scenario | `pulmonary_embolism.yaml`, `deep_vein_thrombosis.yaml`, `cerebral_infarction.yaml` | `derive_lab_values` | D_dimer → VTE-positive (>4 μg/mL FEU) |
| `on_warfarin` | medication | `patient.current_medications` (chronic AF/post-VTE) OR in-hospital warfarin order ≥ 3 days | `derive_lab_values` | PT_INR → therapeutic 2.5 + comorbidity lift |

## Helper architecture

Two sibling helpers in `clinosim/modules/physiology/engine.py`:

```python
scenario_flags_from_protocol(protocol)
  → {"myocardial_injury": bool, "causes_vte": bool}

medication_flags_from_context(patient, medication_orders, admission_date, current_day)
  → {"on_warfarin": bool}
```

Call sites merge both dicts:

```python
flags = {
    **scenario_flags_from_protocol(protocol),
    **medication_flags_from_context(patient, ...),
}
true_labs = derive_lab_values(state, ..., **flags)
```

**4 call sites** all using this pattern:
- `simulator/inpatient.py:563` (Pass-1 lab loop)
- `simulator/inpatient.py:1701` (unknown-condition site, chronic-only)
- `simulator/emergency.py:126` (ED, chronic-only)
- `simulator/outpatient.py:152` (outpatient, chronic-only)

## Adding a new flag (5-step)

1. Identify type:
   - Disease-driven (e.g. `causes_X`) → scenario flag → `scenario_flags_from_protocol`
   - Medication-driven (e.g. `on_X`) → medication flag → `medication_flags_from_context`
2. Extend the appropriate helper's return dict
3. Set the flag at its source (disease YAML or detection logic)
4. Add `<flag_name>: bool = False` kwarg to `derive_lab_values`
5. Implement formula change in `derive_lab_values`

**NEVER** add `flag=value` directly at a call site — J5 prevention (see CLAUDE.md "AD-55 enricher patterns"). The helper is the single edit point so adding a new flag automatically reaches all 4 sites through the `**flags` splat.

## DOAC exclusion (Phase 2b decision)

For PT_INR, DOAC drugs (apixaban / rivaroxaban / edoxaban / dabigatran) are intentionally **NOT detected**. Clinical practice does not monitor INR for DOAC; modeling DOAC INR lift would be clinically misleading. See PR #82 (Phase 2b) for rationale.

## 関連

- `DESIGN.md` AD-57 (BNP-pattern surgical) / AD-59 (per-order sub-rng) / AD-56 (enricher registry)
- `CLAUDE.md` "AD-55 enricher patterns"
- `docs/CONTRIBUTING-modules.md`
```

---

## 5. Component 3: `.github/TEMPLATE_MODULE_README.md` (new)

Boilerplate that future module authors copy. Captures the canonical section ordering observed in best-in-class READMEs (observation, identity, sdoh after PR2).

### Template content

```markdown
# [Module Title] — [JP one-line description]

## 概要 / 役割

[2-3 sentences: what does this module do, why does it exist]

## 設計原則 (該当時のみ)

| Principle | Source |
|---|---|
| 例: AD-16 deterministic | ADR |

## ディレクトリ構造

\```
clinosim/modules/<name>/
  __init__.py            # public API
  engine.py              # core logic / loaders
  reference_data/*.yaml  # data-driven definitions
  README.md
\```

## API Reference

[Public functions exported via __init__.py. Show signature + 1-line description.]

## データ構造 (該当時)

- `MyType` defined in `clinosim/types/<name>.py`
  - `field: type` — 意味

## Dependencies

| Dependency | Why |
|---|---|
| `clinosim/types/<name>` | data types |
| `clinosim/codes/` | code system display lookups |
| `clinosim/locale/<country>/` | locale-specific data |
| [other module] | [reason — see DESIGN.md ADR] |

## Consumers

| Caller | How it uses this module | Impact when changing |
|---|---|---|
| `simulator/inpatient.py:NNN` | calls `X()` at Y location | high (core loop) |
| `modules/output/_fhir_<X>.py` | reads `<data type>` | medium (FHIR builder) |

## 拡張ガイド

[How to add a new <thing> to this module — link to CONTRIBUTING-modules.md]

## 関連

- `DESIGN.md` ADxx
- `CONTRIBUTING-modules.md` セクション
- 関連モジュール: [list]
- 関連 spec / plan: [docs/superpowers/specs/...]
```

---

## 6. Component 4: 22 module README に `## Consumers` セクション追加

**Method**: For each of 22 modules, run `grep -rn "from clinosim.modules.<name>\|import clinosim.modules.<name>" clinosim/ tests/ 2>&1` to find call sites, then list them with impact tier.

**Format** (consistent across all 22):

```markdown
## Consumers

| Caller | How | Impact |
|---|---|---|
| `simulator/inpatient.py:563-571` | `derive_lab_values` (Pass-1) | core |
| `simulator/emergency.py:126` | `derive_lab_values` (ED admit) | core |
| ... | ... | ... |
```

**Impact tier** (3 levels):
- `core` — affects main simulation loop or all encounters
- `medium` — affects specific feature (FHIR builder for X resource, specific lab path)
- `guard` — test only (no runtime impact)

**Effort per module**: ~10-15 minutes (grep + verify + write table).
**Total effort for 22 modules**: ~4-5 hours.

**Batching strategy**: 4 sub-batches of ~5-6 modules each (1 commit per batch).

---

## 7. Component 5: 7 weak READMEs にデータ構造セクション追加

Target READMEs (no `## データ構造` section currently):

- `disease/README.md`
- `encounter/README.md`
- `order/README.md`
- `facility/README.md`
- `procedure/README.md`
- `validator/README.md`
- `population/README.md`

**Format**:

```markdown
## データ構造

主要型 (`clinosim/types/<name>.py` または `engine.py` 内 dataclass):

| Type | 場所 | Key fields | 用途 |
|---|---|---|---|
| `DiseaseProtocol` | `disease/protocol.py` (Pydantic BaseModel) | `disease_id`, `chief_complaint`, `icd_codes`, `course_archetypes`, `outcome_benchmarks` | disease YAML load 結果型 |
| ... | | | |

*注: 一部 type は engine.py 内に残存 (MOD-2..6, TYP-2 既知負債)。* `clinosim/types/<name>.py` への migration は PR_C (type consolidation, 別 PR で計画) を参照。
```

---

## 8. Component 6: `output/README.md` Extensibility セクション追加

```markdown
## 拡張方法 (Extensibility)

### 新しい FHIR リソースを追加する (AD-56)

`_BUNDLE_BUILDERS` を直接編集しない。新規 builder を `register_bundle_builder()` で登録します:

\```python
# clinosim/modules/output/_fhir_my_resource.py
from clinosim.modules.output._fhir_common import BundleContext

def _build_my_resource(ctx: BundleContext) -> list[dict]:
    return [{"resourceType": "MyResource", ...}]
\```

`fhir_r4_adapter.py` で import + `_BUNDLE_BUILDERS.append(_build_my_resource)` (将来 entry-point discovery 化予定)。

### 新しい出力フォーマットを追加する (AD-58)

`register_output_adapter(MyAdapter)` で OutputAdapter サブクラスを登録 → CLI `--format` が自動拡張:

\```python
# clinosim/modules/output/<my_format>_adapter.py
from clinosim.modules.output.adapter import OutputAdapter, register_output_adapter

class MyAdapter(OutputAdapter):
    format_id = "my_format"
    description = "..."
    subdir = "my_format"
    def convert(self, cif_dir: str, output_dir: str, country: str) -> None:
        ...

register_output_adapter(MyAdapter)
\```

詳細は `docs/CONTRIBUTING-modules.md` 「拡張点の使い方」セクション参照。
```

---

## 9. Component 7: `sdoh/README.md` 言語統一 fix

Line 1 currently English. Change to Japanese to match the project convention (Module READMEs are JP with English technical terms per CLAUDE.md).

---

## 10. Component 8: `CONTRIBUTING-modules.md` typed-field-vs-extensions decision tree (G4 absorbed)

Existing section "## CIF への書き込み: Base か extensions か" (around line 142) is currently a 4-line bullet list. Expand into decision-tree format:

```markdown
### CIF への書き込み: Base か extensions か (decision tree)

判定フロー:

1. **すべての EHR で必須のデータか?**
   - YES → 質問 2 へ
   - NO  → `extensions["module_name"]` (opt-in module data)
2. **将来削除しないコアフィールドか?**
   - YES → 質問 3 へ
   - NO  → `extensions`
3. **複数モジュール / FHIR builder が参照するか?**
   - YES → `CIFPatientRecord` typed field
   - NO  → `extensions`

決定 matrix:

| | typed field | extensions |
|---|---|---|
| Always-on Base data | ✓ | |
| Opt-in module data | | ✓ |
| 共通 core EHR field | ✓ | |
| Theme-specific | | ✓ |
| 例 | `immunizations` / `family_history` / `code_status` / `care_level` | `nursing` extensions (always-on but specialized) |
| Persistence | `asdict` で完全シリアライズ | dict、explicit シリアライズ |

**例外明文化 (TYP-4)**: always-on Base enricher で typed field を使ってよい (例 `nursing_risk_assessments`)。**新規 opt-in module は必ず `extensions[<module>]` を使う**。

> **PR2 教訓**: data-only module variant (`modules/sdoh/`) は **データを CIF に書かない** — patient activator が `PatientProfile.smoking_status` 等の既存 field を更新するため、本質的に Base data。新モジュールで CIF 書き込みが不要なら、この判定フローはスキップ。
```

---

## 11. Component 9: cross-reference 整備

### `README.md` / `README.ja.md`

「Project structure」または相当セクションに module map link 追加:

```markdown
## Module Map

For a single-page overview of all 22 modules, their dependencies, and typical call chains, see [`MODULES.md`](MODULES.md).
```

### `DESIGN.md` AD-56 entry

PR_docs cross-reference 追加:

```
... **PR_docs 2026-06-24 comprehensive documentation update** added `MODULES.md` (top-level module map with 22-module inventory + dependency tree + typical call chains), `SCENARIO_FLAGS.md` (central reference for scenario + medication flags routed through `derive_lab_values`), `.github/TEMPLATE_MODULE_README.md` (standardized module README template), and "Consumers" sections to all 22 module READMEs for reverse-dependency visibility.
```

### `CLAUDE.md`

Quick Navigation section at the top (after "Project overview"):

```markdown
## Quick navigation

| Looking for | Read |
|---|---|
| Module overview | [`MODULES.md`](MODULES.md) |
| Scenario / medication flags | [`SCENARIO_FLAGS.md`](SCENARIO_FLAGS.md) |
| Architecture / ADR | [`DESIGN.md`](DESIGN.md) |
| Module author HOW-TO | [`docs/CONTRIBUTING-modules.md`](docs/CONTRIBUTING-modules.md) |
| New module template | [`.github/TEMPLATE_MODULE_README.md`](.github/TEMPLATE_MODULE_README.md) |
| Roadmap | [`TODO.md`](TODO.md) |
```

### `CONTRIBUTING-modules.md`

冒頭に MODULES.md と TEMPLATE への link 追加:

```markdown
> **新規モジュール作成時**: `.github/TEMPLATE_MODULE_README.md` をコピーして開始してください。全 22 module の俯瞰は [`MODULES.md`](../MODULES.md) を参照。
```

---

## 12. Test strategy

- **No new tests required** (pure docs, no code paths touched)
- **Regression check**: `pytest tests/unit/ tests/integration/ -x -q` must remain green (704 baseline)
- **byte-diff**: NOT required (no code, no FHIR output changes)
- **Manual review**: each cross-reference link verified (e.g., `MODULES.md` link from `README.md` actually resolves)

---

## 13. Plan task breakdown

1. **`MODULES.md`** 新規作成 (top-level, 22-module inventory + dependency tree + 3 typical call chains + 5-step quickstart)
2. **`SCENARIO_FLAGS.md`** 新規作成 (top-level, all flags table + helper architecture + 5-step new-flag guide)
3. **`.github/TEMPLATE_MODULE_README.md`** 新規作成 (standardized template, canonical section order)
4. **`output/README.md`** Extensibility section 追加 (register_bundle_builder + register_output_adapter)
5. **`sdoh/README.md`** line 1 言語 fix (English → Japanese)
6. **7 weak READMEs** にデータ構造セクション追加 (disease/encounter/order/facility/procedure/validator/population)
7. **Batch A: 22 module READMEs に Consumers 追加 — 6 module** (codes/locale/types/identity/sdoh/care_level の比較的小さなもの) (※ codes と locale は package-level だが同様)
8. **Batch B: 22 module READMEs に Consumers 追加 — 6 module** (immunization/family_history/code_status/microbiology/nursing/clinical_course)
9. **Batch C: 22 module READMEs に Consumers 追加 — 5 module** (disease/encounter/order/observation/physiology = core simulation)
10. **Batch D: 22 module READMEs に Consumers 追加 — 5 module** (patient/population/procedure/staff/output + facility + healthcare_system + llm_service + validator まで残り全部、count 調整)
11. **`CONTRIBUTING-modules.md`** typed field vs extensions decision tree 拡張 (G4 absorbed)
12. **Cross-reference 整備** — README.md / README.ja.md / DESIGN.md AD-56 / CLAUDE.md Quick Navigation / CONTRIBUTING-modules.md 冒頭
13. **Regression** — 704 unit + integration green 維持確認
14. **Manual review** — 全 cross-reference link が resolve することを目視確認

(Batches A-D の正確なモジュール配分は plan で grep 結果を見ながら調整可)

---

## 14. Out of scope (deferred to future PRs)

- **Type consolidation refactor** (PR_C): 7 modules' types currently in `engine.py` → migrate to `clinosim/types/<name>/`. Byte-diff risk; should be separate PR. Already TODO'd in PR1/PR2 backlog.
- **identity enabled gate registry simplification** (originally G4): code refactor, defer.
- **PR3 (G3 `_fhir_observations.py` 31KB split, immunization extraction)**: next refactor PR after this docs PR merges.
- **`bedrock_setup.md` / `clinical_documents.md`**: existing docs, no update needed in this scope (separate concerns).
