# Code mapping, name resolution and localization — specification

Status: **normative**. Every change that adds, maps, resolves or displays a code, a code system, or a localized name follows this document. A change that cannot follow it updates this document in the same PR, with the reason.

Japanese counterpart: [`code-mapping-and-localization-spec.ja.md`](code-mapping-and-localization-spec.ja.md).

## 1. Principles

1. **One source per fact.** Each code, code-system URI, display name and mapping lives in exactly one data file. Python reads it; Python never restates it.
2. **One accessor per authority, one resolver per vocabulary.** Each authority's data sits in its own files and is read by its own module (§2.2). Every kind of lookup — a LOINC display, a drug's Japanese name, a department label — has one named function. Emitters, narrative, LLM prompts, CSV, eval, audit and benchmarks all call that function. None of them re-implements it.
3. **Codes in CIF, names at output.** CIF stores codes and internal ids (AD-30). Displays are resolved when FHIR, narrative or CSV output is written.
4. **No fabrication.** A code is registered only after it is verified against its authority (§8). Something with no verified code stays uncoded rather than getting a guessed code. A display is shown only for the code it belongs to.
5. **English is the base language.** Every translatable entry has English. Every other language is optional and falls back to English (§6).
6. **Adding a language is a data change.** Code never compares a language with a literal such as `"ja"`. It selects text through the functions in §5, so a new language is new keys in the data and one line in `country_language.yaml`.
7. **Every rule has a guard.** A rule in this document is enforced by a test (§10). A rule without one is listed as a gap in §11.

## 2. Layers and authority separation

### 2.1 Layers

| Layer | Package | Owns | May import |
|---|---|---|---|
| Authority code systems | `clinosim/codes/` | registered codes, URIs, displays, value sets, the drug / procedure / role catalogs, UCUM, JIS X 0401, named SNOMED concepts | `clinosim.countries` only (no `clinosim.locale`, no `clinosim.modules`) |
| Country and display data | `clinosim/locale/` | per-country code mappings, display tables for non-code vocabularies, translation tables, the phrase catalog | `clinosim.codes`, `clinosim.countries` |
| Language selection | `clinosim/countries.py` | country → language, language-tag normalization (§5.1) | nothing in clinosim |
| Consumers | `clinosim/modules/`, `clinosim/simulator/`, `clinosim/eval/`, `clinosim/audit/`, `clinosim/benchmarks/` | decision logic, emitters | the layers above, only through the functions in §4 |

### 2.2 One authority, one set of files

An **authority** is the body that defines a code system (NLM, WHO, MHLW, Regenstrief, SNOMED International, HL7, AMA, JSLM, MEDIS, ...). Each authority's material is kept apart from every other authority's:

1. **Data.** Each code system has one registry file named by its system key (§3.3). Internal-key maps and crosswalks for that system are separate files named after it (`loinc-maps.yaml`, `snomed-maps.yaml`).
2. **Accessor.** Every code system is an instance of the `CodeSystem` base class (§2.3). An authority that needs a hook or lookups of its own — a mapping, a hierarchy, a product choice, a canonical-URI rule — has one subclass in `clinosim/codes/<authority>.py`, and that module reads only its authority's files. Authorities served by the base class alone (HL7 terminology, CVX, DICOM, OMB, clinosim-owned systems) are plain instances built from their registry file and need no module.
3. **Snapshot.** Verified extracts from the authority live in `clinosim/codes/authoritative/`, one file per authority and release (`loinc_2_82_tx.json`, `rxnorm_rxnav_snapshot.json`, ...), and a test checks the registry against them.
4. **Catalogs join authorities, they do not own them.** A catalog (drugs, procedures, staff roles) holds internal ids, names and the codes of several authorities. It resolves each code through that authority's accessor; it never re-implements an authority's lookup rule.

Current layout:

