# Phase 3b-2 = HAI culture susceptibility (S/I/R) — design spec

**Date**: 2026-06-26
**Scope**: PR3b-2 of the Phase 3b series (HAI clinical chain). Builds on PR-93/94/95 (Phase 3b-1 empirical antibiotic regimen) and PR-89 (modules/hai PR-B).
**Status**: design approved, awaiting plan

---

## 1. Goal & scope

PR3b-1 (PR #93) wired empirical antibiotic regimens to HAI events, but the culture
`MicrobiologyResult.susceptibilities` that `modules/hai/enricher.py:_append_hai_culture`
appends is left as an **empty list**. Downstream FHIR / CSV consumers therefore
emit cultures without any S/I/R Observations — clinically incomplete and a
hard blocker for PR3b-3 narrow / de-escalation.

This PR fills the susceptibility metadata using a **CDC NHSN AR 2018-2020-anchored
HAI-specific antibiogram** that is structured per (`hai_type`, `organism_snomed`,
`antibiotic_key`) so CLABSI MRSA (~47% R) and VAP MRSA (~35% R) are
distinguishable.

In-scope deliverables:

1. **A — forward-compat reserves**: add
   `MicrobiologyResult.hai_event_id: str = ""` (PR3b-3 narrow O(1) backref) and
   `AntibioticRegimen.discontinuation_datetime: datetime | None = None`
   (PR3b-3 narrow truncation). Both fields ship with default values so adding
   them is non-breaking and byte-diff-clean for non-HAI paths.
2. **B — HAI-specific antibiogram** in `modules/hai/reference_data/hai_antibiogram.yaml`,
   per-`hai_type` nested. Community `modules/observation/reference_data/microbiology.yaml`
   is untouched (AD-16: non-HAI cultures remain byte-identical).
3. **C — `_append_hai_culture` extension**: lookup antibiogram by
   `(hai_type, organism_snomed)`, sample `S | I | R` per antibiotic via the HAI
   sub-rng, append `SusceptibilityResult` entries, set `hai_event_id`.
4. **Audit expansion** in `modules/antibiotic/audit.py` (AD-60 framework's 3rd
   per-Module plug-in extension): structural S/I/R LOINC checks,
   clinical acceptance bands for MRSA/ESBL rates, and a
   silent_no_op `antibiogram_firing_proof` using the equality_checks
   format established in PR-94.

Explicit non-goals (deferred):

- PR3b-3 narrow / de-escalation regimen append.
- JP-locale antibiogram override (JANIS surveillance). PR3b-2 ships US NHSN only;
  the loader will accept a `country` parameter for future locale plumbing but
  will return the US table for both `US` and `JP` until JANIS data is wired.
- antibiotic-day decay (PR3b-4) and mortality coupling (Phase 3c).
- Any change to `modules/observation/microbiology.py` (community pathogen
  cultures stay exactly as-is, AD-16 protection of unrelated patients).

---

## 2. Architecture & data flow

```
modules/hai/enricher.py:enrich_hai (POST_ENCOUNTER, order=80)
  └─ for each rec, for each device sampling a HAI:
       ├─ _sample_organism(hai_organisms.yaml, sub-rng) → organism_snomed
       ├─ HAIEvent generated → extensions["hai"]
       └─ _append_hai_culture(rec, hai, spec_cfg, onset_date,
                              antibiogram_cfg, rng)              ← extended signature
            ├─ MicrobiologyResult(growth=True, organism_snomed, …)
            ├─ NEW: micro.hai_event_id = hai.hai_id
            ├─ NEW: sample_susceptibilities(
            │        antibiogram_cfg[hai.hai_type][hai.organism_snomed],
            │        rng) → list[SusceptibilityResult]
            └─ rec.microbiology.append(micro)
```

No new enricher order is introduced. No new module file. Community
`generate_microbiology` is not called and is not refactored.

Downstream (unchanged): `_fhir_microbiology.py` walks
`rec.microbiology[*].susceptibilities` and emits one
`Observation` per S/I/R result, linked back to the culture
`DiagnosticReport` via existing references.

---

## 3. Types changes (A: forward-compat reserves)

### 3.1 `clinosim/types/microbiology.py`

```python
@dataclass
class MicrobiologyResult:
    encounter_id: str = ""
    specimen: str = ""
    specimen_snomed: str = ""
    test_loinc: str = ""
    collected_datetime: datetime | None = None
    reported_datetime: datetime | None = None
    growth: bool = False
    organism_snomed: str = ""
    quantitation: str = ""
    susceptibilities: list[SusceptibilityResult] = field(default_factory=list)
    hai_event_id: str = ""   # NEW. "" for community cultures. Populated by
                             # modules/hai/enricher for HAI-derived cultures.
                             # PR3b-3 narrow will use it as an O(1) backref.
```

### 3.2 `clinosim/types/antibiotic.py`

```python
@dataclass
class AntibioticRegimen:
    regimen_id: str = ""
    hai_event_id: str = ""
    encounter_id: str = ""
    drug_key: str = ""
    dose: str = ""
    route: str = ""
    frequency: str = ""
    start_datetime: datetime = field(default_factory=lambda: datetime(1970, 1, 1))
    duration_days: int = 0
    intent: str = "empirical"
    discontinuation_datetime: datetime | None = None   # NEW. None for PR3b-1
                                                       # empirical regimens that
                                                       # ran their full duration.
                                                       # PR3b-3 narrow will set this
                                                       # to the discontinuation
                                                       # datetime when the broad
                                                       # empirical regimen is
                                                       # truncated for narrow.
```

### 3.3 Byte-diff protection

- Both fields default to a value (`""` / `None`) that serializes the same way
  it would without the field in CSV (CSV columns are explicit anyway) and in
  FHIR (where the field is not exposed as a top-level resource attribute).
- The CIF JSON dump's behavior with `asdict()` produces the empty default
  string / `None`, which adds the key to the JSON output. **Therefore CIF
  JSON files (`cif/*.json`) will gain two new keys**. CSV / NDJSON / FHIR
  remain byte-identical for non-HAI paths. A pre-flight on `master` will
  measure exactly which artifacts shift; the spec accepts CIF JSON shift as
  expected (these are internal artifacts, not consumer-facing).

---

## 4. `hai_antibiogram.yaml` design (B + nested + 8-antibiotic panel)

### 4.1 Format

```yaml
# clinosim/modules/hai/reference_data/hai_antibiogram.yaml
#
# CDC NHSN Antimicrobial Resistance Report 2018-2020 (US national pooled).
# Source: https://www.cdc.gov/nhsn/datastat/index.html
#
# Per-entry semantics: hai_antibiogram[hai_type][organism_snomed][antibiotic_key]
#   = [P(S), P(I), P(R)]   — must sum to 1.0 (validated at load time).
#
# Antibiotic panel:
#   PR3b-1 empirical: vancomycin, piperacillin_tazobactam, ceftriaxone
#   PR3b-3 narrow:    cefazolin, cefepime, meropenem, ciprofloxacin,
#                     trimethoprim_sulfamethoxazole
#
# An organism × antibiotic entry is OMITTED when the combination is
# clinically irrelevant (e.g., P. aeruginosa × ceftriaxone — intrinsic R).
# Loader treats omitted combos as "do not sample" (no S/I/R Observation
# emitted, not [0,0,1] padding).

hai_antibiogram:
  clabsi:
    "3092008":   # S. aureus (~47% MRSA in CLABSI)
      vancomycin: [1.00, 0.00, 0.00]
      cefazolin: [0.53, 0.00, 0.47]
      ceftriaxone: [0.53, 0.00, 0.47]
      cefepime: [0.53, 0.00, 0.47]
      ciprofloxacin: [0.55, 0.05, 0.40]
      trimethoprim_sulfamethoxazole: [0.95, 0.02, 0.03]
    "60875001":  # S. epidermidis (CoNS, ~80% MRSE)
      vancomycin: [1.00, 0.00, 0.00]
      cefazolin: [0.20, 0.00, 0.80]
      ceftriaxone: [0.20, 0.00, 0.80]
    "112283007": # E. coli (~11% ESBL in CLABSI)
      ceftriaxone: [0.89, 0.02, 0.09]
      cefepime: [0.92, 0.02, 0.06]
      meropenem: [0.99, 0.00, 0.01]
      piperacillin_tazobactam: [0.92, 0.04, 0.04]
      ciprofloxacin: [0.70, 0.05, 0.25]
      trimethoprim_sulfamethoxazole: [0.70, 0.02, 0.28]
    ...   # K. pneumoniae, E. faecalis, C. albicans (cultured but not S/I/R tested)
  cauti:
    "112283007": # E. coli (~17% ESBL in CAUTI)
      ceftriaxone: [0.83, 0.02, 0.15]
      cefepime: [0.90, 0.02, 0.08]
      meropenem: [0.99, 0.00, 0.01]
      ciprofloxacin: [0.70, 0.05, 0.25]
      trimethoprim_sulfamethoxazole: [0.70, 0.02, 0.28]
    ...   # K. pneumoniae (CAUTI ESBL ~13%), P. aeruginosa, P. mirabilis, E. faecalis
  vap:
    "3092008":   # S. aureus (~35% MRSA in VAP)
      vancomycin: [1.00, 0.00, 0.00]
      cefazolin: [0.65, 0.00, 0.35]
      ceftriaxone: [0.65, 0.00, 0.35]
      cefepime: [0.65, 0.00, 0.35]
    ...   # P. aeruginosa (cefepime ~75%S, pip-tazo ~85%S, meropenem ~80%S, cipro ~75%S),
          # K. pneumoniae, E. coli, E. cloacae, A. baumannii, S. maltophilia
```

### 4.2 Coverage

For each `hai_type`, the antibiogram lists every organism that appears in
`hai_organisms.yaml` for that type. Each organism lists a subset of the
8-antibiotic panel restricted to clinically-tested combinations. Approximate
non-empty cell count: ~50-70 entries total. **Fungi (C. albicans) and
enterococci** are included in `hai_organisms.yaml` for culture growth but are
omitted from `hai_antibiogram.yaml` (S/I/R for these is reported on a
different antibiotic panel — Phase 3c+).

### 4.3 Source comments

Each `hai_type` block carries a top-of-section `# Source:` comment with the
NHSN report year, table number, and URL fragment. Each numerical row carries
a `# NHSN <year> table <N>: <organism> <antibiotic> %R` trailing comment when
the value is taken directly. This satisfies the memory
`feedback_verify_before_asserting` rule (no fabricated values).

---

## 5. `_append_hai_culture` extension (C1)

### 5.1 Signature

```python
def _append_hai_culture(
    rec,
    hai: HAIEvent,
    spec_cfg: dict,
    onset_date: str,
    antibiogram_cfg: dict,                # NEW
    rng: np.random.Generator,             # NEW (passes the existing HAI sub-rng)
) -> None:
```

### 5.2 Body

```python
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
    hai_event_id=hai.hai_id,         # NEW
)
organism_table = (
    antibiogram_cfg.get(hai.hai_type, {}).get(hai.organism_snomed, {})
)
for abx_key, sir_probs in organism_table.items():
    loinc = ANTIBIOTIC_LOINC_LOOKUP.get(abx_key)
    if not loinc:
        continue            # unreachable at runtime; validated at load time
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

### 5.3 Caller update

`enrich_hai` (the loop body) passes `antibiogram_cfg` (loaded once outside the
loop) and `rng` (the existing HAI sub-rng for that patient) through.

### 5.4 RNG ordering & AD-16

- `organism_table.items()` iterates YAML insertion order = deterministic.
- One `rng.choice(3, p=probs)` per antibiotic = O(N_antibiotics) draws per
  HAI event.
- Total draws are a **function of HAI event count and per-organism
  antibiogram size**, both of which depend only on HAI-path config — so
  non-HAI patient cohorts are untouched (community microbiology RNG = a
  different sub-seed entirely; HAI sub-seed advances are isolated by
  `derive_sub_seed(master, ENRICHER_SEED_OFFSETS["hai"], pid)`).
- Force-scenario path (`ForcedScenario.force_hai_event`) is symmetric: same
  per-antibiotic draws happen in the same order, so the post-PR-95 exact
  sequence invariant continues to hold.

---

## 6. Canonical constants & load-time validation

### 6.1 Antibiotic LOINC lookup

Source of truth: `clinosim/modules/observation/reference_data/microbiology.yaml`
already maps 9 antibiotic keys → LOINC. PR3b-2 needs 8 keys, 7 of which
exist (`vancomycin`, `piperacillin_tazobactam`, `ceftriaxone`, `cefazolin`,
`meropenem`, `ciprofloxacin`, `trimethoprim_sulfamethoxazole`).

**Missing key**: `cefepime` (the 8th). Add the LOINC for "Cefepime
[Susceptibility]". A first guess is **18874-8** but this MUST be verified
against NLM LOINC search as Plan Task 0 (authoritative lookup is a hard
prerequisite per memory `feedback_verify_before_asserting` — never
fabricate codes). If 18874-8 is wrong, substitute the verified LOINC and
update spec accordingly before implementation begins.

A new module-level loader in `clinosim/modules/antibiotic/__init__.py`
exposes `ANTIBIOTIC_LOINC_LOOKUP: dict[str, str]` by reading
`microbiology.yaml`'s `antibiotics:` section. Putting the lookup on the
`antibiotic` module (not `hai`) keeps the LOINC source unified for both
PR3b-2 (HAI culture S/I/R) and PR3b-1 (antibiotic regimen LOINC for
MAR-side surveillance, if ever needed).

### 6.2 hai_antibiogram.yaml loader

```python
# clinosim/modules/hai/__init__.py exports HAI_TYPES = ("clabsi","cauti","vap")
# clinosim/modules/hai/reference_data already has hai_organisms.yaml

@lru_cache(maxsize=1)
def load_hai_antibiogram() -> dict:
    with open(...) as f:
        data = yaml.safe_load(f)
    abx = data["hai_antibiogram"]
    valid_hai_types = set(HAI_TYPES)
    valid_organisms = _organisms_per_hai_type()  # from hai_organisms.yaml
    valid_antibiotics = set(ANTIBIOTIC_LOINC_LOOKUP.keys())
    for hai_type, organisms in abx.items():
        if hai_type not in valid_hai_types:
            raise ValueError(
                f"hai_antibiogram.yaml: unknown hai_type {hai_type!r}, "
                f"expected one of {sorted(valid_hai_types)}"
            )
        for snomed, abx_table in organisms.items():
            if snomed not in valid_organisms[hai_type]:
                raise ValueError(
                    f"hai_antibiogram.yaml: organism {snomed} not in "
                    f"hai_organisms.yaml for hai_type {hai_type}"
                )
            for abx_key, sir in abx_table.items():
                if abx_key not in valid_antibiotics:
                    raise ValueError(
                        f"hai_antibiogram.yaml: unknown antibiotic key {abx_key!r} "
                        f"(must be one of ANTIBIOTIC_LOINC_LOOKUP)"
                    )
                if not (isinstance(sir, list) and len(sir) == 3):
                    raise ValueError(...)
                if abs(sum(sir) - 1.0) > 0.01:
                    raise ValueError(...)
    return data
```

PR-90 / PR-94 lesson: validate at **import time** so a typo can never
silently produce a no-op antibiogram lookup.

---

## 7. Audit framework expansion (`modules/antibiotic/audit.py`)

The existing `modules/antibiotic/audit.py` already has structural,
clinical, and silent_no_op axes. PR3b-2 extends each axis:

### 7.1 structural axis

Add to `structural_obs_codes` the 8 antibiotic S/I/R LOINC codes (one
per antibiotic in the panel). Audit asserts: for every HAI-derived culture,
a non-empty subset of these Observations is emitted with
`valueCodeableConcept` carrying an `interpretation` of `S | I | R`.

### 7.2 clinical_acceptance axis (new acceptance bands)

Two bands per organism+HAI-type cohort where NHSN reports a public %R:

| Cohort | Antibiotic | Expected R range | Source |
|---|---|---|---|
| CLABSI / S. aureus | cefazolin (proxy for MRSA) | 40% - 55% | NHSN 2018-2020 |
| CAUTI / E. coli | ceftriaxone (proxy for ESBL) | 12% - 22% | NHSN 2018-2020 |
| VAP / S. aureus | cefazolin (proxy for MRSA) | 30% - 45% | NHSN 2018-2020 |
| HAI cohort (any) | susceptibilities=[] rate | < 5% | sanity (most HAI organisms have a tested panel; fungi etc. are <5%) |

Bands have generous tolerances because rare-event Poisson tails at p=10k
can shift cohort percentages substantially.

### 7.3 silent_no_op axis = `antibiogram_firing_proof`

Use the `equality_checks` format established in PR-94. Construct a
synthetic `HAIEvent(hai_type="clabsi", organism_snomed="3092008")`,
call `_append_hai_culture` once via a deterministic seeded sub-rng,
and assert:

```python
proof = {
    "kind": "equality_checks",
    "checks": [
        ("clabsi_saureus_susceptibility_count", actual_len, 6),
        ("clabsi_saureus_vancomycin_is_S", actual_vanc_interp, "S"),
    ],
}
```

This proves antibiogram lookup, sampling, and append all wire together
end-to-end. Closed-form expected values come from the antibiogram YAML
(vancomycin row is `[1.00, 0.00, 0.00]` so it always samples "S").

If the antibiogram file is later edited to change those rows, the proof
expected values must be edited in the same PR — the existing
audit harness self-check guarantees a stub proof fails loud.

---

## 8. Testing strategy

### 8.1 Unit tests

`tests/unit/modules/hai/test_hai_antibiogram.py` (new):

- `load_hai_antibiogram` raises `ValueError` on:
  - unknown `hai_type` key (e.g., `"CLABSI"` uppercase)
  - organism SNOMED absent from `hai_organisms.yaml`
  - antibiotic key absent from `ANTIBIOTIC_LOINC_LOOKUP`
  - probability triple not length 3
  - probability triple summing != 1.0 (tolerance 0.01)
- `load_hai_antibiogram` returns a frozen dict on success.

`tests/unit/modules/hai/test_hai_susceptibility_sampling.py` (new):

- Synthetic HAI event + fixed seed → expected susceptibility list (golden
  comparison of antibiotic keys + interpretations).
- 1000-trial seeded simulation → empirical S/I/R proportions within 95%
  CI of antibiogram values.

### 8.2 Integration tests

`tests/integration/test_hai_susceptibility_chain.py` (new):

- `ForcedScenario.force_hai_event` for each (CLABSI, CAUTI, VAP) and each
  organism in the antibiogram. Verify:
  - `rec.microbiology[i].susceptibilities` non-empty.
  - All `antibiotic_loinc` values appear in `ANTIBIOTIC_LOINC_LOOKUP`.
  - `interpretation in {"S", "I", "R"}`.
  - `rec.microbiology[i].hai_event_id == rec.extensions["hai"][j].hai_id`
    (backref integrity, single HAI per encounter case).

Extend `tests/integration/test_hai_enricher_force.py`:

- Force-scenario exact-sequence test (post-PR-95 invariant) re-pinned: the
  HAI sub-rng draws are now `[organism_choice + N_antibiotic × choice(3,p)]`
  per HAI event. Exact total draw count must match the antibiogram-derived
  formula at the test-fixture level.

### 8.3 Audit run

`clinosim audit run` PASS at p=2000 (smoke) and p=10000 (full) on master vs
this PR. New silent_no_op proof must surface in the report's
`proof_eq_*` info lines (PR-94 framework feature).

### 8.4 Byte-diff

- Generate p=2000 baseline on master HEAD `6011b06e`.
- Generate same on the PR branch.
- Assert: every non-HAI NDJSON file is byte-identical.
- `microbiology.ndjson` and `cif/*.json` will differ; the diff is
  bounded by `N_HAI_events × (1 hai_event_id key + per-antibiogram S/I/R
  Observations)`. Report the line count in the PR body.

---

## 9. Verification gates (PR/merge process)

Following memory `feedback_pr_merge_dqr_required` and
`feedback_iterative_adversarial_review`:

1. `pytest -m unit -m integration -m e2e` all green (+12-15 new tests).
2. `clinosim audit run` PASS on all 4 axes (structural / clinical /
   jp_language / silent_no_op).
3. byte-diff: all non-HAI NDJSON byte-identical.
4. 3-axis DQR (US p=10k + JP p=5k), saved to
   `docs/reviews/2026-06-26-phase-3b-2-hai-susceptibility-data-quality-review.md`.
5. Full docs sync: `MODULES.md`, `SCENARIO_FLAGS.md`, `modules/hai/README.md`,
   `modules/antibiotic/README.md`, `DESIGN.md` (note AD-60 audit framework
   extension), `CLAUDE.md` (Phase 3b-2 entry), `TODO.md` (mark PR3b-2
   done; cite next is PR3b-3).
6. PR body includes audit summary + byte-diff line counts + DQR doc link.
7. **Post-merge adversarial review fan-out** (8 agents matching PR scope).
   If findings → fix PR. **Apply the iterative principle: the fix PR itself
   gets another adversarial review round** (`feedback_iterative_adversarial_review`).

---

## 10. Forward-compat for PR3b-3

By the end of PR3b-2 the following hooks exist for PR3b-3 narrow:

- `MicrobiologyResult.hai_event_id` → O(1) backref from culture to HAI.
- `AntibioticRegimen.discontinuation_datetime` → narrow truncation field.
- `AntibioticRegimen.intent` → already supports `"narrowed"` value.
- `SusceptibilityResult.interpretation` → narrow logic input.
- `hai_antibiogram.yaml` 8-antibiotic panel → all narrow target candidates
  covered.

PR3b-3 will: (a) walk `extensions["antibiotic"]`, (b) for each empirical
regimen find the matching culture via `hai_event_id`, (c) select a narrow
target from the susceptibility list where `interpretation == "S"` matches
clinical narrow-target rules (cefazolin for MSSA, etc.), (d) append a
`narrowed` regimen with `intent="narrowed"`, (e) set the original
empirical's `discontinuation_datetime` to the culture report date + 1d.

---

## 11. Non-scope (explicit)

- **PR3b-3 narrow chain** — not in this PR.
- **JP JANIS antibiogram** — country parameter is plumbed but JP returns
  US table until JANIS data is added.
- **Antibiotic-day decay (PR3b-4)** — not in this PR.
- **Mortality coupling (Phase 3c)** — not in this PR.
- **Community microbiology (modules/observation/microbiology.py)** —
  not modified; community pathogen cultures remain byte-identical.
- **JP locale display polish for S/I/R** — current FHIR adapter handles
  S/I/R as `interpretation` codes (English); JP display is a separate
  concern handled outside this PR.
