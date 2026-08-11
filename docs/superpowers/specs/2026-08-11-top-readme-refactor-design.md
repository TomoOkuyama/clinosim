# Phase 2 — Top README refactor design

**Date**: 2026-08-11
**Related Issue**: #718 (Phase 1 done, rows 4 + 6 folded into this Phase)
**Related maintainer direction**: "global OSS project, English default, `.ja.md`
for Japanese; top README should be OSS-standard shape, short, contributor-
friendly"

## Goal

Refactor the repository root `README.md` from its current 286-line
form into a short, major-OSS-standard landing page (target ~100
lines), migrate the extracted content into `docs/` so nothing is
lost, and bring `README.ja.md` along in structural parity.

Also close #718 by wiring in the two "no README by design" exclusion
notes that were deferred out of Phase 1 (top-level `clinosim/`
package and `clinosim/modules/identity/providers/`).

## Non-goals

- Rewriting `CONTRIBUTING.md`, `AGENTS.md`, `DESIGN.md`, or any
  in-repo module README (Phase 1 covered the module dirs).
- Translating docs/ pages into Japanese (JA docs are a separate,
  future Phase 3 scope; JA README will link to EN docs annotated
  with `(英語)` per existing module convention).
- Changing the docs site theme, mkdocs plugin set, or hosting
  arrangement.
- Introducing new CI jobs. Existing `mkdocs build` job continues to
  guard link integrity.

## File-change inventory

