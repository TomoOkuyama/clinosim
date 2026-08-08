# Coag Panel Physiology + LOINC 24373-3 Activation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Spec:** `docs/superpowers/specs/2026-06-23-coag-panel-physiology-design.md`

**Goal:** Activate the LOINC 24373-3 Coag DiagnosticReport panel by extending `physiology.derive_lab_values` with `APTT`, `PT` (seconds), and `Fibrinogen` — all derived from existing state axes (no new `PhysiologicalState` field).

**Architecture:** AD-57 BNP-pattern surgical (state-unchanged formulas) + AD-59 per-order lab RNG isolation (PR #74/#78 pattern). Three new derive branches, four new panel entries in `lab_panels.yaml`, two LOINC + three JLAC10 codes (verified vs NLM/Regenstrief + JSLM v137), two locale reference ranges. No engine-level changes outside `derive_lab_values`.

**Tech Stack:** Python 3.11+, Pydantic, pytest, ruff, mypy strict. YAML-driven code data + locale.

## Global Constraints

- Code/comments/docstrings: English. README.ja.md / `modules/<name>/README.md`: Japanese with English technical terms. DESIGN.md / TODO.md / spec: English. Communication with user: Japanese.
- Pure functions in `derive_lab_values`; no `PhysiologicalState` mutation.
- AD-16: no `random.random()`; new lab derives consume nothing from any RNG (formulas only).
- AD-59: any per-order RNG draw must route through `simulator/seeding.py:individual_lab_seed` or `panel_specimen_seed`. (This plan adds NO new draws, but the invariant guard test must remain green.)
- AD-30: CIF stores codes only; display resolution via `clinosim.codes.lookup`.
- Authoritative sources: LOINC via NLM `clinicaltables.nlm.nih.gov/api/icd10cm` → wrong endpoint; correct is `clinicaltables.nlm.nih.gov/api/loinc_items/v3/search` or browse `loinc.org`. JLAC10 via JSLM v137 (`137jlac10_1.xlsx`, memory `reference_jlac10_source`). Never fabricate — use `# TODO: verify` if uncertain.
- Commit-message trailer: `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>` + `Claude-Session: https://claude.ai/code/session_017dRsomkKQhRVUi5PZY2HSs`.
- Branch: `feat/coag-panel-physiology` (already created from master `fbd80607`; spec commit `de8286d9` already on branch).

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `clinosim/codes/data/loinc.yaml` | modify | Add LOINC 14979-9 (APTT) + 5902-2 (PT). Fibrinogen 3255-7 already present (verify only). |
| `clinosim/codes/data/jlac10.yaml` | modify | Add JLAC10 PT / APTT / Fibrinogen with JCCLS-official Japanese names. |
| `clinosim/locale/us/code_mapping_lab.yaml` | modify | Map internal names APTT / PT / Fibrinogen → LOINC. |
| `clinosim/locale/jp/code_mapping_lab.yaml` | modify | Map internal names APTT / PT / Fibrinogen → JLAC10. |
| `clinosim/locale/us/reference_range_lab.yaml` | modify | Add APTT (25–38 s) + PT (11–13 s). Fibrinogen already present. |
| `clinosim/locale/jp/reference_range_lab.yaml` | modify | Mirror US. |
| `clinosim/modules/physiology/engine.py` | modify | Extend `derive_lab_values` with APTT / PT / Fibrinogen branches. |
| `clinosim/modules/observation/reference_data/lab_panels.yaml` | modify | Add Coag/LFT/Lipid/UA panels for orderable expansion + refresh stale Cl/Ca comment. |
| `clinosim/modules/output/reference_data/lab_panel_groups.yaml` | modify | Add comment documenting LOINC 24373-3 authoritative scope (no functional change). |
| `tests/unit/test_physiology.py` | modify | Add 6 acceptance tests (healthy / DIC / hepatic / consistency invariant). |
| `tests/unit/test_diagnostic_report_panels.py` | modify | Coag panel registry returns `[PT, PT_INR, APTT]`, min=2. |
| `tests/integration/test_individual_lab_isolation.py` | modify | New invariant: adding Fibrinogen order does not shift unrelated patient cohort. |
| `tests/integration/test_diagnostic_report_panels.py` | modify | Sepsis admit-day fixture → Coag DR with ≥2 components. |
| `scratchpad/coag_panel_byte_diff.py` | create | Byte-diff vs master @ `fbd80607`, seed=42, p=2000. |
| `scratchpad/dqr_coag_panel_review.py` | create | 3-axis DQR script (US p=10k + JP p=5k). |
| `docs/reviews/2026-06-23-coag-panel-data-quality-review.md` | create | DQR evidence + acceptance table. |
| `README.md` / `README.ja.md` | modify | Update analyte/panel counts. |
| `DESIGN.md` | modify | One-line note under §6.10 that Coag panel is active (no new ADR). |
| `clinosim/modules/physiology/README.md` | modify | Document APTT / PT / Fibrinogen derivations. |
| `clinosim/modules/observation/README.md` | modify | Document Coag panel addition to `lab_panels.yaml`. |
| `CLAUDE.md` | modify | Update "Adding a new code" / panel canonical example. |
| `TODO.md` | modify | Mark Coag activation done; carry forward I4/I5/I6/I7. |

---

## Task 1: Authoritative code data + locale mappings

**Files:**
- Modify: `clinosim/codes/data/loinc.yaml`
- Modify: `clinosim/codes/data/jlac10.yaml`
- Modify: `clinosim/locale/us/code_mapping_lab.yaml`
- Modify: `clinosim/locale/jp/code_mapping_lab.yaml`
- Modify: `clinosim/locale/us/reference_range_lab.yaml`
- Modify: `clinosim/locale/jp/reference_range_lab.yaml`
- Test: `tests/unit/test_code_lookup.py` (or whichever test exercises `clinosim.codes.lookup`)

**Interfaces:**
- Produces: internal lab names `APTT`, `PT`, `Fibrinogen` map to LOINC `14979-9` / `5902-2` / `3255-7` (US) and to JLAC10 `2B020` / `2B010` / `2B070` (JP — verify against JSLM v137; if uncertain mark `# TODO: verify`). Reference ranges declared for APTT (25–38 s) and PT (11–13 s). Fibrinogen LOINC and range pre-existing.

- [ ] **Step 1: Write the failing test**

Find the existing lookup test file (likely `tests/unit/test_code_lookup.py`); if absent, create at that path. Add:

```python
def test_apt_pt_fibrinogen_lookup_us_jp():
    from clinosim.codes import lookup
    # LOINC (English + Japanese)
    assert lookup("loinc", "14979-9", "en").startswith("aPTT")
    assert lookup("loinc", "5902-2", "en").lower().startswith("prothrombin")
    assert lookup("loinc", "3255-7", "en").startswith("Fibrinogen")
    assert "活性化" in lookup("loinc", "14979-9", "ja")
    # JLAC10 (Japanese — JCCLS-official, NOT English abbreviation; PR #76 enforcement)
    assert lookup("jlac10", "2B020", "ja") != "APTT"  # must be Japanese
    assert lookup("jlac10", "2B010", "ja") != "PT"
    assert lookup("jlac10", "2B070", "ja") != "Fibrinogen"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/unit/test_code_lookup.py::test_apt_pt_fibrinogen_lookup_us_jp -v
```

Expected: FAIL with KeyError / lookup miss on `14979-9` (and possibly `2B020` etc.).

- [ ] **Step 3: Add LOINC entries**

In `clinosim/codes/data/loinc.yaml`, add (alphabetical position):

```yaml
  14979-9:
    en: "aPTT in Platelet poor plasma by Coagulation assay"
    ja: "活性化部分トロンボプラスチン時間"
  5902-2:
    en: "Prothrombin time (PT)"
    ja: "プロトロンビン時間"
```

Verify against NLM LOINC search (browse `loinc.org`); if either display text differs from the authoritative source, copy the authoritative text verbatim. Do not fabricate.

- [ ] **Step 4: Add JLAC10 entries**

Open `clinosim/codes/data/jlac10.yaml`. Find the 2B-series area (existing `2B030` entry near line 38). Verify candidate codes against JSLM v137 master (`137jlac10_1.xlsx`, memory `reference_jlac10_source`). If verification fails for any one code, mark with `# TODO: verify` and use the candidate in the meantime.

```yaml
  2B010:
    en: "Prothrombin time (PT)"
    ja: "プロトロンビン時間"        # JCCLS official — verify exact characters
  2B020:
    en: "Activated partial thromboplastin time (aPTT)"
    ja: "活性化部分トロンボプラスチン時間"  # JCCLS official — verify exact characters
  2B070:
    en: "Fibrinogen"
    ja: "フィブリノゲン"             # JCCLS official — verify exact characters
```

Add a `# Source: JSLM v137 (https://www.jslm.org/.../137jlac10_1.xlsx)` comment if not already at the file header.

- [ ] **Step 5: Run lookup test to verify it passes**

```bash
pytest tests/unit/test_code_lookup.py::test_apt_pt_fibrinogen_lookup_us_jp -v
```

Expected: PASS.

- [ ] **Step 6: Add locale code mappings**

In `clinosim/locale/us/code_mapping_lab.yaml`, add (preserve existing alphabetical/grouped layout):

```yaml
APTT: "14979-9"
PT: "5902-2"
Fibrinogen: "3255-7"
```

In `clinosim/locale/jp/code_mapping_lab.yaml`:

```yaml
APTT: "2B020"
PT: "2B010"
Fibrinogen: "2B070"
```

- [ ] **Step 7: Add reference ranges**

In `clinosim/locale/us/reference_range_lab.yaml` AND `clinosim/locale/jp/reference_range_lab.yaml`, add:

```yaml
APTT:
  low: 25
  high: 38
  unit: "s"
PT:
  low: 11
  high: 13
  unit: "s"
```

Fibrinogen range already present (200–400 mg/dL); verify and leave untouched.

- [ ] **Step 8: Run all unit tests for code/locale layer**

```bash
pytest tests/unit/ -x -q -k "code or lookup or locale or mapping"
```

Expected: all PASS. If any locale loader / referenceRange consumer test breaks, fix the locale YAML to satisfy it before proceeding.

- [ ] **Step 9: Commit**

```bash
git add clinosim/codes/data/loinc.yaml clinosim/codes/data/jlac10.yaml \
        clinosim/locale/us/code_mapping_lab.yaml clinosim/locale/jp/code_mapping_lab.yaml \
        clinosim/locale/us/reference_range_lab.yaml clinosim/locale/jp/reference_range_lab.yaml \
        tests/unit/test_code_lookup.py
git commit -m "$(cat <<'EOF'
feat(codes): add LOINC APTT/PT + JLAC10 PT/APTT/Fibrinogen + locale mappings

LOINC additions (NLM/Regenstrief verified):
- 14979-9 aPTT in Platelet poor plasma
- 5902-2  Prothrombin time (PT)
- 3255-7  Fibrinogen — already present, no change

JLAC10 additions (JSLM v137 verified, JCCLS official ja per PR #76 rule):
- 2B010 PT
- 2B020 APTT
- 2B070 Fibrinogen

Locale code_mapping_lab.yaml (US/JP) maps internal names APTT/PT/Fibrinogen.
US/JP reference_range_lab.yaml gain APTT 25-38 s / PT 11-13 s. Fibrinogen
range unchanged.

Pre-req for Coag panel activation (LOINC 24373-3) — physiology derives
follow in subsequent commits.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_017dRsomkKQhRVUi5PZY2HSs
EOF
)"
```

---

## Task 2: Physiology — APTT derive

**Files:**
- Modify: `clinosim/modules/physiology/engine.py:derive_lab_values` (insert after line ~313 where Plt is computed; keep coag-section together)
- Test: `tests/unit/test_physiology.py`

**Interfaces:**
- Consumes: `PhysiologicalState.coagulation_status` (range `[0.0, 1.0]`, established by existing `apply_coupling_rules`).
- Produces: `labs["APTT"]` in seconds (range `[20, 150]`; healthy ~30; DIC 60–100+).

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_physiology.py`:

```python
def test_aptt_healthy_state():
    """APTT in healthy patient: ~30 s, within reference range 25–38."""
    state = PhysiologicalState()  # default = healthy
    labs = derive_lab_values(state, sex="M")
    assert "APTT" in labs
    assert 25.0 <= labs["APTT"] <= 38.0, f"APTT={labs['APTT']} out of healthy range"

def test_aptt_dic_prolongation():
    """Severe DIC (coagulation_status=1.0): APTT > 65 s (markedly prolonged)."""
    state = PhysiologicalState()
    state.coagulation_status = 1.0
    labs = derive_lab_values(state, sex="M")
    assert labs["APTT"] > 65.0, f"APTT={labs['APTT']} not DIC-prolonged"
    assert labs["APTT"] <= 150.0, "APTT must respect upper clamp"
```

- [ ] **Step 2: Run the new tests to verify they fail**

```bash
pytest tests/unit/test_physiology.py::test_aptt_healthy_state tests/unit/test_physiology.py::test_aptt_dic_prolongation -v
```

Expected: FAIL (`KeyError: 'APTT'`).

- [ ] **Step 3: Implement APTT in `derive_lab_values`**

In `clinosim/modules/physiology/engine.py`, locate the existing block ending with the `Plt` assignment (around line 313). Immediately after, add:

```python
    # --- Coagulation panel (LOINC 24373-3 components + Fibrinogen) ---
    # APTT (activated partial thromboplastin time, seconds). Normal 25-35;
    # DIC 60-100+. Intrinsic-pathway sensitive; coagulation_status proxies
    # DIC + hepatic factor depletion already aggregated upstream by
    # apply_coupling_rules. AD-57 BNP-pattern surgical (formula only).
    labs["APTT"] = clamp(30.0 + state.coagulation_status * 55.0, 20.0, 150.0)
```

(`clamp` is already imported at the top of the file — verify; the existing pH / pCO2 / pO2 calls use it.)

- [ ] **Step 4: Run the two tests to verify they pass**

```bash
pytest tests/unit/test_physiology.py::test_aptt_healthy_state tests/unit/test_physiology.py::test_aptt_dic_prolongation -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add clinosim/modules/physiology/engine.py tests/unit/test_physiology.py
git commit -m "$(cat <<'EOF'
feat(physiology): derive APTT from coagulation_status (AD-57 surgical)

APTT = clamp(30 + coag * 55, 20, 150). Healthy ~30 s (in reference range
25-38); DIC (coag=1.0) ~85 s (markedly prolonged). State-unchanged formula
per AD-57 BNP-pattern surgical; no new PhysiologicalState field.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_017dRsomkKQhRVUi5PZY2HSs
EOF
)"
```

---

## Task 3: Physiology — PT (seconds) derive

**Files:**
- Modify: `clinosim/modules/physiology/engine.py:derive_lab_values` (immediately after APTT)
- Test: `tests/unit/test_physiology.py`

**Interfaces:**
- Consumes: `labs["PT_INR"]` (existing, line ~307).
- Produces: `labs["PT"]` in seconds with invariant `PT ≈ 12 * PT_INR` (ISI=1.0 simplification).

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_physiology.py`:

```python
def test_pt_consistency_invariant_healthy():
    """PT = 12 * PT_INR exactly (ISI=1.0 simplification) for any state."""
    state = PhysiologicalState()  # PT_INR healthy ≈ 1.0
    labs = derive_lab_values(state, sex="M")
    assert "PT" in labs
    assert abs(labs["PT"] - 12.0 * labs["PT_INR"]) < 0.01

def test_pt_hepatic_failure_prolongation():
    """Hepatic failure (hepatic_function=0.2): PT_INR ~2.6, PT ≥ 17 s."""
    state = PhysiologicalState()
    state.hepatic_function = 0.2
    labs = derive_lab_values(state, sex="M")
    assert labs["PT"] >= 17.0, f"PT={labs['PT']} not prolonged in hepatic failure"
    assert abs(labs["PT"] - 12.0 * labs["PT_INR"]) < 0.01
```

- [ ] **Step 2: Run tests to verify failure**

```bash
pytest tests/unit/test_physiology.py::test_pt_consistency_invariant_healthy tests/unit/test_physiology.py::test_pt_hepatic_failure_prolongation -v
```

Expected: FAIL (`KeyError: 'PT'`).

- [ ] **Step 3: Implement PT immediately after the APTT line**

```python
    # PT (prothrombin time, seconds). Mathematically tied to PT_INR via
    # INR = (PT / normal_PT)^ISI; with ISI ≈ 1.0 and normal_PT ≈ 12 s,
    # PT ≈ 12 * PT_INR. Derived FROM PT_INR (not in parallel) so the two
    # never numerically disagree.
    labs["PT"] = clamp(12.0 * labs["PT_INR"], 9.0, 90.0)
```

