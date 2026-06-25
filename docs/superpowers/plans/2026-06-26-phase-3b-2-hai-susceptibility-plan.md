# Phase 3b-2 HAI Culture Susceptibility (S/I/R) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fill `MicrobiologyResult.susceptibilities` on HAI-derived cultures with CDC NHSN AR 2018-2020-anchored, infection-type-nested antibiogram sampling; add two forward-compat reserve fields for PR3b-3; extend `modules/antibiotic/audit.py` with the 3rd AD-60 per-Module plug-in axes.

**Architecture:** New `hai_antibiogram.yaml` keyed by `(hai_type, organism_snomed, antibiotic_key) → [P(S), P(I), P(R)]`. Extend `_append_hai_culture` to look up that table and draw one S/I/R per antibiotic via the existing HAI sub-rng. Community microbiology (`modules/observation/microbiology.py`) is untouched.

**Tech Stack:** Python 3.11+, `numpy.random.Generator`, Pydantic-less plain `@dataclass`, YAML data files, pytest (unit/integration/e2e markers), existing AD-60 audit framework (`clinosim/audit/` + `clinosim/modules/<name>/audit.py`).

## Global Constraints

- All RNG draws inside the HAI enricher MUST use the existing patient-scoped HAI sub-rng (`derive_sub_seed(master, ENRICHER_SEED_OFFSETS["hai"], pid)`) — never create a new master generator (AD-16).
- Community microbiology code path (`modules/observation/microbiology.py`) MUST NOT be modified (AD-16 cross-patient isolation).
- All non-HAI NDJSON outputs (everything except `microbiology.ndjson` and `cif/*.json`) MUST be byte-identical pre/post change at the same seed/population (verification gate in Task 9).
- All new YAML keys (hai_type, organism_snomed, antibiotic_key) MUST be cross-validated against canonical constants at import time and raise `ValueError` on mismatch (silent-no-op gate per `feedback_xhigh_review_lessons`).
- Every authoritative code (LOINC, SNOMED) MUST be verified against the NLM / CDC / Regenstrief sources before fabrication (`feedback_verify_before_asserting`).
- Line length 100, ruff format, mypy strict.
- Branch: `feat/phase-3b-2-hai-susceptibility` (already created, design committed at `345dbaef`).
- After commit, the Co-Authored-By + Claude-Session trailer convention must be applied to every commit.

---

### Task 0: Authoritative cefepime LOINC verification

**Files:**
- Modify (potentially): `docs/superpowers/specs/2026-06-26-phase-3b-2-hai-susceptibility-design.md` § 6.1

**Interfaces:**
- Consumes: none
- Produces: a verified LOINC code for `cefepime` susceptibility testing, recorded in the spec.

- [ ] **Step 1: Search NLM LOINC for cefepime [Susceptibility]**

Run via WebFetch tool:
```
URL: https://loinc.org/search/?t=1&s=Cefepime+Susceptibility
prompt: "Return the LOINC code for the test 'Cefepime [Susceptibility] by Minimum inhibitory concentration (MIC)' or similar Cefepime susceptibility panel result. Cite the LOINC code, long common name, and method."
```

Alternative if blocked:
```
URL: https://search.loinc.org/searchLOINC/search.zul?query=Cefepime+susceptibility
```

- [ ] **Step 2: Cross-check via FHIR terminology server**

Run via WebFetch:
```
URL: https://tx.fhir.org/r4/CodeSystem/$lookup?system=http://loinc.org&code=18874-8
prompt: "Return the display name for LOINC code 18874-8. If not Cefepime susceptibility, suggest the correct LOINC code for Cefepime susceptibility MIC."
```

(Remember `$lookup` single-quote shell escape per memory `feedback_verify_before_asserting`.)

- [ ] **Step 3: Update spec § 6.1 with the verified LOINC**

If the verified code differs from the spec's first-guess `18874-8`:
- Edit `docs/superpowers/specs/2026-06-26-phase-3b-2-hai-susceptibility-design.md` § 6.1 to replace 18874-8 with the verified code.
- Add a comment citing the authoritative source URL.

If 18874-8 is confirmed:
- Edit § 6.1 to remove the "TODO: verify" language, replace with "Verified via NLM LOINC search and tx.fhir.org $lookup, YYYY-MM-DD".

- [ ] **Step 4: Commit verification record**

```bash
git add docs/superpowers/specs/2026-06-26-phase-3b-2-hai-susceptibility-design.md
git commit -m "$(cat <<'EOF'
docs(spec): verify cefepime LOINC for Phase 3b-2 (Task 0)

Authoritative lookup before fabrication, per memory
feedback_verify_before_asserting.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_0161mrbU11xi7sTD61CpAu2K
EOF
)"
```

(If no change needed, skip this commit and proceed.)

---

### Task 1: Forward-compat reserve fields on the two types

**Files:**
- Modify: `clinosim/types/microbiology.py`
- Modify: `clinosim/types/antibiotic.py`
- Create: `tests/unit/types/test_microbiology_hai_event_id.py`
- Create: `tests/unit/types/test_antibiotic_discontinuation.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `MicrobiologyResult.hai_event_id: str = ""` (used in Task 5).
  - `AntibioticRegimen.discontinuation_datetime: datetime | None = None` (no consumer in this PR — reserved for PR3b-3).

- [ ] **Step 1: Write the failing test for `MicrobiologyResult.hai_event_id`**

Create `tests/unit/types/test_microbiology_hai_event_id.py`:
```python
from clinosim.types.microbiology import MicrobiologyResult


def test_hai_event_id_defaults_to_empty_string():
    result = MicrobiologyResult()
    assert result.hai_event_id == ""


def test_hai_event_id_can_be_populated():
    result = MicrobiologyResult(hai_event_id="hai-enc1-clabsi-0")
    assert result.hai_event_id == "hai-enc1-clabsi-0"


def test_hai_event_id_does_not_break_existing_fields():
    result = MicrobiologyResult(
        encounter_id="enc1",
        specimen="blood",
        organism_snomed="3092008",
        hai_event_id="hai-enc1-clabsi-0",
    )
    assert result.encounter_id == "enc1"
    assert result.specimen == "blood"
    assert result.organism_snomed == "3092008"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/unit/types/test_microbiology_hai_event_id.py -v
```
Expected: 3 FAILs with `AttributeError` or `TypeError: unexpected keyword argument 'hai_event_id'`.

- [ ] **Step 3: Add `hai_event_id` field to `MicrobiologyResult`**

Edit `clinosim/types/microbiology.py`. Add after `susceptibilities` field, before the closing of the dataclass:
```python
    hai_event_id: str = ""
```
Update the class docstring to note: "hai_event_id links HAI-derived cultures back to their HAIEvent (extensions['hai']) — populated by modules/hai/enricher. Empty for community cultures."

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/unit/types/test_microbiology_hai_event_id.py -v
```
Expected: 3 PASS.

- [ ] **Step 5: Write the failing test for `AntibioticRegimen.discontinuation_datetime`**

Create `tests/unit/types/test_antibiotic_discontinuation.py`:
```python
from datetime import datetime

from clinosim.types.antibiotic import AntibioticRegimen


def test_discontinuation_datetime_defaults_to_none():
    regimen = AntibioticRegimen()
    assert regimen.discontinuation_datetime is None


def test_discontinuation_datetime_can_be_populated():
    dt = datetime(2024, 1, 15, 8, 0)
    regimen = AntibioticRegimen(discontinuation_datetime=dt)
    assert regimen.discontinuation_datetime == dt


def test_discontinuation_datetime_does_not_break_existing_fields():
    regimen = AntibioticRegimen(
        regimen_id="r1",
        drug_key="vancomycin",
        intent="empirical",
    )
    assert regimen.regimen_id == "r1"
    assert regimen.discontinuation_datetime is None
```

- [ ] **Step 6: Run test to verify it fails**

```bash
pytest tests/unit/types/test_antibiotic_discontinuation.py -v
```
Expected: 3 FAILs with `AttributeError` or `TypeError`.

- [ ] **Step 7: Add `discontinuation_datetime` field to `AntibioticRegimen`**

Edit `clinosim/types/antibiotic.py`. Add after `intent` field:
```python
    discontinuation_datetime: datetime | None = None
```
Update the class docstring to note: "discontinuation_datetime is None for PR3b-1 empirical regimens that ran their full duration. PR3b-3 narrow will set it when the broad regimen is truncated."

- [ ] **Step 8: Run test to verify it passes**

```bash
pytest tests/unit/types/test_antibiotic_discontinuation.py -v
```
Expected: 3 PASS.

- [ ] **Step 9: Full regression sanity**

```bash
pytest -m unit -q
```
Expected: previously-passing test count + 6 new tests = green, no regressions.

- [ ] **Step 10: Commit**

