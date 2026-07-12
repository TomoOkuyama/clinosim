# Country scaffold template (`_template`)

This directory is a **schema-only scaffold**, not a runnable country. Each
YAML file contains placeholder values (`__TODO_...__` or empty lists) and
schema-shape comments. Copy the folder to your `<xx>/` locale directory
and replace the placeholders with data from authoritative sources.

See [`docs/add-your-country.md`](../../../docs/add-your-country.md) for the
full walk-through.

## Files

| File | Required? | Purpose |
|---|---|---|
| `names.yaml` | ✓ | Given / family names + frequency weights |
| `addresses.yaml` | ✓ | Regions / postal codes |
| `demographics.yaml` | ✓ | Age / blood type / chronic-disease prevalence / disease incidence |
| `formatting.yaml` | ✓ | Date / time / number formatting |
| `code_mapping_diagnosis.yaml` | ✓ | Internal disease id → national diagnosis code |
| `code_mapping_lab.yaml` | ✓ | Internal lab name → national lab code |
| `code_mapping_drug.yaml` | ✓ | Internal drug name → national drug code |
| `code_mapping_procedure.yaml` | ✓ | Internal procedure name → national procedure code |
| `reference_range_lab.yaml` | ✓ | Sex / age lab reference ranges |

## Non-runnable warning

The scaffold intentionally does NOT declare itself as a valid country in
`_COUNTRY_DIR_MAP`. Running `clinosim simulate --country _template` will
fail. This prevents accidental "runs with placeholder data" errors.
