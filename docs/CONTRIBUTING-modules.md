# Contributor Guide: adding a module / plug-in

This document is the practical playbook for a new contributor to
**add a module / plug-in to clinosim, generate data, and correctly
choose which data or code to use**. Architectural principles (ADRs)
live in `DESIGN.md`; the overview of the conventions lives in
`AGENTS.md`. This document does not duplicate them — it concentrates
on **HOW-TO**.

> **This document is centred on the CIF-generation layer** (Layers
> 1-3 = reference YAML, loader, CIF-generation module). **To add or
> extend a FHIR builder (Layer 4 = `_fhir_*.py`)**, see
> [`docs/design-guides/fhir-data-generation-logic.md`](design-guides/fhir-data-generation-logic.md)
> (BundleContext / code_lookup / multilingual display / identifier-
> system conventions / register_bundle_builder).

> **When creating a new module**: start by copying
> [`.github/TEMPLATE_MODULE_README.md`](../.github/TEMPLATE_MODULE_README.md).
> For an overview of all 33 modules (counting rule: packages under
> `clinosim/modules/`; non-package files such as `_shared.py` are
> excluded), see [`MODULES.md`](../MODULES.md). For picking the PR
> verification approach, see the "PR verification guide: byte-diff
> vs. 3-axis DQR" section below. For the whole reading order, see
> [`docs/design-guides/README.md`](design-guides/README.md).

Canonical source-code paths:
- Enricher registry: `clinosim/simulator/enrichers.py`
- Output-adapter registry: `clinosim/modules/output/adapter.py`
- FHIR bundle-builder registry: `clinosim/modules/output/fhir_r4_adapter.py`
- Shared types: `clinosim/types/`
- Code systems: `clinosim/codes/`
- Locale data: `clinosim/locale/`

## First ADRs to read (curated; full set in `DESIGN.md`)

`DESIGN.md` contains 55+ ADRs, but a new module author should grasp
these 9 first:

| ADR | One-line summary |
|---|---|
| AD-16 | Determinism: same seed + same config = byte-identical structural output. Every RNG must derive from a sub-seed of `numpy.random.Generator` (`random.random()` is forbidden). |
| AD-17 | CIF is the sole simulation output. Format adapters (FHIR / CSV) read only from CIF — they do not touch simulation internals. |
| AD-25 | CIF is language-neutral. Localization (term translation, units, formatting) happens at output time (the only country-specific data at CIF-generation time is names). |
| AD-30 | Code is the truth: CIF holds codes only; display text is resolved at output time via `code_lookup()`. |
| AD-55 | The three classes of data addition: Base (always-on, extends core types) / opt-in Module / always-on Module (near-essential clinical cascade). |
| AD-56 | Extension goes through the registries (`register_bundle_builder` / `register_output_adapter` / `register_enricher`). Never edit the core dispatch. |
| AD-59 | Per-order lab RNG isolation: a YAML lab-order edit must not shift unrelated patients' cohorts (`panel_specimen_seed` / `individual_lab_seed`). |
| AD-60 | `clinosim audit run` = the unified verification gate for new-feature PRs (4 axes: structural / clinical / jp_language / silent_no_op). |
| AD-65 | Two-pass CIF: structural (Stage 1, immutable) and narrative (Stage 2, versioned) are separated at file level. Canonical spec = [`clinosim/modules/output/SPEC.md`](../clinosim/modules/output/SPEC.md). |

---

## Decision: Base or Module?

When adding new data or a new feature, first decide between **Base
(always-on, extends the core)**, **opt-in Module (gated by
`SimulatorConfig.modules` + `config.module_enabled()`)**, and
**always-on Module = near-essential clinical cascade** (added
2026-06-25 as AD-55 PR3b-1 supplement: a module that inevitably
emits a clinically-coherent extension on top of an upstream
`extensions[X]` — e.g. `device` / `hai` / `antibiotic` / `imaging`)
(AD-55).

**Always-on Module precedents (as of 2026-07-01):** (The Tier 1 #3
roadmap = [`docs/design-notes/2026-06-30-tier1-document-and-event-density-master-plan.md`](design-notes/2026-06-30-tier1-document-and-event-density-master-plan.md).)
- `device` (PR-A): ICU device placement (POST_ENCOUNTER order=70).
- `hai` (PR-B): CDC NHSN HAI sampling (POST_ENCOUNTER order=80).
  Requires `extensions["device"]`.
- `antibiotic` (PR3b-1): empirical antibiotics for HAI
  (POST_ENCOUNTER order=85). Requires `extensions["hai"]`.
