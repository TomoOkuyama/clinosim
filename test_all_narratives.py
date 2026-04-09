#!/usr/bin/env python3
"""
Generate all 5 narrative types from actual CIF data.

For each narrative type:
1. Find appropriate encounter in CIF
2. Extract relevant clinical data
3. Generate narrative with Bedrock
4. Check consistency
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).parent))

from clinosim.simulator.engine import run_beta, run_forced
from clinosim.types.config import SimulatorConfig, ForcedScenario
from clinosim.types.encounter import EncounterType
from clinosim.modules.llm_service.engine import LLMTaskType
from clinosim.modules.llm_service.providers import BedrockProvider
from clinosim.codes import lookup as code_lookup


def extract_admission_hp_data(cif_record):
    """Extract data for Admission H&P."""
    inpatient = None
    for enc in cif_record.encounters:
        if enc.encounter_type == EncounterType.INPATIENT:
            inpatient = enc
            break

    if not inpatient:
        return None

    # Admission vitals
    adm_vitals = None
    if cif_record.vital_signs:
        for vs in cif_record.vital_signs:
            if vs.timestamp >= inpatient.admission_datetime:
                adm_vitals = vs
                break

    # Admission labs (first 4 hours)
    adm_cutoff = inpatient.admission_datetime + timedelta(hours=4)
    adm_labs = [
        lab for lab in cif_record.lab_results
        if lab.result_datetime >= inpatient.admission_datetime
        and lab.result_datetime <= adm_cutoff
    ]

    # Diagnosis
    dx = code_lookup(
        cif_record.clinical_diagnosis.admission_diagnosis_system,
        cif_record.clinical_diagnosis.admission_diagnosis_code,
        "en"
    ) if cif_record.clinical_diagnosis.admission_diagnosis_code else "Unknown"

    # PMH from patient profile
    pmh = getattr(cif_record.patient, 'medical_history', [])

    return {
        "type": "Admission H&P",
        "patient": cif_record.patient,
        "encounter": inpatient,
        "admission_vitals": adm_vitals,
        "admission_labs": adm_labs,
        "diagnosis": dx,
        "pmh": pmh,
    }


def extract_discharge_summary_data(cif_record):
    """Extract data for Discharge Summary."""
    inpatient = None
    for enc in cif_record.encounters:
        if enc.encounter_type == EncounterType.INPATIENT and enc.discharge_datetime:
            inpatient = enc
            break

    if not inpatient:
        return None

    # Vitals
    adm_vitals = None
    disch_vitals = None
    if cif_record.vital_signs:
        for vs in cif_record.vital_signs:
            if vs.timestamp >= inpatient.admission_datetime and not adm_vitals:
                adm_vitals = vs
            if vs.timestamp <= inpatient.discharge_datetime:
                disch_vitals = vs

    # Labs
    adm_cutoff = inpatient.admission_datetime + timedelta(hours=4)
    adm_labs = [lab for lab in cif_record.lab_results
                if lab.result_datetime >= inpatient.admission_datetime
                and lab.result_datetime <= adm_cutoff]

    disch_cutoff = inpatient.discharge_datetime - timedelta(hours=24)
    disch_labs = [lab for lab in cif_record.lab_results
                  if lab.result_datetime >= disch_cutoff
                  and lab.result_datetime <= inpatient.discharge_datetime]

    # Diagnoses
    adm_dx = code_lookup(
        cif_record.clinical_diagnosis.admission_diagnosis_system,
        cif_record.clinical_diagnosis.admission_diagnosis_code,
        "en"
    ) if cif_record.clinical_diagnosis.admission_diagnosis_code else "Unknown"

    disch_dx = code_lookup(
        cif_record.clinical_diagnosis.discharge_diagnosis_system,
        cif_record.clinical_diagnosis.discharge_diagnosis_code,
        "en"
    ) if cif_record.clinical_diagnosis.discharge_diagnosis_code else adm_dx

    # Medications
    disch_meds = []
    if cif_record.discharge_prescription:
        disch_meds = [item.get("drug_name", "Unknown")
                      for item in cif_record.discharge_prescription.items]

    los = (inpatient.discharge_datetime - inpatient.admission_datetime).days

    return {
        "type": "Discharge Summary",
        "patient": cif_record.patient,
        "encounter": inpatient,
        "admission_vitals": adm_vitals,
        "admission_labs": adm_labs,
        "discharge_vitals": disch_vitals,
        "discharge_labs": disch_labs,
        "admission_diagnosis": adm_dx,
        "discharge_diagnosis": disch_dx,
        "discharge_medications": disch_meds,
        "los_days": los,
    }


def extract_operative_note_data(cif_record):
    """Extract data for Operative Note."""
    if not cif_record.procedures:
        return None

    proc = cif_record.procedures[0]

    # For now, use mock data since CIF procedure structure may vary
    return {
        "type": "Operative Note",
        "patient": cif_record.patient,
        "procedure": proc,
        "mock": True,  # Flag to indicate we need better extraction
    }


def extract_procedure_note_data(cif_record):
    """Extract data for Procedure Note."""
    if not cif_record.procedures:
        return None

    proc = cif_record.procedures[0]

    return {
        "type": "Procedure Note",
        "patient": cif_record.patient,
        "procedure": proc,
        "mock": True,
    }


def extract_death_note_data(cif_record):
    """Extract data for Death Note."""
    if not cif_record.deceased:
        return None

    # Find death encounter
    death_enc = None
    for enc in cif_record.encounters:
        if enc.discharge_disposition == "exp":
            death_enc = enc
            break

    if not death_enc:
        return None

    dx = code_lookup(
        cif_record.clinical_diagnosis.discharge_diagnosis_system,
        cif_record.clinical_diagnosis.discharge_diagnosis_code,
        "en"
    ) if cif_record.clinical_diagnosis.discharge_diagnosis_code else "Unknown"

    return {
        "type": "Death Note",
        "patient": cif_record.patient,
        "encounter": death_enc,
        "cause_of_death": dx,
        "death_datetime": death_enc.discharge_datetime,
    }


def build_prompt(data: dict) -> tuple[str, str]:
    """Build prompt based on narrative type."""

    if data["type"] == "Admission H&P":
        system = "You are a physician writing an admission History & Physical. Write in English. Use standard medical terminology."

        patient = data["patient"]
        enc = data["encounter"]
        vitals = data["admission_vitals"]
        labs = data["admission_labs"]

        parts = [
            f"Patient: {patient.age}yo {patient.sex}",
            f"Chief Complaint: {enc.chief_complaint}",
            f"Admission Diagnosis: {data['diagnosis']}",
            "",
        ]

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

        if labs:
            parts.append("Admission Labs:")
            for lab in labs[:5]:
                flag = f" ({lab.flag})" if lab.flag else ""
                parts.append(f"  - {lab.lab_name}: {lab.value} {lab.unit or ''}{flag}")
            parts.append("")

        parts.append("Write a concise admission H&P (500-800 chars).")

        return system, "\n".join(parts)

    elif data["type"] == "Discharge Summary":
        system = "You are a physician writing a discharge summary. Be comprehensive but concise. Write in English. Use standard medical terminology."

        patient = data["patient"]
        enc = data["encounter"]

        parts = [
            f"Patient: {patient.age}yo {patient.sex}",
            f"Admission Date: {enc.admission_datetime.strftime('%Y-%m-%d')}",
            f"Discharge Date: {enc.discharge_datetime.strftime('%Y-%m-%d')}",
            f"Length of Stay: {data['los_days']} days",
            "",
            f"Chief Complaint: {enc.chief_complaint}",
            f"Admission Diagnosis: {data['admission_diagnosis']}",
            f"Discharge Diagnosis: {data['discharge_diagnosis']}",
            "",
        ]

        if data['admission_vitals']:
            v = data['admission_vitals']
            parts.append("Admission Vitals:")
            if v.temperature_celsius:
                parts.append(f"  - Temp: {v.temperature_celsius}°C")
            if v.heart_rate:
                parts.append(f"  - HR: {v.heart_rate} bpm")
            if v.spo2:
                parts.append(f"  - SpO2: {v.spo2}%")
            parts.append("")

        if data['admission_labs']:
            parts.append("Admission Labs:")
            for lab in data['admission_labs'][:3]:
                parts.append(f"  - {lab.lab_name}: {lab.value} {lab.unit or ''}")
            parts.append("")

        if data['discharge_vitals']:
            parts.append("Discharge Vitals: Stable")
            parts.append("")

        if data['discharge_medications']:
            parts.append("Discharge Medications:")
            for med in data['discharge_medications']:
                parts.append(f"  - {med}")
            parts.append("")

        parts.append("Write a concise discharge summary (500-800 chars).")

        return system, "\n".join(parts)

    elif data["type"] == "Operative Note":
        system = "You are a surgeon writing an operative note. Write in English. Use standard medical terminology."

        patient = data["patient"]

        user = f"""Patient: {patient.age}yo {patient.sex}

