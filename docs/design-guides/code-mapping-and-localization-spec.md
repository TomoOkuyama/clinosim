# Code mapping, name resolution and localization — specification

Status: **normative**. Every change that adds, maps, resolves or displays a code, a code system, or a localized name follows this document. A change that cannot follow it updates this document in the same PR, with the reason.

Japanese counterpart: [`code-mapping-and-localization-spec.ja.md`](code-mapping-and-localization-spec.ja.md).

## 1. Principles

1. **One source per fact.** Each code, code-system URI, display name and mapping lives in exactly one data file. Python reads it; Python never restates it.
2. **One resolver per authority or vocabulary.** Every kind of lookup — a LOINC display, a drug's Japanese name, a department label — has one named function. Emitters, narrative, LLM prompts, CSV, eval, audit and benchmarks all call that function. None of them re-implements it.
3. **Codes in CIF, names at output.** CIF stores codes and internal ids (AD-30). Displays are resolved when FHIR, narrative or CSV output is written.
4. **No fabrication.** A code is registered only after it is verified against its authority (§7). Something with no verified code stays uncoded rather than getting a guessed code.
5. **Adding a language is a data change.** Code never branches on a specific language except through the functions in §5.

## 2. Layers

| Layer | Package | Owns | May import |
|---|---|---|---|
| Authority code systems | `clinosim/codes/` | registered codes, URIs, displays, value sets, the drug / procedure / role catalogs, UCUM, JIS X 0401, named SNOMED concepts | nothing above it (no `clinosim.locale`, no `clinosim.modules`) |
| Country and display data | `clinosim/locale/` | per-country code mappings, display tables for non-code vocabularies, the phrase catalog, country → language | `clinosim.codes` |
| Consumers | `clinosim/modules/`, `clinosim/simulator/`, `clinosim/eval/`, `clinosim/audit/`, `clinosim/benchmarks/` | decision logic, emitters | both layers above, only through the functions in §4 |

## 3. YAML formats

### 3.1 Code-system registry — `clinosim/codes/data/<system-key>.yaml`

```yaml
metadata:
  name: HL7 FHIR Discharge Disposition
  uri: http://terminology.hl7.org/CodeSystem/discharge-disposition   # canonical URI (spec fixedUri)
  source: "HL7 Terminology (THO)"                                    # authority the codes were verified against
codes:
  home: {en: "Home", ja: "自宅退院"}
  exp:  {en: "Expired", ja: "死亡退院"}
```

- The file name is the **system key** used by every resolver (`loinc`, `snomed-ct`, `icd-10-cm`, `hl7-discharge-disposition`, ...).
- `codes.<code>.en` is **required** and equals the authority's display, for example the LOINC long common name or the SNOMED preferred term. Other languages are optional keys named by ISO-639-1 code (`ja`, ...).
- Systems without code data, used only for their URI, are registered in `_BUILTIN_URIS` (`codes/loader.py`) under a key. Two mechanisms let several keys share data:
  - **Data aliases.** `_SYSTEM_DATA_ALIASES`: the same data under another URI, for example `icd-10-mhlw` → `icd-10`.
  - **Lookup siblings.** `_SYSTEM_LOOKUP_SIBLINGS`: display-only lookups that fall back to another system, for example `yj` → `hot7`.
- Verified authoritative snapshots live in `clinosim/codes/authoritative/` (§7).

### 3.2 Country code mapping — `clinosim/locale/<cc>/code_mapping_<domain>.yaml`

```yaml
# locale/jp/code_mapping_lab.yaml
WBC: "2A010"
CRP: "5C070"
```

- Maps an **internal name** to the code that country emits, for the domains `lab`, `drug`, `diagnosis` and `procedure`.
- The code system of the value is `codes.system_key_for(kind, country)`. For example `lab`/`US` is `loinc` and `lab`/`JP` is `jlac10`.
- Every value is registered in that system's registry file.

### 3.3 Catalogs — identities with codes and names