| Authority | Registry files | Accessor | Snapshot |
|---|---|---|---|
| ICD-10-CM (NLM / CMS) | `icd-10-cm.yaml` | `codes/icd10.py` | — |
| ICD-10 (WHO; MHLW Japanese names) | `icd-10.yaml` (alias `icd-10-mhlw`) | `codes/icd10.py` | `icd10_who_tx.json`, `icd10_mhlw_2013_ja.json` |
| MEDIS 病名管理番号 | `medis-disease-keyno.yaml` | `codes/icd10.py` (§11) | — |
| LOINC | `loinc.yaml`, `loinc-maps.yaml` | `codes/loinc.py` | `loinc_2_82_tx.json` |
| SNOMED CT | `snomed-ct.yaml`, `snomed-maps.yaml`, `procedure-phrase-to-snomed.yaml`, `procedure-snomed-metadata.yaml` | `codes/snomed.py`, `codes/snomed_concepts.py` | — |
| RxNorm | `rxnorm.yaml` | through `codes/drugs.py` | `rxnorm_rxnav_snapshot.json` |
| YJ / HOT (MHLW, MEDIS) | `yj.yaml`, `hot7.yaml` | `codes/drugs.py` (§11) | `yj_mhlw_snapshot.json`, `JP_MedicationCodeYJ_CS_full.json`, `yj_tx_fragment.json` |
| JLAC10 / JP-CLINS lab | `jlac10.yaml`, `jp-clins-lab-uncoded.yaml` | `codes/loader.py` (§11) | the JP-CLINS package |
| CPT / K-codes | `cpt.yaml`, `k-codes.yaml` | `codes/procedures.py` | `shinryo_koui_ssk_20261013_ja.json` |
| UCUM | `ucum-aliases.yaml` | `codes/ucum.py` | — |
| JIS X 0401 | `jis-x-0401-prefectures.yaml` | `codes/prefectures.py` | — |
| HL7 terminology | `hl7-*.yaml` | generic functions; `codes/hl7_encounter.py` (typed names, checked against the registry) | — |
| JP Core / JP-CLINS / JP eCheckup / MHLW document codes | `jpfhir-*.yaml`, `jp-*.yaml`, `mhlw-*.yaml`, `fhir-profiles-*.yaml` | generic functions | — |
| clinosim-owned systems | `clinosim-*.yaml` | generic functions | — |

### 2.3 Base classes

The operations every source shares are implemented once, in a base class, and are not re-implemented or overridden per source.

**`CodeSystem` (codes layer).** One instance per system key, built from its registry file (§3.3).

- **Owns, final.** `display(code, lang)`, `code_exists(code, *, exact)`, `uri`, language normalization (§5.1), the resolution order (§4.4), the fallback order (§6) and miss handling (`None`, never the code). A subclass never overrides these; a test checks it.
- **Hooks a subclass may implement.** `parents(code)`: the codes a code generalizes to, most specific first (default: none; ICD-10 and ICD-10-CM: the code without its decimal part). Lookup siblings are declared data (§3.3), not code.
- **Authority lookups.** A subclass adds its authority's own lookups as methods, for example the YJ product for a drug and route class, the LOINC code of an internal key, the SNOMED code of a procedure phrase.
- **Registry.** Every system key resolves to exactly one instance, so tests can iterate over all systems (snapshot, URI, `en` coverage).

**`LocalizedTable` (locale layer).** One instance per display table or translation table (§3.7, §3.8).

- **Owns, final.** Loading and kind validation, `get(key, lang, *, fallback)` with the fallback order of §6, and the `en` rule.
- **Declared properties.** Whether an unknown slug is humanised (§6.4) is a property of the table, allowed only for a table whose slug coverage is tested.

**Entry points.** Consumers keep calling the module functions of §4 (`codes.display`, `loinc_display`, `vocab_display`, ...). Those functions delegate to the instances; consumers do not construct or subclass them. Catalogs (§3.5) are not `CodeSystem` subclasses: they hold internal ids and resolve codes through the `CodeSystem` instances.

## 3. YAML authoring

### 3.1 Common rules

These rules apply to every data YAML under `clinosim/codes/data/`, `clinosim/locale/` and `clinosim/modules/*/reference_data/`.

1. **Header.** The file starts with a `metadata` block: `kind` (one of §3.2), `name`, `source` (the authority, or `clinosim` for owned data), plus `uri` for a code system and `verified` (date or release) where the content was checked against an authority. A comment above the block may explain the file.
2. **Keys are identifiers.** A key is an internal identifier: a snake_case slug, a catalog id, a canonical lab name, or the authority's code as the authority writes it. Display text is never a key. The one exception is a translation table (§3.2), whose key is the English source text it translates.
3. **Codes are strings.** Every code value is quoted (`"2A010"`, `"0410"`), so leading zeros and numeric-looking codes survive parsing.
4. **Translatable text is a language map.** `{en: ..., ja: ...}`, English first. `en` is required (except in a translation table, where the key is the English). Language keys are lower-case BCP-47 tags, normally the ISO 639-1 code (`en`, `ja`). A field name never carries a language (`title_ja`, `display_en` are not allowed); a second language is a second key in the map.
5. **Style.** Two-space indent, no tabs, no anchors or aliases. An entry that fits on one line uses flow style (`office: {en: Office worker, ja: 事務職}`); an entry with nested fields uses block style.
6. **Order.** Entries are ordered by key unless the order carries meaning; when it does, `metadata` says so (for example the YJ route-class order in `drugs.yaml`, §3.5).
7. **Editing.** Files are edited by hand or by a script that edits text in place. Loading and re-dumping a file is not allowed, because it drops every comment. A generated file says in its header which script and source produced it.
8. **Validation.** Each kind has a schema, and a test validates every file against it. A loader rejects unknown fields instead of ignoring them.

