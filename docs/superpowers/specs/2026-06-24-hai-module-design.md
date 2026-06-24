# PR-B — `modules/hai` design (Phase 2 of device + HAI series)

**Date**: 2026-06-24
**Series**: device + HAI feature (Phase 2 of 4-PR plan)
**Type**: New feature (3-axis DQR gate)
**Branch**: `feat/hai-module-prb`

## Background

PR-A (`modules/device`, merged as #88) landed `extensions["device"] =
list[DeviceRecord]` for ICU encounters with 3 device types (CVC,
indwelling catheter, ventilator). PR-A's spec called out PR-B as the
**first consumer** of that cross-module dependency point.

PR-B implements `modules/hai`: a post_records enricher that consumes
device line-days, samples CLABSI / CAUTI / VAP onsets via CDC NHSN
per-line-day risk rates, emits FHIR `Condition` resources, and appends
diagnostic cultures to the existing `record.microbiology` field so the
existing `_fhir_microbiology.py` builder picks them up automatically.

## Goals

1. New `modules/hai/` AD-55 opt-in Module emitting HAI `Condition`
   resources on ICU encounters whose devices acquired an infection.
2. Three HAI types matched 1:1 to PR-A device types:
   - **CLABSI** ← CVC (SNOMED 52124006)
   - **CAUTI** ← indwelling catheter (SNOMED 23973005)
   - **VAP** ← ventilator (SNOMED 706172005)
3. Onset sampling via CDC NHSN baseline per-line-day risk rates
   (per-day risk 0.0010–0.0015), independent sub-seed
   (`ENRICHER_SEED_OFFSETS["hai"] = 0x4841` "HA").
4. Culture confirmation per CDC HAI definition — append
   `MicrobiologyResult` to `record.microbiology`; existing
   `_fhir_microbiology.py` builder emits Specimen + Observation +
   DiagnosticReport (zero new wiring).
5. New `_fhir_hai.py` builder file (PR3 theme-per-file pattern) emits
   only the HAI Condition.
6. 3-axis DQR PASS (structural / clinical / JP language).
7. Documentation sync in PR-B (no follow-up doc PR per
   `feedback_pr_merge_dqr_required`).

## Non-goals (explicit defer-list)

1. **Antibiotic treatment orders** (empirical Vancomycin / Cefazolin →
   narrow on culture). Phase 3.
2. **Susceptibility (S/I/R) results** —
   `MicrobiologyResult.susceptibilities = []`. Phase 3 antimicrobial
   resistance work will fill these.
3. **HAI-triggered WBC / CRP shifts**. State mutation banned (PR #62
   lesson); a BNP-pattern observation-time formula is implementable but
   out of scope here.
4. **Mortality impact** (HAI onset → in-hospital mortality lift). Phase 3
   outcome benchmarks.
5. **Repeat HAI on the same device**. Each DeviceRecord produces at most
   one HAIEvent — at-most-one simplification.
6. **Strict snapshot-in-progress line-days**. When
   `device.removal_date is None`, the sampler uses a conservative
   line_days = 7. Phase 3 will refine using the simulator's snapshot
   date.
7. **Peripheral IV / arterial line HAIs**. Phase 1 device scope cap
   inherited; future PR if downstream analytics needs it.
8. **Device-state mutation on HAI** (e.g. early removal). State unchanged
   (BNP-pattern surgical principle).

## Architecture

```
PR-A (merged):
  CIFPatientRecord.extensions["device"] = list[DeviceRecord]   ← upstream

PR-B (this spec):
  hai_enricher (post_records, order=80)
    ├─ extensions["device"] walk
    ├─ per-device probability sampling (line-days × CDC NHSN per-day risk)
    ├─ independent per-patient sub-seed (0x4841 "HA")
    ├─ on onset → HAIEvent + culture MicrobiologyResult
    └─ writes: extensions["hai"] + record.microbiology.append(...)

  _fhir_hai.py (new theme-per-file builder)
    └─ _build_hai_conditions(ctx)  — Condition resource (ICD-10 + SNOMED dual coding)

  _fhir_microbiology.py (existing, PR3-extracted)
    └─ already iterates record.microbiology → emits Specimen + Observation
        + DiagnosticReport for HAI cultures with zero new wiring
```

### AD-55 classification

- **Opt-in Module** (not Base). Production default-on, registered via
  `register_builtin_enrichers()` with `enabled=lambda c: True`
  (matching PR-A / immunization / family_history precedent).
- Sub-seed offset: `0x4841` ("HA"). Module-level assert in
  `clinosim/simulator/seeding.py` catches collisions.
- Enricher order = 80 (after device=70). HAI enricher must run after
  device because it consumes `extensions["device"]`.

## Components

### `clinosim/types/hai.py` (new shared type)

```python
"""Hospital-acquired infection events (AD-55 Module: hai)."""
from __future__ import annotations
from dataclasses import dataclass


@dataclass
class HAIEvent:
    """One HAI onset detected during an ICU encounter.

    Stored as list[HAIEvent] under CIFPatientRecord.extensions["hai"].
    Onset sampled probabilistically from CDC NHSN per-line-day risk
    rates against PR-A device line-days. A corresponding
    MicrobiologyResult is appended to record.microbiology to satisfy
    the CDC culture-confirmation criterion (emitted by the existing
    _fhir_microbiology.py builder).
    """
    hai_id: str
    encounter_id: str
    hai_type: str            # "clabsi" | "cauti" | "vap"
    source_device_id: str
    icd10_code: str          # internal canonical; mapped at output
    snomed_code: str
    onset_date: str          # ISO YYYY-MM-DD
    organism_snomed: str
    culture_specimen_id: str
```

Direct-import pattern (`from clinosim.types.hai import HAIEvent`) matching
PR-A `DeviceRecord` precedent — no `__init__.py` registration.

### `clinosim/modules/hai/`

```
__init__.py                # public API: load_*_config, enrich_hai
engine.py                  # sample_hai_onset, _sample_organism, loaders
enricher.py                # post_records Enricher
reference_data/
  hai_rates.yaml           # CDC NHSN per-line-day risk rates
  hai_codes.yaml           # 3 ICD-10-CM + WHO + SNOMED codes
  hai_organisms.yaml       # per-HAI organism distribution (weight)
  hai_specimens.yaml       # per-HAI specimen SNOMED + LOINC
README.md                  # TEMPLATE_MODULE_README.md
```

### `reference_data/hai_rates.yaml`

```yaml
# CDC NHSN device-associated infection rates per 1000 device-days
# (2018-2020 ICU mixed wards average; National Healthcare Safety
# Network annual reports, https://www.cdc.gov/nhsn/datastat).
hai_rates:
  clabsi:
    per_day_risk: 0.0010
    source_device_type: cvc
  cauti:
    per_day_risk: 0.0014
    source_device_type: indwelling_catheter
  vap:
    per_day_risk: 0.0015
    source_device_type: mechanical_ventilator
```

### `reference_data/hai_codes.yaml`

```yaml
# All codes pending tx.fhir.org $expand + NLM ICD-10-CM API
# verification at implementation time (Task 1 of the plan).
# Spec values are tentative; PR #80 fabrication-prevention precedent.
hai_codes:
  clabsi:
    icd10_us_billable: "T80.211A"   # TODO: verify NLM ICD-10-CM API
    icd10_jp_who: "T80.2"           # TODO: verify WHO ICD-10 browser
    snomed: "433142000"             # TODO: verify tx.fhir.org $expand
    display_en: "Bloodstream infection due to central venous catheter"
    display_ja: "中心静脈カテーテル関連血流感染症"
  cauti:
    icd10_us_billable: "T83.511A"
    icd10_jp_who: "T83.5"
    snomed: "425500004"
    display_en: "Catheter-associated urinary tract infection"
    display_ja: "カテーテル関連尿路感染症"
  vap:
    icd10_us_billable: "J95.851"
    icd10_jp_who: "J95.8"
    snomed: "429271009"
    display_en: "Ventilator-associated pneumonia"
    display_ja: "人工呼吸器関連肺炎"
```

### `reference_data/hai_organisms.yaml`

CDC NHSN HAI Annual Report organism distributions. SNOMED codes for
each pathogen verified via tx.fhir.org `$expand` at implementation time.

```yaml
# Source: CDC NHSN annual HAI report organism distributions.
hai_organisms:
  clabsi:                       # top organisms ~80% coverage
    - {snomed: "...staph_aureus", weight: 0.20}
    - {snomed: "...cons", weight: 0.18}
    - {snomed: "...candida_spp", weight: 0.15}
    - {snomed: "...enterococcus", weight: 0.13}
    - {snomed: "...klebsiella", weight: 0.10}
    - {snomed: "...ecoli", weight: 0.10}
    - {snomed: "...pseudomonas", weight: 0.09}
    - {snomed: "...other", weight: 0.05}
  cauti:
    - {snomed: "...ecoli", weight: 0.27}
    - {snomed: "...candida_spp", weight: 0.18}
    - {snomed: "...enterococcus", weight: 0.16}
    - {snomed: "...klebsiella", weight: 0.13}
    - {snomed: "...pseudomonas", weight: 0.10}
    - {snomed: "...proteus_mirabilis", weight: 0.06}
    - {snomed: "...other", weight: 0.10}
  vap:
    - {snomed: "...staph_aureus", weight: 0.24}
    - {snomed: "...pseudomonas", weight: 0.17}
    - {snomed: "...klebsiella", weight: 0.10}
    - {snomed: "...ecoli", weight: 0.08}
    - {snomed: "...enterobacter", weight: 0.08}
    - {snomed: "...acinetobacter", weight: 0.05}
    - {snomed: "...stenotrophomonas", weight: 0.04}
    - {snomed: "...other", weight: 0.24}
```

All `"...placeholder"` strings replaced with verified SNOMED codes
during plan Task 1.

### `reference_data/hai_specimens.yaml`

```yaml
# Per-HAI culture specimen mapping. SNOMED + LOINC verified at plan Task 1.
hai_specimens:
  clabsi:
    specimen: "blood"
    specimen_snomed: "119297000"   # Blood specimen (verify)
    test_loinc: "600-7"            # Blood culture (verify NLM)
  cauti:
    specimen: "urine"
    specimen_snomed: "122575003"   # Urine specimen (verify)
    test_loinc: "630-4"            # Urine culture (verify)
  vap:
    specimen: "sputum"
    specimen_snomed: "119334006"   # Sputum specimen (verify)
    test_loinc: "624-7"            # Sputum culture (verify)
```

### `engine.py` — onset sampling

```python
def sample_hai_onset(
    device,                       # DeviceRecord
    rate_cfg: dict,
    rng: np.random.Generator,
) -> tuple[bool, int | None]:
    """Return (occurred, onset_day_offset) for this device.

    Returns (False, None) when no onset; (True, k) when onset on
    placement_date + k days. k is uniformly sampled from
    [2, line_days) per CDC's ≥48h HAI definition.

    Snapshot in-progress (device.removal_date is None) uses a
    conservative line_days = 7 (Phase 2 simplification).
    """
    placement = date.fromisoformat(device.placement_date)
    if device.removal_date:
        line_days = (date.fromisoformat(device.removal_date) - placement).days
    else:
        line_days = 7  # snapshot in-progress fallback
    if line_days < 2:
        return (False, None)
    per_day_risk = rate_cfg["per_day_risk"]
    cumulative = 1 - (1 - per_day_risk) ** line_days
    if rng.random() >= cumulative:
        return (False, None)
    onset_offset = int(rng.integers(2, line_days))
    return (True, onset_offset)


def _sample_organism(weights: list[dict], rng: np.random.Generator) -> str:
    """Weighted choice over (snomed, weight) pairs."""
    snomeds = [w["snomed"] for w in weights]
    p = np.array([w["weight"] for w in weights], dtype=float)
    p = p / p.sum()
    return rng.choice(snomeds, p=p)
```

### `enricher.py`

```python
def enrich_hai(ctx) -> None:
    rates = load_hai_rates()
    codes = load_hai_codes()
    organisms = load_hai_organisms()
    specimens = load_hai_specimens()
    _DEVICE_TO_HAI = {
        "cvc": "clabsi",
        "indwelling_catheter": "cauti",
        "mechanical_ventilator": "vap",
    }
    for rec in ctx.records:
        pid = _get(rec.patient, "patient_id", "") if _get(rec, "patient") else ""
        rng = np.random.default_rng(
            derive_sub_seed(ctx.master_seed,
                            ENRICHER_SEED_OFFSETS["hai"], pid or "x")
        )
        ext = _get(rec, "extensions", {}) or {}
        devices = ext.get("device", []) or []
        if not devices:
            continue
        hai_events: list[HAIEvent] = []
        for device in devices:
            hai_type = _DEVICE_TO_HAI.get(_get(device, "device_type"))
            if not hai_type:
                continue
            occurred, onset_offset = sample_hai_onset(
                device, rates[hai_type], rng,
            )
            if not occurred:
                continue
            organism = _sample_organism(organisms[hai_type], rng)
            hai_id = f"hai-{_get(device, 'encounter_id')}-{hai_type}-{len(hai_events)}"
            onset_date = _add_days(_get(device, 'placement_date'), onset_offset)
            ev = HAIEvent(
                hai_id=hai_id,
                encounter_id=_get(device, 'encounter_id'),
                hai_type=hai_type,
                source_device_id=_get(device, 'device_id'),
                icd10_code=codes[hai_type]["icd10_us_billable"],
                snomed_code=codes[hai_type]["snomed"],
                onset_date=onset_date,
                organism_snomed=organism,
                culture_specimen_id=f"spec-hai-{hai_id}",
            )
            hai_events.append(ev)
            _append_hai_culture(rec, ev, specimens[hai_type], onset_date)
        if hai_events:
            if isinstance(rec, dict):
                rec.setdefault("extensions", {})["hai"] = hai_events
            else:
                rec.extensions["hai"] = hai_events


def _append_hai_culture(rec, hai: HAIEvent, spec_cfg: dict, onset_date: str) -> None:
    """Append a MicrobiologyResult to record.microbiology so the
    existing _fhir_microbiology.py builder emits the culture."""
    from datetime import datetime, timedelta
    onset_dt = datetime.fromisoformat(onset_date)
    micro = MicrobiologyResult(
        encounter_id=hai.encounter_id,
        specimen=spec_cfg["specimen"],
        specimen_snomed=spec_cfg["specimen_snomed"],
        test_loinc=spec_cfg["test_loinc"],
        collected_datetime=onset_dt,
        reported_datetime=onset_dt + timedelta(days=2),
        growth=True,
        organism_snomed=hai.organism_snomed,
        quantitation="positive",
        susceptibilities=[],
    )
    if isinstance(rec, dict):
        rec.setdefault("microbiology", []).append(micro)
    else:
        rec.microbiology.append(micro)
```

### `_fhir_hai.py` builder

```python
def _build_hai_conditions(ctx: BundleContext) -> list[dict]:
    hais = _get(ctx.record, "extensions", {}).get("hai") or []
    if not hais:
        return []
    country = ctx.country
    lang = "ja" if country == "JP" else "en"
    out: list[dict] = []
    for h in hais:
        icd_internal = get_attr_or_key(h, "icd10_code", "")
        snomed = get_attr_or_key(h, "snomed_code", "")
        hai_id = get_attr_or_key(h, "hai_id", "")
        enc_id = get_attr_or_key(h, "encounter_id", "")
        onset_date = get_attr_or_key(h, "onset_date", "")
        if not icd_internal or not hai_id:
            continue
        icd_country = _map_diagnosis_code(icd_internal, country)
        icd_sys_key = "icd-10-cm" if country == "US" else "icd-10"
        icd_disp = code_lookup(icd_sys_key, icd_country, lang) or ""
        snomed_disp = code_lookup("snomed-ct", snomed, lang) or ""
        coding = [{
            "system": get_system_uri(icd_sys_key),
            "code": icd_country,
            "display": icd_disp,
        }]
        if snomed:
            coding.append({
                "system": get_system_uri("snomed-ct"),
                "code": snomed,
                "display": snomed_disp,
            })
        out.append({
            "resourceType": "Condition",
            "id": hai_id,
            "clinicalStatus": {"coding": [{
                "system": get_system_uri("hl7-condition-clinical"),
                "code": "active",
            }]},
            "verificationStatus": {"coding": [{
                "system": get_system_uri("hl7-condition-verification"),
                "code": "confirmed",
            }]},
            "category": [{"coding": [{
                "system": get_system_uri("hl7-condition-category"),
                "code": "encounter-diagnosis",
            }]}],
            "code": {"coding": coding, "text": icd_disp or snomed_disp},
            "subject": {"reference": f"Patient/{ctx.patient_id}"},
            "encounter": {"reference": f"Encounter/{enc_id}"},
            "onsetDateTime": onset_date,
        })
    return out
```

### Adapter wiring (`fhir_r4_adapter.py`)

- Import: `from clinosim.modules.output._fhir_hai import _build_hai_conditions  # noqa: F401`
- `_BUNDLE_BUILDERS.append(_build_hai_conditions)` after the 2 device
  builders.
- Note: HAI Conditions are appended to the existing Condition.ndjson —
  no new NDJSON file.

### `clinosim/simulator/seeding.py:ENRICHER_SEED_OFFSETS`

```python
ENRICHER_SEED_OFFSETS = {
    ...,
    "device": 0x4445,    # "DE" (PR-A)
    "hai":    0x4841,    # "HA" (PR-B)
}
```

`0x4841 = 18497`, distinct from all current offsets — module-level
duplicate assert in seeding.py will guard.

### ICD code mapping (existing infrastructure)

- US output: `icd10_us_billable` value → emitted directly as
  ICD-10-CM (`get_system_uri("icd-10-cm")`).
- JP output: `_map_diagnosis_code(icd_internal, "JP")` looks up
  `code_mapping_diagnosis/jp.yaml` to fold CM-granular T80.211A →
  WHO T80.2. Plan Task 1 adds three entries to that yaml.
- Both ICD-10-CM and WHO ICD-10 codes verified against authoritative
  sources (NLM ICD-10-CM API + WHO ICD-10 browser) at Task 1; SNOMED via
  tx.fhir.org `$expand`.

## Data flow

```
run_beta()
  └─ register_builtin_enrichers() post_records phase (ordered):
      ├─ ... existing enrichers ...
      ├─ device_enricher  (order=70) → extensions["device"]
      └─ hai_enricher     (order=80) ← new
          ├─ walks extensions["device"]
          ├─ per-device probability sampling
          ├─ appends HAIEvent → extensions["hai"]
          └─ appends MicrobiologyResult → record.microbiology

  ↓ output adapter
  fhir_r4_adapter._BUNDLE_BUILDERS
    ├─ ... existing builders ...
    ├─ _bb_microbiology         ← emits HAI cultures (no change)
    ├─ build_lab_panel_reports
    ├─ ... device builders ...
    └─ _build_hai_conditions    ← new

  → Condition.ndjson + Specimen.ndjson + Observation.ndjson +
    DiagnosticReport.ndjson now include HAI rows.
    No new NDJSON files.
```

## Verification — 3-axis DQR (gate)

US p=10000 + JP p=5000 seed=42. Results recorded in
`docs/reviews/2026-06-24-hai-module-data-quality-review.md`.

### Expected HAI counts (from PR-A DQR data)

PR-A US p=10000: 125 CVC × ~7 line-days, 125 catheter × ~7, 103 vent × ~7

- CLABSI: 125 × 7 × 0.0010 ≈ **0.9 expected** (Poisson 0–3 likely)
- CAUTI: 125 × 7 × 0.0014 ≈ **1.2 expected** (Poisson 0–3)
- VAP: 103 × 7 × 0.0015 ≈ **1.1 expected** (Poisson 0–3)

JP p=5000: ~7 of each device × ~13 line-days → ~0.1–0.2 each HAI
expected. **JP cohort with 0 HAI is acceptable** — rare event at small
n; Phase 3 may scale JP cohort to p=20000 for stable HAI sub-cohort.

### Axis 1 — structural

- Condition.id (HAI) uniqueness per-encounter scope: 100%
- Condition.subject + encounter refs resolve: 100%
- Dual coding present (ICD primary + SNOMED secondary): 100%
- US ICD-10-CM granular present; JP ICD-10 WHO 4-char present
- display ≠ code: 100%
- clinicalStatus="active", verificationStatus="confirmed",
  category="encounter-diagnosis": 100%
- onsetDateTime is ISO date format
- Linked culture (via record.microbiology) inherits PR3 `_fhir_microbiology.py`
  structural guarantees

### Axis 2 — clinical coherence

- HAI count within Poisson 2-sigma of expected per type (per-country)
- Every HAI's `source_device_id` references an actual DeviceRecord in
  the same patient's `extensions["device"]`
- onset_date ≥ device.placement_date + 2 days (CDC ≥48h rule)
- onset_date ≤ device.removal_date when present
- All HAIs link to ICU inpatient encounters (zero non-ICU HAI)
- Organism distribution per HAI type approximates
  `hai_organisms.yaml` weights (Chi-square within tolerance)
- Culture specimen type matches HAI type (CLABSI→blood, CAUTI→urine,
  VAP→sputum)

### Axis 3 — JP language quality

- US output: zero Japanese characters in HAI Condition + culture chain
- JP output: HAI Condition.code.text + display + culture organism
  display 100% Japanese
- JP ICD = WHO 4-char (T80.2, T83.5, J95.8); CM-granular leak 0
- JP organism displays from `snomed-ct.yaml` `ja:` fields (or US-only
  if no JP translation; reviewed in Task 1)

### byte-diff supplement

- Pre-existing NDJSON (all 11+) byte-identical between master and branch
- Exception: Condition / Specimen / Observation / DiagnosticReport
  show HAI-attributable additions; their pre-existing rows are
  byte-identical (only new HAI rows added — no shift of existing rows)
- New NDJSON files: 0 (HAI does not introduce a new resource type;
  Condition is reused)

## Tests

### Unit

- `tests/unit/test_hai_engine.py`
  - `sample_hai_onset`: deterministic given seed; non-zero per-day
    risk; line_days<2 short-circuit; snapshot in-progress fallback;
    onset_offset in [2, line_days)
  - `_sample_organism`: weighted distribution converges to YAML weights
    over many draws
  - Loaders: `load_hai_rates`, `load_hai_codes`, `load_hai_organisms`,
    `load_hai_specimens` return expected shapes
- `tests/unit/test_hai_enricher.py`
  - Offset registration: `ENRICHER_SEED_OFFSETS["hai"] == 0x4841`
  - Empty CIF noop
  - Patient with no devices → no HAI
  - Patient with device + forced 100% per-day-risk → exactly one HAI per
    device type (under deterministic rng)
  - Independent sub-seed isolation
  - HAI Event ↔ MicrobiologyResult bidirectional link
    (`source_device_id` → DeviceRecord, `culture_specimen_id`
    naming consistency)
- `tests/unit/test_hai_codes_coverage.py`
  - 3 ICD-10-CM + 3 WHO ICD-10 + 3 SNOMED HAI codes resolve via
    `code_lookup()` in en + ja

### Integration

- `tests/integration/test_hai_extension_persistence.py`
  - CIF JSON round-trip preserves `extensions["hai"]` as list of
    HAIEvent (dict / dataclass dual)
- `tests/integration/test_hai_fhir_output.py`
  - Small p=500 ICU cohort produces ≥1 HAI Condition with matched
    culture (Specimen + Observation + DR)
  - HAI Condition.subject refs resolve to Patient.id
  - HAI Condition.encounter refs resolve to Encounter.id
  - culture Specimen.id matches HAI's culture_specimen_id (or naming
    convention)