| Catalog | File | Entry shape |
|---|---|---|
| Drugs | `codes/data/drugs.yaml` | `<drug_id>: {names: {en, ja}, codes: {rxnorm, yj, hot7}, classes: [...], aliases: [...]}` |
| Procedures | `codes/data/clinosim-procedure-catalog.yaml` | `bedside: [{type, cpt, k_code, name: {en, ja}, anesthesia}]` |
| Staff roles | `codes/data/clinosim-clinician-role.yaml` | `<role>: {title: {en, ja}, staff_prefix, suffix_en, suffix_ja, practitioner_role, qualification: {code, display, display_en}}` |
| Departments | `locale/shared/department_display.yaml` | `<dept>: {en, ja, specialty_snomed}` |

A catalog id (`drug_id`, procedure `type`, role, department) is the stable internal identifier. Codes and names are looked up from it, never the reverse.

### 3.4 Value sets — `clinosim/codes/data/valuesets.yaml`

```yaml
groups:
  diabetes: {space: internal, match: prefix, members: [E11, E10, E13]}
```

- `space` is either `internal` (codes as stored in CIF chronic conditions) or `emitted` (codes after the country mapping).
- `match` is either `prefix` or `exact`.
- Every internal group is also a named patient condition that disease YAMLs may reference.
- Decision logic tests code membership only through a value set; code literals in conditions are not allowed.

### 3.5 Display tables for non-code vocabularies — `clinosim/locale/shared/<vocabulary>.yaml`

```yaml
occupation:
  office: {en: Office worker, ja: 事務職}
```

- Keyed by the internal slug, with one entry per slug and language.
- One table per vocabulary. Examples:
  - `vocabulary.yaml` — occupation, smoking, alcohol, arrival mode
  - `narrative_imaging.yaml` — imaging exams
  - `department_display.yaml`
- FHIR, narrative and LLM prompts read the same table. A second copy of a vocabulary is not allowed.

### 3.6 Phrase catalog — `clinosim/locale/shared/narrative_phrases.yaml`

Sentence templates keyed by dotted id (`prescription.next_visit`), with `{placeholder}` arguments. Read through `t(key, lang, **kwargs)`.

### 3.7 Disease and encounter protocols

A disease YAML refers to codes it owns through its own fields: `icd_codes` (primary, variants, `by_chronic_prefix`), `implied_chronic_codes` and `sequela_code`. It refers to drugs by `drug_id` and to patient conditions by value-set name. Encounter-condition YAMLs follow the same rules.

## 4. Resolution functions

Consumers resolve names only through these functions. Several are added by open PRs; §9 lists the functions that do not exist yet.

### 4.1 Code systems (`clinosim.codes`)

| Function | Returns | Miss |
|---|---|---|
| `display(system, code, lang)` | display in `lang`, then English | `None` |
| `code_exists(system, code, *, exact=False)` | registration check | `False`; raises on an unknown system |
| `get_system_uri(system)` / `system_key_for_uri(uri)` | URI ↔ key | `urn:clinosim:<key>` / `None` |
| `system_key_for(kind, country)` | system key for a domain and country | raises on an unknown kind |
| `is_english_only_system(key_or_uri)` | whether displays are English-only (§5.3) | — |
| `jp_clins_lab_system(kind)` / `jlac10_display(code, lang)` | JP lab CodeSystem URI / JLAC10 display | raises / `None` |
| `codes.loinc`: `loinc_display`, `loinc_coding` | LOINC display / Coding | `None` / coding without display |
| `codes.valuesets`: `concept_group`, `has_condition`, `patient_condition_names`, `code_by_chronic_prefix` | value-set membership | `KeyError` on an unknown group |
| `codes.drugs`: `resolve_drug`, `get_drug`, `find_drug`, `names_drug`, `drug_name_needles` | drug identity and name matching | raises / `None` / `False` |
| `codes.procedures`: `procedure_code`, `procedure_type_display`, `procedure_code_display` | procedure codes and names | `""` / humanised type / `None` |
| `codes.ucum`: `ucum_code`, `ucum_quantity` | UCUM code / FHIR Quantity | unit passed through |
| `codes.prefectures.prefecture_code(name)` | JIS X 0401 code | `""` |
| `codes.snomed_concepts` | named SNOMED concepts used in logic | — |