Procedure: Hip fracture ORIF (mock data - using template)
Preop Diagnosis: Femoral neck fracture
Postop Diagnosis: Femoral neck fracture (internal fixation performed)
Anesthesia: General anesthesia
Duration: 120 minutes
EBL: 450 mL
Findings: Fracture line clear, good bone quality
Complications: None

Write a concise operative note (500-800 chars)."""

        return system, user

    elif data["type"] == "Procedure Note":
        system = "You are a physician writing a procedure note. Write in English. Use standard medical terminology."

        patient = data["patient"]

        user = f"""Patient: {patient.age}yo {patient.sex}

Procedure: Central venous catheter insertion (mock data - using template)
Indication: Septic shock, fluid management
Technique: Seldinger technique, right internal jugular vein
Complications: None

Write a concise procedure note (500-800 chars)."""

        return system, user

    elif data["type"] == "Death Note":
        system = "You are a physician writing a death note. Be respectful and concise. Write in English. Use standard medical terminology."

        patient = data["patient"]
        enc = data["encounter"]

        user = f"""Patient: {patient.age}yo {patient.sex}

Time of Death: {enc.discharge_datetime.strftime('%Y-%m-%d %H:%M')}
Cause of Death: {data['cause_of_death']}

Hospital Course: Patient was admitted and received intensive treatment but condition deteriorated.