### e2e

- Existing e2e golden files may need refresh for the small set of seeds
  that happen to hit HAI onset. Refresh in the same PR.

## Documentation sync (in this PR)

| Doc | Update |
|---|---|
| `clinosim/modules/hai/README.md` | New; TEMPLATE_MODULE_README.md skeleton; Dependencies (types/codes + modules/device); Consumers (`simulator/enrichers.py`, `output/_fhir_hai.py`); cross-module device consumption documented; CDC NHSN baseline rates explained |
| `MODULES.md` | New `hai` row (enrichment layer, Tier: optional, Deps: types/codes + `modules/device`); 23 → 24 modules; dependency tree gains hai; sample call chain updated |
| `DESIGN.md` AD-56 entry | Continuation: "**PR-B hai module 2026-06-24** added Phase 2 of the device + HAI 4-PR series: `modules/hai/` (CLABSI / CAUTI / VAP onset sampling via CDC NHSN baseline; consumes PR-A `extensions['device']` line-days)..." |
| `CLAUDE.md` "Key directories" | Add `hai/  <- ★ CDC NHSN HAI sampling (CLABSI/CAUTI/VAP, AD-55 Module, PR-B)` under `device/` |
| `CLAUDE.md` "AD-55 enricher patterns" | sub-seed example updated with `0x4841` |
| `clinosim/modules/output/README.md` | Extensibility table: `_fhir_hai.py` row |
| `clinosim/simulator/seeding.py:ENRICHER_SEED_OFFSETS` | Add `"hai": 0x4841` |
| `TODO.md` | PR-B done entry + 4-PR series context update |
| `README.md` / `README.ja.md` | "Quality & Compliance" module list mention hai; Condition.ndjson description gains "+ HAI" annotation |
| `SCENARIO_FLAGS.md` | No change (HAI not a flag) |
| `docs/CONTRIBUTING-modules.md` | Optionally add "Cross-module consumption pattern" subsection documenting PR-A → PR-B as canonical example (Plan task 12 judgment) |

