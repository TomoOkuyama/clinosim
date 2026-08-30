# LLM prompt YAML audit — 2026-08-30

Audit of every file under `clinosim/modules/llm_service/prompts/{ja,en}/`
for consistency with the recent narrative-CIF changes (PR #979–#986,
#988, #990–#992, and the death-cert / death-discharge-summary chain
#961/#965).

Branch: `chore/llm-prompt-audit-2026-08-30`.
Repo master reviewed at: `5877661226`.

## Reachability analysis (essential context)

Only **two** prompt YAML files are wired into the current narrative
pipeline (`clinosim/modules/document/narrative/replacement_strategy.py`
lines 442, 631):

| File | Path | Purpose |
| --- | --- | --- |
| `narrative_seed.yaml` | ja/en | per-section fallback (`_apply_template_seed_strategy`) |
| `narrative_seed_bundle.yaml` | ja/en | bundle strategy — mainline for every `template_seed_bundle` spec since session-88j |

Every other file (`admission_hp`, `discharge_summary`, `death_summary`,
`death_certificate_contributing/duration`, six `death_discharge_summary_*`,
`operative_note`, `procedure_note`, `referral_note`) is reachable ONLY
via `LLMService.generate(task_type=X, ..., variables={...})`
(`engine.py:385`).  A grep of the tree finds no production callsite
that passes `variables=` — only three unit tests (`test_llm_service.py`
lines 42/48/60/66/73/88/94/101/102) exercise `LLMService.generate` with
`variables=None`, which takes the legacy hardcoded `_build_prompt`
branch and NEVER reads the YAML.

Consequently every non-`narrative_seed*` prompt file is currently
dormant.  This is not necessarily wrong — the `referral_note.yaml`
description explicitly documents itself as a "per-task 直接 generate
経路の fallback 向け" — but audit findings on those files are
low-severity: they do not affect real narratives today.

## Per-file findings

Doc-type-based grouping (JA + EN combined). Verdicts:
**consistent** / **drift** / **dead** / **unclear**.

### `narrative_seed_bundle.yaml` (JA + EN) — **LIVE**, drift + fixed

Verdict: **drift** (partly fixed inline, remainder tracked as Issue).

Findings:

1. **[FIXED inline]** Stale cross-reference `see Rule 8` in the Context
   contract line for `hospital_day_label` (JA line 118, EN line 104).
   Rules were consolidated 11 → 5 in v9; the pointer to Rule 8 was left
   behind.  Rewritten to `see Rule 3` (VERBATIM COPY, the block that
   actually governs `hospital_day_label`).  Version bumped 11 → 12.

2. **[FIXED inline]** Typo `today's_vitals_summary` in the JA and EN
   `### progress_note` guidance (line 313 / 233).  The declared context
   key (line 60 / 48) is `todays_vitals_summary` without the apostrophe;
   Rule 2 REQUIRED INCLUSION also uses the underscore form.

3. **[Issue A — non-trivial]** Missing per-doc-type guidance for
   `operative_note` and `procedure_note`.  Both were promoted to
   `template_seed_bundle` in PRs #991 / #992 (`document_type_specs.yaml`
   lines 498–563), and their `llm_enabled_sections` (`op_findings`,
   `op_course`, `op_postop_plan` / `pn_course`, `pn_complications`,
   `pn_postop_plan`) flow through this bundle prompt — but there is no
   `### operative_note` or `### procedure_note` block in the
   `=== Per document_type ===` section.  The generic Hard Rules still
   apply, but the LLM does not know that op_findings is meant to be
   intraoperative-only, op_postop_plan is a handoff sentence, etc.

4. **[Issue B — non-trivial]** Missing per-doc-type guidance for
   `death_certificate` and `death_discharge_summary`.  These are
   `template_seed_bundle` with LLM-eligible sections
   (`duration_of_immediate_cause`, `contributing_conditions` /
   seven death-summary sections).  Same shape gap as Issue A — the
   LLM has no per-doc-type contract for tone (legal-form vs
   physician-authored narrative) or length caps.

5. **[Minor, informational — not filed]** Context contract does not
   explicitly enumerate every enrichment key added by #941 (admit /
   dispo), #942 (NKA), #946 (BMI/vitals), #973 (IV rate).  The keys
   are still surfaced through `todays_vitals_summary` /
   `active_medications_today` and the "surface every context key
   present" Rule 2 covers them behaviourally, so no functional drift.

