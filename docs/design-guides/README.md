# Design Guides — reading path for new module authors

An index for the new contributor (human or AI) adding a module to
clinosim. Read the entries below in the order shown. (0) – (4) are
mandatory for everyone; (5) – (8) apply only when you are touching
that specific surface.

| # | Document | When to read |
|---|---|---|
| 0a | [`project-concept-and-design.md`](project-concept-and-design.md) | **First.** Project concept (the 9 requirements), the end-to-end pipeline, the two-layer narrative design, current state and roadmap catch-up. |
| 0b | [`implementation-rules.md`](implementation-rules.md) | **Before writing any code.** The distilled invariants every implementer must obey — workflow discipline, determinism, canonical helpers, silent-no-op defense, verification gates. |
| 0c | [`data-generation-walkthrough.md`](data-generation-walkthrough.md) | **After the concept doc.** How one patient record is born: population → life events → encounter simulation → CIF → FHIR, walked end-to-end with actual file and function names. Covers the three-stage CLI, enrichers, and extension entry points. Onboarding material for new contributors. |
| 1 | [`MODULES.md`](../../MODULES.md) | Overview of all 33 modules (`clinosim/modules/` packages), their dependency graph, and data flow, on a single page. |
| 2 | [`docs/CONTRIBUTING-modules.md`](../CONTRIBUTING-modules.md) | Before implementation. The practical playbook — Base / Module classification, canonical layout, loader / sub-seed / registry usage, verification triage (byte-diff vs. 3-axis DQR). |
| 3 | [`.github/TEMPLATE_MODULE_README.md`](../../.github/TEMPLATE_MODULE_README.md) | When creating a new module skeleton. Copy the README and path-constants boilerplate from here. |
| 4 | Curated ADRs in [`DESIGN.md`](../../DESIGN.md) | When you need the reasoning behind a design decision. Start with the 9 core ADRs — AD-16, AD-17, AD-25, AD-30, AD-55, AD-56, AD-59, AD-60, AD-65 (one-line summaries in the "最初に読む ADR" table of `CONTRIBUTING-modules.md`). |
| 5 | [`clinosim/modules/output/SPEC.md`](../../clinosim/modules/output/SPEC.md) | Only when you touch clinical documents or narratives. The canonical spec for two-pass CIF (structural + narrative separation, AD-65). |
| 6 | [`docs/design-guides/fhir-data-generation-logic.md`](fhir-data-generation-logic.md) | Only when you add or extend a FHIR builder (`_fhir_*.py`, Layer 4). Covers `code_lookup`, URIs, multilingual display, and the anti-patterns. |
| 7 | [`SCENARIO_FLAGS.md`](../../SCENARIO_FLAGS.md) | Only when you touch lab values or scenario / medication flags (`causes_X`, `on_warfarin`). Lists every flag and the procedure to add one. |
| 8 | [`data-model-and-completeness-conventions.md`](data-model-and-completeness-conventions.md) | Only when you implement a FHIR completeness fix-point (severity unification, orphan YAML keys, `extra="forbid"`, I10 stage, `person.age`, `course_archetypes`). Documents the prohibitions on C1 / C2 / C3 incompleteness and the as-of-age pattern. The registry lives at `docs/design-notes/2026-07-06-fix-point-registry.md`. |

Japanese counterpart: [`README.ja.md`](README.ja.md).