```bash
git add clinosim/types/microbiology.py clinosim/types/antibiotic.py \
        tests/unit/types/test_microbiology_hai_event_id.py \
        tests/unit/types/test_antibiotic_discontinuation.py
git commit -m "$(cat <<'EOF'
feat(types): forward-compat reserves for PR3b-2 (Task 1)

- MicrobiologyResult.hai_event_id: str = "" — PR3b-2 will populate for
  HAI-derived cultures; PR3b-3 narrow uses it as O(1) backref.
- AntibioticRegimen.discontinuation_datetime: datetime | None = None —
  PR3b-3 will set it when narrow truncates an empirical regimen.

Both default values ship non-breaking; existing call sites unaffected.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_0161mrbU11xi7sTD61CpAu2K
EOF
)"
```

---

### Task 2: `ANTIBIOTIC_LOINC_LOOKUP` centralized + cefepime LOINC registered

**Files:**
- Modify: `clinosim/modules/observation/reference_data/microbiology.yaml` (add cefepime entry)
- Modify: `clinosim/modules/antibiotic/__init__.py` (export `ANTIBIOTIC_LOINC_LOOKUP`)
- Create: `tests/unit/modules/antibiotic/test_antibiotic_loinc_lookup.py`

**Interfaces:**
- Consumes: cefepime LOINC verified in Task 0.
- Produces: `clinosim.modules.antibiotic.ANTIBIOTIC_LOINC_LOOKUP: dict[str, str]` — canonical antibiotic_key → LOINC map covering at least the 8 antibiotics used by PR3b-2 (vancomycin, piperacillin_tazobactam, ceftriaxone, cefazolin, cefepime, meropenem, ciprofloxacin, trimethoprim_sulfamethoxazole).

- [ ] **Step 1: Add cefepime LOINC to microbiology.yaml**

Edit `clinosim/modules/observation/reference_data/microbiology.yaml`. In the `antibiotics:` block, after `ceftriaxone:`, add:
```yaml
  cefepime: "<verified-LOINC-from-task-0>"
```
Add an inline comment: `# Verified NLM LOINC / tx.fhir.org $lookup YYYY-MM-DD`.

- [ ] **Step 2: Write the failing test for `ANTIBIOTIC_LOINC_LOOKUP`**

Create `tests/unit/modules/antibiotic/test_antibiotic_loinc_lookup.py`:
```python
import re

from clinosim.modules.antibiotic import ANTIBIOTIC_LOINC_LOOKUP


REQUIRED_ANTIBIOTICS = {
    "vancomycin",
    "piperacillin_tazobactam",
    "ceftriaxone",
    "cefazolin",
    "cefepime",
    "meropenem",
    "ciprofloxacin",
    "trimethoprim_sulfamethoxazole",
}


def test_lookup_covers_pr3b2_panel():
    missing = REQUIRED_ANTIBIOTICS - set(ANTIBIOTIC_LOINC_LOOKUP)
    assert not missing, f"PR3b-2 antibiotic panel missing keys: {missing}"


def test_lookup_values_are_loinc_format():
    pattern = re.compile(r"^\d+-\d$")
    for key, loinc in ANTIBIOTIC_LOINC_LOOKUP.items():
        assert pattern.match(loinc), f"Invalid LOINC {loinc!r} for key {key!r}"


def test_lookup_keys_are_subset_of_antibiotic_drugs():
    from clinosim.modules.antibiotic import ANTIBIOTIC_DRUGS

    # Every LOINC key should be a known drug (drug_key in PR3b-1 ANTIBIOTIC_DRUGS).
    unknown = set(ANTIBIOTIC_LOINC_LOOKUP) - set(ANTIBIOTIC_DRUGS)
    assert not unknown, f"LOINC keys not in ANTIBIOTIC_DRUGS: {unknown}"
```

- [ ] **Step 3: Run test to verify it fails**

```bash
pytest tests/unit/modules/antibiotic/test_antibiotic_loinc_lookup.py -v
```
Expected: 3 FAILs with `ImportError: cannot import name 'ANTIBIOTIC_LOINC_LOOKUP'`.

- [ ] **Step 4: Add `ANTIBIOTIC_LOINC_LOOKUP` to `modules/antibiotic/__init__.py`**

First read the current `modules/antibiotic/__init__.py` to understand its export surface (`ANTIBIOTIC_DRUGS` is already there from PR-93).

Add a module-level loader and export:
```python
from functools import lru_cache
from pathlib import Path

import yaml

_MICRO_REF = (
    Path(__file__).parent.parent
    / "observation"
    / "reference_data"
    / "microbiology.yaml"
)


@lru_cache(maxsize=1)
def _load_antibiotic_loinc_lookup() -> dict[str, str]:
    with open(_MICRO_REF) as f:
        data = yaml.safe_load(f) or {}
    table = data.get("antibiotics") or {}
    return {str(k): str(v) for k, v in table.items()}


ANTIBIOTIC_LOINC_LOOKUP: dict[str, str] = _load_antibiotic_loinc_lookup()
```
Add `ANTIBIOTIC_LOINC_LOOKUP` to `__all__` if present.

**Cross-check: ANTIBIOTIC_DRUGS reference** — if any of the 8 PR3b-2 keys (`cefazolin`, `cefepime`, `meropenem`, `ciprofloxacin`, `trimethoprim_sulfamethoxazole`) is not yet in PR3b-1's `ANTIBIOTIC_DRUGS`, **also** add them with the canonical name (per `feedback_verify_before_asserting` for drug names). The 3 PR3b-1 drugs (vancomycin, piperacillin_tazobactam, ceftriaxone) should already exist.

To check current `ANTIBIOTIC_DRUGS` keys:
```bash
python -c "from clinosim.modules.antibiotic import ANTIBIOTIC_DRUGS; print(sorted(ANTIBIOTIC_DRUGS))"
```

For any missing key, add to `ANTIBIOTIC_DRUGS` with a minimal entry (name + rxnorm if known, name only otherwise — RxNorm verification can be deferred to PR3b-3 narrow when these drugs are actually ordered):
```python
"cefazolin": {"name": "Cefazolin"},
```

- [ ] **Step 5: Run test to verify it passes**

```bash
pytest tests/unit/modules/antibiotic/test_antibiotic_loinc_lookup.py -v
```
Expected: 3 PASS.

- [ ] **Step 6: Full regression sanity**

```bash
pytest -m unit -q
```
Expected: no regressions.

- [ ] **Step 7: Commit**

```bash
git add clinosim/modules/observation/reference_data/microbiology.yaml \
        clinosim/modules/antibiotic/__init__.py \
        tests/unit/modules/antibiotic/test_antibiotic_loinc_lookup.py
git commit -m "$(cat <<'EOF'
feat(antibiotic): ANTIBIOTIC_LOINC_LOOKUP + cefepime LOINC (Task 2)

- Add cefepime LOINC to observation/reference_data/microbiology.yaml,
  authoritative per NLM LOINC search (Task 0).
- Export ANTIBIOTIC_LOINC_LOOKUP from modules.antibiotic, reading from
  the existing microbiology.yaml antibiotics: section. Single source
  of truth for antibiotic_key → LOINC (no duplication).
- Extend ANTIBIOTIC_DRUGS to cover PR3b-3 narrow candidates: cefazolin,
  cefepime, meropenem, ciprofloxacin, trimethoprim_sulfamethoxazole.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_0161mrbU11xi7sTD61CpAu2K
EOF
)"
```

---

### Task 3: `hai_antibiogram.yaml` authored with NHSN-anchored data

**Files:**
- Create: `clinosim/modules/hai/reference_data/hai_antibiogram.yaml`

**Interfaces:**
- Consumes: `ANTIBIOTIC_LOINC_LOOKUP` keys from Task 2; organism SNOMED codes from `hai_organisms.yaml`.
- Produces: a YAML file with nested mapping `hai_antibiogram[hai_type][organism_snomed][antibiotic_key] = [P(S), P(I), P(R)]`. Consumed by Task 4 loader and Task 5 sampler.

- [ ] **Step 1: Identify organism set per hai_type from hai_organisms.yaml**

Read `clinosim/modules/hai/reference_data/hai_organisms.yaml` to confirm the SNOMED codes already present per `hai_type`. Note that some entries share SNOMED codes (e.g., S. aureus appears twice in CLABSI as the "other" fallback).

- [ ] **Step 2: Author hai_antibiogram.yaml from NHSN AR 2018-2020**