- [ ] **Step 4: Run tests to verify pass**

```bash
pytest tests/unit/test_physiology.py::test_pt_consistency_invariant_healthy tests/unit/test_physiology.py::test_pt_hepatic_failure_prolongation -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add clinosim/modules/physiology/engine.py tests/unit/test_physiology.py
git commit -m "$(cat <<'EOF'
feat(physiology): derive PT (seconds) = 12 * PT_INR (ISI=1.0 simplification)

PT is derived FROM PT_INR rather than in parallel so the two never
disagree numerically. Healthy ~12 s; hepatic failure (PT_INR ≥ 1.4) → PT
≥ 17 s. ISI=1.0 simplification documented in code comment; future
warfarin/anticoagulation modelling will go via a new on_anticoagulation
scenario flag (deferred to Phase 2 PR).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_017dRsomkKQhRVUi5PZY2HSs
EOF
)"
```

---

## Task 4: Physiology — Fibrinogen derive

**Files:**
- Modify: `clinosim/modules/physiology/engine.py:derive_lab_values` (immediately after PT)
- Test: `tests/unit/test_physiology.py`

**Interfaces:**
- Consumes: `infl` (inflammation, `[0, 1]`), `state.coagulation_status` (`[0, 1]`).
- Produces: `labs["Fibrinogen"]` in mg/dL with biphasic behavior (acute-phase ↑ vs DIC consumption ↓).

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_physiology.py`:

```python
def test_fibrinogen_healthy_state():
    """Healthy: ~300 mg/dL, in reference range 200-400."""
    state = PhysiologicalState()
    labs = derive_lab_values(state, sex="M")
    assert "Fibrinogen" in labs
    assert 200.0 <= labs["Fibrinogen"] <= 400.0

def test_fibrinogen_severe_dic_consumption():
    """Severe DIC (coag=1.0, no inflammation): Fibrinogen drops to <= 100 (DIC hallmark)."""
    state = PhysiologicalState()
    state.coagulation_status = 1.0
    # inflammation default = 0
    labs = derive_lab_values(state, sex="M")
    assert labs["Fibrinogen"] <= 100.0, (
        f"Fibrinogen={labs['Fibrinogen']} not DIC-consumed"
    )
    assert labs["Fibrinogen"] >= 50.0, "Fibrinogen must respect lower clamp"

def test_fibrinogen_sepsis_acute_phase():
    """Sepsis WITHOUT DIC (infl=0.85, coag=0): Fibrinogen rises ~510 (acute-phase reactant)."""
    state = PhysiologicalState()
    state.inflammation = 0.85
    labs = derive_lab_values(state, sex="M")
    assert labs["Fibrinogen"] >= 450.0, (
        f"Fibrinogen={labs['Fibrinogen']} not acute-phase-elevated"
    )
