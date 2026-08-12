"""Pediatric encounter emission module (Issue #760 META).

Adds age-band-driven pediatric encounters (well-child visits, immunization
visits, pediatric acute) to the population's yearly healthcare calendar.
See `README.md` for the pipeline overview and
`reference_data/pediatric_schedule.yaml` for the encounter-type registry.

This module ships in incremental passes per META #760:

  Pass 1 (this PR): foundation only — module scaffold, YAML loader with
    empty schema, integration point in `generate_healthcare_calendar`.
    Byte-diff neutral: with no encounter types registered, no events are
    emitted, cohort output is bit-identical to pre-module runs.
  Pass 2+: register concrete encounter types (well-child, immunization,
    pediatric acute, adolescent behavioural) via pure YAML edits.
"""

from __future__ import annotations
