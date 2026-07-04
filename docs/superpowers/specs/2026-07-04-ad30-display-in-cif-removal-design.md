# AD-30 chain: display-in-CIF removal — Design Spec

**Date:** 2026-07-04 (session 34)
**Status:** Approved for implementation
**Branch:** `feature/ad30-display-in-cif-removal` (to be created)
**Source:** `TODO.md` "★★ AD-30 chain: display-in-CIF removal (CIF schema change + golden regen)"

## 1. Problem

AD-30 states: "CIF stores codes only, not display text — display is resolved at
output time via `clinosim.codes`." Three CIF dataclass fields violate this:
`AllergyReaction.manifestation_display`, `Allergy.allergen_display`
(`clinosim/types/allergy.py`), and `ImagingSeries.body_site_display`
(`clinosim/types/imaging.py`). All three are populated at simulation time from
hardcoded YAML display text (`allergens.yaml` / `body_sites.yaml`, `_en` keys
only), not from `clinosim.codes`.

A session-34 investigation confirmed the TODO's claim that "the builder already
re-resolves via code_lookup → dead data" is **true for the FHIR builders**
(`_fhir_allergy_intolerance.py`, `_fhir_imaging_study.py` use the CIF field only
as a fallback when `code_lookup("snomed-ct", code, lang)` fails to resolve — and
every code currently in use resolves successfully, so the fallback never fires
in practice) but **false for `allergen_display`'s narrative consumer**:
`clinosim/modules/document/narrative/template_generator.py:761` reads
`allergen_display` directly with **no `code_lookup` call anywhere in that path**.
Removing the field without also fixing this consumer would silently blank the
allergy section of every generated clinical document (H&P, discharge summary,
progress notes) — a regression, not a cleanup.

`manifestation_display` and `body_site_display` have no equivalent narrative
consumer; both are genuinely dead outside their FHIR-builder fallback role.

## 2. Principle

