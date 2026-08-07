# Coag Panel PR — Data-Quality Review (US)

- bundle root: `scratchpad/coag_dqr_us`
- country: US

## Structural

- Coag DR (24373-3) count: **493**
- Coag DR result[] unresolved references: **0**  (PASS)
- New Coag-related Observations: **621**, with refRange: **621** (100.0%)  (PASS)
- Coag codings with display==code or empty: **0**  (PASS)
- Coag code → display samples:
    - `6301-6` → `PT-INR`
    - `14979-9` → `aPTT`
    - `3255-7` → `Fibrinogen`

## Clinical

- Sepsis (A41) admit-day Fibrinogen p50 = **501.0** mg/dL  (target 350-650 acute-phase band; PASS)  [n=56]  NB: DIC consumption appears in LOS-mid for the subset that develops DIC (~10-30% of sepsis), not on admit day.
- Sepsis (A41) admit-day APTT p75 = **31.1** s  (target ≥ 30 = above upper reference, mild trending; PASS)  [n=9]  NB: DIC-grade prolongation appears in LOS-mid for the DIC subset.
- Hepatic PT_INR: no admit-day samples in cohort
- PT = 12 × PT_INR consistency: no matched pairs (expected — no disease YAML orders {test:'PT'} individually)
- Whole-cohort Fibrinogen: p10=**358** p50=**481** p90=**546** mg/dL  (in [50, 800] clamp: PASS)  [n=112]  NB: cohort median ≠ healthy median (cohort is disease-weighted).

## JP Language

- US output Japanese leak in Coag fields: **0**  (PASS)  [scanned 1114 resources]