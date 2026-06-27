# PR3b-3 — HAI culture S/I/R driven narrow / de-escalation chain (design)

**Status**: design (approved 2026-06-27, brainstorming session)
**Branch**: `feat/pr3b-3-narrow-de-escalation`
**Predecessors**: PR #93 (PR3b-1 empirical) / PR #96-#98 (PR3b-2 antibiogram S/I/R)
**Verification gate**: `clinosim audit run` (AD-60) + 3-axis DQR (US p=10000 + JP p=5000)
**byte-diff invariant**: **broken intentionally** (new-feature PR, not refactor) — empirical MAR truncation + new narrow Order/MAR + `MedicationRequest.status` change. Documented in PR body.

## 1. Background

PR3b-1 (PR #93) introduced the `modules/antibiotic/` always-on Module that emits IDSA empirical regimens for every HAI event (`extensions["hai"]`). PR3b-2 (PR #96 + #97 + #98) extended `modules/hai/_append_hai_culture` so each HAI-derived `MicrobiologyResult` carries antibiogram-driven `SusceptibilityResult` items (S/I/R) and a `hai_event_id` backref.

Three forward-compat reserves shipped in those PRs that PR3b-3 must consume to be load-bearing:

- `AntibioticRegimen.intent: str = "empirical"` — PR3b-3 reserves the `"narrowed"` value
- `AntibioticRegimen.discontinuation_datetime: datetime | None = None` — PR3b-3 sets this when an empirical regimen is truncated
- `MicrobiologyResult.hai_event_id: str = ""` — PR-B writes the `HAIEvent.hai_id`; PR3b-3 reads it to look up the susceptibilities for a given empirical regimen

In addition, `modules/antibiotic/audit.py` surfaces `_NHSN_RESISTANCE_BANDS` and `HAI_EMPTY_SUSCEPTIBILITIES_MAX_RATE` in `clinical_acceptance` metadata but the clinical axis does **not** actively enforce them (TODO marker at `audit.py:58-66, 115`). PR3b-3 closes this TODO by wiring active enforcement in `clinosim/audit/axes/clinical.py`.

PR3b-3 also adds a self-audit gate (**narrow rate** per (hai_type, organism) cohort) so the chain itself is protected against PR-90-class silent-no-op regressions.

## 2. Design decisions

### 2.1 narrow target selection = ladder YAML walk (Q1)

Per-(hai_type, organism_snomed) narrow→broad ladder YAML. Walk top-down, accept the first drug with `interpretation == "S"`. I and R skip to the next ladder entry. Empty / all-non-S → no narrow (empirical continues).

Rejected alternatives:
- **Decision-tree YAML** (MRSA / MSSA / ESBL +/- branches) — schema complexity + tree evaluator itself is PR-90 silent-no-op risk
- **"Preserve first-S empirical drug"** — does not exercise `intent="narrowed"` reserve, no true switch capability

### 2.2 enricher placement = same `enrich_antibiotic` 2-pass (Q2)

`enrich_antibiotic(ctx)` in `modules/antibiotic/enricher.py` is extended with a Pass 2 that runs after Pass 1 (empirical regimen + Order + MAR generation). POST_ENCOUNTER stage, order=85 unchanged. Same sub-seed (no new RNG draws — `select_narrow_target` is pure).

Rejected alternatives:
- **New `narrow_enricher.py` at order=90** — breaks the 1-module-1-enricher convention (`modules/<name>/enricher.py`) and starts a new pattern
- **Separate `modules/narrow_antibiotic/` module** — cross-module mutation (modifying `modules/antibiotic` outputs from a sibling module) violates AD-16 responsibility boundaries

### 2.3 ladder data model = per-(hai_type, organism_snomed) full enumeration (Q3)

`narrow_ladder[hai_type][organism_snomed] = [drug_key, drug_key, ...]` — three-level nested YAML, identical schema to `hai_antibiogram.yaml`. Each (hai_type, organism, abx_key) entry is cross-validated at import time against `hai_antibiogram.yaml` (i.e., a ladder may only reference combinations the antibiogram actually models). Cross-validation also checks `hai_type in HAI_TYPES` and `abx_key in ANTIBIOTIC_DRUGS`.

I (intermediate) is **not** an acceptable narrow target (CLSI guidance: narrow target must be S; I requires either dose escalation or different drug — neither is what narrow chain models).

Fallback for ladder-empty or all-non-S: **empirical continues unchanged** (no `discontinuation_datetime`, no new regimen). This is also IDSA standard ("if culture non-susceptible, continue empirical broad-spectrum").

### 2.4 discontinuation data model = narrowing by elimination (Q4)

Three clinical cases:

| Case | Example | Action |
|---|---|---|
| **(i) switch** | CLABSI/MSSA (cefazolin S, empirical = vanc + pip-tazo) → narrow target = cefazolin (not in empirical) | All empirical regimens get `discontinuation_datetime = reported_datetime`. New `AntibioticRegimen(intent="narrowed", ...)` for cefazolin added. New Order + MAR added. |
| **(ii) elimination** | CLABSI/MRSA (cefazolin R, vancomycin S, empirical = vanc + pip-tazo) → narrow target = vancomycin (in empirical) | Empirical regimen with `drug_key == narrow_target` is **kept unchanged**. All other empirical regimens get `discontinuation_datetime = reported_datetime`. No new regimen / Order / MAR added. |
| **(iii) no change** | CAUTI/E.coli/ESBL- (ceftriaxone S, empirical = ceftriaxone alone) → narrow target = ceftriaxone (= empirical, single drug) | **Nothing happens.** Empirical continues unchanged, no `discontinuation_datetime`, no new regimen. |

Rationale: Same drug must not appear in two `AntibioticRegimen` objects per HAI event (data quality + FHIR `MedicationRequest` timeline clarity).

`intent="narrowed"` load-bearing rate: case (i) only. Estimated population: ~30-40% of HAI events (MSSA CLABSI 47% × 53% S ≈ 25% + MSSE CLABSI minor + E.coli ESBL+ CAUTI / VAP narrow-to-meropenem). This is sufficient for the reserve to be load-bearing in audit and adversarial review.

### 2.5 timing, duration, MAR truncation, FHIR status (Q5)

| Item | Value |
|---|---|
| narrow decision trigger time | `MicrobiologyResult.reported_datetime` (= HAI onset + 2 days, hardcoded in `modules/hai/enricher.py`) |
| empirical `discontinuation_datetime` | `reported_datetime` (set on each truncated empirical regimen; case (i) all / case (ii) non-narrow-target subset) |
| narrow regimen `start_datetime` | `reported_datetime` (case (i) only) |
| narrow regimen `duration_days` | `total_course - elapsed_days`, where `total_course = empirical.duration_days` (from `hai_empirical.yaml`: 14 / 7 / 7) and `elapsed_days = (reported_datetime - empirical.start_datetime).days` (typically 2). Dynamic calc so changing `hai_specimens.yaml` reported-offset propagates automatically. |
| empirical `Order.duration_days` | **unchanged** (placement intent preserved, FHIR `dispenseRequest.expectedSupplyDuration` retains 14 / 7 — the discontinuation is reflected via `status="stopped"` and MAR truncation, not by mutating placement). |
| empirical MAR | truncated by reusing `generate_mar_doses` pattern with `stop_datetime = min(snapshot, regimen.discontinuation_datetime)` (no doses scheduled past `stop_datetime`). |
| narrow Order | new `Order(order_type=MEDICATION, status=ACCEPTED, display_name=ANTIBIOTIC_DRUGS[narrow_drug]["name"], ordered_datetime=reported_datetime, duration_days=narrow_duration, reason_condition=hai_event_id)` (mirrors empirical Order shape, status=ACCEPTED matching Pass 1). |
| narrow MAR | `generate_mar_doses(narrow_regimen, snapshot_datetime, narrow_order_id)` (existing helper, no changes). |
| regimen_id naming | empirical: existing `abx-{hai_id}-{drug_slug}`. narrow: `abx-{hai_id}-{drug_slug}-narrowed` (suffix prevents collision when narrow drug = empirical drug, e.g., MRSA CLABSI elimination case keeps the empirical regimen as-is so no collision anyway, but suffix is defensive). |

### 2.6 FHIR `MedicationRequest.status` wiring

`clinosim/modules/output/_fhir_medications.py` is extended so that when emitting `MedicationRequest` from an `AntibioticRegimen` (the only place `discontinuation_datetime` is meaningful), the FHIR resource's `status` field is set to:

- `"stopped"` if `regimen.discontinuation_datetime is not None`
- `"active"` otherwise (existing default)

This is a CIF-side typed field flowing to FHIR — the existing `_fhir_medications.py` builder is the natural single edit point. Non-antibiotic medications (e.g., DVT prophylaxis from disease YAMLs) are unaffected (they do not pass through `AntibioticRegimen` and have no `discontinuation_datetime`).

### 2.7 audit clinical axis active enforcement (Q6)

`clinosim/audit/axes/clinical.py:run()` is extended to actively enforce three new gates that complement (not replace) the existing HAI WBC/CRP delta gate:

1. **NHSN R-rate gate** — for each entry in `_NHSN_RESISTANCE_BANDS`:
   - Find all `Observation.ndjson` rows with `code.coding[].code == LOINC[antibiotic]` and `valueCodeableConcept.coding[].code == "R"` belonging to encounters in the (hai_type, organism) cohort
   - Compute `observed_R_rate = R_count / total_count`
   - Gate: `expected_R_min <= observed_R_rate <= expected_R_max` → PASS, else FAIL
   - Cohort size < 30 → WARN (small-p Bernoulli noise margin, mitigated by silent_no_op lift_firing_proof)

2. **empty susceptibility rate gate** — denominator is panel-eligible HAI cultures only (organism in antibiogram, i.e., excluding E. faecalis 78065002 + C. albicans 53326005 as documented in `audit.py:103-115`):
   - Compute `observed_empty_rate = (cultures with empty SusceptibilityResult list) / (panel-eligible HAI cultures)`
   - Gate: `observed_empty_rate <= HAI_EMPTY_SUSCEPTIBILITIES_MAX_RATE` (0.05) → PASS, else FAIL

3. **narrow rate gate** (new, PR3b-3 self-audit) — per (hai_type, organism) cohort:
   - Compute `observed_narrow_rate = (HAI events with at least one `extensions["antibiotic"]` regimen having `discontinuation_datetime is not None` OR `intent == "narrowed"`) / (total HAI events in cohort)`
   - Per-cohort acceptance band defined in new `clinical_acceptance["narrow_rate_bands"]` (list[dict] mirroring `_NHSN_RESISTANCE_BANDS` shape: `{cohort: "<hai_type>/<organism_snomed>", expected_narrow_rate_min, expected_narrow_rate_max, source}`)
   - Cohort size < 30 → WARN
   - Zero observed narrow rate in any cohort where narrowing is expected → FAIL (PR-90-class silent-no-op detection)

Empirical bands (derived from antibiogram S-rates):
- CLABSI / S. aureus (3092008): expected_narrow_rate_min=0.40, max=0.60 (cefazolin S = 53% → ~53% switch to cefazolin)
- CAUTI / E. coli (112283007): expected_narrow_rate_min=0.10, max=0.30 (ceftriaxone R-rate ≈ 12-22% per NHSN AR 2018-2020; ESBL+ events trigger switch to meropenem, ESBL- events are case (iii) no-change → cohort narrow rate ≈ ceftriaxone R-rate)
- VAP / S. aureus (3092008): expected_narrow_rate_min=0.40, max=0.60

Bands cited from NHSN AR 2018-2020 source data (already in antibiogram YAML).

### 2.8 lift_firing_proof PR3b-3 extension

`_build_combined_proof` in `modules/antibiotic/audit.py` is extended with a third sub-proof that exercises Pass 2 against a synthetic CLABSI/MSSA case (cefazolin S in seed=0). Six equality_checks added:

1. `narrow_target_drug` = `"cefazolin"`
2. `empirical_vancomycin_discontinued_at` = `reported_datetime`
3. `empirical_pip_tazo_discontinued_at` = `reported_datetime`
4. `new_narrowed_regimen_count` = `1`
5. `new_narrowed_regimen_drug` = `"cefazolin"`
6. `new_narrowed_regimen_intent` = `"narrowed"`

Total `equality_checks` in `_build_combined_proof`: 8 (PR3b-1) + 3 (PR3b-2) + 6 (PR3b-3) = **17**.

Per the existing exception isolation pattern (`audit.py:262-274` after PR #98 MED-3), a PR3b-3 sub-proof exception isolates to its own 1-tuple FAIL marker rather than dropping the PR3b-1 + PR3b-2 checks.

## 3. Files

### New

- `clinosim/modules/antibiotic/reference_data/narrow_ladder.yaml`
- `tests/unit/test_narrow_ladder.py`
- `tests/unit/test_narrow_engine.py`
- `tests/integration/test_narrow_enricher.py`
- `docs/reviews/2026-06-27-pr3b-3-narrow-de-escalation-data-quality-review.md` (post-implementation DQR)

### Modified

- `clinosim/modules/antibiotic/engine.py` — `load_narrow_ladder()` + 3-way cross-validation + `select_narrow_target(susceptibilities, ladder_for_organism) -> str | None` + `narrow_regimens(empirical_regimens_for_event, microbiology, snapshot, ladder) -> NarrowOutcome`
- `clinosim/modules/antibiotic/enricher.py` — Pass 2 (microbiology backref lookup → `narrow_regimens(...)` → mutate empirical / append new Order/MAR/regimen per outcome)
- `clinosim/modules/output/_fhir_medications.py` — `MedicationRequest.status` from `regimen.discontinuation_datetime`
- `clinosim/modules/antibiotic/audit.py` — `narrow_rate_bands` in `clinical_acceptance` + `_build_combined_proof` extension with 6 PR3b-3 equality_checks + ladder canonical-constants assertion at import time
- `clinosim/audit/axes/clinical.py` — three new enforcement blocks (NHSN R-rate, empty rate, narrow rate)
- `tests/integration/test_antibiotic_audit.py` — verify each new gate fires correctly under forced HAI cohort
- `clinosim/modules/antibiotic/README.md` — document narrow chain + ladder schema
- `clinosim/modules/hai/README.md` — link to PR3b-3 consumer
- `CLAUDE.md` — Phase 3b-3 entry (Module independence / current implementation phase / silent-no-op defense triplet sections)
- `TODO.md` — strike PR3b-3, update roadmap
- `MODULES.md` — antibiotic module description update

### Unchanged

- All other `clinosim/types/*.py` (no new typed fields — `intent` + `discontinuation_datetime` already reserved)
- `clinosim/modules/hai/*` (PR3b-3 only reads `record.microbiology`, no write)
- All other enrichers
- All disease / encounter YAMLs

## 4. Data flow

```
[POST_ENCOUNTER cascade]
  device (order=70)    → extensions["device"]
  hai    (order=80)    → extensions["hai"] + record.microbiology
  antibiotic (order=85):
    Pass 1: per HAIEvent → empirical AntibioticRegimen(s)
            + Order(MEDICATION, status=ACCEPTED, duration_days=total_course)
            + MAR doses (snapshot-bounded)
    Pass 2: for each empirical regimen in extensions["antibiotic"]:
              micro = find_microbiology_by_hai_event_id(regimen)
              if micro is None: continue
              if micro.reported_datetime > snapshot: continue  # AD-32
              narrow_target = select_narrow_target(
                  micro.susceptibilities,
                  ladder[micro.hai_type][micro.organism_snomed]
              )
              outcome = narrow_outcome(narrow_target, empirical_regimens_for_event)
              dispatch outcome:
                NO_CHANGE        → continue
                ELIMINATION      → set discontinuation on non-target empirical;
                                   truncate their MAR; no new regimen
                SWITCH           → set discontinuation on all empirical;
                                   truncate all their MAR; append new
                                   narrowed AntibioticRegimen + new Order + new MAR
```

## 5. Error handling / edge cases

- **`snapshot < reported_datetime`**: narrow decision skipped (empirical continues unchanged, AD-32 partial data semantics)
- **`MicrobiologyResult` not found for `hai_event_id`**: defensive skip — invariant violation but production state would mean hai enricher silently failed, in which case empirical also has nothing to narrow to. No `raise`.
- **all ladder entries non-S**: empirical continues (no `discontinuation_datetime`)
- **empty `susceptibilities` list**: same as above (treated as "no S in ladder")
- **narrow target = empirical single drug** (case (iii)): nothing happens
- **`narrow_ladder.yaml` entry references unknown (hai_type, organism, abx)**: `ValueError` at import time (3-way cross-validation against `HAI_TYPES` + `hai_antibiogram.yaml` + `ANTIBIOTIC_DRUGS`)
- **`MedicationRequest.status` for non-antibiotic medications**: unchanged (the `discontinuation_datetime` field exists only on `AntibioticRegimen`; other CIF medication paths do not pass through this regimen type)

## 6. Testing strategy

### Unit

`tests/unit/test_narrow_ladder.py` (≈5 tests):
- `test_load_succeeds` — happy path, structure check
- `test_unknown_hai_type_raises` — cohort `"CLABSI"` (uppercase) → ValueError
- `test_unknown_organism_raises` — organism not in `hai_organisms.yaml` for that hai_type → ValueError
- `test_unknown_antibiotic_raises` — drug_key not in `ANTIBIOTIC_DRUGS` → ValueError
- `test_ladder_entry_not_in_antibiogram_raises` — (hai_type, organism, abx) combination absent from `hai_antibiogram.yaml` → ValueError

`tests/unit/test_narrow_engine.py` (≈8 tests):
- `test_select_narrow_target_first_S_wins` — basic walk
- `test_select_narrow_target_skips_R_and_I` — non-S entries skipped
- `test_select_narrow_target_returns_none_on_empty_ladder`
- `test_select_narrow_target_returns_none_on_all_non_S`
- `test_select_narrow_target_returns_none_on_empty_susc`
- `test_narrow_outcome_no_change` — case (iii)
- `test_narrow_outcome_elimination` — case (ii)
- `test_narrow_outcome_switch` — case (i)

### Integration

`tests/integration/test_narrow_enricher.py` (≈5 tests):
- `test_clabsi_mssa_switch_to_cefazolin` — case (i) with FHIR status check
- `test_clabsi_mrsa_elimination_pip_tazo_stops_vanc_continues` — case (ii)
- `test_cauti_ecoli_esbl_negative_no_change` — case (iii)
- `test_cauti_ecoli_esbl_positive_switch_to_meropenem` — case (i) variant
- `test_snapshot_before_reported_no_narrow` — AD-32 edge case

`tests/integration/test_antibiotic_audit.py` (existing file extended, ≈4 new tests):
- `test_clinical_axis_nhsn_r_rate_gate_fires` — population-scale R-rate gate works under forced HAI cohort
- `test_clinical_axis_empty_susc_rate_gate_fires`
- `test_clinical_axis_narrow_rate_gate_fires_for_mssa_clabsi`
- `test_lift_firing_proof_pr3b_3_six_new_equality_checks_pass`

### e2e golden

Existing golden files must be regenerated (this is a new-feature PR, byte-diff invariant intentionally broken). New goldens committed in same PR.

### audit

`clinosim audit run` over US p=10000 + JP p=5000 generation. All 4 axes must PASS (or WARN where rare-event acceptable). DQR document at `docs/reviews/2026-06-27-pr3b-3-narrow-de-escalation-data-quality-review.md` records:
- narrow rate per (hai_type, organism) cohort
- NHSN R-rate observation vs band
- empty susceptibility rate
- before/after FHIR resource counts (MedicationRequest with status=stopped, intent=narrowed)
- 4-axis verdict + WARN/FAIL details if any

## 7. Determinism (AD-16)

PR3b-3 adds **no new RNG draws**. `select_narrow_target` is a pure function over already-determined `SusceptibilityResult` items (these are sampled in HAI enricher's own sub-seed). All narrow outcomes are fully determined by the upstream HAI/microbiology decision.

The 2-pass structure inside `enrich_antibiotic` does not add any new sub-seed (no `derive_sub_seed` call). The cascade order (70 → 80 → 85) is unchanged.

byte-diff: empirical MAR will be shorter (truncation) + new narrow Order/MAR added + MedicationRequest.status differs. This is the expected, intentional change of the new feature; `clinosim audit run` is the primary gate (not byte-diff).

## 8. Verification gate (per CLAUDE.md "PR/Merge前DQR必須")

This is a **new-feature PR**, so:

- **primary gate**: `clinosim audit run` 4 axes (structural / clinical / jp_language / silent_no_op) all PASS or WARN-with-justification
- **DQR**: `docs/reviews/2026-06-27-pr3b-3-narrow-de-escalation-data-quality-review.md`
- **e2e golden**: regenerated and committed in same PR (golden change is the feature change)
- **post-merge**: adversarial review fan-out (4-stage chain pattern from session 17 / 19 / 20 / 21)

byte-diff Full (US p=10000 + JP p=5000) is **NOT** run as a gate (would fail by construction), only as evidence of which NDJSON files change and by how much.

## 9. Out of scope

- **PR3b-4 = WBC/CRP forward-delta decay after antibiotic start** — separate PR, pairs naturally with PR3b-3 (narrow → decay)
- **eGFR-based dose modification** — `hai_empirical.yaml` comment already flags this as future work
- **Duration extension for complicated bacteremia** (e.g., S. aureus bacteremia → 4-6 weeks if metastatic) — not modeled
- **Multi-drug narrow** (e.g., empirical 2 drugs, narrow to 2 different drugs) — current scope: select_narrow_target returns one drug_key, eliminate or switch is single-drug
- **PR_C type consolidation** (7 modules → `clinosim/types/`) — separate refactor PR
- **audit clinical axis Phase 2 per-event observed-vs-theoretical verification** — separate PR (this PR adds population-level gates only)

## 10. Stopping criteria (adversarial chain)

Per `feedback_iterative_adversarial_review`: stop the adversarial review chain when:
- Critical / Important = 0 in the latest fan-out
- findings are converging (count diminishing across rounds)
- remaining items are cosmetic / docs / test-only
- next-round expected fix size is tiny (< 5 commits)

Document the convergence verdict in the final fix PR body so the basis for stopping is explicit.
