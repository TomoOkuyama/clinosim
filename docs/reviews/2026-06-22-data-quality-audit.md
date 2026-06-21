# Data-quality audit — 2026-06-22

**Scope:** Comprehensive audit after the AD-55 Base completion (family history,
code status, extended SDOH) and the FA-1 adapter split + data-quality follow-ups.

**Datasets:** US 10,000 catchment (seed 42) → 24,568 patients / 160,059 encounters;
JP 5,000 (seed 42, `--jp-insurance`) → 2,454 patients / 16,001 encounters. FHIR R4
Bulk export + CIF.

## Result: clean — no fixes required

### FHIR conformance (US and JP)

| Check | US | JP |
|---|---|---|
| Duplicate resource ids | **0** | **0** |
| Unresolved references | **0** | **0** |
| `display == code` | **0** | **0** |
| Japanese chars in US output | **0** | n/a |
| Numeric Observations missing referenceRange | 251,690 | 34,479 |

The "missing referenceRange" set is **exactly** the observations that have no
clinical normal range — Supplemental oxygen flow rate (a dose) and the 24-hour
intake/output totals:

```
187,853  Supplemental oxygen flow rate
 21,279  Fluid intake total 24 hour
 21,279  Urine output 24 hour
 21,279  Fluid output total 24 hour
```

This matches the documented-correct behaviour from the 2026-06-21 audit (O2 dose +
24h I/O legitimately carry no referenceRange). Every lab/vital with a normal range
has one. **Not a regression.**

### New AD-55 Base data

- **Smoking status** (US Core, both countries): one per patient. US never 52% /
  former 28% / current 19%; JP never 56% / former 29% / current 15%. Plausible.
- **Alcohol use**: one per patient. US none 38% / social 47% / heavy 16%.
- **Family history**: 68,832 US / 6,874 JP FamilyMemberHistory (~2.8 relatives ×
  patients).
- **Code status**: For-resuscitation 87% / DNR 11% / Comfort 2.7% (US); similar JP.
- **要介護度 (care level)**: JP only (US = 0). 330/2,454 JP patients certified
  (~13% overall, age-weighted), distribution skewed to 要支援1-2 / 要介護1.

### Clinical coherence (CIF)

- **Sepsis min-SBP**: US median 104, **SBP<90 = 20%** — the distributive-shock fix
  (PR #62) confirmed in a fresh dataset. JP median 100.5 (n=12, noisier).
- **HbA1c**: US median 7.0, JP 6.6 (glycemic-control model, PR #44).
- **MI Troponin_I**: median ~72-75, max 173 (elevated for AMI).

## Conclusion

The full session's work — FA-1 monolith split, the chronic-primary-diagnosis and
septic-shock fixes, and the three new AD-55 Base features — maintains complete FHIR
conformance and clinical coherence with no regressions. No code changes required.

## Pending (environment-blocked)

Two SNOMED concept bindings carry `# TODO: verify` because the SNOMED CT
browser/Snowstorm API is unreachable from the build environment: the code-status
resuscitation concepts (PR #64) and the alcohol-use values (PR #65). Verify against
the SNOMED CT browser before release. The 要介護度 classification itself is
authoritative (MHLW); only the FHIR concept-code binding is provisional.
