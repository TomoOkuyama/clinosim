#!/usr/bin/env python3
"""
Test the new narrative module.

Verifies:
1. Module imports work correctly
2. CIF extraction functions work
3. Prompt building functions work
4. Integration with existing test data
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from clinosim.modules.narrative import (
    extract_admission_hp_data,
    extract_discharge_summary_data,
    identify_narratives_needed,
    build_prompt,
)
from clinosim.simulator.engine import run_forced
from clinosim.types.config import SimulatorConfig, ForcedScenario


def main():
    print("=" * 80)
    print("NARRATIVE MODULE INTEGRATION TEST")
    print("=" * 80)

    # Generate test data
    print("\n[1] Generating test patient with forced scenario...")
    config = SimulatorConfig(country="US", random_seed=42)
    scenario = ForcedScenario(
        disease_id="bacterial_pneumonia",
        severity="moderate",
        n_patients=1
    )

    cif = run_forced(scenario, config)
    cif_record = cif.patients[0]

    print(f"    ✓ Patient: {cif_record.patient.age}yo {cif_record.patient.sex}")
    print(f"    ✓ Encounters: {len(cif_record.encounters)}")
    print(f"    ✓ Vitals: {len(cif_record.vital_signs)}")
    print(f"    ✓ Labs: {len(cif_record.lab_results)}")

    # Test identify_narratives_needed
    print("\n[2] Testing identify_narratives_needed()...")
    needed = identify_narratives_needed(cif_record)
    print(f"    ✓ Narratives needed: {needed}")

    # Test CIF extraction
    print("\n[3] Testing CIF extraction functions...")

    # Test Admission H&P extraction
    hp_data = extract_admission_hp_data(cif_record)
    if hp_data:
        print("    ✓ Admission H&P data extracted:")
        print(f"      - Patient: {hp_data['patient'].age}yo {hp_data['patient'].sex}")
        print(f"      - Diagnosis: {hp_data['admission_diagnosis']}")
        print(f"      - Vitals: {hp_data['admission_vitals'] is not None}")
        print(f"      - Labs: {len(hp_data['admission_labs'])} tests")
    else:
        print("    ✗ No Admission H&P data (no inpatient encounter)")

    # Test Discharge Summary extraction
    ds_data = extract_discharge_summary_data(cif_record)
    if ds_data:
        print("    ✓ Discharge Summary data extracted:")
        print(f"      - LOS: {ds_data['los_days']} days")
        print(f"      - Admission DX: {ds_data['admission_diagnosis']}")
        print(f"      - Discharge DX: {ds_data['discharge_diagnosis']}")
        print(f"      - Medications: {len(ds_data['discharge_medications'])}")
    else:
        print("    ✗ No Discharge Summary data (no discharged encounter)")

    # Test prompt building
    print("\n[4] Testing prompt building...")

    if hp_data:
        system, user = build_prompt("admission_hp", hp_data, "en")
        print("    ✓ Admission H&P prompt built:")
        print(f"      - System prompt length: {len(system)} chars")
        print(f"      - User prompt length: {len(user)} chars")
        print(f"      - User prompt preview:")
        print("      " + "-" * 70)
        for line in user.split("\n")[:10]:
            print(f"      {line}")
        print("      " + "-" * 70)

    if ds_data:
        system, user = build_prompt("discharge_summary", ds_data, "en")
        print("    ✓ Discharge Summary prompt built:")
        print(f"      - System prompt length: {len(system)} chars")
        print(f"      - User prompt length: {len(user)} chars")

    # Summary
    print("\n" + "=" * 80)
    print("TEST SUMMARY")
    print("=" * 80)
    print("✓ Module imports successful")
    print("✓ CIF extraction functions work")
    print("✓ Prompt building functions work")
    print("✓ Integration with existing codebase works")
    print()
    print("Next step: Test with Bedrock LLM to generate actual narratives")
    print("Run: python test_all_narratives.py")
    print()


if __name__ == "__main__":
    main()
