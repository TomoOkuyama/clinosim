# clinosim Project Concept & Design — catch-up doc

**Status:** Active (2026-07-03, established in session 32).
**Audience:** any new developer or implementation agent (Opus 4.7,
etc.) reading their first "what is this project and how is it built"
overview. The rulebook lives in
[`implementation-rules.md`](implementation-rules.md); the detailed
architecture lives in `DESIGN.md` (the full ADR set).

---

## 1. Project concept (the goal)

**clinosim is a high-quality generator of EHR / EMR sample datasets.**
Every judgment axis is **data quality, clinical coherence, and
realism of the data.**

The 9 confirmed user requirements (verified at the 2026-07-02 grand
design review):

1. High-quality EHR / EMR dataset generation is the goal (sample
   data for research, development, product demos).
2. Output is multi-format by design, **FHIR R4 first** (Bulk Data
   NDJSON). Future: SS-MIX2 / CSV / HL7 v2.
3. Data is born from an event-driven **forward simulation**:
   demographics → outpatient / disease scenario firing → hospital
   visit event firing → labs / interview / procedure → condition
   change.
4. Main pipeline + module composition. **Module responsibilities
   are clearly decomposed** so that adding a module alone can
   generate a new kind of data.
5. The intermediate representation **CIF** (Clinical Intermediate
   Format) is a **two-layer split: structural CIF + narrative CIF**.
   FHIR is generated from both.
6. **Narrative is swappable**: template generation → later regenerate
   with Bedrock / local LLM → regenerate FHIR — each stage runs
   independently (narrative is versioned).
7. Narrative has a per-information-type prompt and is generated
   through a **unified interface** whose input is patient profile /
   scenario / structural CIF.
8. **Data-driven**: static definitions (vital-sign values, codes,
   etc.) are not written in Python — they live in YAML.
9. **Multi-country**: US default + JP already implemented. Country-
   specific information (My Number, insurance, care conventions) is
   defined in YAML / JSON so that other countries can be added
   through the same shape.

## 2. Pipeline overview

```
 population (demographics / households)                   Layer 0-1: reference YAML
   └→ scenario firing (32 diseases / 46 encounters)         (disease / encounter protocols,
        └→ encounter simulation (inpatient / ED / outpatient) locale, codes)
             ├ physiology-state transition (daily loop)
             ├ orders / labs / vitals / MAR / procedures
             ├ POST_ENCOUNTER enrichers (device → hai → antibiotic → imaging → triage → nursing → document)
             └→ POST_RECORDS enrichers (nursing flowsheet, immunization, …)
   ↓
 ★ CIF (the sole simulation output, AD-17)
   ├ cif/structural/patients/<enc>.json   … Stage 1, structural, immutable
   └ cif/narratives/<version>/documents/… … Stage 2, narrative, versioned + swappable (AD-65)
   ↓
 format adapters (read only from CIF)
   ├ FHIR R4 NDJSON (the _fhir_* builders, registry-registered) ← the current primary output
   └ CSV / (future: SS-MIX2, HL7 v2)
```

- **Three-stage CLI (AD-37)**: `clinosim simulate` (→ structural CIF)
  → `clinosim narrate --provider template|mock|ollama|bedrock` (→
  `narratives/<version>/`) → `clinosim export-fhir --narrative-version X`.
  That is the concrete embodiment of requirement 6 (swappability).
- **Determinism (AD-16)**: every random draw comes from a hierarchical
  sub-seed. Same seed = byte-identical output (wall-clock reads were
  eliminated project-wide in the determinism chain, session 34).
- **★ For the detailed version of this diagram** (an end-to-end
  trace with actual file and function names), see
  [`data-generation-walkthrough.md`](data-generation-walkthrough.md).
  New contributors should grasp the overview here first, then follow
  the walkthrough to trace one patient's generation concretely.

## 3. Layers and responsibility split

| Layer | Contents | Location |
|---|---|---|
| 0 | International code systems (LOINC / ICD / RxNorm / JLAC10 …, EN-first) | `clinosim/codes/` |
| 1 | Reference-data YAML (disease / lab / locale / hospital config) | `modules/*/reference_data/`, `locale/`, `config/` |
| 2 | Loader (cached + fail-loud validation) | inside each module |
| 3 | CIF generation (simulator + 33 modules) | `simulator/`, `modules/` |
| 4 | Output adapter (FHIR builders and others) | `modules/output/` |

- **33 modules** (see `MODULES.md` for the map). They split into
  always-on (mandatory in the clinical cascade: device → hai →
  antibiotic / imaging / document / triage / nursing_assignment,
  etc.) and opt-in.