Write a concise death note (500-800 chars)."""

        return system, user

    return "", ""


def main():
    print("=" * 80)
    print("GENERATE ALL 5 NARRATIVE TYPES FROM CIF DATA")
    print("=" * 80)

    # Use forced scenarios to ensure we get all types
    print("\n[1] Generating forced scenarios...")
    config = SimulatorConfig(country="US", random_seed=42)

    # Generate different patients for different narratives
    scenarios = {
        "admission_discharge": ForcedScenario(
            disease_id="bacterial_pneumonia",
            severity="moderate",
            n_patients=1
        ),
        "death": ForcedScenario(
            disease_id="hemorrhagic_stroke",
            severity="severe",
            n_patients=1,
            force_outcome="death"
        ),
    }

    all_records = []

    for name, scenario in scenarios.items():
        print(f"    Generating {name}...")
        cif = run_forced(scenario, config)
        all_records.extend(cif.patients)

    print(f"    ✓ Generated {len(all_records)} patient records")

    # Find patients for each narrative type
    print("\n[2] Finding suitable patients for each narrative type...")

    narratives_to_generate = []

    # 1. Admission H&P - any inpatient
    for record in all_records:
        data = extract_admission_hp_data(record)
        if data:
            narratives_to_generate.append(data)
            print(f"    ✓ Admission H&P: {data['patient'].age}yo {data['patient'].sex}")
            break

    # 2. Discharge Summary - inpatient with discharge
    for record in all_records:
        data = extract_discharge_summary_data(record)
        if data:
            narratives_to_generate.append(data)
            print(f"    ✓ Discharge Summary: {data['patient'].age}yo {data['patient'].sex}")
            break

    # 3. Operative Note - patient with procedure (mock for now)
    for record in all_records:
        data = extract_operative_note_data(record)
        if data:
            narratives_to_generate.append(data)
            print(f"    ✓ Operative Note: {data['patient'].age}yo {data['patient'].sex} (mock data)")
            break

    # 4. Procedure Note - patient with procedure (mock for now)
    for record in all_records:
        data = extract_procedure_note_data(record)
        if data:
            narratives_to_generate.append(data)
            print(f"    ✓ Procedure Note: {data['patient'].age}yo {data['patient'].sex} (mock data)")
            break

    # 5. Death Note - deceased patient
    for record in all_records:
        data = extract_death_note_data(record)
        if data:
            narratives_to_generate.append(data)
            print(f"    ✓ Death Note: {data['patient'].age}yo {data['patient'].sex}")
            break

    print(f"\n    Found {len(narratives_to_generate)}/5 narrative types")

    # Generate narratives
    print("\n[3] Generating narratives with Bedrock...")

    provider = BedrockProvider({
        "region": "us-east-1",
        "model": "us.anthropic.claude-sonnet-4-6",
    })

    for i, data in enumerate(narratives_to_generate, 1):
        print(f"\n{'=' * 80}")
        print(f"{i}. {data['type']}")
        print("=" * 80)

        system, user = build_prompt(data)

        print("\n[INPUT PROMPT]")
        print("-" * 80)
        print(user[:500] + "..." if len(user) > 500 else user)

        print("\n[GENERATING...]")
        import time
        t0 = time.time()
        response = provider.complete(
            prompt=user,
            model="us.anthropic.claude-sonnet-4-6",
            max_tokens=2000,
            system_prompt=system,
        )
        t1 = time.time()

        print(f"✓ Generated in {t1-t0:.1f}s")
        print(f"  Input: {response.input_tokens} tokens")
        print(f"  Output: {response.output_tokens} tokens")

        print("\n[GENERATED NARRATIVE]")
        print("-" * 80)
        print(response.text)
        print()

        if data.get("mock"):
            print("⚠️  Note: This narrative uses mock/template data")
            print("   Real CIF extraction for procedures not yet implemented")

    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"✓ Successfully generated {len(narratives_to_generate)}/5 narrative types")
    print("✓ Used real CIF data where available")
    print("⚠️  Operative/Procedure notes use mock data (CIF extraction needed)")
    print()


if __name__ == "__main__":
    main()