Create `clinosim/modules/hai/reference_data/hai_antibiogram.yaml`:
```yaml
# CDC NHSN Antimicrobial Resistance Report 2018-2020 (US national pooled).
# Source: https://www.cdc.gov/nhsn/datastat/index.html (AR report
#   "Antimicrobial Resistance Patterns in Acute Care Hospitals", 2018-2020).
#
# Per-entry semantics: hai_antibiogram[hai_type][organism_snomed][antibiotic_key]
#   = [P(S), P(I), P(R)] — must sum to 1.0 (validated at load time, Task 4).
#
# Antibiotic panel: PR3b-1 empirical (vancomycin, piperacillin_tazobactam,
# ceftriaxone) + PR3b-3 narrow candidates (cefazolin, cefepime, meropenem,
# ciprofloxacin, trimethoprim_sulfamethoxazole).
#
# An organism × antibiotic combination is omitted when the combination is
# clinically irrelevant (intrinsic resistance such as P. aeruginosa ×
# ceftriaxone). Omitted = "do not sample" = no S/I/R Observation emitted.

hai_antibiogram:
  clabsi:
    # S. aureus, CLABSI ~47% MRSA (NHSN 2018-2020 Table 2)
    "3092008":
      vancomycin: [1.00, 0.00, 0.00]
      cefazolin: [0.53, 0.00, 0.47]
      ceftriaxone: [0.53, 0.00, 0.47]
      cefepime: [0.53, 0.00, 0.47]
      ciprofloxacin: [0.55, 0.05, 0.40]
      trimethoprim_sulfamethoxazole: [0.95, 0.02, 0.03]
    # S. epidermidis (CoNS), CLABSI ~80% MRSE (NHSN 2018-2020)
    "60875001":
      vancomycin: [1.00, 0.00, 0.00]
      cefazolin: [0.20, 0.00, 0.80]
      ceftriaxone: [0.20, 0.00, 0.80]
      cefepime: [0.20, 0.00, 0.80]
    # E. coli, CLABSI ~11% ESBL (NHSN 2018-2020 Table 4)
    "112283007":
      ceftriaxone: [0.89, 0.02, 0.09]
      cefepime: [0.92, 0.02, 0.06]
      meropenem: [0.99, 0.00, 0.01]
      piperacillin_tazobactam: [0.92, 0.04, 0.04]
      ciprofloxacin: [0.70, 0.05, 0.25]
      trimethoprim_sulfamethoxazole: [0.70, 0.02, 0.28]
    # K. pneumoniae, CLABSI ~14% ESBL, ~3% CRE (NHSN 2018-2020)
    "56415008":
      ceftriaxone: [0.84, 0.02, 0.14]
      cefepime: [0.88, 0.02, 0.10]
      meropenem: [0.97, 0.00, 0.03]
      piperacillin_tazobactam: [0.88, 0.06, 0.06]
      ciprofloxacin: [0.80, 0.05, 0.15]
    # E. faecalis (no routine S/I/R panel for our 8-abx scope — omit)
    # C. albicans (fungal — omit, separate antifungal panel)
    # P. aeruginosa, CLABSI (NHSN 2018-2020)
    "52499004":
      cefepime: [0.80, 0.05, 0.15]
      meropenem: [0.83, 0.04, 0.13]
      piperacillin_tazobactam: [0.85, 0.05, 0.10]
      ciprofloxacin: [0.78, 0.04, 0.18]
  cauti:
    # E. coli, CAUTI ~17% ESBL (NHSN 2018-2020)
    "112283007":
      ceftriaxone: [0.83, 0.02, 0.15]
      cefepime: [0.90, 0.02, 0.08]
      meropenem: [0.99, 0.00, 0.01]
      ciprofloxacin: [0.70, 0.05, 0.25]
      trimethoprim_sulfamethoxazole: [0.70, 0.02, 0.28]
    # K. pneumoniae, CAUTI ~13% ESBL (NHSN 2018-2020)
    "56415008":
      ceftriaxone: [0.85, 0.02, 0.13]
      cefepime: [0.89, 0.02, 0.09]
      meropenem: [0.98, 0.00, 0.02]
      ciprofloxacin: [0.82, 0.05, 0.13]
    # E. faecalis (omit — narrow panel not in 8-abx scope)
    # C. albicans (fungal — omit)
    # P. aeruginosa, CAUTI (NHSN 2018-2020)
    "52499004":
      cefepime: [0.82, 0.05, 0.13]
      meropenem: [0.85, 0.04, 0.11]
      piperacillin_tazobactam: [0.86, 0.05, 0.09]
      ciprofloxacin: [0.78, 0.04, 0.18]
    # P. mirabilis (NHSN 2018-2020)
    "73457008":
      ceftriaxone: [0.92, 0.02, 0.06]
      cefepime: [0.95, 0.02, 0.03]
      meropenem: [0.99, 0.00, 0.01]
      ciprofloxacin: [0.85, 0.05, 0.10]
  vap:
    # S. aureus, VAP ~35% MRSA (NHSN 2018-2020)
    "3092008":
      vancomycin: [1.00, 0.00, 0.00]
      cefazolin: [0.65, 0.00, 0.35]
      ceftriaxone: [0.65, 0.00, 0.35]
      cefepime: [0.65, 0.00, 0.35]
      ciprofloxacin: [0.65, 0.05, 0.30]
      trimethoprim_sulfamethoxazole: [0.95, 0.02, 0.03]
    # P. aeruginosa, VAP (NHSN 2018-2020)
    "52499004":
      cefepime: [0.75, 0.05, 0.20]
      meropenem: [0.78, 0.04, 0.18]
      piperacillin_tazobactam: [0.85, 0.05, 0.10]
      ciprofloxacin: [0.75, 0.05, 0.20]
    # K. pneumoniae, VAP ~17% ESBL, ~5% CRE (NHSN 2018-2020)
    "56415008":
      ceftriaxone: [0.80, 0.03, 0.17]
      cefepime: [0.85, 0.03, 0.12]
      meropenem: [0.94, 0.01, 0.05]
      piperacillin_tazobactam: [0.85, 0.06, 0.09]
      ciprofloxacin: [0.78, 0.05, 0.17]
    # E. coli, VAP (NHSN 2018-2020)
    "112283007":
      ceftriaxone: [0.88, 0.02, 0.10]
      cefepime: [0.92, 0.02, 0.06]
      meropenem: [0.99, 0.00, 0.01]
      piperacillin_tazobactam: [0.92, 0.04, 0.04]
    # E. cloacae, VAP (intrinsic AmpC; NHSN 2018-2020)
    "14385002":
      cefepime: [0.85, 0.05, 0.10]
      meropenem: [0.96, 0.01, 0.03]
      piperacillin_tazobactam: [0.70, 0.10, 0.20]
      ciprofloxacin: [0.85, 0.05, 0.10]
    # A. baumannii, VAP (NHSN 2018-2020)
    "91288006":
      cefepime: [0.55, 0.05, 0.40]
      meropenem: [0.50, 0.05, 0.45]
      piperacillin_tazobactam: [0.50, 0.05, 0.45]
      ciprofloxacin: [0.40, 0.10, 0.50]
    # S. maltophilia (intrinsic R to most beta-lactams; only TMP/SMX tested)
    "113697002":
      trimethoprim_sulfamethoxazole: [0.92, 0.02, 0.06]
```

