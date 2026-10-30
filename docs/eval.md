# `clinosim eval` — public evaluation framework

`clinosim eval` scores a generated cohort against six axes — three
universal (**structural**, **clinical**, **locale**) and three
country-conditional (**jp_clins_lab_compliance**,
**jp_core_compliance**, **us_core_compliance**) — and emits a JSON +
Markdown report with per-check outcomes, an axis score (0–100), and
an overall score. Country-conditional axes activate only for cohorts
whose locale matches. The axis set is the `axes` dict in
`clinosim/eval/engine.py::EvalEngine`; each axis lives in
`clinosim/eval/axes/`.

It is **not** `clinosim audit run` (see
[`docs/CONTRIBUTING-modules.md`](CONTRIBUTING-modules.md) "PR verification guide"):

|  | `clinosim eval` | `clinosim audit run` |
|---|---|---|
| Intended user | External researcher / ML engineer | Contributor writing a PR |
| Input | Any FHIR NDJSON directory | Cohort produced during a Module PR |
| Output | Numeric score + violation list | PASS / FAIL / WARN per axis × Module |
| Requires Module registration | No | Yes (per-Module `audit.py`) |
| Report formats | JSON + Markdown | Markdown |

## Quick start

```bash
# Build one of the shipped presets (see datasets/README.md).
clinosim dataset build jp-100 --output ./jp-100

# Score it.
clinosim eval -d ./jp-100
```

Options:

```
clinosim eval
  -d/--cohort-dir DIR      Root of the generated cohort (contains fhir_r4/), or a
                           Synthea fhir/ output directory (auto-detected and
                           normalized before scoring)
  --json PATH              Write JSON report to PATH
  --md PATH                Write Markdown report to PATH
  --country CODE           Limit to one or more country subdirectories
                           (<cohort-dir>/<CODE>/fhir_r4/; repeat the flag).
                           Default: every discovered subdirectory. The locale
                           lens itself is taken from the subdirectory name, or
                           auto-detected from the first Patient's
                           address.country / JP Core meta.profile for the flat
                           <cohort-dir>/fhir_r4/ layout (fallback: US)
  --only-axes LIST         Comma-separated axis ids to run (e.g.
                           clinical,locale); unknown ids fail fast
  --synthea-normalize DIR  Where to write the normalized Synthea layout
                           (default: <cohort-dir>/../synthea-normalized/)
  --strict                 Exit 1 if any axis reports a FAIL check
```

## Axes

Structural + locale hold 5 checks each; clinical holds 7 (5 MVP +
2 coherence, added in P1-9). More checks land through issues tagged
`good first issue` on GitHub. Country-conditional axes activate per
cohort locale: `jp_clins_lab_compliance` and `jp_core_compliance`
run for JP cohorts, `us_core_compliance` for US cohorts. The
compliance axes hold 3 (`jp_clins_lab_compliance`), 7
(`jp_core_compliance`: Patient / Encounter / MedicationRequest) and 7
(`us_core_compliance`: Patient / Encounter / Condition) checks, each
gated on invariants that hold at 100 % on master. See
[eval-rules.md](eval-rules.md) for the per-check list. See [`clinosim.eval`](../clinosim/eval/README.md)
and `clinosim/eval/axes/` for the live full axis list.

### Structural (FHIR compliance)

| Check | Severity | What it asserts |
|---|---|---|
| `resource_id_uniqueness` | critical | No duplicate `id` within one resourceType |
| `reference_integrity` | critical | Every `reference` field resolves to an emitted resource |
| `required_fields_present` | major | Patient.identifier / Encounter.status / Condition.subject non-empty |
| `meta_profile_declared` | major (JP only) | Every JP Core primary resourceType declares `meta.profile` |
| `resource_type_consistency` | minor | Every NDJSON row's `resourceType` matches its filename |

### Clinical (coherence)

