# Quick start

## Build a shipped dataset preset

```bash
clinosim dataset list                                    # enumerate presets
# jp-100      JP cohort, 100 patients, 2026-01-01 to 2026-03-31 (3 months)
# jp-1000     JP cohort, 1000 patients, 2026-01-01 to 2026-06-30 (6 months)
# us-100      US cohort, 100 patients, 2026-01-01 to 2026-03-31 (3 months)
# us-1000     US cohort, 1000 patients, 2026-01-01 to 2026-06-30 (6 months)

clinosim dataset build jp-100 --output ./jp-100          # ~30 s
```

Output layout:

```
jp-100/
├── cif/                         # canonical intermediate format
└── fhir_r4/
    ├── Patient.ndjson
    ├── Encounter.ndjson
    ├── Condition.ndjson
    ├── Observation.ndjson
    ├── ...
    └── manifest.json            # FHIR Bulk manifest
```

More detail: [Datasets](../reference/datasets.md).

## Roll your own cohort

```bash
# JP, 500 patients, 3 months
clinosim simulate \
    --country JP --population 500 --seed 42 \
    --start 2026-01-01 --end 2026-03-31 \
    --output ./my-cohort --format fhir

# US, 1000 patients, 12 months
clinosim simulate \
    --country US --population 1000 --seed 42 \
    --start 2025-07-01 --end 2026-06-30 \
    --output ./my-us-cohort --format fhir
```

Deterministic — same seed + same params = byte-identical output. Verify
at any time with:

```bash
bash scripts/reproduce.sh
```

See [Reproducibility](../development/reproducibility.md) for the
underlying guarantee.

## Score a cohort

```bash
clinosim eval -d ./jp-100                                # Markdown to stdout
clinosim eval -d ./jp-100 --json report.json --md report.md
```

Full reference: [Evaluation](../eval.md).

## Next steps

- **Understand the model** — [Concepts / Data generation walkthrough](../design-guides/data-generation-walkthrough.md)
- **Extend a disease YAML** — [Adding a module](../CONTRIBUTING-modules.md)
- **Verify reproducibility on your machine** — [Reproducibility](../development/reproducibility.md)
