# Coag Panel PR — Data-Quality Review (JP)

- bundle root: `scratchpad/coag_dqr_jp`
- country: JP

## Structural

- Coag DR (24373-3) count: **4**
- Coag DR result[] unresolved references: **0**  (PASS)
- New Coag-related Observations: **1378**, with refRange: **1378** (100.0%)  (PASS)
- Coag codings with display==code or empty: **0**  (PASS)
- Coag code → display samples:
    - `2B030` → `プロトロンビン時間`
    - `2B100` → `フィブリノゲン`
    - `2B020` → `活性化部分トロンボプラスチン時間`

## Clinical

- Sepsis (A41) admit-day Fibrinogen p50 = **516.0** mg/dL  (target 350-650 acute-phase band; PASS)  [n=11]  NB: DIC consumption appears in LOS-mid for the subset that develops DIC (~10-30% of sepsis), not on admit day.
- Sepsis (A41) admit-day APTT p75 = **31.9** s  (target ≥ 30 = above upper reference, mild trending; PASS)  [n=1]  NB: DIC-grade prolongation appears in LOS-mid for the DIC subset.
- Hepatic PT_INR: no admit-day samples in cohort
- Whole-cohort Fibrinogen: p10=**391** p50=**512** p90=**574** mg/dL  (in [50, 800] clamp: PASS)  [n=18]  NB: cohort median ≠ healthy median (cohort is disease-weighted).

## JP Language

- JP output Japanese coverage in Coag fields: **2760** instances  (PASS)  [scanned 1382 resources]
  - `2B020` ja=`活性化部分トロンボプラスチン時間`  (PASS)
  - `2B030` ja=`プロトロンビン時間`  (PASS)
  - `2B100` ja=`フィブリノゲン`  (PASS)