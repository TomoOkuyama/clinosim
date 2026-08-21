# Comparing clinosim and Synthea with `clinosim eval`

[Synthea](https://synthetichealth.github.io/synthea/) (MITRE's state-
transition synthetic health record generator) and clinosim tackle the
same problem from different angles. This page starts with the design
differences ([Feature comparison](#feature-comparison), [When to use
which](#when-to-use-which)) and then shows how to score both tools on
the **same** evaluation axes so you can compare them side by side
quantitatively. clinosim ships an adapter that fans Synthea's
per-patient Bundle output into the per-`ResourceType` NDJSON layout
`clinosim eval` expects.

!!! note "Synthea is an optional dependency"
    Nothing in clinosim imports or depends on Synthea at runtime. Java
    (11+) is only needed while you generate a Synthea cohort. Once the
    output exists on disk, everything below is pure Python.

## Feature comparison

| Dimension | clinosim | Synthea |
|---|---|---|
| Modeling approach | Physiology-driven forward simulation (14-var hidden state per patient) | State-transition modules per condition |
| Coherence between labs / vitals | Guaranteed by shared physiological state | Independent per module |
| Native FHIR R4 output | Bulk Data Access NDJSON, one file per ResourceType | FHIR R4 JSON per patient |
| JP Core profile compliance | 16 resource types | Not a design goal |
| Multi-locale (US + JP) | Both first-class; JP names, addresses, insurance, JLAC10, MHLW YJ | US-first; internationalization via community modules |
| Determinism guarantee | Byte-identical output within a MINOR release for the same seed | Deterministic per-run seed |
| Extension model | YAML-driven (edit a file, no code) | Java module (`.json` state machines + code) |
| Runtime | Python 3.11+ | Java 11+ |
| License | MIT | Apache 2.0 |

## When to use which

- **clinosim** — you need clinically coherent labs / vitals, JP output, or want to iterate on disease definitions without touching Java code.
- **Synthea** — you need a broad US population with well-established disease modules and a mature downstream tooling ecosystem.

## 1 — Generate a Synthea cohort

Synthea is Java-based. Two easy ways to run it:

### Docker

```bash
mkdir -p ./synthea-out
docker run --rm \
    -v "$(pwd)/synthea-out:/output" \
    docker.io/mitre/synthea:latest \
    -p 100 \
    --exporter.fhir.export=true \
    --exporter.fhir.transaction_bundle=true \
    --exporter.baseDirectory=/output \
    California San_Francisco
```

The FHIR R4 output lands in `./synthea-out/fhir/` — one JSON file per
patient (a top-level FHIR Bundle whose `entry[].resource` list holds
Patient / Encounter / Observation / ...).

### Java direct

If you prefer the plain `.jar` route:

```bash
git clone https://github.com/synthetichealth/synthea.git
cd synthea
./run_synthea -p 100 \
    --exporter.fhir.export=true \
    California San_Francisco
# → output/fhir/<uuid>.json
```

Refer to the [Synthea wiki](https://github.com/synthetichealth/synthea/wiki)
for population size / state / config options.

## 2 — Score the Synthea cohort with `clinosim eval`

Point `clinosim eval` at Synthea's `fhir/` output — the layout is
auto-detected and the Bundle files are normalized into
`fhir_r4/<ResourceType>.ndjson` alongside it:

```bash
clinosim eval -d ./synthea-out/fhir
# clinosim eval: detected Synthea layout — normalizing into ./synthea-out/synthea-normalized
# clinosim eval: wrote 12345 resources across 18 ResourceType(s)
# ...
# Overall score: 82.4 / 100 (WARN)
```

The normalization is deterministic (same Bundles ⇒ same NDJSON bytes);
subsequent `eval` runs against the same input reuse the on-disk
`synthea-normalized/` directory unless you `rm -rf` it.

Force the target directory with `--synthea-normalize`:

```bash
clinosim eval -d ./synthea-out/fhir \
    --synthea-normalize /tmp/synthea-flat \
    --json synthea-eval.json \
    --md synthea-eval.md
```

## 3 — Score the equivalent clinosim cohort

Generate a comparable clinosim cohort — the `us-100` preset ships with
the same size / country / duration ballpark:

```bash
clinosim dataset build us-100 --output ./clinosim-out
clinosim eval -d ./clinosim-out \
    --json clinosim-eval.json \
    --md clinosim-eval.md
```

## 4 — Compare axis by axis

Diff the two JSON reports on the axes you care about:

```bash
python3 - <<'PY'
import json
a = json.load(open("synthea-eval.json"))
b = json.load(open("clinosim-eval.json"))
print(f"{'axis':<15} {'synthea':>10} {'clinosim':>10}")
for ax_a, ax_b in zip(a["axes"], b["axes"]):
    assert ax_a["axis"] == ax_b["axis"]
    print(f"{ax_a['axis']:<15} {ax_a['score']:>10.1f} {ax_b['score']:>10.1f}")
print(f"{'overall':<15} {a['overall_score']:>10.1f} {b['overall_score']:>10.1f}")
PY
```

Example output (a real comparison will differ):

```
axis            synthea    clinosim
structural         98.5      100.0
clinical           74.2       77.8
locale             85.0      100.0
overall            85.9       92.6
```

The scoring formula is documented at
[Evaluation](eval.md#scoring); the per-check pass criteria at
[Evaluation rules](eval-rules.md).

## What the two tools legitimately score differently

- **Structural.** Both tools emit valid FHIR R4, so scores here should
  be close. Any structural gap tends to be resource-cardinality: e.g.
  Synthea doesn't emit `CareTeam` for every Encounter, clinosim does
  after session 46 P0.
- **Clinical.** clinosim's physiology model was tuned by the
  `condition_lab_coherence` pairings in [eval-rules.md](eval-rules.md),
  so a clinosim cohort should score high there almost by construction.
  Synthea's state-transition modules were tuned for prevalence and
  progression, which is a different quality axis; the coherence checks
  will surface pairings where Synthea's per-condition lab modules and
  the eval bands don't line up. Neither result is inherently "wrong" —
  it's what you're measuring.
- **Locale.** clinosim's JP checks (`japanese_displays_on_condition`,
  `jlac10_or_loinc_on_lab`, `yj_code_on_medications`,
  `jp_core_profile_declared`) will fail on Synthea output because
  Synthea is US-first — the eval tool is calling out that Synthea
  wasn't built to hit those thresholds, not that Synthea is broken.
  Use `--country US` to restrict the locale axis to the US checks
  when scoring Synthea.

## Adding a rule that's fair to both

If you plan to publish a comparison, [eval-rules.md](eval-rules.md#adding-a-rule)
is the single edit point for the check set. Any new rule you land there
will score both tools consistently on the next eval run.

## See also

- [Evaluation](eval.md) — CLI + scoring reference.
- [Evaluation rules](eval-rules.md) — per-check pass criteria + literature.
- [Datasets](reference/datasets.md) — clinosim preset cohorts.
- [Reproducibility](development/reproducibility.md) — clinosim's byte-identical
  determinism contract.
- [Synthea documentation](https://github.com/synthetichealth/synthea/wiki).