### 3.2 Kinds and where they live

| `kind` | Holds | Location and name |
|---|---|---|
| `code-system` | the codes of one system with their displays | `codes/data/<system-key>.yaml` (§3.3) |
| `map` | internal key → code of one system | `codes/data/<system-key>-maps.yaml` |
| `crosswalk` | code or phrase → code of another system | `codes/data/<from>-to-<to>.yaml` or `<from>-<subject>-crosswalk.yaml` |
| `catalog` | internal identities with their codes and names | `codes/data/` (§3.5) |
| `value-set` | named groups of codes | `codes/data/valuesets.yaml` (§3.6) |
| `country-mapping` | internal name → the code one country emits | `locale/<cc>/code_mapping_<domain>.yaml` (§3.4) |
| `display-table` | internal slug → display, for a vocabulary that has no code | `locale/shared/<vocabulary>.yaml` (§3.7) |
| `translation-table` | English source text → other languages, for free text the generator writes in English | `locale/shared/` |
| `phrase-catalog` | sentence templates | `locale/shared/narrative_phrases.yaml` (§3.8) |
| `reference` | thresholds, keyword lists, content that is not code or display data | `modules/<module>/reference_data/` |

`codes/data` holds only `code-system`, `map`, `crosswalk`, `catalog` and `value-set` files.

### 3.3 Code-system registry

```yaml
metadata:
  kind: code-system
  name: HL7 FHIR Discharge Disposition
  uri: http://terminology.hl7.org/CodeSystem/discharge-disposition   # canonical URI (spec fixedUri)
  source: "HL7 Terminology (THO)"                                    # authority the codes were verified against
codes:
  home: {en: "Home", ja: "自宅退院"}
  exp:  {en: "Expired", ja: "死亡退院"}
```

- The file name is the **system key** used by every resolver (`loinc`, `snomed-ct`, `icd-10-cm`, `hl7-discharge-disposition`, ...).
- `codes.<code>.en` is **required** and equals the authority's display, for example the LOINC long common name or the SNOMED preferred term. Other languages are optional keys.
- Systems without code data, used only for their URI, are registered in `_BUILTIN_URIS` (`codes/loader.py`) under a key. Two mechanisms let several keys share data:
  - **Data aliases.** `_SYSTEM_DATA_ALIASES`: the same data under another URI, for example `icd-10-mhlw` → `icd-10`.
  - **Lookup siblings.** `_SYSTEM_LOOKUP_SIBLINGS`: display lookups that fall back to another system, for example `yj` → `hot7`, and an ICD-10-CM code taking the MHLW Japanese name of the same WHO code.
- A system the generator addresses by slug rather than by code (OMB race and ethnicity) keeps a `slug_to_code` block in the same file, read through `slug_to_code`.

### 3.4 Country code mapping

```yaml
# locale/jp/code_mapping_lab.yaml
WBC: "2A010"
CRP: "5C070"
```

- Maps an **internal name** to the code that country emits, for the domains `lab`, `drug`, `diagnosis` and `procedure`.
- The code system of the value is `codes.system_key_for(kind, country)`. For example `lab`/`US` is `loinc` and `lab`/`JP` is `jlac10`.
- Every value is registered in that system's registry file.

### 3.5 Catalogs

| Catalog | File | Entry shape |
|---|---|---|
| Drugs | `codes/data/drugs.yaml` | `<drug_id>: {names: {en, ja}, codes: {rxnorm, yj: {<route_class>: <YJ12>}}, classes: [...], aliases: [...]}` |
| Procedures | `codes/data/clinosim-procedure-catalog.yaml` | `bedside: [{type, cpt, k_code, name: {en, ja}, anesthesia}]` |
| Staff roles | `codes/data/clinosim-clinician-role.yaml` | `<role>: {title: {en, ja}, staff_prefix, suffix, practitioner_role, qualification: {code, display}}` (`suffix` and `qualification.display` are language maps; §11) |
| Departments | `locale/shared/department_display.yaml` | `<dept>: {en, ja, specialty_snomed}` |