- Inter-module dependencies are limited to those declared in a
  module's README `Dependencies` block plus `types/` / `codes/` /
  `locale/`. Writes into CIF go through `extensions[<module>]` (a
  new typed field on a core type is Base-only).
- **Extension goes through three registries** (AD-56 / AD-58):
  adding a FHIR resource = `register_bundle_builder`; adding an
  output format = `register_output_adapter`; adding a generation
  pass = `register_enricher`. The dispatch body itself is never
  edited.

## 4. Narrative generation design (the concrete form of requirements 5–7)

```
 Stage 1 (inside simulation, document module):
   Emits only the ClinicalDocument stub (metadata + author + encounter
   binding, narrative=None).

 Stage 2 (post-simulation, narrate CLI):
   NarrativePass (ABC; walk = (doc_type, language) → patients in sorted
   order = optimal for the LLM cache)
     ├ TemplateNarrativePass … generator = TemplateNarrativeGenerator
     └ LLMNarrativePass      … generator = LLMNarrativeGenerator
           └ apply_replacement_strategy(spec.stage2_strategy)
                ├ template_only  → template output as-is
                └ template_seed  → only the section listed in
                                   spec.llm_enabled_sections; the
                                   template text is the seed the LLM
                                   rewrites (strategy D+B)
                     └ LLMService.complete_prompt()  ← the sole seam
                                                       for LLM calls
                                                       (AD-11)
                          ├ prompt: llm_service/prompts/{en,ja}/*.yaml (AD-40)
                          ├ retry + PromptCache (disk, prompt-hash)
                          └ NarrativeCache (in-memory, clinical-key + seed hash)
```

- **Unified input IF** = `NarrativeContext` (patient / encounter /
  labs / vitals / meds / diagnoses / disease_protocol / severity /
  archetype / day_index / narrative_spine / materialized_facts).
  Stage 2 assembles it from structural CIF (real schema wired
  during chain 1a).
- **Generator contract** = the `NarrativeGenerator` Protocol
  (`types/document.py`), injected into the Pass.
- **Document type** is defined in `document_type_specs.yaml`
  (YAML-driven: LOINC / sections / encounter_types_supported /
  generation_frequency / stage2_strategy). Currently 9 doc types
  (H&P, progress, discharge, three nursing types including the
  3-shift shift note, outpatient SOAP, two ED types).
- **Verification**: template / mock = golden byte-diff (AD-66).
  Real LLM = `check-narratives` (a 5-axis semantic check: structure
  / facts_used / prohibited patterns / expected phrases / numbers).
- **Real LLM generation runs on a separate server** as an operational
  decision (2026-07-03). Runbook =
  `docs/design-notes/2026-07-03-remote-llm-narrative-workflow.md`.

## 5. Multi-country design (requirement 9)

- Strict separation between `codes/` (international standards,
  locale-independent, EN required) and `locale/<country>/` (names /
  addresses / reference intervals / code_mapping) — AD-35.
- CIF is language-neutral (codes only, AD-30). Display is resolved
  at output time via `code_lookup(system, code, lang)`.
- Country dispatch goes through `is_jp()` / `resolve_lang()`;
  country → code-system dispatch through `system_key_for()` (single
  source).
- JP-specific: insurance / My Number (identity module, opt-in),
  long-term-care level, JLAC10 / YJ / K-code, JP-Core-compliant
  FHIR. The audit enforces **zero Japanese in US output; every JP
  display in Japanese for JP output**.
- Adding a new country = locale directory + language key added to
  the codes YAMLs + demographics YAML — that is the shape of the
  extension surface.

## 6. Quality-assurance machinery (the project's defining feature)

| Mechanism | Role |
|---|---|
| `pytest -m unit / integration / e2e` | Three ordinary test tiers (1000+ / 264 / 35) |
| `pytest -m regression` (opt-in) | Narrative goldens byte-diff for the 6 canonical patient profiles (template + llm-mock, AD-66) |
| byte-diff | The merge gate for refactor PRs (FHIR NDJSON + narratives sha256 match) |
| `clinosim audit run` (AD-60) | 4-axis audit: structural / clinical / jp_language / **silent_no_op** (`lift_firing_proof` = proof that the feature actually fired) |
| `check-narratives` | The semantic gate for real LLM narratives |
| Adversarial review | Per-PR 5-lens review (findings must be evidenced) → fix → merge chain culture |

**Silent-no-op — "it looks like it ran but it did not fire" — is the
biggest enemy of this project.** Historical incidents (PR-90 / J5 /
C-1) drove a three-layer defense across the codebase: fail-loud
validation, canonical constants, and firing counters. Details:
`implementation-rules.md` §9.

## 7. Current state and roadmap (as of 2026-09-02)

