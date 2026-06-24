# Comprehensive Documentation Update — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Pure docs PR — no test gates, no byte-diff, no DQR. Inline execution recommended.

**Goal:** Comprehensive documentation update so first-time viewers can navigate the project quickly and find each module's relationships (Dependencies + Consumers + cross-references). Pure docs work; no code changes.

**Architecture:** Two new top-level docs (`MODULES.md` module map, `SCENARIO_FLAGS.md` flag reference) + new module README template (`.github/TEMPLATE_MODULE_README.md`) + `## Consumers` section added to all 22 module READMEs (grep-based) + `## データ構造` sections added to 7 weak READMEs + `output/README.md` Extensibility section + `sdoh/README.md` language fix + `CONTRIBUTING-modules.md` extended with PR verification guide and typed-field-vs-extensions decision tree (G4 absorbed) + cross-reference integration across README EN/JP / DESIGN / CLAUDE.

**Tech Stack:** Markdown only. No code, no tests, no dependencies added.

## Global Constraints

- Branch: `feat/ad55-foundation-refactor-pr3-docs` (already created, spec commits `148e4077` + `0ad25db3`)
- Spec source: `docs/superpowers/specs/2026-06-24-comprehensive-docs-update-design.md`
- Predecessor: PR #84 (PR2 G2 SDOH integrity), master HEAD `5189857e`
- **No code changes** — pure documentation. No `pytest`, no `byte-diff`, no `3-axis DQR`.
- **Sanity regression**: at the end, run `pytest tests/unit/ tests/integration/ -x -q 2>&1 | tail -3` to confirm 704 baseline tests still pass (sanity check that no `__init__.py` docstring edit etc. accidentally broke a code path).
- **Manual link verification** at the end: every new cross-reference link must resolve to an actual file.
- **Language convention** (CLAUDE.md):
  - Top-level docs (MODULES.md, SCENARIO_FLAGS.md, README.md, DESIGN.md, CLAUDE.md, CONTRIBUTING-modules.md): **English** (default)
  - Module READMEs (`clinosim/modules/<name>/README.md`): **Japanese with English technical terms**
  - `README.ja.md`: Japanese mirror of README.md
- **G4 absorbed**: this PR is the G4 superset (typed-field-vs-extensions decision tree was original G4 doctrine docs scope; absorbed here as Task 11b)
- **Commit trailer (every commit)**:
  ```
  Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01PDwHvpzArboaKwtBDNpw8R
  ```

## File Structure

### New files
| Path | Purpose | Language |
|---|---|---|
| `MODULES.md` (top-level) | Module map: 22-module inventory + dependency tree + 3 typical call chains + 5-step new-module quick-start | English |
| `SCENARIO_FLAGS.md` (top-level) | Central reference for all scenario + medication flags routed through derive_lab_values | English |
| `.github/TEMPLATE_MODULE_README.md` | Boilerplate template for future module READMEs | Japanese |

### Modified files
| Path | Change |
|---|---|
| `clinosim/modules/output/README.md` | Add "## 拡張方法 (Extensibility)" section |
| `clinosim/modules/sdoh/README.md` | Fix line 1 (English → Japanese) |
| 7 weak READMEs (disease/encounter/order/facility/procedure/validator/population) | Add "## データ構造" section |
| All 22 module READMEs | Add "## Consumers" section (4 batches) |
| `docs/CONTRIBUTING-modules.md` | Add "PR 検証ガイド: byte-diff vs 3-axis DQR" sub-section + extend "CIF への書き込み" into decision-tree |
| `README.md` / `README.ja.md` | Add Module Map link |
| `DESIGN.md` AD-56 entry | Add PR_docs cross-reference |
| `CLAUDE.md` | Add Quick Navigation section |
| `TODO.md` | PR_docs done entry + remaining PR3 (G3) backlog |

---

## Task 1: Create `MODULES.md` (top-level module map)

**Files:**
- Create: `MODULES.md` (project root)

**Content blueprint:**

```markdown
# clinosim Module Map

A single-page overview of clinosim's 22 modules: what each one does, what
it depends on, who depends on it, and how data flows through the
simulator end-to-end. **Read this first** if you're new to the project.

## このドキュメントの読み方

| Goal | Read |
|---|---|
| 初めて見る | top to bottom |
| 特定モジュールを探す | "Module Inventory" table |
| 既存コードを変更する | "Typical Change Impact" |
| 新モジュールを足す | [docs/CONTRIBUTING-modules.md](docs/CONTRIBUTING-modules.md) + [.github/TEMPLATE_MODULE_README.md](.github/TEMPLATE_MODULE_README.md) |
| PR の検証手段を選ぶ | [docs/CONTRIBUTING-modules.md](docs/CONTRIBUTING-modules.md) "PR 検証ガイド" |

## TL;DR

clinosim は population-driven、physiology-based の合成 EHR データ
シミュレータ。22 module を 3 layer に組織化:

1. **Foundation** — `clinosim/codes/` + `clinosim/locale/` + `clinosim/types/`
   (no clinosim cross-dependencies)
2. **Simulation** — physiology → observation → order → clinical_course →
   encounter / patient activation
3. **Output** — `clinosim/modules/output/` adapters consume CIF, emit
   FHIR R4 (Bulk Data) / CSV

データ流: `population → patient activation → encounter loop →
CIF (canonical intermediate format) → output adapter`

**真の goal** は CIF データを **FHIR R4 + JP Core 準拠** の正確な
出力に変換すること、臨床現実性 + JP localization 品質を維持しながら。
詳細は [docs/CONTRIBUTING-modules.md](docs/CONTRIBUTING-modules.md)
「PR 検証ガイド」参照。

## レイヤー構造

```
┌─ Foundation (no clinosim deps) ──────────────────────────┐
│  clinosim/codes/       international code systems        │
│  clinosim/locale/      country-specific data             │
│  clinosim/types/       shared data types                 │
└──────────────────────────────────────────────────────────┘
            ↓                ↓               ↓
┌─ Simulation (physiology-driven) ─────────────────────────┐
│  physiology   patient state + lab/vital derivation       │
│  observation  result generation (panels, microbiology, …) │
│  order        lab/medication/imaging order placement     │
│  clinical_course  daily evolution + complications        │
│  diagnosis    Bayesian-ish working diagnosis             │
│  procedure    surgical + bedside procedures              │
│  encounter    inpatient/ED/outpatient YAML protocols     │
│  disease      30+ disease YAML protocols                 │
└──────────────────────────────────────────────────────────┘
            ↓                ↓               ↓
┌─ Population & Activation ────────────────────────────────┐
│  population   demographics + life events                 │
│  patient      Layer 1 → Layer 2 activation               │
│  identity     JP insurance + national ID (opt-in)        │
│  staff        roster + practitioner assignment           │
│  facility     hospital state + bed/ward management       │
│  healthcare_system  country-scoped operational params    │
└──────────────────────────────────────────────────────────┘
            ↓                ↓               ↓
┌─ Enrichment (AD-55 Base post-records) ───────────────────┐
│  immunization     CVX vaccine history                    │
│  family_history   first-degree relative disease history  │
│  code_status      DNR/Full Code resuscitation status     │
│  care_level       JP 要介護度 (JP only)                  │
│  sdoh             smoking + alcohol reference data       │
└──────────────────────────────────────────────────────────┘
            ↓                ↓               ↓
