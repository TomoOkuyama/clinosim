# `clinosim/modules/drug_safety/reference_data/`

YAML schemas for the drug_safety module. All three files are consumed
via `PyYAML.safe_load` at import time (cached via `functools.lru_cache`).

## `drug_classes.yaml`

Drug → class[] taxonomy. Adding a new drug is a pure YAML edit — no
code change required.

```yaml
mappings:
  <Canonical Drug Name>:
    aliases:      [<additional names, case-insensitive substring match — EN + JP + brand>]
    drug_ja:      "<JP display>"
    classes:      [<class tags, dot-notated: family.subfamily>]
```

Class taxonomy conventions:

- `anticoagulant.{vka, doac, heparin}`
- `antiplatelet.{cox_inhibitor, p2y12, gp2b3a}`
- `nsaid.{non_selective, cox2_selective}` (Aspirin is dual-class,
  belonging to both `antiplatelet.cox_inhibitor` and
  `nsaid.non_selective`)
- `ccb.{dhp, non_dhp}`
- `beta_blocker.{cardioselective, non_selective}`
- `acei` / `arb` / `acei_arb` (union tag on both)
- `potassium_supplement`, `electrolyte_supplement`
- `diuretic.{loop, thiazide, k_sparing}`
- `statin`, `cyp3a4_substrate`, `cyp3a4_inhibitor_strong`
- `xanthine_oxidase_inhibitor`, `thiopurine`, `immunosuppressant`
- `ssri`, `maoi`, `antidepressant`, `antiparkinsonian`
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
`../../../locale/shared/drug_substitution.yaml` or from the
disease YAML `alternative_*` blocks.

Severity → default action:
| severity          | default_action    | narrative surface           |
|-------------------|-------------------|-----------------------------|
| `allowed`         | `emit`            | —                           |
| `minor`           | `emit`            | —                           |
| `moderate`        | `emit_with_note`  | MR.note caution attached    |
| `major`           | `skip`            | substitute + skip log entry |
| `contraindicated` | `skip`            | substitute + skip log entry |

## `../../../locale/shared/drug_substitution.yaml`

Generic indication → alternative drug pool. Consulted after
disease-YAML `alternative_*` blocks (via `_indication_tag`) and before
returning `None`.

```yaml
indications:
  <indication_tag>:
    description: "<one-line explanation>"
    alternatives:
      - drug: "<generic drug name>"
        drug_ja: "<JP display>"
        default_dose: "<neutral dose string>"
        default_route: "<PO | IV | SC | INH>"
        default_frequency: "<daily | bid | tid | qid | prn | q6h_prn>"
```

`suggest_alternative` iterates the `alternatives` list in order and
re-checks each candidate against the caller's active meds via
`check_pair`. The first conflict-free entry wins.

## Adding a new rule

1. Add any missing drug to `drug_classes.yaml`.
2. Add the rule to `contraindications.yaml`, citing the source
   guideline. Set `substitution_hint` when a natural indication tag
   exists.
3. If the substitution_hint is new, add it to
   `locale/shared/drug_substitution.yaml` (or add an
   `_indication_tag` marker to a disease YAML `alternative_*` block
   if one exists for the disease scope).
4. Add a unit test asserting `check_pair(drug_a, drug_b).severity ==
   <expected>`.
5. Cohort-verify: run `verify_medical_stats.py` on a p=1000 sim and
   confirm `contraindicated_pair_count` stays at 0.
