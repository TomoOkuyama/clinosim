# Phase 2a (D-dimer + causes_vte + J5) — DQR (JP)

- bundle root: `scratchpad/phase2a_dqr_jp`
- country: JP

## Structural

- D-dimer Observations: **45**, with refRange: **45** (100.0%)  (PASS)
- D-dimer display==code or empty: **0**  (PASS)
  - `2B140` → `D-Dダイマー`

## Clinical

- PE (I26) admit-day D-dimer p50 = **4.69** ug/mL  (target >= 4.0; PASS)  [n=3]
- DVT (I80) admit-day D-dimer p50 = **4.91** ug/mL  (target >= 4.0; PASS)  [n=1]
- Cerebral infarction (I63) admit-day D-dimer p50 = **4.67** ug/mL  (target >= 4.0; PASS)  [n=11]
- Sepsis (A41) — should be non-specific admit-day D-dimer p50 = **0.90** ug/mL  (target < 2.0; PASS)  [n=9]
- Whole-cohort D-dimer: p10=**0.56** p50=**0.95** p90=**5.04** ug/mL  (in [0.15, 20] clamp: PASS)  [n=45]
- Troponin distribution: n=**156**; >5 ng/mL = **48**; >30 ng/mL = **43** (J5 fix lets ED-route MI reach these tiers)

## JP Language

- JP output Japanese coverage in D-dimer fields: **90** instances  (PASS)  [scanned 45 resources]
  - `2B140` ja=`D-Dダイマー`  (PASS)