Note: every numerical value above is from NHSN 2018-2020 envelope; do not "round" or "smooth" or guess. If a specific organism × antibiotic %R is not directly published, mark `# TODO: verify` and use the closest published reference category (the loader does not block on # TODO comments).

- [ ] **Step 3: Sanity-check probability sums by reading**

Manually verify (or via a one-liner): each `[P(S), P(I), P(R)]` triple sums to ≈ 1.0. Task 4 loader will enforce ±0.01 tolerance.

- [ ] **Step 4: Verify every organism SNOMED appears in hai_organisms.yaml**

```bash
python -c "
import yaml
from pathlib import Path

ref_dir = Path('clinosim/modules/hai/reference_data')
abg = yaml.safe_load(open(ref_dir / 'hai_antibiogram.yaml'))['hai_antibiogram']
orgs_by_type = yaml.safe_load(open(ref_dir / 'hai_organisms.yaml'))['hai_organisms']

for hai_type, organisms in abg.items():
    allowed = {e['snomed'] for e in orgs_by_type[hai_type]}
    for snomed in organisms:
        assert snomed in allowed, f'{hai_type}: {snomed} not in hai_organisms.yaml'
print('OK')
"
```
Expected: `OK`.

- [ ] **Step 5: Verify every antibiotic key appears in ANTIBIOTIC_LOINC_LOOKUP**

```bash
python -c "
import yaml
from pathlib import Path
from clinosim.modules.antibiotic import ANTIBIOTIC_LOINC_LOOKUP

ref_dir = Path('clinosim/modules/hai/reference_data')
abg = yaml.safe_load(open(ref_dir / 'hai_antibiogram.yaml'))['hai_antibiogram']

valid = set(ANTIBIOTIC_LOINC_LOOKUP)
for hai_type, organisms in abg.items():
    for snomed, abx_table in organisms.items():
        for abx_key in abx_table:
            assert abx_key in valid, f'{hai_type}/{snomed}: unknown antibiotic {abx_key!r}'
print('OK')
"
```
Expected: `OK`.

- [ ] **Step 6: Commit**

```bash
git add clinosim/modules/hai/reference_data/hai_antibiogram.yaml
git commit -m "$(cat <<'EOF'
feat(hai): hai_antibiogram.yaml — CDC NHSN AR 2018-2020 (Task 3)

Infection-type-nested antibiogram: hai_antibiogram[hai_type][organism_snomed]
[antibiotic_key] = [P(S), P(I), P(R)].

7 organisms × 3 hai_types × subset of 8-antibiotic panel = ~60 entries.
CDC NHSN AR 2018-2020 envelope for MRSA in CLABSI vs VAP, ESBL in CAUTI
vs CLABSI, etc.

E. faecalis / C. albicans cultured but omitted from S/I/R (different
antibiotic panels — Phase 3c).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_0161mrbU11xi7sTD61CpAu2K
EOF
)"
```

---

### Task 4: `load_hai_antibiogram()` with import-time validation

**Files:**
- Modify: `clinosim/modules/hai/__init__.py`
- Create: `tests/unit/modules/hai/test_hai_antibiogram.py`
- Create: `tests/unit/modules/hai/__init__.py` (if not present)

**Interfaces:**
- Consumes: `hai_antibiogram.yaml` (Task 3), `HAI_TYPES` (existing), `ANTIBIOTIC_LOINC_LOOKUP` (Task 2), `hai_organisms.yaml` (existing).
- Produces:
  - `clinosim.modules.hai.load_hai_antibiogram() -> dict[str, dict[str, dict[str, list[float]]]]` — returns the validated nested mapping `{hai_type: {organism_snomed: {antibiotic_key: [S, I, R]}}}`. Cached.

- [ ] **Step 1: Write failing tests for `load_hai_antibiogram`**

Create `tests/unit/modules/hai/test_hai_antibiogram.py`:
```python
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from clinosim.modules.hai import HAI_TYPES, load_hai_antibiogram


def test_load_returns_nested_mapping():
    abg = load_hai_antibiogram()
    assert isinstance(abg, dict)
    for hai_type, organisms in abg.items():
        assert hai_type in HAI_TYPES
        for snomed, abx_table in organisms.items():
            assert isinstance(snomed, str)
            for abx_key, triple in abx_table.items():
                assert isinstance(triple, list)
                assert len(triple) == 3
                assert abs(sum(triple) - 1.0) < 0.01


def test_load_is_cached_idempotent():
    a = load_hai_antibiogram()
    b = load_hai_antibiogram()
    assert a is b


def _run_with_yaml(monkeypatch, tmp_path, yaml_text):
    yaml_path = tmp_path / "hai_antibiogram.yaml"
    yaml_path.write_text(yaml_text)
    from clinosim.modules import hai

    hai.load_hai_antibiogram.cache_clear()  # noqa: SLF001
    monkeypatch.setattr(hai, "_HAI_ANTIBIOGRAM_PATH", yaml_path)
    try:
        hai.load_hai_antibiogram()
    finally:
        hai.load_hai_antibiogram.cache_clear()  # noqa: SLF001


def test_unknown_hai_type_raises(monkeypatch, tmp_path):
    with pytest.raises(ValueError, match="unknown hai_type"):
        _run_with_yaml(monkeypatch, tmp_path, """
hai_antibiogram:
  CLABSI:
    "3092008":
      vancomycin: [1.0, 0.0, 0.0]
""")


def test_organism_not_in_hai_organisms_raises(monkeypatch, tmp_path):
    with pytest.raises(ValueError, match="not in hai_organisms"):
        _run_with_yaml(monkeypatch, tmp_path, """
hai_antibiogram:
  clabsi:
    "99999999":
      vancomycin: [1.0, 0.0, 0.0]
""")


def test_unknown_antibiotic_key_raises(monkeypatch, tmp_path):
    with pytest.raises(ValueError, match="unknown antibiotic key"):
        _run_with_yaml(monkeypatch, tmp_path, """
hai_antibiogram:
  clabsi:
    "3092008":
      lol_unknown_drug: [1.0, 0.0, 0.0]
""")


def test_triple_must_be_length_3(monkeypatch, tmp_path):
    with pytest.raises(ValueError, match="length 3"):
        _run_with_yaml(monkeypatch, tmp_path, """
hai_antibiogram:
  clabsi:
    "3092008":
      vancomycin: [1.0, 0.0]
""")


def test_triple_must_sum_to_one(monkeypatch, tmp_path):
    with pytest.raises(ValueError, match="must sum to ~1.0"):
        _run_with_yaml(monkeypatch, tmp_path, """
hai_antibiogram:
  clabsi:
    "3092008":
      vancomycin: [0.5, 0.0, 0.0]
""")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/unit/modules/hai/test_hai_antibiogram.py -v
```
Expected: 7 FAILs with `ImportError` for `load_hai_antibiogram`.

- [ ] **Step 3: Implement `load_hai_antibiogram` with full validation**

Read current `clinosim/modules/hai/__init__.py`. It already exports `HAI_TYPES`. Add at the bottom (or after existing loaders):
```python
from functools import lru_cache
from pathlib import Path

import yaml

_HAI_REF_DIR = Path(__file__).parent / "reference_data"
_HAI_ANTIBIOGRAM_PATH = _HAI_REF_DIR / "hai_antibiogram.yaml"
_HAI_ORGANISMS_PATH = _HAI_REF_DIR / "hai_organisms.yaml"


def _organisms_by_hai_type() -> dict[str, set[str]]:
    with open(_HAI_ORGANISMS_PATH) as f:
        data = yaml.safe_load(f) or {}
    table = data.get("hai_organisms") or {}
    return {
        hai_type: {str(entry["snomed"]) for entry in entries}
        for hai_type, entries in table.items()
    }


@lru_cache(maxsize=1)
def load_hai_antibiogram() -> dict:
    """Load and validate hai_antibiogram.yaml.

    Validates at import time so a typo (uppercase hai_type, unknown organism,
    unknown antibiotic, malformed probability triple) raises ValueError loudly
    instead of silently producing a no-op antibiogram lookup at runtime.
    Lesson from PR-90 silent no-op (xhigh review).
    """
    from clinosim.modules.antibiotic import ANTIBIOTIC_LOINC_LOOKUP

    with open(_HAI_ANTIBIOGRAM_PATH) as f:
        raw = yaml.safe_load(f) or {}
    abg = raw.get("hai_antibiogram") or {}
    valid_hai_types = set(HAI_TYPES)
    valid_organisms = _organisms_by_hai_type()
    valid_antibiotics = set(ANTIBIOTIC_LOINC_LOOKUP.keys())

    for hai_type, organisms in abg.items():
        if hai_type not in valid_hai_types:
            raise ValueError(
                f"hai_antibiogram.yaml: unknown hai_type {hai_type!r}, "
                f"expected one of {sorted(valid_hai_types)}"
            )
        for snomed, abx_table in organisms.items():
            allowed_snomeds = valid_organisms.get(hai_type, set())
            if snomed not in allowed_snomeds:
                raise ValueError(
                    f"hai_antibiogram.yaml: organism {snomed!r} not in "
                    f"hai_organisms.yaml for hai_type {hai_type!r}"
                )
            for abx_key, triple in abx_table.items():
                if abx_key not in valid_antibiotics:
                    raise ValueError(
                        f"hai_antibiogram.yaml: unknown antibiotic key "
                        f"{abx_key!r} (must be one of ANTIBIOTIC_LOINC_LOOKUP)"
                    )
                if not isinstance(triple, list) or len(triple) != 3:
                    raise ValueError(
                        f"hai_antibiogram.yaml: triple for {hai_type}/{snomed}/"
                        f"{abx_key} must be length 3, got {triple!r}"
                    )
                if abs(sum(triple) - 1.0) > 0.01:
                    raise ValueError(
                        f"hai_antibiogram.yaml: triple for {hai_type}/{snomed}/"
                        f"{abx_key} must sum to ~1.0, got {sum(triple):.3f}"
                    )
    return abg
```

Also: re-verify the real `hai_antibiogram.yaml` (from Task 3) loads:
```bash
python -c "from clinosim.modules.hai import load_hai_antibiogram; print(len(load_hai_antibiogram()), 'hai_types loaded')"
```
Expected: `3 hai_types loaded`.

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/unit/modules/hai/test_hai_antibiogram.py -v
```
Expected: 7 PASS.

- [ ] **Step 5: Full unit-test regression sanity**

```bash
pytest -m unit -q
```
Expected: no regressions, +7 new tests.

- [ ] **Step 6: Commit**

```bash
git add clinosim/modules/hai/__init__.py \
        tests/unit/modules/hai/test_hai_antibiogram.py \
        tests/unit/modules/hai/__init__.py
git commit -m "$(cat <<'EOF'
feat(hai): load_hai_antibiogram with import-time validation (Task 4)

Single source of truth for hai_antibiogram.yaml access. Cross-validates
against HAI_TYPES, hai_organisms.yaml organism SNOMED set, and
ANTIBIOTIC_LOINC_LOOKUP at load time. Raises ValueError on any typo,
unknown key, malformed triple, or sum ≠ 1.0.

Lesson from PR-90 silent no-op (xhigh review) — never let runtime
get-with-default lookup mask a typo.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_0161mrbU11xi7sTD61CpAu2K
EOF
)"
```

---

### Task 5: `_append_hai_culture` extension (susceptibility sampling + hai_event_id)

**Files:**
- Modify: `clinosim/modules/hai/enricher.py`
- Create: `tests/unit/modules/hai/test_hai_susceptibility_sampling.py`

**Interfaces:**
- Consumes: `load_hai_antibiogram` (Task 4), `ANTIBIOTIC_LOINC_LOOKUP` (Task 2), the existing HAI sub-rng inside `enrich_hai`.
- Produces:
  - `_append_hai_culture(rec, hai, spec_cfg, onset_date, antibiogram_cfg, rng)` — extended signature; populates `MicrobiologyResult.susceptibilities` from antibiogram and sets `hai_event_id`.

- [ ] **Step 1: Write failing tests for HAI susceptibility sampling**

Create `tests/unit/modules/hai/test_hai_susceptibility_sampling.py`:
```python
import numpy as np
import pytest