A catalog id (`drug_id`, procedure `type`, role, department) is the stable internal identifier. Codes and names are looked up from it, never the reverse.

**JP drug codes.** A YJ code names one product, which fixes its form and strength. So `codes.yj` maps a route class (`oral`, `injection`, `inhalation`, `rectal`, `topical`, `intravesical`; the `route_classes` table at the top of `drugs.yaml`) to a full 12-character YJ code:

- **Order.** The most-used route comes first. `codes["yj"]` is that first code, for lookups that have no route.
- **Choice.** The product is the one that matches the simulator's usual dose. The original brand is preferred.
- **Verification.** Every code is listed in the MHLW YJ master (snapshot: `codes/authoritative/yj_mhlw_snapshot.json`) and in `JP_MedicationCodeYJ_CS_full.json`.
- **No product.** A drug with no listed product for a route has no code there. It is emitted in the eCS `nocoded` slice.
- **Not used.** A 7-digit YJ prefix is never a code, and `hot7.yaml` registers no codes.

### 3.6 Value sets

```yaml
groups:
  diabetes: {space: internal, match: prefix, members: [E11, E10, E13]}
```

- `space` is either `internal` (codes as stored in CIF chronic conditions) or `emitted` (codes after the country mapping).
- `match` is either `prefix` or `exact`.
- Every internal group is also a named patient condition that disease YAMLs may reference.
- Decision logic tests code membership only through a value set; code literals in conditions are not allowed.

### 3.7 Display tables

```yaml
occupation:
  office: {en: Office worker, ja: 事務職}
```

- Keyed by the internal slug, with one language map per slug.
- One table per vocabulary. Examples:
  - `vocabulary.yaml` — occupation, smoking, alcohol, arrival mode
  - `narrative_imaging.yaml` — imaging exams
  - `lab_display.yaml` — lab analytes and panels, keyed by lower-cased lab token; the language map is the clinician short form and an optional `formal` map holds the full analyte name
  - `department_display.yaml`
- FHIR, narrative and LLM prompts read the same table. A second copy of a vocabulary is not allowed, and a vocabulary that has codes takes its labels from the code system (§5.3), not from a display table.

### 3.8 Translation tables and the phrase catalog

- **Translation table.** For names the generator writes as English free text (order strings, medication terms), a translation table maps the English text to other languages: `"dvt prophylaxis": {ja: DVT予防}`. It is read only through the free-text resolvers in §4.3. It never translates a code's display (that is the code system's own `ja`), and it never holds text whose source is a data file (that text carries its own language map at its source).
- **Phrase catalog.** Sentence templates keyed by dotted id (`prescription.next_visit`), with `{placeholder}` arguments, read through `t(key, lang, **kwargs)`.

### 3.9 Disease and encounter protocols

A disease YAML refers to codes it owns through its own fields: `icd_codes` (primary, variants, `by_chronic_prefix`), `implied_chronic_codes` and `sequela_code`. It refers to drugs by `drug_id` and to patient conditions by value-set name. Text it shows (chief complaints, notes) is a language map in the protocol itself. Encounter-condition YAMLs follow the same rules.

## 4. Resolution functions

Consumers resolve names only through these functions.

### 4.1 Code systems (`clinosim.codes`)

