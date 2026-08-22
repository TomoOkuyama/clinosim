<!-- Extracted from `README.md` (Issue #568 PR A2). Update the pointer in README when this file's heading changes. -->

# Datasets

Four named dataset presets live under
[`datasets/`](datasets/) — small (US/JP × 100) for smoke tests and
demos, medium (US/JP × 1000) for ML development. All at seed 42 and
reproducibly buildable from the CLI:

```bash
clinosim dataset list                                    # enumerate presets
clinosim dataset build jp-100 --output ./jp-100          # build one preset
```

| Preset | Country | Patients | Period | Approx. size |
|---|---|---:|---:|---:|
| [`us-100`](datasets/us-100/)   | US | 100  | 3 months | ~2 MB   |
| [`us-1000`](datasets/us-1000/) | US | 1000 | 6 months | ~30 MB  |
| [`jp-100`](datasets/jp-100/)   | JP | 100  | 3 months | ~2 MB   |
| [`jp-1000`](datasets/jp-1000/) | JP | 1000 | 6 months | ~30 MB  |

Each preset ships with a dataset card in HuggingFace format
(`datasets/<name>/README.md`) so it can be pushed to the HF Hub with no
metadata rework. The Zenodo integration (`.zenodo.json` at repo root)
mints a DOI on every tagged release, so cite the DOI for the exact
clinosim version you built the data with.

Starting with the **next release cycle**, the release workflow builds
all four presets and attaches them as GitHub Release assets. The
current v0.3.0 release ships the infrastructure only — use
`clinosim dataset build` to reproduce locally.

To load a dataset into a FHIR server (HAPI FHIR, etc.), see
[`../fhir-server-ingestion.md`](../fhir-server-ingestion.md).

---
