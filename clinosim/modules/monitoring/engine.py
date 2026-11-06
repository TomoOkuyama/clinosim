"""Chronic-medication-driven monitoring pipeline (Issue #757) — engine.

Provides :func:`monitoring_labs_for_patient` which walks
``patient.current_medications`` and returns the standard-of-care
monitoring labs the patient should receive at each chronic follow-up
visit. The list is filtered per-visit through the mapping's
``per_visit_probability`` field so labs whose real cadence is longer
than the patient's typical visit interval (HbA1c q3-6mo on a q2mo INR
schedule) do not fire every time.

## Design

- **Data-driven**: mapping lives in ``reference_data/medication_monitoring.yaml``
  (one table for both monitoring paths, Issue #2786)
  so adding a new (medication, lab) pair requires only a YAML edit,
  never a code change.
- **Post-hoc composition**: the returned labs are merged INTO the
  visit's ``visit_labs`` list by the caller; the existing lab emit
  loop then treats them identically to any other visit lab, including
  the ``BASELINE_LAB_NORMALS`` / ``derive_lab_values`` gate that
  silent-drops unknown analytes (rule that #957 slice 1 also
  respected).
- **Draw-free**: the caller (``simulator/phases/_healthcare_calendar.py``)
  passes a stable visit key; the ``per_visit_probability`` gate is a hash
  of the key and the mapping (``determinism.sha_bernoulli``), so it consumes
  no random stream and adding a mapping shifts no other draw (Issue #2786).

## Scope of this path

- Chronic follow-up visits only. Monitoring labs on other encounters
  (including inpatient / ED records) come from the separate POST_RECORDS
  enricher (``enricher.py``, ``reference_data/medication_monitoring.yaml``).
- Cadence here is a probability approximation of visit-cadence *
  lab-cadence; there is no last-draw-date tracking on this path (the
  enricher path tracks ``interval_months`` per analyte).
- The mapping covers warfarin, levothyroxine, metformin, insulin,
  digoxin, statins, ACE-I/ARB/diuretics, lithium, tacrolimus and
  ciclosporin; see the yaml for the labs of each entry.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from clinosim.codes.drugs import medication_matches
from clinosim.determinism import sha_bernoulli

_HERE = Path(__file__).resolve().parent
_REF_DIR = _HERE / "reference_data"


@lru_cache(maxsize=1)
def load_medication_lab_mapping() -> dict[str, dict[str, Any]]:
    """The drug → monitoring-lab table of the chronic follow-up path, read from
    the one monitoring table, ``medication_monitoring.yaml``, that the
    POST_RECORDS enricher also reads (Issue #2786). Each entry's
    ``per_visit_probability`` gates the follow-up visit; its labs are the
    entry's monitoring labs."""
    from clinosim.modules.monitoring.mapping import load_medication_monitoring

    return {
        key: {
            "drugs": list(entry.get("drugs") or []),
            "classes": list(entry.get("classes") or []),
            "labs": [str(m["lab"]) for m in entry["monitoring"]],
            "per_visit_probability": float(entry["per_visit_probability"]),
        }
        for key, entry in load_medication_monitoring().items()
    }


def monitoring_labs_for_patient(
    current_medications: list[Any],
    visit_key: str,
) -> list[str]:
    """Return the monitoring-lab list for a patient's ``current_medications``.

    Args:
        current_medications: iterable of ``HomeMedication``-like objects
            with ``drug_name`` / ``drug_name_ja`` string attributes. May
            also be ``dict`` entries (JSON-deserialized CIF).
        visit_key: stable key of the visit (patient and visit time). Each
            mapping's ``per_visit_probability`` gate is a hash of the key
            and the mapping, so it draws nothing from the visit's random
            stream and adding a mapping shifts no other draw (Issue #2786;
            determinism spec §4).

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
    for key, entry in mapping.items():
        # Catalog identity, not name substrings (Issue #2371).
        if not any(
            medication_matches(med, entry.get("drugs") or (), entry.get("classes") or ()) for med in current_medications
        ):
            continue
        prob = float(entry["per_visit_probability"])
        if not sha_bernoulli(f"monitoring:{visit_key}:{key}", prob):
            continue
        for lab in entry["labs"]:
            if lab not in seen:
                out.append(lab)
                seen.add(lab)
    return out
