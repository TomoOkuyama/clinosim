# Septic shock distributive perfusion — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Revision (realism audit):** the perfusion-coupling approach below was implemented and then **rejected** — it regressed sepsis labs to absurd levels (Cr 8.1, BUN 166) and perturbed the master RNG stream (76% demographic churn). Final approach: apply the distributive hypotension at `derive_vital_signs` only (SBP/DBP), leaving `perfusion_status` untouched — golden-safe, labs preserved. See the spec for details. Coefficient `DISTRIBUTIVE_SBP_COEFF = 60`, `DISTRIBUTIVE_THRESHOLD = 0.7`.

**Goal:** Add distributive (vasodilatory) hypotension so severe systemic inflammation lowers SBP/DBP at vitals derivation, producing septic shock coherent with the already-elevated sepsis labs.

**Architecture:** One deterministic term in `derive_vital_signs` (`clinosim/modules/physiology/engine.py`), gated by an inflammation threshold, applied to the displayed SBP/DBP without mutating physiological state. Coefficient tuned by generation audit.

**Tech Stack:** Python 3.11, pytest.

## Global Constraints

- Determinism (AD-16): no new RNG draw — `distributive` is a pure function of existing `inflammation_level`.
- Coefficients are named module-level constants (like `HBA1C_*`), not inline magic numbers.
- Scope: only `apply_coupling_rules` perfusion calc changes. No SBP/HR formula change, no `sepsis.yaml` severity tier, no `R65.x` change.

---

### Task 1: Distributive perfusion coupling (TDD)

**Files:**
- Modify: `clinosim/modules/physiology/engine.py` (`apply_coupling_rules`, + two constants)
- Test: `tests/unit/test_distributive_shock.py`

- [ ] Step 1: Write failing tests — high inflammation lowers perfusion below cardiac-only baseline; at/below threshold unchanged; severe-sepsis-like state drives perfusion < 0.4; determinism.
- [ ] Step 2: Run, verify fail.
- [ ] Step 3: Implement `DISTRIBUTIVE_THRESHOLD=0.7`, `DISTRIBUTIVE_COEFF=4.0`; add `distributive = -max(0.0, inflammation_level - THRESHOLD) * COEFF` into perfusion clamp.
- [ ] Step 4: Run, verify pass; `pytest -m unit`.
- [ ] Step 5: Commit.

### Task 2: Audit-calibrate coefficients

- [ ] Step 1: Generate US (`-p 3000 -s 99`) + JP (`-p 2000 --jp-insurance -s 99`).
- [ ] Step 2: Audit sepsis SBP (median, p10, %<90, %<60); confirm hip-fracture cohort unaffected.
- [ ] Step 3: Tune THRESHOLD/COEFF so sepsis SBP<90 ~15–25%, SBP<60 rare; repeat.
- [ ] Step 4: Pin coefficients with audit comment; update spec note.
- [ ] Step 5: Commit.

### Task 3: Verify + golden

- [ ] Step 1: byte-diff master vs branch — only inflammation>threshold encounters change.
- [ ] Step 2: `pytest -m unit` / `-m integration`.
- [ ] Step 3: `pytest -m e2e` — re-bless golden only if intended change.
- [ ] Step 4: PR with audit before/after numbers.
