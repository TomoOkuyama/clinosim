# Historical scratchpad archive

Archived working files from `scratchpad/` at the repo root — byte-diff
scripts, per-PR audit reports, and raw logs used during specific past
PR investigations. Not part of the runtime or test path.

Kept for historical traceability: the numeric results in `*_results.md`
are the audit evidence that supported specific merge decisions in the
`bmp_cl_ca` / `cbc_bmp` / `coag_panel` / `hai` / `phase2a` / `phase2b` /
`phase3a` / `pr3` / `refactor_pr1-2` / `device` chains. Scripts (`*.py`)
are the tools that produced those reports.

Files were moved on 2026-08-07 as part of the repo-hygiene series
(PR B of A-G). The `scratchpad/` directory at the repo root is now
gitignored — future maintainer working files live untracked there.

## Naming conventions

- `<feature>_byte_diff.py` — per-PR byte-diff generator
- `<feature>_byte_diff_results.md` — output of that generator
- `<feature>_dqr_<country>.md` — Data-Quality Review markdown
- `<feature>_dqr_*.log` — raw pytest / cohort output the DQR summarizes
- `dqr_<name>_review.py` — adversarial review scripts

No cross-references from live docs. If any of the audit findings need to
be promoted to permanent documentation, move the specific `*_results.md`
to `docs/reviews/` and add a proper archive front-matter.
