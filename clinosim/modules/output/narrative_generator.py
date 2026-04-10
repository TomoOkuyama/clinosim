"""Stage 2: Narrative Generator — reads structural CIF, generates narrative layer.

Can be re-run with different LLMs without re-running simulation.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any

from clinosim.modules.llm_service.engine import (
    ClinicalEventData,
    LLMService,
    LLMTaskType,
    PatientSummary,
)


def generate_narratives(
    cif_dir: str,
    llm_service: LLMService,
    version_id: str | None = None,
    language: str = "ja",
) -> str:
    """Generate narrative layer for all patients in a structural CIF.

    Returns the version_id of the generated narratives.
    """
    structural_dir = os.path.join(cif_dir, "structural", "patients")
    if not os.path.exists(structural_dir):
        raise FileNotFoundError(f"CIF structural directory not found: {structural_dir}")

    # Create version directory
    if version_id is None:
        version_id = f"narrative_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    narrative_dir = os.path.join(cif_dir, "narratives", version_id, "patients")
    os.makedirs(narrative_dir, exist_ok=True)

    patient_count = 0

    for filename in sorted(os.listdir(structural_dir)):
        if not filename.endswith(".json"):
            continue

        with open(os.path.join(structural_dir, filename)) as f:
            record = json.load(f)

        narratives = _generate_patient_narratives(record, llm_service, language)

        with open(os.path.join(narrative_dir, filename), "w", encoding="utf-8") as f:
            json.dump(narratives, f, indent=2, ensure_ascii=False)

        patient_count += 1

    # Write manifest
    manifest = {
        "version_id": version_id,
        "llm_mode": llm_service.mode,
        "generation_timestamp": datetime.now().isoformat(),
        "patient_count": patient_count,
        "language": language,
        "cost_report": llm_service.cost_report(),
    }
    manifest_path = os.path.join(cif_dir, "narratives", version_id, "manifest.json")
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    # Set as current
    current_link = os.path.join(cif_dir, "narratives", "current_version.txt")
    with open(current_link, "w") as f:
        f.write(version_id)

    return version_id


def _generate_patient_narratives(
    record: dict,
    llm: LLMService,
    language: str,
) -> dict[str, Any]:
    """Generate all narrative texts for one patient."""
    patient = record.get("patient", {})
    patient_id = patient.get("patient_id", "")
    name = patient.get("name", {})

    # Extract clinical data from CIF record
    clinical_dx = record.get("clinical_diagnosis", {})
    condition = record.get("condition_event", {})
    encounters = record.get("encounters", [])
    chief = encounters[0].get("chief_complaint", "") if encounters else ""
    dx_name = clinical_dx.get("discharge_diagnosis_name") or clinical_dx.get("admission_diagnosis_name", "")
    gt_diseases = condition.get("ground_truth_diseases", [])

    ps = PatientSummary(
        age=patient.get("age", 0),
        sex=patient.get("sex", ""),
        country="JP" if language == "ja" else "US",
        chief_complaint=chief,
        relevant_conditions=[c.get("name", "") for c in patient.get("chronic_conditions", [])],
        current_diagnosis=dx_name or (gt_diseases[0] if gt_diseases else "Unknown"),
        diagnosis_confidence=0.85,
        hospital_day=0,
        department="internal_medicine",
    )

    notes: list[dict] = []

    for enc in record.get("encounters", []):
        enc_id = enc.get("encounter_id", "")
        admission = enc.get("admission_datetime", "")
        discharge = enc.get("discharge_datetime", "")

        # Calculate LOS
        los_days = 14
        if admission and discharge:
            from datetime import datetime as dt
            try:
                a = dt.fromisoformat(admission)
                d = dt.fromisoformat(discharge)
                los_days = (d - a).days
            except (ValueError, TypeError):
                pass

        # Admission H&P
        ps.hospital_day = 0
        hp = llm.generate(LLMTaskType.ADMISSION_HP, ClinicalEventData(
            patient_summary=ps,
            event_data={"chief_complaint": chief},
            language=language,
        ))
        notes.append({
            "encounter_id": enc_id,
            "note_type": "admission_hp",
            "hospital_day": 0,
            "text": hp.text,
            "source": hp.source,
        })

        # Progress notes for key days
        states = record.get("physiological_states", [])
        key_days = [1, 3, 7] + ([los_days - 1] if los_days > 7 else [])
        for day in key_days:
            if day >= len(states):
                break
            state = states[day]
            ps.hospital_day = day
            note = llm.generate(LLMTaskType.PROGRESS_NOTE, ClinicalEventData(
                patient_summary=ps,
                event_data={
                    "vitals": {"temperature": "37.2"},
                    "key_labs": {"CRP": f"{state.get('inflammation_level', 0) * 100:.0f}"},
                },
                language=language,
            ))
            notes.append({
                "encounter_id": enc_id,
                "note_type": "progress_note",
                "hospital_day": day,
                "text": note.text,
                "source": note.source,
            })

        # Discharge summary
        ps.hospital_day = los_days
        # Extract discharge medications from CIF
        rx = record.get("discharge_prescription") or {}
        rx_items = rx.get("items", [])
        rx_names = [item.get("drug_name", item.get("drug", "")) for item in rx_items if isinstance(item, dict)]

        ds = llm.generate(LLMTaskType.DISCHARGE_SUMMARY, ClinicalEventData(
            patient_summary=ps,
            event_data={
                "los_days": los_days,
                "final_diagnosis": dx_name,
                "discharge_medications": rx_names or ["None"],
            },
            language=language,
        ))
        notes.append({
            "encounter_id": enc_id,
            "note_type": "discharge_summary",
            "hospital_day": los_days,
            "text": ds.text,
            "source": ds.source,
        })

    return {
        "patient_id": patient_id,
        "patient_name": name.get("display_name", patient_id),
        "notes": notes,
    }
