# scripts/

Maintainer utilities and CI helpers (Issue #568). This README explicitly
distinguishes "safe for anyone to run" from "assumes maintainer AWS /
EC2 / Bedrock access". If in doubt, treat a script as maintainer-only.

## CI-called

These are invoked by GitHub Actions workflows. Do not delete or rename
without also updating the workflow.

| Script | Called from | Purpose |
| --- | --- | --- |
| [`reproduce.sh`](reproduce.sh) | `.github/workflows/nightly.yml` | Regenerate a canonical cohort and diff against the reference — determinism regression gate |
| [`validate_jp.sh`](validate_jp.sh) | maintainer + smoke-run | Wraps the JP cohort validator (JP-CLINS lab compliance) — the CI workflow calls it via `clinosim eval` directly, but the shell wrapper is kept for local repro |
| [`pin_jp_validator.sh`](pin_jp_validator.sh) | maintainer + CI (SHA-pin refresh helper) | Refresh the SHA-256 pins on the `jpfhir.jp` JP-CLINS `.tgz` package. Run when a package rev bumps upstream |

## User-facing

These are safe for a package user to run against a locally-generated
cohort. They require nothing beyond `pip install -e .[dev]`.

| Script | Purpose |
| --- | --- |
| [`full_run_us.sh`](full_run_us.sh) | End-to-end run generating a US cohort with default settings — the "does clinosim work on my box" smoke test |
| [`full_run_ja.sh`](full_run_ja.sh) | Same, JP locale. Requires `CLINOSIM_JP_CLINS_PKG_DIR` env pointing at a JP-CLINS package dir |

## Maintainer-only (require AWS / EC2 / Bedrock access)

These scripts assume a maintainer environment (AWS credentials, EC2
SSH access, provisioned Bedrock quota). They are checked in for
reproducibility of maintainer-side workflows; a user running them will
hit a permission error.

| Script | Purpose | Assumption |
| --- | --- | --- |
| [`full_run_bedrock.sh`](full_run_bedrock.sh) | Full cohort + Bedrock LLM narrative pass | AWS Bedrock quota + `AWS_PROFILE` set |
| [`generate_with_bedrock.sh`](generate_with_bedrock.sh) | Same as above, thin wrapper | Same |
| [`test_bedrock_connection.py`](test_bedrock_connection.py) | Bedrock connectivity smoke test | AWS Bedrock quota |
| [`validate_bedrock_single.sh`](validate_bedrock_single.sh) | Single-patient Bedrock-narrative validate | AWS Bedrock quota |
| [`validate_5types_bedrock.py`](validate_5types_bedrock.py) | 5-doc-type Bedrock validation matrix | AWS Bedrock quota |
| [`run_ab_test_narrative.py`](run_ab_test_narrative.py) / [`.sh`](run_ab_test_narrative.sh) | Template-vs-LLM A/B run + comparison | AWS Bedrock quota |
| [`prepare_ab_test_prompts.py`](prepare_ab_test_prompts.py) | Prompt-corpus generator for A/B test | Local only, but pairs with the above |
| [`validate_ja_narratives.sh`](validate_ja_narratives.sh) / [`validate_ja_compact.sh`](validate_ja_compact.sh) / [`validate_ja_compact2.sh`](validate_ja_compact2.sh) | JP narrative validators (compare vs golden output) | Local only, but reference paths bake in maintainer directory layout |

## Data-refresh helpers

Called manually when the upstream authoritative source changes. Not on
any regular schedule.

| Script | Purpose |
| --- | --- |
| [`refresh_authoritative_loinc.py`](refresh_authoritative_loinc.py) | Refresh the LOINC common-lab table from the authoritative dump |
| [`refresh_authoritative_yj.py`](refresh_authoritative_yj.py) | Refresh YJ-code (drug) canonical map |
| [`refresh_authoritative_yj_tx_valid.py`](refresh_authoritative_yj_tx_valid.py) | Same, validating against tx-server |
| [`convert_ja_narrative_style.py`](convert_ja_narrative_style.py) | One-off stylistic conversion pass (JP narrative corpus) |
| [`audit_disease_narrative_en.py`](audit_disease_narrative_en.py) | English narrative audit (per-disease coverage) |
| [`diagnose_triage_severity.py`](diagnose_triage_severity.py) | Triage-severity distribution diagnostic |
| [`extract_5type_samples.sh`](extract_5type_samples.sh) | Extract 5 document-type sample bundles from a cohort |

## Retired / one-shot migrations

The following scripts were one-shot data-migration tools for closed
issues. They will be moved to `docs/history/scripts-archive/` in a
follow-up PR.

- [`patch_cif_procedures.py`](patch_cif_procedures.py) — one-shot CIF
  patcher for a closed procedure-field migration.

## When adding a script

Place under the appropriate section by asking: "can a user without
AWS credentials run this end-to-end?" — if yes, user-facing; if no,
maintainer-only. Update this README in the same PR.
