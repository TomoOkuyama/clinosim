# Configuration and reference data — specification

Status: **normative**. Every change that adds or reads a reference-data YAML, a configuration table, an age-banded table or a constant follows this document. A change that cannot follow it updates this document in the same PR, with the reason.

Japanese counterpart: [`configuration-and-reference-data-spec.ja.md`](configuration-and-reference-data-spec.ja.md).

Related specs, linked rather than restated:
- How YAML is authored and read (`load_data_yaml`, `metadata.kind`, file placement), code tables and value sets: [`code-mapping-and-localization-spec.md`](code-mapping-and-localization-spec.md) §3.1 / §3.6.
- Where a constant lives (YAML or Python): [`documentation-and-code-quality-policy.md`](documentation-and-code-quality-policy.md) §5 / §5.1.
- Loader conventions (path constants, `@lru_cache`, owner accessors): [`implementation-rules.md`](implementation-rules.md) §5.

## 1. Principles

1. **One reader, one shape check.** Reference data is read through its owner module's loader, and its shape is checked when it is loaded, not when a key is first missed. A malformed or unknown key fails loudly at load time.
2. **One table per fact.** A value used by several stages (a follow-up interval, a named condition, an age-banded rate) lives in one table, and every stage reads that table through one accessor.
3. **One interpretation of a key format.** Shared key formats (age bands, code groups) are parsed by one helper, so every table spells and reads them the same way.
4. **Every rule has a guard.** Each rule names the test that enforces it; a rule without one is listed in §5.

## 2. Loading and validating

| Rule | Canonical code | Guard |
|---|---|---|
| Every data YAML is parsed by the one reader and declares its `metadata.kind`. | `clinosim/datafiles.py::load_data_yaml`, `data_metadata` | `tests/unit/test_data_yaml_conventions_2465.py` |
| A module's reference YAML is validated at load by a Pydantic model (`ConfigDict(extra="forbid")`), so an unknown key or a missing required key fails at import. Codes the YAML names are checked to exist through `clinosim.codes`. A new key is added to the model first (AD-69). | per module: `modules/<module>/` models (allergy, care_level, code_status, device, disease, document, encounter, family_history, hai, imaging, nursing, observation, order, sdoh, triage) | `tests/unit/test_configuration_spec_guards.py::test_module_reference_yaml_has_a_model` (ratchet), per-module model tests |
| A cached loader's return value is shared and read-only. | `@lru_cache` loaders | `implementation-rules.md` §3 (review) |

## 3. Shared tables

| Rule | Canonical code | Guard |
|---|---|---|
| Age-banded tables use keys `"lo-hi"` (both ends inclusive) and `"lo+"` (open-ended), and are parsed and looked up only by the shared helper; the first band that covers the age wins, and each caller states what an uncovered age yields. | `clinosim/age_bands.py` (`parse_age_band`, `parse_closed_age_band`, `age_band_covers`, `find_age_band`, `lookup_age_band`) | `tests/unit/test_age_bands_2516.py`, `tests/unit/test_configuration_spec_guards.py::test_no_ad_hoc_age_band_parsing` |
| Follow-up vitals and visit intervals of chronic conditions come from one table, read by the simulator, the population calendar and the outpatient note. | `locale/shared/chronic_followup.yaml` via `clinosim.locale.loader` | `tests/unit/test_followup_from_yaml_2287.py` |
| A condition named in decision logic (severity modifiers, complication risk factors, lab flags: "diabetes", "dyslipidemia", ...) is resolved through the value sets, not by an ICD prefix written at the call site. | `clinosim/codes/valuesets.py` (`has_condition`, `concept_group`), `codes/data/valuesets.yaml` | `tests/unit/test_named_conditions_2285.py`, `tests/unit/test_valuesets_2280.py`, `tests/unit/test_diabetes_group_2281.py` |
| Probability vectors from YAML are normalized with `normalize_probabilities(p, fallback="raise")`. | `clinosim/modules/_shared.py` | [`determinism-and-rng-spec.md`](determinism-and-rng-spec.md) §2 |

## 4. Constants

| Rule | Canonical code | Guard |
|---|---|---|
| A table keyed by domain identifiers (disease, drug, lab, age band, country) lives in YAML. A formula coefficient or a clinical threshold lives as a named, documented constant in a `_<topic>_thresholds.py` / `_defaults.py` module, with its source. Code holds no unnamed clinical literals. | policy | [`documentation-and-code-quality-policy.md`](documentation-and-code-quality-policy.md) §5.1 (review) |

## 5. Gaps

| Gap | Where |
|---|---|
| Modules whose reference YAML has no Pydantic model (some validate with hand-written checks, some not at all): antibiotic, clinical_course, diagnosis, drug_safety, llm_service, monitoring, newborn, patient, pediatric, physiology, population, procedure, prophylaxis. The guard allows exactly these; the list may only shrink. | `tests/unit/test_configuration_spec_guards.py::_NO_MODEL_YET` |
| The constants-placement policy has no automatic guard. | review |
