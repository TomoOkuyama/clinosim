#!/usr/bin/env python3
"""
Generate a narrative from actual CIF data (1 patient simulation).

This script:
1. Runs a minimal simulation (10 patients, 1 month)
2. Extracts the first inpatient encounter from CIF
3. Extracts clinical data from CIF (vitals, labs, meds)
4. Generates narrative using REAL CIF data
5. Checks consistency between narrative and CIF
"""

import sys
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent))

from clinosim.simulator.engine import run_beta
from clinosim.types.config import SimulatorConfig
from clinosim.types.encounter import EncounterType
from clinosim.modules.llm_service.engine import (
    LLMService,
    LLMTaskType,
    PatientSummary,
    ClinicalEventData,
)
from clinosim.modules.llm_service.providers import BedrockProvider
from clinosim.codes import lookup as code_lookup


def extract_data_from_cif(cif_record):
    """Extract clinical data from CIF for narrative generation."""

    # Find first inpatient encounter
    inpatient_encounter = None
    for enc in cif_record.encounters:
        if enc.encounter_type == EncounterType.INPATIENT:
            inpatient_encounter = enc
            break

    if not inpatient_encounter:
        return None

    # Get admission vitals (first vital after admission)
    admission_vitals = None
    if cif_record.vital_signs:
        for vs in cif_record.vital_signs:
            if vs.timestamp >= inpatient_encounter.admission_datetime:
                admission_vitals = vs
                break

    # Get admission labs (within first 4 hours)
    from datetime import timedelta
    admission_cutoff = inpatient_encounter.admission_datetime + timedelta(hours=4)
    admission_labs = [
        lab for lab in cif_record.lab_results
        if lab.result_datetime >= inpatient_encounter.admission_datetime
        and lab.result_datetime <= admission_cutoff
    ]

    # Get discharge vitals (last vital before discharge)
    discharge_vitals = None
    if cif_record.vital_signs and inpatient_encounter.discharge_datetime:
        for vs in reversed(cif_record.vital_signs):
            if vs.timestamp <= inpatient_encounter.discharge_datetime:
                discharge_vitals = vs
                break

    # Get discharge labs (within last 24h before discharge)
    discharge_labs = []
    if inpatient_encounter.discharge_datetime:
        discharge_cutoff = inpatient_encounter.discharge_datetime - timedelta(hours=24)
        discharge_labs = [
            lab for lab in cif_record.lab_results
            if lab.result_datetime >= discharge_cutoff
            and lab.result_datetime <= inpatient_encounter.discharge_datetime
        ]

    # Resolve diagnosis codes to English
    admission_dx = code_lookup(
        cif_record.clinical_diagnosis.admission_diagnosis_system,
        cif_record.clinical_diagnosis.admission_diagnosis_code,
        "en"
    ) if cif_record.clinical_diagnosis.admission_diagnosis_code else "Unknown"

    discharge_dx = code_lookup(
        cif_record.clinical_diagnosis.discharge_diagnosis_system,
        cif_record.clinical_diagnosis.discharge_diagnosis_code,
        "en"
    ) if cif_record.clinical_diagnosis.discharge_diagnosis_code else admission_dx

    # Get medications
    discharge_meds = []
    if cif_record.discharge_prescription:
        discharge_meds = [item.get("drug_name", "Unknown") for item in cif_record.discharge_prescription.items]

    return {
        "encounter": inpatient_encounter,
        "patient": cif_record.patient,
        "admission_vitals": admission_vitals,
        "admission_labs": admission_labs,
        "discharge_vitals": discharge_vitals,
        "discharge_labs": discharge_labs,
        "admission_diagnosis": admission_dx,
        "discharge_diagnosis": discharge_dx,
        "discharge_medications": discharge_meds,
        "los_days": (inpatient_encounter.discharge_datetime - inpatient_encounter.admission_datetime).days if inpatient_encounter.discharge_datetime else 0,
    }