`lookup(system, code, lang)` is legacy: on a miss it returns the code itself. New code uses `display(...) or <explicit fallback>`.

### 4.2 Country mappings and display tables (`clinosim.locale.loader`)

| Function | Returns |
|---|---|
| `load_code_mapping(domain, country)` | internal name → code for that country |
| `lab_code(lab_name, country)` / `lab_codes(lab_name)` | `(system_key, code)` / the codes of every locale |
| `vocab_display(vocab, slug, lang, *, fallback)` | vocabulary display (`vocabulary.yaml`) |
| `narrative_label(section, key, lang, fallback)` | narrative label |
| `imaging_exam_display(exam_id, lang)` | imaging exam name |
| `department_display(dept, lang)` / `department_specialty_snomed(dept)` | department label / specialty code |
| `role_display(role, lang, *, facet)` | staff role title, suffix or qualification |
| `chronic_followup_vitals(code)` / `chronic_followup_interval_months(codes)` | follow-up schedule data |
| `t(key, lang, **kwargs)` (`clinosim.locale.i18n`) | phrase |

### 4.3 Output helpers

| Function | Use |
|---|---|
| `modules.output.fhir_r4.lib.common.dual_slot_concept(system_key, code, lang, *, text, fallback_display)` | every coded CodeableConcept (§5.3) |
| `modules.output.fhir_r4.lib.common.system_coding(system_key, code, lang, *, fallback_display)` | a Coding-typed element with no `text` slot, such as `Encounter.class` (§5.3) |
| `modules._shared.practitioner_name(staff_id, roster_map)` | practitioner display; `""` on a miss |
| `modules._shared.pick_localized_field(record, base, lang)` | CIF `<base>_<lang>` fields |
| `simulator.event_refs.event_ref_kind(value)` | namespace of a `disease_id` / ground-truth value |

## 5. Localization

### 5.1 Output language

The output language comes from the country: `clinosim.countries.lang_for(country)`, driven by `locale/shared/country_language.yaml`. It is case-insensitive, and an unmapped country gets English. Code tests `countries.is_jp` / `is_us` only for country rules (reimbursement codes, profiles). It never tests them to pick a display language.

### 5.2 Data shape

- **Translatable text** is a `{<lang>: text}` entry. Inline `x_ja if is_jp(...) else x_en` is not allowed.
- **CIF fields** that carry text per language use `<base>` for English and `<base>_<lang>` for the others, read through `pick_localized_field`.
- **New languages** are added by putting a `<lang>` key in the data. No code change is needed.

### 5.3 English-only code systems (dual slot)

`is_english_only_system` covers LOINC, SNOMED CT, HL7 terminology, `http://hl7.org/fhir/`, DICOM and UCUM. For these systems:

- **JP output.** `coding.display` is the English canonical display. The Japanese label goes in `CodeableConcept.text`. A Japanese display inside the coding is a validation error.
- **Other systems.** JP Core, JP-CLINS, MEDIS, YJ and clinosim-owned systems keep the display in the output language.
- **Where it is built.** The concept is built at the emit site with `dual_slot_concept`. It is not filled in later by a post-process walker.
- **Coding-typed elements.** An element whose type is `Coding` (`Encounter.class`, `classHistory.class`) has no `text` slot. It is built with `system_coding` and carries the English display in every locale.
- **HL7 vocabularies.** Each HL7 CodeSystem the generator emits has a code-keyed registry file (`hl7-v3-actcode`, `hl7-v3-actpriority`, `hl7-observation-category`, `hl7-condition-category`, `hl7-v3-participationtype`, `hl7-diagnosis-role`, `hl7-organization-type`, `hl7-observation-interpretation`, ...). Japanese labels are looked up by code, never by the English display.

## 6. Fallback rules

1. **Order.** Requested language, then English, then the caller's **explicit** fallback.
2. **What a fallback never is.** It is never another language (Japanese in English output), the lookup key, the raw code, a raw id or a raw slug.
3. **A missing code or id** returns `None` / `""` from the resolver. The caller decides what to show and passes it explicitly, or omits the element ("silence beats fabrication").
4. **Humanised slugs.** A humanised slug (underscores → spaces) is allowed only as the last fallback of a display table for internal slugs. For example `imaging_exam_display`, `procedure_type_display` and `department_display` humanise an unknown slug. It is allowed only when a unit test asserts that every slug the generator emits is in the table. A title-cased slug (`.title()`) is never allowed.
5. **A missing English entry** is a data bug, and a test detects it. A missing non-English entry falls back to English (rule 1).

