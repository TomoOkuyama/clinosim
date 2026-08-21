# Data-Model & Completeness Conventions — cross-session compliance rules

**Status:** Active (2026-07-06, established in session 38).
**Audience:** any session or implementation agent working on one of
the chains in the FHIR completeness fix-point registry
(`docs/design-notes/2026-07-06-fix-point-registry.md`).
**Positioning:** a supplement to
[`implementation-rules.md`](implementation-rules.md) (whole-project
invariants) and
[`fhir-data-generation-logic.md`](fhir-data-generation-logic.md)
(Layer 4). This file adds only the rules that are specific to
completeness fixes — existing rules are **not restated; they are
cross-linked** (duplication is against this project's own conventions).
When in doubt, apply the four judgment axes: **data quality,
clinical coherence, maintainability, conceptual fit**.

---

## 0. Read first (prerequisites)

1. [`implementation-rules.md`](implementation-rules.md) — the
   whole-project invariants (canonical helpers, determinism,
   silent-no-op defense, verification gates). **The rules in this
   supplement do not override them; they add to them.**
2. [`../design-notes/2026-07-06-fhir-completeness-and-data-model-unification.md`](../design-notes/2026-07-06-fhir-completeness-and-data-model-unification.md) — background and goals (why this convention set is needed).
3. `docs/design-notes/2026-07-06-fix-point-registry.md` — status,
   dependencies, and verification steps for the FP you are about to
   tackle.

---

## 1. FHIR Completeness Contract (the project's new first principle)

Promote **"the clinical intent an author wrote in a YAML file must
reach the FHIR output"** to an invariant. Three classes of
incompleteness are defined (background doc §1); none may be
introduced anew:

- **C1 Silent-drop forbidden.** A YAML key that is silently defaulted
  or discarded before being read is disallowed.
- **C2 Degenerate forbidden.** A FHIR element that ships as a no-op,
  a placeholder, or a value identical across every patient is
  disallowed.
- **C3 Missing-structure forbidden.** A resource or event expected by
  the disease / encounter definition and not emitted is disallowed.

Every new feature or fix must prove for itself that it introduces no
new C1 / C2 / C3 (see the §5 checklist).

---

## 2. YAML key lifecycle rules (C1 defense)

### 2.1 "Do not ship a YAML key that is never read"

When you add a new YAML key, either wire the consumer code in the
**same PR** or do not add the key. This is the YAML analogue of
`implementation-rules.md` §9-5 "no aspirational scaffolding".

### 2.2 Make `extra="forbid"` the default for YAML-loaded Pydantic models

- `PatientProfile` (`config.py:101`) is the reference. Every new
  YAML-loaded `BaseModel` gets `model_config = ConfigDict(extra="forbid")`
  **from the start**.
- Existing models with `extra="ignore"` (i.e. silent-drop) are
  scheduled for removal (FP-YAML-3 migrates `DiseaseProtocol`).
- `extra="allow"` (as in `EncounterConditionProtocol`) combined with
  raw-dict returns is "deliberately unvalidated", but that path
  should also be closed in the future by cross-checking against
  canonical constants (`SUPPORTED_*` diff detection,
  `implementation-rules.md` §9-2).

### 2.3 Defend the raw-dict path too

Disease YAML has two access routes: (A) `DiseaseProtocol(**data)`
attribute access and (B) raw-dict `.get()` calls in
`order/engine.py`. **`extra="forbid"` only defends route A.** Route
B must be funnelled through the owner module's accessor so that
unknown keys fail loudly at load time (FP-YAML-3). "Only one route
defended" is the J5 class regression (a single-venue wiring) all
over again.

### 2.4 Record intent even when deleting a key

If an orphan key cites clinical literature (TIMI, ACC-AHA, Tokyo
Guidelines, etc.), record "why we deleted rather than wired" in the
commit message or in `DESIGN.md` before removing it. Do not let the
intent behind the data asset disappear.

---

## 3. Severity single-source-of-truth rules (FP-SEV-MODEL / finalised in AD-67)

- The canonical source of severity is the **disease YAML
  `severity.distribution` × `modifiers`**. The owner is
  `clinosim/modules/disease/severity.py`. The locale-side
  `severity_beta` / `severity_minimum` have been removed —
  **do not resurrect them** (`test_completeness_invariants.py`
  enforces zero readers).
- Sampling uses `sample_severity(protocol, person, rng) -> (category, score)`
  (inpatient — also returns the continuous score) and
  `sample_severity_category(distribution, modifiers, person, rng, minimum) -> category`
  (ED shared). The category ↔ score boundaries are **defined once**
  in `SEVERITY_SCORE_RANGES` + `category_from_score`.
- **Forbidden**: hard-coded 0.3 / 0.7 thresholds at call sites
  (`category_from_score` is the single source). Do not carry the
  minimum in two places (unify in `minimum_severity` and clamp
  inside `sample_severity`).
- Inpatient (`population/engine` → `inpatient`) and ED
  (`emergency`) ride the same primitive.
- Modifier conditions split into person-derived (EVALUABLE) and
  disease-intrinsic (RESERVED_INTRINSIC, currently skipped). An
  unknown condition raises at load time via
  `_validate_severity_block`.

---

## 4. Do not create "generated but non-functional" (C2 defense)

### 4.1 Wire stage / severity together with the physiology consumer

Graded-stage diseases (CKD / HF / COPD / asthma / IHD wired in
session 37; I10 not yet = FP-I10) **may not** add a
`STAGE_SEVERITY` entry alone. You must land all four together:
(1) the stage → severity_score mapping,
(2) the `physiology/engine.py:initialize_state` consumer branch,
(3) the ripple through vitals / labs / prescriptions,
(4) the appropriate FHIR resource code.
"A severity_score no one reads" is C2.

### 4.2 The as-of-age pattern (FP-AGE reference implementation)

To render or compute time-dependent attributes (like age) correctly
across a multi-year simulation, use the **as-of-date function**
promoted from `immunization/engine.py:36-39 _age_on(dob, on, fallback)`
into `_shared`. The call site passes the event date
(`event.timestamp`).

- **Group that does not touch the seed path** (output / narrative /
  LLM / labs): as-of-ifying only produces a display-value diff in
  the goldens → low risk.
- **Group that touches the seed path** (incidence decisions — RNG
  branches change): full golden regeneration + an ADR note is
  mandatory → separate phase.
- Groups that legitimately freeze at snapshot time (identity /
  household / height shrinkage) are not as-of-ified.

**Generalise this "does it touch the seed path?" two-phase split to
every determinism-touching change.**

### 4.3 Do not overload the wrong FHIR code

Forbidden: reusing a `Condition.stage` SNOMED type — for example,
"Tumor stage finding" (385356007) — for hypertension because "it's
close enough". If the correct code is not in the codes YAML, verify
against an authoritative source (NLM / WHO) and add it
(`implementation-rules.md` §6 — no fabrication).

---

## 5. Clinical authoring rules (C3 defense)

### 5.1 Think of `course_archetypes` and `complications` together

When adding `course_archetypes` to an acute disease, the source of
worsening events (ICU transfer, DVT, delirium, SSI) is the
`complications:` block (course archetype = trajectory shape,
complications = discrete events). Trauma / post-op diseases have a
fallback trajectory tuned for inflammatory internal medicine that
is clinically incoherent for them, so write **`complications`
first, or together with `course_archetypes`** — never after. Template:
`bacterial_pneumonia.yaml:581-655`.

### 5.2 Per-disease verification for disease authoring

Once you write new `course_archetypes` / `complications`, generate
that disease's cohort and grep the real output for
(a) worsening courses firing at non-zero rate and (b) the additional
Observation / narrative appearing on worsening days. Green tests
alone cannot catch C3 (`implementation-rules.md` §8 "grep real
output").

---

## 6. Implementation-session checklist (completeness-fix specific)

In addition to the chain workflow in `implementation-rules.md` §0:

1. **Before starting**: confirm the FP's Status and dependencies in
   the registry. If a dependency FP is not DONE, respect the order
   (especially FP-YAML-1 → 2 → 3, and FP-SEV-MODEL →
   archetype_modifiers / I10).
2. **C1 check**: every key in the YAMLs you touched is consumed
   (both routes A and B). Every existing YAML still loads under a
   model you added or enabled `extra="forbid"` on.
3. **C2 check**: the FHIR element you added is non-degenerate in
   the cohort (distributed across patients, not a default fallback).
4. **C3 check**: the resource that the disease / encounter expects
   actually shows up in the real output (grep).
5. **Determinism**: decide whether you touched the seed path →
   declare "byte-preserving refactor" or "new-feature with golden
   regeneration".
6. **On DONE**: update the registry's Status to DONE + append the
   PR / commit. If the completeness gate (FP-COMPLETENESS-GATE)
   already exists, get the audit completeness axis to green.

---

## 7. I / O interface at a glance (the boundaries this fix set touches)

| Boundary | Input | Output | Canonical seam |
|---|---|---|---|
| Disease YAML → simulation | `reference_data/*.yaml` | `DiseaseProtocol` (attribute) / raw dict (order) | `load_disease_protocol` (A) / owner accessor (B, cleaned up in FP-YAML-3) |
| Severity decision | `event.severity` (float) / protocol distribution | `"mild|moderate|severe"` + score | `severity_from_protocol` (added in FP-SEV-MODEL) |
| Age reference | `dob` + event date | as-of age (int) | `_age_on` (promoted to `_shared` in FP-AGE) |
| code → display | `(system, code, lang)` | display string | `code_lookup` / `system_key_for` (existing) |
| CIF → FHIR | structural + narrative CIF | FHIR R4 NDJSON | `_fhir_*` builders (registry-registered, existing) |
| Completeness verification | cohort NDJSON | AxisResult | `clinosim/audit/axes/completeness.py` (added in FP-COMPLETENESS-GATE) |

Japanese counterpart: [`data-model-and-completeness-conventions.ja.md`](data-model-and-completeness-conventions.ja.md).