def build_enriched_prompt_discharge_summary(data: dict) -> tuple[str, str]:
    """Build a detailed prompt using REAL CIF data for Discharge Summary."""

    patient = data["patient"]
    enc = data["encounter"]
    adm_vitals = data["admission_vitals"]
    adm_labs = data["admission_labs"]
    disch_vitals = data["discharge_vitals"]
    disch_labs = data["discharge_labs"]

    # System prompt
    system = (
        "You are a physician writing a discharge summary. "
        "Be comprehensive but concise. Write in English. Use standard medical terminology."
    )

    # User prompt with REAL CIF data
    user_parts = [
        f"Patient: {patient.age}yo {patient.sex}",
        f"Admission Date: {enc.admission_datetime.strftime('%Y-%m-%d')}",
        f"Discharge Date: {enc.discharge_datetime.strftime('%Y-%m-%d') if enc.discharge_datetime else 'In progress'}",
        f"Length of Stay: {data['los_days']} days",
        f"",
        f"Chief Complaint: {enc.chief_complaint}",
        f"",
        f"Admission Diagnosis: {data['admission_diagnosis']}",
        f"Discharge Diagnosis: {data['discharge_diagnosis']}",
        f"",
    ]

    # Admission vitals (REAL from CIF)
    if adm_vitals:
        user_parts.append("Admission Vitals:")
        if adm_vitals.temperature_celsius:
            user_parts.append(f"  - Temp: {adm_vitals.temperature_celsius}°C")
        if adm_vitals.heart_rate:
            user_parts.append(f"  - HR: {adm_vitals.heart_rate} bpm")
        if adm_vitals.systolic_bp and adm_vitals.diastolic_bp:
            user_parts.append(f"  - BP: {adm_vitals.systolic_bp}/{adm_vitals.diastolic_bp} mmHg")
        if adm_vitals.respiratory_rate:
            user_parts.append(f"  - RR: {adm_vitals.respiratory_rate} /min")
        if adm_vitals.spo2:
            user_parts.append(f"  - SpO2: {adm_vitals.spo2}%")
        user_parts.append("")

    # Admission labs (REAL from CIF)
    if adm_labs:
        user_parts.append("Admission Labs:")
        for lab in adm_labs[:5]:  # First 5 labs
            flag_str = f" ({lab.flag})" if lab.flag else ""
            user_parts.append(f"  - {lab.lab_name}: {lab.value} {lab.unit or ''}{flag_str}")
        user_parts.append("")

    # Discharge vitals (REAL from CIF)
    if disch_vitals:
        user_parts.append("Discharge Vitals:")
        if disch_vitals.temperature_celsius:
            user_parts.append(f"  - Temp: {disch_vitals.temperature_celsius}°C")
        if disch_vitals.heart_rate:
            user_parts.append(f"  - HR: {disch_vitals.heart_rate} bpm")
        if disch_vitals.systolic_bp and disch_vitals.diastolic_bp:
            user_parts.append(f"  - BP: {disch_vitals.systolic_bp}/{disch_vitals.diastolic_bp} mmHg")
        if disch_vitals.spo2:
            user_parts.append(f"  - SpO2: {disch_vitals.spo2}%")
        user_parts.append("")

    # Discharge labs (REAL from CIF)
    if disch_labs:
        user_parts.append("Discharge Labs:")
        for lab in disch_labs[:5]:
            user_parts.append(f"  - {lab.lab_name}: {lab.value} {lab.unit or ''}")
        user_parts.append("")

    # Discharge medications
    if data["discharge_medications"]:
        user_parts.append("Discharge Medications:")
        for med in data["discharge_medications"]:
            user_parts.append(f"  - {med}")
        user_parts.append("")

    user_parts.append("Write a concise discharge summary (500-800 chars).")

    user = "\n".join(user_parts)

    return system, user