- `imaging` (Tier 1 #2, AD-62): imaging metadata chain
  (POST_ENCOUNTER order=90). Generates `extensions["imaging"]`
  only for encounters whose disease YAML declares `imaging_orders`;
  emits ImagingStudy + Endpoint + radiology DR + imaging SR. Does
  not depend on upstream extensions (independent from device / hai).
- `allergy` (Tier 1 #3, AD-63): AllergyIntolerance 8-field SNOMED-
  coded schema upgrade (POST_RECORDS order=65). Samples allergies at
  a 15 % prevalence into `PersonRecord.allergies: list[Allergy] | None`;
  `_fhir_allergy_intolerance.py` emits them. Replaces the inline
  sampling in `activator.py`.
- `document` (Tier 1 #3, AD-63): template-driven clinical-document
  emission from Stage 1 (POST_ENCOUNTER order=95). Writes
  `ClinicalDocument` / `ClinicalImpressionRecord` into
  `extensions["document"]` + `extensions["clinical_impressions"]`;
  three FHIR builders emit them
  (`_fhir_document_reference.py` /
  `_fhir_composition.py` /
  `_fhir_clinical_impression.py`). `enabled=lambda c: True`; does
  not depend on `extensions["allergy"]` (the builder reads
  `patient.allergies` directly for allergy info).
- `triage` (Tier 1 #3 α-min-2, AD-64): samples ED encounter's
  triage level (JTAS / JP, ESI / US) + arrival_mode +
  acuity_score (POST_ENCOUNTER order=93). Writes to
  `EncounterRecord.triage_data`; `document_enricher` uses it to
  dispatch `ED_TRIAGE_NOTE` (LOINC 54094-8). `enabled=lambda c: True`,
  ED-only (non-ED encounters no-op early return).
- `nursing_assignment` (Tier 1 #3 α-min-2, AD-64): assigns a primary
  nurse to inpatient / ICU / rehab encounters (POST_ENCOUNTER
  order=94). Writes to `EncounterRecord.primary_nurse_id`;
  `_fhir_care_team.py` uses it for `CareTeam.participant[1]`.
  `enabled=lambda c: True`. **Note**: this module lives in the
  `modules/nursing/` directory but is the POST_ENCOUNTER `nursing_enricher`
  function (primary-nurse assignment). The same directory also holds
  the POST_RECORDS enricher responsible for the nursing flowsheet
  (NEWS2 / GCS / Braden / Morse). Do not confuse them.

### Decision checklist

If the answer is Yes to all of these, it is **Base**. If even one
leans No, it is an **opt-in Module**.

1. Is this data essential to almost every EHR? (e.g. admission
   basics, vitals, lab results.)
2. Does it exist in almost every encounter regardless of country /
   theme?
3. Should it live as a typed field on the CIF core type
   (`CIFPatientRecord` / `CIFDataset`) permanently?

Conversely, an **opt-in Module** if any of these apply:

- Scoped to a single theme (`identity` = residence / insurance
  number, `immunization` = vaccination).
- Only meaningful in a specific country (JP insurance numbers, etc.)
  or a user might reasonably want to turn it off.
- Can be written into `CIFPatientRecord.extensions[<module>]` without
  polluting the core type.

### Gate implementation (for opt-in)

An opt-in module is gated via `Enricher.enabled`. The correct idiom
is `config.module_enabled(name, default=...)` (AD-56).

```python
# in register_builtin_enrichers() in clinosim/simulator/enrichers.py
register_enricher(Enricher(
    name="immunization",
    stage=POST_RECORDS,
    run=run_immunization_enricher,
    order=200,
    enabled=lambda c: c.module_enabled("immunization", default=True),
))
```

> **Note (EXT-5):** `module_enabled()` is currently not wired in
> production; the `modules` dict is a dead key. New modules should
> gate via `module_enabled` as shown above so the advertised AD-56
> gate is actually active. Keeping `default=True` preserves the
> existing goldens.

### Locale-dependent signature convention

A function that loads locale-specific data (per-country prevalence,
reference ranges, code mappings, etc.) **must take a `country: str`
parameter** and return a no-op value (`{}` / `""` etc.) early for
unsupported countries:

```python
from functools import lru_cache

from clinosim.modules._shared import is_jp

@lru_cache(maxsize=2)
def load_rates(country: str = "JP") -> dict:
    """Load rates for ``country``. Returns {} for unsupported countries."""
    if not is_jp(country):        # always decide country through is_jp() (see "shared helpers" below)
        return {}
    with open(_LOCALE / "jp" / "...") as f:
        return yaml.safe_load(f)
```

Rationale — even when a module currently supports only one country
(e.g. `care_level` is JP-only), unifying the signature lets a future
US addition land without changing caller APIs. Hard-coding
`_LOCALE / "jp" / ...` without a country argument is a consistency
bug.

Combine with `@lru_cache(maxsize=...)` to avoid repeated loads (the
other modules — immunization / family_history / code_status — use
this same pattern).

---

## Module structure

Each module is a single package under `clinosim/modules/<name>/`.
**Its dependencies on other modules are limited to those declared
under `## Dependencies` in the README.**

### Canonical layout

```
clinosim/modules/<name>/
  __init__.py            <- re-export the public API via __all__ (do not leave empty)
  engine.py              <- pure-function set. No cross-module imports.
  protocol.py            <- (optional) Pydantic-validated YAML loader
  reference_data/*.yaml  <- data-driven definitions (validated by Pydantic)
  README.md              <- Japanese + English technical terms. Must have ## Dependencies.
```

### Shared helpers go into `clinosim/modules/_shared.py`

When multiple enrichers need the same helper (e.g. `get_attr_or_key(obj, name, default)`
for dict / dataclass dual attribute access), do not write a local
definition inside each module — put it in **`clinosim/modules/_shared.py`**.
New modules import it as:

```python
from clinosim.modules._shared import get_attr_or_key as _get
```

The `as _get` alias keeps a short local name and preserves call-site
readability. Promote a new cross-module helper into `_shared.py`
only **at the point a second module actually needs it** (YAGNI — if
only one module uses it, leave it local).

The helpers currently in `_shared.py` (`normalize_probabilities`
added in PR-A 2026-06-26; `is_jp` / `resolve_lang` added by the
2026-07-02 shared-logic unification):

- `get_attr_or_key(obj, name, default)` — dict / dataclass dual
  attribute access.
- `normalize_probabilities(probs, fallback="uniform") -> np.ndarray`
  — normalises a probability array to 1.0 (see "Probability-sampling
  convention" below).
- `is_jp(country) -> bool` — **the sole canonical idiom for the JP
  decision** (case-insensitive + strip normalisation).
- `resolve_lang(country) -> str` — **the sole canonical idiom for
  display-language selection** (JP → `"ja"`, else → `"en"`).

**Mandatory idiom for JP-gating / language selection (2026-07-02)** —
country decisions and display-language selection must go through
`is_jp(country)` / `resolve_lang(country)`:

```python
from clinosim.modules._shared import is_jp, resolve_lang

if is_jp(ctx.country):
    ...
lang = resolve_lang(ctx.country)   # "ja" / "en"
```

> **Anti-pattern:** do not write new hand-rolled country-decision
> variants (`country == "JP"` / `country.lower() == "jp"` /
> `str(country).upper() == "JP"` /
> `lang = "ja" if country == "JP" else "en"`). Before the shared-
> logic unification 5 divergent idioms coexisted, and case-handling
> differences could silently disable JP gating — a PR-90-class risk.
> `is_jp` / `resolve_lang` are the single normalisation point.

### Canonical form of path constants (established in PR-A 2026-06-26)

The **canonical pattern** for how a module loads reference_data or
locale data:

```python
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_REF_DIR = _HERE / "reference_data"        # if the module owns reference_data/
_LOCALE = _HERE.parents[1] / "locale"      # if the module reads clinosim/locale/
```

At call sites, assemble paths as `_REF_DIR / "X.yaml"` /
`_LOCALE / country / "X.yaml"`, avoiding inline `Path(__file__).parent / ...`.
Reasons:

- Anchoring on `_HERE` decouples `parents[N]` from the module's
  depth in the tree, avoiding the **fragile `.parents[2]` problem**
  (the old pattern in `immunization`).
- Unified naming (retiring the drift of
  `_REFERENCE_DATA_DIR` / `_DATA` / `_HAI_REF_DIR`) makes grep /
  refactor easy.
- Data-only module variants also adopt the same `_HERE` + `_REF_DIR`.

### `@lru_cache` `maxsize` convention (established in PR-A 2026-06-26)

| Loader signature | `maxsize` |
|---|---|
| `load_X() -> dict` (no parameter) | `1` |
| `load_X(country: str) -> dict` | `2` (US + JP) |
| `load_X(country: str, language: str)` | `4` (for future multilingual expansion; currently unused) |

`maxsize` only affects the eviction policy, but it is a
**load-bearing signal that makes intent legible**. Placing
`maxsize=4` on a country-only loader misleads reviewers into
thinking "planning for 4 countries?".

**Completed in PR-B1 (2026-06-27) + adversarial fix**: the residual
hand-rolled cache pattern (`global X; if X is None: ... else return X`
used in **6 loaders**) was retired, and every module's loader now
uses `@lru_cache` as the standard. Touch targets were
`clinosim/modules/encounter/protocol.py:load_all_encounter_conditions` /
`clinosim/simulator/helpers.py:_load_all_disease_protocols` /
`clinosim/modules/output/_fhir_diagnostic_report.py:load_panel_groups` /
`clinosim/modules/output/_fhir_localization.py`'s `_load_med_terms_ja`
+ `_load_drug_names_ja` + `_load_department_display`. Introducing a
global mutable `_cache` variable in a new module is forbidden (it
conflicts with the standard test pattern that uses
`load_X.cache_clear()` in `test_*` fixtures). The same PR also
removed the `try/except pass` silent-skip in
`clinosim/simulator/helpers.py:_load_all_disease_protocols`
(strengthening silent-no-op defense in line with the PR #102 three-
layer defense). **In the Step-1 brainstorming sweep, do not filter
grep by meaning like `grep -i "cache\|state\|memo"` — always use the
generic sentinel pattern `grep -E "^_[A-Za-z_]+: *.+ *= *None"`**
(PR-B1 adversarial-review lesson: the meaning filter produced a
false negative on caches like `_drug_names_ja`).

**Shared-logic unification (2026-07-02) also `@lru_cache`d the
protocol / config loaders**:
`load_disease_protocol(disease_id)` (`maxsize=64`) /
`load_encounter_condition(condition_id)` (`maxsize=64`) /
`load_healthcare_config(country)` (`maxsize=2`) /
`load_hospital_operations()` (`maxsize=1`).

> **Mandatory rule: a cached loader's return value is a shared
> instance — never mutate it.** The dict / Pydantic model returned
> from an `@lru_cache`d loader is a single object shared across all
> callers (Pydantic models are mutable by default; dicts are of
> course mutable). If a caller rewrites a field, the change silently
> propagates to every other caller in the same process — a PR-90-
> class hidden-state bug. Treat as read-only. If mutation is needed,
> the caller must `copy.deepcopy(data)` / `model.model_copy(deep=True)`
> first.

### Aggregate loaders live on the owner module (2026-07-02)

Do not write an aggregate loader that globs / walks another module's
`reference_data/` from an external package such as the simulator.
**The layout and validation of `reference_data` is the owner
module's responsibility** (responsibility-decomposition point); if
an external package knows the path structure, a layout change breaks
things silently.

- Canonical example: `load_all_disease_protocols()` is defined on
  `clinosim/modules/disease/protocol.py` (owner).
  `clinosim/simulator/helpers.py:_load_all_disease_protocols` is a
  thin re-export alias of the same `lru_cache` object, so existing
  callers and the `.cache_clear()` test pattern remain unchanged.
- Likewise, reading another module's YAML by direct path join is
  forbidden — use the owner module's public accessor (e.g. `modules/antibiotic`
  does not read `microbiology.yaml` directly; it imports
  `clinosim.modules.observation.microbiology.antibiotic_loinc_lookup()`).

### Probability-sampling convention (established in PR-A 2026-06-26)

Wrap every `rng.choice(items, p=weights)` call in
`normalize_probabilities()`:

```python
from clinosim.modules._shared import normalize_probabilities

probs = normalize_probabilities(weights)   # idempotent on already-normalized arrays
idx = int(rng.choice(len(items), p=probs))
```

Reason: `numpy.random.Generator.choice` **does not auto-normalise**
`p=` (a sum ≠ 1.0 raises `ValueError`). If the YAML is normalised
by hand, an editing mistake that breaks the sum causes either a
silent regression or a runtime crash. `normalize_probabilities` behaves
as follows:

- If already normalised: byte-identical with `np.asarray(probs, dtype=float)`
  (byte-diff invariant preserved).
- If not normalised: normalises.
- If `sum == 0`: falls back to uniform (`fallback="raise"` also
  available to raise `ValueError`).
- Negative weights raise `ValueError`.

Inline literals (e.g. `p=[0.6, 0.4]`) are trivially normalised and
do not need migration.

### Import-time cross-validation (canonical-constants gate)

A module whose YAML data embeds external IDs (SNOMED / LOINC /
antibiotic key, etc.) **cross-checks against the canonical set at
load time** and loud-fails on unknown keys via `ValueError` (a
structural defense against silent-no-op — the PR-90 lesson).
Precedents:

- `clinosim/modules/hai/__init__.py:load_hai_antibiogram` — 3-way
  validation of `HAI_TYPES` × `hai_organisms.yaml` SNOMED ×
  `ANTIBIOTIC_LOINC_LOOKUP`.
- `clinosim/modules/observation/microbiology.py:_validate_microbiology`
  — cross-checks the organism antibiogram key against the
  `antibiotics` set (migrated from silent skip to `ValueError` in
  PR-A 2026-06-26; expanded to 7 cross-refs by Fix #100 / #101).
- `clinosim/modules/antibiotic/audit.py:_validate_nhsn_resistance_bands`
  — validates the cohort / antibiotic in `_NHSN_RESISTANCE_BANDS`
  against the canonical set.
- `clinosim/modules/hai/engine.py:_validate_hai_organisms` —
  validates `hai_organisms.yaml` on `HAI_TYPES` × SNOMED-non-empty
  × non-negative-weight × non-zero-sum (this PR 2026-06-27).
- `clinosim/locale/loader.py:_validate_demographics` /
  `_validate_names` / `_validate_addresses` — validate
  `demographics.yaml`'s `lifestyle_distribution`, `names.yaml`'s
  `surnames` / `given_names`, and `addresses.yaml`'s `cities` on
  non-negative weight + sum > 0 (this PR 2026-06-27; the 4 main
  loaders are now complete).
- `clinosim/modules/antibiotic/engine.py:_validate_narrow_ladder` —
  **4-way validation** of `narrow_ladder.yaml`: `HAI_TYPES` ×
  `hai_antibiogram.yaml` (forward + reverse-coverage) ×
  `ANTIBIOTIC_DRUGS` + empty-container rejection (top-level / drug
  list) (PR3b-3 + adversarial-2 stage-3; reverse-coverage is a
  silent-no-op defense for when a new organism is added).
- `clinosim/modules/antibiotic/audit.py:_validate_narrow_rate_bands`
  — cohort-string-format check on `_NARROW_RATE_BANDS`
  (per-hai_type only, no slash) + required keys + range [0, 1] +
  empty-list rejection (PR3b-3 adversarial-1 / 2; a cohort-string-
  typo defense).
- `clinosim/modules/hai/engine.py:_validate_hai_rates` —
  `per_day_risk ∈ [0, 1]` + `source_device_type ∈ load_devices_config()["devices"]`
  (HAI sibling sweep 2026-06-29).
- `clinosim/modules/hai/engine.py:_validate_hai_codes` —
  `icd10_us_billable` / `icd10_jp_who` / `snomed` verified for
  membership directly against authoritative `cs.codes` via
  `_code_in_data()` (HAI sibling sweep 2026-06-29).
- `clinosim/modules/hai/engine.py:_validate_hai_specimens` —
  `specimen_snomed` / `test_loinc` authoritatively verified via
  `_code_in_data()` (HAI sibling sweep 2026-06-29).
- `clinosim/modules/hai/lab_lift.py:_validate_hai_lab_lift_config`
  — `ramp_peak_days > 0` + lift values ∈ [0, 1] + HAI_TYPES
  forward-coverage (HAI sibling sweep 2026-06-29; refactored from
  an inline check).

When a new module creates an external-ID-referencing YAML or a
probability-weight YAML, adopt the same pattern (wire `_validate_X(data)`
inside `load_X`; combine with `fallback="raise"` for symmetric
downstream defense). Do not forget **reverse-coverage** (canonical
set ⊆ data set) either — as revealed by the adv-1 stage-2 sibling
sweep, forward-only validation cannot prevent silent-no-op when a
new canonical entry is added.

### Per-dimensional cohort filter (PR3b-3 D1+D2, 2026-06-29)

When an audit clinical-axis gate is calibrated on a per-(dim1, dim2, …)
cohort threshold but the gate filter drops a dimension, the threshold's
meaning breaks at production scale (currently masked by the n<30
WARN guard). Example: PR3b-3 D1 filtered the band
`clabsi/3092008/cefazolin` (S. aureus only) by `hai_type` alone —
i.e. mixed S. aureus + S. epidermidis + E. coli measurement. D2's
empty-rate threshold (5 %) assumed an NHSN-panel-eligible
denominator, but was measured on the full HAI cohort denominator —
i.e. E. faecalis / C. albicans no-panel inflated both numerator and
denominator.

**New rule**: when implementing an audit gate, verify that the gate
filter consumes every dimension of the band cohort key. Either drop
an unconsumed dimension from the cohort key, or build a lookup map
for that dimension and incorporate it into the filter. **Build the
lookup map once per (country, audit-run) and reuse it across
multiple gates** (the D1 R-rate + D2 empty-rate sharing
`_organism_per_encounter` is the precedent).

- Precedent: `clinosim/audit/axes/clinical.py:_organism_per_encounter`
  — one-pass walk of `Observation.ndjson mb-org-*` builds
  `{enc_id: {organism_snomed, ...}}`, reused by D1 + D2.
- Precedent: `clinosim/audit/axes/clinical.py:_panel_eligible_organisms`
  — derives the panel-eligible set from `load_hai_antibiogram()`
  keys (no-panel is auto-excluded by antibiogram absence, not a
  hard-coded list).

### Validator ordering & reverse staleness (PR3b-3 chain stage-2/3, 2026-06-29)

When an audit module's `audit.py` defines canonical-constants
validators + reverse-coverage validators, obey these 3 principles:

1. **All validators MUST run BEFORE `register_audit_module`**: this
   guarantees a stale spec never enters the registry on validator
   failure. Precedent
   `clinosim/modules/antibiotic/audit.py:656-658`, where
   `_validate_narrow_rate_bands` + `_validate_nhsn_resistance_bands`
   + `_validate_narrow_ladder_at_import` are all invoked before
   `register`.
2. **Symmetry of forward-coverage + reverse-coverage**: when a band
   set requires "every (dim1, dim2) in the canonical YAML is covered
   or explicitly exempt" (reverse), require also "every canonical
   HAI_TYPE has at least one band" (forward) on the same set.
   Missing either → silent-no-op risk when a new dimension is
   added. Precedent `_validate_narrow_rate_bands` (forward) +
   `_validate_nhsn_resistance_bands` (reverse + forward via band).
3. **Reverse-coverage staleness check**: a validator that owns an
   exempt list should also check "does every exempt entry actually
   exist in the current YAML data?". This prevents a silent risk
   where dropping an organism from YAML leaves a stale exempt.
   Precedent: the `_NHSN_REVERSE_COVERAGE_EXEMPT` staleness loop in
   `_validate_nhsn_resistance_bands`.

Regression-test pattern: assert with `inspect.getsource()` that
each `_validate_*()` call in the source appears at a position less
than `register_audit_module(` (precedent
`tests/integration/test_antibiotic_audit.py:test_validators_run_before_register_audit_module`).

### Cross-module canonical URI constants (PR3b-5, 2026-06-29)

Do not hard-code canonical URIs (system / identifier URIs, etc.)
shared between a FHIR builder and an audit reader as string
literals. **Adopt the pattern: define at the writer-side module
(`clinosim/modules/output/_fhir_*.py`) as a module-level constant
+ have the reader side import it**. On rename, the reader triggers
`ImportError`, defending against silent-no-op skip (same pattern:
`MB_ORG_ID_PREFIX` PR #113 / `ABX_ORDER_ID_PREFIX` PR #114 /
`HAI_EVENT_ID_SYSTEM` PR3b-5).

Constant-naming convention:
- ID prefix: `<BUILDER_PREFIX>_<RESOURCE>_ID_PREFIX = "..."` (e.g.
  `MB_ORG_ID_PREFIX`).
- System URI (canonical): `<DOMAIN>_<CONCEPT>_SYSTEM = "..."` (e.g.
  `HAI_EVENT_ID_SYSTEM`).
- For internal URIs, use the **urn form**:
  `urn:clinosim:identifier:<purpose>` (for `identifier.system`; e.g.
  `HAI_EVENT_ID_SYSTEM = "urn:clinosim:identifier:hai-event-id"`) or
  `urn:clinosim:<resource>:<concept>` (for other resources; e.g.
  `"urn:clinosim:staff"` in `_fhir_practitioner.py`). In pr117-adv-1
  the coexisting mix of http-form and urn-form was unified to the
  urn form (the urn form is allowed only for internal concepts that
  have no registered URI in JP Core / US Core / an HL7 IG).

Contract-test pattern: `assert clinical_axis.CONSTANT is mb_builder.CONSTANT`
(pinning identical object identity and matching import path).
Precedent
`tests/unit/test_clinical_axis_per_organism.py:test_hai_event_id_system_canonical_constant_shared`.

### Data-only modules (variant)

A module variant that carries **only reference data + a loader** —
with no generation / assignment logic — like `modules/sdoh/`, is
also permitted (established by PR2 2026-06-24). `clinosim/codes/`
is the precedent for the same pattern.

Criteria:
- The data exists, but generation / assignment happens elsewhere
  (patient activator, FHIR output builder, another module's
  enricher).
- Multiple consumers need to share a common reference-data source.
- The theme has strong room for future data expansion.

Layout:

```
clinosim/modules/<name>/
  __init__.py            <- public API (export the loader function)
  engine.py              <- @lru_cache-wrapped loader only (no assignment function OK)
  reference_data/*.yaml  <- data-driven definitions
  README.md              <- same shape as other modules
```

`enricher.py` is **not needed** (no post_records enricher
registration). Registration in `ENRICHER_SEED_OFFSETS` is also
**not needed** (no RNG draw).

### Canonical "pure-function engine" (MOD-13 is the reference)

`observation/engine.py` has **zero cross-module imports** and takes
all context — physiology values, reference ranges, etc. — as
function arguments. Use it as the reference for new engines.

```python
# Good: take context as arguments. Do not import clinosim.modules.*
def generate_lab_result(canon: str, true_value: float, rng: np.random.Generator,
                        reference_ranges: dict | None = None) -> float:
    ...
```

### Types live in `clinosim/types/` (not defined inside the engine)

**Shared runtime types must not be defined inside a module** (per
AGENTS.md: "All types defined in `clinosim/types/`").

- `@dataclass` → runtime types (e.g. `clinosim/types/patient.py`,
  `encounter.py`, `output.py`).
- Pydantic `BaseModel` → YAML-loaded config types (AD-18; e.g.
  `clinosim/types/config.py`).

> **Known debt (MOD-2..6, TYP-2):** `PersonRecord` / `LifeEvent` /
> `HospitalizationSummary` (population/engine.py), `StaffMember` /
> `StaffRoster` (staff/engine.py), `ProcedureRecord` /
> `RehabSession` (procedure/engine.py), `HospitalState`
> (facility/hospital_state.py), and `DiseaseProtocol`
> (disease/protocol.py) still live in engines. **Do not repeat that
> mistake — define new types under `clinosim/types/<name>.py` from
> the start and export them from `clinosim/types/__init__.py` via
> `__all__`.** Loader functions (`load_disease_protocol`, etc.)
> stay on the module side, and the types are imported from `types`.

### YAML is validated with Pydantic

`disease/protocol.py` is the correct reference:
`DiseaseProtocol(BaseModel)` is loaded via
`load_disease_protocol()` with `model_validate()`.

> **Anti-pattern (ENC-1):** `encounter/protocol.py` returns 46
> YAMLs as bare `dict[str, Any]` and swallows parse errors with
> `except Exception: pass`. **Wrap every new YAML protocol in
> Pydantic** and adopt gradually via `extra="allow"`. `bare
> except` is forbidden.

### Publish the public API via `__init__.py`

> **Known debt (MOD-1, TYP-1):** 17 of 18 module `__init__.py`
> files are empty (0 bytes), and callers reach internals directly
> (`from clinosim.modules.population.engine import LifeEvent`).
> Only `identity/__init__.py` correctly exports via `__all__`.
> **New modules re-export the public surface from `__init__.py`**
> and callers use `from clinosim.modules.<name> import X` rather
> than `.engine`.

### Write `## Dependencies` in the README

Declare permitted dependencies (`clinosim/types/`, `clinosim/codes/`,
`clinosim/locale/`, and any other modules explicitly listed in the
README) under `## Dependencies` (English heading, matching
`identity/README.md`).

---

## Data-generation conventions

### Determinism contract (AD-16 / AD-17)

- **CIF is the sole simulation output** (AD-17). A venue simulator
  only **returns** a record via `return CIFPatientRecord(...)`. It
  does not write into a shared collection directly, nor call an
  output adapter (DET-7 reference: `inpatient.py:402` and similar
  return-based flows).
- **`random.random()` / stdlib `random` are forbidden** (AD-16,
  DET-8). Always use the `np.random.Generator` passed as an argument.
  Module-level mutable global state is also forbidden.
  - **Violation example (DET-4):** storing state on a function
    object attribute (`_generate_vitals._prev_diet`) causes multiple
    test invocations that share a deterministic id like `FORCED-0001`
    to read stale state. Keep state in call-scope local variables.

### PR verification guide: byte-diff vs. 3-axis DQR

**The true goal**: convert CIF data into accurate **FHIR R4 +
JP-Core-compliant** output + preserve clinical coherence + preserve
JP-localization quality.

Different PR shapes call for different verification approaches:

| PR shape | Verification | What it guarantees |
|---|---|---|
| **Pure mechanical refactor** (e.g. internal restructure, helper unification, registry centralisation, file split) | **byte-diff** — the 11 NDJSONs generated at the same seed / config on master and branch are sha256 IDENTICAL | **The output has not changed at all** before / after the refactor — a no-regression gate. |
| **New feature / realism improvement** (e.g. new analyte, new scenario flag, new medication coupling, new disease) | **`clinosim audit run`** — a 4-axis (structural / clinical / jp_language / silent_no_op) batch check. The module author registers a `ModuleAuditSpec` in `clinosim/modules/<name>/audit.py`. Save the report as `docs/reviews/<date>-<topic>-audit.md`. | **FHIR R4 / JP Core compliance + clinical coherence + JP-language quality + silent-no-op gate** (prevents recurrence of PR-90-class bugs) — a goal-achievement gate. |
| **Pure docs update** (e.g. README update, new doc) | Regression check (tests green) + manual link review. | No code has changed. |
| **Mixed** (refactor + a small behavior change) | Confirm via byte-diff that only intended changes exist + confirm the goal is preserved via DQR. | Both. |

**byte-diff is a means; the 3-axis DQR is the true goal test.**

- Using byte-diff on a refactor PR is a mechanical shortcut for
  "no behavior change". If the output changes, the refactor claim
  is a lie.
- On a new-feature PR, byte-diff **may deliberately not be
  identical**. The 3-axis DQR verifies the real goal — FHIR / JP-
  Core spec compliance, clinical validity (e.g. INR 2-3 in a
  warfarin patient), JP-localization quality (display strings,
  JLAC10 `ja` conforming to authoritative sources).
- Example: Phase 2a (D-dimer / causes_vte) is a new feature, so 9
  NDJSONs are byte-identical and the remaining 2 (Observation /
  DR) change intentionally. The 3-axis DQR verifies whether the D-
  dimer of PE / DVT / CI patients sits in the VTE-positive band, and
  whether the JLAC10 2B140 `ja` matches the JCCLS official Japanese
  name, etc.

#### byte-diff procedure

1. On master HEAD run
   `python -m clinosim.simulator.cli generate -p 2000 -s 42 --country US --format fhir-r4 -o scratchpad/<topic>_byte_diff/master/us`
   (and the same for JP).
2. On branch HEAD run the same command into
   `scratchpad/<topic>_byte_diff/branch/us`.
3. Run the sha256-comparison script (use
   `scratchpad/refactor_pr*_byte_diff/compare.py` from PR1 / PR2 as
   a template).
4. Confirm all 11 NDJSONs are IDENTICAL (the refactor-PR gate).
5. Save the results as `scratchpad/<topic>_byte_diff_results.md`
   and commit them into the PR.

#### 3-axis DQR procedure

1. Generate at US p≥10000 + JP p≥5000 (a large cohort to catch
   cohort-emergent phenomena).
2. Run the 3-axis audit script (use
   `scratchpad/phase2*_dqr/dqr_audit.py` from Phase 2a / 2b as a
   template):
   - **Structural**: `refRange` 100 %, `interpretation` 100 %,
     `display ≠ code` 100 %, zero id duplicates.
   - **Clinical**: expected per-disease lab-value ranges (DKA HCO3
     / ACS Troponin / VTE D-dimer / AF chronic INR therapeutic,
     etc.).
   - **JP language**: zero Japanese leakage into US, JP display
     strings conforming to authoritative sources (JCCLS-JSLM /
     MHLW etc.).
3. Confirm every axis PASSes.
4. Save the results as `docs/reviews/<date>-<topic>-data-quality-review.md`
   and commit them into the PR.

### Derive from physiological state

Whenever possible, derive labs / vitals from the patient's
physiological state (`true_value`). Funnel the generation chain
through:

```
order → canonical_lab_name → generate_lab_result(true_value, rng) → determine_flag(canon, observed, sex, reference_ranges)
```

When a disease or a drug lifts a specific lab, use `derive_lab_values`'s
scenario flags (`causes_X`) or medication flags (`on_warfarin`,
etc.) — see [`SCENARIO_FLAGS.md`](../SCENARIO_FLAGS.md) for the flag
list, addition procedure, and the design that prevents the J5
pattern.

> **Note (OBS-3):** pass the locale reference range into
> `determine_flag()`. The current call sites (`inpatient.py:604`,
> `outpatient.py:178`, `emergency.py:146`, etc.) do not pass
> `reference_ranges=`, so interpretation on JP output is computed
> against the US default — an inconsistency. New calls must pass
> `reference_ranges=load_reference_ranges(country).get("ranges", {})`.
>
> **Note (DET-6):** do not define fallback baseline lab values
> per-venue (WBC 6500 in `outpatient.py` diverging from WBC 7500 in
> `emergency.py`). Import the single constant on the
> `observation/engine.py` side.

### Sub-seed derivation rules (the exact pattern to copy)

Each enricher / module **derives its own sub-stream from the master
seed** and never touches the main random stream. The derivation
formula is centralised in
`clinosim/seeding.py:derive_sub_seed(master, module_offset, key)`
(AD-16 / AD-59).

```python
from clinosim.simulator.seeding import ENRICHER_SEED_OFFSETS, derive_sub_seed

# a fresh Generator per patient / encounter
rng = np.random.default_rng(
    derive_sub_seed(ctx.master_seed, ENRICHER_SEED_OFFSETS["my_module"], patient_id)
)
```

`key` must always mix in a **per-entity unique key** such as
patient_id / household_id / encounter_id (DET-3: the identity module
has a known inconsistency where the sub-seed is integer-only and
lacks per-patient keying).

**Registering a new module's offset**: when creating a module,
register the sub-seed numeric offset in
**`clinosim/seeding.py:ENRICHER_SEED_OFFSETS`**. The
convention is **16-bit hex ASCII (2 characters)** — pick two
letters mnemonic for the module name:

```python
ENRICHER_SEED_OFFSETS = {
    "identity":       540_054,    # exception: legacy decimal (grandfathered)
    "microbiology":   770_077,    # exception: legacy decimal (grandfathered)
    "immunization":   0x494D,     # "IM"
    "code_status":    0x4353,     # "CS"
    "family_history": 0x4648,     # "FH"
    "care_level":     0x434C,     # "CL"
    "nursing":        0x4E55,     # "NU"
    # New module examples: "device" = 0x4456 ("DV"), "hai" = 0x4841 ("HA")
}
```

Modules do not carry a local constant — they import from the
registry. The `assert len(set(...values())) == len(...)` at the end
of the dict detects duplicate offsets at import time (structurally
preventing accidental contamination of an existing module's RNG
stream).

### Writing into CIF: Base or extensions (decision tree)

Decision flow:

1. **Is this data essential to every EHR?**
   - YES → question 2.
   - NO  → `extensions["module_name"]` (opt-in module data).
2. **Is it a core field that will never be removed?**
   - YES → question 3.
   - NO  → `extensions`.
3. **Do multiple modules / FHIR builders reference it?**
   - YES → `CIFPatientRecord` typed field.
   - NO  → `extensions`.

Decision matrix:

| Axis | Typed field | `extensions` |
|---|---|---|
| Always-on Base data | ✓ | |
| Opt-in module data | | ✓ |
| Shared core EHR field | ✓ | |
| Theme-specific | | ✓ |
| Examples | `immunizations` / `family_history` / `code_status` / `care_level` | `nursing` extensions (always-on but specialised) |
| Persistence | Fully serialised by `asdict` | dict, explicitly serialised |

**Exception clarified (TYP-4)**: an always-on Base enricher may use
a typed field (e.g. `nursing_risk_assessments`). **A new opt-in
module must always use `extensions[<module>]`.**

> **PR2 lesson (data-only variant)**: a data-only module variant
> like `modules/sdoh/` **does not write into CIF** — the patient
> activator updates existing fields like
> `PatientProfile.smoking_status`, so it is essentially Base data.
> If a new module does not need to write into CIF, skip this
> decision flow entirely.

```python
# inside an opt-in module enricher
rec.extensions["my_module"] = [asdict(r) for r in my_records]

# inside an always-on Base enricher (exception: TYP-4)
rec.my_typed_field = [asdict(r) for r in my_records]
```

---

## Using the extension points

**All three registries extend by registration only — never edit the
core dispatch.**

### A. Add a FHIR resource (`register_bundle_builder`, AD-56)

Do not edit `_build_bundle()`. A builder is a pure function
`(ctx: BundleContext) -> list[dict]` that returns raw resources (do
not wrap in a Bundle entry — the registry uniformly wraps them via
`_entry()`).

```python
# clinosim/modules/output/fhir_r4_adapter.py
def _bb_my_resource(ctx: BundleContext) -> list[dict]:
    # ctx fields: record, country, roster_map, hospital_config, patient_data,
    #             patient_id, primary_dx_code, admit_dx_code, primary_enc_id, patient_sex, ...
    if ctx.country != "JP":          # country gating happens inside the builder
        return []
    return [{"resourceType": "...", "id": f"...-{ctx.primary_enc_id}", ...}]

register_bundle_builder(_bb_my_resource)
```

- Naming is unified with the `_bb_*` prefix (EXT-6:
  `_build_nursing_observations` etc. are legacy).
- `Resource.id` must be globally unique within its type. Use
  encounter-scoped ids (`lab-{encounter_id}-...`) — FA-7.
- **Double-wrap caveat (FA-3):** the builder returns a raw resource
  dict. Do not call `_entry()` inside the builder.

**Canonical example — `_bb_service_requests` (PR1, 2026-06-29,
`_fhir_service_request.py`):**

```python
# clinosim/modules/output/_fhir_service_request.py
from clinosim.modules.output.fhir_r4_adapter import register_bundle_builder, BundleContext
from clinosim.modules.order.panel_grouping import classify_lab_specs

def _bb_service_requests(ctx: BundleContext) -> list[dict]:
    """Emit 1 ServiceRequest per panel instance + 1 per stand-alone lab order."""
    resources: list[dict] = []
    orders = _collect_lab_orders(ctx.record)       # walk all encounters' orders
    for group_key, group_orders in _group_by_panel(orders):
        sr = _build_service_request(group_key, group_orders, ctx)
        resources.append(sr)
    return resources

register_bundle_builder(_bb_service_requests)
```

Key patterns illustrated:
- `ctx.record` is the `CIFPatientRecord` (a dict on the production
  JSON path, a dataclass in tests). Always access fields via
  `_o(order, "field_name", default)` (the `get_attr_or_key` wrapper —
  see `clinosim/modules/_shared.py`) to support both paths — unit
  tests may pass dataclass instances while the production path
  deserialises to dict.
- Panel-grouping logic lives in
  `clinosim/modules/order/panel_grouping.py:classify_lab_specs`.
  Never inline a panel-detection if/elif inside a builder. [AD-61]
- Both dict-path and dataclass-path MUST be covered by tests: a
  subprocess integration smoke test exercises the production dict
  path (see `tests/integration/test_service_request.py`).

See [`clinosim/modules/output/_fhir_service_request.py`](../clinosim/modules/output/_fhir_service_request.py)
for the full implementation.

### B. Add an output format (`register_output_adapter`, AD-58)

Do not edit the CLI `--format` dispatch. Register a class that
satisfies the `OutputAdapter` Protocol, following the
`adapters_builtin.py` pattern. An adapter may depend **only on CIF
+ `clinosim.codes` + `clinosim.locale`**.

```python
# clinosim/modules/output/adapter.py Protocol:
#   format_id: str / description: str / subdir: str
#   def convert(self, cif_dir: str, out_dir: str, ctx: OutputContext) -> None
class MyFormatAdapter:
    format_id = "my-format"
    description = "My export format"
    subdir = "my_format"

    def convert(self, cif_dir: str, out_dir: str, ctx: OutputContext) -> None:
        from clinosim.modules.output.my_converter import convert_cif_to_myformat
        convert_cif_to_myformat(cif_dir, out_dir, country=ctx.country)  # pass ctx.country

register_output_adapter(MyFormatAdapter())
```

For built-in adapters, `_ensure_builtins()` imports `adapters_builtin`
which self-registers. Add `register_output_adapter(...)` there for
a new built-in.

> **Note (FA-9):** always use `ctx.country`. The CSV adapter has a
> known debt of dropping `ctx.country`.

### C. Add a post-pass (Enricher, AD-56)

Do not inline into `run_beta`. Register the `Enricher` in
`register_builtin_enrichers()` (`enrichers.py`).

```python
# clinosim/simulator/enrichers.py
@dataclass  # the actual definition is the existing Enricher dataclass
# Enricher(name, stage, run: Callable[[EnricherContext], None], order=100, enabled=lambda c: True)

def run_my_pass(ctx: EnricherContext) -> None:
    # ctx fields: config, master_seed, population, records
    rng_seed = _sub_seed(ctx.master_seed, "my-pass")  # own sub-seed (do not touch the main stream)
    for rec in ctx.records:
        rec.extensions["my_module"] = ...

register_enricher(Enricher(
    name="my_module",
    stage=POST_RECORDS,                 # or POST_POPULATION
    run=run_my_pass,
    order=300,                          # ascending execution. Fixed order = determinism.
    enabled=lambda c: c.module_enabled("my_module", default=True),
))
```

- `stage` is `POST_POPULATION` (after population generation, before
  simulation — mutates `ctx.population`) or `POST_RECORDS` (after
  record generation — reads / extends `ctx.records`).
- The registry is idempotent by name. The integer `order` controls
  execution order = governs determinism.

---

## What data / code to use

### Codes vs. locale separation

- **`clinosim/codes/`** = international standard code systems
  (locale-independent, EN-first): `icd-10-cm.yaml`, `icd-10.yaml`,
  `loinc.yaml`, `rxnorm.yaml`, `yj.yaml`, `cpt.yaml`, `k-codes.yaml`,
  `cvx.yaml`, etc.
- **`clinosim/locale/`** = country / culture-dependent data only
  (names, addresses, reference ranges, `code_mapping_*`).
  Terminology has moved into `codes/` (CODES-2). **Do not put
  display text in locale.**

### Resolve display via `lookup()` (AD-30)

CIF holds **codes only**. Display is resolved at output time.

```python
from clinosim.codes import lookup as code_lookup
name = code_lookup("icd-10-cm", "I50.9", "en")  # returns code itself / EN fallback on miss
```

> **Anti-pattern (DUP-3, FA-4, DIAG-1):** do not create a new
> display dict like `CONDITION_NAMES` (patient/activator.py). Fields
> like `admission_diagnosis_name` in `csv_adapter.py` /
> `narrative_generator.py` are ghost fields absent from CIF and
> always empty. Use `code_lookup(system, code, lang)` for new code.

### Resolve URI via `get_system_uri()`

```python
from clinosim.codes import get_system_uri
uri = get_system_uri("snomed-ct")  # do not embed FHIR system URIs as string literals
```

> **Anti-pattern (URI-1, CODES-4, FA-2):** do not embed
> SNOMED / LOINC / UCUM / HL7 URIs as raw strings (many remnants
> still in `fhir_r4_adapter.py`). Register a new key's canonical
> HL7 URI in `_BUILTIN_URIS` in `codes/loader.py` before using
> `get_system_uri()`.

### Country → code-system selection via `system_key_for()` (2026-07-02)

The "JP uses JLAC10 / ICD-10 (WHO) / YJ / K-codes, everything else
uses LOINC / ICD-10-CM / RxNorm / CPT" mapping must always go
through `clinosim.codes.system_key_for(kind, country)` (single
source of truth):

```python
from clinosim.codes import system_key_for

system = system_key_for("lab", country)        # JP → "jlac10", else → "loinc"
system = system_key_for("diagnosis", country)  # JP → "icd-10", else → "icd-10-cm"
system = system_key_for("drug", country)       # JP → "yj",     else → "rxnorm"
system = system_key_for("procedure", country)  # JP → "k-codes", else → "cpt"
```

- `kind` is one of `"lab"` / `"diagnosis"` / `"drug"` /
  `"procedure"`. An unknown `kind` raises `KeyError` fail-loud (no
  silent fallback).
- `country` is case-insensitive (JP decision is normalised
  internally).

> **Anti-pattern:** do not write inline branching like
> `"jlac10" if country == "JP" else "loinc"` at builder / simulator
> call sites. Before the shared-logic unification, the same choice
> was inlined in many places, creating a J5-pattern risk where
> only some call sites were updated when a new code system was
> added.

### Internal-name → standard code = `code_mapping`

Resolve internal test names (`"WBC"`) → standard code via
`locale/<country>/code_mapping_*.yaml` (`load_code_mapping()`).
Route through the canonical loader — do not `yaml.safe_load` the
YAML directly (LOC-1).

### The locale's shared data also goes through a canonical loader (expanded 2026-07-02)

`clinosim/locale/loader.py` provides cached loaders for the shared
locale data. **When a canonical loader exists for a YAML, raw
`yaml.safe_load` inside a module or a FHIR builder is forbidden**
(the 2026-07-02 shared-logic unification migrated the inline reads
in `_fhir_localization.py` and `patient/activator.py` to the
loaders):

- `load_med_terms_ja()` — JP medical-terms table (categories +
  terms; preserves YAML order = order-sensitive substitution).
- `load_drug_names_ja()` — EN → JA drug-name mapping (keys are
  lowercase-normalised).
- `load_department_display()` — department display table
  (`{key: {en, ja}}`).
- `load_chronic_medications()` — chronic-condition → routine
  medications (consumed by the patient activator).

All are `@lru_cache(maxsize=1)` — the return value is a shared
instance, so mutation is forbidden (see the mandatory rule under
"`@lru_cache` `maxsize` convention"). When you add a new shared
locale YAML, define its cached loader in `locale/loader.py`
similarly, and have consumers import it.

### Authoritative sources / English-first / code coverage

- **Authoritative sources only:** CMS (ICD-10-CM), NLM (RxNorm,
  ICD-10-CM API `clinicaltables.nlm.nih.gov/api/icd10cm`), WHO
  (ICD-10, `icd.who.int/browse10`), Regenstrief (LOINC), AMA
  (CPT), JCCLS / JSLM (JLAC10), MHLW (YJ, K codes). **Do not
  fabricate codes** (CODES-7: sharing a fabricated display for
  RxNorm CUI 18631 across 2 drugs is a real case).
- **English-first:** every entry in `codes/data/*.yaml` requires
  `en`; other languages (`ja`, etc.) are optional (CODES-1).
- **Every emittable diagnosis code must be registered:** disease
  `icd_codes` (primary + variants), encounter `icd10_code`,
  `builtin_differentials.yaml` `differentials[*].icd` +
  `diagnosis_progression`. US billable in `icd-10-cm.yaml`;
  non-billable in `code_mapping_diagnosis/us.yaml` folded to a
  billable leaf. JP puts WHO 3-4 digit codes into `icd-10.yaml`
  (CM-grained codes fold into WHO parents via
  `code_mapping_diagnosis/jp.yaml`). After addition, always run:

```bash
pytest tests/unit/test_diagnosis_code_coverage.py
```

> There is no equivalent coverage test yet for RxNorm / YJ / CPT /
> K-codes / CVX (CODES-6). After adding a drug / procedure code,
> manually verify that the mapping → codes existence chain resolves.

---

## Checklist when adding

Execute in order:

1. **Read the target module's `README.md`** (grasp Dependencies
   and existing API).
2. **Define shared types in `clinosim/types/<name>.py`** and
   export them from `types/__init__.py` via `__all__` (do not
   define types inside the engine). `@dataclass` = runtime,
   Pydantic = config (AD-18).
3. **If data-driven, `reference_data/*.yaml` + Pydantic
   validation** (`model_validate`). `bare except` is forbidden.
4. **Derive the deterministic sub-seed** with the exact formula
   (mix in a per-entity key). `random.random()` / global state is
   forbidden.
5. **Register at the correct registry**: FHIR →
   `register_bundle_builder`; output format →
   `register_output_adapter`; post-pass → `register_enricher`. Do
   not edit the core dispatch / `_build_bundle` / `run_beta` /
   CLI `--format`.
6. **Code coverage:** cross-check the new / changed codes against
   an authoritative source → register in
   `codes/data/<system>.yaml` (`en` required) or `code_mapping_*`
   → run `pytest tests/unit/test_diagnosis_code_coverage.py`.
7. **Update the README / types** (when API / data structures
   change). Confirm downstream impact via the README's dependency
   graph.
8. **`pytest -x -q`** (unit is mandatory before commit). If output
   may be affected, verify goldens via `pytest -m e2e`.
9. **Audit the generated CIF + FHIR for clinical coherence**
   (labs / vitals consistent with physiology; diagnosis codes
   resolve correctly; no English leakage in JP output; URI /
   reference integrity).

---

## Regen scope matrix: Local iteration cycles (AD-65, 2026-07-02)

The two-pass CIF generation architecture (`clinosim simulate` →
Stage 1 structural + auto Stage 2 template narratives) plus the dev
facility (`test-disease --format`, `narrate` verb) enables fast
iteration on different change types. Use this matrix to select the
fastest workflow for your change. The canonical spec for the two-
pass structural / narrative CIF separation is
[`clinosim/modules/output/SPEC.md`](../clinosim/modules/output/SPEC.md)
§ "Stage 2: Narrative Generation".

### Change types and iteration time

| Change target | Fastest regen command | Estimated time | Notes |
|---|---|---|---|
| **Simulator engine / enricher** (population, disease, encounter logic) | `clinosim simulate -p N -o /tmp/cX` | 5-50 min | Full cohort → CIF output. Proportional to N. |
| **Template narrative generator** (TemplateNarrativeGenerator, bug A pattern) | `clinosim narrate --cif-dir /tmp/cX --version-id template` → `clinosim export-fhir --cif-dir /tmp/cX` | ~30 sec + 5 min | Reuse existing structural CIF. Stage 2 only. |
| **FHIR builder** (bug C pattern) | `clinosim export-fhir --cif-dir /tmp/cX` | ~5 min | Reuse existing CIF. Stage 3 only. |
| **Locale display / code resolution** | `clinosim export-fhir --cif-dir /tmp/cX` | ~5 min | No CIF change, Stage 3 only. |
| **1 disease scenario** (bug B pattern: structural CIF bug within 1 disease) | `clinosim test-disease <disease_id> -n 5 --format all -o /tmp/verify` | ~10 seconds | Structural CIF + Stage 2 narratives + Stage 3 FHIR, 5 patients. |
| **1 encounter condition** (bug B pattern: structural CIF bug within 1 ED/outpatient condition) | `clinosim test-encounter <condition_id> --format all -o /tmp/verify` | ~5 seconds | Same 3 stages, ~3 patients. |

### Case 1: Template narrative generator bug (AD-65 Tier 1 #3)

**Symptom:** H&P Progress Note HPI section contains Japanese characters in US cohort (bug A pattern).

**Workflow:**

1. **Diagnose** via `test-disease` (structural CIF only):
   ```bash
   clinosim test-disease acute_mi -n 1 --format cif -o /tmp/test
   # Verify structural CIF has correct encounter/patient data
   ```

2. **Fix** in code: `clinosim/modules/document/narrative/template_generator.py`
   - Locate builder function (`_build_hpi`, `_build_physical_examination`)
   - Check `_pick_localized(tmpl, key, lang)` call is routing to `en` field for US language
   - Verify Disease YAML `narrative.physical_examination_en` field is populated

3. **Verify fix** via fast Stage 2 regen (skip expensive full cohort):
   ```bash
   # Reuse structural CIF from step 1
   clinosim narrate --cif-dir /tmp/test --version-id template
   clinosim export-fhir --cif-dir /tmp/test
   # Check output Composition resource's text field has zero Japanese
   ```

4. **Full validation** (once confident):
   ```bash
   clinosim simulate -p 500 --country US -o /tmp/us500
   clinosim audit run --cif-dir /tmp/us500
   # Gate: "us_admission_hp_zero_ja_chars" = 0
   ```

**Total iteration time:** ~35 seconds per fix attempt (10 sec `test-disease` + 25 sec `narrate`+`export-fhir`).

---

### Case 2: Structural/author bug (encounter/order/enricher logic)

**Symptom:** Nursing notes have physician as author instead of primary nurse (bug B pattern).

**Workflow:**

1. **Diagnose** via unit test:
   ```bash
   pytest tests/unit/test_document_author_selection.py -xvs
   # Verify _pick_document_author(spec, encounter) returns correct id
   ```

2. **Fix** in code: `clinosim/modules/document/engine.py`
   - Locate `_emit_doc()` function
   - Replace hardcoded `attending_id = encounter.attending_physician_id`
   - Call helper `_pick_document_author(spec, encounter)` instead

3. **Verify fix** via `test-disease --format all` (includes structural + narrative + FHIR):
   ```bash
   clinosim test-disease acute_mi -n 3 --format all -o /tmp/verify
   # Check FHIR Composition.author field
   # Check CIF Composition.subject.type has nursing LOINC + author is nurse_id
   ```

4. **Integration test** on production cohort:
   ```bash
   clinosim simulate -p 500 --country US -o /tmp/us500
   clinosim audit run --cif-dir /tmp/us500
   # Gate: "nursing_doc_author_is_nurse_ratio" = 1.0
   ```

**Total iteration time:** ~8 seconds per fix attempt (3 sec `test-disease`, 5 sec integration).

---

### Case 3: FHIR builder bug

**Symptom:** Composition resource is missing a required section, or reference integrity is broken.

**Workflow:**

1. **Diagnose** via unit test on builder:
   ```bash
   pytest tests/unit/test_fhir_composition.py -xvs -k "missing_section"
   # Unit test on builder logic
   ```

2. **Fix** in code: `clinosim/modules/output/_fhir_composition.py`
   - Check `_bb_compositions()` reads `doc.narrative.sections` (post-AD-65 structure)
   - Verify reference integrity: all `reference` URIs resolve to resources in manifest

3. **Quick structural check** (FHIR builder doesn't change structural CIF):
   ```bash
   # Reuse existing /tmp/us500 CIF from case 2
   clinosim export-fhir --cif-dir /tmp/us500
   # Inspect Composition.ndjson for correct section[] content
   ```

4. **Validation**:
   ```bash
   pytest tests/unit/test_fhir_composition.py -xvs
   pytest -m integration -xvs tests/integration/test_fhir_reference_integrity.py
   ```

**Total iteration time:** ~5 minutes per fix attempt (all Stage 3 only, no CIF regen).

---

### Determinism & reproducibility

- **Seed pinning:** All structural + narrative generation uses deterministic seed (default 42). Use `--seed N` to reproduce exact cohort across runs.
- **Narrative version pointer:** `cif/narratives/current_version.txt` tracks active narrative version. Export defaults to `current`, or specify `--narrative-version <id>`.
- **Backwards compat:** Old CIF without narrative dir → `export-fhir` emits empty narrative and warns. `test-disease --format cif` writes structural CIF only (no narrative, consistent with `simulate` Stage 1 output).

---

## Common pitfalls

**Do**
- Engines are pure functions; context is passed as arguments
  (`observation/engine.py` is the reference).
- Types live in `clinosim/types/`; display via `code_lookup()`; URI
  via `get_system_uri()`.
- Country decisions via `is_jp()`; display language via
  `resolve_lang()`; country → code-system selection via
  `system_key_for()` (do not write hand-rolled `country == "JP"`
  variants or inline branching).
- Treat cached loader return values as read-only (shared instance —
  mutation forbidden).
- Venue simulators **return** `CIFPatientRecord`; opt-in modules
  write into `extensions[<module>]`.
- Mix a per-entity key into the sub-seed and construct a fresh
  `default_rng` per entity.
- Validate YAML with Pydantic; route through the canonical loaders
  (`locale/loader.py`, `codes/loader.py`).

**Don't**
- ❌ Do not save display text into CIF (codes only — AD-30).
- ❌ Do not hard-code FHIR system URIs / diagnosis displays as raw
  strings (URI-1, MOD-11, DUP-1 / 2 / 3, FA-2 / 4 / 8).
- ❌ Do not use `random.random()` / stdlib `random` / module-level
  mutable globals (AD-16; DET-4's `_prev_diet` is a cautionary
  case).
- ❌ Do not edit the core dispatch (`_build_bundle`, `run_beta`,
  CLI `--format`) — extend via the registry.
- ❌ Do not define shared types inside an engine (MOD-2..6). Do not
  leave `__init__.py` empty — export the public API
  (MOD-1 / TYP-1).
- ❌ Do not import private functions (`_sample_given_name` etc.)
  from another module (MOD-7 / TYP-5) — promote them to the
  locale's public utility.
- ❌ Do not fabricate codes; do not swallow YAML errors with
  `except Exception: pass` (CODES-7, ENC-1).
- ❌ Do not drop `ctx.country` (FA-9). Do not forget to pass the
  locale reference range into `determine_flag()` (OBS-3).
- ❌ Do not define per-venue baseline values or lookup tables that
  drift (DET-6, DUP-1).

## Adding a new patient profile fixture (AD-66)

See `tests/fixtures/patient_profiles/README.md` for the full workflow.
Quick summary:

1. Copy an existing profile YAML as a template
2. Edit `profile_id` (must match filename stem), `disease_id`, `country`, `severity`, `archetype`, `patient_overrides`
3. Run `clinosim regenerate-goldens --profile <new_profile_id>` to bootstrap the golden
4. Manually review `<new_profile_id>.golden.json`
5. Run `pytest -m regression -k <new_profile_id> -q` to verify
6. Commit YAML + golden together (AD-66 rule 1)

**AD-66 policy** (see `AGENTS.md` for canonical wording):
- Profile YAML changes MUST regenerate golden + commit both together
- Unexpected `git diff` on goldens after intentional template changes = regression suspicion

Japanese counterpart: [`CONTRIBUTING-modules.ja.md`](CONTRIBUTING-modules.ja.md).