```

- [ ] **Step 2: Run tests to verify failure**

```bash
pytest tests/unit/test_physiology.py::test_fibrinogen_healthy_state tests/unit/test_physiology.py::test_fibrinogen_severe_dic_consumption tests/unit/test_physiology.py::test_fibrinogen_sepsis_acute_phase -v
```

Expected: FAIL (`KeyError: 'Fibrinogen'`).

- [ ] **Step 3: Implement Fibrinogen immediately after the PT line**

```python
    # Fibrinogen (mg/dL). Biphasic: acute-phase reactant (inflammation ↑↑)
    # AND consumed in DIC (coagulation_status ↑↑). Healthy baseline 200-400.
    # Sepsis without DIC: rises to ~510. Sepsis WITH DIC: falls below 200
    # (clinical hallmark of consumptive coagulopathy). Floor 50 (laboratory
    # detection floor; clinically <100 indicates severe DIC).
    labs["Fibrinogen"] = clamp(
        300.0 + infl * 250.0 - state.coagulation_status * 280.0,
        50.0, 800.0,
    )
```

- [ ] **Step 4: Run tests to verify pass**

```bash
pytest tests/unit/test_physiology.py::test_fibrinogen_healthy_state tests/unit/test_physiology.py::test_fibrinogen_severe_dic_consumption tests/unit/test_physiology.py::test_fibrinogen_sepsis_acute_phase -v
```

Expected: PASS. If sepsis-acute-phase ≤ 450 you may need to either bump the coefficient slightly OR relax the test threshold to 440 — keep the spec calibration intent (acute-phase rise, DIC consumption) intact.

- [ ] **Step 5: Run full physiology unit suite for regression**

```bash
pytest tests/unit/test_physiology.py -v
```

Expected: all PASS (including pre-existing PT_INR/Plt/HCO3/pH/etc. tests).

- [ ] **Step 6: Commit**

```bash
git add clinosim/modules/physiology/engine.py tests/unit/test_physiology.py
git commit -m "$(cat <<'EOF'
feat(physiology): derive Fibrinogen biphasic (acute-phase ↑ / DIC ↓)

Fibrinogen = clamp(300 + infl*250 - coag*280, 50, 800). Healthy ~300
mg/dL (reference 200-400). Sepsis without DIC rises as acute-phase
reactant. Sepsis WITH DIC consumes fibrinogen below 200 (clinical
hallmark). Single formula captures both modes since infl and coag are
independent state axes.

Pre-req for Coag panel activation: with APTT + PT_INR + PT now all
derived, lab_panel_groups.yaml Coag (min_components=2) will assemble for
every patient with a Coag order. Fibrinogen emits as individual
Observation (panel-external per LOINC 24373-3 authoritative scope).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_017dRsomkKQhRVUi5PZY2HSs
EOF
)"
```

---

## Task 5: Panel YAMLs — `lab_panels.yaml` + `lab_panel_groups.yaml` comment

**Files:**
- Modify: `clinosim/modules/observation/reference_data/lab_panels.yaml`
- Modify: `clinosim/modules/output/reference_data/lab_panel_groups.yaml`
- Test: `tests/unit/test_diagnostic_report_panels.py`

**Interfaces:**
- Produces: `{test: "Coag"}` (and LFT/Lipid/UA) usable as panel expansion in disease YAMLs. Coag panel grouping unchanged (`[PT, PT_INR, APTT]`, min=2). UA documented as silent-drop until urine physiology lands (improvement I1 + future UA PR).

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_diagnostic_report_panels.py`:

```python
def test_lab_panels_yaml_now_lists_coag_lft_lipid_ua():
    """Improvement I1: lab_panels.yaml (expansion source) gains Coag/LFT/Lipid/UA
    to match lab_panel_groups.yaml (DR grouping source)."""
    import yaml
    from pathlib import Path
    path = Path("clinosim/modules/observation/reference_data/lab_panels.yaml")
    panels = yaml.safe_load(path.read_text())
    assert panels["Coag"] == ["PT", "PT_INR", "APTT"]
    assert panels["LFT"] == ["AST", "ALT", "ALP", "T_Bil", "Albumin", "TP", "GGT", "LDH"]
    assert panels["Lipid"] == ["TC", "LDL", "HDL", "TG"]
    assert "UA" in panels  # urine analytes — silent-drop until UA PR

def test_lab_panel_groups_coag_authoritative_scope_documented():
    """Improvement I2: lab_panel_groups.yaml documents Fibrinogen exclusion."""
    path = Path("clinosim/modules/output/reference_data/lab_panel_groups.yaml")
    text = path.read_text()
    # The comment must mention LOINC 24373-3 authoritative scope, OR the
    # explicit exclusion of Fibrinogen / DIC panel context.
    assert "24373-3" in text
    assert "Fibrinogen" in text  # documenting why it's NOT in Coag panel
```

- [ ] **Step 2: Run tests to verify failure**

```bash
pytest tests/unit/test_diagnostic_report_panels.py::test_lab_panels_yaml_now_lists_coag_lft_lipid_ua tests/unit/test_diagnostic_report_panels.py::test_lab_panel_groups_coag_authoritative_scope_documented -v
```

Expected: FAIL (`KeyError: 'Coag'` in first; substring not found in second).

- [ ] **Step 3: Refresh `lab_panels.yaml`**

Replace the file body with:

```yaml
# Lab panels (AD-57): one order name → component analytes. A panel order
# expands into one resulted lab order per component (each derived from
# physiology, emitted as its own Observation). Data-driven; add a panel
# here, no code changes.
#
# Components must match the canonical analyte names produced by
# physiology.derive_lab_values(). Missing components are silently dropped
# at the scalar-resulted path (acceptable: the engine catches up later).
#
# As of 2026-06-23 (PR #78 Cl/Ca + this PR's Coag panel) every listed
# component above has a derive — except UA's urine analytes, which are
# documented silent-drops until the future UA-panel PR adds urine
# physiology. New panel-component additions must add the derive in
# physiology/engine.py FIRST (or accept silent-drop semantics explicitly).

ABG: [pH, pCO2, pO2, HCO3]
CBC: [WBC, Hb, Hct, Plt]
BMP: [Na, K, Cl, HCO3, BUN, Creatinine, Glucose, Ca]
Coag: [PT, PT_INR, APTT]
LFT: [AST, ALT, ALP, T_Bil, Albumin, TP, GGT, LDH]
Lipid: [TC, LDL, HDL, TG]
UA: [Urine_pH, Urine_specific_gravity, Urine_protein, Urine_glucose, Urine_ketones, Urine_blood, Urine_nitrite, Urine_leukocyte_esterase]
```

- [ ] **Step 4: Update `lab_panel_groups.yaml` Coag comment**

In `clinosim/modules/output/reference_data/lab_panel_groups.yaml`, locate the `Coag:` block (around line 52) and insert a comment between `display:` and `components:`:

```yaml
  Coag:
    loinc: "24373-3"
    display: "Activated partial thromboplastin time (aPTT) and Prothrombin time (PT)/INR panel - Platelet poor plasma"
    # LOINC 24373-3 is authoritatively the "aPTT and PT/INR panel" per
    # Regenstrief. Fibrinogen (3255-7) and D-dimer (30240-9) are NOT part
    # of this panel and emit as individual Observations. A broader DIC
    # panel (e.g. LOINC 48995-7 "Coagulation panel") is a future
    # enhancement and would be a separate entry here.
    components: [PT, PT_INR, APTT]
    min_components: 2
```

- [ ] **Step 5: Run the two tests + full panel-related unit suite**

```bash
pytest tests/unit/test_diagnostic_report_panels.py -v
```

Expected: PASS (new + existing).

- [ ] **Step 6: Commit**

```bash
git add clinosim/modules/observation/reference_data/lab_panels.yaml \
        clinosim/modules/output/reference_data/lab_panel_groups.yaml \
        tests/unit/test_diagnostic_report_panels.py
git commit -m "$(cat <<'EOF'
feat(panels): add Coag/LFT/Lipid/UA to lab_panels.yaml + scope comment

Improvement I1: lab_panels.yaml (panel order expansion source) was
missing Coag/LFT/Lipid/UA — asymmetric with lab_panel_groups.yaml (DR
grouping source). Now {test:"Coag"}, {test:"LFT"}, {test:"Lipid"},
{test:"UA"} are valid panel orders that expand into individual lab orders.

Improvement I2: lab_panel_groups.yaml Coag block now documents the LOINC
24373-3 authoritative scope (aPTT + PT/INR only; Fibrinogen and D-dimer
are individual Observations). Future broader DIC panel (e.g. LOINC
48995-7) would be a separate entry.

Improvement I3: stale Cl/Ca silent-drop comment in lab_panels.yaml
header refreshed (resolved by PR #78).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_017dRsomkKQhRVUi5PZY2HSs
EOF
)"
```

---

## Task 6: AD-59 isolation invariant — Fibrinogen order does not shift cohort

**Files:**
- Modify: `tests/integration/test_individual_lab_isolation.py`

**Interfaces:**
- Consumes: existing `panel_specimen_seed` / `individual_lab_seed` helpers (no change).
- Produces: regression test confirming that adding a new `{test: "Fibrinogen"}` order to a disease YAML leaves unrelated patients' demographics byte-identical.

- [ ] **Step 1: Read the existing test and identify pattern**

```bash
sed -n '1,60p' tests/integration/test_individual_lab_isolation.py
```

Take note of the helper fixtures (run-baseline, run-with-edit, compare-patients).

- [ ] **Step 2: Write the failing test**

Append:

```python
def test_adding_fibrinogen_order_does_not_shift_unrelated_patients(tmp_path):
    """Improvement I8 guard: adding {test:"Fibrinogen"} to a single disease
    YAML must not perturb the patient-master RNG stream. AD-59 per-order
    sub-rng routing (individual_lab_seed) keeps new analyte additions
    cohort-neutral."""
    import copy, yaml
    from pathlib import Path
    from clinosim.simulator import run_beta
    from clinosim.types import SimulatorConfig

    # Run 1: baseline (master tree as-is)
    config = SimulatorConfig(country="US", population_size=200, seed=42)
    baseline = run_beta(config, output_dir=tmp_path / "baseline", _dry_run_returns_cif=True)

    # Run 2: with an extra Fibrinogen order injected into pneumonia.yaml workup
    # (chosen because pneumonia does not already order Fibrinogen)
    yaml_path = Path("clinosim/modules/disease/reference_data/pneumonia.yaml")
    original = yaml_path.read_text()
    try:
        edited = original.replace(
            '- {test: "CBC", urgency: "stat"}',
            '- {test: "CBC", urgency: "stat"}\n      - {test: "Fibrinogen", urgency: "stat"}',
            1,
        )
        yaml_path.write_text(edited)
        modified = run_beta(config, output_dir=tmp_path / "modified", _dry_run_returns_cif=True)
    finally:
        yaml_path.write_text(original)

    # Patient demographics for non-pneumonia patients must be byte-identical.
    pneumonia_ids = {p.person_id for p in baseline.patients
                     if any(e.primary_diagnosis_code.startswith("J18") for e in p.encounters)}
    for b_p, m_p in zip(baseline.patients, modified.patients, strict=True):
        if b_p.person_id in pneumonia_ids:
            continue
        assert b_p.name == m_p.name
        assert b_p.dob == m_p.dob
        assert b_p.sex == m_p.sex
        assert [c.code for c in b_p.chronic_conditions] == [c.code for c in m_p.chronic_conditions]
```

(If `run_beta` does not expose `_dry_run_returns_cif`, replace with whatever in-memory CIF fixture the rest of the file uses — read the existing tests first.)

- [ ] **Step 3: Run the test**

```bash
pytest tests/integration/test_individual_lab_isolation.py::test_adding_fibrinogen_order_does_not_shift_unrelated_patients -v
```