## 4-axis evaluation

| Axis | Score | Reasoning |
|---|---|---|
| データ品質 | ◎ | New Condition resource type contributions; dual ICD + SNOMED coding; culture-confirmed per CDC; CDC NHSN baseline directly calibratable |
| 臨床整合性 | ◎ | Line-days × per-day risk = actual epidemiologic mechanism; CDC ≥48h rule honored; device → HAI → culture chain consistent |
| メンテ性 (責任分解クリア) | ◎ | post_records enricher pattern + PR3 theme-per-file + existing `_fhir_microbiology.py` reuse (no new culture builder); cross-module dependency one-way (PR-A → PR-B) |
| コンセプト適切性 | ◎ | First clean implementation of cross-module enricher consumption pattern (foundation for Phase 3+); deliberately avoided scenario-flag and state-mutation alternatives; surgical observation-time computation only |

## Risk register

| Risk | Mitigation |
|---|---|
| ICD-10 / SNOMED codes fabricated (PR #80 lesson) | Plan Task 1 runs NLM ICD-10-CM API + WHO browser + tx.fhir.org `$expand` verification before any other file uses them. `# TODO: verify` markers in spec YAML enforce. |
| hai enricher leaks into main RNG | independent sub-seed (`0x4841`); byte-diff supplement catches |
| JP cohort 0 HAI at p=5000 (rare event) | Acceptable per `expected_counts` section; Phase 3 may scale JP cohort or compute confidence interval |
| organism SNOMED codes missing JP translation | Plan Task 1 SNOMED additions include `ja:` field; if any organism has no authoritative ja, fall back to en (acceptable for organism names, scientific Latin) |
| Snapshot in-progress device → no removal_date → unbounded sampling | `line_days = 7` conservative fallback in `sample_hai_onset` (documented in Non-goals §6) |
| HAI Condition + existing primary Condition collision on same Encounter | HAI Condition uses `hai-...` id namespace; primary Condition uses `cond-...` ; integration test confirms no id collision |

## Future work (Phase 3+ preview, non-binding)

- **Antibiotic empirical → narrow-spectrum order chain** when HAI fires
- **Susceptibility (S/I/R)** filling MicrobiologyResult.susceptibilities
  with antimicrobial resistance distributions
- **HAI-triggered observation-time WBC / CRP lift** (BNP-pattern surgical
  formula reading extensions["hai"] in derive_lab_values)
- **HAI mortality impact** on outcome benchmarks
- **Strict snapshot date integration** for snapshot-in-progress
  line-days
- **Repeat HAI per device** (currently at-most-one)

## Related links

- PR-A (#88): `modules/device` — `extensions["device"]` upstream
  - spec: `docs/superpowers/specs/2026-06-24-device-module-design.md`
  - plan: `docs/superpowers/plans/2026-06-24-device-module-pra.md`
  - DQR: `docs/reviews/2026-06-24-device-module-data-quality-review.md`
- PR3 (#87): `_fhir_observations.py` split — `_fhir_microbiology.py`
  established as standalone culture builder PR-B reuses
- AD-55 Base vs Module decision: `docs/CONTRIBUTING-modules.md`
  "判断: Base か Module か"
- AD-56 builder + enricher registry: `DESIGN.md` AD-56
- PR verification guide: `docs/CONTRIBUTING-modules.md` "PR 検証ガイド"
- SNOMED / NLM authoritative sources: memory `reference_tx_fhir_terminology`
- CDC NHSN annual reports:
  https://www.cdc.gov/nhsn/datastat (referenced in `hai_rates.yaml`)
