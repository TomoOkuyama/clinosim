"""Chronic-medication-driven monitoring pipeline (Issue #757 META).

Reads each patient's `current_medications` and injects per-medication
standard-of-care monitoring labs (e.g. Warfarin → PT-INR) into the
existing encounters. See `README.md` for the pipeline overview and
`reference_data/medication_monitoring.yaml` for the drug → labs mapping.
"""

from __future__ import annotations
