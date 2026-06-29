# PR3b-3 Clinical Axis Completion (D1 + D2) — Design

**Date**: 2026-06-29
**Author**: Tomo Okuyama + Claude (Opus 4.7)
**Status**: Draft (pending user approval)
**Branch**: `feat/pr3b-3-clinical-axis-completion` (to be created)

## Why

PR3b-3 (PR #107-#111) wired three audit clinical-axis gates for HAI antibiotic
susceptibility / narrow-de-escalation chain:

- NHSN R-rate gate per-(hai_type, organism, antibiotic)
- Empty-susceptibilities rate gate per panel-eligible HAI cohort
- Narrow-rate gate per-hai_type aggregate

Two of the three gates retained `# TODO(post-PR3b-3)` markers because they
required a per-encounter organism lookup the original PR did not implement.
The current behaviour is **safe** (masked by `n<30` WARN guards and rare-event
data scale) but **the gates are not yet measuring what the bands were
calibrated against**. At production scale (n>=30 per cohort) the masked gates
would either silently FAIL on correct behavior (D1) or always FAIL on
inflated denominator (D2).

This PR completes the per-organism filtering, deletes the two TODO markers,
and closes the PR3b-3 chain (no PR3b-3-related deferred TODOs remain).

## What is included

- `D1` = R-rate gate per-organism filter (`clinical.py:175-191` TODO)
- `D2` = Empty-rate gate panel-eligible filter (`antibiotic/audit.py:111-128` TODO)
- 1 shared helper: `_organism_per_encounter(cohort, country) -> dict[str, set[str]]`
- 1 derived helper: `_panel_eligible_organisms() -> dict[str, set[str]]`
- Test layered (unit + integration)
- audit re-run + optional band threshold adjust (same-PR)
- TODO comment removal + docs sync

## What is explicitly out-of-scope (deferred, separate backlog)

- Reference-data sibling sweep (hai_lab_lift / hai_rates / hai_codes /
  hai_specimens / hai_organisms reverse-coverage `_validate_*`)
- audit registry `_reset_for_test` ordering bug (5 pre-existing test failures
  on master, baseline)
- DESIGN.md AD-55/AD-60 PR3b-3 supplement section
- Emit `hai_event_id` as a FHIR identifier to distinguish HAI vs community
  cultures (scope creep; community contamination is rare in HAI cohort
  encounters and the antibiogram covers the same per-organism resistance
  regardless of HAI/community origin)

These are tracked separately and **must not be folded into this PR**. The
"finishing PR3b-3 chain" intent is to converge with **zero PR3b-3-related
deferred TODOs**; folding adjacent backlogs in dilutes the convergence.

## Architecture

### Helper 1: `_organism_per_encounter`

```python
def _organism_per_encounter(cohort: Cohort, country: str) -> dict[str, set[str]]:
    """Return {encounter_id: {organism_snomed, ...}} from microbiology Observations.

    Walks Observation.ndjson once, filters to mb-org-* organism observations
    that carry a valueCodeableConcept SNOMED code (growth observations).
    No-growth observations (valueString="No growth"/"発育なし") and non-mb
    Observations are skipped.

    A single encounter may have multiple cultures (CLABSI + secondary)
    yielding multiple organisms; all are accumulated into the set.
    """
```

- Pure FHIR-only walk. No CIF / state coupling.
- Input: `Cohort` lazy reader + `country` selector.
- Cost: O(n) where n = Observation count for the country.
- Side effect: none.

### Helper 2: `_panel_eligible_organisms`

```python
def _panel_eligible_organisms() -> dict[str, set[str]]:
    """Per-hai_type set of organisms with antibiogram entries (panel-eligible).

    Derived from load_hai_antibiogram() keys. Organisms without an antibiogram
    entry (E.faecalis 78065002, C.albicans 53326005, future no-panel additions)
    are automatically excluded — no hard-coded exclusion list.
    """
```

- Reads `hai_antibiogram.yaml` via cached `load_hai_antibiogram()`.
- Returns: `{hai_type: {organism_snomed, ...}}`.
- Cost: O(1) after first call (lru_cache hit on antibiogram).

### Placement

Both helpers added inline in `clinosim/audit/axes/clinical.py`. Rationale:

- scope-tiny (single file completion of PR3b-3 chain)
- reader can see the full gate semantic in one file
- if a future axis needs the same helpers, `extract function` refactor is
  trivial (1 caller → 2 callers is the canonical extract trigger)

### D1 Wiring (R-rate gate)

The existing block at `clinical.py:175-235` parses `band["cohort"].split("/")`
into `hai_type_b, _organism_b` but then computes `cohort_enc_set` as
`cohort_enc.get(hai_type_b, set())` — **organism is discarded**. The fix:

```python
org_per_enc = _organism_per_encounter(cohort, country)

for band in r_bands:
    hai_type_b, organism_b = band["cohort"].split("/", maxsplit=1)
    # ... abx_loinc lookup unchanged ...
    base_set = cohort_enc.get(hai_type_b, set())
    cohort_enc_set = {
        e for e in base_set if organism_b in org_per_enc.get(e, set())
    }
    if not cohort_enc_set:
        result.info[f"{country}_{band['cohort']}_{abx_key}_n"] = 0
        continue
    # ... susceptibility counting loop UNCHANGED (already filters by encounter)
```

The susceptibility counting loop already filters by `eid in cohort_enc_set`,
so narrowing the set automatically narrows the count. `n<30` WARN guard
remains in place for rare-event safety.

### D2 Wiring (empty-rate gate)

The existing block at `clinical.py:237-273` computes `all_cohort_encs` as the
union of all HAI cohort encounters and uses that as the denominator. The fix:

```python
panel_orgs = _panel_eligible_organisms()

panel_eligible_encs: set[str] = set()
for hai_type, encs in cohort_enc.items():
    eligible = panel_orgs.get(hai_type, set())
    for e in encs:
        if any(org in eligible for org in org_per_enc.get(e, set())):
            panel_eligible_encs.add(e)

enc_has_susc: dict[str, bool] = {e: False for e in panel_eligible_encs}
# ... rest of the gate UNCHANGED
```

Encounters whose only cultures are no-panel organisms (E.faecalis CLABSI,
C.albicans CAUTI) are excluded from both numerator and denominator,
restoring the NHSN denominator definition the 5% threshold was calibrated
against.

### TODO comment removal

- `clinical.py:175-191` — entire TODO block removed; replace with single-line
  comment explaining the per-organism filter
- `antibiotic/audit.py:111-128` — `HAI_EMPTY_SUSCEPTIBILITIES_MAX_RATE` block
  simplified; remove the `TODO(post-PR3b-3)` paragraph; keep the NHSN
  denominator-definition explanation as load-bearing rationale

### Calibration policy (Same-PR adjust)

After implementation, run `clinosim audit run` against a p=5000 US+JP cohort
(scratchpad/pr3b3_dqr_v2). Expected observations:

- R-rate gate: per-(hai_type, organism, abx) cohort sizes vary; bands
  pre-calibrated against per-organism rates (CDC NHSN AR 2018-2020) so
  observed rates should fall inside bands. If not, adjust bands within this
  PR with explicit `# source: NHSN AR 2018-2020 ...` provenance.
- Empty-rate gate: with panel-eligible denominator the observed rate should
  drop substantially (from ~28-34% no-panel inflation toward the production
  ~0.5% calibrated baseline). If still >5%, this signals a deeper data bug
  in the antibiogram loading and would require a separate investigation.

## Testing

### Unit (`tests/unit/test_clinical_axis_per_organism.py`, new)

- `_organism_per_encounter`:
  - mb-org-* + valueCodeableConcept SNOMED → mapping built correctly
  - id prefix mismatch (lab-*, vs-*) → skipped
  - encounter ref missing → skipped
  - valueCodeableConcept missing (no-growth) → skipped
  - multiple cultures per encounter → all organisms in set
  - empty Observation.ndjson → empty dict
- `_panel_eligible_organisms`:
  - all antibiogram organisms included per hai_type
  - E.faecalis (78065002) excluded automatically
  - C.albicans (53326005) excluded automatically
  - non-antibiogram hai_type → empty set

### Integration (`tests/integration/test_antibiotic_audit.py`, extended)

- D1: synthetic NDJSON with 2 organisms per hai_type → bands fire per
  organism cohort, NOT mixed
- D1: cohort with only one organism present → other organism's band yields
  n=0, no spurious FAIL
- D2: cohort with mix of panel-eligible + no-panel organism encounters →
  denominator excludes no-panel encounters
- D2: cohort with only no-panel organism encounters → panel_eligible_encs
  empty → gate skipped (no spurious FAIL)
- Regression: existing 37 PR3b-3 tests remain green
- n<30 WARN guard fires correctly when cohort small

### Pre-merge gate

`pytest tests/unit tests/integration -m "unit or integration"` full sweep —
**not** feature-specific subset (session 22 lesson, CLAUDE.md reinforced
rule).

### audit run + DQR

```bash
clinosim generate --country US --population 5000 --seed 42 --output scratchpad/pr3b3_dqr_v2/us
clinosim generate --country JP --population 5000 --seed 42 --output scratchpad/pr3b3_dqr_v2/jp
clinosim audit run -d scratchpad/pr3b3_dqr_v2
```

Record results in `docs/reviews/2026-06-29-pr3b-3-clinical-axis-completion-dqr.md`:

- per-(hai_type, organism, abx) observed R-rate vs band
- panel-eligible empty rate vs 5% threshold
- band adjustment decisions (same-PR, if any) with NHSN provenance

## Decision rationale

### HAI vs community culture separation (decided: ignore)

`mb-org-*` Observations carry no HAI-event backref in FHIR output
(`MicrobiologyResult.hai_event_id` exists in CIF but is not emitted). A
single HAI-cohort encounter could theoretically have a community-acquired
culture mixed in. We accept this for two reasons:

1. HAI is the primary culture indication in a HAI-cohort encounter;
   community contamination is rare (<5% in production-scale HAI cohorts).
2. The antibiogram measures per-organism resistance regardless of
   HAI/community origin; an S.aureus blood culture in a CLABSI patient is
   biologically the same organism whether it caused the line infection or
   colonized a wound.

If future evidence shows this contamination materially shifts R-rates,
emitting `hai_event_id` as a FHIR identifier is a separate small PR.

### Helper inline vs extracted (decided: inline)

YAGNI. 1 caller today. Extract trigger fires at 2 callers (canonical refactor
threshold). Inline keeps the gate semantic in one file for the next reader.

### Same-PR band adjustment vs follow-up PR (decided: same-PR)

"Finish PR3b-3 chain" intent. If audit reveals band drift, fixing it in the
same PR keeps the band threshold + filter implementation atomic and avoids
the "fix-then-recalibrate" PR sequence that fragments the chain.

## Risks + mitigations

| Risk | Mitigation |
|---|---|
| Per-organism filter narrows cohort below n=30 at p=5000 (R-rate gate WARN, not FAIL) | n<30 WARN guard already in place; rare-event safety. Acceptable for PR3b-3 chain closure. |
| Same-PR band adjustment expands scope | Bound: only adjust bands the audit run flags; document each adjustment with NHSN source. If >2 bands need adjustment, split into follow-up PR. |
| Helper introduces FHIR-output coupling that breaks if microbiology builder changes | Test asserts mb-org-* id prefix + valueCodeableConcept structure; regression catches builder drift. |
| Adversarial review finds the helper missing edge cases | Acceptable — that's the load-bearing purpose of the chain. Stage-1 fix expected, stage-2/3 hopefully converged. |

## Convergence criteria

Chain is considered closed (PR3b-3 chain complete-closure declared) when:

1. D1+D2 PR merged + green
2. audit run shows per-(hai_type, organism, abx) gates firing as intended
3. post-merge adversarial fan-out reaches converged stop (Critical 0,
   Important 0, finding converging, residual cosmetic only, next-stage
   expected size tiny — session 19 stopping criteria)
4. Both TODO markers (`clinical.py:175-191` + `audit.py:111-128`) removed
5. CLAUDE.md + `project_ehr_enrichment` memory updated to record "PR3b-3
   related deferred = 0"

## Expected PR count

Best 2 PR (main + docs convergence record), typical 3 PR (main + adv-1 fix +
docs), worst 4 PR (main + adv-1 + adv-2 + docs). Match PR #102 chain pattern
(short, 2-PR convergence) given the scope-small bug-fix nature.
