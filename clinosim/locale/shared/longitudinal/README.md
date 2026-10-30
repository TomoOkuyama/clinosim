# Longitudinal attribute catalog

One yaml per clinical attribute. Each file carries the common frontmatter (`attribute_id`, `pattern`, `depends_on`, `clinical_scope`) plus the pattern-specific body. See the full design at `docs/superpowers/specs/2026-10-20-longitudinal-state-evolution-design.md` for schema details.

`clinosim/modules/longitudinal/loader.py` loads every `*.yaml` under this directory recursively (`rglob`). Current contents (64 files; patterns: 4 `ar1`, 19 `markov`, 41 `event`):

- `hba1c_trajectory.yaml` — AR(1) HbA1c latent for E11 / E10 adults
- `labs/` (1) — LDL trajectory
- `vitals/` (1) — SBP trajectory
- `anthropometry/` (1) — BMI drift
- `stage/` (19) — Markov stage transitions (CKD, COPD, heart failure, ischemic heart disease, atrial fibrillation, dementia, Parkinson, MS, liver fibrosis / alcoholic liver disease, stroke sequelae, cancer stages)
- `event/` (35) — event-firing attributes: chronic-disease onset (`*_onset.yaml`) and DM complication onset (nephropathy / neuropathy / retinopathy)
- `med/` (6) — treatment escalation (DM: insulin / SGLT2i; HTN: third / fourth agent; lipids: high-intensity statin / ezetimibe)