## 7. Adding or changing a code

1. **Verify against the authority** before registering:

   | System | Authority |
   |---|---|
   | ICD-10-CM | NLM / CMS |
   | ICD-10 | WHO browser |
   | LOINC | loinc.org or tx.fhir.org `$lookup` |
   | SNOMED CT | tx.fhir.org `$lookup` / SNOMED browser |
   | RxNorm | RxNav |
   | YJ / HOT | MHLW / MEDIS masters |
   | JLAC10 | JSLM master |
   | CPT | AMA CPT |
   | K-codes | MHLW 診療報酬点数表 |
   | HL7 | THO |
   | JP Core / JP-CLINS URIs | the package's fixedUri |

2. **Register the code** in `codes/data/<system>.yaml`, with `en` equal to the authority display.
3. **Update the snapshot** in `codes/authoritative/` when one exists for the system: `rxnorm_rxnav_snapshot.json` or `loinc_2_82_tx.json`.
4. **Add the mapping or catalog entry** that uses the code (§3.2–3.4).
5. **Run the coverage tests:** diagnosis coverage, the authoritative-snapshot tests and the system-URI coverage test.

## 8. Prohibited patterns

- A code-system URI string literal outside `clinosim/codes/`. Use `get_system_uri`. Prefix lists that name URI families are the only exception.
- A code literal in a Python comparison or a Python dict of codes or displays (CPT, LOINC, SNOMED, ICD, YJ, ...). Use a value set, a catalog or a named concept.
- A second table for the same vocabulary or code mapping.
- Identifying a drug, lab or condition by substring of free text. Use the catalog id, canonical lab name or value set (`names_drug` is the one sanctioned name matcher).
- `.title()` or bare `replace("_", " ")` on a slug that reaches output, except under rule 6.4.
- Translating a code display with a free-text translator (`localize_drug_name` and similar) instead of the code system's own `ja` display.
- `lookup(...) or ...`, which never takes the fallback because `lookup` echoes the code.

## 9. Known deviations

These parts of the code base do not yet conform. Each one is removed by the issue listed.

| Deviation | Issue |
|---|---|
| **Fallback.** `display` / `lookup`, `resolve_text` and `t` end with a last-resort value: the first available language, the code, `str(value)` or the key. That can break §6.1–6.2, and there is no single retrieval API. | #2275 |
| ICD lookup, short names and crosswalks are not behind one accessor (two short-name tables, CM/WHO Japanese divergence). | #2257 |
| SNOMED codes and displays are still held in emitter dicts (route, severity), and 74 SNOMED literals are unregistered. | #2258 |
| Document LOINCs are defined in eight places, some section codes do not mean their section, and emitters still hold LOINC constants. | #2344 |
| Legacy JP drug codes (7-digit YJ ingredient prefixes) remain in the drug catalog and are emitted under the HOT7 URI. | #2347 |
| CPT / K-codes the generator emits but has not registered. | #2340 |
| HL7 `terminology.hl7.org` URI literals outside `clinosim/codes/`, and three overlapping coding helpers (`_coding_with_display`, `_value`, `_build_hosp_concept`). | #2349 |
| Remaining hand-built dual-slot concepts, and the post-process text-filling walkers. | #2337 |
| Lab analyte display is spread over five tables. | #2267 |
| Drug names go through free-text translation, not the catalog. | #2271 |
| Language literals are still embedded in Python. | #2277 |
| Records do not carry `drug_id`. | #2297 |
| Drug classes and aliases are held outside the catalog. | #2298 |
| Lab identity uses non-canonical names at some boundaries. | #2299 |
| Checkup results use LOINC as `lab_name`. | #2300 |
| Eval plausibility bounds, and the two panel definitions. | #2332 |
| No lint guard enforces §8. | #2266 |