┌─ Output ─────────────────────────────────────────────────┐
│  output       CIF → FHIR R4 NDJSON / CSV adapters        │
│  llm_service  optional narrative generation              │
│  validator    data quality checks                        │
└──────────────────────────────────────────────────────────┘
```

## Module Inventory

すべての module。`Module` 列のリンクで該当 README へ。

| Module | 役割 | Layer | 主 Dependencies | 主 Consumers | Tier |
|---|---|---|---|---|---|
| [codes](clinosim/codes/README.md) | 国際コード体系 (LOINC/SNOMED/ICD/RxNorm/JLAC10/CVX) lookup | foundation | (none) | 全 module | foundational |
| [locale](clinosim/locale/README.md) | 国別文化データ (names/addresses/reference ranges/code_mapping) | foundation | codes | patient/observation/output/identity | foundational |
| [physiology](clinosim/modules/physiology/README.md) | 患者生理学状態 + lab/vital derivation (15 state axes) | simulation | types | observation, simulator/* (4 sites) | core |
| [observation](clinosim/modules/observation/README.md) | lab/vital result generation (panels, microbiology, nursing) | simulation | physiology/codes/locale | simulator/*, output | core |
| [order](clinosim/modules/order/README.md) | lab/medication/imaging order placement | simulation | observation/codes | simulator/* | core |
| [clinical_course](clinosim/modules/clinical_course/README.md) | archetype rule-based daily evolution + complications | simulation | physiology | simulator/inpatient.py | core |
| [diagnosis](clinosim/modules/diagnosis/README.md) | working/discharge diagnosis with Bayesian likelihood ratios | simulation | codes | simulator/inpatient.py | core |
| [procedure](clinosim/modules/procedure/README.md) | surgical + bedside procedures + rehab | simulation | codes/locale/types | simulator/inpatient.py | core |
| [encounter](clinosim/modules/encounter/README.md) | 46 ED/outpatient condition YAML protocols | simulation | codes/locale | simulator/emergency.py, simulator/outpatient.py | core |
| [disease](clinosim/modules/disease/README.md) | 30+ disease YAML protocols (Pydantic-validated) | simulation | types | simulator/inpatient.py | core |
| [population](clinosim/modules/population/README.md) | demographics + life events (Layer 1) | population | locale | simulator/__init__.py | core |
| [patient](clinosim/modules/patient/README.md) | Layer 1 → Layer 2 activation (chronic conditions + home meds) | population | population/codes/locale/sdoh | simulator/* | core |
| [identity](clinosim/modules/identity/README.md) | JP insurance + national ID assignment (AD-54, opt-in) | population | locale/types | output (FHIR Coverage) | optional (JP) |
| [staff](clinosim/modules/staff/README.md) | hospital roster + practitioner role assignment | population | types | simulator/*, output (Practitioner) | core |
| [facility](clinosim/modules/facility/README.md) | hospital state + bed/ward management + M/M/1 queueing | population | types | simulator/inpatient.py, output (Location) | core |
| [healthcare_system](clinosim/modules/healthcare_system/README.md) | country-scoped operational parameters (lab freq/dept names) | population | locale | simulator/*, observation | infrastructure |
| [immunization](clinosim/modules/immunization/README.md) | CVX adult vaccine history (post_records enricher) | enrichment | types/codes/locale | simulator/enrichers.py, output (Immunization) | optional |
| [family_history](clinosim/modules/family_history/README.md) | first-degree relative disease history (post_records enricher) | enrichment | types/codes/locale | simulator/enrichers.py, output (FamilyMemberHistory) | optional |
| [code_status](clinosim/modules/code_status/README.md) | DNR/Full Code SNOMED resuscitation status (encounter enricher) | enrichment | types/codes | simulator/enrichers.py, output (Observation) | optional |
| [care_level](clinosim/modules/care_level/README.md) | JP 要介護度 long-term-care need level (JP-only enricher) | enrichment | types/codes/locale | simulator/enrichers.py, output (Observation) | optional (JP) |
| [sdoh](clinosim/modules/sdoh/README.md) | smoking + alcohol enum→SNOMED reference data (data-only variant) | enrichment | codes | output (_fhir_smoking_alcohol.py) | foundational |
| [output](clinosim/modules/output/README.md) | CIF → FHIR R4 NDJSON / CSV adapters (registry-based) | output | 全 module (via builders) | CLI (clinosim generate) | core |
| [llm_service](clinosim/modules/llm_service/README.md) | optional narrative generation (Ollama / Bedrock / Anthropic) | output | codes | output (narrative path), simulator | optional |
| [validator](clinosim/modules/validator/README.md) | data quality tier framework | output | types | CLI (clinosim validate) | optional |

**Tier 凡例**:
- `foundational` — used by almost everything; changes ripple widely
- `core` — main simulation loop; changes affect every generated patient
- `optional` — opt-in feature; can be disabled without breaking core flow
- `infrastructure` — operational parameters; rare changes

## Dependency Tree (text ASCII)

```
codes/  (no deps)
locale/  └── codes/
types/  (no deps)

physiology/  └── types/
observation/  ├── physiology/
              ├── codes/
              └── locale/
order/  └── observation/, codes/
clinical_course/  └── physiology/
diagnosis/  └── codes/
procedure/  └── codes/, locale/, types/
encounter/  └── codes/, locale/
disease/  └── types/

population/  └── locale/
patient/  ├── population/
          ├── codes/
          ├── locale/
          └── sdoh/
identity/  └── locale/, types/
staff/  └── types/
facility/  └── types/
healthcare_system/  └── locale/

immunization/  ├── types/
               ├── codes/
               └── locale/
family_history/  ├── types/
                 ├── codes/
                 └── locale/
code_status/  ├── types/
              └── codes/
care_level/  ├── types/
             ├── codes/
             └── locale/
sdoh/  └── codes/  (data-only variant, no enricher)

output/  └── 全 module  (via _BUNDLE_BUILDERS + registry)
llm_service/  └── codes/
validator/  └── types/

simulator/  (top-level orchestration)
  ├── population/  (Layer 1)
  ├── patient/    (Layer 2)
  ├── encounter/  (inpatient/ED/outpatient YAML)
  ├── disease/    (inpatient YAML)
  ├── physiology/ (state)
  ├── observation/ (labs/vitals)
  ├── order/      (orders/MAR)
  ├── clinical_course/  (daily evolution)
  ├── diagnosis/  (working dx)
  ├── procedure/  (surgical/bedside)
  ├── staff/      (assignment)
  ├── facility/   (beds/wards)
  ├── enrichers.py  (post_records: immunization/family_history/code_status/care_level/nursing)
  └── output/     (CIF → FHIR/CSV)
```

## Typical Call Chains

### Chain 1: Population generation
```
simulator/run_beta()
  ↓ load_population() — population/engine.py
  ↓ assign_identities() — identity/assign.py  (if --jp-insurance)
  ↓ activate_patient() — patient/activator.py
      ├── _derive_home_medications() — uses locale/shared/chronic_medications.yaml
      └── PatientProfile populated (chronic_conditions, smoking_status, alcohol_use, …)
```

### Chain 2: Lab derivation (most-touched code path)
```
simulator/inpatient.py: _run_daily_loop()
  ↓ scenario_flags_from_protocol(protocol) — physiology/engine.py
  ↓ medication_flags_from_context(patient, all_orders, …) — physiology/engine.py
  ↓ flags = {**scenario_flags, **medication_flags}
  ↓ derive_lab_values(state, sex, age, **flags) — physiology/engine.py
  ↓ per-order sub-rng via individual_lab_seed() — simulator/seeding.py
  ↓ OrderResult populated → patient_record.lab_results
```

### Chain 3: FHIR export
```
CLI: clinosim generate --format fhir-r4
  ↓ output/fhir_r4_adapter.py: convert_cif_to_fhir()
  ↓ for each CIF patient:
    ↓ build BundleContext (record + country + roster + …)
    ↓ for each builder in _BUNDLE_BUILDERS:
        builder(ctx) → list[dict]  (FHIR resources)
    ↓ write() each resource to <ResourceType>.ndjson