CIF-stored display text is removed wherever a `code_lookup()`-resolvable
alternative already exists and is already the effective source of truth. Where
a consumer has no `code_lookup` wiring yet (the `allergen_display` narrative
path), that consumer is fixed to call `code_lookup()` as part of the same
change — this is a required companion to make the field removal safe, not
optional scope creep. Once fields are removed, every FHIR-builder fallback
branch referencing them is deleted too (the field won't exist to fall back to).

**Unresolved-code behavior (user-approved):** rather than keep a CIF-stored
fallback for codes `code_lookup()` can't resolve, add import-time validation
(matching this codebase's established `_validate_*` pattern) so an unregistered
SNOMED code in `allergens.yaml`/`body_sites.yaml` raises at load time instead of
silently reaching runtime. This closes the gap `code_lookup()`'s own runtime
fallback (return the code itself, unchanged) would otherwise paper over.

## 3. Scope — per-site fix plan

| # | Site | Fix |
|---|------|-----|
| 1 | `AllergyReaction.manifestation_display` (`types/allergy.py:18`) | Remove field. Remove the assignment at `allergy/engine.py:140`. Remove the fallback branch at `_fhir_allergy_intolerance.py:154-157` (`or manifestation_display`) — `code_lookup()`'s result becomes the sole source. |
| 2 | `ImagingSeries.body_site_display` (`types/imaging.py:27`) | Remove field. Remove the assignments at `imaging/engine.py:290,309`. Remove the fallback branch at `_fhir_imaging_study.py:117-120` — `code_lookup()`'s result becomes the sole source. |
| 3 | `Allergy.allergen_display` (`types/allergy.py:28`) | Remove field. Remove the assignment at `allergy/engine.py:132`. Remove the fallback branch at `_fhir_allergy_intolerance.py:100-102`. **Companion fix (required, not optional):** `template_generator.py:761` and its upstream data plumbing (`narrative/context.py:32,48`, `narrative/passes.py:260`) are changed to derive the narrative-facing allergen display via `code_lookup("snomed-ct", allergen_code, lang)` instead of reading a CIF-stored string. |
| 4 | Import-time validation | Add validation to `allergy/engine.py`'s `load_allergens()` and `imaging/engine.py`'s `load_body_sites()`: every SNOMED code referenced (`allergen_code`, `manifestation_snomed`, `body_site_snomed`) must exist in the `clinosim.codes` snomed-ct registry, else raise at import time — matching the established `_validate_*` convention (reuse the existing `_code_in_data()`-style helper if one is already available for this purpose; otherwise define the equivalent lookup inline, following the same pattern as `_validate_hai_organisms` / `_validate_demographics`). |
| 5 | `TODO.md` | Record the locale-freeze bug (allergen/body-site display text is always `display_en`, never localized to `display_ja` for JP patients) as a new, separate deferred TODO item. Not part of this chain's scope. |

## 4. Out of scope (deferred, recorded separately in TODO.md)

- The locale-freeze bug (§3 item 5) — a distinct data-quality/localization defect,
  unrelated to AD-30's "no display text in CIF" concern. Fixing it would require
  threading `lang`/`country` into `load_allergens()`/`load_body_sites()` call
  sites and choosing `display_en`/`display_ja` accordingly — a different shape
  of change than this chain.
- `clinosim/modules/output/_fhir_service_request.py`'s independent body-site
  display re-derivation (re-reads `body_sites.yaml` directly, bypassing both the
  CIF field this chain removes and `code_lookup()`) — it does not read
  `ImagingSeries.body_site_display` at all, so it is unaffected by this chain's
  removal and its own architectural inconsistency (a third body-site-display
  code path, alongside `code_lookup()` and the CIF field) is a separate,
  pre-existing concern.

## 5. Verification

- `pytest -x -q` full suite green.
- `grep -rn "manifestation_display\|allergen_display\|body_site_display" clinosim/`
  after implementation — confirm zero hits in `types/`, `modules/allergy/`,
  `modules/imaging/`, and the FHIR builders (only test files, if any remaining
  fixture helpers still use the old name, should be updated too — see Testing
  note below).
- Narrative golden impact check: three allergen codes have a CIF-stored display
  that diverges from `code_lookup()`'s canonical text (`303408005` "Sulfa drugs"
  vs "Sulfonamide", `227037002` "Eggs" vs "Egg", `256262001` "Pollen" vs
  "Tree pollen"). If any of the 6 canonical patient-profile fixtures
  (`tests/fixtures/patient_profiles/*.yaml`) has a patient with one of these
  three allergens, its narrative golden's rendered allergy text will change —
  expected and correct (the new text is the authoritative `code_lookup()`
  value). Regenerate via `clinosim regenerate-goldens --all` and, per AD-66
  Rule 2, confirm no *other* profile's golden changed unexpectedly before
  committing.
- `clinosim audit run` on a small US + JP cohort — confirm no clinical-axis
  regression.
- Manually inspect one US and one JP FHIR export containing an allergy and an
  imaging study — confirm `AllergyIntolerance.reaction.manifestation.text` /
  `.code.text`, `AllergyIntolerance.code.text`, and
  `ImagingStudy.series.bodySite.display` are correctly localized (English for
  US, Japanese for JP) purely from `code_lookup()`, with no CIF-field
  involvement possible (the field no longer exists).

## 6. Testing note

Removing these three fields is a breaking change for any dataclass construction
in tests that passes them as kwargs (e.g. `tests/unit/test_types_allergy.py`,
`tests/unit/output/test_fhir_allergy_intolerance.py`,
`tests/unit/test_types_imaging.py`, `tests/unit/output/test_fhir_imaging_study.py`,
`tests/unit/modules/document/narrative/test_template_generator.py`). This is
expected, in-scope churn — those tests were asserting on or constructing the
very fields this chain removes; updating them (to assert on `code_lookup()`
output instead, where the removed field was the point of the test) is part of
the work, not a side effect to minimize.