| Function | Returns | Miss |
|---|---|---|
| `display(system, code, lang)` | display in `lang`, then English (§4.4) | `None` |
| `code_exists(system, code, *, exact=False)` | registration check | `False`; raises on an unknown system |
| `get_system_uri(system)` / `system_key_for_uri(uri)` | URI ↔ key | `urn:clinosim:<key>` / `None` |
| `data_table(name)` | parsed `codes/data/<name>.yaml` for a table without its own accessor (a copy) | raises `FileNotFoundError` |
| `system_key_for(kind, country)` | system key for a domain and country | raises on an unknown kind |
| `is_english_only_system(key_or_uri)` | whether displays are English-only (§5.3) | — |
| `slug_to_code(system)` | a system's `slug_to_code` block | `{}` |
| `code_system(system)` / `system_keys()` | the system's `CodeSystem` instance (§2.3) / every system key, for tests that iterate all systems | `None` / — |
| `jp_clins_lab_system(kind)` / `jlac10_display(code, lang)` | JP lab CodeSystem URI / JLAC10 display | raises / `None` |
| `codes.loinc`: `loinc_display`, `loinc_coding` | LOINC display / Coding | `None` / coding without display |
| `codes.loinc`: `loinc_for(kind, key)`, `loinc_map(kind)` | LOINC code of an internal key (`codes/data/loinc-maps.yaml`: anthropometric, blood_group, care_level, report, section, apgar, newborn_screen) | `KeyError` on an unknown kind or key |
| `modules.document.narrative.registry.document_loinc(doc_type)` | a document type's LOINC code, defined once in `document_type_specs.yaml` | raises on an unknown type |
| `codes.valuesets`: `concept_group`, `has_condition`, `patient_condition_names`, `code_by_chronic_prefix` | value-set membership | `KeyError` on an unknown group |
| `codes.drugs`: `resolve_drug`, `get_drug`, `find_drug`, `drug_key(ref)`, `same_drug(a, b)` | drug identity; identity key (catalog id, else the normalised name) and whether two references name the same drug — no substring matching | raises / `None` / `""` / `False` |
| `codes.drugs`: `route_class(route)`, `jp_drug_code(drug, route)`, `jp_drug_code_table(route)` | route class of an order route; the JP YJ product for a drug and route | `""` / `None` / no entry |
| `codes.drugs`: `drug_display(ref, lang)` | catalog name of a drug id, name or alias (then its longest leading-word prefix) in `lang`, then English | `None` |
| `codes.drugs`: `identify_drug(text)`, `drug_classes(ref)` | the catalog drug a free-text medication string names (exact id / name / alias, leading words, then the longest contained name or alias — whole-word for ASCII); its catalog classes with every dotted ancestor | `None` / `()` |
| `codes.drugs`: `drug_ref(name_or_id)`, `has_drug(meds, drug_id_or_class)`, `medication_matches(med, drugs, classes)` | the catalog `drug_id` a name, alias or free-text string names; whether any medication record is that drug or in that class (by its `drug_id`, else its name) | `""` / `False` |
| `codes.icd10`: `icd10_system(country)`, `icd10_display(code, country, lang)`, `condition_short_name(code, lang)`, `condition_label(code, country, lang)`, `medis_disease_keyno(icd)` | ICD-10 system of a country; official display (JP Japanese: the MHLW 2013 name, verbatim); clinical short name (by category); the name used in prose and `Condition.code.text` (short name, then official display); MEDIS 病名管理番号 | key / `None` / `None` / `None` / `None` |
| `codes.procedures`: `procedure_code`, `procedure_type_display`, `procedure_code_display` | procedure codes and names | `""` / humanised type / `None` |
| `codes.ucum`: `ucum_code`, `ucum_quantity`, `ucum_prose` | UCUM code / FHIR Quantity / the unit as written in prose (`mm[Hg]` → `mmHg`, `{INR}` → `""`) | unit passed through |
| `codes.prefectures.prefecture_code(name)` | JIS X 0401 code | `""` |
| `codes.snomed_concepts` | named SNOMED concepts used in logic | — |
| `codes.snomed`: `snomed_display(code, lang)`, `snomed_for(kind, key)`, `snomed_map(kind)`, `snomed_for_phrase(text)` | SNOMED display; internal key → code (`route`, `severity`, `abo`, `rh`, `cchd_site`, `encounter_type`, `oxygen_device`, `stage`, `procedure_category`, `order_category`, `specimen_type`, `newborn_screen`; `codes/data/snomed-maps.yaml`); free-text procedure / order name → code (first matching phrase in `codes/data/procedure-phrase-to-snomed.yaml`) | `None` / `None` / `KeyError` / `None` |

`lookup(system, code, lang)` is `display(...)` with `""` on a miss; it never returns the code itself. New code uses `display(...) or <explicit fallback>`.

### 4.2 Country mappings and display tables (`clinosim.locale.loader`)

| Function | Returns |
|---|---|
| `load_code_mapping(domain, country)` | internal name → code for that country |
| `lab_code(lab_name, country)` / `lab_codes(lab_name)` | `(system_key, code)` / the codes of every locale |
| `vocab_display(vocab, slug, lang, *, fallback)` | vocabulary display (`vocabulary.yaml`) |
| `narrative_label(section, key, lang, fallback)` | narrative label |
| `imaging_exam_display(exam_id, lang)` | imaging exam name |
| `lab_display(name, lang, *, style, fallback)` | lab analyte or panel name: `style="prose"` for narrative, LLM text and `DiagnosticReport.conclusion`; `style="formal"` for the FHIR `code.text` of analytes with no standard code. A coded `Observation.code.coding.display` keeps the authority display |
| `department_display(dept, lang)` / `department_specialty_snomed(dept)` | department label / specialty code |
| `role_display(role, lang, *, facet)` | staff role title, suffix or qualification |
| `chronic_followup_vitals(code)` / `chronic_followup_interval_months(codes)` | follow-up schedule data |
| `t(key, lang, **kwargs)` (`clinosim.locale.i18n`) | phrase; `""` for an unknown key (never the key) |
| `locale.localized`: `localized(entry, lang, *, fallback)`, `localized_field(record, base, lang, *, fallback)`, `label(catalog, section, key, lang, *, fallback)` | the one value selection for language maps, `<base>_<lang>` fields and vocabulary catalogs (§6). `t`, `resolve_localized_display` and `resolve_text` delegate to it |