| Check | Severity | What it asserts |
|---|---|---|
| `lab_values_physiological_range` | major | LOINC-coded lab values fall inside physiological bounds (WBC, Hb, Cr, Glucose, K, Na, T-bili, PT-INR) |
| `age_condition_consistency` | major | No adult-only conditions on pediatric patients |
| `medication_date_sanity` | major | MedicationRequest.authoredOn ≥ Patient.birthDate |
| `encounter_temporal_ordering` | major | Encounter.period.start ≤ .end |
| `condition_encounter_link` | minor | When Condition.encounter is set, it resolves to an emitted Encounter |
| `condition_lab_coherence` | major | Sepsis lifts lactate, DKA drops HCO₃, MI lifts troponin, ... (8 pairings — see [eval-rules.md](eval-rules.md#condition_lab_coherence-major)) |
| `medication_lab_coherence_warfarin` | major | Warfarin patients' PT-INR sits in the 2.0–3.5 therapeutic band |

### Locale (language + code system)

Dispatched by cohort country: the country subdirectory name when the
cohort uses the `<root>/<country>/fhir_r4/` layout, otherwise
auto-detected from the first Patient's `address.country` or JP Core
`meta.profile` presence (fallback: US).

**JP checks:**

| Check | Severity |
|---|---|
| `japanese_displays_on_condition` | major |
| `jlac10_or_loinc_on_lab` | major |
| `yj_code_on_medications` | major |
| `jp_core_profile_declared` | major |
| `jp_name_order` | minor |

**US checks:**

| Check | Severity |
|---|---|
| `ascii_only_displays` | major |
| `rxnorm_present_on_medications` | major |
| `loinc_present_on_lab_observations` | major |
| `no_japanese_leakage` | critical |
| `us_practitioner_name_order` | minor |

## Scoring

Per-axis score = 100 × Σ(pass-weight) / Σ(total-weight), where:

- Severity weights: **CRITICAL = 3, MAJOR = 2, MINOR = 1**.
- Outcome weights: **PASS = 1.0, WARN = 0.5, FAIL / N/A = 0.0**.

Overall score = arithmetic mean of the score of every axis result in
the report (one result per axis × country subdirectory). A
country-conditional axis that does not apply to the cohort's locale
still appears in the report with an empty `checks` list and a score of
0.0, and it is included in that mean.
Overall status is `FAIL` if any check on any axis is FAIL, else
`WARN` if any is WARN, else `PASS`.

## JSON output shape

```json
{
  "eval_version": "1",
  "cohort_dir": "./jp-100",
  "generated_at": "2026-07-12T04:55:08.910006+00:00",
  "resource_counts": {"_flat": {"Patient": 41, "Encounter": 109, ...}},
  "overall_score": 83.3,
  "overall_status": "FAIL",
  "axes": [
    {
      "axis": "structural",
      "country": "_flat",
      "score": 100.0,
      "status": "PASS",
      "checks": [
        {
          "name": "resource_id_uniqueness",
          "outcome": "PASS",
          "severity": "critical",
          "weight": 3,
          "message": "All resource ids are unique within their resourceType.",
          "detail": {}
        },
        ...
      ]
    },
    ...
  ]
}
```

## Programmatic use

```python
from clinosim.eval import EvalEngine

engine = EvalEngine(cohort_dir="./jp-100")
report = engine.run()

print(report.overall_score, report.overall_status)
for axis in report.axes:
    print(axis.axis, axis.score, axis.status)
    for check in axis.checks:
        if check.outcome.value == "FAIL":
            print("  FAIL:", check.name, check.message)
```

## Extending

To add a check:

1. Open the relevant file under `clinosim/eval/axes/`.
2. Add a `_check_<name>(cohort, country) -> EvalCheck` helper.
3. Append it to the axis's `run()` return list.
4. Add a unit test in `tests/unit/test_eval_axes.py` that crafts a
   minimal mini-cohort triggering the FAIL outcome.
5. Update `docs/eval.md` and `CHANGELOG.md`.

The 5-check MVP is intentional — the framework is worth more than any
one check. Small, well-scoped additions are easier to review than a
one-shot 30-check rewrite.
