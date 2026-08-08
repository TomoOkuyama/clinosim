# Design: Unify `MedicationRequest.category` derivation across order and discharge paths

Issue: [#548](https://github.com/TomoOkuyama/clinosim/issues/548)
Date: 2026-08-08
Status: Design approved, ready for implementation-plan phase.

## Goal

Introduce a single canonical helper `_derive_mr_category` in
`clinosim/modules/output/fhir_r4/medications/medications.py` that both
public FHIR MedicationRequest builders
(`_build_medication_request`, `_build_discharge_medication_request`)
call to derive the `medicationrequest-category` (code, display) tuple.
Eliminates the divergence between the 5-branch (order path) and
2-branch (discharge path) decision trees documented in Issue #548.

## Non-goals (out of scope)

The Issue's original proposal ("extract `_build_medication_request_core`
that produces category + courseOfTherapy + dispense + dosageInstruction
from a decision table keyed on `kind ∈ {"order", "discharge_from_inpatient",
"outpatient_renewal"}`") is deliberately **narrowed**:

- **`courseOfTherapyType`**: `_course_for_order` and `_course_for_discharge`
  (extracted in session 84) encode **clinically distinct concepts**
  (chronic-vs-acute for order path; handed-over-maintenance-vs-short-course
  for discharge path). Session 84's decomposition already satisfies SRP;
  unifying under a shared decision table would collapse the two rules
  into a superficially-shared but semantically-tangled function.
- **`dispenseRequest`**: source fields differ fundamentally (order path
  reads `end_datetime` + emits `numberOfRepeatsAllowed`; discharge path
  reads `duration_days` + emits `expectedSupplyDuration`). Sharing would
  require an input-adapter dataclass with Optional fields for every
  source-specific field — over-engineering for two callers.
- **`dosageInstruction`**: order path has a full Order dict with
  `dose_quantity` / `frequency` / `prn` (goes through
  `build_dosage_instruction` fragment builder); discharge path has only
  `dose` text / `route` / `dose_ja` / `dose_en` overrides. The input
  shapes are fundamentally different; shared logic would restate the
  divergence internally.
- **All other divergent slots** (id generation, status derivation, intent
  derivation, priority, requester, note, substitution, reasonReference,
  medication_intent): each is either legitimately caller-specific (input
  shape dictates) or already extracted to shared helpers
  (`_build_medication_request_meta`, `_build_medication_request_identifiers`,
  `_resolve_medication_concept`).

The category field is the only one where the two callers use the SAME
decision axes (encounter_type + boolean flags) but the discharge caller's
2-branch implementation silently drops two axes (`is_episodic`,
`is_discharge_intent`) that the order caller relies on. That is a genuine
duplication; the other four are legitimate divergence.

## Design decisions

### DD1: Extract only the category derivation; leave other slots per-caller

Rationale in the "Non-goals" block above. The refactor is
**minimum-viable**: it addresses the observed silent-drift risk
(discharge-path category ignoring axes the order path considers) without
imposing a false symmetry on legitimately-divergent slots.

### DD2: Canonical decision tree = order path's 5-branch logic, with rule order preserved

The order path's decision tree (`_build_medication_request:679-696`)
already models all four HL7 `medicationrequest-category` codes correctly.
The discharge caller's 2-branch was a shortcut that assumed
`encounter_type=="inpatient"` implies discharge and non-inpatient implies
chronic community refill. That assumption fails for emergency-encounter
discharge scripts (episodic ED-treatment Rx should be `outpatient`, not
`community`).

The canonical helper is the order path's decision, cleanly parameterised.
Callers supply the same four axes explicitly rather than deriving them
from `clinical_intent` substrings inline.

### DD3: Discharge caller supplies fixed literals for the three boolean axes

DischargeRxItem has no `clinical_intent` field (session 85 confirmed via
the resume prompt's Issue #548 defer entry). The discharge caller passes:

- `is_home_med=False` — discharge scripts do not carry the "home
  medication" tag; if a discharge item IS a chronic med restart it is
  categorised as `community` via rule 1 (outpatient-non-episodic gate),
  not via `is_home_med`.
- `is_episodic=False` — discharge context is inherently non-episodic
  (episodic implies the Rx is intra-encounter treatment, not take-home).
- `is_discharge_intent=True` — discharge caller by identity IS
  discharge intent.

These literals collapse the discharge caller's decision tree to three
rule-1/2/3 branches at helper level: inpatient → discharge (rule 3),
outpatient → community (rule 1), emergency → outpatient (rule 2). The
fourth possibility (empty `encounter_type`) triggers rule 5 fallback
(`inpatient`).

### DD4: Accept documented byte-diff shift on emergency-encounter discharge items

Emergency-encounter discharge items shift from `community` (current) to
`outpatient` (new). This is a semantic **improvement** (HL7
`medicationrequest-category` CS: `outpatient` = "single-episode outpatient
or ED order"; `community` = "chronic long-term prescription with expected
refills"). ED discharge scripts are typically acute treatment (antibiotics
for infection, painkillers for injury) — `outpatient` is the accurate
label.

Options considered:

| Option | Approach | Verdict |
|---|---|---|
| A | Accept shift, document in PR body | **Chosen** — semantic improvement, byte-diff bounded to emergency-discharge items only |
| B | Add caller-specific branch to helper (`if encounter_type == "emergency" and is_discharge_intent: return community`) | ✗ Anti-pattern: caller-specific logic inside a "canonical" helper breaks SRP |
| C | Reorder rules to keep discharge caller producing community for non-inpatient | ✗ Order-caller callers see behavioural change; worse than option A |

Empty `encounter_type` also shifts (`community` → `inpatient` via rule 5
fallback). Expected to be 0 occurrences in real cohorts (encounter_type
is populated by the simulator); if preflight shows non-zero, the shift is
also documented.

## Architecture

**Current**:

```
_build_medication_request(order, ...) [251 LOC]
├─ category: inline 5-branch decision tree
├─ courseOfTherapyType: _course_for_order helper
├─ dispenseRequest: inline (validityPeriod + numberOfRepeatsAllowed)
└─ dosageInstruction: build_dosage_instruction(order, country)

_build_discharge_medication_request(item, ...) [128 LOC]
├─ category: inline 2-branch  ← silent-drift risk
├─ courseOfTherapyType: _course_for_discharge helper
├─ dispenseRequest: inline (validityPeriod + expectedSupplyDuration)
└─ dosageInstruction: inline {route, text}
```

**After**:

```
_derive_mr_category(encounter_type, is_home_med, is_episodic, is_discharge_intent) → (code, display)
  └─ 5-rule canonical decision tree

_build_medication_request(order, ...) [~245 LOC]
├─ category: _derive_mr_category(...)  ← via helper
├─ courseOfTherapyType: _course_for_order helper (unchanged)
├─ dispenseRequest: inline (unchanged)
└─ dosageInstruction: build_dosage_instruction (unchanged)

_build_discharge_medication_request(item, ...) [~123 LOC]
├─ category: _derive_mr_category(...)  ← via helper
├─ courseOfTherapyType: _course_for_discharge helper (unchanged)
├─ dispenseRequest: inline (unchanged)
└─ dosageInstruction: inline (unchanged)
```

Responsibility split:

- `_derive_mr_category`: single canonical source for
  `medicationrequest-category` derivation
- `_course_for_order` / `_course_for_discharge`: per-caller
  acute-vs-continuous judgement (clinically distinct concepts,
  session 84's separation preserved)
- `_build_medication_request`: encounter-time Order → FHIR
  MedicationRequest (order-specific slots: priority / substitution /
  note / medication_intent / complex status derivation / antibiotic id)
- `_build_discharge_medication_request`: DischargeRxItem → FHIR
  MedicationRequest (discharge-specific slots: expectedSupplyDuration /
  dose_ja/en overrides)

## Components

### C1 — new helper `_derive_mr_category`

Location: `clinosim/modules/output/fhir_r4/medications/medications.py`
(module-private, adjacent to `_course_for_order` / `_course_for_discharge`
at L103-122).

```python
def _derive_mr_category(
    encounter_type: str,
    is_home_med: bool,
    is_episodic: bool,
    is_discharge_intent: bool,
) -> tuple[str, str]:
    """Derive the ``medicationrequest-category`` (code, display) for a FHIR
    MedicationRequest emission (Issue #548 unification).

    Single source of truth for the 5-way decision tree previously
    duplicated across the order path (5-branch) and the discharge path
    (2-branch, which silently omitted episodic / discharge-intent
    awareness).

    HL7 CodeSystem: ``medicationrequest-category``
      * ``community``  — chronic home-medication or outpatient renewal
      * ``outpatient`` — episodic outpatient / emergency-department order
      * ``inpatient``  — inpatient order that is NOT a take-home
      * ``discharge``  — inpatient take-home script (Rx at discharge)

    Decision rule (evaluated in order):

    1. is_home_med OR (encounter_type=="outpatient" AND NOT is_episodic)
       → community — chronic maintenance / outpatient renewal
    2. encounter_type in ("outpatient", "emergency")
       → outpatient — episodic OP / ED order
    3. encounter_type == "inpatient" AND is_discharge_intent
       → discharge — inpatient take-home
    4. encounter_type == "inpatient"
       → inpatient — in-house prescription
    5. otherwise (encounter_type empty / unknown)
       → inpatient — safe fallback (intent already indicates an order was authored)
    """
    if is_home_med or (encounter_type == "outpatient" and not is_episodic):
        return "community", "Community"
    if encounter_type in ("outpatient", "emergency"):
        return "outpatient", "Outpatient"
    if encounter_type == "inpatient" and is_discharge_intent:
        return "discharge", "Discharge"
    if encounter_type == "inpatient":
        return "inpatient", "Inpatient"
    return "inpatient", "Inpatient"
```

Return-value invariant: always a non-empty 2-tuple, both elements
non-empty strings. Caller can safely index `[0]`/`[1]` without a guard.

### C2 — modified `_build_medication_request` (order path)

Replace `medications.py:679-698` (the 20-LOC inline decision tree):

```python
# Before
_cat_code = _cat_display = ""
if _is_home_med or (encounter_type == "outpatient" and not _is_episodic):
    _cat_code, _cat_display = "community", "Community"
elif encounter_type == "outpatient":
    _cat_code, _cat_display = "outpatient", "Outpatient"
elif encounter_type == "emergency":
    _cat_code, _cat_display = "outpatient", "Outpatient"
elif encounter_type == "inpatient":
    if "discharge" in _ci_lower:
        _cat_code, _cat_display = "discharge", "Discharge"
    else:
        _cat_code, _cat_display = "inpatient", "Inpatient"
else:
    _cat_code, _cat_display = "inpatient", "Inpatient"
if _cat_code:
    resource["category"] = _build_category_block(_cat_code, _cat_display)

# After (7 LOC)
_is_discharge_intent = "discharge" in _ci_lower
_cat_code, _cat_display = _derive_mr_category(
    encounter_type=encounter_type,
    is_home_med=_is_home_med,
    is_episodic=_is_episodic,
    is_discharge_intent=_is_discharge_intent,
)
resource["category"] = _build_category_block(_cat_code, _cat_display)
```

Note: the `if _cat_code:` gate is removed because the helper's return-value
invariant guarantees a non-empty tuple. Pre-refactor all five branches
also returned non-empty tuples, so gate removal is byte-neutral (dead-code
cleanup).

### C3 — modified `_build_discharge_medication_request` (discharge path)

Replace `medications.py:890-895` (the 6-LOC inline 2-branch):

```python
# Before
_is_discharge = encounter_type == "inpatient"
cat_code, cat_display = ("discharge", "Discharge") if _is_discharge else ("community", "Community")
resource["category"] = _build_category_block(cat_code, cat_display)

# After (7 LOC)
# discharge builder's caller identity implies is_discharge_intent=True and
# no episodic / home-medication semantics (DischargeRxItem lacks the
# clinical_intent tag that the order path uses to detect these).
cat_code, cat_display = _derive_mr_category(
    encounter_type=encounter_type,
    is_home_med=False,
    is_episodic=False,
    is_discharge_intent=True,
)
resource["category"] = _build_category_block(cat_code, cat_display)
```

### C4 — components NOT modified

- `_course_for_order`, `_course_for_discharge` — session 84 separation preserved.
- `dispenseRequest` inline logic in both callers — source fields differ.
- `dosageInstruction` inline logic in both callers — source structures differ.
- id generation (`_resolve_antibiotic_mr_id` vs sequence-based prefix).
- status / intent derivation (per-caller complexity).
- `rp_number` / `order_in_rp` handling (per-caller input shape).
- `_build_medication_request_meta`, `_build_medication_request_identifiers`,
  `_resolve_medication_concept`, `_build_category_block`,
  `_build_course_of_therapy_block` — pre-existing shared helpers.

## Data flow — byte-diff surface

### Order path (`_build_medication_request`)

**Refactor guarantee: byte-neutral**. All five current inline branches map
1:1 to `_derive_mr_category`'s five rules, returning the identical
(code, display) tuple:

| Current branch | Helper rule | Result |
|---|---|---|
| `is_home_med OR outpatient AND NOT episodic` → community | 1 | identical |
| `outpatient` (implies episodic per rule 1 fallthrough) → outpatient | 2 | identical |
| `emergency` → outpatient | 2 | identical |
| `inpatient AND "discharge" in ci_lower` → discharge | 3 | identical |
| `inpatient` → inpatient | 4 | identical |
| else → inpatient | 5 | identical |

Unit-test parametrisation (see Testing) locks this 1:1 correspondence.

### Discharge path (`_build_discharge_medication_request`)

**Documented shift on emergency-encounter and empty-encounter-type items**.
Discharge caller supplies fixed literals `is_home_med=False`,
`is_episodic=False`, `is_discharge_intent=True`.

| `encounter_type` | Pre-#548 | Post-#548 | Shift |
|---|---|---|---|
| `"inpatient"` | discharge | discharge (rule 3) | none |
| `"outpatient"` | community | community (rule 1) | none |
| `"emergency"` | community | **outpatient** (rule 2) | **shift** |
| `""` (empty) | community | **inpatient** (rule 5 fallback) | **shift** (edge case) |
| unknown (e.g. `"virtual"`) | community | inpatient (rule 5 fallback) | shift (unlikely case) |

Expected cohort impact: emergency-discharge items form a small minority
(preflight measurement will produce exact count; ED cohort discharge
scripts are 1-5 per 30-patient seed 42 based on prior cohort analysis).
Empty / unknown encounter_type is expected to be 0 occurrences (simulator
always populates encounter_type); if preflight shows non-zero, that shift
is also documented.

### Non-Encounter files, non-MedicationRequest fields, non-shift items

100% byte-identical vs baseline.

## Error handling & edge cases

- **`encounter_type` empty / unknown**: helper rule 5 fallback returns
  `inpatient`. Order path preserves current behavior (empty → inpatient);
  discharge path shifts (empty → inpatient, previously community).
  Preflight measures actual count.
- **Both `is_home_med=True` and `is_episodic=True`** (order path only):
  rule 1 fires first (is_home_med precedence). Matches pre-refactor
  behavior. Clinically ambiguous input but defensively handled.
- **`is_discharge_intent=True` on outpatient encounter** (order path):
  rule 1 fires (outpatient + non-episodic → community). Matches
  pre-refactor behavior — the order path's inline tree also gated
  `discharge` on `encounter_type == "inpatient"`.
- **Callers passing bool combinations the helper can't distinguish
  meaningfully** (e.g. `is_home_med=True` with `is_discharge_intent=True`):
  rule 1 wins. This is the pre-refactor semantics preserved.
- **`_build_discharge_medication_request` receiving `encounter_type`
  outside {"inpatient", "outpatient", "emergency"}**: rule 5 fallback
  applies. `_bb_discharge_medication_requests` passes
  `encounters[0].encounter_type` verbatim; the simulator's CIF schema
  restricts values to those three plus empty, so unexpected values
  indicate upstream data corruption — falling through to `inpatient` is
  a safe emit (the alternative is silent `MedicationRequest.category` field
  omission or empty tuple).

## Testing

### Unit tests (new file)

Path: `tests/unit/output/test_medication_request_category_derivation.py`

Three parametrized test groups (details in the design's Section 5, not
duplicated here to avoid stale drift):

1. `test_derive_mr_category` — 13 direct-input cases covering all five
   rules and the boolean-combination edge cases.
2. `test_derive_mr_category_discharge_caller_shift` — 4 cases locking the
   post-refactor discharge-caller behavior (2 no-shift + 2 documented
   shifts).
3. `test_order_caller_category_byte_neutral` — 7 cases threading realistic
   `(encounter_type, clinical_intent)` inputs through the order-caller's
   boolean derivation and asserting the resulting category matches
   pre-refactor output.

### Existing test updates

`grep -rn 'MedicationRequest.category\|medicationrequest-category' tests/`
enumerates sites that might assert on the category emission. Anticipated:
if any existing test asserts on an emergency-encounter discharge item's
category, its expected value updates from `"community"` to `"outpatient"`
with an inline comment referencing this design.

### Cohort byte-diff verification (must run before requesting review)

1. **Preflight** — with current master code:
   ```bash
   CLINOSIM_JP_CLINS_PKG_DIR=... PYTHONPATH=. clinosim simulate -p 30 -s 42 --country JP --format fhir-r4 -o /tmp/548-baseline-jp
   CLINOSIM_JP_CLINS_PKG_DIR=... PYTHONPATH=. clinosim simulate -p 30 -s 42 --country US --format fhir-r4 -o /tmp/548-baseline-us
   ```
   Count category distribution:
   ```bash
   python3 -c "
   import json
   from collections import Counter
   for country in ('jp', 'us'):
       counter = Counter()
       with open(f'/tmp/548-baseline-{country}/fhir_r4/MedicationRequest.ndjson') as f:
           for line in f:
               r = json.loads(line)
               cat = r.get('category', [{}])[0].get('coding', [{}])[0].get('code', 'MISSING')
               counter[cat] += 1
       print(country, counter)
   "
   ```
2. **PR branch** — regenerate the same cohorts on the refactor branch.
3. **Diff-r**:
   ```bash
   diff -r /tmp/548-baseline-jp /tmp/548-pr-jp -x _generator_metadata.json
   diff -r /tmp/548-baseline-us /tmp/548-pr-us -x _generator_metadata.json
   ```
4. **Gate**:
   - Non-`MedicationRequest.ndjson` files: byte-identical.
   - `MedicationRequest.ndjson`: diff lines fall into the shift categories
     enumerated in the Data flow table (emergency-discharge community →
     outpatient; empty/unknown encounter_type community → inpatient).
     Every diff line maps to an expected shift; unexplained lines block
     merge until root-caused.

### Downstream verification

- **V-D1 fhir-jp-validator**: HL7 `medicationrequest-category` CS defines
  all four codes (`community`, `outpatient`, `inpatient`, `discharge`);
  the shift moves values between valid codes, so validator error count
  should be unchanged. CI gate
  `JP p=300 seed=300 → eval only jp_clins_lab_compliance` verifies.
- **V-D2 iris4h-ai consumer**: grep the downstream consumer for
  `medicationrequest-category` or `category.coding` branching on
  MedicationRequest:
  ```bash
  grep -rn 'medicationrequest-category\|MedicationRequest.*category' ../iris4h-ai/ 2>/dev/null | grep -v '\.git/\|\.ndjson\|\.json'
  ```
  If any consumer branches on the category value, notify the owner and
  file a downstream issue before merging.
- **V-D3 integration**: `pytest tests/integration` — all pass. Any
  failing assertion on category value updated inline.

### PR body checklist

```markdown
- [ ] `pytest tests/unit` — new tests + baseline pass (baseline 3977 + 24 new = 4001)
- [ ] `pytest tests/integration` — all pass
- [ ] `mypy clinosim/` strict — clean
- [ ] `ruff==0.16.0 check` + `format --check` — clean
- [ ] 30-patient seed 42 JP+US cohort diff-r vs master:
  - Non-MedicationRequest resources byte-identical
  - MedicationRequest.category shifts only on documented cases
  - Emergency-discharge shift count: <N>
  - Empty encounter_type shift count: <M> (expected 0)
- [ ] fhir-jp-validator error count vs baseline: unchanged
- [ ] iris4h-ai medicationrequest-category consumer grep: no branching / owner notified
- [ ] Cohort fingerprint shift documented in PR body with per-encounter-type before/after
```

## Effort estimate

- Implementation deletions: ~20 LOC (order-path inline tree) + ~6 LOC
  (discharge-path inline 2-branch) = ~26 LOC.
- Implementation additions: ~40 LOC (`_derive_mr_category` helper) + ~14
  LOC (two updated call sites, 7 LOC each) = ~54 LOC.
- New tests: ~80 LOC (3 parametrized test groups, ~25 LOC each).
- Verification: ~30 min (cohort diff + downstream grep + validator run).
- Net implementation LOC: ~+28; net complexity: reduction (one canonical
  path instead of two divergent inline trees).

## Severity / priority

`high` per Issue #548 severity. Silent divergence between the two
MedicationRequest builders is the largest single-file surface area of
duplicated FHIR emit logic in the codebase; the emergency-discharge
misclassification is a data-quality bug that CI has not caught because
integration tests exercise each builder in isolation.

## Follow-up items (out of this PR, no separate Issue needed)

The Issue's original "extract `_build_medication_request_core` with full
decision table" proposal is intentionally not implemented here (see
Non-goals). If future profile variants (JP-CLINS revision, US
Meaningful-Use profile) require unified rules on `courseOfTherapyType` /
`dispenseRequest` / `dosageInstruction`, revisit under a new Issue at
that time — the current per-caller inline logic is faithful to
clinically-distinct source shapes and should not be prematurely unified.