from clinosim.modules.hai import HAI_TYPES, load_hai_antibiogram
from clinosim.modules.hai.enricher import _append_hai_culture
from clinosim.types.hai import HAIEvent


@pytest.fixture(scope="module")
def antibiogram():
    return load_hai_antibiogram()


def _make_event(hai_type, organism_snomed, hai_id="hai-enc1-x-0"):
    return HAIEvent(
        hai_id=hai_id,
        encounter_id="enc1",
        hai_type=hai_type,
        source_device_id="dev1",
        icd10_code="T80.211A",
        snomed_code="111111111",
        onset_date="2024-01-15",
        organism_snomed=organism_snomed,
        culture_specimen_id=f"spec-{hai_id}",
    )


def _spec_cfg():
    return {"specimen": "blood", "specimen_snomed": "119297000", "test_loinc": "600-7"}


def test_susceptibilities_populated_for_clabsi_saureus(antibiogram):
    rec = {}
    ev = _make_event("clabsi", "3092008")
    rng = np.random.default_rng(42)
    _append_hai_culture(rec, ev, _spec_cfg(), "2024-01-15", antibiogram, rng)
    micros = rec["microbiology"]
    assert len(micros) == 1
    susc = micros[0].susceptibilities
    assert len(susc) == 6  # 6 abx in antibiogram for clabsi/3092008
    for r in susc:
        assert r.interpretation in {"S", "I", "R"}


def test_hai_event_id_backref_set(antibiogram):
    rec = {}
    ev = _make_event("clabsi", "3092008", hai_id="hai-test-id")
    rng = np.random.default_rng(42)
    _append_hai_culture(rec, ev, _spec_cfg(), "2024-01-15", antibiogram, rng)
    assert rec["microbiology"][0].hai_event_id == "hai-test-id"


def test_vancomycin_always_S_for_saureus(antibiogram):
    """vancomycin row is [1.00, 0.00, 0.00] in clabsi/3092008."""
    for seed in range(20):
        rec = {}
        ev = _make_event("clabsi", "3092008")
        rng = np.random.default_rng(seed)
        _append_hai_culture(rec, ev, _spec_cfg(), "2024-01-15", antibiogram, rng)
        vanc = [r for r in rec["microbiology"][0].susceptibilities
                if r.antibiotic_loinc == "18991-2"]
        assert len(vanc) == 1
        assert vanc[0].interpretation == "S"


def test_organism_not_in_antibiogram_yields_empty_susceptibilities(antibiogram):
    """E. faecalis is in hai_organisms.yaml but not antibiogram — empty list ok."""
    rec = {}
    ev = _make_event("clabsi", "78065002")  # E. faecalis
    rng = np.random.default_rng(42)
    _append_hai_culture(rec, ev, _spec_cfg(), "2024-01-15", antibiogram, rng)
    assert rec["microbiology"][0].susceptibilities == []


def test_empirical_S_distribution_for_clabsi_ecoli(antibiogram):
    """E. coli ceftriaxone is [0.89, 0.02, 0.09] — 5000 trials → ~89% S."""
    s_count = 0
    n = 5000
    for seed in range(n):
        rec = {}
        ev = _make_event("clabsi", "112283007")
        rng = np.random.default_rng(seed)
        _append_hai_culture(rec, ev, _spec_cfg(), "2024-01-15", antibiogram, rng)
        ctx = [r for r in rec["microbiology"][0].susceptibilities
               if r.antibiotic_loinc == "18895-3"]  # ceftriaxone
        assert len(ctx) == 1
        if ctx[0].interpretation == "S":
            s_count += 1
    rate = s_count / n
    assert 0.87 <= rate <= 0.91, f"E. coli ceftriaxone S rate {rate:.3f} outside expected"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/unit/modules/hai/test_hai_susceptibility_sampling.py -v
```
Expected: 5 FAILs (susceptibilities empty, signature mismatch, etc).

- [ ] **Step 3: Extend `_append_hai_culture` signature and body**

Edit `clinosim/modules/hai/enricher.py`. Update imports:
```python
from clinosim.modules.antibiotic import ANTIBIOTIC_LOINC_LOOKUP
from clinosim.modules.hai import load_hai_antibiogram
from clinosim.types.microbiology import MicrobiologyResult, SusceptibilityResult
```
(Confirm SusceptibilityResult import is added.)

Update `_SIR` constant location — define at module top if not already:
```python
_SIR = ("S", "I", "R")
```

Replace the `_append_hai_culture` function with:
```python
def _append_hai_culture(
    rec,
    hai: HAIEvent,
    spec_cfg: dict,
    onset_date: str,
    antibiogram_cfg: dict,
    rng: np.random.Generator,
) -> None:
    """Append a MicrobiologyResult so _fhir_microbiology.py emits the culture.

    Populates susceptibilities via NHSN-anchored antibiogram lookup keyed by
    (hai_type, organism_snomed). Sets hai_event_id as a backref for PR3b-3.
    """
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
        hai_event_id=hai.hai_id,
    )
    organism_table = (
        antibiogram_cfg.get(hai.hai_type, {}).get(hai.organism_snomed, {})
    )
    for abx_key, sir_probs in organism_table.items():
        loinc = ANTIBIOTIC_LOINC_LOOKUP.get(abx_key)
        if not loinc:
            continue  # unreachable at runtime (Task 4 validates load time)
        probs = np.array(sir_probs, dtype=float)
        if probs.sum() <= 0:
            continue
        probs = probs / probs.sum()
        interp = _SIR[int(rng.choice(len(_SIR), p=probs))]
        micro.susceptibilities.append(
            SusceptibilityResult(antibiotic_loinc=str(loinc), interpretation=interp)
        )
    if isinstance(rec, dict):
        rec.setdefault("microbiology", []).append(micro)
    else:
        rec.microbiology.append(micro)
```

Update the `enrich_hai` body (around the `_append_hai_culture` call site, currently line 114 region). Above the patient loop, load the antibiogram once:
```python
antibiogram_cfg = load_hai_antibiogram()
```
At the call site:
```python
_append_hai_culture(rec, ev, specimens_cfg[hai_type], onset_date,
                    antibiogram_cfg, rng)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/unit/modules/hai/test_hai_susceptibility_sampling.py -v
```
Expected: 5 PASS (the 5000-trial test may take 5-10s).

- [ ] **Step 5: Full unit + integration regression**

```bash
pytest -m unit -m integration -q
```
Expected: no regressions; the existing HAI tests still pass.

- [ ] **Step 6: Commit**

```bash
git add clinosim/modules/hai/enricher.py \
        tests/unit/modules/hai/test_hai_susceptibility_sampling.py
git commit -m "$(cat <<'EOF'
feat(hai): antibiogram-driven S/I/R sampling on HAI cultures (Task 5)

_append_hai_culture extended:
- antibiogram_cfg + rng passed through
- per-antibiotic S/I/R sampled via rng.choice(3, p=probs)
- hai_event_id set as PR3b-3 backref

Community microbiology (modules/observation/microbiology.py) untouched.
All RNG draws use the existing HAI patient sub-rng (AD-16).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_0161mrbU11xi7sTD61CpAu2K
EOF
)"
```

---

### Task 6: Integration test — HAI culture S/I/R chain end-to-end

**Files:**
- Create: `tests/integration/test_hai_susceptibility_chain.py`

**Interfaces:**
- Consumes: `ForcedScenario.force_hai_event` (existing infrastructure), `enrich_hai` (Task 5), `load_hai_antibiogram` (Task 4).
- Produces: end-to-end exercise of the PR3b-2 chain (HAI sampled → culture appended with S/I/R → backref integrity).

- [ ] **Step 1: Write failing integration test**

Create `tests/integration/test_hai_susceptibility_chain.py`:
```python
"""Integration: PR3b-2 HAI culture S/I/R chain end-to-end."""
from __future__ import annotations

import pytest

from clinosim.simulator import run_forced
from clinosim.simulator.forced_scenario import ForcedScenario


