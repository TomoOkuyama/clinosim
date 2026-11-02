# `clinosim/modules/drug_safety/reference_data/`

YAML schemas for the drug_safety module. All four files
(`contraindications.yaml`, `disease_contraindications.yaml`,
`demographic_gates.yaml` here, plus `modules/drug_safety/reference_data/drug_substitution.yaml`)
are consumed via
`PyYAML.safe_load` on first use (cached via `functools.lru_cache`).

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
    lhs: <class expression>
    rhs: <class expression>
    severity: allowed | minor | moderate | major | contraindicated
    rationale_en: "<one-sentence clinical justification>"
    rationale_ja: "<Japanese translation>"
    substitution_hint: <optional indication tag; null if no substitute>
    source: "<citation: guideline / DDI database / textbook>"
```

Matching:
- **Order-independent**: `check_pair(A, B) == check_pair(B, A)`.
- **Multi-rule hits**: highest-severity rule wins.

`substitution_hint` names an indication tag that `suggest_alternative`
uses as a prior when picking a replacement drug from
`../../../modules/drug_safety/reference_data/drug_substitution.yaml` or from the
disease YAML `alternative_*` blocks.

Severity → default action:
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
      icd_prefix: [<ICD-10 prefixes>]      # required
      stage_in: [<stage strings>]          # optional (Issue #1769); entry must carry a matching stage
    severity: allowed | minor | moderate | major | contraindicated
    substitution_hint: <optional indication tag>
    rationale_en: "..."
    rationale_ja: "..."
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
    min_age: <int>                 # optional — patient must be >= this
    max_age: <int>                 # optional — patient must be <= this
    sex: male | female             # optional
    exception_indications: [<ICD-10 prefixes>]   # optional bypass
    severity: contraindicated | major
    rationale_en: "..."
    rationale_ja: "..."
```

When several rules fire, the highest-severity verdict wins (ties: first
rule).

## `../../../modules/drug_safety/reference_data/drug_substitution.yaml`

Generic indication → alternative drug pool. Consulted after
disease-YAML `alternative_*` blocks (via `_indication_tag`) and before
returning `None`.

```yaml
indications:
  <indication_tag>:
    description: "<one-line explanation>"
    alternatives:
      - drug_id: <id in clinosim/codes/data/drugs.yaml>   # display (en + ja) resolved via the catalog
        # legacy alternative to drug_id: drug: "<EN name>" (Japanese name from the drug catalog)
        default_dose: "<neutral dose string>"
        default_route: "<PO | IV | SC | INH>"
        default_frequency: "<daily | bid | tid | qid | prn | q6h_prn>"
```

`suggest_alternative` iterates the `alternatives` list in order and
re-checks each candidate against the caller's active meds via
`check_candidate_against_active` (pairwise `check_pair`). The first conflict-free entry wins.

## Adding a new rule

1. Give the drugs the rule targets their classes in `codes/data/drugs.yaml`.
2. Add the rule to `contraindications.yaml`, citing the source
   guideline. Set `substitution_hint` when a natural indication tag
   exists.
3. If the substitution_hint is new, add it to
   `modules/drug_safety/reference_data/drug_substitution.yaml` (or add an
   `_indication_tag` marker to a disease YAML `alternative_*` block
   if one exists for the disease scope).
4. Add a unit test asserting `check_pair(drug_a, drug_b).severity ==
   <expected>`.
5. Cohort-verify: run `verify_medical_stats.py` on a p=1000 sim and
   confirm `contraindicated_pair_count` stays at 0.