6. **[Minor, informational — not filed]** EN localization block (Rule
   5) is a single dense paragraph vs the JA version's structured
   A–F subsections.  Both cover the same tokens; JA is more
   readable because the localization applies mostly to JA output.

### `narrative_seed.yaml` (JA + EN) — **LIVE**, consistent

Verdict: **consistent**.

Small, generic per-section refinement contract.  Compatible with every
enrichment PR because it does not enumerate context keys — the seed +
patient context is passed in as opaque text.

### `admission_hp.yaml` (JA + EN) — **DEAD / reserve**

Verdict: **dead** (unreachable from production).

Findings:

- Section list "1. 主訴 / 2. 現病歴 / … / 11. Plan" is a classic 11-section
  H&P layout.  Does not reflect #979 (vitals prepended to physical exam)
  or #984 (HPI enrichment), but the prompt says "only use facts provided
  in the input" so the substitution would still be defensible.
- User template variable names (`${admission_datetime}`,
  `${hpi_summary}`, `${admission_vitals}`, `${initial_labs}`,
  `${admission_diagnosis}`) do not correspond to any current caller.
- No clinical facts to correct.

### `discharge_summary.yaml` (JA + EN) — **DEAD / reserve**

Verdict: **dead**.

- JA hard cap `600字以内`, EN "under 500 words" reflect the old direct-
  generate contract, not the modern bundle strategy that emits full
  hospital_course prose.  Not a bug because unreached; a documentation
  claim if this file were ever revived.
- Preserve-verbatim clause names "検査値、処置、薬剤 (dates and drug
  names)" — does not mention ICD codes explicitly.  Bundle prompt
  (LIVE) covers this fully.

### `death_summary.yaml` (JA + EN) — **DEAD / reserve**

Verdict: **dead** (double-dead — LOINC 69730-0 is NOT registered as a
`DocumentType` per prior audit; `LLMTaskType.DEATH_SUMMARY` exists in
`engine.py:53` but nothing dispatches to it).

Recommendation: mark as reserve-for-future in a header comment or delete.
Filed as Issue D.

### `operative_note.yaml` (JA + EN) — **DEAD / reserve**

Verdict: **dead**.

- 14-section US layout and 400字以内 JA cap look correct for a direct
  operative-note prompt but are superseded by `template_seed_bundle` +
  the new `_build_op_*` builders.  Not reached in production.
- Templates authoritatively fill 9 sections (`op_procedure_name` …
  `op_postop_plan`); only three are LLM-eligible.

### `procedure_note.yaml` (JA + EN) — **DEAD / reserve**

Verdict: **dead**.  Same shape as `operative_note.yaml`.  Templates fill
eight `pn_*` sections; three are LLM-eligible via the bundle path.

### `referral_note.yaml` (JA + EN) — **DEAD / reserve** (documented)

Verdict: **dead** — but the file's own description already explains that
production runs via the bundle path.  This is the model for how the
other dormant prompts should be documented if we choose to keep them.

### `death_certificate_contributing.yaml` (JA + EN) — **DEAD / reserve**

Verdict: **dead** (per-section prompt files are not read by any
callsite; the section-level bundle path uses `narrative_seed_bundle.yaml`
via `apply_replacement_strategy` and looks up ONE prompt, not
per-section).

- Content is defensible — matches the semantic contract for the
  contributing-conditions section on the physical death-certificate form.
- Variable set (`${chronic_conditions}`, `${complications_occurred}`,
  `${primary_cause_display}`, `${primary_cause_code}`,
  `${disease_pattern}`, `${template_seed}`) does not correspond to any
  caller.

### `death_certificate_duration.yaml` (JA + EN) — **DEAD / reserve**

Verdict: **dead**.  Same reasoning as `death_certificate_contributing`.

### `death_discharge_summary_admission_state.yaml` (JA + EN) — **DEAD / reserve**

Verdict: **dead**.

### `death_discharge_summary_treatment_course.yaml` (JA + EN) — **DEAD / reserve**

Verdict: **dead**.

### `death_discharge_summary_terminal_course.yaml` (JA + EN) — **DEAD / reserve**

Verdict: **dead**.

