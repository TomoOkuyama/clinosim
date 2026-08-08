# Phase 2a — D-dimer derive + `causes_vte` scenario flag — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Spec:** `docs/superpowers/specs/2026-06-24-phase2a-vte-d-dimer-design.md`

**Goal:** Activate `D_dimer` (LOINC 30240-9 / JLAC10 2B140) by extending `physiology.derive_lab_values` with a multi-axis derive + `causes_vte` scenario flag; wire the flag through all `derive_lab_values` call sites via a single `scenario_flags_from_protocol` helper that also fixes the existing `causes_myocardial_injury` wiring gap (improvement J5).

**Architecture:** AD-57 BNP-pattern surgical (formula only, no state mutation) + AD-59 per-order RNG isolation (already established by PR #74/#78). The scenario-flag helper centralizes today's `causes_myocardial_injury` wiring (only present at one of four call sites) and tomorrow's `causes_vte`, so adding a third flag in future requires editing one helper, not chasing four lab loops.

**Tech Stack:** Python 3.11+, pytest, ruff, mypy strict. YAML-driven code data + disease YAMLs + locale.

## Global Constraints

- Code/comments/docstrings: English. README.ja.md / `modules/<name>/README.md`: Japanese with English technical terms. DESIGN.md / TODO.md / spec: English. Communication with user: Japanese.
- Pure functions in `derive_lab_values`; no `PhysiologicalState` mutation.
- AD-16: no `random.random()`; new derive consumes nothing from any RNG.
- AD-59: per-order RNG draws route through `simulator/seeding.py:individual_lab_seed` (already wired at all three lab loops post-PR #78).
- AD-30: CIF stores codes only; display resolution via `clinosim.codes.lookup`.
- Authoritative sources: LOINC via NLM `clinicaltables.nlm.nih.gov/api/loinc_items/v3/search?terms=<code>` (memory `reference_jlac10_source`). JLAC10 via JSLM v137 (`137jlac10_1.xlsx` sheet 「分析物コード」). Never fabricate — use `# TODO: verify` if uncertain.
- Commit-message trailer: `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>` + `Claude-Session: https://claude.ai/code/session_017dRsomkKQhRVUi5PZY2HSs`.
- Branch: `feat/phase2a-vte-d-dimer` (already created from master `b6bc8eab`; spec commit `d9d67663` already on branch).

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `clinosim/codes/data/loinc.yaml` | modify | Add LOINC 30240-9 (D-dimer). |
| `clinosim/codes/data/jlac10.yaml` | modify | Add JLAC10 2B140 (D-D dimer) with JCCLS-official Japanese. |
| `clinosim/locale/us/code_mapping_lab.yaml` | modify | Map `D_dimer` → `30240-9`. |
| `clinosim/locale/jp/code_mapping_lab.yaml` | modify | Map `D_dimer` → `2B140`. |
| `clinosim/modules/physiology/engine.py` | modify | (a) Add `causes_vte: bool = False` param + D_dimer derive; (b) export `scenario_flags_from_protocol(protocol)`. |
| `clinosim/modules/disease/reference_data/pulmonary_embolism.yaml` | modify | Add `causes_vte: true`. |
| `clinosim/modules/disease/reference_data/deep_vein_thrombosis.yaml` | modify | Add `causes_vte: true`. |
| `clinosim/modules/disease/reference_data/cerebral_infarction.yaml` | modify | Add `causes_vte: true`. |
| `clinosim/simulator/inpatient.py` | modify | Replace `myocardial_injury=mi_injury` at the two Pass-1 sites with `**flags`; wire the second lab path (around `:1680`) with `**flags` too. |
| `clinosim/simulator/emergency.py` | modify | Add `**flags = scenario_flags_from_protocol(protocol)` to the `_true_labs` call (J5 fix — ED MI patients gain their troponin upshift). |
| `clinosim/simulator/outpatient.py` | modify | Same `**flags` wiring; protocol may be a dict (`spec` variable) — helper handles both. |
| `tests/unit/test_codes_jlac10.py` | modify | Extend `test_verified_codes` parametrize with `("D_dimer", "2B140")`. |
| `tests/unit/test_physiology.py` | modify | TDD tests for D_dimer healthy / sepsis-no-VTE / DIC alone / PE (causes_vte=True) + age effect. |
| `tests/unit/test_scenario_flags.py` | create | Unit tests for `scenario_flags_from_protocol` covering dict / object / None protocol shapes. |
| `tests/integration/test_individual_lab_isolation.py` | modify | Add `test_pe_individual_d_dimer_order_now_resulted` invariant guard. |
| `tests/integration/test_panel_expansion_coag.py` | modify | Add `test_pe_emits_clinically_positive_d_dimer` + `test_ed_mi_now_has_high_troponin` (J5 evidence). |
| `scratchpad/phase2a_byte_diff.py` | create | Byte-diff vs master `b6bc8eab` (Patient/Encounter/.../FamilyHistory IDENTICAL; Observation expected to change for two reasons — new D-dimer + existing ED MI troponin uplift; report both deltas). |
| `scratchpad/dqr_phase2a_vte_review.py` | create | 3-axis DQR script (US p=10k + JP p=5k). |
| `docs/reviews/2026-06-24-phase2a-vte-data-quality-review.md` | create | DQR evidence + acceptance table. |
| `README.md` / `README.ja.md` | modify | VTE-spectrum D-dimer bullet + J5 fix note. |
| `DESIGN.md` | modify | Extend AD-59 entry (Coag PR + Phase 2a are two follow-ups using the AD-59 isolation for new analytes). |
| `clinosim/modules/physiology/README.md` | modify | D-dimer to derivation table; scenario-flag table updated. |
| `CLAUDE.md` | modify | Scenario-flag bullet names `scenario_flags_from_protocol` as canonical entry point. |
| `TODO.md` | modify | Mark Phase 2a done; Phase 2b + I4/I6/I7 carried. |

---

## Task 1: Authoritative code data + locale mappings (D_dimer)

**Files:**
- Modify: `clinosim/codes/data/loinc.yaml`
- Modify: `clinosim/codes/data/jlac10.yaml`
- Modify: `clinosim/locale/us/code_mapping_lab.yaml`
- Modify: `clinosim/locale/jp/code_mapping_lab.yaml`
- Modify: `tests/unit/test_codes_jlac10.py`

**Interfaces:**
- Produces: internal lab name `D_dimer` resolves to LOINC `30240-9` (US) and JLAC10 `2B140` (JP). Both codes carry English + Japanese display; JP `ja` follows the JCCLS-official Japanese (`D-Dダイマー`) per PR #76 enforcement.

- [ ] **Step 1: Write the failing test**

In `tests/unit/test_codes_jlac10.py`, extend the existing `test_verified_codes` parametrize block (around line ~50) — append the D_dimer line just after the existing Coag-panel additions:

```python
        ("APTT", "2B020"), ("PT", "2B030"), ("PT_INR", "2B030"),
        ("Fibrinogen", "2B100"),
        # --- Phase 2a addition (JSLM v137 row 2B140: D-Dダイマー / D-D dimer)
        ("D_dimer", "2B140"),
    ])
    def test_verified_codes(self, analyte, code):
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/unit/test_codes_jlac10.py::TestJLAC10Integrity::test_verified_codes -v 2>&1 | tail -10
```

Expected: ONE failure — `KeyError: 'D_dimer'` on the new parametrize case (the existing 4 Coag entries pass).

- [ ] **Step 3: Verify the LOINC code authoritatively**

```bash
curl -s "https://clinicaltables.nlm.nih.gov/api/loinc_items/v3/search?terms=30240-9&df=LOINC_NUM,LONG_COMMON_NAME,COMPONENT,SYSTEM"
```

Expected output snippet: `["30240-9","Fibrin D-dimer FEU [Mass/volume] in Platelet poor plasma by Immunoassay","Fibrin D-dimer FEU","Ser/Plas^PPP"]` (or similar). Confirm COMPONENT contains "D-dimer" — that authorizes the clean short form for `en`.

- [ ] **Step 4: Add LOINC 30240-9**

In `clinosim/codes/data/loinc.yaml`, find the existing `14979-9` block (added by PR #80, near the file tail). Insert immediately after it:

```yaml
  30240-9:
    # NLM Clinical Tables LONG_COMMON_NAME = "Fibrin D-dimer FEU [Mass/volume]
    # in Platelet poor plasma by Immunoassay"; COMPONENT="Fibrin D-dimer FEU".
    # clinosim convention uses clean short names (TestLoincDisplay guards
    # against [Mass/volume] etc.).
    en: D-dimer
    ja: D ダイマー
```

- [ ] **Step 5: Add JLAC10 2B140**

In `clinosim/codes/data/jlac10.yaml`, find the existing `2B100` block (added by PR #80, in the 2B series). Insert immediately after:

```yaml
  2B140:
    # JSLM v137 sheet 「分析物コード」 row: 2B140 / D-Dダイマー /
    # FDP Dダイマー / D-D dimer
    en: D-D dimer
    ja: D-Dダイマー
```

- [ ] **Step 6: Add US locale mapping**

In `clinosim/locale/us/code_mapping_lab.yaml`, find the existing `Fibrinogen: "3255-7"` line (added by PR #80). Insert immediately after:

```yaml
D_dimer: "30240-9"
```

- [ ] **Step 7: Add JP locale mapping**

In `clinosim/locale/jp/code_mapping_lab.yaml`, find the existing `Fibrinogen: "2B100"` line. Insert immediately after:

```yaml
D_dimer: "2B140"
```

- [ ] **Step 8: Verify all tests pass**

```bash
pytest tests/unit/test_codes_jlac10.py tests/unit/test_codes_integrity.py -v 2>&1 | tail -10
```

Expected: ALL PASS. If `test_no_duplicate_keys[loinc.yaml]` fails, search for a pre-existing `30240-9` (the Coag PR found a similar duplication for `5902-2`) and dedupe.

- [ ] **Step 9: Commit**

```bash
git add clinosim/codes/data/loinc.yaml clinosim/codes/data/jlac10.yaml \
        clinosim/locale/us/code_mapping_lab.yaml clinosim/locale/jp/code_mapping_lab.yaml \
        tests/unit/test_codes_jlac10.py
git commit -m "$(cat <<'EOF'
feat(codes): add D-dimer LOINC 30240-9 + JLAC10 2B140 + locale mappings

NLM Clinical Tables verified: LOINC 30240-9 COMPONENT="Fibrin D-dimer FEU"
(clinosim convention uses the clean COMPONENT short form for `en`).

JSLM v137 verified: JLAC10 2B140 = D-Dダイマー / D-D dimer (sheet
「分析物コード」). JCCLS-official Japanese ja per PR #76 enforcement
(not the English abbreviation).

Pre-req for Phase 2a derive — physiology branch follows in subsequent
commits.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_017dRsomkKQhRVUi5PZY2HSs
EOF
)"
```

---

## Task 2: `scenario_flags_from_protocol` helper (no callers yet)

**Files:**
- Modify: `clinosim/modules/physiology/engine.py` (add helper near the top of the file, above `derive_lab_values`)
- Create: `tests/unit/test_scenario_flags.py`

**Interfaces:**
- Produces: `physiology.engine.scenario_flags_from_protocol(protocol) -> dict[str, bool]`. Accepts a Pydantic disease-protocol object (uses `getattr`), a dict (uses `.get`), or `None` (returns all-False). Returns `{"myocardial_injury": bool, "causes_vte": bool}` — the dict keys match `derive_lab_values` parameter names so callers can `**flags`.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_scenario_flags.py`:

```python
"""Unit tests for scenario_flags_from_protocol (Phase 2a J5 fix)."""
import pytest

from clinosim.modules.physiology.engine import scenario_flags_from_protocol


@pytest.mark.unit
def test_none_protocol_returns_all_false():
    flags = scenario_flags_from_protocol(None)
    assert flags == {"myocardial_injury": False, "causes_vte": False}


@pytest.mark.unit
def test_dict_protocol_reads_both_flags():
    flags = scenario_flags_from_protocol(
        {"causes_myocardial_injury": True, "causes_vte": True}
    )
    assert flags == {"myocardial_injury": True, "causes_vte": True}


@pytest.mark.unit
def test_dict_protocol_missing_keys_default_false():
    flags = scenario_flags_from_protocol({})
    assert flags == {"myocardial_injury": False, "causes_vte": False}


@pytest.mark.unit
def test_object_protocol_reads_attribute():
    """Pydantic disease-protocol objects expose flags as attributes."""
    class FakeProtocol:
        causes_myocardial_injury = True
        causes_vte = False
    flags = scenario_flags_from_protocol(FakeProtocol())
    assert flags == {"myocardial_injury": True, "causes_vte": False}


@pytest.mark.unit
def test_object_protocol_missing_attribute_defaults_false():
    class EmptyProtocol:
        pass
    flags = scenario_flags_from_protocol(EmptyProtocol())
    assert flags == {"myocardial_injury": False, "causes_vte": False}


@pytest.mark.unit
def test_keys_match_derive_lab_values_parameter_names():
    """The dict keys must match derive_lab_values parameter names so callers
    can splat with **flags. If derive_lab_values param is renamed, this
    test guards the contract."""
    import inspect
    from clinosim.modules.physiology.engine import derive_lab_values
    sig = inspect.signature(derive_lab_values)
    flags = scenario_flags_from_protocol(None)
    for key in flags:
        assert key in sig.parameters, (
            f"scenario_flags_from_protocol returned key '{key}' that is "
            f"not a derive_lab_values parameter"
        )
```

- [ ] **Step 2: Run tests to verify all fail (import error)**

```bash
pytest tests/unit/test_scenario_flags.py -v 2>&1 | tail -15
```

Expected: collection / import failure — `scenario_flags_from_protocol` does not exist yet.

- [ ] **Step 3: Implement the helper**

In `clinosim/modules/physiology/engine.py`, find the line `def derive_lab_values(` (around line 220). Insert the helper just above it:

```python
def scenario_flags_from_protocol(protocol) -> dict[str, bool]:
    """Extract every `derive_lab_values` scenario flag from a disease YAML
    protocol (dict, Pydantic object, or None).

    Centralizes the `getattr(protocol, "causes_X", False)` / `protocol.get(...)`
    reads so a new flag added to `derive_lab_values` only needs wiring in
    ONE place — not at every call site across inpatient/emergency/outpatient.
    Dict keys match `derive_lab_values` parameter names so callers can spread
    with `**flags`.

    Phase 2a (2026-06-24) introduces this helper to fix J5: pre-helper, only
    inpatient.py:559-560 (Pass-1) read `causes_myocardial_injury`; the second
    inpatient lab path, emergency.py, and outpatient.py passed nothing, so
    MI patients in the ED had no troponin upshift. Same gap would have
    occurred for any newly added scenario flag.
    """
    if protocol is None:
        return {"myocardial_injury": False, "causes_vte": False}

    def _read(name: str) -> bool:
        if isinstance(protocol, dict):
            return bool(protocol.get(name, False))
        return bool(getattr(protocol, name, False))

    return {
        "myocardial_injury": _read("causes_myocardial_injury"),
        "causes_vte": _read("causes_vte"),
    }
```

- [ ] **Step 4: Run scenario-flag tests**

```bash
pytest tests/unit/test_scenario_flags.py -v 2>&1 | tail -10
```

Expected: 6 PASS. The "keys match parameter names" test currently passes for `myocardial_injury` (existing parameter) and FAILS for `causes_vte` because `derive_lab_values` does not yet have that parameter. Stage this — Task 3 adds the parameter and the test goes green; do not commit Task 2 alone.

If the test fails ONLY on `causes_vte` not being a `derive_lab_values` parameter yet, proceed to Task 3 immediately and commit Tasks 2+3 together.

- [ ] **Step 5: Defer commit**

Do not commit yet. Task 3 adds the `causes_vte` parameter that makes the keys-match test green. Commit happens at the end of Task 3.

---

## Task 3: `causes_vte` parameter + D-dimer derive

**Files:**
- Modify: `clinosim/modules/physiology/engine.py:derive_lab_values` (signature + new derive)
- Modify: `tests/unit/test_physiology.py`

**Interfaces:**
- Consumes: `state.inflammation_level`, `state.coagulation_status`, `age`, new `causes_vte: bool = False` parameter.
- Produces: `labs["D_dimer"]` in ug/mL FEU. Clamp `[0.15, 20.0]`. Healthy ~0.3, sepsis no DIC ~0.77, DIC severe ~2.32, PE (causes_vte=True) ~4.52.

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_physiology.py` (at end of file, after the AG-status test):

```python
# -----------------------------------------------------------------------------
# D-dimer (Phase 2a 2026-06-24): VTE-spectrum analyte. Multi-axis derive
# from coagulation_status + inflammation_level + age, with a scenario-flag
# bump for actual VTE events (causes_vte=True on PE/DVT/embolic stroke).
# AD-57 BNP-pattern surgical (formula only).
# -----------------------------------------------------------------------------


@pytest.mark.unit
def test_d_dimer_healthy_state_low():
    """Healthy adult: D-dimer near baseline ~0.3 ug/mL FEU."""
    state = PhysiologicalState()
    labs = derive_lab_values(state, sex="M", age=45)
    assert "D_dimer" in labs
    assert labs["D_dimer"] < 1.0, \
        f"D-dimer={labs['D_dimer']} should be < 1.0 in a healthy adult"


@pytest.mark.unit
def test_d_dimer_age_adjusted_baseline():
    """Older patients have slightly elevated baseline D-dimer (well-documented
    age effect; 0.005 / year above 50)."""
    state = PhysiologicalState()
    young = derive_lab_values(state, sex="M", age=35)
    old = derive_lab_values(state, sex="M", age=85)
    assert old["D_dimer"] > young["D_dimer"], \
        f"old D-dimer {old['D_dimer']} should exceed young {young['D_dimer']}"


@pytest.mark.unit
def test_d_dimer_vte_flag_elevates_to_positive_range():
    """causes_vte=True puts D-dimer in the clinically positive range (>4)."""
    state = PhysiologicalState()
    labs_no_vte = derive_lab_values(state, sex="M", age=60)
    labs_vte = derive_lab_values(state, sex="M", age=60, causes_vte=True)
    assert labs_vte["D_dimer"] > 4.0, \
        f"VTE D-dimer={labs_vte['D_dimer']} should be clinically positive (>4)"
    assert labs_vte["D_dimer"] > labs_no_vte["D_dimer"] + 3.0, \
        f"VTE flag should add ~4 to D-dimer, got delta " \
        f"{labs_vte['D_dimer'] - labs_no_vte['D_dimer']}"


@pytest.mark.unit
def test_d_dimer_sepsis_without_vte_mildly_elevated():
    """Sepsis without VTE: D-dimer rises modestly (inflammation contribution)
    but stays below the VTE-positive threshold."""
    state = PhysiologicalState(inflammation_level=0.85)
    labs = derive_lab_values(state, sex="M", age=60)
    assert labs["D_dimer"] < 2.0, \
        f"sepsis no-VTE D-dimer={labs['D_dimer']} should stay non-specific"


@pytest.mark.unit
def test_d_dimer_dic_alone_can_reach_positive_without_vte():
    """Severe DIC alone (no VTE) can lift D-dimer into the positive
    range — clinically true (consumptive coagulopathy with fibrinolysis).
    Verifies coag axis contributes meaningfully."""
    state = PhysiologicalState(inflammation_level=0.85, coagulation_status=1.0)
    labs = derive_lab_values(state, sex="M", age=60)
    assert labs["D_dimer"] >= 2.0, \
        f"severe DIC D-dimer={labs['D_dimer']} should be elevated"


@pytest.mark.unit
def test_d_dimer_clamps_at_20():
    """Hard ceiling at 20 ug/mL FEU (assay upper limit)."""
    state = PhysiologicalState(inflammation_level=1.0, coagulation_status=1.0)
    labs = derive_lab_values(state, sex="M", age=100, causes_vte=True)
    assert labs["D_dimer"] <= 20.0


@pytest.mark.unit
def test_d_dimer_floor_at_0_15():
    """Floor at 0.15 ug/mL (lab detection floor)."""
    state = PhysiologicalState()
    labs = derive_lab_values(state, sex="M", age=20)
    assert labs["D_dimer"] >= 0.15
```

- [ ] **Step 2: Run failing tests**

```bash
pytest tests/unit/test_physiology.py -k "d_dimer" -v 2>&1 | tail -15
```

Expected: 7 failures. Some on `KeyError: 'D_dimer'`, the `causes_vte` test fails on `TypeError: unexpected keyword`.

- [ ] **Step 3: Add `causes_vte` parameter**

In `clinosim/modules/physiology/engine.py`, find the existing signature (around line 220):

```python
def derive_lab_values(
    state: PhysiologicalState,
    sex: str,
    age: int,
    has_diabetes: bool = False,
    rng: np.random.Generator | None = None,
    hour: int = 6,
    myocardial_injury: bool = False,
) -> dict[str, float]:
```

Replace with:

```python
def derive_lab_values(
    state: PhysiologicalState,
    sex: str,
    age: int,
    has_diabetes: bool = False,
    rng: np.random.Generator | None = None,
    hour: int = 6,
    myocardial_injury: bool = False,
    causes_vte: bool = False,
) -> dict[str, float]:
```

- [ ] **Step 4: Add D_dimer derive**

In the same function, find the Coag section added by PR #80 (after the `labs["Fibrinogen"] = ...` line). Insert immediately after Fibrinogen:

```python
    # D-dimer (ug/mL FEU). Baseline 0.3 + age-adjustment (well-documented
    # +0.005 / year above 50) + inflammation contribution (sepsis lifts
    # modestly, non-VTE-specific) + coagulation_status (DIC/fibrinolysis
    # lifts further). The decisive signal is `causes_vte`: PE/DVT/embolic
    # stroke push D-dimer to clinically positive 5-20 ug/mL territory.
    # Clamp floor 0.15 (laboratory detection floor), ceiling 20 (assay
    # upper limit). AD-57 BNP-pattern surgical: scenario flag is the
    # input, no state mutation, no master-RNG draw.
    age_factor = max(0.0, age - 50) * 0.005
    d_dimer = (
        0.3
        + age_factor
        + infl * 0.5
        + state.coagulation_status * 1.5
        + (4.0 if causes_vte else 0.0)
    )
    labs["D_dimer"] = clamp(d_dimer, 0.15, 20.0)
```

- [ ] **Step 5: Run D-dimer + scenario-flag tests**

```bash
pytest tests/unit/test_physiology.py -k "d_dimer" tests/unit/test_scenario_flags.py -v 2>&1 | tail -20
```

Expected: 7 D-dimer PASS + 6 scenario_flags PASS. (Task 2's keys-match test now sees `causes_vte` as a `derive_lab_values` parameter.)

- [ ] **Step 6: Run full physiology suite (regression check)**

```bash
pytest tests/unit/test_physiology.py -v 2>&1 | tail -5
```

Expected: ALL PASS (60 from PR #80 + 7 new = 67 or thereabouts).

- [ ] **Step 7: Commit Tasks 2 + 3 together**

```bash
git add clinosim/modules/physiology/engine.py tests/unit/test_physiology.py \
        tests/unit/test_scenario_flags.py
git commit -m "$(cat <<'EOF'
feat(physiology): D-dimer derive + causes_vte flag + scenario_flags helper

derive_lab_values gains:
- causes_vte: bool = False parameter (AD-57 scenario-flag pattern,
  mirrors causes_myocardial_injury)
- D_dimer derive (ug/mL FEU):
    age_factor = max(0, age - 50) * 0.005
    D_dimer = clamp(0.3 + age_factor + infl*0.5 + coag*1.5
                    + (4.0 if causes_vte else 0), 0.15, 20.0)

Sample values match clinical expectation:
- healthy 35:               0.32   (negative)
- healthy 75:               0.45   (age-adjusted baseline)
- sepsis no DIC:            0.77   (non-specific elevation, < 2)
- DIC severe:               2.32   (DIC alone can push positive)
- PE no DIC:                4.52   (VTE-positive ≥4)
- PE + sepsis-DIC:          5.97   (additive)

New scenario_flags_from_protocol(protocol) helper centralizes the
existing causes_myocardial_injury read + adds causes_vte read, accepting
dict / Pydantic object / None. Sets up J5 wiring fix in Task 4.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_017dRsomkKQhRVUi5PZY2HSs
EOF
)"
```

---

## Task 4: J5 wiring fix — pass `**flags` at all 4 `derive_lab_values` call sites

**Files:**
- Modify: `clinosim/simulator/inpatient.py` (3 call sites: ~559-560, ~566, ~1680)
- Modify: `clinosim/simulator/emergency.py:122`
- Modify: `clinosim/simulator/outpatient.py:148`

**Interfaces:**
- Consumes: `scenario_flags_from_protocol(protocol)` from Task 2.
- Produces: every `derive_lab_values` call across the simulator passes both scenario flags consistently. ED-route MI patients now get troponin upshift; VTE-flagged disease patients now get D-dimer upshift.

- [ ] **Step 1: Inspect inpatient.py current state**

```bash
grep -nE "derive_lab_values\(|mi_injury|scenario_flags_from_protocol|causes_myocardial_injury" clinosim/simulator/inpatient.py
```

Expected: 3 `derive_lab_values(` call sites (around 559-560 + 566 + 1680), `mi_injury = bool(getattr(protocol, "causes_myocardial_injury", False))` once, and no `scenario_flags_from_protocol` yet.

- [ ] **Step 2: Edit inpatient Pass-1 + lagged variant (~559-566)**

Find the block:

```python
        mi_injury = bool(getattr(protocol, "causes_myocardial_injury", False))
        true_labs = derive_lab_values(state, sex=patient.sex, age=patient.age, has_diabetes=has_diabetes, hour=lab_hour, myocardial_injury=mi_injury)
```

Replace with:

```python
        flags = scenario_flags_from_protocol(protocol)
        true_labs = derive_lab_values(state, sex=patient.sex, age=patient.age, has_diabetes=has_diabetes, hour=lab_hour, **flags)
```

Also locate the line a few lines down:

```python
            lagged_labs = derive_lab_values(lagged_state, sex=patient.sex, age=patient.age, has_diabetes=has_diabetes, hour=lab_hour, myocardial_injury=mi_injury)
```

Replace with:

```python
            lagged_labs = derive_lab_values(lagged_state, sex=patient.sex, age=patient.age, has_diabetes=has_diabetes, hour=lab_hour, **flags)
```

Add the import at the top of the file (if not already present from another physiology import):

```python
from clinosim.modules.physiology.engine import (
    derive_lab_values, scenario_flags_from_protocol,
)
```

(If `derive_lab_values` is imported elsewhere in the file with another statement, just append `scenario_flags_from_protocol` to that existing import.)

- [ ] **Step 3: Edit inpatient.py:1680 (second lab path)**

Find the line:

```python
        true_labs = derive_lab_values(state, sex=patient.sex, age=patient.age, has_diabetes=has_diabetes)
```

Replace with:

```python
        flags = scenario_flags_from_protocol(protocol if 'protocol' in dir() else None)
        true_labs = derive_lab_values(state, sex=patient.sex, age=patient.age, has_diabetes=has_diabetes, **flags)
```

(The `if 'protocol' in dir()` guard handles the fallback path where no disease protocol is in scope — the helper safely returns all-False flags.)

If `protocol` IS in scope at that line (likely — check the surrounding function), simplify to:

```python
        flags = scenario_flags_from_protocol(protocol)
        true_labs = derive_lab_values(state, sex=patient.sex, age=patient.age, has_diabetes=has_diabetes, **flags)
```

- [ ] **Step 4: Edit emergency.py:122**

Find:

```python
    _true_labs = derive_lab_values(_state, sex=patient.sex, age=patient.age, has_diabetes=_has_dm)
```

Replace with:

```python
    _flags = scenario_flags_from_protocol(protocol)
    _true_labs = derive_lab_values(_state, sex=patient.sex, age=patient.age, has_diabetes=_has_dm, **_flags)
```

Add `scenario_flags_from_protocol` to the existing physiology import at the top of `emergency.py`. (`protocol` is a dict here — the helper handles `.get`.)

- [ ] **Step 5: Edit outpatient.py:148**

Find:

```python
    _true_labs = derive_lab_values(_state, sex=patient.sex, age=patient.age, has_diabetes=_has_dm)
```

Replace with:

```python
    _flags = scenario_flags_from_protocol(spec if 'spec' in dir() else None)
    _true_labs = derive_lab_values(_state, sex=patient.sex, age=patient.age, has_diabetes=_has_dm, **_flags)
```

Inspect the surrounding function to confirm whether the disease YAML / spec dict is in scope under the name `spec` or `protocol` (outpatient uses `spec` for the followup schedule per the existing code). Use whichever name is the disease-YAML data.

Add the helper to the import statement. Note the import already says `from clinosim.modules.physiology.engine import derive_lab_values` near that line — append the helper.

- [ ] **Step 6: Run full simulator-relevant integration suite**

```bash
pytest tests/integration/ -x -q 2>&1 | tail -5
```

Expected: all existing tests PASS (existing tests do not check ED MI troponin levels, so the J5 fix is silent here).

- [ ] **Step 7: Run unit suite (regression)**

```bash
pytest tests/unit/ -x -q 2>&1 | tail -5
```

Expected: ALL PASS.

- [ ] **Step 8: Commit**

```bash
git add clinosim/simulator/inpatient.py clinosim/simulator/emergency.py \
        clinosim/simulator/outpatient.py
git commit -m "$(cat <<'EOF'
fix(simulator): wire scenario_flags at all 4 derive_lab_values sites (J5)

Pre-fix: causes_myocardial_injury was only read by inpatient.py Pass-1
daily lab loop (lines 559-566). The second inpatient lab path (~:1680),
emergency.py:122, and outpatient.py:148 called derive_lab_values without
any scenario flag — so MI patients presenting through the ED produced
type-2 troponin (~0.5 ng/mL) instead of MI-grade necrosis (50+ ng/mL).

This was a silent latent defect that the Coag panel PR did not expose
because Coag analytes don't depend on scenario flags. Adding
causes_vte in the same PR-2a scope would have replicated the gap.

Fix: a single scenario_flags_from_protocol(protocol) helper (Task 2)
reads every flag from a dict / Pydantic object / None and returns a
splat-able dict. All four call sites now use `**flags` so any future
flag added to derive_lab_values reaches every venue automatically.

Side-effect on existing data: ED-route MI patients gain MI-grade
troponin/CK-MB. Byte-diff invariant for the other 8 NDJSONs holds
because the change is formula-only (no state mutation, no master-RNG
draw).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_017dRsomkKQhRVUi5PZY2HSs
EOF
)"
```

---

## Task 5: Disease YAML — `causes_vte: true` on PE/DVT/cerebral_infarction

**Files:**
- Modify: `clinosim/modules/disease/reference_data/pulmonary_embolism.yaml`
- Modify: `clinosim/modules/disease/reference_data/deep_vein_thrombosis.yaml`
- Modify: `clinosim/modules/disease/reference_data/cerebral_infarction.yaml`

**Interfaces:**
- Produces: each of the three disease YAMLs declares `causes_vte: true` at the top level (sibling of `disease_id` / `causes_myocardial_injury`). `scenario_flags_from_protocol` will pick it up and `derive_lab_values` will emit positive D-dimer for these patients.

- [ ] **Step 1: Inspect a working example**

```bash
head -15 clinosim/modules/disease/reference_data/acute_mi.yaml
```

Expected: `causes_myocardial_injury: true` appears in the top-level keys (around line 6).

- [ ] **Step 2: Add to pulmonary_embolism.yaml**

```bash
head -10 clinosim/modules/disease/reference_data/pulmonary_embolism.yaml
```

Insert `causes_vte: true   # PE — clot generation + fibrinolysis → D-dimer ↑↑` immediately after the line that has `disease_id:` (or wherever the `acute_mi.yaml` analogue sits — copy the placement style).

- [ ] **Step 3: Add to deep_vein_thrombosis.yaml**

Same placement: top-level key after `disease_id:`:
```yaml
causes_vte: true   # DVT — same mechanism as PE
```

- [ ] **Step 4: Add to cerebral_infarction.yaml**

```yaml
causes_vte: true   # Embolic ischemic stroke (cardioembolic / large-artery
                   # thrombo-embolic); D-dimer behaves like VTE. NOT
                   # appropriate for hemorrhagic_stroke (mechanism is
                   # intracerebral fibrinolysis, captured by
                   # coagulation_status alone).
```

- [ ] **Step 5: Verify the Pydantic protocol model accepts the new key**

```bash
pytest tests/unit -k "disease and protocol" -v 2>&1 | tail -10
```

Expected: PASS. If the Pydantic model is strict and rejects unknown fields, add `causes_vte: bool = False` to the protocol class. (Check `clinosim/types/disease.py` or similar; the precedent is `causes_myocardial_injury`.) Inspect:

```bash
grep -nE "causes_myocardial_injury|causes_vte" clinosim/types/*.py clinosim/modules/disease/*.py 2>&1
```

If the field exists for `causes_myocardial_injury`, mirror it for `causes_vte`.

- [ ] **Step 6: Run unit + integration suite**

```bash
pytest tests/unit/ tests/integration/ -x -q 2>&1 | tail -5
```

Expected: ALL PASS.

- [ ] **Step 7: Commit**

```bash
git add clinosim/modules/disease/reference_data/pulmonary_embolism.yaml \
        clinosim/modules/disease/reference_data/deep_vein_thrombosis.yaml \
        clinosim/modules/disease/reference_data/cerebral_infarction.yaml \
        clinosim/types/
git commit -m "$(cat <<'EOF'
feat(disease): causes_vte on PE / DVT / cerebral_infarction

Three disease YAMLs gain the new VTE-spectrum scenario flag introduced
in Task 3:

- pulmonary_embolism.yaml: PE itself, primary VTE event
- deep_vein_thrombosis.yaml: DVT, same mechanism
- cerebral_infarction.yaml: most strokes are embolic (cardioembolic or
  large-artery thrombo-embolic) and D-dimer behaves like VTE

hemorrhagic_stroke.yaml deliberately does NOT get the flag — mechanism
is intracerebral fibrinolysis (captured by coagulation_status alone),
not venous-thrombus-derived fibrin breakdown.

AF-RVR / sepsis / COPD / acute_mi also order D-dimer at probability but
do NOT get the flag: their elevation should be non-specific
(inflammation/DIC), not VTE-grade.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_017dRsomkKQhRVUi5PZY2HSs
EOF
)"
```

---

## Task 6: AD-59 isolation guard + Coag integration tests

**Files:**
- Modify: `tests/integration/test_individual_lab_isolation.py`
- Modify: `tests/integration/test_panel_expansion_coag.py`

**Interfaces:**
- Produces: invariant tests that pin (a) PE patients now produce RESULTED D-dimer orders with clinically positive values, (b) the J5 fix lifts ED MI troponin.

- [ ] **Step 1: Add PE D-dimer guard to isolation test**

Append to `tests/integration/test_individual_lab_isolation.py`:

```python
@pytest.mark.integration
def test_pe_individual_d_dimer_order_now_resulted():
    """pulmonary_embolism.yaml orders {test:"D_dimer", urgency:"stat"} at
    admission. After Phase 2a (Tasks 3+5) D-dimer derives with the new
    causes_vte flag and PE patients land in the clinically positive
    range (>4 ug/mL FEU).

    Counterpart to test_dka_individual_cl_order_now_resulted (Cl) and
    test_sepsis_individual_fibrinogen_order_now_resulted (Fibrinogen) —
    same AD-59 invariant exercised for the new VTE-flag path."""
    scenario = ForcedScenario(
        disease_id="pulmonary_embolism", count=3, severity="moderate",
    )
    cfg = SimulatorConfig(random_seed=42, country="US")
    dataset = run_forced(scenario, cfg)

    for record in dataset.patients:
        dd = [
            o for o in record.orders
            if o.display_name == "D_dimer"
            and not (o.order_id.endswith("-D_dimer") and "-" in o.order_id[:-len("-D_dimer")])
        ]
        assert dd, (
            f"PE patient {record.patient.patient_id} should have ≥1 "
            f"individual D_dimer order from pulmonary_embolism.yaml"
        )
        resulted = [o for o in dd if o.status == OrderStatus.RESULTED]
        assert resulted, (
            f"PE patient {record.patient.patient_id}: every D_dimer "
            f"order is non-RESULTED — derive_lab_values must produce "
            f"D_dimer so the order resolves"
        )
        for o in resulted:
            assert o.result is not None and o.result.value is not None
            assert 4.0 <= o.result.value <= 20.0, (
                f"PE D-dimer {o.result.value} should be clinically positive"
            )
```

- [ ] **Step 2: Add J5 evidence to Coag integration test**

Append to `tests/integration/test_panel_expansion_coag.py`:

```python
@pytest.mark.integration
def test_pe_emits_clinically_positive_d_dimer():
    """End-to-end: pulmonary_embolism patients emit D-dimer Observations
    with p50 > 4 ug/mL FEU (clinically positive)."""
    scenario = ForcedScenario(
        disease_id="pulmonary_embolism", count=5, severity="moderate",
    )
    cfg = SimulatorConfig(random_seed=42, country="US")
    dataset = run_forced(scenario, cfg)

    values = []
    for record in dataset.patients:
        for o in record.orders:
            if (o.result is not None and o.result.lab_name == "D_dimer"
                    and o.status.value if hasattr(o.status, "value") else o.status):
                values.append(o.result.value)
    assert values, "expected ≥1 D_dimer result across PE cohort"
    median = sorted(values)[len(values) // 2]
    assert median > 4.0, \
        f"PE D-dimer median {median} should be clinically positive (>4)"


@pytest.mark.integration
def test_ed_mi_now_emits_high_troponin_after_j5_fix():
    """J5 fix evidence: ED-route MI patients now produce MI-grade
    troponin (>5 ng/mL) instead of the pre-fix type-2 background
    (~0.5 ng/mL). Before the fix, emergency.py:122 called
    derive_lab_values without myocardial_injury=True so MI never
    upshifted troponin in the ED."""
    scenario = ForcedScenario(
        disease_id="acute_mi", count=5, severity="moderate",
    )
    cfg = SimulatorConfig(random_seed=42, country="US")
    dataset = run_forced(scenario, cfg)

    troponins = []
    for record in dataset.patients:
        for o in record.orders:
            if o.result is not None and o.result.lab_name == "Troponin_I":
                troponins.append(o.result.value)
    assert troponins, "expected ≥1 Troponin_I result"
    # At least one troponin should be MI-grade
    high = [v for v in troponins if v > 5.0]
    assert high, (
        f"expected at least one MI-grade troponin (>5 ng/mL) in acute_mi "
        f"cohort after J5 fix; got values {sorted(troponins)[-5:]}"
    )
```

- [ ] **Step 3: Run new tests**

```bash
pytest tests/integration/test_individual_lab_isolation.py tests/integration/test_panel_expansion_coag.py -v 2>&1 | tail -15
```

Expected: all PASS (existing tests + 3 new).

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_individual_lab_isolation.py \
        tests/integration/test_panel_expansion_coag.py
git commit -m "$(cat <<'EOF'
test(integration): D-dimer VTE invariant + ED MI troponin J5 evidence

Three integration tests pin Phase 2a behavior:
- PE patients: individual D_dimer order RESULTED with value 4-20 ug/mL
  (AD-59 invariant + causes_vte flag working end-to-end)
- PE D-dimer median across cohort > 4 (clinically positive)
- ED-route acute_mi patients now produce at least one MI-grade
  troponin (>5 ng/mL) — direct evidence of the J5 wiring fix
  (emergency.py:122 was ignoring causes_myocardial_injury pre-fix)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_017dRsomkKQhRVUi5PZY2HSs
EOF
)"
```

---

## Task 7: Byte-diff verification vs master `b6bc8eab`

**Files:**
- Create: `scratchpad/phase2a_byte_diff.py`

**Interfaces:**
- Produces: `scratchpad/phase2a_byte_diff_results.md` reporting which NDJSONs are byte-identical and the expected deltas.

- [ ] **Step 1: Create the diff script**

Copy `scratchpad/coag_panel_byte_diff.py` as a template:

```bash
cp scratchpad/coag_panel_byte_diff.py scratchpad/phase2a_byte_diff.py
```

Edit `scratchpad/phase2a_byte_diff.py`:

- Change `MASTER_REF = "fbd80607"` → `MASTER_REF = "b6bc8eab"` (current master HEAD post-Coag PR).
- Update `NEW_LOINC` to `{"30240-9": "D-dimer (US)"}`.
- Update `NEW_JLAC10` to `{"2B140": "D-dimer (JP)"}`.
- Remove `COAG_PANEL_LOINC` reporting (no new DR panel; D-dimer is panel-external).
- Update the module docstring to describe Phase 2a expectations:
  - IDENTICAL: Patient/Encounter/Condition/MedicationRequest/MedicationAdministration/Procedure/ImagingStudy/Immunization/FamilyMemberHistory
  - CHANGED: Observation (D-dimer additions + ED MI troponin uplift from J5), DiagnosticReport (no Coag-DR changes; existing Coag DRs unchanged)

- [ ] **Step 2: Generate from master `b6bc8eab` and from branch**

```bash
python scratchpad/phase2a_byte_diff.py 2>&1 | tail -50
```

This will:
1. Stash to ensure clean tree.
2. `git checkout b6bc8eab` and generate US + JP @ p=2000 seed=42 to `scratchpad/phase2a_byte_diff_master/{us,jp}/fhir_r4/`.
3. `git checkout feat/phase2a-vte-d-dimer` and generate to `scratchpad/phase2a_byte_diff_branch/{us,jp}/fhir_r4/`.
4. Write report to `scratchpad/phase2a_byte_diff_results.md`.

- [ ] **Step 3: Read and verify the report**

```bash
cat scratchpad/phase2a_byte_diff_results.md
```

Required outcome:
- `Patient.ndjson` master == branch (both US and JP)
- `Encounter.ndjson` master == branch
- `Condition.ndjson` master == branch
- `MedicationRequest.ndjson` master == branch
- `MedicationAdministration.ndjson` master == branch
- `Procedure.ndjson` master == branch
- `ImagingStudy.ndjson` master == branch (or both MISSING)
- `Immunization.ndjson` master == branch
- `FamilyMemberHistory.ndjson` master == branch
- `Observation.ndjson` changes (D-dimer + ED MI troponin uplift)
- `DiagnosticReport.ndjson` essentially unchanged (no Coag-DR delta because D-dimer is panel-external)

If any expected-IDENTICAL file differs, the J5 fix is touching state somewhere it shouldn't. Investigate before proceeding.

- [ ] **Step 4: Commit**

```bash
git add scratchpad/phase2a_byte_diff.py scratchpad/phase2a_byte_diff_results.md
git commit -m "$(cat <<'EOF'
test(byte-diff): Phase 2a — D-dimer + J5 fix vs master b6bc8eab

US/JP p=2000 seed=42. Expected outcome:
- 9 NDJSONs (Patient/Encounter/Condition/Medication*/Procedure/
  Imaging/Immunization/FamilyMemberHistory) byte-identical (AD-59
  invariant: formula-only changes do not shift unrelated cohorts)
- Observation.ndjson changes for two reasons:
    1. New D-dimer Observations across 7 D-dimer-ordering disease
       cohorts (now resulting; were silently dropped pre-PR)
    2. ED-route MI patients gain MI-grade Troponin / CK-MB (J5 fix)
- DiagnosticReport.ndjson essentially unchanged (D-dimer is
  panel-external; Coag panel components PT_INR/APTT unchanged)

The script is run vs master b6bc8eab; results saved to
scratchpad/phase2a_byte_diff_results.md.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_017dRsomkKQhRVUi5PZY2HSs
EOF
)"
```

---

## Task 8: 3-axis DQR + calibration loop

**Files:**
- Create: `scratchpad/dqr_phase2a_vte_review.py`
- Create: `docs/reviews/2026-06-24-phase2a-vte-data-quality-review.md`

**Interfaces:**
- Consumes: generated US p=10000 + JP p=5000 seed=42 FHIR output.
- Produces: DQR report; if any clinical threshold misses, adjust the D-dimer formula coefficient (the `4.0` VTE bump) and re-run.

- [ ] **Step 1: Adapt DQR script from Coag PR template**

```bash
cp scratchpad/dqr_coag_panel_review.py scratchpad/dqr_phase2a_vte_review.py
```

Replace the Coag-specific sections with VTE-specific checks:

```python
"""Data-quality review for Phase 2a VTE + D-dimer PR — three axes.

1. STRUCTURAL HYGIENE
   - LOINC 30240-9 (US) / JLAC10 2B140 (JP) resolve to authoritative display
   - All D-dimer Observations have referenceRange
   - No display==code on D-dimer codings

2. CLINICAL FIDELITY
   - PE (I26) admit-day D-dimer p50 >= 4 (clinically positive)
   - DVT (I80) admit-day D-dimer p50 >= 4
   - Cerebral_infarction (I63) admit-day D-dimer p50 >= 4
   - Sepsis (A41) admit-day D-dimer p50 < 2 (non-specific elevation)
   - Healthy / non-VTE outpatient: D-dimer < 1 in >= 80% of samples
   - J5 fix evidence: ED-route MI patients show Troponin p75 >= 10
     (was ~0.5 pre-fix)

3. JP LOCALIZATION
   - US output: zero Japanese characters in D-dimer fields
   - JP output: D-dimer Observation display in Japanese
   - jlac10.yaml 2B140 ja = "D-Dダイマー" (not English abbreviation)
"""
```

Adapt the existing check functions. Reuse `admit_obs_for_diseases`, `obs_values_by_lab`, `pct` from the Coag template.

- [ ] **Step 2: Generate US p=10000**

```bash
mkdir -p scratchpad/phase2a_dqr_us
python -m clinosim.simulator.cli generate --country US -p 10000 -s 42 \
  -o scratchpad/phase2a_dqr_us --format fhir csv 2>&1 | tail -3
```

- [ ] **Step 3: Generate JP p=5000**

```bash
mkdir -p scratchpad/phase2a_dqr_jp
python -m clinosim.simulator.cli generate --country JP -p 5000 -s 42 \
  -o scratchpad/phase2a_dqr_jp --format fhir csv 2>&1 | tail -3
```

- [ ] **Step 4: Run DQR**

```bash
python scratchpad/dqr_phase2a_vte_review.py scratchpad/phase2a_dqr_us US
python scratchpad/dqr_phase2a_vte_review.py scratchpad/phase2a_dqr_jp JP
```

- [ ] **Step 5: Inspect results, calibrate if needed**

```bash
cat scratchpad/phase2a_dqr_us.md scratchpad/phase2a_dqr_jp.md
```

Per-failure adjustment table:

| Failure | Adjustment |
|---|---|
| PE/DVT D-dimer p50 < 4 | Raise VTE bump `4.0` → `5.0` in `derive_lab_values` |
| Cerebral_infarction p50 < 4 but PE/DVT >= 4 | Calibration is right; cerebral_infarction is a sub-class of VTE flag — accept |
| Sepsis no-VTE p50 >= 2 | Lower `infl * 0.5` → `infl * 0.3` |
| Healthy non-VTE D-dimer >= 1 in > 20% samples | Lower baseline `0.3` to `0.25` |
| ED MI troponin p75 < 10 | J5 fix is not landing — inspect call-site changes |

Any adjustment → re-run **Task 7** (byte-diff) first to confirm only Observation changes, then re-run DQR.

If acceptance bands need realistic re-tightening (similar to the Coag PR's first DQR run revealing admit-day Fibrinogen DIC was unrealistic), update the script's documented threshold + re-run.

- [ ] **Step 6: Write the DQR report**

Create `docs/reviews/2026-06-24-phase2a-vte-data-quality-review.md` following the structure of `docs/reviews/2026-06-24-coag-panel-data-quality-review.md`:

- Generator params (US p=10000 + JP p=5000, seed=42, master `b6bc8eab` + branch HEAD)
- Per-axis PASS/FAIL table with exact percentile numbers
- J5 fix evidence (ED MI troponin distribution before / after)
- Open follow-ups (Phase 2b on_anticoagulation, etc.)

- [ ] **Step 7: Commit**

```bash
git add scratchpad/dqr_phase2a_vte_review.py \
        scratchpad/phase2a_dqr_us.md scratchpad/phase2a_dqr_jp.md \
        docs/reviews/2026-06-24-phase2a-vte-data-quality-review.md
# Also stage any coefficient adjustments + threshold-tightening updates
git add clinosim/modules/physiology/engine.py tests/unit/test_physiology.py
git commit -m "$(cat <<'EOF'
test(dqr): 3-axis review Phase 2a — D-dimer + J5 fix — all axes PASS

US p=10000 + JP p=5000, seed=42.

Structural axis (PASS): LOINC 30240-9 + JLAC10 2B140 resolve, all
D-dimer Observations have refRange, no display==code.

Clinical axis (PASS): PE/DVT/cerebral_infarction D-dimer p50 in the
clinically-positive band (>4 ug/mL FEU); sepsis no-VTE p50 stays
non-specific (<2); ED MI troponin p75 demonstrates the J5 fix lifting
ED-presentation MI from type-2 background to MI-grade necrosis.

JP language axis (PASS): zero US Japanese leak, JP D-dimer display in
Japanese, jlac10.yaml 2B140 ja = "D-Dダイマー" (JCCLS-official, PR #76
rule preserved).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_017dRsomkKQhRVUi5PZY2HSs
EOF
)"
```

---

## Task 9: Full docs sync (PR #79 lesson — same PR)

**Files:**
- Modify: `README.md`, `README.ja.md`, `DESIGN.md`,
  `clinosim/modules/physiology/README.md`, `CLAUDE.md`, `TODO.md`.

**Interfaces:**
- Produces: every user- and contributor-facing doc reflects "VTE-spectrum D-dimer active + J5 scenario-flag wiring fix".

- [ ] **Step 1: README.md**

Insert a new bullet after the Coag-panel bullet added by PR #80:

> - **VTE-spectrum D-dimer** (LOINC 30240-9): `D_dimer` derive from `coagulation_status` + `inflammation_level` + age + a new `causes_vte` scenario flag (set on PE / DVT / embolic ischemic stroke). PE/DVT show clinically positive p50 ≥ 4 ug/mL FEU; sepsis without VTE stays non-specific (< 2). Hemorrhagic stroke deliberately uses `coagulation_status` alone (different mechanism). Wiring fix bundled: `scenario_flags_from_protocol` helper now passes both `causes_myocardial_injury` (existing) and `causes_vte` (new) at every `derive_lab_values` call site — ED-route MI patients now show MI-grade troponin, previously silently produced type-2 background only.

- [ ] **Step 2: README.ja.md**

Mirror, Japanese with English technical terms:

> - **VTE スペクトラム D-dimer** (LOINC 30240-9): `D_dimer` を `coagulation_status` + `inflammation_level` + 年齢 + 新 `causes_vte` シナリオフラグ (PE / DVT / 塞栓性脳梗塞に設定) から導出。PE/DVT は p50 ≥ 4 ug/mL FEU の臨床的陽性、敗血症 VTE なしは非特異な < 2 に留まる。出血性脳梗塞は機序が異なるので `coagulation_status` のみ。配線修正同梱: `scenario_flags_from_protocol` ヘルパで `causes_myocardial_injury` (既存) と `causes_vte` (新) を `derive_lab_values` の全コールサイトで一律に渡すように — ED ルート MI 患者が MI 帯トロポニンを示すようになる (修正前は type-2 背景のみ)

- [ ] **Step 3: DESIGN.md**

Extend AD-59 entry (do NOT add a new ADR):

Find the AD-59 line (`| AD-59 | 2026-06-23 | **Per-order lab RNG isolation.**...`) and append after the existing "Coag panel PR" reference:

> Phase 2a (2026-06-24, D-dimer + `causes_vte`) is the second follow-up to add a new analyte through this isolation — byte-diff again confirms zero shift in unrelated NDJSONs.

- [ ] **Step 4: `clinosim/modules/physiology/README.md`**

In the derivation table (around the existing Fibrinogen entry), add `D_dimer` row:

```
| `D_dimer` | `coagulation_status` + `inflammation_level` + age + `causes_vte` | VTE-spectrum (PE/DVT/embolic stroke) → ≥ 4 ug/mL FEU |
```

Add a scenario-flag subsection naming `scenario_flags_from_protocol` as the canonical entry point.

- [ ] **Step 5: CLAUDE.md**

In the architecture-rules section, update or add a bullet about scenario flags:

> - **Scenario flags into `derive_lab_values`** — Disease YAMLs declare `causes_X: true` flags that lift specific labs at the lab-derive step (no state mutation; AD-57 BNP-pattern surgical). Always read flags via `scenario_flags_from_protocol(protocol)` and pass with `**flags` so every call site (inpatient/ED/outpatient) wires them automatically; never add a fourth `flag=value` parameter to a call site or you risk the J5 gap recurring.

- [ ] **Step 6: TODO.md**

Above the Coag-panel entry, add the Phase 2a entry summarizing the work (mirrors the Coag entry style). Update the deferred-backlog list at the end to remove Phase 2a items (causes_vte + D-dimer + J5) and keep:
- Phase 2b — `on_anticoagulation` axis (I5)
- I4 panel-YAML unification refactor
- I6 `clinical_course.actions[].test` disambiguation
- I7 `platelet_status` axis independence

- [ ] **Step 7: Run full unit + integration regression**

```bash
pytest tests/unit/ tests/integration/ -x -q 2>&1 | tail -5
```

Expected: ALL PASS.

- [ ] **Step 8: Commit**

```bash
git add README.md README.ja.md DESIGN.md \
        clinosim/modules/physiology/README.md \
        CLAUDE.md TODO.md
git commit -m "$(cat <<'EOF'
docs(sync): Phase 2a — VTE/D-dimer + J5 wiring fix

Documents the new VTE-spectrum D-dimer activation + scenario_flags
wiring helper in every user-facing and contributor-facing doc, in the
same PR (PR #79 lesson — no post-merge sync follow-up):

- README.md / README.ja.md: bullet for D-dimer + causes_vte + J5
- DESIGN.md: AD-59 entry extended noting Phase 2a as second follow-up
- modules/physiology/README.md: D-dimer derive table row + scenario-flag
  subsection (scenario_flags_from_protocol is the canonical entry point)
- CLAUDE.md: scenario-flag architecture rule — always go via the
  helper and **flags, never add a fourth flag=value parameter
- TODO.md: Phase 2a marked done; carried backlog = Phase 2b
  (on_anticoagulation), I4/I6/I7

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_017dRsomkKQhRVUi5PZY2HSs
EOF
)"
```

---

## Task 10: PR creation

**Files:** none (gh action).

**Interfaces:**
- Consumes: branch `feat/phase2a-vte-d-dimer` with all commits from Tasks 1–9.
- Produces: GitHub PR with audit links in the body.

- [ ] **Step 1: Final unit + integration + e2e run**

```bash
pytest -x -q 2>&1 | tail -5
```

Expected: ALL PASS. Re-run any flaky e2e individually per memory `feedback_clinosim_workflow`.

- [ ] **Step 2: Push branch**

```bash
git push -u origin feat/phase2a-vte-d-dimer
```

- [ ] **Step 3: Open PR**

```bash
gh pr create --title "feat(physiology): Phase 2a — D-dimer (LOINC 30240-9) + causes_vte + J5 wiring fix" --body "$(cat <<'EOF'
## Summary

Phase 2a of the Coag-family work (PR #80 deferred backlog item 1).
Activates **D-dimer** (LOINC 30240-9 / JLAC10 2B140) by extending
`physiology.derive_lab_values` with:

- New `causes_vte: bool = False` parameter (AD-57 scenario-flag pattern, mirrors `causes_myocardial_injury`)
- D-dimer derive (ug/mL FEU):

  ```
  age_factor = max(0, age - 50) * 0.005
  D_dimer = clamp(0.3 + age_factor + infl*0.5 + coag*1.5
                  + (4.0 if causes_vte else 0), 0.15, 20.0)
  ```

Three disease YAMLs get `causes_vte: true`: pulmonary_embolism, deep_vein_thrombosis, cerebral_infarction (embolic ischemic stroke — D-dimer behaves like VTE because most strokes are embolic, not because the clot is venous). **hemorrhagic_stroke does NOT** get the flag — mechanism is intracerebral fibrinolysis, captured by `coagulation_status` alone.

**Improvement J5 (same PR)**: introduces `scenario_flags_from_protocol(protocol)` helper and replaces `myocardial_injury=mi_injury` at every `derive_lab_values` call site with `**flags`. Pre-fix only `inpatient.py:559-560` (Pass-1 daily loop) read `causes_myocardial_injury`; the second inpatient lab path (~:1680), `emergency.py:122`, and `outpatient.py:148` passed nothing — so MI patients in the ED produced type-2 troponin (~0.5 ng/mL) instead of MI-grade necrosis. Adding `causes_vte` in the same PR scope would have replicated the gap.

## Audit summary

3-axis DQR (US p=10000 + JP p=5000, seed=42) — see `docs/reviews/2026-06-24-phase2a-vte-data-quality-review.md`:
- Structural: LOINC 30240-9 + JLAC10 2B140 resolve, D-dimer refRange 100%, no display==code
- Clinical: PE/DVT/cerebral_infarction D-dimer p50 ≥ 4 (clinically positive); sepsis no-VTE p50 < 2 (specificity); ED MI troponin p75 lifted by J5 fix
- JP language: zero US Japanese leak, JP D-dimer display in Japanese, `jlac10.yaml` 2B140 `ja` = `D-Dダイマー` (JCCLS-official, PR #76 rule preserved)

Byte-diff vs master `b6bc8eab` @ p=2000 seed=42 — `scratchpad/phase2a_byte_diff_results.md`:
- IDENTICAL: Patient/Encounter/Condition/Medication*/Procedure/Imaging/Immunization/FamilyMemberHistory (AD-59 invariant)
- CHANGED: Observation (new D-dimer + J5 ED MI troponin uplift, intentional)
- DR essentially unchanged (D-dimer is panel-external to Coag LOINC 24373-3)

## Improvements adopted

- **J1**: hemorrhagic_stroke boundary documented (no flag, mechanism differs)
- **J2**: cerebral_infarction included (D-dimer behaves like VTE — flag name is "VTE-spectrum")
- **J3**: D-dimer unit (FEU vs DDU) verified — both US/JP use FEU at different cutoffs, no change needed
- **J5**: scenario-flag wiring centralized in `scenario_flags_from_protocol`, all 4 sites now consistent

## Deferred to follow-up PRs

- **Phase 2b**: `on_anticoagulation` axis for warfarin/heparin INR therapeutic-range modelling (I5)
- **I4**: panel-YAML unification refactor
- **I6**: `clinical_course.actions[].test` field disambiguation
- **I7**: `platelet_status` axis independence

## Spec / plan

- Spec: `docs/superpowers/specs/2026-06-24-phase2a-vte-d-dimer-design.md`
- Plan: `docs/superpowers/plans/2026-06-24-phase2a-vte-d-dimer.md`

## Test plan

- [x] unit + integration green (~660 tests)
- [x] e2e golden green (regenerated for D-dimer Observations + ED MI troponin uplift)
- [x] byte-diff invariant verified (`scratchpad/phase2a_byte_diff_results.md`)
- [x] 3-axis DQR PASS (`docs/reviews/2026-06-24-phase2a-vte-data-quality-review.md`)

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_017dRsomkKQhRVUi5PZY2HSs
EOF
)"
```

- [ ] **Step 4: Surface the PR URL to the user.**

---

## Self-Review

**1. Spec coverage** — every scope item in §2 of the spec maps to a task:

| Spec §2 in-scope | Task |
|---|---|
| Physiology extension (`causes_vte` param + D_dimer derive) | Task 3 |
| `scenario_flags_from_protocol` helper (J5 prerequisite) | Task 2 |
| Disease YAML scenario-flag additions (PE/DVT/cerebral_infarction) | Task 5 |
| J5 wiring fix at all 4 call sites | Task 4 |
| Locale code mappings + LOINC/JLAC10 additions | Task 1 |
| AD-59 invariant guard | Task 6 |
| Whole-population DQR | Task 8 |
| Byte-diff invariant verification | Task 7 |
| Docs sync in same PR | Task 9 |

Improvement table J1/J2/J3/J5 all have tasks. J1/J2 land in Task 5 disease YAML comments + spec boundary text; J3 documented in spec as "no action"; J5 lands as Tasks 2+4.

**2. Placeholder scan** — no "TBD", no "add error handling", no untyped references. The one item flagged "investigate at implementation time" (`inpatient.py:1680`'s scope-of-`protocol`) is bounded by the same step: a single 1-line grep and one of two simple alternatives written out.

**3. Type consistency** — `scenario_flags_from_protocol(protocol) -> dict[str, bool]` returns exact keys `{"myocardial_injury", "causes_vte"}` that match `derive_lab_values`'s parameter names. The keys-match test (Task 2) pins the contract. Tasks 4-5 use `**flags` consistently. Disease YAML key is `causes_vte:` (with `causes_` prefix) — the helper translates to `derive_lab_values`'s `causes_vte` parameter name (also `causes_vte` — matches).

Plan ready.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-24-phase2a-vte-d-dimer.md`. Two execution options:

**1. Subagent-Driven** — fresh subagent per task with two-stage review; best where independent verification adds value.

**2. Inline Execution (recommended)** — physiology + simulator + locale, single-module tightly-coupled; memory `feedback_clinosim_workflow` recommends inline for that shape; matches PR #74/#75/#78/#80 cadence. Natural checkpoints: after Task 3 (D-dimer derives + helper green), Task 4 (J5 wiring complete), Task 7 (byte-diff verified), Task 8 (DQR calibration loop), Task 9 (docs sync).
