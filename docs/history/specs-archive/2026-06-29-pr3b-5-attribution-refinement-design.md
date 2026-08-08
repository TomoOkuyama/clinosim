# PR3b-5: Specimen-Organism Susceptibility Attribution Refinement — Design

**Date**: 2026-06-29
**Author**: Tomo Okuyama + Claude (Opus 4.7)
**Status**: Draft (pending user approval)
**Branch**: `feat/pr3b-5-attribution-refinement` (created)
**Prior chain**: PR3b-3 D1+D2 (PR #112-#116, 4-stage adversarial converged)

## Why

PR3b-3 D1+D2 chain closed (2026-06-29, master @ `0520c67aa4`) with one
explicit documented approximation: the R-rate gate joins susceptibility
Observations to a cohort encounter via the **encounter reference alone**.
At p=5000 spot check ~15-20% of microbiology encounters carry ≥2 specimens
(community + HAI culture co-occurrence in sepsis-then-HAI patterns,
multi-organism HAI events). This produces two attribution errors:

- **C1 multi-organism encounter double-count**: a CLABSI encounter that
  grows both S.aureus + S.epidermidis blood cultures double-counts cefazolin
  susceptibility rows under both organism bands.
- **C2 community + HAI co-occurrence**: a sepsis-admitted patient with
  community E.coli blood culture + later CLABSI S.aureus culture has both
  organisms attached to the same encounter; E.coli susc flow into the
  S.aureus MRSA band.

The PR3b-3 chain CLOSED claim was honest because: (a) n<30 WARN guards mask
the gap at simulator-scale cohorts, (b) integration tests behavioral verify
the per-organism filter, (c) DQR §"Known approximation" explicit
documentation prevents future-reader confusion. But the gap is real at
production cohort scale, and the user has elected (session 23, 2026-06-29)
to make **"PR3b-5 + sibling sweep both done"** the next breakpoint —
specifically because this approximation is the only remaining data-quality
/ clinical-coherence compromise.

This PR refines the attribution to be **truly per-(hai_type, organism,
antibiotic)** via specimen-based join + HAI identifier emission.

## What is included

- 2 new helpers in `clinosim/audit/axes/clinical.py`:
  - `_organism_per_specimen(cohort, country) -> dict[specimen_id, organism_snomed]`
  - `_hai_specimens(cohort, country) -> set[specimen_id]`
- 1 new FHIR canonical URI constant `HAI_EVENT_ID_SYSTEM` in
  `clinosim/modules/output/_fhir_microbiology.py`
- `MicrobiologyResult.hai_event_id` emitted as `Observation.identifier`
  (+ Specimen.identifier + DiagnosticReport.identifier for consistency)
  when non-empty (HAI-derived cultures only)
- D1 R-rate gate refactor: susc → specimen → organism join + HAI-only
  filter via `_hai_specimens`
- D2 empty-rate gate: unchanged (encounter-level semantics OK)
- Test layered (unit + integration), specifically pinning C1 + C2 resolution
- audit re-run + DQR documenting approximation 0 achievement

## What is explicitly out-of-scope (deferred to TODO.md formal entries)

All items below MUST be folded into TODO.md as part of this PR's docs sync
step. They are NOT addressed in PR3b-5:

| Item | Reason for defer | TODO.md placement |
|---|---|---|
| Sibling YAML loader sweep (hai_lab_lift / hai_rates / hai_codes / hai_specimens / hai_organisms additional reverse-coverage) | Separate chain immediately after PR3b-5 — user's stated breakpoint | Phase 3b backlog |
| PR3b-4 = WBC/CRP forward-delta decay | New feature, independent of PR3b-5 | Phase 3b backlog |
| audit registry `_reset_for_test` ordering bug | 10 fail master baseline; production code healthy | Test infra backlog |
| audit clinical axis Phase 2 (per-event observed-vs-theoretical enforcement) | New axis-level wiring, scope creep | Phase 3c backlog |
| NHSN clinical-accuracy band verification (CoNS / K.pneumoniae VAP / A.baumannii VAP) | Domain research required, scope creep | Reference data quality backlog |
| I1 WARN per-country diagnostic improvement | Diagnostic UX, no silent-no-op risk | Documentation polish backlog |
| 5 unused MB_*_PREFIX siblings cleanup (MB_SUS / MB_SPECIMEN / MB_DR) | YAGNI — currently no reader | Cleanup backlog |
| DESIGN.md AD-55 / AD-60 PR3b-3 supplement extended ADR text | Partial done; full ADR refinement is polish | Documentation polish backlog |

Folding any of these in dilutes the chain closure. Each gets a one-line
TODO.md entry with sufficient context so a future contributor (or
re-opened session) can pick it up.

## Architecture

### Helper 1: `_organism_per_specimen`

```python
def _organism_per_specimen(cohort: Cohort, country: str) -> dict[str, str]:
    """Return {specimen_id: organism_snomed} from microbiology Observations.

    Walks Observation.ndjson once, filters to mb-org-* organism observations
    with valueCodeableConcept SNOMED coding, extracts specimen_id from
    Observation.specimen.reference. No-growth observations + observations
    without specimen ref + non-canonical SNOMED URIs are skipped.

    Used by PR3b-5 D1 R-rate gate for true per-organism susc attribution
    (replaces the encounter-level approximation from PR3b-3).
    """
```

Cost: O(n) over Observation.ndjson per country (single pass, joined with
the gate's pre-existing susc walk).

### Helper 2: `_hai_specimens`

```python
def _hai_specimens(cohort: Cohort, country: str) -> set[str]:
    """Return set of specimen_ids that are HAI-derived (Observation.identifier
    carries HAI_EVENT_ID_SYSTEM canonical URI with non-empty value).

    Used by PR3b-5 D1 R-rate gate to filter out community-acquired culture
    susceptibilities that share an encounter with a HAI event (C2 resolution).
    """
```

Cost: O(n) over Observation.ndjson (joined with helper 1 walk in
implementation — single pass produces both outputs).

### FHIR identifier emission

```python
# clinosim/modules/output/_fhir_microbiology.py
HAI_EVENT_ID_SYSTEM = "http://clinosim/identifier/hai-event-id"
# Canonical internal-only system URI. clinosim simulator cross-reference
# only — not registered in JP Core / US Core / HL7 IGs. Future external
# integration would map this to a deployment-specific URI via locale config.
```

The FHIR builder writes `identifier` on Specimen / mb-org-* Observation /
mb-sus-* Observation / DiagnosticReport when
`MicrobiologyResult.hai_event_id` is non-empty. Community cultures
(`hai_event_id == ""`) get no identifier — byte-identical to pre-PR3b-5
output for those resources.

### D1 R-rate gate refactor

The existing gate (PR #115 master) loops over Observation.ndjson per band
and matches susc to cohort via encounter ref. Refactor:

1. Pre-compute `org_per_specimen` + `hai_specimens` once per country (same
   pass over Observation.ndjson).
2. For each band: walk susc Observations, extract specimen_id from
   `Observation.specimen.reference`, filter to `spec_id in hai_specimens`
   (HAI-only), match `org_per_specimen[spec_id] == organism_b`.
3. Keep cohort encounter pre-filter for defense in depth (re-verify via
   `_enc_id(row) in cohort_enc_set`).

### Helper placement

Both helpers inline in `clinosim/audit/axes/clinical.py`. Rationale:
matches the PR3b-3 D1+D2 helper placement, scope-tiny, single-file
gate semantic remains readable. Extract trigger fires at 2+ callers (none
yet — D2 stays encounter-level).

### Determinism (AD-16)

No new RNG. Helper functions are pure walks over FHIR NDJSON. FHIR
identifier emission is a deterministic field write from CIF data the
simulator already produces (`MicrobiologyResult.hai_event_id` was set at
PR3b-2 by `_append_hai_culture`).

### Byte-diff invariant

Intentionally broken (new field emission). audit run is the primary gate.
HAI-derived microbiology resources gain `identifier` field; community
cultures unchanged. Existing PR3b-2 / PR3b-3 e2e snapshot tests will
diff; refresh them with the new identifier present on HAI resources only.

## Testing

### Unit (`tests/unit/test_clinical_axis_per_organism.py` extended)

- `_organism_per_specimen`:
  - basic mb-org-* → specimen → organism
  - multi-specimen per encounter
  - no specimen ref → skipped
  - non-canonical SNOMED URI → skipped (defense layer 1 from PR #113)
  - empty file → empty dict
  - non-mb-org id → skipped
- `_hai_specimens`:
  - HAI specimen with identifier → included
  - community specimen without identifier → excluded
  - identifier with wrong system URI → excluded
  - identifier with empty value → excluded
  - empty file → empty set
- `HAI_EVENT_ID_SYSTEM` canonical constant import contract:
  audit clinical.py imports same constant as `_fhir_microbiology.py`;
  rename triggers ImportError (same defense pattern as MB_ORG_ID_PREFIX
  and ABX_ORDER_ID_PREFIX from PR #113 / #114).

### Integration (`tests/integration/test_antibiotic_audit.py` extended)

- **C1 resolution**: synthetic CLABSI encounter with 2 specimens (S.aureus +
  S.epidermidis), cefazolin susc on each. Verify the S.aureus band counts
  only the S.aureus-specimen susc; S.epidermidis-specimen susc go to no
  band (S.epidermidis not banded; verifies no double-count).
- **C2 resolution**: synthetic CLABSI encounter with both a HAI S.aureus
  specimen (identifier set) AND a community E.coli specimen (no identifier).
  Verify E.coli ceftriaxone susc do NOT inflate the S.aureus cefazolin
  band; verify community E.coli are NOT counted in any HAI band.
- **End-to-end FHIR builder**: drive `_bb_microbiology` with a
  MicrobiologyResult that has `hai_event_id` set → assert the Observation
  has `identifier[0].system == HAI_EVENT_ID_SYSTEM` and value equals the
  hai_event_id. Drive with `hai_event_id=""` → assert no identifier field
  emitted.
- All existing 31 PR3b-3 + D1/D2 tests remain green.

### Pre-merge gate (session 22 rule)

`pytest tests/unit tests/integration -m "unit or integration"` full sweep.
Failure count expected = current baseline (10) ± 0-2 from new tests
inheriting `_reset_for_test` cascade (out-of-scope deferred). Each new
failure must be the same root cause; any other failure blocks merge.

### audit run + DQR

```bash
clinosim generate --country US --population 5000 --seed 42 \
  --output scratchpad/pr3b5_dqr/us --format fhir-r4
clinosim generate --country JP --population 5000 --seed 42 \
  --output scratchpad/pr3b5_dqr/jp --format fhir-r4
clinosim audit run -d scratchpad/pr3b5_dqr | tee scratchpad/pr3b5_dqr/audit_output.txt
```

DQR doc `docs/reviews/2026-06-29-pr3b-5-attribution-refinement-dqr.md`:

- Update prior PR3b-3 DQR §"Known approximation" with cross-link
  "**RESOLVED via PR3b-5** (this PR)".
- New DQR records C1 + C2 resolution: per-organism cohort sizes,
  HAI-only filter coverage, no double-count, no community-susc leakage.
- Verdict: "PR3b-5 attribution refinement: VERIFIED. **PR3b-3 D1+D2
  approximation = RESOLVED.**"

## Convergence criteria — Complete Closure

This PR's chain (PR3b-5 main + adversarial fan-out) is CLOSED when:

1. **D1 R-rate gate joins susc → specimen → organism** (not encounter)
2. **FHIR `Observation.identifier` carries `HAI_EVENT_ID_SYSTEM`** for
   HAI-derived microbiology resources
3. **All integration tests pin C1 + C2 resolution** (zero approximation
   markers in test docstrings)
4. **DQR `"Known approximation"` section UPDATED to `"RESOLVED"`** in the
   PR3b-3 DQR (cross-link), and PR3b-5 DQR records the resolved state
5. **All out-of-scope items have formal TODO.md entries** (per the Out-of-scope
   table above)
6. **Post-merge 4-stage adversarial fan-out converged** (Stopping criteria
   from memory `feedback_iterative_adversarial_review`)
7. **CLAUDE.md + DESIGN.md + READMEs reflect PR3b-5 chain CLOSED state**

After PR3b-5 chain CLOSED, the next chain (sibling sweep) begins.

## Risks + mitigations

| Risk | Mitigation |
|---|---|
| Byte-diff breaks downstream consumers of pre-PR3b-5 output | Identifier field is additive; community-only resources unchanged. e2e snapshot refresh documented in DQR. |
| HAI_EVENT_ID_SYSTEM URI choice is arbitrary | Canonical constant in one location; future URI migration is one-line edit + integration test refresh. |
| `_organism_per_specimen` walk doubles memory cost at large p | Single-pass walk produces both helpers' outputs; per-country dict scales linearly with mb-org-* count (~1k at p=5k → negligible). |
| Adversarial review finds spec doesn't actually fix C1+C2 | Integration tests are designed to fail if the join is encounter-level not specimen-level; PR will not merge with failing tests. |
| Test cascade `_reset_for_test` bug worsens by adding tests | Pre-emptively count new test contributions; if cascade grows by >2, escalate (still out-of-scope per spec). |

## Expected PR count

Typical = 3 PR (main + adv-1 fix + docs convergence record). Best = 2 PR.
Worst = 4 PR (main + adv-1 + adv-2 + docs). Matches the scope-medium
new-feature PR pattern (PR3b-3 chain = 5 PR after adv-3 regression).

## Predecessor and successor

- **Predecessor**: PR3b-3 D1+D2 chain (PR #112 + #113 + #114 + #115 + #116)
- **Successor**: Sibling sweep chain (5 YAML loaders × _validate_* +
  reverse-coverage application) — kicks off immediately after PR3b-5
  CLOSED, completing the "PR3b-3 + sibling sweep" breakpoint declared
  by the user.

After **both** PR3b-5 + sibling sweep chains CLOSED, the breakpoint
("区切り") is declared with:
- データ品質: approximation 0 (no encounter-level approximation, no
  community/HAI mix, no specimen-level under-count)
- 臨床整合性: NHSN band semantics fully realized at production-scale
  (per-(hai_type, organism, antibiotic) calibration matches gate
  attribution)
- メンテ性: 6-layer silent-no-op defense applied to all hai_*.yaml
  loaders (sibling sweep result)
- コンセプト適切性: D1 R-rate gate measures exactly what its bands
  are calibrated against; D2 empty-rate gate denominator matches NHSN
  panel-eligible definition; documentation reflects state precisely