### 4.3 Free-text names (`clinosim.locale.free_text`)

For names that reach the generator as English free text and have no code or catalog id. Each kind of name has its own resolver over its own table.

| Function | Table | Returns |
|---|---|---|
| `localize_drug_name(name, lang)` | drug catalog names and aliases, admin-form variants (`load_drug_display_dict`) | the name in `lang`; unchanged when `lang` has no entry |
| `localize_procedure_name(name, lang)` | procedure phrases and imaging exams (`load_procedure_display_dict`), exact match first, then the free-text translator for a composite order string | same |
| `localize_allergen_name(name, lang)` | allergen and substance names (`load_allergen_display_dict`) | same |
| `localize_free_text(text, lang)` | every table (`load_narrative_display_dict`) and the dosage / route / frequency terms (`med_terms.yaml`) | same |

A caller that holds a code or a catalog id uses §4.1 instead. These resolvers never translate a code display.

### 4.4 How `display` resolves a code

The `CodeSystem` base class (§2.3) resolves every system in this order:

1. The exact code in the system.
2. The codes returned by the system's `parents` hook (`E11.9` → `E11`): generalizations of the code, which are still true of it.
3. Steps 1–2 in each lookup sibling of the system (§3.3).
4. Otherwise `None`. A display of a more specific child code is never used for a less specific code (§11).

The language of the entry is chosen by §6: the requested language, then the same code's entry in that language in a lookup sibling, then English, then `None`.

### 4.5 Output helpers

| Function | Use |
|---|---|
| `modules.output.fhir_r4.lib.common.dual_slot_concept(system_key, code, lang, *, text, fallback_display)` | every coded CodeableConcept (§5.3) |
| `modules.output.fhir_r4.lib.common.system_coding(system_key, code, lang, *, fallback_display)` | a Coding-typed element with no `text` slot, such as `Encounter.class` (§5.3) |
| `modules._shared.practitioner_name(staff_id, roster_map)` | practitioner display; `""` on a miss |
| `simulator.event_refs.event_ref_kind(value)` | namespace of a `disease_id` / ground-truth value |

`modules._shared.pick_localized_field` and `modules._shared.resolve_lang` forward to `localized_field` and `lang_for`; new code calls those directly (§11).

## 5. Localization

### 5.1 Output language

- **From the country.** The output language comes from the country: `clinosim.countries.lang_for(country)`, driven by `locale/shared/country_language.yaml`. It is case-insensitive, and an unmapped country gets English.
- **Country rules are not language rules.** Code tests `countries.is_jp` / `is_us` only for country rules (reimbursement codes, profiles, JP-only sections). It never tests them, and never compares the language with a literal, to pick a display.
- **Language tags.** Every function that takes `lang` normalizes it the same way: lower-cased; a country code becomes its language (`"JP"` → `ja`); a regional tag falls back to its primary subtag (`ja-JP` → `ja`); empty becomes `en`. The `codes` layer and the `locale` layer share this one normalization (§11).

### 5.2 Data shape

- **Translatable text in YAML** is a language map (§3.1 rule 4). Inline `x_ja if is_jp(...) else x_en` is not allowed.
- **CIF fields** (Pydantic record fields, not YAML) that carry text per language use `<base>` for English and `<base>_<lang>` for the others, read through `localized_field`, which also accepts `<base>_en`.
- **New languages** are added by putting a `<lang>` key in the data. No code change is needed.

### 5.3 English-only code systems (dual slot)

`is_english_only_system` covers LOINC, SNOMED CT, HL7 terminology, `http://hl7.org/fhir/`, DICOM and UCUM. For these systems:

