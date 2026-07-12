# clinosim

**Clinically Realistic Hospital Data Simulator** — Generate FHIR R4 EHR
data from a virtual hospital.

!!! warning "Personal project disclaimer"
    This is an independent personal project and is **not** an official
    product of any company or organization.

!!! warning "Synthetic data only"
    All output is **fully synthetic**. clinosim does not ingest,
    reference, or reproduce any real patient data or PHI/PII. The output
    is **not intended for clinical use** and must not be relied upon for
    any diagnostic, therapeutic, or care decision.

---

## What is clinosim?

Most synthetic-EHR tools produce records by sampling from disease
distributions. **clinosim runs the disease.** Every patient carries a
hidden 13-variable physiological state, and every lab / vital /
medication is derived from that state.

Three concrete differentiators:

- **Clinical coherence by construction.** Not a post-hoc filter — the
  physiology model makes incoherent labs impossible.
- **JP + US natively.** JP Core profile compliance for 16 primary FHIR
  resource types, JLAC10 / MHLW YJ codes, JP names / addresses /
  insurance out of the box.
- **YAML-driven extension.** 32 inpatient diseases + 46 ED / outpatient
  conditions are all data files, not code.

---

## Get started in 30 seconds

```bash
pip install clinosim                                     # (PyPI upload pending)
# or: pip install "git+https://github.com/TomoOkuyama/clinosim.git@master"

clinosim dataset build jp-100 --output ./jp-100          # ~30 s
clinosim eval -d ./jp-100                                # score it
```

Full walk-through: [Installation](getting-started/installation.md) →
[Quick start](getting-started/quick-start.md).

---

## Where to go next

<div class="grid cards" markdown>

-   :material-book-open-outline: **Concepts**

    ---

    How the population → CIF → FHIR pipeline works end to end.

    [→ Data generation walkthrough](design-guides/data-generation-walkthrough.md)

-   :material-database-outline: **Datasets**

    ---

    Four named preset datasets (US/JP × 100/1000) + how to build your own.

    [→ Datasets reference](reference/datasets.md)

-   :material-chart-line: **Evaluation**

    ---

    Score any generated cohort on structural / clinical / locale axes.

    [→ `clinosim eval`](eval.md)

-   :material-code-braces: **Guides**

    ---

    How to add a module, extend a disease YAML, or wire a new FHIR
    builder.

    [→ Adding a module](CONTRIBUTING-modules.md)

</div>

---

## Comparing to Synthea

[Synthea](https://synthetichealth.github.io/synthea/) tackles synthetic
EHR from a state-transition angle; clinosim from a physiology-simulation
angle. Full side-by-side in the [README](https://github.com/TomoOkuyama/clinosim#how-clinosim-compares-to-synthea).

---

## License

MIT. See the [LICENSE](https://github.com/TomoOkuyama/clinosim/blob/master/LICENSE) at the repository root.
