# clinosim datasets

Preset synthetic EHR datasets. Each subdirectory is one **named preset**
— a small YAML spec (`spec.yaml`) + a dataset card (`README.md`) that
uniquely determines the output at a fixed clinosim version.

## Available presets

| Preset | Country | Patients | Period | Approx. size (FHIR NDJSON) |
|---|---|---|---:|---:|
| [`us-100`](us-100/)   | US | 100  | 3 months | ~2 MB   |
| [`us-1000`](us-1000/) | US | 1000 | 6 months | ~30 MB  |
| [`jp-100`](jp-100/)   | JP | 100  | 3 months | ~2 MB   |
| [`jp-1000`](jp-1000/) | JP | 1000 | 6 months | ~30 MB  |

All four are seeded at 42 and use `--format fhir` (HL7 FHIR R4 Bulk
Data Access NDJSON, one file per ResourceType).

## Building a dataset locally

Each preset builds with a single command:

```bash
clinosim dataset list                          # enumerate available presets
clinosim dataset build jp-100 --output ./jp-100-out
```

That's a thin wrapper over `clinosim generate` — the equivalent long
form is:

```bash
clinosim generate \
    --country JP --population 100 --seed 42 \
    --start 2026-01-01 --end 2026-03-31 \
    --output ./jp-100-out --format fhir
```

The output byte-for-byte matches the released build at the same
clinosim version. That's the SemVer determinism contract; the
`reproducibility` CI job enforces it on every push (see the top-level
[Reproducibility section](../README.md#reproducibility)).

## Downloading pre-built datasets

Starting with the next release cycle, tagged releases automatically
attach pre-built dataset tarballs to the GitHub Release page:

```bash
# v0.2.0 shipped WITHOUT dataset attachments (infrastructure landed
# post-release). From v0.3.0 onward:
gh release download v0.3.0 --pattern "clinosim-dataset-jp-100-*.tar.gz"
tar -xzf clinosim-dataset-jp-100-v0.3.0.tar.gz
```

Between releases, use `clinosim dataset build` locally — output is
guaranteed byte-identical.

## Ethics & disclaimers

Every dataset shipped here is **fully synthetic**. clinosim does not
ingest, reference, or reproduce any real patient data, PHI, or PII.
The output is **not intended for clinical use** and must not be relied
upon for any diagnostic, therapeutic, or care decision. See the
[project-level disclaimers](../README.md#clinosim) for details.

## Citation

If a dataset is used in research, cite the underlying clinosim release
via [`CITATION.cff`](../CITATION.cff) at the repository root. The
Zenodo integration (`.zenodo.json`) mints a DOI on every tagged
release, giving you a stable identifier per dataset build version.

## Adding a new preset

1. Create `datasets/<name>/spec.yaml` with `name`, `country`,
   `population`, `seed`, `start`, `end`.
2. Add a `datasets/<name>/README.md` dataset card (HuggingFace
   frontmatter + body).
3. Run `clinosim dataset build <name>` — must succeed.
4. Run `bash scripts/reproduce.sh` — must stay green.

That's it. No code changes needed in the CLI — it reads the specs at
runtime.
