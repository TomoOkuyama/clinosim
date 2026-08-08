# BNP Heart-Failure Specificity Implementation Plan

**Status:** **IMPLEMENTED** (2026-06-20) — see commits `ac36ff63` (couple BNP to
ventricular wall stress) and `1c22a3e6` (finalize BNP coupling coefficients
from generation audit). Retained as a historical record of the
implementation plan that produced the current BNP mapping in
`physiology/engine.py:283`. The plan's checkbox steps are unchecked because
they were executed in a prior session whose plan-file was never committed;
the engine code, unit test `test_bnp_discriminates_hf_from_mi`, and audit
artifacts are the authoritative outputs.

---

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the BNP lab value discriminate heart failure from MI/other cardiac dysfunction by coupling the physiology engine's BNP mapping to ventricular wall stress (volume overload × cardiac dysfunction).

**Architecture:** Single-line change to the deterministic state→lab BNP mapping in `physiology/engine.py`, adding a `max(0, volume_status) × (1 − cardiac)` coupling term so HF (low cardiac × high volume) rises sharply while uncomplicated MI (low cardiac, normal volume) and non-cardiac fluid overload (preserved heart) stay moderate/low. A BNP assay ceiling is added to the observation re-clamp so the exponential cannot diverge. Coefficients are finalized by a generation audit. No new state axis, no new module, no disease/encounter YAML change — `volume_status` is already set by HF/MI disease YAML `initial_state_impact`.

**Tech Stack:** Python 3.11+, numpy, pytest. ruff + mypy(strict). Determinism via seeded `numpy.random.Generator` (AD-16) — BNP mapping itself uses no rng.

## Global Constraints

- Code comments/docstrings in English; line length 100; ruff formatter; mypy strict.
- Determinism (AD-16): BNP mapping is a pure state→lab function, no rng, no perturbation of the main random stream.
- Only BNP changes intentionally — every other lab/vital/diagnosis/blood-gas value mathematically unchanged.
- Coefficients live inline in the engine like existing troponin/CRP/Na coefficients (no new config file).
- Authoritative clinical targets: normal/non-cardiac BNP <100 pg/mL; MI/other cardiac 100–300; HF exacerbation 800–1500; assay ceiling 5000 pg/mL.
- Generation-audit artifacts go to `/tmp` only (never `output/`) and are deleted after the audit.
- git: branch from master; commit messages end with the `Co-Authored-By` trailer; commit/push/merge only on user instruction.
- e2e is property/determinism-based and CPU-flaky — rerun the individual file before declaring failure.

---

### Task 1: Couple BNP mapping to ventricular wall stress

**Files:**
- Modify: `clinosim/modules/physiology/engine.py` (BNP line, currently `labs["BNP"] = 30 * math.exp((1 - cardiac) * 4)`, ~line 246)
- Test: `tests/unit/test_physiology.py` (add to the `derive_lab_values` test class, near `test_normal_state` / `test_dka_hyperglycemia_from_glucose_status` ~line 152–200)

**Interfaces:**
- Consumes: `derive_lab_values(state: PhysiologicalState, sex: str, age: int, ...) -> dict[str, float]` (existing); `PhysiologicalState` fields `cardiac_function`, `volume_status` (existing).
- Produces: BNP value in returned `labs["BNP"]` now a function of both `cardiac_function` and `volume_status` (coupling). No signature change.

- [ ] **Step 1: Write the failing tests**

Add to `tests/unit/test_physiology.py` in the same class as `test_normal_state` (the `derive_lab_values` tests):

