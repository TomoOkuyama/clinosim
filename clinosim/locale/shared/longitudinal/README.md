# Longitudinal attribute catalog

One yaml per clinical attribute. Each file carries the common frontmatter (`attribute_id`, `pattern`, `depends_on`, `clinical_scope`) plus the pattern-specific body. See the full design at `docs/superpowers/specs/2026-10-20-longitudinal-state-evolution-design.md` for schema details.

Phase 1 contents:

- `hba1c_trajectory.yaml` — AR(1) HbA1c latent for E11 / E10 adults

Later phases will add Markov stage transitions (CKD / CCS / NYHA / CDR / GOLD) and event-firing attributes (DM complication onset, treatment escalation, BMI drift).
