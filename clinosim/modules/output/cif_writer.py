"""CIF Writer — Stage 1: write structural data to JSON files.

v0.1-alpha: JSON format only. Single file per patient.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict
from datetime import date, datetime, timedelta
from typing import Any

from clinosim.modules.population._pediatric_anthropometry import (
    pediatric_snapshot_profile as _peds_snapshot_profile,
)
from clinosim.modules.population._pediatric_anthropometry import (
    pediatric_upper_age as _peds_upper_age,
)
from clinosim.simulator import log as sim_log
from clinosim.types.output import CIFDataset


def _apply_baby_snapshot_anthropometry(
    patient_dict: dict[str, Any],
    snapshot_date: str | None,
    country: str,
    admission_datetime: datetime | None = None,
) -> None:
    """Mid-sim-born pediatric patients (``POP-NNNNN-BABY``) have a
    ``PatientProfile`` initialised at delivery with newborn
    anthropometry (``height_cm=50 w=3.2 bmi=12.8 age=0``). Nothing
    advances those stored scalars as sim time moves forward, so a baby
    born in sim year 1 and audited at sim year 5 still carries the
    newborn snapshot even though the per-encounter FHIR anthropometric
    emit already walks the growth chart by age-at-encounter. Patch the
    stored CIF profile to the growth-chart median at
    ``snapshot_date`` so direct consumers of the CIF JSON see a
    plausible age-matched profile.

    Issue #1759 — ``admission_datetime`` guard: when the record being
    written represents the DELIVERY encounter (admission within one
    day of DOB), the patch is suppressed and the hardcoded newborn
    scalars are preserved. Pre-fix this pass back-propagated the
    end-of-sim age / height / weight onto the delivery record,
    producing records like ``age=3, h=97.0, w=14.7`` on an encounter
    whose own admission_datetime landed in the DOB month.

    Scope: ``patient_id`` ending in ``"-BABY"`` only — these are the
    perinatal.py mid-sim-birth records whose stored anthropometry is
    unambiguously frozen at birth. Pre-sim pediatric persons (sampled
    at generation time with per-patient variability) are intentionally
    left alone in this PR: overwriting them with the growth-chart
    median would also discard their initial sampling noise and
    broaden the scope beyond the audit's CRITICAL finding.

    No-op when ``snapshot_date`` is missing, when the DOB is missing,
    when the baby is already at or past the pediatric upper age at
    snapshot time, when the growth-chart has no row for that age, or
    (Issue #1759) when ``admission_datetime`` is within one day of DOB.
    """
    pid = patient_dict.get("patient_id") or ""
    if not pid.endswith("-BABY"):
        return
    if not snapshot_date:
        return
    dob = patient_dict.get("date_of_birth")
    if not dob:
        return
    try:
        dob_d = date.fromisoformat(str(dob)[:10])
        snap_d = date.fromisoformat(str(snapshot_date)[:10])
    except ValueError:
        return
    # Issue #1759: delivery encounter guard. Preserve the newborn scalars
    # when the record's own admission landed within one day of DOB — the
    # catch-up is for LATER encounters of the same baby, not the one that
    # recorded the birth itself.
    if admission_datetime is not None:
        try:
            adm_d = (
                admission_datetime.date()
                if hasattr(admission_datetime, "date")
                else date.fromisoformat(str(admission_datetime)[:10])
            )
        except (ValueError, AttributeError):
            adm_d = None
        if adm_d is not None and adm_d >= dob_d and (adm_d - dob_d) <= timedelta(days=1):
            return
    if snap_d < dob_d:
        return
    age = snap_d.year - dob_d.year - ((snap_d.month, snap_d.day) < (dob_d.month, dob_d.day))
    patient_dict["age"] = age
    if age >= _peds_upper_age():
        return
    prof = _peds_snapshot_profile(country, patient_dict.get("sex", "M"), age)
    if prof is None:
        return
    patient_dict["height_cm"] = prof["height_cm"]
    patient_dict["weight_kg"] = prof["weight_kg"]
    patient_dict["bmi"] = prof["bmi"]


class _CIFEncoder(json.JSONEncoder):
    """JSON encoder that handles datetime, date, timedelta, and Enum objects."""

    def default(self, obj: Any) -> Any:
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, date):
            return obj.isoformat()
        if isinstance(obj, timedelta):
            return obj.total_seconds()
        if hasattr(obj, "value"):  # Enum
            return obj.value
        return super().default(obj)


def write_cif(dataset: CIFDataset, output_dir: str) -> None:
    """Write structural CIF to JSON files. Narrative content is stripped
    from documents[] — Stage 2 TemplateNarrativePass writes narrative
    separately to cif/narratives/<version>/documents/ (AD-65).

    Emits `sim_log` events (Issue #175):
      - ``cif_write_start`` / ``cif_write_end`` bracket the whole call,
        so a `tail -f` on ``simulator.log`` sees the boundary + ``elapsed_s``
        without waiting for the next print in the caller.
      - ``cif_written`` summary line carries ``patients``, ``bytes_out``,
        ``elapsed_s`` so profile tooling can bucket the write phase.
    """
    t0 = time.perf_counter()
    sim_log.info(
        "cif_writer",
        "cif_write_start",
        patients=len(dataset.patients),
        output_dir=output_dir,
    )
    structural_dir = os.path.join(output_dir, "structural", "patients")
    os.makedirs(structural_dir, exist_ok=True)

    metadata_dict = asdict(dataset.metadata)
    with open(os.path.join(output_dir, "metadata.json"), "w", encoding="utf-8") as f:
        json.dump(metadata_dict, f, cls=_CIFEncoder, indent=2, ensure_ascii=False)

    if dataset.hospital_roster or dataset.hospital_config:
        roster_dict = [asdict(m) for m in dataset.hospital_roster] if dataset.hospital_roster else []
        with open(os.path.join(output_dir, "hospital.json"), "w", encoding="utf-8") as f:
            json.dump(
                {
                    "staff": roster_dict,
                    "config": dataset.hospital_config or {},
                },
                f,
                cls=_CIFEncoder,
                indent=2,
                ensure_ascii=False,
            )

    bytes_out = 0
    for idx, patient_record in enumerate(dataset.patients):
        patient_id = patient_record.patient.patient_id
        enc_id = patient_record.encounters[0].encounter_id if patient_record.encounters else f"{patient_id}-{idx:04d}"
        record_dict = asdict(patient_record)
        # Issue #1759: pass the record's own first-encounter admission
        # datetime so ``_apply_baby_snapshot_anthropometry`` can
        # suppress the catch-up on the delivery encounter (admission
        # within one day of DOB).
        _first_adm = patient_record.encounters[0].admission_datetime if patient_record.encounters else None
        _apply_baby_snapshot_anthropometry(
            record_dict.get("patient") or {},
            dataset.metadata.snapshot_date,
            dataset.metadata.country,
            admission_datetime=_first_adm,
        )
        # AD-65: strip narrative content from documents (Stage 2 writes separately)
        for doc in record_dict.get("documents", []) or []:
            doc["narrative"] = None
        filepath = os.path.join(structural_dir, f"{enc_id}.json")
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(record_dict, f, cls=_CIFEncoder, indent=2, ensure_ascii=False)
        bytes_out += os.path.getsize(filepath)

    elapsed = time.perf_counter() - t0
    sim_log.info(
        "cif_writer",
        "cif_write_end",
        patients=len(dataset.patients),
        bytes_out=bytes_out,
        elapsed_s=round(elapsed, 3),
    )