```python
    def test_bnp_discriminates_hf_from_mi(self):
        # HF exacerbation: low cardiac + volume overload (wall stress) -> high BNP.
        hf = derive_lab_values(
            PhysiologicalState(cardiac_function=0.43, volume_status=0.65),
            sex="M", age=75)
        # Uncomplicated MI: low cardiac, normal/low volume -> moderate BNP.
        mi = derive_lab_values(
            PhysiologicalState(cardiac_function=0.35, volume_status=-0.10),
            sex="M", age=75)
        # Normal heart -> near-baseline BNP.
        normal = derive_lab_values(
            PhysiologicalState(cardiac_function=0.90, volume_status=0.0),
            sex="M", age=75)
        assert normal["BNP"] < 100
        assert 100 < mi["BNP"] < 400
        assert hf["BNP"] > 800
        assert hf["BNP"] > 5 * mi["BNP"]

    def test_bnp_volume_term_gated_by_cardiac(self):
        # Volume overload in a PRESERVED heart (e.g. cirrhosis ascites, AKI) must NOT
        # spuriously elevate BNP — the volume term is gated by cardiac dysfunction.
        preserved = derive_lab_values(
            PhysiologicalState(cardiac_function=0.85, volume_status=0.50),
            sex="M", age=75)
        assert preserved["BNP"] < 100

    def test_bnp_dehydration_does_not_suppress(self):
        # Negative volume_status (dehydration) must not push BNP below the cardiac floor.
        dry = derive_lab_values(
            PhysiologicalState(cardiac_function=0.50, volume_status=-0.60),
            sex="M", age=75)
        floor = derive_lab_values(
            PhysiologicalState(cardiac_function=0.50, volume_status=0.0),
            sex="M", age=75)
        assert dry["BNP"] == pytest.approx(floor["BNP"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/unit/test_physiology.py -k bnp -v`
Expected: `test_bnp_discriminates_hf_from_mi` FAILS (current mapping gives MI BNP > HF BNP, so `hf > 5*mi` and `hf > 800` fail); the other two may pass or fail depending on current behavior. At least the discrimination test must fail.

- [ ] **Step 3: Implement the coupled mapping**

In `clinosim/modules/physiology/engine.py`, replace the BNP line:

```python
    labs["BNP"] = 30 * math.exp((1 - cardiac) * 4)
```

with:

```python
    # BNP reflects ventricular wall stress = volume/pressure load ON a stressed ventricle.
    # The volume term is gated by cardiac dysfunction (coupling), so volume overload only
    # elevates BNP when the heart is failing: HF (low cardiac x high volume) rises sharply,
    # uncomplicated MI (low cardiac, normal volume) stays moderate, and non-cardiac fluid
    # overload in a preserved heart (cirrhosis ascites, AKI) stays low. Deterministic
    # (state -> lab, no rng). Coefficients tuned by generation audit (see plan Task 3).
    labs["BNP"] = 30.0 * math.exp(
        (1 - cardiac) * 2.5 + max(0.0, state.volume_status) * (1 - cardiac) * 6.0
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/unit/test_physiology.py -k bnp -v`
Expected: all three BNP tests PASS.

- [ ] **Step 5: Run the full physiology unit file + lint/type**

Run: `pytest tests/unit/test_physiology.py -q && ruff check clinosim/modules/physiology/engine.py && mypy clinosim/modules/physiology/engine.py`
Expected: all PASS (no new mypy errors vs the repo baseline for this file).

- [ ] **Step 6: Commit**

```bash
git add clinosim/modules/physiology/engine.py tests/unit/test_physiology.py
git commit -m "$(cat <<'EOF'
feat(physiology): couple BNP to ventricular wall stress (HF specificity)

BNP was driven by cardiac_function alone, so HF and MI were indistinguishable
(audit: HF 324 vs non-HF 226, 1.4x). Add a volume_status x (1-cardiac) coupling
term so volume overload only raises BNP in a failing heart: HF rises sharply,
uncomplicated MI stays moderate, preserved-heart fluid overload stays low.
Deterministic state->lab mapping; only BNP changes.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_0156K1AfNoBCnEEkuC8XsY4U
EOF
)"
```

---

### Task 2: Add BNP assay ceiling to observation re-clamp

**Files:**
- Modify: `clinosim/modules/observation/engine.py` `PHYSIOLOGIC_LIMITS` dict (~line 127–146)
- Test: `tests/unit/test_physiology.py` OR `tests/unit/` observation test — add a clamp test (see Step 1 for exact location guidance)

**Interfaces:**
- Consumes: `apply_realistic_variability(lab_name: str, true_value: float, rng) -> float` (existing) which re-clamps via `PHYSIOLOGIC_LIMITS.get(lab_name)`.
- Produces: `PHYSIOLOGIC_LIMITS["BNP"] = (0.0, 5000.0)` so post-noise BNP is bounded to the assay reporting ceiling.

- [ ] **Step 1: Write the failing test**

Add to `tests/unit/test_physiology.py` (it already imports from observation; if not, add `from clinosim.modules.observation.engine import apply_realistic_variability, PHYSIOLOGIC_LIMITS`). Place near other clamp/observation tests:

```python
    def test_bnp_clamped_to_assay_ceiling(self):
        from clinosim.modules.observation.engine import (
            PHYSIOLOGIC_LIMITS,
            apply_realistic_variability,
        )
        assert PHYSIOLOGIC_LIMITS["BNP"] == (0.0, 5000.0)
        rng = np.random.default_rng(0)
        # A divergent true BNP (severe HF) must be capped at the assay ceiling.
        observed = apply_realistic_variability("BNP", 12000.0, rng)
        assert observed <= 5000.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/unit/test_physiology.py -k bnp_clamped -v`
Expected: FAIL — `PHYSIOLOGIC_LIMITS["BNP"]` raises `KeyError` (no entry yet).

- [ ] **Step 3: Add the BNP limit**

In `clinosim/modules/observation/engine.py`, add to `PHYSIOLOGIC_LIMITS` (after the `CK_MB` line, keeping the existing alignment style):

```python
    "BNP": (0.0, 5000.0),       # pg/mL — assay reporting ceiling
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/unit/test_physiology.py -k bnp_clamped -v`
Expected: PASS.

- [ ] **Step 5: Lint/type**

Run: `ruff check clinosim/modules/observation/engine.py && mypy clinosim/modules/observation/engine.py`
Expected: PASS (no new errors vs baseline).

- [ ] **Step 6: Commit**

```bash
git add clinosim/modules/observation/engine.py tests/unit/test_physiology.py
git commit -m "$(cat <<'EOF'
feat(observation): clamp BNP to 5000 pg/mL assay ceiling

The coupled BNP mapping can diverge for severe HF; bound post-noise BNP to the
assay reporting ceiling via the existing PHYSIOLOGIC_LIMITS re-clamp (same path
as K/CRP tail control).

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_0156K1AfNoBCnEEkuC8XsY4U
EOF
)"
```

---

### Task 3: Generation audit and coefficient tuning

**Files:**
- Modify (only if audit requires): `clinosim/modules/physiology/engine.py` BNP coefficients `(2.5, 6.0)` / base `30.0`
- Modify (if coefficients change): the BNP property test thresholds in `tests/unit/test_physiology.py` must remain satisfied
- No committed audit script — audit runs in `/tmp`, artifacts deleted after.

**Interfaces:**
- Consumes: the CLI generation entrypoint (e.g. `python -m clinosim ...` / `clinosim generate`) producing CIF + FHIR for a catchment population; BNP observations in the FHIR `Observation` NDJSON / CIF lab records.
- Produces: confirmed coefficients meeting the clinical targets; no API change.

- [ ] **Step 1: Generate US + JP catchment populations into /tmp**

Generate ~20k catchment for each country into a `/tmp` directory (mirror the prior audit invocation — check `clinosim --help` / README for the exact generate command and flags; use the same hospital config and `--end`/snapshot as prior audits). Example shape (verify exact flags before running):

```bash
clinosim generate --country US --population 20000 --seed 42 --format fhir --out /tmp/bnp_audit_us
clinosim generate --country JP --population 20000 --seed 42 --format fhir --out /tmp/bnp_audit_jp
```

- [ ] **Step 2: Extract BNP by cohort and compute medians**

Write a throwaway `/tmp` script (Python) that reads the generated CIF/FHIR, joins BNP observations to encounter primary/chronic diagnoses, and reports BNP medians for: (a) HF cohort (primary I50* or chronic I50*), (b) non-HF cohort, (c) normal/non-cardiac cohort (e.g. pneumonia/UTI), (d) MI cohort (I21*), (e) non-HF volume-overload cohort (cirrhosis K74*, AKI N17*). Print median and IQR for each.

- [ ] **Step 3: Check against clinical targets**

Confirm:
- (a) HF median ≥ 5× non-HF median (was 1.4×).
- (b) Normal / non-cardiac median < 100 pg/mL.
- (c) HF exacerbation median in 800–1500 pg/mL.
- (d) Cirrhosis/AKI (preserved-heart overload) median < 100 pg/mL.

- [ ] **Step 4: Tune if any target missed**

If targets are missed, adjust the coefficients in `engine.py` (`(1-cardiac)` weight `2.5`, volume-coupling weight `6.0`, base `30.0`) and regenerate. Guidance: raise the volume-coupling weight to lift HF medians; lower the base/`(1-cardiac)` weight if normal/MI run high. After any change, re-run `pytest tests/unit/test_physiology.py -k bnp -v` and ensure the property thresholds still hold (update test thresholds only if the clinical target band itself is re-decided — discuss with user first).

