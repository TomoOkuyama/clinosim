"""Chronic-medication-driven monitoring pipeline (Issue #757) — engine.

Provides :func:`monitoring_labs_for_patient` which walks
``patient.current_medications`` and returns the standard-of-care
monitoring labs the patient should receive at each chronic follow-up
visit. The list is filtered per-visit through the mapping's
``per_visit_probability`` field so labs whose real cadence is longer
than the patient's typical visit interval (HbA1c q3-6mo on a q2mo INR
schedule) do not fire every time.

## Design

- **Data-driven**: mapping lives in ``reference_data/med_lab_mapping.yaml``
  so adding a new (medication, lab) pair requires only a YAML edit,
  never a code change (feedback_constants_live_in_external_config).
- **Post-hoc composition**: the returned labs are merged INTO the
  visit's ``visit_labs`` list by the caller; the existing lab emit
  loop then treats them identically to any other visit lab, including
  the ``BASELINE_LAB_NORMALS`` / ``derive_lab_values`` gate that
  silent-drops unknown analytes (rule that #957 slice 1 also
  respected).
- **Deterministic under a supplied rng**: the caller passes its
  ``ev_rng`` so the same seed yields the same lab set. Adding this
  hook DOES shift the master-rng stream (a real behavioural change,
  not a byte-drift bug) — the rule ``feedback_rng_shift_patient_cache_cascade``
  documents that such shifts are acceptable for a scoped clinical fix
  and require a cohort-level MINOR-version bump.

## Not in scope for this pass

- Inpatient / ED med-driven monitoring (needs a different integration
  point — see #757 for the sibling scope).
- Cadence tracking (last-INR-date driven scheduling). This pass uses a
  probability approximation of visit-cadence * lab-cadence; a true
  chronological state machine is deferred.
- Digoxin / lithium / immunosuppressant level monitoring — the mapping
  YAML is intentionally started small (warfarin / levothyroxine / DM);
  each addition needs its own baseline-normal + reference-range coverage.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import yaml

_HERE = Path(__file__).resolve().parent
_REF_DIR = _HERE / "reference_data"


@lru_cache(maxsize=1)
def load_medication_lab_mapping() -> dict[str, dict[str, Any]]:
    """Load ``med_lab_mapping.yaml`` (cached singleton).

    Fail-loud on missing / malformed structure so misconfigurations
    surface at import time rather than at emit time (silent-no-op
    defense; same pattern as ``imaging/engine.py::_validate_modalities``).
    """
    path = _REF_DIR / "med_lab_mapping.yaml"
    if not path.exists():
        raise FileNotFoundError(f"medication-lab mapping YAML missing: {path}")
    with path.open() as f:
        data = yaml.safe_load(f) or {}
    mapping = data.get("medication_lab_mapping")
    if not mapping or not isinstance(mapping, dict):
        raise ValueError(f"{path.name}: missing or empty 'medication_lab_mapping' key")
    for key, entry in mapping.items():
        if not isinstance(entry, dict):
            raise ValueError(f"{path.name}[{key}]: entry must be a dict")
        for field in ("matches", "labs", "per_visit_probability"):
            if field not in entry:
                raise ValueError(f"{path.name}[{key}]: missing required field {field!r}")
        if not isinstance(entry["matches"], list) or not entry["matches"]:
            raise ValueError(f"{path.name}[{key}].matches: non-empty list required")
        if not isinstance(entry["labs"], list) or not entry["labs"]:
            raise ValueError(f"{path.name}[{key}].labs: non-empty list required")
        prob = entry["per_visit_probability"]
        if not isinstance(prob, int | float) or not 0.0 <= float(prob) <= 1.0:
            raise ValueError(f"{path.name}[{key}].per_visit_probability: must be in [0.0, 1.0]")
    return mapping


def _drug_name_matches(drug_name: str, drug_name_ja: str, patterns: list[str]) -> bool:
    """Return True when either drug-name field contains any of the case-
    insensitive substring patterns."""
    haystack = f"{drug_name} {drug_name_ja}".lower()
    return any(pat.lower() in haystack for pat in patterns)


def monitoring_labs_for_patient(
    current_medications: list[Any],
    rng: np.random.Generator,
) -> list[str]:
    """Return the monitoring-lab list for a patient's ``current_medications``.

    Args:
        current_medications: iterable of ``HomeMedication``-like objects
            with ``drug_name`` / ``drug_name_ja`` string attributes. May
            also be ``dict`` entries (JSON-deserialized CIF).
        rng: visit-scoped rng consumed for each mapping's
            ``per_visit_probability`` gate. The caller should pass the
            visit's ``ev_rng`` so the same seed reproduces the same
            monitoring-lab set.

    Returns:
        List of canonical lab names in mapping-key order, deduplicated.
        Empty when the patient has no monitored medications or when
        every mapping's probability gate failed this visit.
    """
    if not current_medications:
        return []
    mapping = load_medication_lab_mapping()
    out: list[str] = []
    seen: set[str] = set()
    for entry in mapping.values():
        patterns = entry["matches"]
        matched = False
        for med in current_medications:
            if isinstance(med, dict):
                dn = str(med.get("drug_name", "") or "")
                dnj = str(med.get("drug_name_ja", "") or "")
            else:
                dn = str(getattr(med, "drug_name", "") or "")
                dnj = str(getattr(med, "drug_name_ja", "") or "")
            if _drug_name_matches(dn, dnj, patterns):
                matched = True
                break
        if not matched:
            continue
        prob = float(entry["per_visit_probability"])
        if prob < 1.0 and rng.random() >= prob:
            continue
        for lab in entry["labs"]:
            if lab not in seen:
                out.append(lab)
                seen.add(lab)
    return out