- **Version**: v0.5.0 (v0.6.0 release-gate — all 3 META Issues
  (#914 / #957 / #757) closed; awaiting tag). Production cohorts of
  US p=10k / JP p=5k generate with all audit axes PASS. 32 diseases
  + 46 outpatient / ED conditions, 33 modules, 25+ FHIR R4 resource
  types emitted. Longitudinal service lines (oncology + obstetrics —
  cancer chronic markers × chemo regimen cycles + per-cycle drug
  MedicationRequest/Administration × radiation therapy Procedure ×
  **time-boxed `TemporalStatePeriod` pregnancy lifecycle**
  (conception → prenatal visits at gestational weeks 12/24/36 →
  delivery encounter → postpartum) × newborn Patient chain × abortion
  outcome × Z37 past-birth problem-list-item (state_history-derived))
  landed with META #957 Incr 1 (session 97, PR #1051); see
  `docs/reference/oncology-obstetric-service-lines.md` + AD-71
  `docs/architecture/architecture-notes.md` §9.
- **β-JP-1 chain 2 (MHLW forms) is complete** (sessions 33-36): the
  4-of-4 documents — inpatient care plan / nursing-need A, B, C
  evaluation forms (there is officially no "D table" form; the
  wording was corrected in session 36) / nutrition-management plan
  / rehabilitation-implementation plan — have all landed.
- **Shared-logic unification, determinism chain, AD-30 chain, and
  display-dict → codes-YAML migration are complete** (sessions
  31-37): unified narrative IF (N-chain), context wiring, LLM
  goldens + semantic check, elimination of every wall-clock read,
  removal of display-in-CIF vestiges, 8 new codes YAMLs + dual-
  access write-side unification (`set_attr_or_key` /
  `get_or_create_container`).
- **★ FHIR completeness chain complete** (session 38, AD-67 / 68 /
  69): under the goal of "drive the number of incompleteness states
  in the final FHIR output (C1 silent-drop / C2 degenerate / C3
  missing-structure) to zero", 9 chains were digested — severity
  single source (disease YAML canonical, `disease/severity.py`,
  `severity_beta` removed) / `archetype_modifiers` wired /
  `DiseaseProtocol` `extra="forbid"` / `diagnostic_difficulty`
  silent-drop fix / I10 stage → BP physiology consumption / HF +
  subdural `course_archetypes` + `complications` / a completeness-
  invariant gate. Tracking ledger =
  `docs/design-notes/2026-07-06-fix-point-registry.md`; conventions
  = `docs/design-guides/data-model-and-completeness-conventions.md`.
- **Current phase**: the main chains of β-JP-1 and the core C1 / C2
  / C3 of FHIR completeness are done. Next candidates are β-2
  (surgical / anaesthetic records — brainstorming required before
  starting, large in scope) or the remaining completeness work
  (FP-AGE `person.age` multi-year / FP-ARCH-2 / 3 with the 7
  remaining trauma disease `course_archetypes` / cross-cutting
  follow-up). Details live in the fix-point registry and in the
  various deferred sections tracked on the GitHub Issues board
  (`docs/roadmap.md`). The pre-Issues `TODO.md` ledger has been
  retired.
- **Subsequent chains** (in priority order per
  `docs/design-notes/2026-07-02-grand-design-review-and-roadmap.md`
  §4, though the completed parts above take precedence): β-2
  (surgical / anaesthetic) → γ / δ / ε → SS-MIX2.
- **The canonical source for deferred items**: the GitHub Issues
  board (see `docs/roadmap.md`). Before starting work, always read
  `.resume-prompt.md` (the latest session hand-off).

## 8. Glossary

| Term | Meaning |
|---|---|
| CIF | Clinical Intermediate Format. The sole simulation output (two layers: structural + narrative). |
| Chain | A one-theme unit of work (spec → implementation → adv review → merge, usually one PR). |
| adv-1 / 5-lens | Pre-merge adversarial review (silent-no-op / data unification / FHIR·JP Core / determinism / spec-alignment — the 5 viewpoints). |
| Golden | The expected-output JSON for a canonical patient profile (for byte-diff regression). |
| DQR | Data Quality Review (a 3-axis structural / clinical-coherence / JP-language review document under `docs/reviews/`). |
| lift_firing_proof | The mechanism in the audit's silent_no_op axis that proves "the feature actually fired" as an equality. |
| PR-90 / J5 / C-1 | Names of historical silent-no-op incidents (see `implementation-rules.md` §9). |
| Scenario spine / facts | The set of fact tags extracted from structural CIF for narrative generation (the basis of hallucination prevention). |

Japanese counterpart: [`project-concept-and-design.ja.md`](project-concept-and-design.ja.md).
