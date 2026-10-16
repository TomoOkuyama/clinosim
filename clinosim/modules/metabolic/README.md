# `clinosim.modules.metabolic` — BMI-derived and metabolic-cluster chronic conditions

Deterministic chronic-condition enrichment for metabolic syndrome components. Axis 1 is **E66 obesity ICD derivation** from `PersonRecord.bmi`; axis 2 is **E88.81 metabolic syndrome** from the 4-way AND over BMI + HTN + Dyslipidemia + DM; axis 3 is **K76.0 NAFLD** from a BMI + DM-weighted SHA Bernoulli (RNG-neutral per-person assignment); axis 4 is **G47.30 OSA** from a BMI + sex-weighted SHA Bernoulli; axis 5 is **GLP-1 agonist pharmacotherapy** for the E66.9 / E66.01 cohort via new entries in `chronic_medications.yaml` (Semaglutide / Tirzepatide / Liraglutide, SC, exclusive-class). All five axes close out the META #1137 cluster 2 scope.

## Purpose

Fill a data-completeness gap identified in the session-102 cohort audit: `PersonRecord.bmi` was already set at generation and consumed by multiple acute-event risk multipliers, but the ICD-10 obesity classification derived from BMI (E66) was absent from `chronic_conditions` entirely (0% emission vs ~41% CDC NHANES 2017-20 US adult prevalence). The module splits BMI-driven condition derivation out of the shared `demographics.yaml:chronic_prevalence` sampler so a Bernoulli draw is never involved in a condition that is a deterministic function of a Layer-1 attribute, and it collects the four cluster-2 enrichers (plus the GLP-1 pharmacotherapy layer) in one place for a single contributor-facing seam.

Fields written: appends ICD-10 codes to `PersonRecord.chronic_conditions`. Does not touch `encounters`, labs, or `current_medications` directly — the medication layer (axis 5) is served by the shared `chronic_medications.yaml` pipeline through the activator.

## Scope

- **In scope**: E66 obesity ICD derivation (BMI → E66.3 / E66.9 / E66.01), E88.81 metabolic syndrome 4-way AND, K76.0 NAFLD BMI + DM Bernoulli, G47.30 OSA BMI + sex Bernoulli, GLP-1 pharmacotherapy yaml entries for E66.9 / E66.01.
- **Out of scope**: FHIR serialisation ([`output`](../output/README.md)); code-display lookups ([`codes`](../../codes/)); locale text ([`locale`](../../locale/README.md)); chronic-prevalence Bernoulli sampling at POP_GENERATION (`demographics.yaml`); BMI trajectory year-over-year drift (deferred); K76.0 → ALT/AST baseline tie-in (deferred, tracked as a follow-up); bariatric surgery referral encounter + weight-loss counseling procedure codes (deferred, tracked as a follow-up).

## Public API

```python
from clinosim.modules.metabolic import (
    e66_bmi_enricher,            # POST_POPULATION order=15; BMI → E66.*
    e88_81_syndrome_enricher,    # POST_POPULATION order=16; 4-way AND → E88.81
    k76_0_nafld_enricher,        # POST_POPULATION order=17; BMI + DM SHA → K76.0
    g47_30_osa_enricher,         # POST_POPULATION order=18; BMI × sex SHA → G47.30
)
```

The four enrichers are the module's only Python-facing public surface. Axis 5 ships as yaml entries (`locale/shared/chronic_medications.yaml` E66.9 / E66.01 blocks) and has no Python export. All four enrichers accept the standard `ctx` (with `.population.persons`) and mutate `PersonRecord.chronic_conditions` in place.

Internal derivation primitives (`_derive_e66_code`, `_derive_metabolic_syndrome`, `_nafld_probability`, `_draw_nafld`, `_derive_nafld_assignment`, `_bmi_tier`, `_osa_probability`, `_draw_osa`, `_derive_osa_assignment`) are leading-underscore and intended to stay testable but not stable — call sites outside `clinosim/modules/metabolic/` should go through the enrichers. The former `_has_code_with_prefix` module-local helper has been replaced by the shared `clinosim.codes.has_icd_prefix`.

## Determinism