### `death_discharge_summary_circumstances_of_death.yaml` (JA + EN) — **DEAD / reserve**

Verdict: **dead**.

### `death_discharge_summary_family_communication.yaml` (JA + EN) — **DEAD / reserve**

Verdict: **dead**.

### `death_discharge_summary_autopsy_findings.yaml` (JA + EN) — **DEAD / reserve** (naming drift)

Verdict: **dead + naming drift**.

The spec's llm-enabled section key is `autopsy_status_and_findings`
(document_type_specs.yaml lines 436 / 450; `_build_dds_autopsy_status_
and_findings` template_generator.py line 6048) — the file basename says
`autopsy_findings`.  Not currently harmful (nothing looks up the file
by section key), but if the per-section prompt path is ever revived
the file will silently mis-match.  See Issue C.

### `death_discharge_summary_complications_and_comorbidities.yaml` — **MISSING**

`document_type_specs.yaml` lists `complications_and_comorbidities` in
both `composition_sections` (line 434) and `llm_enabled_sections` (no —
wait, it is in llm_enabled at line 448).  Seven llm-enabled DDS
sections; six per-section prompt files present.  The missing sibling
is `death_discharge_summary_complications_and_comorbidities.yaml` (both
JA and EN).  Consistent with the fact that these files are dormant —
but if the per-section fallback is ever wired up it would 404.  See
Issue C.

## Summary table

| Prompt file | JA | EN | Verdict |
| --- | --- | --- | --- |
| narrative_seed_bundle | drift → fixed + Issue A/B | drift → fixed + Issue A/B | drift |
| narrative_seed | consistent | consistent | consistent |
| admission_hp | dead | dead | dead |
| discharge_summary | dead | dead | dead |
| death_summary | dead (no DocType) | dead (no DocType) | dead |
| operative_note | dead | dead | dead |
| procedure_note | dead | dead | dead |
| referral_note | dead (documented) | dead (documented) | dead |
| death_certificate_contributing | dead | dead | dead |
| death_certificate_duration | dead | dead | dead |
| death_discharge_summary_admission_state | dead | dead | dead |
| death_discharge_summary_treatment_course | dead | dead | dead |
| death_discharge_summary_terminal_course | dead | dead | dead |
| death_discharge_summary_circumstances_of_death | dead | dead | dead |
| death_discharge_summary_family_communication | dead | dead | dead |
| death_discharge_summary_autopsy_findings | dead + naming drift | dead + naming drift | dead |
| (missing) death_discharge_summary_complications_and_comorbidities | missing | missing | dead (would 404) |

Counts:

- consistent: 1 (narrative_seed)
- drift (fixed inline or filed): 1 (narrative_seed_bundle)
- dead: 14 (13 present + 1 missing)
- unclear: 0

## Inline fixes applied

- `narrative_seed_bundle.yaml` (both JA and EN): `see Rule 8` → `see Rule 3`.
- `narrative_seed_bundle.yaml` (both JA and EN): `today's_vitals_summary`
  → `todays_vitals_summary`.
- Version bumped 11 → 12 with a description-block changelog entry.

## Issues to file

- **Issue A**: Add `### operative_note` and `### procedure_note`
  per-doc-type guidance blocks to `narrative_seed_bundle.yaml`
  (both JA and EN).
- **Issue B**: Add `### death_certificate` and `### death_discharge_summary`
  per-doc-type guidance blocks to `narrative_seed_bundle.yaml`
  (both JA and EN).
- **Issue C**: Decide the fate of the 14 dormant per-task prompt files
  (delete as dead code, or restore the per-task `LLMService.generate`
  callsite and fix the two per-section-file naming gaps — missing
  `death_discharge_summary_complications_and_comorbidities.yaml` and
  `death_discharge_summary_autopsy_findings.yaml` vs spec key
  `autopsy_status_and_findings`).
- **Issue D**: `death_summary.yaml` (LOINC 69730-0) has no
  `DocumentType` registration — either wire it into `document_type_specs.yaml`
  or remove the prompt files and the `LLMTaskType.DEATH_SUMMARY` enum
  value.

## Verification

- `pytest tests/unit -x -q` — green.
- `pytest tests/integration/test_check_narratives_mock.py -x -q` — green.
- `ruff format . && ruff check .` — clean.
