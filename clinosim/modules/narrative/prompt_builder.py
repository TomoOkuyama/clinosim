"""Build prompts for narrative generation from extracted CIF data.

Each build function takes extracted data dict and returns (system_prompt, user_prompt).
All prompts include concise instructions to optimize token usage.
"""

from __future__ import annotations


def build_prompt(
    narrative_type: str,
    extracted_data: dict,
    language: str,
) -> tuple[str, str]:
    """Build prompt for narrative generation.

    Args:
        narrative_type: Type of narrative ("admission_hp", "discharge_summary", etc.)
        extracted_data: Dict of CIF data extracted for this narrative
        language: Language code ("en" or "ja")

    Returns:
        (system_prompt, user_prompt) tuple

    Raises:
        ValueError: If narrative_type is not recognized
    """
    builders = {
        "admission_hp": build_admission_hp_prompt,
        "discharge_summary": build_discharge_summary_prompt,
        "operative_note": build_operative_note_prompt,
        "procedure_note": build_procedure_note_prompt,
        "death_note": build_death_note_prompt,
    }

    builder = builders.get(narrative_type)
    if not builder:
        raise ValueError(f"Unknown narrative type: {narrative_type}")

    return builder(extracted_data, language)


def build_admission_hp_prompt(data: dict, language: str) -> tuple[str, str]:
    """Build Admission H&P prompt from extracted data."""
    system = (
        "You are a physician writing an admission History & Physical. "
        "Write in English. Use standard medical terminology."
    )

    patient = data["patient"]
    encounter = data["encounter"]
    vitals = data.get("admission_vitals")
    labs = data.get("admission_labs", [])

    parts = [
        f"Patient: {patient.age}yo {patient.sex}",
        f"Chief Complaint: {encounter.chief_complaint}",
        f"Admission Diagnosis: {data['admission_diagnosis']}",
        "",
    ]

    # Add admission vitals (REAL from CIF)
    if vitals:
        parts.append("Admission Vitals:")
        if vitals.temperature_celsius:
            parts.append(f"  - Temp: {vitals.temperature_celsius}°C")
        if vitals.heart_rate:
            parts.append(f"  - HR: {vitals.heart_rate} bpm")
        if vitals.systolic_bp and vitals.diastolic_bp:
            parts.append(f"  - BP: {vitals.systolic_bp}/{vitals.diastolic_bp} mmHg")
        if vitals.respiratory_rate:
            parts.append(f"  - RR: {vitals.respiratory_rate} /min")
        if vitals.spo2:
            parts.append(f"  - SpO2: {vitals.spo2}%")
        parts.append("")

    # Add admission labs (REAL from CIF)
    if labs:
        parts.append("Admission Labs:")
        for lab in labs[:5]:  # First 5 labs
            flag = f" ({lab.flag})" if lab.flag else ""
            parts.append(f"  - {lab.lab_name}: {lab.value} {lab.unit or ''}{flag}")
        parts.append("")

    # Concise instruction (optimized for token usage)
    concise_instr = {
        "ja": "簡潔に記載してください（500-800文字程度）。",
        "en": "Keep it concise and brief (500-800 characters).",
    }.get(language, "Keep it concise.")

    parts.append(f"Write a concise admission H&P. {concise_instr}")

    return system, "\n".join(parts)


def build_discharge_summary_prompt(data: dict, language: str) -> tuple[str, str]:
    """Build Discharge Summary prompt from extracted data."""
    system = (
        "You are a physician writing a discharge summary. "
        "Be comprehensive but concise. Write in English. Use standard medical terminology."
    )

    patient = data["patient"]
    encounter = data["encounter"]

    parts = [
        f"Patient: {patient.age}yo {patient.sex}",
        f"Admission Date: {encounter.admission_datetime.strftime('%Y-%m-%d')}",
        f"Discharge Date: {encounter.discharge_datetime.strftime('%Y-%m-%d')}",
        f"Length of Stay: {data['los_days']} days",
        "",
        f"Chief Complaint: {encounter.chief_complaint}",
        f"Admission Diagnosis: {data['admission_diagnosis']}",
        f"Discharge Diagnosis: {data['discharge_diagnosis']}",
        "",
    ]

    # Admission vitals
    if data.get("admission_vitals"):
        v = data["admission_vitals"]
        parts.append("Admission Vitals:")
        if v.temperature_celsius:
            parts.append(f"  - Temp: {v.temperature_celsius}°C")
        if v.heart_rate:
            parts.append(f"  - HR: {v.heart_rate} bpm")
        if v.spo2:
            parts.append(f"  - SpO2: {v.spo2}%")
        parts.append("")

    # Admission labs
    if data.get("admission_labs"):
        parts.append("Admission Labs:")
        for lab in data["admission_labs"][:3]:
            parts.append(f"  - {lab.lab_name}: {lab.value} {lab.unit or ''}")
        parts.append("")

    # Discharge vitals
    if data.get("discharge_vitals"):
        parts.append("Discharge Vitals: Stable")
        parts.append("")

    # Discharge medications
    if data.get("discharge_medications"):
        parts.append("Discharge Medications:")
        for med in data["discharge_medications"]:
            parts.append(f"  - {med}")
        parts.append("")

    # Concise instruction
    concise_instr = {
        "ja": "簡潔に記載してください（500-800文字程度）。",
        "en": "Keep it concise and brief (500-800 characters).",
    }.get(language, "Keep it concise.")

    parts.append(f"Write a concise discharge summary. {concise_instr}")

    return system, "\n".join(parts)