- **JP output.** `coding.display` is the English canonical display. The Japanese label goes in `CodeableConcept.text`. A Japanese display inside the coding is a validation error.
- **Other systems.** JP Core, JP-CLINS, MEDIS, YJ and clinosim-owned systems keep the display in the output language.
- **Where it is built.** The concept is built at the emit site with `dual_slot_concept`. It is not filled in later by a post-process walker.
- **Coding-typed elements.** An element whose type is `Coding` (`Encounter.class`, `classHistory.class`) has no `text` slot. It is built with `system_coding` and carries the English display in every locale.
- **HL7 vocabularies.** Each HL7 CodeSystem the generator emits has a code-keyed registry file (`hl7-v3-actcode`, `hl7-v3-actpriority`, `hl7-observation-category`, `hl7-condition-category`, `hl7-v3-participationtype`, `hl7-diagnosis-role`, `hl7-organization-type`, `hl7-observation-interpretation`, ...). Japanese labels are looked up by code, never by the English display.
- **Labels for coded vocabularies.** The `text` label of a coded concept (route, frequency, specimen, ...) comes from the language map beside that concept's code, not from a separate per-language table (§11).

## 6. Fallback rules

These rules are common to every resolver in §4, in both layers.

1. **Order.** Requested language, then English, then the caller's **explicit** fallback.
2. **What a fallback never is.** It is never another non-English language (Japanese in English output), the lookup key, the raw code, a raw id or a raw slug.
3. **A missing code or id** returns `None` / `""` from the resolver. The caller decides what to show and passes it explicitly, or omits the element ("silence beats fabrication").
4. **Humanised slugs.** A humanised slug (underscores → spaces) is allowed only as the last fallback of a display table for internal slugs. For example `imaging_exam_display`, `procedure_type_display`, `department_display` and `lab_display` humanise an unknown slug. It is allowed only when a unit test asserts that every slug the generator emits is in the table. A title-cased slug (`.title()`) is never allowed.
5. **A missing English entry** is a data bug, and a test detects it. A missing non-English entry falls back to English (rule 1).
6. **Free text with no table entry** stays in English: the free-text resolvers (§4.3) return their input unchanged.

## 7. Extending

### 7.1 A new code system or authority

1. Verify the codes (§8).
2. Add `codes/data/<system-key>.yaml` (§3.3) and, if the URI is not in the file, the key in `_BUILTIN_URIS`.
3. If the authority needs a hook or lookups of its own, add a `CodeSystem` subclass in `codes/<authority>.py` (§2.3) and list it in §2.2 and §4.1; otherwise the registry file alone gives a plain instance.
4. Add the authoritative snapshot and its test, if the authority publishes one.
5. Add the system to `is_english_only_system` when its displays are English-only.

### 7.2 A new language

1. Map the countries that use it in `locale/shared/country_language.yaml`.
2. Add the `<lang>` key to the language maps that should show it: code-system registries, catalogs, display tables, translation tables, the phrase catalog.
3. Run the coverage tests (§10). Every entry without the new key falls back to English; no code changes.

### 7.3 A new country

1. Map its language (§7.2).
2. Add `locale/<cc>/code_mapping_<domain>.yaml` for each domain whose code system differs, and the country's rows in `system_key_for`.
3. Country rules (profiles, reimbursement codes) test the country, not the language (§5.1).

### 7.4 A new vocabulary

1. If it has codes, it is a code system (§7.1) and its labels live in its registry file.
2. Otherwise add one display table `locale/shared/<vocabulary>.yaml` (§3.7) with `en` for every slug, load it as a `LocalizedTable` (§2.3), and add one entry-point function in §4.2.

## 8. Adding or changing a code

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
3. **Update the snapshot** in `codes/authoritative/` when one exists for the system.
4. **Add the mapping or catalog entry** that uses the code (§3.4–3.6).
5. **Run the coverage tests:** diagnosis coverage, the authoritative-snapshot tests and the system-URI coverage test.

## 9. Prohibited patterns

- A code-system URI string literal outside `clinosim/codes/`. Use `get_system_uri`. Prefix lists that name URI families are the only exception.
- Reading a `codes/data/*.yaml` file directly, or importing `clinosim.codes.loader._load_system`, outside `clinosim/codes/`. Use the per-source accessor or `data_table`.
- An authority's lookup rule implemented outside that authority's accessor (§2.2).
- A code literal in a Python comparison, or a Python dict, list or enum of codes or displays (CPT, LOINC, SNOMED, ICD, YJ, HL7, ...). Use a value set, a catalog, a registry file or a named concept. The one exception is an enum that only names registered codes for typing and checks every member against its registry file at import (`codes/hl7_encounter.py`).
- A second table for the same vocabulary or code mapping, including a per-language table beside the vocabulary's own.
- Identifying a drug, lab or condition by substring of free text. Use the catalog id, canonical lab name or value set; `identify_drug` is the one sanctioned free-text drug matcher.
- Comparing a language with a literal (`lang == "ja"`, `lang != "ja"`) or selecting by `is_jp` to pick a display. Use §4.2.
- A language in a YAML field name (`title_ja`), display text as a YAML key outside a translation table, or an unquoted code value.
- `.title()` or bare `replace("_", " ")` on a slug that reaches output, except under rule 6.4.
- Translating a code display with a free-text resolver (§4.3) instead of the code system's own `ja` display.
- `lookup(...)` in new code. Use `display(...) or <explicit fallback>`, which makes the fallback visible.