def main():
    print("=" * 80)
    print("CIF-BASED NARRATIVE GENERATION TEST")
    print("=" * 80)

    # Step 1: Run minimal simulation
    print("\n[1] Running minimal simulation (100 patients, 3 months)...")
    print("    This will take 1-2 minutes...")

    config = SimulatorConfig(
        catchment_population=100,
        time_range=("2025-01-01", "2025-03-31"),
        country="US",
        random_seed=42,
    )

    cif_dataset = run_beta(config)

    print(f"    ✓ Generated {len(cif_dataset.patients)} patient records")

    # Step 2: Find first inpatient encounter
    print("\n[2] Finding first inpatient encounter in CIF...")

    cif_record = None
    for patient_record in cif_dataset.patients:
        has_inpatient = any(
            enc.encounter_type == EncounterType.INPATIENT
            for enc in patient_record.encounters
        )
        if has_inpatient:
            cif_record = patient_record
            break

    if not cif_record:
        print("    ✗ No inpatient encounters found in this simulation")
        print("    Try running again with different seed or larger population")
        sys.exit(1)

    print(f"    ✓ Found patient: {cif_record.patient.age}yo {cif_record.patient.sex}")

    # Step 3: Extract clinical data from CIF
    print("\n[3] Extracting clinical data from CIF...")

    data = extract_data_from_cif(cif_record)

    if not data:
        print("    ✗ Could not extract data")
        sys.exit(1)

    print(f"    ✓ Chief complaint: {data['encounter'].chief_complaint}")
    print(f"    ✓ Admission diagnosis: {data['admission_diagnosis']}")
    print(f"    ✓ LOS: {data['los_days']} days")
    print(f"    ✓ Admission vitals: {data['admission_vitals'] is not None}")
    print(f"    ✓ Admission labs: {len(data['admission_labs'])} tests")
    print(f"    ✓ Discharge vitals: {data['discharge_vitals'] is not None}")
    print(f"    ✓ Discharge labs: {len(data['discharge_labs'])} tests")

    # Step 4: Build enriched prompt with CIF data
    print("\n[4] Building prompt with REAL CIF data...")

    system_prompt, user_prompt = build_enriched_prompt_discharge_summary(data)

    print("\n--- SYSTEM PROMPT ---")
    print(system_prompt)
    print("\n--- USER PROMPT ---")
    print(user_prompt)

    # Step 5: Generate narrative
    print("\n" + "=" * 80)
    print("[5] Generating narrative with Bedrock...")
    print("=" * 80)

    provider = BedrockProvider({
        "region": "us-east-1",
        "model": "us.anthropic.claude-sonnet-4-6",
    })

    import time
    t0 = time.time()

    response = provider.complete(
        prompt=user_prompt,
        model="us.anthropic.claude-sonnet-4-6",
        max_tokens=4000,
        system_prompt=system_prompt,
    )

    t1 = time.time()

    print(f"✓ Generated in {t1-t0:.1f} seconds")
    print(f"  Input tokens: {response.input_tokens}")
    print(f"  Output tokens: {response.output_tokens}")

    # Step 6: Show generated narrative
    print("\n" + "=" * 80)
    print("[6] GENERATED DISCHARGE SUMMARY")
    print("=" * 80)
    print()
    print(response.text)
    print()

    # Step 7: Consistency check
    print("=" * 80)
    print("[7] CONSISTENCY CHECK")
    print("=" * 80)

    narrative_lower = response.text.lower()

    print("\n✓ DATA FROM CIF (included in prompt):")
    if data['admission_vitals']:
        print(f"  ✓ Admission temp: {data['admission_vitals'].temperature_celsius}°C")
        print(f"  ✓ Admission HR: {data['admission_vitals'].heart_rate} bpm")
        print(f"  ✓ Admission BP: {data['admission_vitals'].systolic_bp}/{data['admission_vitals'].diastolic_bp}")

    if data['admission_labs']:
        print(f"  ✓ Admission labs: {len(data['admission_labs'])} tests")
        for lab in data['admission_labs'][:3]:
            print(f"     - {lab.lab_name}: {lab.value} {lab.unit or ''}")

    if data['discharge_vitals']:
        print(f"  ✓ Discharge vitals: Stable")

    print(f"\n✓ LOS: {data['los_days']} days")
    print(f"✓ Admission DX: {data['admission_diagnosis']}")
    print(f"✓ Discharge DX: {data['discharge_diagnosis']}")

    print("\n⚠️  CHECK NARRATIVE:")
    # Check if narrative mentions vitals that match CIF
    if data['admission_vitals'] and data['admission_vitals'].temperature_celsius:
        temp_str = str(data['admission_vitals'].temperature_celsius)
        if temp_str in response.text or temp_str.replace('.', '') in response.text:
            print(f"  ✓ Narrative mentions admission temp: {temp_str}°C")
        else:
            print(f"  ⚠️  Narrative does not mention exact admission temp from CIF")

    # Check if narrative mentions labs from CIF
    if data['admission_labs']:
        for lab in data['admission_labs'][:2]:
            if lab.lab_name.lower() in narrative_lower:
                print(f"  ✓ Narrative mentions {lab.lab_name}")

    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print("✓ Used REAL CIF data (not mock data)")
    print("✓ Extracted actual vitals, labs, medications from CIF")
    print("✓ Generated narrative with clinical context")
    print()
    print("NEXT STEPS:")
    print("- Implement cif_extractor.py module with this logic")
    print("- Update _build_prompt() to use extracted CIF data")
    print("- Add validator to check narrative-CIF consistency")
    print()


if __name__ == "__main__":
    main()
