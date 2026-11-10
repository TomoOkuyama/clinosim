# Design Guides — where the rules and specs live

The index of the design guides for every contributor (human or agent). It has three parts: the coding rules that apply to every change, the binding specs for each area of the simulator, and background reading for onboarding. When a guide and the code disagree, fix one of them in the same PR — the guides are meant to be true.

## 1. Coding rules (read before writing any code)

| Document | What it covers |
|---|---|
| [Coding rules in `CONTRIBUTING.md`](../../CONTRIBUTING.md#coding-rules) | The five rules every contributor follows (code and data separated, multilingual output, codes, country handling, determinism), each linked to its binding spec. |
| [`implementation-rules.md`](implementation-rules.md) | **Start here.** The rules every change follows — workflow, coding standards, architecture invariants, determinism, canonical helpers, loaders, verification gates, silent-no-op defence — and a map from each concern to its binding spec. |
| [`shared-helpers-catalog.md`](shared-helpers-catalog.md) | Which shared helper to use for X: every cross-module helper by concern, with its path and governing spec. Look here before writing a small utility. |
| [`documentation-and-code-quality-policy.md`](documentation-and-code-quality-policy.md) | Documentation language and EN/JA pairing, self-contained OSS quality, source-comment language, constants placement, dead-code hygiene. |

## 2. Binding specs (read the one for the area you are changing)

Each spec states rules, the canonical code that implements them and the guard tests that enforce them. A change in that area follows the spec, or changes the spec in the same PR.

| Read before you… | Spec |
|---|---|
| add or change a code, a display text, a code mapping, a name-resolution function, localization or a fallback | [`code-mapping-and-localization-spec.md`](code-mapping-and-localization-spec.md) |
| draw a random number, derive a seed or read a clock | [`determinism-and-rng-spec.md`](determinism-and-rng-spec.md) |
| add or read a reference-data YAML, an age-banded table or a constant | [`configuration-and-reference-data-spec.md`](configuration-and-reference-data-spec.md) |
| place, hold, administer, stop, prescribe or code a medication | [`medication-lifecycle-spec.md`](medication-lifecycle-spec.md) |
| order, derive, flag or link a lab result | [`lab-orders-and-results-spec.md`](lab-orders-and-results-spec.md) |
| plan a document, add a section or word a clinical fact | [`narrative-and-document-generation-spec.md`](narrative-and-document-generation-spec.md) |
| create or finish an encounter, apply the snapshot or finish a FHIR resource | [`encounter-lifecycle-and-export-spec.md`](encounter-lifecycle-and-export-spec.md) |
| implement a FHIR completeness fix (unread YAML keys, unconsumed elements, `extra="forbid"`, stages, as-of age) | [`data-model-and-completeness-conventions.md`](data-model-and-completeness-conventions.md) |
| sync code displays with an authoritative source (LOINC, YJ, ICD-10, MHLW tables) | [`code-display-authoritative-sync.md`](code-display-authoritative-sync.md) |

## 3. Background and onboarding

| Document | When to read |
|---|---|
| [`project-concept-and-design.md`](project-concept-and-design.md) | First, for the project concept (the nine requirements), the end-to-end pipeline and the two-layer narrative design. |
| [`data-generation-walkthrough.md`](data-generation-walkthrough.md) | After the concept: how one patient record is born, from population to CIF to FHIR, with the real file and function names. |
| [`MODULES.md`](../../MODULES.md) | The module map: every package under `clinosim/modules/`, the dependency graph, data flow and enricher order. |
| [`docs/CONTRIBUTING-modules.md`](../CONTRIBUTING-modules.md) | Before adding a module: Base vs Module, canonical layout, loader / sub-seed / registry usage, verification (byte-diff vs audit). |
| [`.github/TEMPLATE_MODULE_README.md`](../../.github/TEMPLATE_MODULE_README.md) | When creating a module skeleton: the README and path-constant boilerplate. |
| [`fhir-data-generation-logic.md`](fhir-data-generation-logic.md) | When adding or extending a FHIR builder (`clinosim/modules/output/fhir_r4/<theme>/`). Subordinate to the code-mapping spec on display rules. |
| [`clinosim/modules/output/SPEC.md`](../../clinosim/modules/output/SPEC.md) | When touching clinical documents or narratives: the two-pass CIF (structural + narrative, AD-65). |
| [`SCENARIO_FLAGS.md`](../../SCENARIO_FLAGS.md) | When touching lab values or scenario / medication flags (`causes_X`, `on_warfarin`). |
| [`docs/architecture/adr-history.md`](../architecture/adr-history.md) | When you need the reasoning behind a design decision (ADRs AD-1 to AD-71). |

Historical plans that are no longer current live under [`docs/history/`](../history/).

Japanese counterpart: [`README.ja.md`](README.ja.md).
