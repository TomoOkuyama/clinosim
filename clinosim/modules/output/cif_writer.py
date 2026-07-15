"""CIF Writer — Stage 1: write structural data to JSON files.

v0.1-alpha: JSON format only. Single file per patient.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from datetime import date, datetime, timedelta
from typing import Any

from clinosim.types.output import CIFDataset


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
    separately to cif/narratives/<version>/documents/ (AD-65)."""
    structural_dir = os.path.join(output_dir, "structural", "patients")
    os.makedirs(structural_dir, exist_ok=True)

    metadata_dict = asdict(dataset.metadata)
    with open(os.path.join(output_dir, "metadata.json"), "w") as f:
        json.dump(metadata_dict, f, cls=_CIFEncoder, indent=2, ensure_ascii=False)

    if dataset.hospital_roster or dataset.hospital_config:
        roster_dict = [asdict(m) for m in dataset.hospital_roster] if dataset.hospital_roster else []
        with open(os.path.join(output_dir, "hospital.json"), "w") as f:
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

    for idx, patient_record in enumerate(dataset.patients):
        patient_id = patient_record.patient.patient_id
        enc_id = patient_record.encounters[0].encounter_id if patient_record.encounters else f"{patient_id}-{idx:04d}"
        record_dict = asdict(patient_record)
        # AD-65: strip narrative content from documents (Stage 2 writes separately)
        for doc in record_dict.get("documents", []) or []:
            doc["narrative"] = None
        filepath = os.path.join(structural_dir, f"{enc_id}.json")
        with open(filepath, "w") as f:
            json.dump(record_dict, f, cls=_CIFEncoder, indent=2, ensure_ascii=False)