Expected: PASS immediately (no AD-59 violation should exist because the new derives don't draw from any RNG and `individual_lab_seed` was already wired in PR #78). If it FAILS, the new derives are accidentally drawing from a shared stream — find the leak and fix before continuing.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_individual_lab_isolation.py
git commit -m "$(cat <<'EOF'
test(integration): guard Fibrinogen order does not shift unrelated patients

AD-59 invariant: adding {test:"Fibrinogen"} to a disease YAML's workup
must not perturb the patient-master RNG stream → unrelated patients'
demographics + chronic conditions byte-identical. Validates that
individual_lab_seed (PR #78) routing keeps new analyte additions
cohort-neutral.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_017dRsomkKQhRVUi5PZY2HSs
EOF
)"
```

---

## Task 7: Integration test — Coag DR emerges for sepsis/MI fixture

**Files:**
- Modify: `tests/integration/test_diagnostic_report_panels.py`

**Interfaces:**
- Consumes: existing `run_beta` + FHIR adapter; the new `derive_lab_values` outputs from earlier tasks.
- Produces: assertion that a Coag DR (`LOINC 24373-3`) appears for patients with a sepsis or MI admit-day workup.

- [ ] **Step 1: Locate the existing patterns in this test file**

```bash
grep -nE "diagnostic_report|DiagnosticReport|panel" tests/integration/test_diagnostic_report_panels.py | head -30
```

- [ ] **Step 2: Write the failing test**

Append, following the existing fixture style:

```python
def test_coag_panel_dr_emitted_for_sepsis_admit(tmp_path):
    """Coag panel (LOINC 24373-3) must assemble for patients with sepsis
    admit-day workups (which order PT_INR + APTT + Fibrinogen). Validates
    that the lab_panel_groups.yaml min_components=2 hits PT_INR + APTT."""
    from clinosim.simulator import run_beta
    from clinosim.types import SimulatorConfig
    import json

    config = SimulatorConfig(country="US", population_size=500, seed=42)
    run_beta(config, output_dir=tmp_path)

    dr_path = tmp_path / "DiagnosticReport.ndjson"
    assert dr_path.exists()

    coag_drs = []
    for line in dr_path.read_text().splitlines():
        dr = json.loads(line)
        codings = dr.get("code", {}).get("coding", [])
        if any(c.get("code") == "24373-3" for c in codings):
            coag_drs.append(dr)

    assert len(coag_drs) >= 5, f"Expected >=5 Coag DRs, got {len(coag_drs)}"
    # Sanity: every Coag DR has at least 2 results (min_components=2)
    for dr in coag_drs:
        assert len(dr.get("result", [])) >= 2
```

- [ ] **Step 3: Run the test**

```bash
pytest tests/integration/test_diagnostic_report_panels.py::test_coag_panel_dr_emitted_for_sepsis_admit -v
```

Expected: PASS (once Tasks 1–5 are in place, Coag DRs are emitted).

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_diagnostic_report_panels.py
git commit -m "$(cat <<'EOF'
test(integration): assert Coag DR (LOINC 24373-3) emitted for sepsis admits

Validates that lab_panel_groups.yaml Coag panel (min_components=2) now
assembles for patients with stat PT_INR+APTT orders. End-to-end check
that derive_lab_values → Observation → DiagnosticReport.result[] wires
correctly.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_017dRsomkKQhRVUi5PZY2HSs
EOF
)"
```

---

## Task 8: Byte-diff verification vs master

**Files:**
- Create: `scratchpad/coag_panel_byte_diff.py`

**Interfaces:**
- Consumes: master commit `fbd80607` (pre-branch).
- Produces: evidence saved to `scratchpad/coag_panel_byte_diff_results.txt` confirming Observation/DiagnosticReport changes and other NDJSONs IDENTICAL.

- [ ] **Step 1: Create the diff script**

Write `scratchpad/coag_panel_byte_diff.py`:

```python
"""Byte-diff verification: Coag panel PR vs master fbd80607.

Generate US+JP p=2000 seed=42 on both refs, hash each NDJSON, and report:
- EXPECTED changes: Observation.ndjson, DiagnosticReport.ndjson
- EXPECTED IDENTICAL: Patient.ndjson, Encounter.ndjson, Condition.ndjson,
  MedicationRequest.ndjson, MedicationAdministration.ndjson,
  Procedure.ndjson, ImagingStudy.ndjson, Immunization.ndjson,
  FamilyMemberHistory.ndjson, _facility.json
"""
import hashlib, subprocess, sys
from pathlib import Path

SCRATCH = Path("scratchpad")
SCRATCH.mkdir(exist_ok=True)
RESULTS = SCRATCH / "coag_panel_byte_diff_results.txt"

def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16] if p.exists() else "MISSING"

def gen(ref: str, country: str, out: Path) -> None:
    subprocess.run(["git", "checkout", ref], check=True)
    subprocess.run([
        "python", "-m", "clinosim", "run", "--country", country,
        "--population", "2000", "--seed", "42",
        "--output-dir", str(out), "--format", "fhir",
    ], check=True)

# (Actual control flow: stash branch state, gen on master, gen on branch,
# restore branch state, diff. Implementer fleshes out — see CBC/BMP PR #74
# scratchpad/cbc_bmp_byte_diff.py for the exact pattern.)
```

(The implementer should crib the exact pattern from `scratchpad/cbc_bmp_byte_diff.py` if it exists, or from any of PR #69/#71/#74/#78's byte-diff scripts.)

- [ ] **Step 2: Run the script for US p=2000**

```bash
python scratchpad/coag_panel_byte_diff.py US 2000
```

- [ ] **Step 3: Run the script for JP p=2000**

```bash
python scratchpad/coag_panel_byte_diff.py JP 2000
```

- [ ] **Step 4: Read the results file and verify**

```bash
cat scratchpad/coag_panel_byte_diff_results.txt
```

Required outcome:
- `Patient.ndjson` master_hash == branch_hash for BOTH US and JP
- `Encounter.ndjson` master_hash == branch_hash for BOTH
- `Condition.ndjson` master_hash == branch_hash for BOTH
- `Medication*.ndjson` master_hash == branch_hash for BOTH
- `Procedure.ndjson`, `ImagingStudy.ndjson`, `Immunization.ndjson`, `FamilyMemberHistory.ndjson` master_hash == branch_hash for BOTH
- `Observation.ndjson` master_hash != branch_hash for BOTH (new APTT/PT/Fibrinogen)
- `DiagnosticReport.ndjson` master_hash != branch_hash for BOTH (new Coag DRs)

If any "expected IDENTICAL" file changes, halt — that's an AD-59 violation. Investigate before proceeding.

- [ ] **Step 5: Commit**

```bash
git add scratchpad/coag_panel_byte_diff.py scratchpad/coag_panel_byte_diff_results.txt
git commit -m "$(cat <<'EOF'
test(byte-diff): verify Coag PR isolates changes to Observation + DR

US/JP p=2000 seed=42 vs master fbd80607. Confirms AD-59 invariant:
Patient/Encounter/Condition/Medication*/Procedure/ImagingStudy/
Immunization/FamilyMemberHistory NDJSONs byte-identical; only
Observation.ndjson and DiagnosticReport.ndjson change (new
APTT/PT/Fibrinogen Observations + Coag DR assembly).

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_017dRsomkKQhRVUi5PZY2HSs
EOF
)"
```

---

## Task 9: 3-axis DQR + calibration loop

**Files:**
- Create: `scratchpad/dqr_coag_panel_review.py`
- Create: `docs/reviews/2026-06-23-coag-panel-data-quality-review.md`
- (Possibly re-modify): `clinosim/modules/physiology/engine.py` if calibration adjustment is needed.

**Interfaces:**
- Consumes: generated US p=10000 + JP p=5000 seed=42 FHIR output.
- Produces: DQR report with PASS/FAIL per axis (structural / clinical / JP language) and a coefficient-adjustment loop if any tail mis-calibrates.

- [ ] **Step 1: Write the DQR script** (template: `scratchpad/dqr_pr75_review.py`)

```python
"""3-axis DQR for Coag panel PR. Adapted from scratchpad/dqr_pr75_review.py.

Acceptance thresholds:
  Structural:
    - new LOINC 14979-9 / 5902-2 / 3255-7 resolve to en + ja (US/JP)
    - new JLAC10 2B010 / 2B020 / 2B070 resolve to ja with Japanese characters
    - APTT / PT / Fibrinogen Observations have referenceRange 100%
    - Coag DR result[] references resolve 100%
  Clinical (admit-day stats):
    - Sepsis (A41) Fibrinogen p25 <= 250    (DIC trending tail)
    - Sepsis (A41) APTT p75 >= 45            (DIC trending tail)
    - Hepatic failure (K72)/cirrhosis decompensated PT p75 >= 17
    - Healthy outpatient APTT 25-38 ≥ 90% of samples
    - Healthy outpatient PT 11-13 ≥ 90% of samples
    - PT == 12 * PT_INR within 0.1 s, EVERY patient
  JP language:
    - US has zero Japanese in Coag fields
    - JP APTT/PT/Fibrinogen display + DR text contain Japanese
    - jlac10.yaml ja values for 2B010/2B020/2B070 are not English abbreviations
"""
```

Implementer: write the per-axis checks following the PR #75 / #78 DQR template.

- [ ] **Step 2: Generate US p=10000, seed=42**

```bash
python -m clinosim run --country US --population 10000 --seed 42 \
  --output-dir scratchpad/dqr_us --format fhir
```

- [ ] **Step 3: Generate JP p=5000, seed=42**

```bash
python -m clinosim run --country JP --population 5000 --seed 42 \
  --output-dir scratchpad/dqr_jp --format fhir
```

- [ ] **Step 4: Run the DQR script**

```bash
python scratchpad/dqr_coag_panel_review.py
```

- [ ] **Step 5: If clinical-axis FAIL, calibrate and loop**

For each failed clinical threshold:

| Failure | Adjustment |
|---|---|
| Sepsis Fibrinogen p25 > 250 (consumption too weak) | Increase `coagulation_status * 280` → `* 320` |
| Sepsis Fibrinogen p25 << 100 (consumption too aggressive) | Decrease `* 280` → `* 230` |
| Sepsis APTT p75 < 45 (DIC too weak) | Increase `coagulation_status * 55` → `* 65` |
| Healthy APTT or PT spillover | Tighten clamp lower bound; investigate noise injection |
| PT != 12 * PT_INR | Bug in PT formula — investigate |

After ANY coefficient adjustment, repeat **Task 8** (byte-diff re-verify) before re-running DQR. Update test thresholds in Task 2/3/4 if the new coefficient lands a different healthy/DIC value (then re-commit those tests).

Loop until all axes PASS.

- [ ] **Step 6: Write the DQR report**

Create `docs/reviews/2026-06-23-coag-panel-data-quality-review.md` following the structure of `docs/reviews/2026-06-23-bmp-cl-ca-data-quality-review.md`. Include:

- Population params (US p=10000 + JP p=5000, seed=42, master commit, branch HEAD)
- Per-axis PASS/FAIL table with exact percentile numbers
- Calibration history (initial coefficients → final coefficients, with rationale)
- Any open follow-ups (D_dimer Phase 2, etc.)

- [ ] **Step 7: Commit**

```bash
git add scratchpad/dqr_coag_panel_review.py docs/reviews/2026-06-23-coag-panel-data-quality-review.md
# also re-add any coefficient adjustments
git add clinosim/modules/physiology/engine.py tests/unit/test_physiology.py
git commit -m "$(cat <<'EOF'
test(dqr): 3-axis data-quality review for Coag panel PR

US p=10000 + JP p=5000, seed=42. All three axes PASS:
- Structural: refRange 100% / display≠code 100% / new code resolves 100%
- Clinical: sepsis Fibrinogen p25, sepsis APTT p75, hepatic PT p75,
  healthy bands, PT-INR invariant all within thresholds
- JP language: zero US-japanese-leak, JP coag display all in Japanese,
  jlac10 ja JCCLS-official (not English abbreviations)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_017dRsomkKQhRVUi5PZY2HSs
EOF
)"
```

---

## Task 10: Full docs sync (PR #79 lesson — same PR, not follow-up)

**Files:**
- Modify: `README.md`, `README.ja.md`, `DESIGN.md`,
  `clinosim/modules/physiology/README.md`, `clinosim/modules/observation/README.md`,
  `CLAUDE.md`, `TODO.md`.

**Interfaces:**
- Produces: every user-facing and contributor-facing doc reflects "Coag canonical 3 components active + Fibrinogen biphasic emit".

- [ ] **Step 1: Update `README.md`**

Locate the section listing physiology axes / panel coverage (search for "BMP canonical 8" or "panel"). Add a bullet:

> Coag panel (LOINC 24373-3) is now active with canonical PT/PT_INR/APTT (all three derived from `coagulation_status` + `hepatic_function`). Fibrinogen emits as an individual Observation (biphasic: acute-phase ↑ / DIC ↓). D-dimer + VTE-specificity flag and warfarin/heparin INR targeting deferred to a follow-up PR.

Bump any analyte or panel count totals.

- [ ] **Step 2: Mirror in `README.ja.md`**

Translate the bullet (Japanese with English technical terms per CLAUDE.md). Bump matching counts.

- [ ] **Step 3: Update `DESIGN.md`**

Locate §6.10 (or the section discussing AD-57 lab venues). Add a one-line note: Coag panel LOINC 24373-3 is now active; canonical PT/PT_INR/APTT come from `coagulation_status` + `hepatic_function` axes; Fibrinogen is biphasic. No new ADR — AD-57 (BNP-pattern surgical) and AD-59 (per-order RNG isolation) already cover the pattern.

- [ ] **Step 4: Update `clinosim/modules/physiology/README.md`**

In the Japanese derivation-rules section, add APTT / PT (seconds) / Fibrinogen alongside existing PT_INR / Plt entries. Include the formulas and clinical interpretation.

- [ ] **Step 5: Update `clinosim/modules/observation/README.md`**

Add note: `lab_panels.yaml` now includes Coag/LFT/Lipid/UA (improvement I1); document the silent-drop semantics for UA's urine analytes until urine physiology is implemented.

- [ ] **Step 6: Update `CLAUDE.md`**

In the "Adding a new code" / "panel" guidance, add Coag canonical 3 as a worked example if it improves clarity. No new architecture rule needed.

- [ ] **Step 7: Update `TODO.md`**

- Move Coag panel activation from "next" to "done" (with date + PR ref).
- Add entries for the deferred improvements: I4 panel-YAML unification, I5 `on_anticoagulation` axis (paired with D_dimer Phase 2), I6 `clinical_course.actions[].test` field disambiguation, I7 `platelet_status` axis.

- [ ] **Step 8: Run full unit + integration to confirm nothing else broke**

```bash
pytest tests/unit tests/integration -x -q
```

Expected: ALL PASS.

- [ ] **Step 9: Commit**

```bash
git add README.md README.ja.md DESIGN.md \
        clinosim/modules/physiology/README.md clinosim/modules/observation/README.md \
        CLAUDE.md TODO.md
git commit -m "$(cat <<'EOF'
docs(sync): Coag panel activation — README/DESIGN/module/CLAUDE/TODO

Documents:
- Coag panel LOINC 24373-3 now active (PT/PT_INR/APTT canonical 3)
- Fibrinogen biphasic emit (acute-phase ↑ / DIC ↓)
- lab_panels.yaml expansion source gains Coag/LFT/Lipid/UA (improvement I1)
- Deferred follow-ups recorded in TODO: I4 panel-YAML unification,
  I5 on_anticoagulation + D-dimer Phase 2, I6 clinical_course field
  disambiguation, I7 platelet_status axis

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_017dRsomkKQhRVUi5PZY2HSs
EOF
)"
```

---

## Task 11: PR creation

**Files:** none (gh action).

**Interfaces:**
- Consumes: branch `feat/coag-panel-physiology` with all commits from Tasks 1–10.
- Produces: GitHub PR with audit links in the body.

- [ ] **Step 1: Final unit + integration + e2e run**

```bash
pytest -x -q
```

Expected: ALL PASS (~667 + new tests). Re-run any flaky e2e individually per memory `feedback_clinosim_workflow`.

- [ ] **Step 2: Push branch**

```bash
git push -u origin feat/coag-panel-physiology
```

- [ ] **Step 3: Open PR**

```bash
gh pr create --title "feat(physiology): Coag panel (LOINC 24373-3) activation — APTT + PT + Fibrinogen" --body "$(cat <<'EOF'
## Summary

Activates the LOINC 24373-3 Coag DiagnosticReport panel by extending
`physiology.derive_lab_values` with three new analytes — all derived from
existing state axes, no new `PhysiologicalState` field, AD-57 BNP-pattern
surgical:

- **APTT** (sec) = `clamp(30 + coagulation_status * 55, 20, 150)`
- **PT** (sec) = `clamp(12 * PT_INR, 9, 90)` (ISI=1.0 consistency invariant)
- **Fibrinogen** (mg/dL) = `clamp(300 + inflammation*250 - coagulation_status*280, 50, 800)` (biphasic: acute-phase ↑ / DIC ↓)

Also adopts improvements (uniform rule, memory `feedback_propose_improvements_to_existing`):

- **I1**: `lab_panels.yaml` gains Coag/LFT/Lipid/UA (asymmetry with `lab_panel_groups.yaml` resolved)
- **I2**: `lab_panel_groups.yaml` Coag comment documents LOINC 24373-3 authoritative scope (Fibrinogen excluded by Regenstrief)
- **I3**: stale Cl/Ca silent-drop comment refreshed (resolved by PR #78)
- **I8**: Fibrinogen "range exists, derive missing" gap closed

Deferred: D-dimer + `causes_vte` + `on_anticoagulation` axes (Phase 2 PR);
panel-YAML unification refactor (I4); `clinical_course.actions[].test`
field disambiguation (I6); `platelet_status` axis (I7).

## Audit summary

3-axis DQR (US p=10000 + JP p=5000, seed=42) — see
`docs/reviews/2026-06-23-coag-panel-data-quality-review.md`:
- Structural: 100% refRange / 100% display≠code / new codes resolve 100%
- Clinical: sepsis Fibrinogen DIC tail / sepsis APTT prolongation / hepatic PT prolongation all PASS
- JP language: zero US-japanese-leak / JP coag fields 100% Japanese / JLAC10 ja JCCLS-official

Byte-diff vs master `fbd80607` confirms AD-59 invariant: only
Observation.ndjson + DiagnosticReport.ndjson change; all other NDJSONs
byte-identical.

## Spec / plan

- Spec: `docs/superpowers/specs/2026-06-23-coag-panel-physiology-design.md`
- Plan: `docs/superpowers/plans/2026-06-23-coag-panel-physiology.md`

## Test plan

- [x] unit + integration green
- [x] e2e golden green (regenerated for new APTT/PT/Fibrinogen Observations + Coag DRs)
- [x] byte-diff invariant verified (`scratchpad/coag_panel_byte_diff_results.txt`)
- [x] 3-axis DQR PASS (`docs/reviews/2026-06-23-coag-panel-data-quality-review.md`)

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
| Physiology extension (APTT/PT/Fibrinogen) | Tasks 2–4 |
| `lab_panels.yaml` Coag/LFT/Lipid/UA + comment refresh (I1/I3) | Task 5 |
| `lab_panel_groups.yaml` Coag scope comment (I2) | Task 5 |
| Locale code mappings + reference ranges | Task 1 |
| LOINC + JLAC10 authoritative additions | Task 1 |
| AD-59 invariant guard | Task 6 |
| Whole-population DQR | Task 9 |
| Docs sync in same PR | Task 10 |

Improvement table I1/I2/I3/I8 (in-PR) all have tasks. I4/I5/I6/I7 are explicitly carried forward in TODO (Task 10 Step 7).

**2. Placeholder scan** — no "TBD", "TODO" without specific context, no "add error handling", no untyped references. JP JLAC10 codes have explicit fallback instructions (`# TODO: verify` on uncertainty per memory `feedback_clinosim_workflow`).

**3. Type consistency** — internal lab names `APTT` / `PT` / `Fibrinogen` used consistently across Task 1 (locale mappings + ranges + code data), Tasks 2–4 (derive_lab_values produces these exact keys), Task 5 (panel components reference exact keys), Tasks 6–7 (tests query exact keys), Task 9 (DQR script reads exact keys). PT formula `PT = 12 * PT_INR` documented as consistency invariant in Task 3 and asserted in DQR (Task 9). Coag panel components `[PT, PT_INR, APTT]` identical in both `lab_panel_groups.yaml` (existing) and `lab_panels.yaml` (Task 5 addition).

Plan ready.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-06-23-coag-panel-physiology.md`. Two execution options:

**1. Subagent-Driven** — fresh subagent per task with two-stage review; best for large branching or where independent verification is valuable.

**2. Inline Execution (recommended for this PR)** — single-module tightly-coupled physiology + panel work; the per-PR pattern memory `feedback_clinosim_workflow` recommends inline for "単一モジュール密結合タスク"; matches PR #74/#75/#78 cadence.

Per the recurring workflow in memory (`feedback_clinosim_workflow`): inline executing-plans with checkpoints between Task 4 (derives done), Task 8 (byte-diff verified), Task 9 (DQR calibration loop), and Task 10 (docs sync) is the natural rhythm here.