- **Axes 1-2**: pure deterministic functions of BMI + chronic-condition set. Zero RNG consumption. Byte-identity preserved for cohorts whose BMI distribution never crosses an E66 threshold or whose chronic-condition set never satisfies the E88.81 4-way AND.
- **Axes 3-4**: SHA-256 per-person Bernoulli. Each enricher hashes `<module salt>|<person_id>` to a 64-bit quantile, compares against the BMI (+ DM / sex)-weighted probability. **RNG-neutral — the master simulation stream is never consumed**, so adding these enrichers preserves byte-identity for cohorts under their respective thresholds. Separate salts (`metabolic.nafld.v1` vs `metabolic.osa.v1`) make a given patient's NAFLD / OSA assignments statistically independent, not perfectly correlated.
- **Axis 5**: served by the chronic-medications activator pipeline, which uses the shared per-patient sub-RNG. Already governed by `ENRICHER_SEED_OFFSETS["chronic_medications"]` upstream; the metabolic module does not register its own sub-seed.

No entry in `ENRICHER_SEED_OFFSETS` is required for axes 1-4 (SHA-based or RNG-free).

## Dependencies

- `clinosim.types.population.PersonRecord` — reads `.bmi`, `.sex`, `.person_id`; mutates `.chronic_conditions`.
- `hashlib` (stdlib) — SHA-256 for the axis 3 / 4 Bernoulli draw.
- Downstream, axis 5 depends on `clinosim.modules.patient.activator` reading the yaml entries at patient activation.

No cross-module clinosim imports. Register side (`clinosim/simulator/enrichers.py`) imports the four enrichers.

## Constants and configuration

Thresholds live as module-level constants in `engine.py` rather than yaml so the deterministic-derivation invariant stays co-located with the derivation code:

- `_BMI_OVERWEIGHT_THRESHOLD = 25.0`, `_BMI_OBESITY_THRESHOLD = 30.0`, `_BMI_MORBID_THRESHOLD = 40.0` — WHO BMI tier bounds (also used by `_bmi_tier` across axes 1-4).
- `_SYNDROME_BMI_THRESHOLD = 30.0`, `_HTN_PREFIXES`, `_DYSLIPIDEMIA_PREFIXES`, `_DM_PREFIXES`, `_SYNDROME_CODE = "E88.81"` — axis 2 AND criteria.
- `_NAFLD_CODE = "K76.0"`, `_NAFLD_OBESE_PREVALENCE = 0.60`, `_NAFLD_MORBID_PREVALENCE = 0.85`, `_NAFLD_DM_UPLIFT = 1.15`, `_NAFLD_SALT = "metabolic.nafld.v1"` — axis 3 anchors (Younossi 2016 obese sub-cohort).
- `_OSA_CODE = "G47.30"`, `_OSA_PREVALENCE_MALE`, `_OSA_PREVALENCE_FEMALE`, `_OSA_SALT = "metabolic.osa.v1"` — axis 4 anchors (Peppard 2013 BMI tier × sex table).

Axis 5 constants live in `locale/shared/chronic_medications.yaml` under the `E66.9:` / `E66.01:` blocks (drug names, doses, routes, probabilities, `exclusive_classes: ["glp1"]`). A later refinement can externalise axis 2's AND criteria into `reference_data/metabolic_syndrome_criteria.yaml` if a 3-of-5 NCEP ATP III relaxation is ever added.

## Directory contents

```
clinosim/modules/metabolic/
├── __init__.py           # Public re-exports (4 enrichers)
├── engine.py             # Derivation primitives + 4 enricher wrappers
├── README.md             # (this file)
└── README.ja.md          # Japanese sibling
```

No sub-packages. No yaml data files (constants inline; axis-5 pharmacotherapy ships via the shared chronic_medications yaml). No audit plug-in.

## Enricher wiring

Registered in `clinosim.simulator.enrichers.register_builtin_enrichers`:

| Enricher | Stage | Order | Prereqs |
|---|---|---|---|
| `e66_bmi_enricher` | `POST_POPULATION` | 15 | BMI finalised at POP_GENERATION |
| `e88_81_syndrome_enricher` | `POST_POPULATION` | 16 | chronic_prevalence sampler (HTN/DM/Dyslipidemia) + E66 enricher |
| `k76_0_nafld_enricher` | `POST_POPULATION` | 17 | BMI + DM finalised |
| `g47_30_osa_enricher` | `POST_POPULATION` | 18 | BMI + sex finalised |

All four run between allergy / identity (order 10) and `natural_death` (order 20). All are always-on (no locale or config gate) — the thresholds themselves gate emission.

Axis 5 is served by the standard medication activator reading `chronic_medications.yaml`; no new enricher registration.

## Output surfaces (consumers)

- `PersonRecord.chronic_conditions` — appended ICD-10 codes flow into every downstream consumer that reads chronic conditions, including:
  - FHIR Condition serialisation ([`output/fhir_r4/documents/composition.py`](../output/fhir_r4/documents/composition.py))
  - Narrative generation ([`document/narrative/`](../document/narrative/))
  - Risk multiplier lookups in `population/aging.py`, `simulator/outpatient.py`
  - DR + consistency validators ([`validator/`](../validator/))
- `locale/shared/chronic_medications.yaml` E66.9 / E66.01 blocks (axis 5) are consumed by `modules/patient/activator.py` → `HomeMedication.drug_name` → downstream prescription paths.

## Testing

`tests/unit/modules/metabolic/`:

- `test_e66_bmi_enricher.py` — 5 derivation boundary tests + 5 enricher-behavior tests + 1 mixed-cohort smoke + 1 pre-existing-variant pass-through.
- `test_e88_81_syndrome_enricher.py` — 8 derivation AND-criteria tests + 5 enricher-behavior tests + 1 mixed-cohort smoke.
- `test_k76_0_nafld_enricher.py` — 4 probability anchor + DM-uplift + 4 SHA-draw + 2 derivation-wrapper + 4 enricher-behavior (incl. 500-person prevalence band + RNG-neutral cross-seed).
- `test_g47_30_osa_enricher.py` — 1 BMI-tier boundary + 4 prevalence anchor (M / F / 2:1 ratio / unknown-sex fallback) + 4 SHA-draw (incl. salt separation from K76.0) + 2 derivation-wrapper + 4 enricher-behavior (incl. sex-gradient visibility + RNG-neutral cross-seed).

Total: 55 tests. All run in < 1 s; no fixtures beyond local `_person` + `_Ctx` dataclasses.

End-to-end verification uses `scripts/engine-fingerprint.sh` on the US s42 + JP s17 p=500 cohort pair — the per-axis commit history records byte-identity-preserving TOTAL hashes before / after.

## Ownership

Maintained alongside the META #1137 cluster-2 scope. Primary audit touchpoint: the clinical anchors (Younossi 2016, Peppard 2013) in `engine.py`'s module docstring. Future axes should land as sibling axis files once the module exceeds ~600 LOC — the current single `engine.py` is review-friendly at ~430 LOC but will need a per-axis split (`e66.py`, `e88_81.py`, …) if cluster 2 grows further.

Follow-ups (both former tracking METAs — #1137 and #1633 — are now closed; these items are open future work with no dedicated META):

- **K76.0 NAFLD → ALT/AST baseline tie-in** — downstream PR will steer liver-enzyme emission toward elevated range for K76.0-chronic patients so the "lab-conditional" half of the issue scope is also satisfied.
- **Bariatric surgery referral encounter + weight-loss counseling procedure** — the GLP-1 pharmacotherapy half of axis 5 ships here; the surgery referral encounter and counseling procedure code emission need new encounter yaml entries rather than a chronic-med addition.
- **BMI trajectory** — current `PersonRecord.bmi` is static over the sim window. A `bmi_trajectory` (mirroring `glycemic_trajectory`) would let BMI drift year-over-year and reclassify a patient between E66 tiers mid-sim.

## See also

- `clinosim/modules/allergy/README.md` — POST_POPULATION enricher template reference.
- `.github/TEMPLATE_MODULE_README.md` — canonical 11-section skeleton.
- Issue #1137 (META: new modules — mental_health/ + metabolic/) — now closed.
- Issue #1126 (motivating issue for cluster 2 scope).