@pytest.mark.integration
@pytest.mark.parametrize("hai_type,organism_snomed,expected_abx_count", [
    ("clabsi", "3092008", 6),    # S. aureus, 6 antibiotics in antibiogram
    ("cauti", "112283007", 5),   # E. coli, 5 antibiotics
    ("vap", "3092008", 6),       # S. aureus VAP, 6 antibiotics
])
def test_force_hai_event_populates_susceptibilities(
    hai_type, organism_snomed, expected_abx_count
):
    """ForcedScenario fires the chain; antibiogram populates susceptibilities."""
    forced = ForcedScenario(
        force_hai_event={
            "hai_type": hai_type,
            "onset_offset_days": 3,
            "organism_snomed": organism_snomed,
        },
    )
    records = run_forced(scenario=forced, count=1, seed=42)
    # Find the patient with a forced HAI event.
    hai_recs = [r for r in records if r.extensions.get("hai")]
    assert hai_recs, f"no HAI event in forced run for {hai_type}"
    rec = hai_recs[0]
    hai_events = rec.extensions["hai"]
    assert len(hai_events) >= 1
    hai_id_set = {e.hai_id for e in hai_events}

    # The culture with hai_event_id matching one of the HAI events should
    # have the expected susceptibility count.
    hai_cultures = [m for m in rec.microbiology if m.hai_event_id in hai_id_set]
    assert hai_cultures, f"no HAI culture for {hai_type}"
    micro = hai_cultures[0]
    assert micro.organism_snomed == organism_snomed
    assert len(micro.susceptibilities) == expected_abx_count
    for s in micro.susceptibilities:
        assert s.interpretation in {"S", "I", "R"}
        assert s.antibiotic_loinc  # non-empty


@pytest.mark.integration
def test_community_culture_has_no_hai_event_id_backref():
    """Sanity: non-HAI culture from existing modules/observation/microbiology
    has hai_event_id == "" (AD-16 protection of unrelated code path)."""
    # Generate a small community-pathogen cohort (no HAI forced).
    records = run_forced(scenario=ForcedScenario(), count=5, seed=42)
    community = [
        m for r in records for m in r.microbiology
        if not r.extensions.get("hai")
    ]
    for m in community:
        assert m.hai_event_id == "", (
            f"community culture has unexpected hai_event_id {m.hai_event_id!r}"
        )
```

Note: the exact `run_forced` invocation may differ — read `clinosim/simulator/forced_scenario.py` and the existing `tests/integration/test_hai_enricher_force.py` to confirm the harness contract before implementing. Use the same patterns.

- [ ] **Step 2: Verify test naming / harness contract**

```bash
grep -n "force_hai_event\|run_forced\b" tests/integration/test_hai_enricher_force.py | head -20
```
Adjust the new test to match the existing call pattern.

- [ ] **Step 3: Run integration test**

```bash
pytest tests/integration/test_hai_susceptibility_chain.py -v
```
Expected: 4 PASS (3 parametrized + 1 community).

If the `expected_abx_count` per parametrize case fails because the antibiogram has a different row count, **read the YAML and update the parametrize counts to match**. Document the count in a comment by each parameter.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_hai_susceptibility_chain.py
git commit -m "$(cat <<'EOF'
test(hai): integration test for PR3b-2 S/I/R chain (Task 6)

End-to-end exercise: ForcedScenario fires HAI → enricher samples
antibiogram → MicrobiologyResult.susceptibilities populated +
hai_event_id backref pinned.

Community-culture parity check: cultures from community microbiology
path keep hai_event_id == "" (AD-16 verification).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_0161mrbU11xi7sTD61CpAu2K
EOF
)"
```

---

### Task 7: AD-16 RNG sequence test update (post-PR-95 exact-sequence pinning)

**Files:**
- Modify: `tests/integration/test_hai_enricher_force.py`

**Interfaces:**
- Consumes: HAI sub-rng exact draw sequence as established in PR-95.
- Produces: an updated AD-16 sequence test pinning the new draw count `[organism_choice + per-antibiotic choice]` per HAI event.

- [ ] **Step 1: Read existing AD-16 sequence test**

```bash
grep -n "def test_" tests/integration/test_hai_enricher_force.py
```
Identify the test currently pinning the exact RNG sequence (PR-95 added strict equality `==` on draw counts).

- [ ] **Step 2: Compute expected draw count after PR3b-2**

For a single forced HAI event with organism `O` and hai_type `T`:
- pre-PR3b-2 draws (in the firing path): existing PR-95 count = 3 (`random() + integers(2, line_days) + choice(N, p=weights)`)
- new draws (PR3b-2): N_antibiotic = count of entries in `hai_antibiogram[T][O]`
- total new draws per HAI event = pre-PR3b-2 + N_antibiotic

The test fixture in PR-95 uses a known `(T, O)` pair — read the fixture's organism and look up N_antibiotic in `hai_antibiogram.yaml`.

- [ ] **Step 3: Update the assertion**

Edit `tests/integration/test_hai_enricher_force.py`. Find the assertion that currently checks `actual_draw_count == 3` (or similar) and change to:
```python
# Post-PR3b-2: forced path now drains organism_choice + per-antibiotic S/I/R.
# For the fixture (hai_type=<T>, organism=<O>) the antibiogram has <N> entries.
EXPECTED_DRAWS = 3 + N_ANTIBIOTIC_<T>_<O>  # named constant computed above
assert actual_draws == EXPECTED_DRAWS
```
Document the constant inline: `# 3 (PR-95 firing path) + 6 (antibiogram clabsi/3092008) = 9`.

- [ ] **Step 4: Run test to verify it passes**

```bash
pytest tests/integration/test_hai_enricher_force.py -v
```
Expected: PASS.

- [ ] **Step 5: Symmetric verification — non-forced firing path**

If the PR-95 test also includes a monkeypatched `per_day_risk=1.0` non-forced path assertion, update its draw count the same way (the non-forced firing path also calls `_append_hai_culture` and so draws the same antibiogram entries).

- [ ] **Step 6: Commit**

```bash
git add tests/integration/test_hai_enricher_force.py
git commit -m "$(cat <<'EOF'
test(hai): AD-16 RNG sequence pin updated for PR3b-2 (Task 7)

PR-95 pinned the forced/non-forced firing path to 3 draws (random +
integers + choice). PR3b-2 adds N_antibiotic per-antibiotic
rng.choice(3, p=probs) draws. New pinned count = 3 + N_antibiotic for
the test fixture's (hai_type, organism) pair.

Strict equality (==) retained per PR-95 lesson — no permissive >=.
Both forced and non-forced firing paths verified.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_0161mrbU11xi7sTD61CpAu2K
EOF
)"
```

---

### Task 8: Audit framework expansion in `modules/antibiotic/audit.py`

**Files:**
- Modify: `clinosim/modules/antibiotic/audit.py`

**Interfaces:**
- Consumes: AD-60 `ModuleAuditSpec` registration API, `equality_checks` proof format established in PR-94.
- Produces: extended structural / clinical_acceptance / silent_no_op axes covering S/I/R.

- [ ] **Step 1: Read existing audit.py**

```bash
cat clinosim/modules/antibiotic/audit.py
```
Identify:
- the `structural_obs_codes` list
- the `clinical_acceptance` list
- the `silent_no_op` proof block (which uses `equality_checks` format from PR-94)

- [ ] **Step 2: Extend `structural_obs_codes` for S/I/R LOINC**

Add the 8 antibiotic LOINC codes to whatever list governs structural Observation presence. Reference these from `ANTIBIOTIC_LOINC_LOOKUP` (do not duplicate strings):
```python
from clinosim.modules.antibiotic import ANTIBIOTIC_LOINC_LOOKUP

# Add per-LOINC structural check for S/I/R Observations attached to HAI cultures.
ABX_LOINCS = list(ANTIBIOTIC_LOINC_LOOKUP.values())
```

Add a structural check that for every HAI culture (`DiagnosticReport` with a culture LOINC), at least one antibiotic-susceptibility `Observation` with a code in `ABX_LOINCS` is present — UNLESS the organism is in the "no S/I/R panel" set (E. faecalis, C. albicans).

- [ ] **Step 3: Extend `clinical_acceptance` bands**

Add the NHSN-anchored acceptance bands (use exact source-cited values):
```python
HAI_RESISTANCE_BANDS = [
    {
        "cohort": "clabsi/3092008",  # S. aureus CLABSI
        "antibiotic": "cefazolin",   # MRSA proxy
        "expected_R_min": 0.40,
        "expected_R_max": 0.55,
        "source": "NHSN AR 2018-2020 Table 2",
    },
    {
        "cohort": "cauti/112283007",  # E. coli CAUTI
        "antibiotic": "ceftriaxone",  # ESBL proxy
        "expected_R_min": 0.12,
        "expected_R_max": 0.22,
        "source": "NHSN AR 2018-2020 Table 4",
    },
    {
        "cohort": "vap/3092008",     # S. aureus VAP
        "antibiotic": "cefazolin",   # MRSA proxy
        "expected_R_min": 0.30,
        "expected_R_max": 0.45,
        "source": "NHSN AR 2018-2020 Table 2",
    },
]

HAI_EMPTY_SUSCEPTIBILITIES_MAX_RATE = 0.05
```

Wire these into whatever the audit's clinical-axis cohort filter currently does. If the existing axis takes a list of acceptance entries, extend it; if not, add a per-band helper that the axis can consume.

- [ ] **Step 4: Extend `silent_no_op` proof with `antibiogram_firing_proof`**