| Kind | Path | Change |
| --- | --- | --- |
| New | `docs/getting-started/configuration.md` | Absorbs the current README `Configuration` section (CLI flags + env vars tables). |
| New | `docs/getting-started/first-cohort.md` | Absorbs the current README `Sample output — one physiology-driven lab` (full JSON + narrative). |
| Modify | `docs/synthea-comparison.md` | Absorbs the current README Synthea comparison table + when-to-use guidance; existing overlapping content is deduplicated. |
| Modify | `docs/architecture/data-flow.md` | Appends the pipeline SVG block (`docs/assets/pipeline.svg`) with alt text. |
| Modify | `docs/getting-started/quick-start.md` | Adds a next-step link to `first-cohort.md`. |
| Modify | `docs/README.md` | Registers the two new files in the "For users" section. |
| Modify | `mkdocs.yml` | Adds the two new files to `nav`. |
| Rewrite | `README.md` | 286 → ~100 lines. Also includes a one-line note that top-level `clinosim/` package has no dedicated README by design (#718 row 4). |
| Rewrite | `README.ja.md` | Mirrors new EN structure section-for-section (~100 lines). |
| Modify | `pyproject.toml` | `[project.urls] Documentation` from `github.com/…#readme` → `https://tomookuyama.github.io/clinosim/`. |
| Modify | `clinosim/modules/identity/README.md` | Appends a one-line note under the existing "Providers" section stating that `providers/` is intentionally not README-covered because the parent section documents the dispatch pattern (#718 row 6). JA companion updated in the same commit. |
| Unchanged | `CONTRIBUTING.md` | Already comprehensive; slim README will point to it. |
| Unchanged | `docs/architecture/**` (other files) | Existing content is used as-is by the slim README's `Learn more` link. |

## New root `README.md` structure

Target: **~100 lines**. Section budget:

```
Header (title + tagline + docs link + JA link)                [4]
Badges (CI / Docs / PyPI / Python / License / FHIR)            [6]
Callouts (personal-project disclaimer + synthetic-data only)   [4]

## What is clinosim?                                          [12]
   2-3 short paragraphs. Names the single differentiator
   (physiology-driven forward simulation, clinical coherence
   by construction).

## Install                                                    [10]
   pip install clinosim + dev install from a clone.

## Quick start                                                [10]
   One US-cohort command producing FHIR NDJSON (matches the
   current README's US example). Link to
   docs/getting-started/configuration.md for the full CLI
   reference; JP cohort, presets, and hospital-config override
   handled via docs.

## See it in action                                            [8]
   4-6 line narrative: warfarin patient → PT-INR 2.7
   therapeutic band. Link to first-cohort.md for the full
   JSON walkthrough.

## Why clinosim?                                              [10]
   Three differentiator bullets (coherence / JP native /
   YAML-driven). Prior-art (Synthea) mentioned in a single
   line with link to docs/synthea-comparison.md.

## Learn more                                                 [12]
   Link table:
     - Documentation site
     - Architecture reference
     - Module index
     - Data quality & eval
     - JP-CLINS profile support
     - Contributing
     - AI-agent conventions
     - Changelog

## Community                                                   [8]
   Bullets:
     - Code of Conduct
     - Security policy
     - Good first issues
     - Issue templates
     - Citation → CITATION.cff (GitHub button)

## License                                                     [3]
   MIT + one line pointing bundled code-system licences to
   clinosim/codes/README.md.

Note: also includes the one-line #718-row-4 note that
top-level `clinosim/` package has no dedicated README.
Placed near Learn more or as a footnote.

Total ≈ 90 lines.
```

## `README.ja.md` parity strategy

The Japanese README is a **structural mirror**, not a summary and
not a superset. Rules:

1. Section headings match one-for-one in order and level. `## Why
   clinosim?` in EN ↔ `## なぜ clinosim か` in JA.
2. Content is equivalent-translation, not summary or omission.
3. Links: EN links to EN docs; JA links to the same EN docs (JA docs
   scope is Phase 3) annotated with `(英語)` where the target is
   English-only — the same pattern the module JA READMEs already use.
4. Code blocks, CLI examples, and other literals are identical
   between the two files. Comments inside code blocks stay in
   English (matches the code-comment-language policy).
5. **Same-commit rule**: any change to `README.md` must ship in the
   same PR as the matching change to `README.ja.md`. One-language-
   only PRs are not permitted for either file after this refactor.
6. **EN is authoritative**: on conflict, EN is source of truth. JA
   gets fixed to match EN, never the reverse.
7. This refactor **does not translate any docs/ file into JA**. JA
   translations of docs/ pages are Phase 3 scope.

## Content-migration map

Each removed / relocated section from the current root README, and
where its content ends up:

| Current section (lines) | New location | Handling |
| --- | --- | --- |
| Header + badges + disclaimers (1-19) | Same, in new README | Kept |
| What clinosim does (20-30) | New README `## What is clinosim?` | 3 paragraphs → 2, use-case bullets kept |
| Why + 3 differentiators (33-52) | New README `## Why clinosim?` | Bullets kept, prose trimmed |
| Synthea comparison (53-77) | `docs/synthea-comparison.md` (modified) | Existing content deduplicated; table + when-to-use merged in |
| Sample output JSON (79-120) | `docs/getting-started/first-cohort.md` (new) | Full JSON + narrative moved; root retains 4-6 line snippet + link |
| Pipeline diagram (122-126) | `docs/architecture/data-flow.md` (modified) | SVG block appended with alt text; asset stays under `docs/assets/` |
| Install (130-145) | New README `## Install` | Unchanged |
| Quick start (147-169) | New README `## Quick start` | US example kept; JP + preset examples collapsed into a single "→ Documentation" line |
| Configuration (171-195) | `docs/getting-started/configuration.md` (new) | Both tables moved verbatim; adds a note pointing to `clinosim simulate --help` |
| Architecture at a glance (197-222) | Split — `## Learn more` link table in root; `docs/architecture/README.md` (existing) is the actual entry; `clinosim/modules/README.md` (from Phase 1) is the module list | Current 7-bullet module list is removed from the root (superseded by the module index) |
| Data quality (224-233) | `## Learn more` — one row | Detail lives in `docs/eval.md` + `clinosim/audit/README.md` + `clinosim/eval/README.md` |
| Contributing (235-253) | `## Learn more` — one row pointing to `CONTRIBUTING.md` | CI-requirement list removed from root (already in CONTRIBUTING.md) |
| Governance table (255-264) | New README `## Community` | 6-row table → 5-bullet list |
| License detail (266-276) | New README `## License` — one line | Bundled code-system licences → `clinosim/codes/README.md` |
| Citation BibTeX (278-286) | Removed from README | `CITATION.cff` already exists and drives the GitHub "Cite this repository" button |

## PR sequence and gates

Three PRs, strictly serial (PR-A → PR-B → PR-C) to avoid dead links
during the transition. CI wait for each is parallelizable via
background watch (Phase 1 recipe).

### PR-A — docs receiver files (goes first)

Scope: the seven docs-side changes in the inventory table.

Gates:
- `mkdocs build --strict` green (link check + nav integrity)
- Every cross-reference target in new files exists
- Existing root README's links are unchanged and still live
- Full CI green (docs job + integration shards)

Post-merge state: root README is unchanged, docs are enriched. No
regression risk to consumers.

### PR-B — root README + JA rewrite (the main change)

Scope: `README.md` rewrite + `README.ja.md` mirror rewrite. Single
commit including both files (parity rule 5).

Gates:
- All link targets exist (grep for cross-refs, includes PR-A's new
  docs)
- EN and JA section heading count, order, and level match (mechanical
  diff)
- Badges and docs-site link render correctly on GitHub
- `mkdocs build --strict` green
- Full CI green

Post-merge state: slim OSS-standard root README delivered.

### PR-C — cleanup: pyproject + #718 residuals

Scope:
- `pyproject.toml [project.urls] Documentation` → hosted docs URL
- `clinosim/modules/identity/README.md` — one-line note that
  `providers/` is intentionally not README-covered (parent already
  documents the pattern). Closes #718 row 6.
- New root README already includes the equivalent note for
  top-level `clinosim/` (row 4). Verified in this PR.
- Closes #718 in the PR body.
- Comment on #633 noting condition 1 is verifiable green, ask
  maintainer to close.

Gates:
- `python -m build` reproduces the new Documentation URL in wheel
  metadata (spot check)
- Post-merge inline audit — this loop should print zero un-noted gaps:
  ```
  for d in $(find clinosim -type d ! -path '*__pycache__*'); do
    if ls "$d"/*.py > /dev/null 2>&1; then
      test -f "$d/README.md"    || echo "EN missing: $d"
      test -f "$d/README.ja.md" || echo "JA missing: $d"
    fi
  done
  ```
  Only `clinosim` (row 4, documented in root README) and
  `clinosim/modules/identity/providers` (row 6, documented in
  parent identity/README.md) are permitted misses.
- Full CI green

Post-merge state: #718 closes, #633 becomes close-eligible.

## Verification checklist (per PR)

Every PR must satisfy:

- `mkdocs build --strict` succeeds locally before push
- `grep`-based cross-reference audit shows no dead links
- `git branch --show-current` before push (not on `master`)
- DCO signoff on every commit
- PR body self-contained (no local-file references)

Every PR-B / PR-C additionally:

- EN and JA README diff shows matching section structure
- Removed content is genuinely reachable via the new location (spot-
  check each removed section)

## Open items deliberately deferred to implementation

Decisions the implementation plan will make (not blocking spec
approval):

- **Badges**: current 6 kept. Additional candidates (`good first
  issue` count, etc.) evaluated at plan time.
- **`Learn more` formatting**: table vs bullet list.
- **`Community` formatting**: table vs bullet list.
- **"See it in action" wording**: how to compress the PT-INR
  narrative to 4-6 lines while keeping the "hidden state chose the
  therapeutic band" beat intact.
- **Exact placement of the row-4 note** (top-level `clinosim/` no-
  README note): footnote at bottom of README, or a line inside
  `Learn more`.

## Success criteria

- Root `README.md` is between 80 and 120 lines.
- Root `README.ja.md` is within ±15% of the EN line count and
  section-structure-identical.
- Every relocated section is fully reachable from the new location
  (no truncation, no summarization loss).
- `mkdocs build --strict` remains green.
- No dead links in any of the modified files (grep audit).
- #718 becomes closeable at the end of PR-C.
- #633 success-measure condition 1 becomes verifiable green at the
  end of PR-C (conditions 2 and 3 already green after PR #720).

## Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| PR-B has a dead link because PR-A wasn't merged first | Strict PR order (A → B → C). PR-B's checks include a cross-ref audit that would catch this. |
| JA README drifts from EN in a future edit | Same-commit rule (parity rule 5) codified in the PR-B body and echoed here. Future PR reviewers check the diff mentions both files or explains why not. |
| Existing docs/synthea-comparison.md and the migrated content conflict on tone | PR-A includes a deduplication pass; the migrated content is merged into the existing structure, not appended. |
| Removed Citation BibTeX confuses users who bookmarked it | `CITATION.cff` already exists and produces a superset (BibTeX + APA); the GitHub "Cite this repository" button is more discoverable than a README block. Low risk. |
| Hosted-docs URL change in pyproject.toml breaks packaging | Verified with `python -m build`; the URL is metadata, not a runtime dependency. Low risk. |

## Timeline (rough)

- PR-A: ~30 min to write + 15 min CI + 5 min merge
- PR-B: ~45 min to write (EN + JA) + 15 min CI + 5 min merge
- PR-C: ~15 min to write + 15 min CI + 5 min merge

Sequential dependency means end-to-end wall clock is roughly the sum
of the write times + one CI wait window (background-watched);
practical target = same session or split across two sessions.