- [ ] **Step 5: Delete audit artifacts**

```bash
rm -rf /tmp/bnp_audit_us /tmp/bnp_audit_jp /tmp/bnp_audit_*.py
```

- [ ] **Step 6: Commit (only if coefficients changed)**

```bash
git add clinosim/modules/physiology/engine.py tests/unit/test_physiology.py
git commit -m "$(cat <<'EOF'
tune(physiology): finalize BNP coupling coefficients from generation audit

Audit (US+JP 20k): HF median <X> vs non-HF <Y> (<Z>x), normal <100, HF 800-1500,
cirrhosis/AKI <100. Coefficients (<a>, <b>) confirmed.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_0156K1AfNoBCnEEkuC8XsY4U
EOF
)"
```

---

### Task 4: Update docs and verify full suite + determinism

**Files:**
- Modify: `clinosim/modules/physiology/README.md` (BNP mapping line ~130 region; `cardiac_function` / `volume_status` driver rows)
- Modify: `clinosim/modules/physiology/SPEC.md` (BNP line ~254–255)
- Test: full unit/integration + e2e golden

**Interfaces:**
- Consumes: final coefficients from Task 3.
- Produces: docs consistent with shipped mapping.

- [ ] **Step 1: Update SPEC.md BNP line**

In `clinosim/modules/physiology/SPEC.md`, replace the BNP example line (`labs["BNP"] = 30 * math.exp((1 - cardiac) * 4)  # ...`) with the coupled form and an updated comment describing the wall-stress (volume × cardiac dysfunction) coupling and the example outputs (normal ~40, MI ~150, HF mod ~1150). Use the FINAL coefficients from Task 3.

- [ ] **Step 2: Update README.md driver descriptions**

In `clinosim/modules/physiology/README.md`, update the `cardiac_function` and `volume_status` rows / coupling notes so the BNP driver reads "BNP via ventricular wall stress = volume overload × cardiac dysfunction" (not cardiac alone). Keep wording style consistent with the file (Japanese + English technical terms).

- [ ] **Step 3: Run full unit + integration suite**

Run: `pytest -m unit -q && pytest -m integration -q`
Expected: all PASS (prior baseline 319 unit+integration + new BNP tests).

- [ ] **Step 4: Run e2e golden (determinism / invariance)**

Run: `pytest -m e2e -q`
Expected: PASS. If golden files compare exact output and BNP values are included, the only diffs must be BNP observation values; update golden files if the project's convention is to regenerate them for intended value changes (check how prior value-changing PRs — e.g. sodium axis PR #27 — handled golden updates, and follow the same procedure). If a failure looks like CPU-contention flake, rerun the single e2e file to confirm.

- [ ] **Step 5: Commit docs (+ golden if regenerated)**

```bash
git add clinosim/modules/physiology/README.md clinosim/modules/physiology/SPEC.md
git commit -m "$(cat <<'EOF'
docs(physiology): document BNP ventricular wall-stress coupling

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_0156K1AfNoBCnEEkuC8XsY4U
EOF
)"
```

---

## Self-Review

**Spec coverage:**
- Core mapping change → Task 1 ✓
- BNP 5000 clamp → Task 2 ✓
- Invariance / normal ≈39 no-regression → covered by Task 1 normal<100 test + Task 4 e2e golden ✓
- Generation audit (a)–(d) targets + coefficient tuning → Task 3 ✓
- Unit BNP discrimination + coupling-gate + dehydration tests → Task 1 ✓
- Determinism / e2e golden BNP-only diff → Task 4 ✓
- Docs (README/SPEC) → Task 4 ✓
- Out-of-scope (renal confounder) → not implemented, correctly absent ✓

**Placeholder scan:** Task 3 audit command flags are marked "verify exact flags before running" (the prior audit invocation is the source of truth; engine code does not fix the CLI signature) — this is a deliberate verify-step, not a placeholder. Coefficient values in the Task 3 commit message use `<X>`/`<a>` because they are determined BY that task. All code steps contain complete code.

**Type consistency:** `derive_lab_values(state, sex, age)`, `PhysiologicalState(cardiac_function=, volume_status=)`, `apply_realistic_variability(lab_name, true_value, rng)`, `PHYSIOLOGIC_LIMITS` — all match existing signatures verified in the source. No new symbols introduced.
