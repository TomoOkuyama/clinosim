# `clinosim/modules/drug_safety/reference_data/`

YAML schemas for the drug_safety module. All five files
(`contraindications.yaml`, `disease_contraindications.yaml`,
`demographic_gates.yaml`, `allergy_contraindications.yaml`,
`drug_substitution.yaml`) are loaded on
first use (cached via `functools.lru_cache`) through
`clinosim.datafiles.load_validated_yaml`, which drops the `metadata`
header and validates the content against an `extra="forbid"` Pydantic
model in [`../_models.py`](../_models.py): `ContraindicationsFile`,
`DiseaseContraindicationsFile`, `DemographicGatesFile`,
`AllergyContraindicationsFile`, `DrugSubstitutionFile`. A typo, an unknown key, a class or drug id
missing from the drug catalog, or a duplicate rule id raises
`pydantic.ValidationError` at load.

## Drug classes

Drug identity, aliases and classes live in the drug catalog
(`clinosim/codes/data/drugs.yaml`, Issue #2298). The classifier resolves a
free-text drug name with `clinosim.codes.drugs.identify_drug` (exact id /
name / alias, then leading words, then the longest catalog name or alias
the text contains, whole-word for ASCII) and its classes with
`drug_classes`, which adds every dotted ancestor (`anticoagulant.vka` →
`anticoagulant`). Adding a drug or a class is a catalog edit.

Class taxonomy conventions:

- `anticoagulant.{vka, doac, heparin}`
- `antiplatelet.{cox_inhibitor, p2y12}`
- `nsaid.{non_selective, preferential_cox2, cox2_selective}` (Aspirin is dual-class,
  belonging to both `antiplatelet.cox_inhibitor` and
  `nsaid.non_selective`)
- `ccb.{dhp, non_dhp}`
- `beta_blocker.{cardioselective, non_selective}`
- `acei` / `arb` / `acei_arb` (union tag on both)
- `potassium_supplement`, `electrolyte_supplement`
- `diuretic.{loop, thiazide, k_sparing}`
- `statin`, `cyp3a4_substrate`, `cyp3a4_inhibitor_strong`
- `xanthine_oxidase_inhibitor`, `thiopurine`, `immunosuppressant`
- `ssri`, `snri`, `maoi`, `antidepressant`, `atypical_antidepressant`,
  `antiparkinsonian`
- `benzodiazepine`, `anxiolytic`, `biguanide`, `lithium`
- `analgesic.non_opioid`, `macrolide`
- `antihypertensive`, `antiarrhythmic.class4`

**Rule of thumb**: assign every class the drug belongs to. Rules are
matched by class, so a drug added to an existing class automatically
inherits every rule targeting that class.

## `contraindications.yaml`

Class × class contraindication rules. Adding a rule = pure YAML edit.

```yaml
rules:
  - id: <kebab-case unique identifier>
    lhs: <catalog class tag>
    rhs: <catalog class tag>
    severity: minor | moderate | major | contraindicated
    rationale:
      en: "<one-sentence clinical justification>"
      ja: "<Japanese translation>"
    substitution_hint: <optional indication tag; null if no substitute>
    source: "<citation: guideline / DDI database / textbook>"
    exempt:                        # optional (Issue #3003): pairs the rule does not apply to
      - lhs: <class of the drug on the lhs side>
        rhs: <class of the drug on the rhs side>
        source: "<citation>"

discharge_reconciliation_rules: [<rule id>, ...]   # rules the discharge Rx reconciles (Issue #2713)

triple_therapy_after_acs:          # antithrombotic plan: anticoagulant + DAPT after ACS
  aspirin_days: <int >= 1>
  p2y12_with_oac: <catalog drug id>
  p2y12_dose: "<dose string>"
```

`discharge_reconciliation_rules` must name rule ids defined in
`rules` (read by `discharge_reconciliation_rules()`);
`triple_therapy_after_acs` is read by `triple_therapy_after_acs_plan()`.

Matching:
- **Order-independent**: `check_pair(A, B) == check_pair(B, A)`.
- **Multi-rule hits**: highest-severity rule wins.
- **Exemptions**: a pair matching one of the rule's `exempt` entries
  (oriented like `lhs` / `rhs`) does not trigger it — e.g. heparin with
  antiplatelet aspirin under `anticoagulant-plus-nsaid`.

`substitution_hint` names an indication tag that `suggest_alternative`
uses as a prior when picking a replacement drug from
`drug_substitution.yaml` or from the disease YAML `alternative_*`
blocks.

Severity → default action (`allowed` is the verdict when no rule
matches; a rule cannot assert it):
| severity          | default_action    | narrative surface           |
|-------------------|-------------------|-----------------------------|
| `allowed`         | `emit`            | —                           |
| `minor`           | `emit`            | —                           |
| `moderate`        | `emit_with_note`  | MR.note caution attached    |
| `major`           | `skip`            | substitute + skip log entry |
| `contraindicated` | `skip`            | substitute + skip log entry |

## `disease_contraindications.yaml`

Drug class × chronic-disease-state rules, consumed by
`check_candidate_against_disease_state`.

```yaml
rules:
  - id: <kebab-case unique identifier>
    drug_class: <catalog class tag (codes/data/drugs.yaml)>
    disease_predicate:
      icd_prefix: [<ICD-10 prefixes>]      # required, non-empty
      stage_in: [<stage strings>]          # optional (Issue #1769); entry must carry a matching stage
    severity: minor | moderate | major | contraindicated
    substitution_hint: <optional indication tag>
    rationale:
      en: "..."
      ja: "..."
    source: "..."
```

`active_conditions` entries are bare ICD strings or `(code, stage)`
tuples. Every matching rule is returned (one `SafetyVerdict` each);
callers pick the highest severity.

## `demographic_gates.yaml`

Age / sex "prescribe at all?" rules, consumed by
`demographic.check_demographic_gate`.

```yaml
rules:
  - id: <kebab-case unique identifier>
    drug_names: [<case-insensitive substring aliases — EN / JA / brand>]
    min_age: <int >= 0>            # optional — patient must be >= this
    sex: male | female             # optional
    exception_indications: [<ICD-10 prefixes>]   # optional bypass
    severity: minor | moderate | major | contraindicated
    rationale:
      en: "..."
      ja: "..."
    references: "<citation>"
```

A rule must gate at least one of `min_age` / `sex`; there is no upper
age gate.

When several rules fire, the highest-severity verdict wins (ties: first
rule).

## `allergy_contraindications.yaml`

Drug class × recorded-allergy rules (Issue #2924), read by
`engine.check_candidate_against_allergies`.

```yaml
rules:
  - id: <kebab-case unique identifier>
    allergen_code: "<SNOMED code of a medication allergen in modules/allergy/reference_data/allergens.yaml>"
    drug_classes: [<catalog class tag>, ...]     # the candidate belongs to one of these
    exclude_classes: [<catalog class tag>, ...]  # optional: and to none of these
    severity: minor | moderate | major | contraindicated
    rationale: {en: "...", ja: "..."}
    substitution_hint: <optional indication tag for suggest_alternative>
    source: "<citation>"
```

A rule fires when the patient has an active allergy record (clinical
status `active`, not refuted, not the "No known allergy" assertion) to
`allergen_code`. `contraindicated` / `major` drop the drug (logged on
`safety_skip_log`, substituted when `suggest_alternative` finds an
alternative for `substitution_hint`); `moderate` / `minor` keep it with a
caution note. Cross-reactive classes that current evidence treats as low
risk (cephalosporins in penicillin allergy, selective COX-2 inhibitors in
aspirin allergy, sulfonamide non-antibiotics in sulfonamide antibiotic
allergy) are `moderate`.

## `drug_substitution.yaml`

Generic indication → alternative drug pool. Consulted after
disease-YAML `alternative_*` blocks (via `_indication_tag`) and before
returning `None`.

```yaml
indications:
  <indication_tag>:
    description: "<one-line explanation>"
    alternatives:
      - drug_id: <id in clinosim/codes/data/drugs.yaml>   # display (en + ja) resolved via the catalog
        default_dose: "<neutral dose string>"
        default_route: "<PO | IV | SC | INH>"
        default_frequency: "<daily | bid | tid | qid | prn | q6h_prn>"
```

`suggest_alternative` iterates the `alternatives` list in order and
re-checks each candidate against the caller's active meds via
`check_candidate_against_active` (pairwise `check_pair`). The first conflict-free entry wins.

## `hyperkalemia_response.yaml`

Inpatient response to a potassium result (Issue #2981), read by
`clinosim.modules.drug_safety.hyperkalemia` and validated by
`HyperkalemiaResponseFile`:

- `treat_threshold_mmol_l` — potassium (mmol/L) at or above which drugs
  are held and the order set is placed (6.0).
- `hold_classes` — catalog classes whose doses are held from the result to
  discharge (`acei`, `arb`, `diuretic.k_sparing`).
- `treatment.<US|JP>` — one-time orders: `drug_id` (catalog), `dose` (the
  parseable order dose, e.g. `1 g IV`) and `dose_text.{en,ja}` (the
  localised instruction); `ongoing: true` (the binder) repeats the entry
  on consecutive days at or above the threshold.

## Adding a new rule

1. Give the drugs the rule targets their classes in `codes/data/drugs.yaml`.
2. Add the rule to `contraindications.yaml`, citing the source
   guideline. Set `substitution_hint` when a natural indication tag
   exists.
3. If the substitution_hint is new, add it to `drug_substitution.yaml`
   (or add an `_indication_tag` marker to a disease YAML
   `alternative_*` block if one exists for the disease scope).
4. Add a unit test asserting `check_pair(drug_a, drug_b).severity ==
   <expected>`.
5. Cohort-verify: run `verify_medical_stats.py` on a p=1000 sim and
   confirm `contraindicated_pair_count` stays at 0.

Japanese counterpart: [`README.ja.md`](README.ja.md).
