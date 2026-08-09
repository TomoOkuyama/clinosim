# Constants and magic-number audit — 2026-08-09

**Scope**: named-constant discipline across `clinosim/**/*.py` per
[Documentation + code-quality policy §5](../design-guides/documentation-and-code-quality-policy.md#5-constants-and-configuration).

**Baseline commit**: `master` `628326b6e2b`.

**Purpose**: publish a project-wide baseline so subsequent constants-cleanup
PRs can be scoped, prioritised, and measured. This is a **read-only audit
report** — no source code is renamed by the PR that publishes this file.

## 1. What §5 requires

Every scalar constant, threshold, cutoff, or magic number that affects
patient state, clinical logic, resource output, or a user-visible number
must be:

1. **Named** — never inlined as a bare literal in the middle of an
   expression.
2. **Docstring-annotated** with purpose, unit, and source / rationale.
3. **Located** in a module-local `_constants.py` / `_thresholds.py`, the
   module's public `__init__.py`, `clinosim/config/*.yaml`, or
   `clinosim/types/config.py`.

## 2. Baseline numbers

Reproduce (2026-08-09 against `master` `628326b6e2b`):

```bash
# Bare numeric literals in production code (rough upper bound; includes
# integers and decimals, may double-count within docstrings)
find clinosim -name '*.py' -not -path '*/reference_data/*' \
  -exec grep -ohE '\b[0-9]+\.?[0-9]*\b' {} + | wc -l

# Already-named module-scope constants (SCREAMING_SNAKE_CASE)
grep -rnE '^[A-Z_][A-Z0-9_]{2,}\s*[=:]' clinosim/ --include='*.py' | wc -l

# Existing _constants / _thresholds files (compliant models)
find clinosim -name '_constants.py' -o -name '*_thresholds.py' \
              -o -name '*_defaults.py' -o -name '_coupling*.py' \
              -o -name '_reference*.py'
```

Result:

| Metric | Value |
|---|---:|
| Bare numeric literals in `clinosim/**/*.py` | ~13,048 |
| Named module-scope constants | 653 |
| Existing `_constants` / `_thresholds`-style files | 3 |

The 13,048 count is a rough upper bound: it counts every numeric token,
including obviously-out-of-scope literals like tuple indices, RNG seeds,
loop bounds, unit conversions, and numeric tokens inside code strings
(e.g. LOINC codes such as `"8867-4"` are picked up by the regex). The
in-scope subset (values that materially affect patient state / clinical
logic / resource output / user-visible numbers) is a smaller fraction —
see §5 for the triage bucket split.

## 3. Per-directory literal counts

Top-level packages under `clinosim/`:

| Package | Literals (`.py` only) |
|---|---:|
| `clinosim/modules/` | 9,956 |
| `clinosim/simulator/` | 1,520 |
| `clinosim/types/` | 588 |
| `clinosim/eval/` | 475 |
| `clinosim/audit/` | 222 |
| `clinosim/codes/` | 108 |
| `clinosim/benchmarks/` | 90 |
| `clinosim/locale/` | 77 |
| `clinosim/dataset/` | 12 |
| `clinosim/config/` | 0 (YAML-only package) |
| **Total** | ~13,048 |

Under `clinosim/modules/` (top 10 subdirectories by literal count):

| Module directory | Literals | Notes |
|---|---:|---|
| `modules/output/` | 3,889 | Heavy with LOINC / SNOMED code strings (regex picks up digits inside codes); dominated by `fhir_r4/`. |
| `modules/document/` | 1,331 | Heavy with narrative template formatting and font-size constants. |
| `modules/physiology/` | 629 | Highest clinical density — coupling coefficients, decay rates, activation thresholds. |
| `modules/antibiotic/` | 472 | Antibiotic dosing, timing, spectrum tables. |
| `modules/observation/` | 391 | Lab reference ranges, vital-sign bounds. |
| `modules/clinical_course/` | 357 | Archetype transition timing and modifiers. |
| `modules/patient/` | 319 | Chronic-condition prevalences, severity distributions. |
| `modules/population/` | 246 | Demographic distributions. |
| `modules/order/` | 239 | Order timing, urgency mappings. |
| `modules/hai/` | 236 | HAI incidence rates and organism prevalences. |

## 4. Existing compliant `_thresholds` files (models for new work)

The three files below already satisfy §5. New per-domain `_constants` /
`_thresholds` files added by future cleanup PRs should follow the same
shape (module-local file next to the consumer, one constant per line,
docstring block above each constant citing purpose / unit / source /
consumer):

| File | LOC | Domain |
|---|---:|---|
| `clinosim/modules/physiology/dehydration_thresholds.py` | 56 | Dehydration cutoffs on `volume_status` |
| `clinosim/modules/physiology/renal_thresholds.py` | 46 | Renal-function severity cutoffs |
| `clinosim/modules/observation/vitals_thresholds.py` | 43 | Vital-sign normal / critical bands |

## 5. Triage bucket definitions

For any bare literal encountered, the cleanup process places it in one
of three buckets:

- **Already documented** (compliant). Passes §5 as-is: named, docstring-
  annotated, correctly located. Recorded here for the record; no action.
- **Rename + document** (in-scope for a follow-up PR). Materially affects
  patient state / clinical logic / FHIR resource output / user-visible
  numbers. Requires: introduce a named constant, add a docstring
  (purpose / unit / source or clinical citation), relocate per §5 point 3.
- **Out of scope**. Loop bounds, array indices, unit conversions, RNG
  seed literals, LOINC / SNOMED code strings, obvious tautologies,
  format-only constants (line widths, indent levels).

The distribution of the 13,048 literals across the three buckets is
approximately (hand-waved from sampling):

| Bucket | Fraction | ~count |
|---|---:|---:|
| Already documented | ~5 % | ~650 |
| Rename + document | ~25 – 35 % | ~3,000 – 4,500 |
| Out of scope | ~60 – 70 % | ~7,900 – 9,400 |

The "Rename + document" bucket is the target of the follow-up cleanup PRs.

## 6. Recommended first cleanup PRs (three hotspots)

The three hotspots below are the highest-clinical-leverage, highest-visibility
starting points. Each becomes its own follow-up PR with its own
byte-diff verification (renaming a constant must never change its
numeric value; the golden cohort must be regenerated to confirm).

### 6.1 Hotspot A — `modules/physiology/engine.py` coupling coefficients

The physiology model's core clinical coupling. Coefficients such as
`0.9`, `0.4`, `0.15`, `0.5`, `0.2`, `0.3` appear inline in the state-
transition math without documentation. Example lines from the current
file (as of `master` `628326b6e2b`):

```python
state.renal_function *= 1.0 - s * 0.9           # engine.py:55
if s > 0.5:
    state.anemia_level += 0.15                  # engine.py:57
    state.ph_status -= s * 0.1                  # engine.py:58

state.cardiac_function *= 1.0 - s * 0.4         # engine.py:60
if s > 0.3:
    state.volume_status += s * 0.3              # engine.py:62
state.sodium_status -= s * 0.30                 # engine.py:63
```

**Cleanup shape**: introduce `modules/physiology/_coupling_coefficients.py`
alongside the existing `dehydration_thresholds.py` and `renal_thresholds.py`.
Named constants: `RENAL_FUNCTION_DECAY_PER_SEVERITY = 0.9` (with
docstring naming CKD progression model), `ANEMIA_INCREMENT_AT_MODERATE = 0.15`
(threshold: `s > 0.5`), `CARDIAC_FUNCTION_DECAY_PER_SEVERITY = 0.4`, etc.
Each docstring cites the physiology model reference or explicitly marks
"empirical tuning for the synthetic simulator".

### 6.2 Hotspot B — `modules/output/fhir_r4/labs/observations.py` vital-sign reference ranges

Reference and critical bounds appear as positional tuples that are hard
to read and impossible to grep by field name. Example (as of
`master` `628326b6e2b`):

```python
("heart_rate", "8867-4", "Heart rate", "脈拍", "/min", 60, 100, 40, 130, 0),
("spo2",       "2708-6", "Oxygen saturation", "酸素飽和度", "%", 95, 100, 88, None, 5),
("temperature_celsius", "8310-5", "Body temperature", "体温", "Cel", 36.0, 37.5, 35.0, 39.5, 30),
("respiratory_rate", "9279-1", "Respiratory rate", "呼吸数", "/min", 12, 20, 8, 30, 60),
```

The positional bounds (`60, 100, 40, 130`) are normal-low / normal-high /
critical-low / critical-high without a schema.

**Cleanup shape**: introduce `modules/output/fhir_r4/labs/_reference_ranges.py`
with one `@dataclass` per vital (fields: `slug`, `loinc_code`,
`display_en`, `display_ja`, `unit`, `normal_low`, `normal_high`,
`critical_low`, `critical_high`, `hysteresis_seconds`). Docstring per
vital cites the clinical reference (JCCLS 共用基準範囲 for JP, HL7
FHIR vitals US Core equivalent for US).

### 6.3 Hotspot C — `modules/patient/activator.py` severity → activation probabilities

Chronic-condition severity distributions drive patient generation
without inline clinical citation. Example (as of `master` `628326b6e2b`):

```python
"N18": {"G1": 0.05, "G2": 0.15, "G3a": 0.35, "G3b": 0.50, "G4": 0.70, "G5": 0.90},
"I50": {"NYHA I": 0.10, "NYHA II": 0.25, "NYHA III": 0.45, "NYHA IV": 0.70},
"J44": {"GOLD 1": 0.10, "GOLD 2": 0.25, "GOLD 3": 0.45, "GOLD 4": 0.70},
"J45": {"Mild intermittent": 0.05, "Mild persistent": 0.15, ...},
"I25": {"CCS I": 0.10, "CCS II": 0.25, "CCS III": 0.50},
```

Each probability set needs a citation to the epidemiology source
(KDIGO for N18, NYHA for I50, GOLD report for J44, GINA for J45, CCS
grading for I25, ADA/JDS for E11, etc.).

**Cleanup shape**: introduce `modules/patient/_severity_activation.py`
with one named dict per condition and a docstring block per condition
citing the classification system and the epidemiology reference for the
prevalence numbers.

## 7. Additional cleanup targets (by module concentration)

After the three hotspots, the following modules carry the next tier of
in-scope literals — worth their own per-module PR:

- `modules/output/fhir_r4/` (~3,889 total; substantial fraction inside
  LOINC / SNOMED code strings and therefore out of scope, but the
  builder logic itself carries dosing / timing / count constants worth
  documenting).
- `modules/antibiotic/` (~472; dosing tables, spectrum coverage).
- `modules/hai/` (~236; HAI incidence rates, culture-positive fractions).
- `modules/population/` (~246; age / sex / comorbidity distributions).
- `modules/order/` (~239; order timing, urgency mappings).

## 8. Follow-up PRs (per-hotspot, each with byte-diff verification)

Each cleanup PR follows the pattern:

1. Add the new `_constants.py` / `_thresholds.py` / `_coupling_coefficients.py`
   file. Every constant has docstring (purpose / unit / source).
2. Replace the inline literals at the consumer site with references to
   the new named constants.
3. Regenerate the golden cohort (`clinosim simulate` at the pinned test
   seed) and confirm byte-identical output vs. `master` (`diff -r`).
4. Add / update the module's `README.md` "Constants and configuration"
   section to reference the new file.
5. `ruff format` and `ruff check` clean; commits Signed-off-by.

Recommended order (highest clinical leverage first):

- Hotspot A (physiology coupling coefficients) — foundational, unblocks
  discussion of physiology-model realism.
- Hotspot B (labs reference ranges) — highest reader-visibility (FHIR
  output).
- Hotspot C (patient severity activation) — highest patient-generation
  impact.

## 9. Out-of-scope for this campaign

- Test-file literals. Fixture files often carry one-off numbers that add
  no value if extracted.
- Constants inside `clinosim/config/*.yaml`. Already compliant by
  virtue of being in the config-YAML directory.
- Runtime validation of constants (Pydantic models, etc.).
- Rewriting clinical logic. Renaming a threshold does not change what
  it means.

## Change history

- **2026-08-09** — Baseline established. Published in the PR closing
  [Issue #637](https://github.com/TomoOkuyama/clinosim/issues/637)
  PR-A of the constants-cleanup campaign. Follow-up hotspot PRs land
  the actual renames.