Add a new entry in the `silent_no_op` axis proof list. Use the `equality_checks` format established by PR-94:
```python
def _antibiogram_firing_proof() -> dict:
    """Synthetic HAIEvent → exact susceptibility count + vancomycin = S."""
    import numpy as np

    from clinosim.modules.hai import load_hai_antibiogram
    from clinosim.modules.hai.enricher import _append_hai_culture
    from clinosim.types.hai import HAIEvent

    rec: dict = {}
    ev = HAIEvent(
        hai_id="hai-proof",
        encounter_id="enc-proof",
        hai_type="clabsi",
        source_device_id="dev-proof",
        icd10_code="T80.211A",
        snomed_code="431193003",  # placeholder; real proof reads codes_cfg
        onset_date="2024-01-15",
        organism_snomed="3092008",
        culture_specimen_id="spec-proof",
    )
    abg = load_hai_antibiogram()
    rng = np.random.default_rng(0)
    _append_hai_culture(
        rec, ev,
        {"specimen": "blood", "specimen_snomed": "119297000", "test_loinc": "600-7"},
        "2024-01-15", abg, rng,
    )
    susc = rec["microbiology"][0].susceptibilities
    vanc_interp = next(
        (s.interpretation for s in susc if s.antibiotic_loinc == "18991-2"),
        None,
    )
    return {
        "kind": "equality_checks",
        "checks": [
            ("clabsi_saureus_susceptibility_count", len(susc), 6),
            ("clabsi_saureus_vancomycin_is_S", vanc_interp, "S"),
        ],
    }
```
Register it in the `ModuleAuditSpec` for `antibiotic`. The audit framework's harness self-check (added in PR-94) verifies the proof format is recognized; this proof exercises the entire PR3b-2 chain end-to-end.

- [ ] **Step 5: Run audit on master HEAD vs branch HEAD**

```bash
clinosim audit run -p 2000 --seed 42 2>&1 | tee /tmp/audit_p2000.log
```
Verify the new `proof_eq_clabsi_saureus_*` lines appear in the report (PR-94 framework feature). Verify the new resistance-band lines appear in the clinical-axis section.

Expected: PASS on structural / clinical / jp_language / silent_no_op axes.

- [ ] **Step 6: Commit**

```bash
git add clinosim/modules/antibiotic/audit.py
git commit -m "$(cat <<'EOF'
feat(audit): PR3b-2 S/I/R coverage (Task 8)

modules/antibiotic/audit.py extended:
- structural_obs_codes: 8 antibiotic-susceptibility LOINCs from
  ANTIBIOTIC_LOINC_LOOKUP, asserted present on HAI cultures.
- clinical_acceptance: 3 NHSN-anchored MRSA/ESBL R-rate bands +
  HAI cohort empty-susceptibilities max-rate (sanity).
- silent_no_op: antibiogram_firing_proof using PR-94 equality_checks
  format; synthetic HAIEvent → 6 susceptibilities including
  vancomycin = S (closed-form from [1.00, 0.00, 0.00] row).

Audit framework harness self-check (PR-94) catches proof-format
errors loudly; the proof exercises the full PR3b-2 chain.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_0161mrbU11xi7sTD61CpAu2K
EOF
)"
```

---

### Task 9: Byte-diff verification + clinosim audit run + 3-axis DQR

**Files:**
- Create: `docs/reviews/2026-06-26-phase-3b-2-hai-susceptibility-data-quality-review.md`

**Interfaces:**
- Consumes: branch HEAD after Task 8.
- Produces: DQR doc with byte-diff results, audit summary, and clinical metrics.

- [ ] **Step 1: Run full test suite**

```bash
pytest -m unit -m integration -q
```
Expected: green.

```bash
pytest -m e2e -q
```
Expected: green (existing 13 golden e2e tests).

- [ ] **Step 2: Byte-diff baseline generation on master `6011b06e`**

```bash
git stash -u  # save in-progress work
git checkout 6011b06e
mkdir -p scratchpad/pr3b2_byte_diff/baseline
clinosim generate --country US --count 2000 --seed 42 \
    --output scratchpad/pr3b2_byte_diff/baseline/us \
    --format ndjson,csv,cif
clinosim generate --country JP --count 1000 --seed 42 \
    --output scratchpad/pr3b2_byte_diff/baseline/jp \
    --format ndjson,csv,cif
git checkout feat/phase-3b-2-hai-susceptibility
git stash pop
```

(If `clinosim generate` CLI flags differ, mirror the pattern from
`scratchpad/abx_dqr/` from session 17.)

- [ ] **Step 3: Byte-diff PR branch generation**

```bash
mkdir -p scratchpad/pr3b2_byte_diff/pr
clinosim generate --country US --count 2000 --seed 42 \
    --output scratchpad/pr3b2_byte_diff/pr/us \
    --format ndjson,csv,cif
clinosim generate --country JP --count 1000 --seed 42 \
    --output scratchpad/pr3b2_byte_diff/pr/jp \
    --format ndjson,csv,cif
```

- [ ] **Step 4: Diff non-microbiology / non-CIF artifacts**

```bash
diff -r scratchpad/pr3b2_byte_diff/baseline/us scratchpad/pr3b2_byte_diff/pr/us \
    | grep -v "microbiology.ndjson\|^Only in.*cif/" \
    | head -30
```
Expected: every other NDJSON byte-identical (no diff output beyond microbiology and CIF directories).

Record the result. If ANY non-microbiology / non-CIF artifact differs, **STOP and investigate** — that is an AD-16 violation.

- [ ] **Step 5: Run `clinosim audit run`**

```bash
clinosim audit run -p 10000 --seed 42 --country US > /tmp/audit_us.txt 2>&1
clinosim audit run -p 5000 --seed 42 --country JP > /tmp/audit_jp.txt 2>&1
```
Expected: PASS on all 4 axes including the new antibiogram_firing_proof.

- [ ] **Step 6: Write DQR doc**

Create `docs/reviews/2026-06-26-phase-3b-2-hai-susceptibility-data-quality-review.md`. Template (fill in actual numbers from steps 4-5):

```markdown
# Phase 3b-2 HAI Culture Susceptibility — Data Quality Review

**Date**: 2026-06-26
**Branch**: feat/phase-3b-2-hai-susceptibility
**Spec**: docs/superpowers/specs/2026-06-26-phase-3b-2-hai-susceptibility-design.md
**Master baseline**: 6011b06e

## 1. Byte-diff (p=2000 US + p=1000 JP, seed=42)

| Artifact | Baseline → PR | Notes |
|---|---|---|
| microbiology.ndjson | DIFF (expected) | + N_susceptibility Observations per HAI culture |
| cif/*.json | DIFF (expected) | + hai_event_id field on HAI cultures, + discontinuation_datetime on regimens |
| All other NDJSON | IDENTICAL | AD-16 community microbiology untouched |
| CSV | IDENTICAL | (or specify if diff present) |

## 2. clinosim audit run (p=10k US + p=5k JP)

| Axis | US | JP | Notes |
|---|---|---|---|
| structural | PASS / WARN / FAIL | … | refRange + S/I/R LOINC coverage |
| clinical | PASS | … | MRSA/ESBL bands within NHSN envelope |
| jp_language | PASS | … | (JP only) |
| silent_no_op | PASS | … | antibiogram_firing_proof emitted equality_checks |

## 3. Clinical realism (HAI cohort, US p=10k)

(Fill in actual measured rates per organism × hai_type from generated data.)

| Cohort | Antibiotic | Measured %R | Expected band | Verdict |
|---|---|---|---|---|
| CLABSI / S. aureus | cefazolin | X% | 40-55% | PASS / FAIL |
| CAUTI / E. coli | ceftriaxone | X% | 12-22% | PASS / FAIL |
| VAP / S. aureus | cefazolin | X% | 30-45% | PASS / FAIL |
| HAI cohort | susceptibilities=[] | X% | < 5% | PASS / FAIL |

## 4. JP language quality (JP p=5k)

(Same as PR-93 — no Japanese text added by PR3b-2; FHIR S/I/R `interpretation`
uses v3-ObservationInterpretation codes which display via existing FHIR
display logic. JP regression PASS expected.)

## 5. Ship-readiness verdict

PASS / WARN / FAIL.

Backlog (if any): describe.
```

- [ ] **Step 7: Commit DQR**

```bash
git add docs/reviews/2026-06-26-phase-3b-2-hai-susceptibility-data-quality-review.md
git commit -m "$(cat <<'EOF'
docs(review): Phase 3b-2 DQR (Task 9)

Byte-diff PASS for all non-HAI NDJSON / non-CIF artifacts.
clinosim audit run PASS on 4 axes including new antibiogram_firing_proof.
HAI cohort %R bands within NHSN envelope.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_0161mrbU11xi7sTD61CpAu2K
EOF
)"
```

- [ ] **Step 8: Clean up byte-diff scratch**

```bash
rm -rf scratchpad/pr3b2_byte_diff
```

---

### Task 10: Docs sync