## 10. Enforcement

| Rule | Test |
|---|---|
| Functions and files named here exist; deviations name an issue | `tests/unit/test_code_mapping_spec_2342.py` |
| URIs and code data only through `clinosim.codes` | `tests/unit/codes/test_codes_lint_guard_2266.py`, `tests/unit/test_system_uri_coverage.py`, `tests/unit/test_hl7_uri_registry_2349.py`, `tests/unit/test_registry_uris_2265.py` |
| Canonical URIs match the profiles' fixedUri | `tests/unit/test_registry_uri_pin.py` |
| Registry displays match the authority | `tests/unit/codes/test_display_matches_authoritative.py` |
| Emitted codes are registered | `tests/unit/codes/test_emitted_diagnosis_registered_2429.py`, `tests/unit/codes/test_procedure_codes_registered_2340.py` |
| A miss never echoes the code | `tests/unit/codes/test_no_code_echo_2416.py` |
| Dual slot for English-only systems | `tests/unit/test_dual_slot_2276.py` |
| One selection API and fallback order | `tests/unit/locale/test_localized_api_2395.py` |
| No direct language selection | `tests/unit/locale/test_no_direct_language_selection_2397.py` |
| No comparison of a language with a literal (ratchet: remaining sites pinned to their issues) | `tests/unit/locale/test_no_language_literal_comparison_2455.py` |
| Language-suffixed YAML fields that remain (§11) pair `<base>_ja` with `<base>_en` | `tests/unit/locale/test_localized_field_shape_2398.py` |
| No Japanese in non-JP output, no Japanese literals in Python | `tests/unit/test_no_japanese_fallback_2273.py`, `tests/unit/test_no_japanese_literals_2277.py`, `tests/unit/test_narrative_literals_2400.py`, `tests/unit/test_module_literals_2406.py`, `tests/unit/test_simulator_literals_2405.py`, `tests/unit/output/test_fhir_lib_literals_2402.py`, `tests/unit/output/test_fhir_lab_condition_literals_2403.py`, `tests/unit/output/test_fhir_emitter_literals_2404.py` |
| A third country is not treated as the US | `tests/unit/test_third_country_fallbacks_2203.py` |
| Every entry has English; YAML header and schema per kind; base-class operations not overridden | none yet (§11) |

## 11. Known deviations

These parts of the code base do not yet conform. Each one is removed by the issue listed; [#2452](https://github.com/TomoOkuyama/clinosim/issues/2452) tracks them all.

| Deviation | Issue |
|---|---|
| Display tables are loaded by separate functions with their own miss handling, not by `LocalizedTable` (§2.3) | #2471 |
| `codes.display` matches the language argument exactly: no country-code or case normalization, no BCP-47 primary-subtag fallback (§5.1) | #2453 |
| `display` / `code_exists` fall back to the first registered child of a code (§4.4) | #2454 |
| Narrative renderers compare the language with `"ja"` (29 comparisons in 16 files) | #2456 |
| FHIR emitters and shared helpers compare the language with `"ja"` | #2457 |
| `codes/data/fhir-ja-labels.yaml` is a Japanese-only second table for routes, frequencies and fixed labels (§5.3) | #2459 |
| Slug-keyed display tables have entries without `en` (§6.5) | #2460 |
| `chief_complaint_translations.yaml` translates protocol text keyed by its English sentence (§3.9) | #2461 |
| `clinosim-clinician-role.yaml`, `perinatal.yaml`, `chronic_followup.yaml`, `pregnancy_substitutions.yaml` use language-suffixed field names (§3.1) | #2462 |
| JLAC10 / JP-CLINS lookups sit in the generic loader, MEDIS in the ICD-10 module, YJ / HOT only in the drug catalog module (§2.2) | #2463 |
| Data YAMLs lack the `metadata.kind` header and per-kind schema validation (§3.1) | #2465 |
| `codes/data` holds reference data and translation tables (§3.2) | #2466 |
| Duplicate resolver names and pass-through wrappers (`llm_service.engine.loinc_for`, `fhir_r4.lib.common.loinc_coding`, `pick_localized_field`, `resolve_lang`, `get_display`, `codes.match`) | #2467 |
