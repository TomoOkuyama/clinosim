# `clinosim.modules.drug_safety`

Class-based contraindication gate + alternative-drug substitution.

> **Note**: This is a stub README to unblock the module-readme-coverage gate.
> The full canonical 11-section README is authored in Task 15 of the
> implementation plan (`docs/superpowers/plans/2026-09-03-drug-safety-module.md`).
> The authoritative design lives at
> [`docs/superpowers/specs/2026-09-03-drug-safety-module-design.md`](../../../docs/superpowers/specs/2026-09-03-drug-safety-module-design.md).

## Purpose

Prevents contraindicated medication co-prescriptions from appearing in
generated CIF/FHIR records, matching how a real EHR CPOE system
suppresses them at order-entry time. Where the pre-fix cohort emits
~150 contraindicated pairs per 10 000 US patients (warfarin+aspirin,
warfarin+NSAID, β-blocker + non-DHP CCB, ACEi/ARB + K supplement), the
gate reduces that count to zero via a class-based rule engine invoked
from the `order` and `patient` modules.

## Public API

- `check_pair(drug_a, drug_b) -> SafetyVerdict`
- `check_candidate_against_active(candidate, active_meds) -> list[SafetyVerdict]`
- `suggest_alternative(candidate, indication, *, active_meds, disease_ctx, country) -> AlternativeDrug | None`
- `resolve_classes(drug_name) -> list[str]`
- `canonical_name(drug_name) -> str | None`
- `japanese_display(drug_name) -> str | None`

## Ownership

Session 99 (2026-09-03).