```

Adding a FHIR resource: register a new builder via
`register_bundle_builder()` (AD-56) — never edit `_BUNDLE_BUILDERS` list
directly.

## Typical Change Impact

| Change | Affects | Notes |
|---|---|---|
| Add scenario flag (e.g. `causes_X`) | `physiology.engine` + 4 derive_lab_values call sites | Helper-mediated via `scenario_flags_from_protocol`; see [SCENARIO_FLAGS.md](SCENARIO_FLAGS.md) |
| Add medication-driven lab effect | `physiology.engine` + 4 sites | Helper-mediated via `medication_flags_from_context`; see [SCENARIO_FLAGS.md](SCENARIO_FLAGS.md) |
| Add new code (LOINC/SNOMED/ICD/…) | `codes/data/<system>.yaml` (en + optional ja) | See [clinosim/codes/README.md](clinosim/codes/README.md) |
| Add new FHIR resource type | New `_fhir_<X>.py` + `register_bundle_builder()` | See [clinosim/modules/output/README.md](clinosim/modules/output/README.md) "Extensibility" |
| Add new disease | New disease YAML + register in `locale/<country>/demographics.yaml` | See [clinosim/modules/disease/README.md](clinosim/modules/disease/README.md) |
| Add new module | Copy [.github/TEMPLATE_MODULE_README.md](.github/TEMPLATE_MODULE_README.md); register in [docs/CONTRIBUTING-modules.md](docs/CONTRIBUTING-modules.md) | |

> **真の goal は FHIR R4 / JP Core 準拠 + 臨床整合性 + JP language 品質**。
> PR の検証手段(byte-diff vs 3-axis DQR)については
> [docs/CONTRIBUTING-modules.md](docs/CONTRIBUTING-modules.md) 「PR 検証ガイド」を参照。

## Adding a New Module (5-step quick-start)

1. **Decide Base vs opt-in Module** → [docs/CONTRIBUTING-modules.md](docs/CONTRIBUTING-modules.md) 「判断: Base か Module か」
2. **Copy template** → [.github/TEMPLATE_MODULE_README.md](.github/TEMPLATE_MODULE_README.md) to `clinosim/modules/<name>/README.md`
3. **Create files per template** → `__init__.py` + `engine.py` + `reference_data/*.yaml` + `README.md`
4. **If enricher**: register sub-seed offset in `clinosim/simulator/seeding.py:ENRICHER_SEED_OFFSETS` (16-bit hex ASCII convention)
5. **Update this `MODULES.md`** inventory table with new row

## Where to Read Next

| Doc | Purpose |
|---|---|
| [README.md](README.md) / [README.ja.md](README.ja.md) | User-facing overview |
| [DESIGN.md](DESIGN.md) | Architecture + ADR table (55+ entries) |
| [CLAUDE.md](CLAUDE.md) | AI agent rules + project conventions |
| [docs/CONTRIBUTING-modules.md](docs/CONTRIBUTING-modules.md) | Module-author playbook + PR verification guide |
| [.github/TEMPLATE_MODULE_README.md](.github/TEMPLATE_MODULE_README.md) | Boilerplate for new module READMEs |
| [SCENARIO_FLAGS.md](SCENARIO_FLAGS.md) | Scenario / medication flag central reference |
| [TODO.md](TODO.md) | Roadmap |
| Per-module `README.md` | API + Dependencies + Consumers |
```

- [ ] **Step 1: Create the file**

Use the Write tool to create `/Users/tokuyama/workspace/clinosim/MODULES.md` with the content blueprint above.

- [ ] **Step 2: Verify all referenced links resolve**

Run: `for f in clinosim/codes/README.md clinosim/locale/README.md clinosim/modules/physiology/README.md clinosim/modules/output/README.md README.md README.ja.md DESIGN.md CLAUDE.md docs/CONTRIBUTING-modules.md TODO.md; do [ -f "$f" ] && echo "OK $f" || echo "MISSING $f"; done`

Expected: all `OK`. `SCENARIO_FLAGS.md` and `.github/TEMPLATE_MODULE_README.md` will be `MISSING` at this point — they're created in Tasks 2 + 3, so OK to defer link verification.

- [ ] **Step 3: Commit**

```bash
git add MODULES.md
git commit -m "$(cat <<'EOF'
docs(modules): MODULES.md — top-level 22-module map

Single-page overview of clinosim's 22 modules for new contributors:
- 3-layer architecture (Foundation / Simulation / Output)
- Full module inventory table (Module / Role / Layer / Dependencies /
  Consumers / Impact tier)
- Dependency tree (ASCII)
- 3 typical call chains (population generation / lab derivation /
  FHIR export)
- Typical change impact table (scenario flag / code addition /
  FHIR resource / disease / new module)
- 5-step new-module quick-start
- "Where to read next" navigation

First-time-viewer's first doc. Cross-references DESIGN.md, CLAUDE.md,
CONTRIBUTING-modules.md, per-module READMEs.

SCENARIO_FLAGS.md and .github/TEMPLATE_MODULE_README.md links resolve
after Tasks 2 + 3 complete.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01PDwHvpzArboaKwtBDNpw8R
EOF
)"
```

---

## Task 2: Create `SCENARIO_FLAGS.md` (top-level)

**Files:**
- Create: `SCENARIO_FLAGS.md` (project root)

**Content blueprint:**

```markdown
# Scenario & Medication Flags

clinosim's `physiology.derive_lab_values()` accepts boolean flags that
lift specific lab values at derive time. This document is the single
source of truth for **all current flags**, the **helper architecture**
that wires them, and the **5-step process** for adding new ones.

## What are these?

Disease YAMLs declare **scenario flags** (`causes_X`); patient context
provides **medication flags** (`on_X`). All flags follow the BNP-pattern
surgical principle (AD-57): **no `PhysiologicalState` mutation,
formula-only override**. This keeps state immutable and prevents the
master-RNG-cascade defect documented in spec
`docs/superpowers/specs/2026-06-22-aki-dka-surgical-calibration-design.md`.

## All current flags

| Flag | Type | Set in | Read in | Effect on lab values |
|---|---|---|---|---|
| `myocardial_injury` (alias: `causes_myocardial_injury` on disease YAML) | scenario | `acute_mi.yaml` | `physiology.engine.derive_lab_values` | Troponin_I → ACS-grade (~10-100 ng/mL); CK_MB also elevates |
| `causes_vte` | scenario | `pulmonary_embolism.yaml`, `deep_vein_thrombosis.yaml`, `cerebral_infarction.yaml` (embolic) | `derive_lab_values` | D_dimer → VTE-positive (clamp 0.15-20 μg/mL FEU; PE/DVT/CI admit p50 ≥ 4) |
| `on_warfarin` | medication | `PatientProfile.current_medications` (chronic AF/post-VTE) **OR** in-hospital warfarin order ≥ 3 days old (loading-dose rule) | `derive_lab_values` | PT_INR → therapeutic 2.5 + half-gain comorbidity perturbation; PT also (PT = 12 × PT_INR) |

## Helper architecture

Two sibling helpers in `clinosim/modules/physiology/engine.py`:

```python
def scenario_flags_from_protocol(protocol) -> dict[str, bool]:
    """Read all scenario flags from a disease YAML protocol.

    Currently returns {"myocardial_injury": bool, "causes_vte": bool}.
    Extend the dict for future scenario flags."""
    ...

def medication_flags_from_context(patient, medication_orders=None,
                                  admission_date=None, current_day=None) -> dict[str, bool]:
    """Read all medication flags from patient + encounter context.

    Currently returns {"on_warfarin": bool}.
    DOAC (apixaban/rivaroxaban/edoxaban/dabigatran) intentionally NOT
    detected — INR is not clinically monitored for DOAC; modeling DOAC
    INR lift would be clinically misleading.
    Extend the dict for future medication couplings."""
    ...
```

**Call sites merge both dicts**:

```python
flags = {
    **scenario_flags_from_protocol(protocol),
    **medication_flags_from_context(patient, all_med_orders, admission_date, day),
}
true_labs = derive_lab_values(state, sex=patient.sex, age=patient.age, **flags)
```

**4 derive_lab_values call sites** (all using this pattern after Phase 2b):

| Site | File | Purpose | medication context |
|---|---|---|---|
| Pass-1 lab loop | `simulator/inpatient.py:563-571` | daily inpatient labs | full (orders + day) |
| unknown-condition site | `simulator/inpatient.py:~1701` | unknown-condition encounter labs | chronic-only |
| ED admit | `simulator/emergency.py:126-130` | ED visit labs | chronic-only |
| Outpatient followup | `simulator/outpatient.py:152-160` | chronic-disease followup labs | chronic-only |

## Adding a new flag (5-step)

1. **Identify type**:
   - Disease-driven (e.g. `causes_dehydration`) → **scenario flag** → extend `scenario_flags_from_protocol`
   - Medication-driven (e.g. `on_steroid`) → **medication flag** → extend `medication_flags_from_context`
2. **Set the flag at its source**:
   - Scenario: add `causes_X: true` to relevant disease YAMLs
   - Medication: add detection rule to the helper (string match on `current_medications` and/or `medication_orders`)
3. **Extend the helper's return dict** to include the new key
4. **Add `<flag_name>: bool = False` kwarg** to `derive_lab_values`
5. **Implement formula change** in `derive_lab_values` (BNP-pattern surgical: no state mutation, formula-only)

**NEVER** add `flag=value` directly at a call site — J5 prevention (see
[CLAUDE.md](CLAUDE.md) "AD-55 enricher patterns"). The helper is the
single edit point so adding a new flag automatically reaches all 4 sites
through the `**flags` splat.

## DOAC exclusion (Phase 2b clinical decision)

For PT_INR, DOAC drugs (apixaban / rivaroxaban / edoxaban / dabigatran)
are intentionally **NOT detected** by `medication_flags_from_context`.
Clinical practice does not monitor INR for DOAC; modeling DOAC INR lift
would be clinically misleading and contradict the project's "真の goal
= FHIR/JP Core compliance + 臨床整合性" principle. See PR #82 (Phase 2b)
for the full rationale.

## 関連

- [DESIGN.md](DESIGN.md) AD-57 (BNP-pattern surgical) / AD-59 (per-order sub-rng) / AD-56 (enricher registry)
- [CLAUDE.md](CLAUDE.md) "AD-55 enricher patterns"
- [docs/CONTRIBUTING-modules.md](docs/CONTRIBUTING-modules.md) "PR 検証ガイド" + "sub-seed 導出ルール"
- [clinosim/modules/physiology/README.md](clinosim/modules/physiology/README.md) — helper API reference
- spec / plan: `docs/superpowers/specs/2026-06-24-phase2a-vte-d-dimer-design.md` (causes_vte) + `docs/superpowers/specs/2026-06-24-phase2b-on-anticoagulation-design.md` (on_warfarin)
```

- [ ] **Step 1: Create the file**

Use Write tool to create `/Users/tokuyama/workspace/clinosim/SCENARIO_FLAGS.md` with the blueprint.

- [ ] **Step 2: Commit**

```bash
git add SCENARIO_FLAGS.md
git commit -m "$(cat <<'EOF'
docs(flags): SCENARIO_FLAGS.md — central reference for derive_lab_values flags

Single source of truth for all current scenario + medication flags
routed through physiology.derive_lab_values():
- Current flags table (myocardial_injury / causes_vte / on_warfarin)
- Helper architecture (scenario_flags_from_protocol +
  medication_flags_from_context, J5 prevention pattern)
- 4 derive_lab_values call sites with full table
- 5-step add-a-new-flag guide
- DOAC exclusion clinical rationale (Phase 2b)

Cross-references DESIGN.md ADRs, CLAUDE.md, CONTRIBUTING-modules.md,
physiology/README.md, and the Phase 2a/2b spec docs.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01PDwHvpzArboaKwtBDNpw8R
EOF
)"
```

---

## Task 3: Create `.github/TEMPLATE_MODULE_README.md`

**Files:**
- Create: `.github/TEMPLATE_MODULE_README.md`

**Content blueprint** (verbatim — this IS the template, in Japanese matching module README convention):

```markdown
# [モジュールタイトル] — [JP one-line description]

> このファイルは新規モジュール README のテンプレートです。
> `<placeholders>` を埋め、不要なセクションは削除してください。

## 概要 / 役割

[2-3 sentences: what does this module do, why does it exist]

## 設計原則 (該当時のみ)

| Principle | Source |
|---|---|
| 例: AD-16 deterministic (sub-seed) | DESIGN.md AD-16 |
| 例: BNP-pattern surgical (state-unchanged) | DESIGN.md AD-57 |

## ディレクトリ構造

```
clinosim/modules/<name>/
  __init__.py            # public API export
  engine.py              # core logic / loaders
  reference_data/*.yaml  # data-driven definitions
  README.md              # this file
```

## API Reference

[Public functions exported via __init__.py. Show signature + 1-line description for each.]

```python
def public_function(arg: type) -> ReturnType:
    """One-line description.

    Optional longer explanation.
    """
```

## データ構造 (該当時)

主要型 (`clinosim/types/<name>.py` 推奨; 既存負債で `engine.py` 内残置の場合もあり):

| Type | 場所 | Key fields | 用途 |
|---|---|---|---|
| `MyType` | `clinosim/types/<name>.py` (`@dataclass`) | `field_a`, `field_b` | このモジュールの公開データ型 |

## Dependencies

| Dependency | Why |
|---|---|
| `clinosim/types/<name>` | data types |
| `clinosim/codes/` | code system display lookups via `code_lookup()` |
| `clinosim/locale/<country>/` | locale-specific data (該当時のみ) |
| (他モジュール) | (理由 — DESIGN.md ADR 参照) |

> 各モジュールは README の Dependencies に明記したもののみに依存可 (CLAUDE.md「Module independence」)。

## Consumers

このモジュールに依存するもの:

| Caller | How it uses this module | Impact when changing |
|---|---|---|
| `simulator/inpatient.py:NNN` | calls `public_function()` at line NNN | core (main simulation loop) |
| `modules/output/_fhir_<X>.py` | reads `<data type>` | medium (FHIR builder for X resource) |
| `tests/unit/test_<name>.py` | 各種 unit tests | guard |

**Impact tier**:
- `core` — affects main simulation loop or all encounters
- `medium` — affects specific feature (FHIR builder, lab path, etc.)
- `guard` — test only (no runtime impact)

## 拡張ガイド (Extensibility) (該当時)

[How to add a new <thing> to this module — e.g., new analyte, new scenario flag, new SDOH attribute]

詳細は [docs/CONTRIBUTING-modules.md](../../../docs/CONTRIBUTING-modules.md) 参照。

## 関連

- [DESIGN.md](../../../DESIGN.md) ADxx (該当 ADR)
- [docs/CONTRIBUTING-modules.md](../../../docs/CONTRIBUTING-modules.md) 該当セクション
- [MODULES.md](../../../MODULES.md) — 全 module 俯瞰
- 関連モジュール: [リスト]
- 関連 spec / plan: `docs/superpowers/specs/...` (該当時)
```

- [ ] **Step 1: Create `.github/` directory if needed**

```bash
mkdir -p .github
```

- [ ] **Step 2: Create the template file**

Use Write tool to create `/Users/tokuyama/workspace/clinosim/.github/TEMPLATE_MODULE_README.md` with the blueprint.

- [ ] **Step 3: Commit**

```bash
git add .github/TEMPLATE_MODULE_README.md
git commit -m "$(cat <<'EOF'
docs(template): .github/TEMPLATE_MODULE_README.md — module README boilerplate

Standardized module README template for new contributors. Canonical
section order (matches best-in-class READMEs like observation, identity,
sdoh after PR2):

1. 概要 / 役割
2. 設計原則 (該当時のみ)
3. ディレクトリ構造
4. API Reference
5. データ構造 (該当時)
6. Dependencies
7. Consumers (impact tier guidance: core / medium / guard)
8. 拡張ガイド (該当時)
9. 関連 (cross-references to DESIGN.md, CONTRIBUTING-modules.md,
   MODULES.md, related modules, spec/plan)

Used by:
- MODULES.md "Adding a New Module" quick-start (step 2)
- docs/CONTRIBUTING-modules.md (referenced from template-mention)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01PDwHvpzArboaKwtBDNpw8R
EOF
)"
```

---

## Task 4: `output/README.md` Extensibility section

**Files:**
- Modify: `clinosim/modules/output/README.md` (add new section before "関連" / end)

**Content to add**:

```markdown
## 拡張方法 (Extensibility)

### 新しい FHIR リソースを追加する (AD-56 registry pattern)

`_BUNDLE_BUILDERS` リストを **直接編集しない**。新規 builder を `register_bundle_builder()` で登録します:

```python
# clinosim/modules/output/_fhir_my_resource.py
from clinosim.modules.output._fhir_common import BundleContext

def _build_my_resource(ctx: BundleContext) -> list[dict]:
    """Build FHIR MyResource resources from CIF data.

    Reads ctx.record / ctx.patient_data / ctx.country, returns a list
    of FHIR resource dicts (NOT Bundle entries — _entry() wraps them).
    """
    return [{
        "resourceType": "MyResource",
        "id": f"myresource-{ctx.patient_id}",
        ...
    }]
```

そして `fhir_r4_adapter.py` で import + 登録 (現状は `_BUNDLE_BUILDERS` リストへの append、将来 entry-point discovery 化予定):

```python
# clinosim/modules/output/fhir_r4_adapter.py
from clinosim.modules.output._fhir_my_resource import _build_my_resource  # noqa: F401

_BUNDLE_BUILDERS = [
    ...,
    _build_my_resource,
]
```

実例 (PR2 SDOH refactor で確立した分離パターン):
- `_fhir_smoking_alcohol.py` — LOINC-keyed social-history Observation
- `_fhir_care_level.py` — JP-only custom code system
- `_fhir_immunization.py` (将来 PR3 で `_fhir_observations.py` から分離予定)
- `_fhir_family_history.py` — FamilyMemberHistory
- `_fhir_code_status.py` — code-status Observation

### 新しい出力フォーマットを追加する (AD-58 adapter registry)

`OutputAdapter` サブクラスを `register_output_adapter()` で登録 → CLI `--format` が自動拡張:

```python
# clinosim/modules/output/<my_format>_adapter.py
from clinosim.modules.output.adapter import OutputAdapter, register_output_adapter

class MyFormatAdapter(OutputAdapter):
    format_id = "my-format"
    description = "My custom output format"
    subdir = "my_format"

    def convert(self, cif_dir: str, output_dir: str, country: str) -> None:
        """Read CIF from cif_dir, write my-format output to output_dir."""
        ...

register_output_adapter(MyFormatAdapter)
```

実例:
- `csv_adapter.py` — CSV adapter (always-on Base format)
- `fhir_r4_adapter.py` — FHIR R4 Bulk Data adapter
- (将来) `ssmix2_adapter.py` / `hl7v2_adapter.py` 等

### 共通 helper

複数 builder で使う helper は `_fhir_common.py` に置き、各 builder 側で import します:
- `_social_category(country)` — social-history Observation.category
- `_value(system_key, code, lang)` — CodeableConcept with display lookup
- `_micro_coding(system_key, code, lang)` — bare coding (CodeableConcept ラップなし)
- `_loinc_coding(code, lang)` — LOINC coding entry
- `_survey_category()` — survey Observation.category
- `_build_diagnosis_codeable_concept(code, system_key, country)` — multilingual ICD coding
- `_entry(resource)` — Bundle entry wrapper

詳細は [docs/CONTRIBUTING-modules.md](../../../docs/CONTRIBUTING-modules.md) 「拡張点の使い方」セクション参照。
```

- [ ] **Step 1: Read the file to find insertion point**

Run: `grep -n "^##" /Users/tokuyama/workspace/clinosim/clinosim/modules/output/README.md`

Identify the last "##" section (likely "関連" or "依存"). Insert new section before that, or at the end if appropriate.

- [ ] **Step 2: Use Edit tool to insert**

Use Edit tool with `old_string` = the marker line you found in step 1 (or a unique nearby line), and `new_string` = the marker + new section.

- [ ] **Step 3: Commit**

```bash
git add clinosim/modules/output/README.md
git commit -m "$(cat <<'EOF'
docs(output): add Extensibility section — register_bundle_builder + register_output_adapter

output/README.md previously did not document the registry-based
extension patterns. New section "## 拡張方法 (Extensibility)" covers:

1. Adding FHIR resources via register_bundle_builder (AD-56) with
   examples from the PR2 SDOH split + immunization/family_history/
   code_status builders
2. Adding output formats via register_output_adapter (AD-58) with
   csv_adapter and fhir_r4_adapter examples
3. Common helpers in _fhir_common.py (social_category, _value,
   _micro_coding, _loinc_coding, _survey_category,
   _build_diagnosis_codeable_concept, _entry)

Cross-references docs/CONTRIBUTING-modules.md.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01PDwHvpzArboaKwtBDNpw8R
EOF
)"
```

---

## Task 5: `sdoh/README.md` line 1 language fix

**Files:**
- Modify: `clinosim/modules/sdoh/README.md` (line 1)

- [ ] **Step 1: Verify current state**

Run: `head -3 /Users/tokuyama/workspace/clinosim/clinosim/modules/sdoh/README.md`

Expected: line 1 is English (per audit), line 2 + later are JP.

- [ ] **Step 2: Use Edit tool to translate line 1**

The current line 1 is:
```
# clinosim/modules/sdoh
```

This is actually a code path heading, not English-vs-Japanese prose; the audit may have flagged a different line. Confirm by reading the actual top of the file with Read tool, then translate any English-prose line to Japanese.

If line 1 is `# clinosim/modules/sdoh` (a code path), this is acceptable as-is (module READMEs commonly use the path as title). Look for an English-prose introductory sentence and translate it.

The PR2 spec already created the sdoh README in Japanese; check if there's actually an inconsistency. If none, skip this task and document why.

Likely fix: the audit may have flagged the title format itself as "English-ish". To be safe, add a Japanese subtitle:

```markdown
# clinosim/modules/sdoh

AD-55 Base SDOH (social determinants of health) モジュール。
```

(if the existing first line is the title only, append a Japanese subtitle)

- [ ] **Step 3: Commit**

```bash
git add clinosim/modules/sdoh/README.md
git commit -m "$(cat <<'EOF'
docs(sdoh): unify README to Japanese (CLAUDE.md convention)

Module READMEs use Japanese with English technical terms per CLAUDE.md.
sdoh/README.md previously had English-prose line 1 (audit flagged
language inconsistency); now Japanese.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01PDwHvpzArboaKwtBDNpw8R
EOF
)"
```

(If no actual inconsistency exists after inspection, skip this commit and proceed to Task 6.)

---

## Task 6: 7 weak READMEs — add `## データ構造` section

**Files:**
- Modify each of:
  - `clinosim/modules/disease/README.md`
  - `clinosim/modules/encounter/README.md`
  - `clinosim/modules/order/README.md`
  - `clinosim/modules/facility/README.md`
  - `clinosim/modules/procedure/README.md`
  - `clinosim/modules/validator/README.md`
  - `clinosim/modules/population/README.md`

**Per-module data-structure content** (use grep to find actual types in each module):

For each module:

```markdown
## データ構造

主要型 (`clinosim/types/<name>.py` 推奨; 既存負債で `engine.py` 内残置の場合もあり、CLAUDE.md "All types defined in clinosim/types/" を将来統一予定):

| Type | 場所 | Key fields | 用途 |
|---|---|---|---|
| `TypeName` | `module/path/file.py:NNN` | `field_a`, `field_b` | usage |
| ... | | | |
```

Per-module entries (verify each path via `grep -n "^class\|^@dataclass\|class.*BaseModel" clinosim/modules/<name>/*.py`):

| Module | Likely types to document |
|---|---|
| disease | `DiseaseProtocol` (Pydantic, `disease/protocol.py`) |
| encounter | encounter condition dict from `protocol.py` (no Pydantic — `load_encounter_condition` returns dict) |
| order | `Order` (`types/encounter.py`), `OrderResult`, `OrderStatus` enum, `OrderType` enum |
| facility | `HospitalState` (`facility/hospital_state.py`) |
| procedure | `ProcedureRecord` (`procedure/engine.py` or `types/`), `RehabSession` |
| validator | Validator tier types (check `validator/engine.py`) |
| population | `PersonRecord` (`population/engine.py`), `LifeEvent`, `HospitalizationSummary` |

- [ ] **Step 1: For each module, locate the type definitions**

Run: `for mod in disease encounter order facility procedure validator population; do echo "=== $mod ==="; grep -n "^class \|^@dataclass\|BaseModel" clinosim/modules/$mod/*.py 2>/dev/null | head -10; done`

- [ ] **Step 2: For each module, find insertion point in its README**

Each README should have an `## API Reference` or `## ディレクトリ構造` section. Insert `## データ構造` AFTER the API section and BEFORE the `## Dependencies` section.

- [ ] **Step 3: Edit each of the 7 READMEs**

Use Edit tool per module, with the data-structure content tailored to that module (using info from Step 1).

- [ ] **Step 4: Commit**

```bash
git add clinosim/modules/disease/README.md \
        clinosim/modules/encounter/README.md \
        clinosim/modules/order/README.md \
        clinosim/modules/facility/README.md \
        clinosim/modules/procedure/README.md \
        clinosim/modules/validator/README.md \
        clinosim/modules/population/README.md
git commit -m "$(cat <<'EOF'
docs(modules): add data-structure section to 7 READMEs

Audit found 7 module READMEs without explicit "## データ構造" section:
disease / encounter / order / facility / procedure / validator /
population. Developers had to grep module code to discover key types
(Pydantic models / dataclasses / enums).

Each gains a "## データ構造" table listing:
- Type name + file path
- Key fields
- Usage

Type-consolidation refactor (some types still in engine.py instead of
types/) is tracked separately as PR_C backlog (CLAUDE.md "All types
defined in clinosim/types/" rule; deferred to avoid mixing pure-docs
with code refactor).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01PDwHvpzArboaKwtBDNpw8R
EOF
)"
```

---

## Tasks 7-10: Add `## Consumers` section to 22 module READMEs (4 batches)

For each batch, follow the same per-module process:

### Per-module process

1. Find consumers: `grep -rln "from clinosim.modules.<name>\b\|import clinosim.modules.<name>\b" clinosim/ tests/ 2>/dev/null`
2. For each consumer file, identify how it uses the module (one line)
3. Assign impact tier: `core` (main loop), `medium` (specific feature), `guard` (test only)
4. Insert `## Consumers` section AFTER `## Dependencies` and BEFORE `## 関連` (or any later section)

### Consumers section format

```markdown
## Consumers

このモジュールに依存するもの:

| Caller | How | Impact |
|---|---|---|
| `simulator/inpatient.py:NNN` | calls `function()` at line NNN | core |
| `modules/output/_fhir_<X>.py` | reads `<data type>` | medium |
| `tests/unit/test_<name>.py` | unit tests | guard |
```

### Task 7 — Batch A (6 small modules, ~18 consumer entries total)

**Modules:** care_level / diagnosis / facility / healthcare_system / order / validator

- [ ] **Step 1: For each Batch A module, gather consumers**

Run: `for mod in care_level diagnosis facility healthcare_system order validator; do echo "=== $mod ==="; grep -rln "from clinosim.modules.$mod\b\|import clinosim.modules.$mod\b" clinosim/ tests/ 2>/dev/null; done`

- [ ] **Step 2: For each module, insert Consumers section using Edit tool**

(Per-module Edit with content tailored to grep results)

- [ ] **Step 3: Commit Batch A**

```bash
git add clinosim/modules/care_level/README.md \
        clinosim/modules/diagnosis/README.md \
        clinosim/modules/facility/README.md \
        clinosim/modules/healthcare_system/README.md \
        clinosim/modules/order/README.md \
        clinosim/modules/validator/README.md
git commit -m "$(cat <<'EOF'
docs(modules): add Consumers section — Batch A (6 small modules)

Reverse-dependency visibility for: care_level / diagnosis / facility /
healthcare_system / order / validator. Each "## Consumers" section
lists caller files with impact tier (core / medium / guard).

Batch A consumer counts: care_level=4, diagnosis=4, facility=3,
healthcare_system=2, order=3, validator=2.

Part of comprehensive docs update (PR_docs). 22 module READMEs gain
Consumers sections in 4 batches.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01PDwHvpzArboaKwtBDNpw8R
EOF
)"
```

### Task 8 — Batch B (6 small-medium modules, ~32 consumer entries)

**Modules:** clinical_course / family_history / immunization / sdoh / code_status / patient

- [ ] **Step 1: Gather consumers**

Run: `for mod in clinical_course family_history immunization sdoh code_status patient; do echo "=== $mod ==="; grep -rln "from clinosim.modules.$mod\b\|import clinosim.modules.$mod\b" clinosim/ tests/ 2>/dev/null; done`

- [ ] **Step 2: For each module, insert Consumers section**

(Per-module Edit with content tailored to grep results)

- [ ] **Step 3: Commit Batch B**

```bash
git add clinosim/modules/clinical_course/README.md \
        clinosim/modules/family_history/README.md \
        clinosim/modules/immunization/README.md \
        clinosim/modules/sdoh/README.md \
        clinosim/modules/code_status/README.md \
        clinosim/modules/patient/README.md
git commit -m "$(cat <<'EOF'
docs(modules): add Consumers section — Batch B (6 small-medium modules)

Reverse-dependency visibility for: clinical_course / family_history /
immunization / sdoh / code_status / patient.

Batch B consumer counts: clinical_course=5, family_history=5,
immunization=5, sdoh=5, code_status=6, patient=6.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01PDwHvpzArboaKwtBDNpw8R
EOF
)"
```

### Task 9 — Batch C (6 medium modules, ~45 consumer entries)

**Modules:** procedure / llm_service / disease / encounter / identity / staff

- [ ] **Step 1: Gather consumers**

Run: `for mod in procedure llm_service disease encounter identity staff; do echo "=== $mod ==="; grep -rln "from clinosim.modules.$mod\b\|import clinosim.modules.$mod\b" clinosim/ tests/ 2>/dev/null; done`

- [ ] **Step 2: Insert Consumers sections**

(Per-module Edit)

- [ ] **Step 3: Commit Batch C**

```bash
git add clinosim/modules/procedure/README.md \
        clinosim/modules/llm_service/README.md \
        clinosim/modules/disease/README.md \
        clinosim/modules/encounter/README.md \
        clinosim/modules/identity/README.md \
        clinosim/modules/staff/README.md
git commit -m "$(cat <<'EOF'
docs(modules): add Consumers section — Batch C (6 medium modules)

Reverse-dependency visibility for: procedure / llm_service / disease /
encounter / identity / staff.

Batch C consumer counts: procedure=6, llm_service=7, disease=8,
encounter=8, identity=8, staff=8.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01PDwHvpzArboaKwtBDNpw8R
EOF
)"
```

### Task 10 — Batch D (4 large modules, ~93 consumer entries)

**Modules:** population / observation / physiology / output

For output (51 consumers), group internal `_fhir_*.py` cross-references into a single row ("21 sibling _fhir_*.py files reuse common helpers") rather than enumerating each.

- [ ] **Step 1: Gather consumers**

Run: `for mod in population observation physiology output; do echo "=== $mod ==="; grep -rln "from clinosim.modules.$mod\b\|import clinosim.modules.$mod\b" clinosim/ tests/ 2>/dev/null | head -25; done`

- [ ] **Step 2: Insert Consumers sections**

(Per-module Edit; for output, collapse `_fhir_*.py` internal cross-refs into one row)

- [ ] **Step 3: Commit Batch D**

```bash
git add clinosim/modules/population/README.md \
        clinosim/modules/observation/README.md \
        clinosim/modules/physiology/README.md \
        clinosim/modules/output/README.md
git commit -m "$(cat <<'EOF'
docs(modules): add Consumers section — Batch D (4 large modules)

Reverse-dependency visibility for: population / observation /
physiology / output.

Batch D consumer counts: population=11, observation=14, physiology=17,
output=51. For output, the 21 sibling _fhir_*.py files (internal
cross-references) are collapsed into a single row rather than
enumerated, since they all reuse common helpers from _fhir_common.py.

This completes the Consumers section addition across all 22 module
READMEs (Batches A+B+C+D). Reverse-dependency visibility now uniform.

Also adds package-level READMEs (codes / locale) where appropriate.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01PDwHvpzArboaKwtBDNpw8R
EOF
)"
```

---

## Task 11a: `CONTRIBUTING-modules.md` PR verification guide

**Files:**
- Modify: `docs/CONTRIBUTING-modules.md`

**Content to insert** (after the existing "## データ生成の作法" / "### 決定論コントラクト" section):

```markdown
### PR 検証ガイド: byte-diff vs 3-axis DQR

**真の goal**: CIF データを **FHIR R4 + JP Core 準拠** の正確な出力に変換すること + 臨床的整合性 + JP localization 品質。

PR の性質によって適切な検証手段が異なります:

| PR の性質 | 検証手段 | 何を保証するか |
|---|---|---|
| **Pure mechanical refactor** (例: 内部構造整理、helper 共通化、registry 中央化、ファイル分割) | **byte-diff** — master と branch で同 seed/設定で生成した 11 NDJSON が sha256 IDENTICAL | refactor 前後で **出力が一切変わっていない** = no-regression gate |
| **新機能 / リアリティ改善** (例: 新 analyte 追加、scenario flag 追加、medication coupling 追加、新疾患追加) | **3-axis DQR** (`docs/reviews/<date>-<topic>-data-quality-review.md`) | **FHIR R4 / JP Core 適合性 + 臨床整合性 + JP language 品質** = goal achievement gate |
| **Pure docs update** (例: README 更新、新 doc 作成) | regression check (テスト緑) + manual link review | code 変更がないこと |
| **混合** (refactor + 小さな behavior change) | byte-diff で意図的変化のみあることを確認 + DQR で goal 維持を確認 | 両方 |

**byte-diff は手段、3-axis DQR が真の goal テスト**:
- refactor PR で byte-diff を使うのは「behavior 変えていない」を mechanical に確認する shortcut。output が変わると refactor の主張が嘘になるため。
- 新機能 PR では byte-diff は **完全一致でなくて OK** (意図的に変わる)。3-axis DQR が真のゴール — FHIR/JP Core 規格適合性、臨床的妥当性 (warfarin patient の INR 2-3 等)、JP localization 品質 (display 文字列、JLAC10 ja の権威出典準拠) — を verify する。
- 例: Phase 2a (D-dimer / causes_vte) は新機能なので、9 NDJSON は byte-identical で残り 2 つ (Observation / DR) が意図的に変化。3-axis DQR で PE/DVT/CI 患者の D-dimer が VTE-positive 帯にあるか + JLAC10 2B140 ja JCCLS 公式日本語名であるか等を verify。

#### byte-diff の実施手順

1. master HEAD で `python -m clinosim.simulator.cli generate -p 2000 -s 42 --country US --format fhir-r4 -o scratchpad/<topic>_byte_diff/master/us` (JP も同様)
2. branch HEAD で同じコマンドを `scratchpad/<topic>_byte_diff/branch/us` に出力
3. sha256 比較スクリプトを実行 (PR1/PR2 の `scratchpad/refactor_pr*_byte_diff/compare.py` を template として参照)
4. 全 11 NDJSON が IDENTICAL であることを確認 (refactor PR の gate)
5. 結果を `scratchpad/<topic>_byte_diff_results.md` に書き、PR 本体に commit

#### 3-axis DQR の実施手順

1. US p≥10000 + JP p≥5000 で生成 (大規模 cohort で cohort-emergent 現象を捕捉)
2. 3 軸監査スクリプトを実行 (Phase 2a/2b の `scratchpad/phase2*_dqr/dqr_audit.py` を template として参照):
   - **構造**: refRange 100%, interpretation 100%, display≠code 100%, id 重複 0
   - **臨床**: 期待される疾患ごとの lab 値域 (DKA HCO3 / ACS Troponin / VTE D-dimer / AF chronic INR therapeutic 等)
   - **JP language**: US 日本語混入 0、JP display 文字列が JCCLS-JSLM / MHLW 等の権威出典準拠
3. 全 axes PASS を確認
4. 結果を `docs/reviews/<date>-<topic>-data-quality-review.md` に書き、PR 本体に commit
```

- [ ] **Step 1: Locate insertion point**

Run: `grep -n "^### " docs/CONTRIBUTING-modules.md | head -15`

Find the section "### 決定論コントラクト (AD-16 / AD-17)" or similar; insert new sub-section after it.

- [ ] **Step 2: Use Edit tool to insert the new sub-section**

- [ ] **Step 3: Commit**

```bash
git add docs/CONTRIBUTING-modules.md
git commit -m "$(cat <<'EOF'
docs(contributing): add PR verification guide — byte-diff vs 3-axis DQR

User feedback (2026-06-24):
> byte-diffってなんのため？CIFにある情報は、適切にFHIRやJP COREに
> 準拠したFHIR R4にするのがゴールだよ？

Document the distinction explicitly so future contributors know which
verification gate applies to which PR shape. Key principle:

- byte-diff is a refactor-PR no-regression mechanic
- 3-axis DQR (FHIR/JP Core compliance + clinical coherence + JP
  language quality) is the true goal-achievement gate for feature PRs

New sub-section under "## データ生成の作法" / "### 決定論コントラクト":
- Decision matrix table mapping PR shape to verification method
- byte-diff step-by-step (5 steps, references PR1/PR2 compare.py)
- 3-axis DQR step-by-step (4 steps, references Phase 2a/2b dqr_audit.py)
- Example: Phase 2a (causes_vte) — 9 NDJSON identical + 2 intentional
  changes → DQR verifies clinical band

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01PDwHvpzArboaKwtBDNpw8R
EOF
)"
```

---

## Task 11b: `CONTRIBUTING-modules.md` typed-field-vs-extensions decision tree (G4 absorbed)

**Files:**
- Modify: `docs/CONTRIBUTING-modules.md`

**Replace** the existing "### CIF への書き込み: Base か extensions か" section (currently ~5 lines of bullets) with the decision-tree format:

- [ ] **Step 1: Locate the existing section**

Run: `grep -n "CIF への書き込み" docs/CONTRIBUTING-modules.md`

- [ ] **Step 2: Use Edit tool to replace with the decision-tree version**

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

| 軸 | typed field | extensions |
|---|---|---|
| Always-on Base data | ✓ | |
| Opt-in module data | | ✓ |
| 共通 core EHR field | ✓ | |
| Theme-specific | | ✓ |
| 例 | `immunizations` / `family_history` / `code_status` / `care_level` | `nursing` extensions (always-on だが specialized) |
| Persistence | `asdict` で完全シリアライズ | dict、explicit シリアライズ |

**例外明文化 (TYP-4)**: always-on の Base enricher で typed field を使ってよい (例 `nursing_risk_assessments`)。**新規 opt-in module は必ず `extensions[<module>]` を使う**。

> **PR2 教訓 (data-only variant)**: `modules/sdoh/` のような data-only module variant は **データを CIF に書かない** — patient activator が `PatientProfile.smoking_status` 等の既存 field を更新するため、本質的に Base data。新モジュールで CIF 書き込みが不要なら、この判定フローはスキップ。

```python
# opt-in module enricher 内
rec.extensions["my_module"] = [asdict(r) for r in my_records]

# always-on Base enricher 内 (例外: TYP-4)
rec.my_typed_field = [asdict(r) for r in my_records]
```
```

- [ ] **Step 3: Commit**

```bash
git add docs/CONTRIBUTING-modules.md
git commit -m "$(cat <<'EOF'
docs(contributing): typed-field-vs-extensions decision tree (G4 absorbed)

Originally G4 doctrine docs scope (typed field vs extensions decision
tree), absorbed into PR_docs. Existing "CIF への書き込み: Base か
extensions か" section (5-line bullets) replaced with full decision-tree:

- 3-question judgment flow
- Decision matrix table (axis / typed field / extensions / examples /
  persistence)
- TYP-4 exception (always-on Base enricher exception)
- PR2 lesson re data-only module variant (modules/sdoh/) which skips
  CIF write entirely

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01PDwHvpzArboaKwtBDNpw8R
EOF
)"
```

---

## Task 12: Cross-reference integration

**Files:**
- Modify: `README.md`
- Modify: `README.ja.md`
- Modify: `DESIGN.md` AD-56 entry
- Modify: `CLAUDE.md` (add Quick Navigation section)
- Modify: `docs/CONTRIBUTING-modules.md` (top)

- [ ] **Step 1: Add Module Map link to README.md**

Find a top-level section in `README.md` (e.g., after the project description), insert:

```markdown
## Module Map

For a single-page overview of all 22 modules, their dependencies, and typical call chains, see [`MODULES.md`](MODULES.md).
```

Use Edit tool.

- [ ] **Step 2: Mirror in README.ja.md**

Same insertion in Japanese:

```markdown
## モジュール一覧

22 モジュール全体の俯瞰 (依存関係 + 典型的なコールチェーン) は [`MODULES.md`](MODULES.md) を参照。
```

- [ ] **Step 3: Extend DESIGN.md AD-56 entry**

Find the AD-56 row (already extended in PR1 + PR2). Append the PR_docs reference:

```
... **PR_docs 2026-06-24 comprehensive documentation update** added `MODULES.md` (top-level module map with 22-module inventory + dependency tree + typical call chains), `SCENARIO_FLAGS.md` (central reference for scenario + medication flags routed through `derive_lab_values`), `.github/TEMPLATE_MODULE_README.md` (standardized module README template), and "Consumers" sections to all 22 module READMEs for reverse-dependency visibility. Also extended `docs/CONTRIBUTING-modules.md` with PR verification guide (byte-diff vs 3-axis DQR decision matrix; absorbs original G4 typed-field-vs-extensions decision tree).
```

Use Edit tool.

- [ ] **Step 4: Add Quick Navigation to CLAUDE.md**

Find the top of `CLAUDE.md` (after the "## Project overview" or first heading). Insert:

```markdown
## Quick navigation

| Looking for | Read |
|---|---|
| Module overview | [`MODULES.md`](MODULES.md) |
| Scenario / medication flags | [`SCENARIO_FLAGS.md`](SCENARIO_FLAGS.md) |
| Architecture / ADR table | [`DESIGN.md`](DESIGN.md) |
| Module author HOW-TO + PR verification guide | [`docs/CONTRIBUTING-modules.md`](docs/CONTRIBUTING-modules.md) |
| New module template | [`.github/TEMPLATE_MODULE_README.md`](.github/TEMPLATE_MODULE_README.md) |
| Roadmap | [`TODO.md`](TODO.md) |
```

- [ ] **Step 5: Add header link to CONTRIBUTING-modules.md**

At the very top of `docs/CONTRIBUTING-modules.md` (before "## 判断: Base か Module か"), insert:

```markdown
> **新規モジュール作成時**: [.github/TEMPLATE_MODULE_README.md](../.github/TEMPLATE_MODULE_README.md) をコピーして開始。全 22 module の俯瞰は [`MODULES.md`](../MODULES.md) を参照。PR 検証手段の選び方は本書 "PR 検証ガイド" セクション参照。
```

- [ ] **Step 6: Commit**

```bash
git add README.md README.ja.md DESIGN.md CLAUDE.md docs/CONTRIBUTING-modules.md
git commit -m "$(cat <<'EOF'
docs(cross-ref): integrate MODULES.md / SCENARIO_FLAGS.md / TEMPLATE links

Top-level cross-reference integration so the new docs are discoverable
from existing entry points:

- README.md / README.ja.md: "Module Map" section pointing to MODULES.md
- DESIGN.md AD-56 entry: PR_docs note describing all new docs +
  CONTRIBUTING extensions
- CLAUDE.md: new "Quick navigation" table at the top (Module overview /
  flags / architecture / contributor playbook / template / roadmap)
- docs/CONTRIBUTING-modules.md: header link directing new contributors
  to TEMPLATE_MODULE_README.md + MODULES.md + PR verification guide

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01PDwHvpzArboaKwtBDNpw8R
EOF
)"
```

---

## Task 13: Regression check

**Goal:** Confirm no `__init__.py` docstring edit or similar accidentally broke a code path. Should be 100% no-op since no code was touched.

- [ ] **Step 1: Run full unit + integration suite**

Run: `pytest tests/unit/ tests/integration/ -x -q 2>&1 | tail -5`

Expected: 704 passed (baseline). Any failure = investigate (the edit was supposed to be pure docs).

---

## Task 14: Manual link review

**Goal:** Every new cross-reference link resolves to an actual file.

- [ ] **Step 1: Collect all link targets**

Run: 
```
grep -rEn "\]\([./A-Za-z][^)]*\.md\)" MODULES.md SCENARIO_FLAGS.md .github/TEMPLATE_MODULE_README.md docs/CONTRIBUTING-modules.md README.md README.ja.md CLAUDE.md 2>/dev/null | head -50
```

- [ ] **Step 2: For each unique target, verify it exists**

```bash
for f in MODULES.md SCENARIO_FLAGS.md .github/TEMPLATE_MODULE_README.md \
         DESIGN.md CLAUDE.md README.md README.ja.md TODO.md \
         docs/CONTRIBUTING-modules.md \
         clinosim/codes/README.md clinosim/locale/README.md \
         clinosim/modules/physiology/README.md clinosim/modules/output/README.md \
         clinosim/modules/sdoh/README.md; do
  [ -f "$f" ] && echo "OK $f" || echo "MISSING $f"
done
```

Expected: all `OK`.

- [ ] **Step 3: Update TODO.md with PR_docs done entry**

In TODO.md, append after the existing PR2 entry:

```markdown

**Comprehensive Documentation Update (G4 absorbed) — 2026-06-24:**
Pure documentation PR_docs (no code changes; no byte-diff / DQR required).
Five-fold improvement to first-time-viewer onboarding + module-relationship
visibility:

1. **MODULES.md** (new top-level) — 22-module inventory + dependency tree
   + 3 typical call chains + 5-step new-module quick-start.
2. **SCENARIO_FLAGS.md** (new top-level) — central reference for all
   scenario + medication flags routed through derive_lab_values (currently
   myocardial_injury / causes_vte / on_warfarin) + helper architecture +
   5-step new-flag guide.
3. **.github/TEMPLATE_MODULE_README.md** (new) — standardized template
   for new module READMEs with canonical section order.
4. **All 22 module READMEs gained `## Consumers` section** — reverse-
   dependency visibility (impact tier core/medium/guard) so contributors
   can assess downstream impact of any module change.
5. **7 weak READMEs** gained `## データ構造` section (disease/encounter/
   order/facility/procedure/validator/population).

Additional fixes:
- `output/README.md` gained Extensibility section (register_bundle_builder
  + register_output_adapter patterns documented).
- `sdoh/README.md` language consistency fix (was English line 1).
- `CONTRIBUTING-modules.md` gained PR 検証ガイド sub-section
  (byte-diff vs 3-axis DQR decision matrix — clarifies that the TRUE
  goal is FHIR R4 / JP Core compliance + 臨床整合性 + JP language
  quality; byte-diff is a refactor-PR mechanic only).
- `CONTRIBUTING-modules.md` typed-field-vs-extensions decision tree
  extended (G4 doctrine docs absorbed).
- Cross-reference integration across README EN/JP / DESIGN AD-56 /
  CLAUDE Quick Navigation / CONTRIBUTING header.

Series context: PR1 (G1) + PR2 (G2) + **PR_docs (G4 absorbed) ✓**.
Remaining: PR3 (G3 `_fhir_observations.py` 31KB split, immunization
extraction) → then device + HAI feature work.

Backlog: PR_C type consolidation (7 modules' types in engine.py →
types/) — code refactor with byte-diff risk, separate concern from
docs work.
```

- [ ] **Step 4: Commit TODO.md update**

```bash
git add TODO.md
git commit -m "$(cat <<'EOF'
docs(todo): PR_docs done entry + PR_C backlog explicit

PR_docs (comprehensive documentation update) complete:
- MODULES.md (top-level module map)
- SCENARIO_FLAGS.md (central flag reference)
- .github/TEMPLATE_MODULE_README.md (boilerplate)
- 22 module READMEs gain Consumers sections (4 batches)
- 7 weak READMEs gain data-structure sections
- output/README.md Extensibility section
- sdoh/README.md language fix
- CONTRIBUTING-modules.md PR verification guide + typed-field-vs-
  extensions decision tree (G4 absorbed)
- Cross-reference integration (README EN/JP / DESIGN AD-56 / CLAUDE
  Quick Nav / CONTRIBUTING header)

PR_C backlog (type consolidation): 7 modules currently define types
in engine.py instead of clinosim/types/ (CLAUDE.md "All types defined
in clinosim/types/" rule). Code refactor with byte-diff risk; separate
PR. Modules: population (PersonRecord/LifeEvent/HospitalizationSummary),
facility (HospitalState), procedure (ProcedureRecord/RehabSession),
encounter (no Pydantic protocol type), staff (StaffMember/StaffRoster),
disease (DiseaseProtocol already in protocol.py — different concern).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01PDwHvpzArboaKwtBDNpw8R
EOF
)"
```

---

## Final: Push + PR

After all tasks complete:

```bash
git push -u origin feat/ad55-foundation-refactor-pr3-docs
gh pr create --title "docs: comprehensive documentation update — module map + Consumers + doctrine (G4 absorbed)" --body "$(cat <<'EOF'
## Summary

Comprehensive documentation update per user request:

> ドキュメントを網羅的に更新して。初めて見る人にとってわかりやすい
> ようにして。それぞれのモジュールが、どのモジュールと、あるいは
> どのファイルと関連しているかも記述するように。

**Pure docs PR — no code changes**, no byte-diff or 3-axis DQR required.

### New top-level docs

- **MODULES.md** — single-page module map: 22-module inventory + dependency tree + 3 typical call chains + 5-step new-module quick-start
- **SCENARIO_FLAGS.md** — central reference for all scenario + medication flags + helper architecture + 5-step new-flag guide
- **.github/TEMPLATE_MODULE_README.md** — standardized module README template

### Existing docs strengthened

- **22 module READMEs gain `## Consumers` section** — reverse-dependency visibility (impact tier: core / medium / guard) so contributors can assess downstream impact
- **7 weak READMEs gain `## データ構造` section** — disease/encounter/order/facility/procedure/validator/population
- **`output/README.md` Extensibility section** — register_bundle_builder + register_output_adapter patterns documented
- **`sdoh/README.md` language fix** — line 1 unified to Japanese per CLAUDE.md convention
- **`CONTRIBUTING-modules.md`** — gains PR verification guide (byte-diff vs 3-axis DQR decision matrix) + typed-field-vs-extensions decision tree (G4 absorbed)

### Cross-reference integration

- `README.md` / `README.ja.md` — Module Map link
- `DESIGN.md` AD-56 — PR_docs cross-reference
- `CLAUDE.md` — Quick Navigation section at top
- `CONTRIBUTING-modules.md` — header link to template + MODULES.md + PR verification guide

### PR verification clarification (user feedback)

A key feedback this PR captures explicitly:

> byte-diffってなんのため？CIFにある情報は、適切にFHIRやJP COREに
> 準拠したFHIR R4にするのがゴールだよ？

byte-diff is a **refactor-PR no-regression mechanic**. The **true project goal** is producing CIF data that converts to **FHIR R4 + JP Core compliant output** with clinical coherence + JP language quality. The **3-axis DQR** (structural / clinical / JP language) is the goal-achievement gate for feature PRs. The new "PR 検証ガイド" sub-section in CONTRIBUTING-modules.md documents which gate applies to which PR shape.

## Series context

- PR1 (G1, merged): structural DRY ✓
- PR2 (G2, merged): SDOH integrity ✓
- **PR_docs (G4 absorbed, this PR)**: comprehensive docs ✓
- PR3 (G3): `_fhir_observations.py` 31KB split (immunization extraction)
- Then: device + HAI feature work

## Backlog (deferred from this PR)

- **PR_C type consolidation**: 7 modules currently define types in `engine.py` instead of `clinosim/types/` (CLAUDE.md rule). Code refactor with byte-diff risk; separate PR.

## Spec / Plan

- spec: `docs/superpowers/specs/2026-06-24-comprehensive-docs-update-design.md`
- plan: `docs/superpowers/plans/2026-06-24-comprehensive-docs-update.md`

## Test plan

- [x] Regression check (704 unit + integration green; pure docs, no code touched)
- [x] Manual link review (every new cross-reference resolves)

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_01PDwHvpzArboaKwtBDNpw8R
EOF
)"
```

---

## Self-Review Notes

**Spec coverage check (against spec §1-§14)**:
- §1 Motivation / audit findings → all captured in component tasks
- §2 Architecture diagram → Tasks 1-12 cover all listed deliverables
- §3 MODULES.md → Task 1 (with full content blueprint)
- §4 SCENARIO_FLAGS.md → Task 2 (with full content blueprint)
- §5 TEMPLATE_MODULE_README.md → Task 3 (with full content blueprint)
- §6 22 module READMEs Consumers → Tasks 7-10 (4 batches, per-module grep-based content)
- §7 7 weak READMEs data structure → Task 6 (per-module type tables)
- §8 output/README.md Extensibility → Task 4 (with full content blueprint)
- §9 sdoh/README.md language fix → Task 5 (verify-then-fix flow)
- §10a PR verification guide → Task 11a (with full content blueprint)
- §10b typed-field decision tree → Task 11b (with full content blueprint)
- §11 cross-reference integration → Task 12 (5 sub-edits)
- §12 verification strategy → Task 13 (regression) + Task 14 (manual link review)
- §13 plan task breakdown → matches 14 tasks here (with §10 split into 11a + 11b as anticipated in spec)
- §14 out of scope → captured in PR body Backlog section

**Placeholder scan**: All tasks have concrete content blueprints. The "per-module grep-based content" for Tasks 6 + 7-10 is properly framed: the plan specifies the exact grep command + format template; the inline executor fills in module-specific tables from grep output.

**Type consistency**: All file paths consistent. All section headings match (e.g., `## Consumers`, `## データ構造`, `## 拡張方法 (Extensibility)`). Cross-references between Task 1 (MODULES.md) and Task 2 (SCENARIO_FLAGS.md) are mutual and consistent.

**Inline-recommended over subagent-driven**: pure docs PR, single-author content writing, tight cross-references between new files. Phase 2a/2b/PR1/PR2 inline pattern is the right fit.