def build_operative_note_prompt(data: dict, language: str) -> tuple[str, str]:
    """Build Operative Note prompt from extracted data.

    TODO: Enhance with real CIF procedure data once extraction is implemented.
    """
    system = (
        "You are a surgeon writing an operative note. "
        "Write in English. Use standard medical terminology."
    )

    patient = data["patient"]

    # TODO: Use real CIF procedure data instead of placeholders
    user = f"""Patient: {patient.age}yo {patient.sex}

Procedure: {data.get('procedure', 'Surgical procedure')}
Preop Diagnosis: {data.get('preop_diagnosis', 'Pending CIF extraction')}
Postop Diagnosis: {data.get('postop_diagnosis', 'Pending CIF extraction')}
Anesthesia: {data.get('anesthesia_type', 'General anesthesia')}
Duration: {data.get('duration_minutes', 120)} minutes
EBL: {data.get('ebl_ml', 0)} mL
Findings: {data.get('findings', 'Pending CIF extraction')}
Complications: {', '.join(data.get('complications', [])) or 'None'}

Write a concise operative note."""

    # Add concise instruction
    concise_instr = {
        "ja": "簡潔に記載してください（500-800文字程度）。",
        "en": "Keep it concise and brief (500-800 characters).",
    }.get(language, "Keep it concise.")

    user += f" {concise_instr}"

    return system, user


def build_procedure_note_prompt(data: dict, language: str) -> tuple[str, str]:
    """Build Procedure Note prompt from extracted data.

    TODO: Enhance with real CIF procedure data once extraction is implemented.
    """
    system = (
        "You are a physician writing a procedure note. "
        "Write in English. Use standard medical terminology."
    )

    patient = data["patient"]

    # TODO: Use real CIF procedure data
    user = f"""Patient: {patient.age}yo {patient.sex}

Procedure: {data.get('procedure', 'Bedside procedure')}
Indication: {data.get('indication', 'Pending CIF extraction')}
Technique: {data.get('technique', 'Standard technique')}
Complications: {', '.join(data.get('complications', [])) or 'None'}

Write a concise procedure note."""

    # Add concise instruction
    concise_instr = {
        "ja": "簡潔に記載してください（500-800文字程度）。",
        "en": "Keep it concise and brief (500-800 characters).",
    }.get(language, "Keep it concise.")

    user += f" {concise_instr}"

    return system, user


def build_death_note_prompt(data: dict, language: str) -> tuple[str, str]:
    """Build Death Note prompt from extracted data."""
    system = (
        "You are a physician writing a death note. "
        "Be respectful and concise. Write in English. Use standard medical terminology."
    )

    patient = data["patient"]
    encounter = data["encounter"]

    user = f"""Patient: {patient.age}yo {patient.sex}

Time of Death: {encounter.discharge_datetime.strftime('%Y-%m-%d %H:%M')}
Cause of Death: {data['cause_of_death']}

Hospital Course: {data.get('hospital_course_summary', 'Patient was admitted and received intensive treatment but condition deteriorated.')}

Write a concise death note."""

    # Add concise instruction
    concise_instr = {
        "ja": "簡潔に記載してください（500-800文字程度）。",
        "en": "Keep it concise and brief (500-800 characters).",
    }.get(language, "Keep it concise.")

    user += f" {concise_instr}"

    return system, user
