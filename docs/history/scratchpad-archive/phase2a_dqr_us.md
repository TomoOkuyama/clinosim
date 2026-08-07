# Phase 2a (D-dimer + causes_vte + J5) — DQR (US)

- bundle root: `scratchpad/phase2a_dqr_us`
- country: US

## Structural

- D-dimer Observations: **945**, with refRange: **945** (100.0%)  (PASS)
- D-dimer display==code or empty: **0**  (PASS)
  - `48065-7` → `D-dimer`

## Clinical

- PE (I26) admit-day D-dimer p50 = **4.60** ug/mL  (target >= 4.0; PASS)  [n=24]
- DVT (I80) admit-day D-dimer p50 = **4.70** ug/mL  (target >= 4.0; PASS)  [n=22]
- Cerebral infarction (I63) admit-day D-dimer p50 = **4.45** ug/mL  (target >= 4.0; PASS)  [n=119]
- Sepsis (A41) — should be non-specific admit-day D-dimer p50 = **0.84** ug/mL  (target < 2.0; PASS)  [n=50]
- Whole-cohort D-dimer: p10=**0.48** p50=**0.60** p90=**4.47** ug/mL  (in [0.15, 20] clamp: PASS)  [n=945]
- Troponin distribution: n=**4945**; >5 ng/mL = **2531**; >30 ng/mL = **2499** (J5 fix lets ED-route MI reach these tiers)

## JP Language

- US output Japanese leak in D-dimer fields: **0**  (PASS)  [scanned 945 resources]