# Session 93 continuation — v0.6.0 Tier-1 + Tier-2 complete (2026-08-31)

## Scope of this session

Continuation of session 93. Started with all Wave-1/2 fixes merged
(#1003-#1010) and a premature `v0.6.0` tag that had been cut earlier
in the day. Wrapped with all Tier-1 + Tier-2 scope closed and Tier-3
(chemo cycle scheduling + perinatal chain — architecture-level changes)
deferred pending direction from the maintainer.

## Timeline

| # | Commit / PR | What |
|---|-------------|------|
| 1 | PR #1012 (`chore: unrelease v0.6.0`) | Deleted GitHub Release + `v0.6.0` tag (remote + local) after review of the released scope revealed unfinished sub-scope on Issues #914 / #957 / #757. Reverted `__version__` to 0.5.0 and collapsed `[0.6.0]` back into `[Unreleased]` with an explanatory note. |
| 2 | PR #1013 (`feat(monitoring): remaining 5 mappings`) | Added statin / ACE-i-ARB-diuretic / digoxin / lithium / tacrolimus / ciclosporin mappings on top of the Foundation shipped in #1010. New baselines + reference ranges + LOINC codes for the 4 drug-level analytes. **Closes #757.** |
| 3 | PR #1014 (`fix(discharge-carryforward)`) | Root-cause trace of hypertension × antibiotic co-emission led to `helpers._deactivate_to_layer1`: acute short-course therapy (`duration_days ≤ 14`) was carried forward as chronic home meds and re-prescribed at every subsequent visit. Added a cutoff filter. **Closes #914 Bucket B.** Verified: 0/295 hypertension encounters carry any antibiotic MR post-fix (was 18/295). |
| 4 | PR #1015 (`feat(oncology): 5 additional JP cancers`) | Added C15 esophageal / C16 gastric / C25 pancreatic / C67 bladder / C71 glioma with follow-up schedules + prevalence per MHLW 患者調査 2020 + 国立がん研究センター がん統計 2020. Male C50 (~1 %) intentionally deferred. |
| 5 | PR #1016 (`feat(oncology): RT Procedure emit`) | Registered M001 / M001-2 / M001-3 in k-codes.yaml. Added `radiation_therapy_eligible: true` flag to 9 cancer follow-up entries (C15/C16/C18/C22/C25/C34/C50/C61/C71; C67 omitted per bladder-cancer clinical practice). Emit fires at 40 % per-visit probability via isolated per-encounter sub-rng (master-rng shape preserved). Verified: 0 → 1 RT Procedure at p=500. |

## Design axes considered before each PR

Per the maintainer's directive that scope decisions be evaluated
against data quality, clinical coherence, temporal consistency,
module responsibility, and OSS structure appropriateness, the
"why data-only vs why sim-logic-change" question was posed
explicitly for each PR:

- **#1013 remaining monitoring mappings** — pure data / YAML.
  Foundation shipped in #1010 supports the pattern. Zero simulation
  logic change.
- **#1014 discharge carry-forward** — sim logic change scoped to a
  single 4-line filter in an existing function. Root cause was
  clearly identified by tracing MR authorship; alternative fixes
  (adding an `end_date` field to `HomeMedication`) would have been
  broader architectural changes with no data-quality upside.
- **#1015 additional cancer YAMLs** — pure data / YAML.
- **#1016 RT Procedure** — small sim logic change (~35 new lines) in
  existing outpatient dispatch path. Alternative (new oncology
  enricher module) would have been over-scoped for the "0 records"
  gap being closed.

Tier-3 items (chemo cycle scheduling + perinatal chain) require new
cross-encounter state machines / multi-patient generation
respectively; the maintainer preferred wrap-then-decide over inline
implementation.

## Metrics — release-gate spot checks at wrap

Full p=1000 JP verification was run for the earlier v0.6.0 attempt
(PR #1011); the four subsequent PRs (#1013-#1016) preserve or
improve those numbers:

| Metric | v0.5.0 baseline | Post PR #1011 (p=1000) | Post PR #1016 |
|--------|----------------:|-----------------------:|--------------:|
| Patient-hex leaked Observation ids | 32,690 | **0** | 0 |
| ImagingStudy CT/MR/US < 60 min pairs | 780 | **0** | 0 |
| Visit-reason Z-code Conditions | ~14,384 (43 %) | **0** | 0 |
| AVPU × GCS same-day in-range | 48.0 % | **99.8 %** | 99.8 % |
| MR ↔ MA frequency match | 23.5 % | **55.4 %** | 55.4 % |
| Pyelonephritis ≥ 3-antibiotic count | 72 | **2** | 2 |
| Hypertension encounters × antibiotic MR | 18 (of 295) | 18 | **0** (this session) |
| US warfarin patients with ≥ 1 PT_INR | 0 / 6 | 4 / 4 | 4 / 4 |
| RT Procedure resources | 0 | 0 | **1** (at p=500) |
| Tumor marker Observations | 0 | 9 (at p=500) | 9 |

Unit + integration test surface: **5,116 pass + 1 xpass** (+ 5 new
tests this session for the #757 remaining mappings).

## Remaining for v0.6.0 (Tier 3)

See `.resume-prompt.md` (repo-root, gitignored per project convention)
for the full architecture-option matrix. Summary:

- **#957 chemo cycle scheduling** — two architectural options
  ("full state machine" ~2-3 days / "scheduled recurring visits"
  ~1-1.5 days). Maintainer preferred the lighter option at wrap.
- **#957 perinatal chain** — two architectural options
  ("full multi-patient chain" ~3-5 days / "mother-side only"
  ~1 day). Maintainer preferred the lighter option at wrap.
- **#957 male C50** — small (~2 hours) paired change.

## Files touched (net additions)

- **New module**: `clinosim/modules/monitoring/` (Foundation shipped
  in #1010, extended in #1013).
- **New YAML config values**: `radiation_therapy_eligible`,
  `duration_days` cutoff (14).
- **New analytes**: 6 tumor markers + 4 drug levels — baselines +
  UCUM units + reference ranges (JP + US) + LOINC codes.
- **New K-codes**: M001 / M001-2 / M001-3 (radiation therapy).

Full file inventory in `.resume-prompt.md`.