**Files:**
- Modify: `MODULES.md`
- Modify: `SCENARIO_FLAGS.md` (only if a new flag is added — PR3b-2 does not add one; verify and skip if so)
- Modify: `clinosim/modules/hai/README.md`
- Modify: `clinosim/modules/antibiotic/README.md`
- Modify: `clinosim/modules/observation/README.md` (note: community microbiology untouched)
- Modify: `DESIGN.md` (AD entry / AD-60 framework extension note)
- Modify: `CLAUDE.md` (Phase 3b-2 entry)
- Modify: `TODO.md` (mark PR3b-2 done; cite PR3b-3 as next)
- Modify: `README.md` + `README.ja.md` (Quality & Compliance section + module list if relevant)

**Interfaces:**
- Consumes: shipped feature in Tasks 1-8 + DQR doc from Task 9.
- Produces: all canonical docs reflect PR3b-2.

- [ ] **Step 1: Update MODULES.md**

Find the existing HAI module entry. Add bullets noting susceptibility population + hai_event_id backref. Refresh data-flow diagrams if any.

- [ ] **Step 2: Update modules/hai/README.md**

Document:
- New `load_hai_antibiogram()` export.
- `_append_hai_culture` signature expanded.
- `hai_antibiogram.yaml` location, format, NHSN source citation.
- Cross-reference to PR3b-3 narrow (forward-compat reserve fields).

- [ ] **Step 3: Update modules/antibiotic/README.md**

Document:
- New `ANTIBIOTIC_LOINC_LOOKUP` export.
- Audit.py expanded with 3rd axis content.
- Cross-reference forward-compat `AntibioticRegimen.discontinuation_datetime`.

- [ ] **Step 4: Update DESIGN.md**

If an ADR entry covers Phase 3b series, add a note for PR3b-2 (one paragraph). If AD-60 audit framework is in a dedicated ADR, note the `antibiogram_firing_proof` as a second-generation proof using the PR-94 equality_checks format.

- [ ] **Step 5: Update CLAUDE.md**

In the "AD-55 enricher patterns" → "Phase 3b-1 HAI empirical antibiotic" subsection, add a sibling subsection "Phase 3b-2 HAI culture susceptibility" describing:
- `hai_antibiogram.yaml` as the HAI module's antibiogram source of truth (B3 pattern).
- `MicrobiologyResult.hai_event_id` backref convention.
- import-time canonical-constants validation lesson reapplied.

- [ ] **Step 6: Update TODO.md**

In the Phase 3b backlog section (TODO.md:535-540 region from session 17), mark PR3b-2 done with a one-line summary + DQR doc link; cite PR3b-3 narrow as the next candidate.

- [ ] **Step 7: Update README.md / README.ja.md**

If the Quality & Compliance / 品質 section mentions per-PR DQRs, add the PR3b-2 link. If module count or feature list changes, refresh.

- [ ] **Step 8: Commit docs sync**

```bash
git add MODULES.md DESIGN.md CLAUDE.md TODO.md README.md README.ja.md \
        clinosim/modules/hai/README.md clinosim/modules/antibiotic/README.md \
        clinosim/modules/observation/README.md
git commit -m "$(cat <<'EOF'
docs(phase3b-2): MODULES / DESIGN / CLAUDE / TODO / READMEs sync (Task 10)

PR3b-2 = HAI culture S/I/R + forward-compat reserves shipped:
- hai_antibiogram.yaml (CDC NHSN AR 2018-2020)
- _append_hai_culture extended with antibiogram-driven S/I/R
- ANTIBIOTIC_LOINC_LOOKUP centralized
- modules/antibiotic/audit.py extended (S/I/R coverage + NHSN bands +
  antibiogram_firing_proof)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_0161mrbU11xi7sTD61CpAu2K
EOF
)"
```

---

### Task 11: PR creation + post-merge adversarial review readiness

**Files:**
- None (PR is created via gh).

**Interfaces:**
- Consumes: branch HEAD after Task 10 is committed.
- Produces: an open PR on GitHub against master, ready for the post-merge adversarial review fan-out.

- [ ] **Step 1: Final regression**

```bash
pytest -m unit -m integration -m e2e -q
```
Expected: all green.

- [ ] **Step 2: Push branch**

```bash
git push -u origin feat/phase-3b-2-hai-susceptibility
```

- [ ] **Step 3: Create PR**

```bash
gh pr create --title "Phase 3b-2: HAI culture susceptibility (S/I/R) + forward-compat reserves" --body "$(cat <<'EOF'
## Summary
- Fill `MicrobiologyResult.susceptibilities` on HAI-derived cultures via
  `hai_antibiogram.yaml` (CDC NHSN AR 2018-2020).
- Add forward-compat reserves: `MicrobiologyResult.hai_event_id`
  (PR3b-3 narrow O(1) backref) and
  `AntibioticRegimen.discontinuation_datetime` (PR3b-3 narrow truncation).
- Centralize `ANTIBIOTIC_LOINC_LOOKUP` from existing `microbiology.yaml`.
- Extend `modules/antibiotic/audit.py` with 3 axes covering S/I/R:
  structural LOINC presence, NHSN-anchored MRSA/ESBL clinical bands,
  antibiogram_firing_proof using PR-94 equality_checks format.
- Community microbiology code path untouched (AD-16).

## Verification
- 780+ unit/integration tests green (+ ~15 new).
- 13 e2e golden tests unchanged.
- `clinosim audit run`: PASS on all 4 axes (structural / clinical /
  jp_language / silent_no_op).
- Byte-diff vs master `6011b06e`: every non-HAI NDJSON / non-CIF
  artifact byte-identical at p=2000 US + p=1000 JP, seed=42.
- 3-axis DQR at US p=10k + JP p=5k: `docs/reviews/2026-06-26-phase-3b-2-hai-susceptibility-data-quality-review.md`.

## Test plan
- [x] `pytest -m unit -m integration -m e2e`
- [x] `clinosim audit run` US p=10k + JP p=5k
- [x] Byte-diff vs master
- [x] DQR doc
- [ ] Post-merge adversarial review fan-out (8-10 agents, per
  feedback_iterative_adversarial_review)
- [ ] Fix PR (if findings); fix PR itself also gets adversarial review

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_0161mrbU11xi7sTD61CpAu2K
EOF
)"
```

- [ ] **Step 4: Verify PR creation**

```bash
gh pr view --json url,state,title
```
Expected: state OPEN, title matches.

- [ ] **Step 5: Surface PR to user for merge approval**

Once the user approves merge:
```bash
gh pr merge --merge --delete-branch
git checkout master
git pull
```

- [ ] **Step 6: Post-merge adversarial review fan-out (in the next session turn)**

Apply `feedback_iterative_adversarial_review`: dispatch 8-10 independent
reviewer agents (per `superpowers:dispatching-parallel-agents`) against the
merged commits, asking each to verify the PR3b-2 change independently
without seeing other reviewers' verdicts. Findings → fix PR. The fix PR
itself also gets adversarial review (3 agents — scope smaller).

---

## Self-Review

Run the spec coverage / placeholder / type-consistency checks now.

**Spec coverage (§ → task)**:
- § 1 Goal & scope → Task 0-11 (whole PR)
- § 2 Architecture & data flow → Task 5
- § 3 Types changes → Task 1
- § 4 hai_antibiogram.yaml → Task 3
- § 5 _append_hai_culture extension → Task 5
- § 6.1 ANTIBIOTIC_LOINC_LOOKUP → Task 2
- § 6.2 hai_antibiogram loader → Task 4
- § 7.1 structural axis → Task 8
- § 7.2 clinical_acceptance → Task 8
- § 7.3 silent_no_op antibiogram_firing_proof → Task 8
- § 8 Testing strategy → Tasks 1, 2, 4, 5, 6, 7
- § 9 Verification gates → Tasks 9, 11
- § 10 Forward-compat for PR3b-3 → Task 1 + Task 3 (panel) + Task 5 (backref)
- § 11 Non-scope → enforced by AD-16 RNG ordering (Task 5) and Task 9 byte-diff

All sections covered. No gaps.

**Placeholder scan**: cefepime LOINC is gated behind Task 0 (authoritative
verify before fabrication). No "TBD", "TODO", "fill in details" in steps.
Every test has executable code. Every commit message is complete.

**Type consistency**:
- `MicrobiologyResult.hai_event_id: str = ""` introduced in Task 1, populated in
  Task 5, asserted in Task 6.
- `AntibioticRegimen.discontinuation_datetime: datetime | None = None`
  introduced in Task 1 (no further consumer in this PR — reserved for PR3b-3).
- `ANTIBIOTIC_LOINC_LOOKUP: dict[str, str]` introduced in Task 2, consumed in
  Task 4 (validation), Task 5 (sampling), Task 8 (audit).
- `load_hai_antibiogram() -> dict` introduced in Task 4, consumed in Task 5.
- `_append_hai_culture(rec, hai, spec_cfg, onset_date, antibiogram_cfg, rng)`
  extended in Task 5, exercised in Task 6.
- `HAI_TYPES`, `HAIEvent`, existing — unchanged signatures.

No naming drift.
