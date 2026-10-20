# Longitudinal Phase 4c — Oncology AJCC/TNM Markov Stages Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add six Markov stage ladder yamls under `clinosim/locale/shared/longitudinal/stage/` for the six cancer families already carrying medication regimens in `chronic_medications.yaml` (C16 gastric, C18 colon, C22 liver, C34 lung, C50 breast, C61 prostate), so that cancer-carrying patients evolve across AJCC 8 / BCLC stages year-over-year through the longitudinal engine instead of a frozen scalar at Layer-1 generation.

**Architecture:** Pure yaml authoring plus unit + integration tests. Phase 2's Markov pattern (`clinosim/modules/longitudinal/patterns/markov.py`), loader, and engine dispatch are reused unchanged. Each new yaml declares `pattern: markov`, `icd_base: C<nn>`, a states vector + `initial_distribution` + `transitions` map, and ships AJCC 8 (or BCLC for HCC) stage labels with per-year progression rates calibrated against NCCN 2024 guidelines and SEER adjusted survival.

**Tech Stack:** Python 3.12, pydantic 2.x, pyyaml, numpy.

**Spec:** `docs/superpowers/specs/2026-10-20-longitudinal-state-evolution-design.md` — §4.2.2 Markov pattern body, §8 Phase 2 scope (cancer stage ladders are explicitly in-scope for Phase 2 as a horizontal extension of the chronic-stage framework; this plan ships them as Phase 4c now that Phase 2 has merged for non-cancer chronic conditions).

## Global Constraints

- Markov stage yamls live under `clinosim/locale/shared/longitudinal/stage/` (Phase 2 convention). One yaml per icd_base.
- Every yaml has `attribute_id`, `pattern: markov`, `depends_on: []`, `clinical_scope.requires_chronic_codes: ["C<nn>"]`, `clinical_scope.requires_age_band: [0, 120]`, `state_name`, `icd_base`, `states`, `initial_distribution`, `transitions`, `narrative_label` (`en` + `ja`), and `source`.
- The terminal stage (AJCC IV for anatomic staging, BCLC D for HCC) is absorbing — its `transitions` entry is an empty mapping `{}`.
- `extra="forbid"` on all pydantic models is unchanged — no `MarkovSpec` edits here.
- Byte-identity across the migration is NOT required (spec §2.3). Patients with the triggering C-code gain stage history; non-cancer cohorts byte-identical.
- `scripts/reproduce.sh` same-seed-twice contract stays as CI gate. CI merge gate: `scripts/wait-pr-ci.sh <num>` + grep `"FAILURE"` = 0 before merge.
- No Claude attribution lines in PR body or commit messages (DCO signoff only via `git commit -s`).
- CHANGELOG + PR body entries written as a single Markdown paragraph per bullet, NOT hard-wrapped.
- CHANGELOG `## [Unreleased]` already has an `### Added` block (Phase 4a + 4b.1); append the Phase 4c bullet to that existing block, do NOT create a new `### Added` heading.
- BCLC (Barcelona Clinic Liver Cancer) is used for C22 instead of AJCC because BCLC is the clinically authoritative treatment-allocation stage for HCC — NCCN, EASL, AASLD all cite BCLC.
- Each `requires_chronic_codes: ["C<nn>"]` is a prefix match; a person carrying `C50.1` or `C50.2` matches `["C50"]` via `_chronic_codes_match` prefix semantics (existing engine behavior).

## Review Focus

1. **ICD prefix match on sub-codes** — a person carrying `C50.1` (breast upper-outer quadrant) or `C50.2` must engage the C50 Markov attribute; the yaml's `requires_chronic_codes: ["C50"]` must prefix-match sub-codes, not require exact `C50`. Pinned in Task 3.
2. **BCLC non-numeric state labels** — C22's states are `BCLC 0 / A / B / C / D` (strings with embedded spaces), not AJCC `I / II / III / IV` numerals. The Markov loader + `step()` + `initial()` must round-trip these string keys through yaml → `MarkovSpec.states` + `transitions` dict unmodified. Pinned in Task 2.
3. **Non-cancer cohort byte-identity** — a cohort with zero C16/C18/C22/C34/C50/C61 patients produces no stage history from these yamls (clinical_scope gate drops them out of scope → zero RNG draws). Pinned in Task 4 integration.
4. **icd_base isolation across cancers** — a person carrying `C50` must engage ONLY the breast attribute, not the lung (C34) or colon (C18) attributes. The engine's `_select_markov_winners` keys on `icd_base`, so distinct icd_bases produce distinct winners; verify end-to-end. Pinned in Task 4.
5. **Terminal-state absorption** — a person already at `AJCC IV` (or `BCLC D` for C22) must stay there under every subsequent `advance_one_year` call; the empty transitions row is the absorbing property that governs long-horizon trajectories. Pinned in Task 4.

---

## File Structure

**Create:**
- `clinosim/locale/shared/longitudinal/stage/gastric_cancer_stage_c16.yaml`
- `clinosim/locale/shared/longitudinal/stage/colon_cancer_stage_c18.yaml`
- `clinosim/locale/shared/longitudinal/stage/liver_cancer_stage_c22.yaml`
- `clinosim/locale/shared/longitudinal/stage/lung_cancer_stage_c34.yaml`
- `clinosim/locale/shared/longitudinal/stage/breast_cancer_stage_c50.yaml`
- `clinosim/locale/shared/longitudinal/stage/prostate_cancer_stage_c61.yaml`
- `tests/modules/longitudinal/test_cancer_stage_yamls_load.py` — all 6 yamls load with expected states + absorbing terminal + prefix scope.
- `tests/modules/longitudinal/test_cancer_stage_bclc_strings.py` — Task 2 pin for Review Focus #2 (non-numeric BCLC labels round-trip).
- `tests/integration/test_cancer_stage_in_cif.py` — p=200 US 5y cohort stage history populated per cancer type; non-cancer cohort gains no cancer stage keys; icd_base isolation; terminal absorption.

**Modify:**
- `CHANGELOG.md` — append one bullet to the existing `## [Unreleased]` `### Added` block.

---

## Task 1: C16 gastric + C18 colon stage yamls

**Files:**
- Create: `clinosim/locale/shared/longitudinal/stage/gastric_cancer_stage_c16.yaml`
- Create: `clinosim/locale/shared/longitudinal/stage/colon_cancer_stage_c18.yaml`
- Test: `tests/modules/longitudinal/test_cancer_stage_yamls_load.py`

**Interfaces:**
- Consumes: Phase 2 `MarkovSpec` + loader (`clinosim/modules/longitudinal/loader.py`) unchanged.
- Produces: two `AttributeSpec` entries at `attribute_id: gastric_cancer_stage_c16` and `colon_cancer_stage_c18`; both with `clinical_scope.requires_chronic_codes` matching their C-prefix, `states: ["AJCC I", "AJCC II", "AJCC III", "AJCC IV"]`, `transitions["AJCC IV"] == {}`.

- [ ] **Step 1: Write failing test**

```python
# tests/modules/longitudinal/test_cancer_stage_yamls_load.py
from clinosim.modules.longitudinal.loader import load_attribute_specs


AJCC_STATES = ["AJCC I", "AJCC II", "AJCC III", "AJCC IV"]


def test_gastric_cancer_stage_yaml_loads():
    load_attribute_specs.cache_clear()
    specs = load_attribute_specs()
    assert "gastric_cancer_stage_c16" in specs
    spec = specs["gastric_cancer_stage_c16"]
    assert spec.pattern == "markov"
    assert spec.clinical_scope.requires_chronic_codes == ["C16"]
    body = spec.body
    assert body.icd_base == "C16"
    assert body.states == AJCC_STATES
    assert body.transitions["AJCC IV"] == {}  # absorbing
    assert body.transitions["AJCC I"]["AJCC II"] == 0.15
    assert body.transitions["AJCC II"]["AJCC III"] == 0.10
    assert body.transitions["AJCC III"]["AJCC IV"] == 0.08


def test_colon_cancer_stage_yaml_loads():
    load_attribute_specs.cache_clear()
    specs = load_attribute_specs()
    assert "colon_cancer_stage_c18" in specs
    spec = specs["colon_cancer_stage_c18"]
    assert spec.pattern == "markov"
    assert spec.clinical_scope.requires_chronic_codes == ["C18"]
    body = spec.body
    assert body.icd_base == "C18"
    assert body.states == AJCC_STATES
    assert body.transitions["AJCC IV"] == {}
    assert body.transitions["AJCC I"]["AJCC II"] == 0.12
    assert body.transitions["AJCC II"]["AJCC III"] == 0.08
    assert body.transitions["AJCC III"]["AJCC IV"] == 0.06
```

- [ ] **Step 2: Run tests to verify failing**

Run: `pytest tests/modules/longitudinal/test_cancer_stage_yamls_load.py -v`
Expected: FAIL — `"gastric_cancer_stage_c16" not in specs`.

- [ ] **Step 3: Author `gastric_cancer_stage_c16.yaml`**

Clinical calibration (gastric cancer under adjuvant fluoropyrimidine):
- Initial distribution weighted toward later stages because clinosim's gastric cohort is diagnostic-presentation-selected (symptomatic → more advanced at diagnosis).
- Per-year progression: `I → II: 0.15`, `II → III: 0.10`, `III → IV: 0.08`. Reflects natural history under 5-FU-based adjuvant per JGCA 2021 + AJCC 8 (Amin MB et al, AJCC Cancer Staging Manual 8e, Springer 2017).
- SEER 2024 adjusted 5y survival stage I 71 %, stage IV 6 % — stage IV absorbing is clinically appropriate (further mortality driven by `_condition_reactive_mortality`).

Yaml content: standard shape (see `ckd_n18.yaml` exemplar). `states: ["AJCC I", "AJCC II", "AJCC III", "AJCC IV"]`, `initial_distribution: {"AJCC I": 0.15, "AJCC II": 0.30, "AJCC III": 0.35, "AJCC IV": 0.20}`, `transitions` with the three rates above and `"AJCC IV": {}`. `narrative_label.en: "Gastric cancer stage"`, `narrative_label.ja: "胃癌 ステージ"`. Source cites: AJCC 8 Manual (Amin MB et al 2017); JGCA 2021 Treatment Guidelines; SEER 2024 adjusted survival.

- [ ] **Step 4: Author `colon_cancer_stage_c18.yaml`**

Clinical calibration (colon cancer under adjuvant):
- Initial distribution slightly more early-stage because colorectal screening (colonoscopy) catches more stage I-II: `{"AJCC I": 0.25, "AJCC II": 0.35, "AJCC III": 0.25, "AJCC IV": 0.15}`.
- Per-year progression: `I → II: 0.12`, `II → III: 0.08`, `III → IV: 0.06`. Reflects natural history under FOLFOX/CAPOX adjuvant per NCCN Colon 2024 + SEER 2024.
- Terminal: `"AJCC IV": {}` absorbing.

Yaml content: standard shape. `narrative_label.en: "Colon cancer stage"`, `narrative_label.ja: "結腸癌 ステージ"`. Source cites: AJCC 8 Manual; NCCN Colon Cancer Guidelines v2024; SEER 2024 adjusted survival (Howlader N et al, SEER Cancer Statistics Review).

- [ ] **Step 5: Run tests to verify passing**

Run: `pytest tests/modules/longitudinal/test_cancer_stage_yamls_load.py -v`
Expected: 2/2 pass.

- [ ] **Step 6: Full longitudinal regression**

Run: `pytest tests/modules/longitudinal/`
Expected: all green (prior Phase 2 + 4a + 4b.1 tests unchanged).

- [ ] **Step 7: Commit**

```bash
git add clinosim/locale/shared/longitudinal/stage/gastric_cancer_stage_c16.yaml \
        clinosim/locale/shared/longitudinal/stage/colon_cancer_stage_c18.yaml \
        tests/modules/longitudinal/test_cancer_stage_yamls_load.py
git commit -s -m "feat(longitudinal): add C16 gastric + C18 colon cancer Markov stage ladders"
```

---

## Task 2: C22 liver (BCLC) + C34 lung AJCC stage yamls

**Files:**
- Create: `clinosim/locale/shared/longitudinal/stage/liver_cancer_stage_c22.yaml`
- Create: `clinosim/locale/shared/longitudinal/stage/lung_cancer_stage_c34.yaml`
- Test: extend `tests/modules/longitudinal/test_cancer_stage_yamls_load.py` + new `tests/modules/longitudinal/test_cancer_stage_bclc_strings.py`

**Interfaces:**
- Produces: `AttributeSpec` entries at `attribute_id: liver_cancer_stage_c22` (BCLC states) and `lung_cancer_stage_c34` (AJCC states).

- [ ] **Step 1: Append failing tests to `test_cancer_stage_yamls_load.py`**

```python
BCLC_STATES = ["BCLC 0", "BCLC A", "BCLC B", "BCLC C", "BCLC D"]


def test_liver_cancer_stage_yaml_loads():
    load_attribute_specs.cache_clear()
    specs = load_attribute_specs()
    assert "liver_cancer_stage_c22" in specs
    spec = specs["liver_cancer_stage_c22"]
    assert spec.pattern == "markov"
    assert spec.clinical_scope.requires_chronic_codes == ["C22"]
    body = spec.body
    assert body.icd_base == "C22"
    assert body.states == BCLC_STATES
    assert body.transitions["BCLC D"] == {}
    assert body.transitions["BCLC 0"]["BCLC A"] == 0.20
    assert body.transitions["BCLC A"]["BCLC B"] == 0.18
    assert body.transitions["BCLC B"]["BCLC C"] == 0.15
    assert body.transitions["BCLC C"]["BCLC D"] == 0.20


def test_lung_cancer_stage_yaml_loads():
    load_attribute_specs.cache_clear()
    specs = load_attribute_specs()
    assert "lung_cancer_stage_c34" in specs
    spec = specs["lung_cancer_stage_c34"]
    assert spec.clinical_scope.requires_chronic_codes == ["C34"]
    body = spec.body
    assert body.icd_base == "C34"
    assert body.states == AJCC_STATES
    assert body.transitions["AJCC IV"] == {}
    assert body.transitions["AJCC I"]["AJCC II"] == 0.18
    assert body.transitions["AJCC II"]["AJCC III"] == 0.12
    assert body.transitions["AJCC III"]["AJCC IV"] == 0.10
```

- [ ] **Step 2: Write Review Focus #2 pin — BCLC string round-trip**

```python
# tests/modules/longitudinal/test_cancer_stage_bclc_strings.py
"""Review Focus #2 — BCLC non-numeric stage labels round-trip through
yaml → MarkovSpec → step() → initial() unchanged (strings with embedded
spaces are not special-cased anywhere)."""

import numpy as np

from clinosim.modules.longitudinal.loader import load_attribute_specs
from clinosim.modules.longitudinal.patterns.markov import step, initial


def test_bclc_initial_draw_returns_known_state():
    load_attribute_specs.cache_clear()
    spec = load_attribute_specs()["liver_cancer_stage_c22"].body
    for seed in (0, 1, 7, 42, 123):
        s = initial(np.random.default_rng(seed), spec)
        assert s in {"BCLC 0", "BCLC A", "BCLC B", "BCLC C", "BCLC D"}


def test_bclc_step_from_terminal_stays_terminal():
    load_attribute_specs.cache_clear()
    spec = load_attribute_specs()["liver_cancer_stage_c22"].body
    for _ in range(10):
        assert step("BCLC D", np.random.default_rng(0), spec) == "BCLC D"


def test_bclc_step_from_early_may_progress():
    """Over many trials from BCLC 0 the step must sometimes return BCLC A."""
    load_attribute_specs.cache_clear()
    spec = load_attribute_specs()["liver_cancer_stage_c22"].body
    progressed = sum(1 for seed in range(100) if step("BCLC 0", np.random.default_rng(seed), spec) == "BCLC A")
    assert progressed > 0, "BCLC 0 never progressed to BCLC A across 100 seeds — Markov row misread"
```

- [ ] **Step 3: Verify failing**

Run: `pytest tests/modules/longitudinal/test_cancer_stage_yamls_load.py tests/modules/longitudinal/test_cancer_stage_bclc_strings.py -v`
Expected: FAIL — `"liver_cancer_stage_c22" not in specs`.

- [ ] **Step 4: Author `liver_cancer_stage_c22.yaml`**

Clinical calibration (HCC under BCLC-driven treatment allocation):
- BCLC (Barcelona Clinic Liver Cancer) stages: `0` (very early, single ≤ 2 cm, Child-Pugh A, PS 0), `A` (early, single or ≤ 3 nodules ≤ 3 cm), `B` (intermediate, multinodular), `C` (advanced, vascular invasion / extra-hepatic), `D` (terminal, Child-Pugh C or PS > 2).
- Treatment allocation: 0/A → curative (resection / ablation / transplant), B → TACE, C → systemic (sorafenib / lenvatinib / atezolizumab-bevacizumab), D → best supportive.
- Initial distribution: `{"BCLC 0": 0.10, "BCLC A": 0.20, "BCLC B": 0.30, "BCLC C": 0.30, "BCLC D": 0.10}` — HCC often diagnosed intermediate-stage due to lack of screening in cirrhosis.
- Per-year progression: `0 → A: 0.20`, `A → B: 0.18`, `B → C: 0.15`, `C → D: 0.20`. HCC natural history is faster than most solid tumors.
- Terminal: `"BCLC D": {}`.

Yaml content: standard shape. `state_name: "liver_cancer_stage"`, `icd_base: C22`, `narrative_label.en: "BCLC stage"`, `narrative_label.ja: "BCLC ステージ"`. Source cites: Reig M et al, "BCLC strategy for prognosis prediction and treatment recommendation: 2022 update", J Hepatol 2022;76:681; AASLD 2023 HCC Guidance (Singal AG et al, Hepatology 2023); EASL 2018 Clinical Practice Guidelines on HCC Management.

- [ ] **Step 5: Author `lung_cancer_stage_c34.yaml`**

Clinical calibration (NSCLC under NCCN 2024):
- Initial distribution: `{"AJCC I": 0.20, "AJCC II": 0.15, "AJCC III": 0.25, "AJCC IV": 0.40}` — NSCLC diagnosed late (symptomatic presentation, screening programs limited in reach).
- Per-year progression: `I → II: 0.18`, `II → III: 0.12`, `III → IV: 0.10`. Faster than breast / colon because lung cancer biology is more aggressive and metastasis-prone.
- Terminal: `"AJCC IV": {}`.

Yaml content: standard shape. `state_name: "lung_cancer_stage"`, `icd_base: C34`, `narrative_label.en: "Lung cancer stage"`, `narrative_label.ja: "肺癌 ステージ"`. Source cites: Amin MB et al, AJCC Cancer Staging Manual 8e, 2017 (Lung Chapter 36); NCCN Non-Small Cell Lung Cancer Guidelines v2024; Goldstraw P et al, "The IASLC Lung Cancer Staging Project: Proposals for Revision of the TNM Stage Groupings in the Forthcoming (Eighth) Edition", J Thorac Oncol 2016;11:39.

- [ ] **Step 6: Run tests to verify passing**

Run: `pytest tests/modules/longitudinal/test_cancer_stage_yamls_load.py tests/modules/longitudinal/test_cancer_stage_bclc_strings.py -v`
Expected: all previous + new tests pass.

- [ ] **Step 7: Commit**

```bash
git add clinosim/locale/shared/longitudinal/stage/liver_cancer_stage_c22.yaml \
        clinosim/locale/shared/longitudinal/stage/lung_cancer_stage_c34.yaml \
        tests/modules/longitudinal/test_cancer_stage_yamls_load.py \
        tests/modules/longitudinal/test_cancer_stage_bclc_strings.py
git commit -s -m "feat(longitudinal): add C22 liver (BCLC) + C34 lung Markov stage ladders"
```

---

## Task 3: C50 breast + C61 prostate stage yamls (+ Review Focus #1 pin)

**Files:**
- Create: `clinosim/locale/shared/longitudinal/stage/breast_cancer_stage_c50.yaml`
- Create: `clinosim/locale/shared/longitudinal/stage/prostate_cancer_stage_c61.yaml`
- Test: extend `tests/modules/longitudinal/test_cancer_stage_yamls_load.py`

**Interfaces:**
- Produces: `AttributeSpec` entries at `attribute_id: breast_cancer_stage_c50`, `prostate_cancer_stage_c61`. Both use `AJCC_STATES`. Prefix scope `["C50"]` / `["C61"]`.

- [ ] **Step 1: Append failing tests**

```python
def test_breast_cancer_stage_yaml_loads():
    load_attribute_specs.cache_clear()
    specs = load_attribute_specs()
    assert "breast_cancer_stage_c50" in specs
    spec = specs["breast_cancer_stage_c50"]
    assert spec.clinical_scope.requires_chronic_codes == ["C50"]
    body = spec.body
    assert body.icd_base == "C50"
    assert body.states == AJCC_STATES
    assert body.transitions["AJCC IV"] == {}
    assert body.transitions["AJCC I"]["AJCC II"] == 0.08
    assert body.transitions["AJCC II"]["AJCC III"] == 0.06
    assert body.transitions["AJCC III"]["AJCC IV"] == 0.05


def test_prostate_cancer_stage_yaml_loads():
    load_attribute_specs.cache_clear()
    specs = load_attribute_specs()
    assert "prostate_cancer_stage_c61" in specs
    spec = specs["prostate_cancer_stage_c61"]
    assert spec.clinical_scope.requires_chronic_codes == ["C61"]
    body = spec.body
    assert body.icd_base == "C61"
    assert body.states == AJCC_STATES
    assert body.transitions["AJCC IV"] == {}
    assert body.transitions["AJCC I"]["AJCC II"] == 0.05
    assert body.transitions["AJCC II"]["AJCC III"] == 0.04
    assert body.transitions["AJCC III"]["AJCC IV"] == 0.03


def test_breast_subcode_matches_c50_prefix():
    """Review Focus #1 pin: a person carrying C50.1 (upper-outer quadrant)
    engages the breast attribute via requires_chronic_codes prefix match."""
    from datetime import date
    from clinosim.modules.longitudinal import engine as le
    from clinosim.types.population import PersonRecord
    import numpy as np

    load_attribute_specs.cache_clear()
    p = PersonRecord(
        person_id="PX", household_id="HX", age=55, sex="F",
        date_of_birth=date(1970, 1, 1), chronic_conditions=["C50.1"],
    )
    snap = le.initial_snapshot(p, 2024, np.random.default_rng(0))
    assert "C50" in snap.chronic_stages
    assert snap.chronic_stages["C50"] in {"AJCC I", "AJCC II", "AJCC III", "AJCC IV"}
```

- [ ] **Step 2: Verify failing**

Run: `pytest tests/modules/longitudinal/test_cancer_stage_yamls_load.py -v`
Expected: FAIL — `"breast_cancer_stage_c50" not in specs`.

- [ ] **Step 3: Author `breast_cancer_stage_c50.yaml`**

Clinical calibration (breast under endocrine ± HER2 therapy):
- Initial distribution: `{"AJCC I": 0.35, "AJCC II": 0.35, "AJCC III": 0.20, "AJCC IV": 0.10}` — mammographic screening skews early-stage.
- Per-year progression: `I → II: 0.08`, `II → III: 0.06`, `III → IV: 0.05`. Lower than GI/lung because endocrine therapy (tamoxifen / AI) + HER2-directed therapy is highly effective for the majority ER+ or HER2+ cohort.
- Terminal: `"AJCC IV": {}`.

Yaml content: standard shape. `state_name: "breast_cancer_stage"`, `icd_base: C50`, `narrative_label.en: "Breast cancer stage"`, `narrative_label.ja: "乳癌 ステージ"`. Source cites: AJCC 8 Manual Breast Chapter 48 (Amin MB et al 2017); NCCN Breast Cancer Guidelines v2024; SEER 2024 5y relative survival (Howlader N et al).

- [ ] **Step 4: Author `prostate_cancer_stage_c61.yaml`**

Clinical calibration (prostate under ADT):
- Initial distribution: `{"AJCC I": 0.30, "AJCC II": 0.40, "AJCC III": 0.20, "AJCC IV": 0.10}` — PSA screening + relatively indolent biology skew early-stage.
- Per-year progression: `I → II: 0.05`, `II → III: 0.04`, `III → IV: 0.03`. Among the slowest solid-tumor progression rates because ADT + newer AR-targeted agents (abiraterone / enzalutamide) extend progression-free intervals substantially.
- Terminal: `"AJCC IV": {}`.

Yaml content: standard shape. `state_name: "prostate_cancer_stage"`, `icd_base: C61`, `narrative_label.en: "Prostate cancer stage"`, `narrative_label.ja: "前立腺癌 ステージ"`. Source cites: AJCC 8 Manual Prostate Chapter 58; NCCN Prostate Cancer Guidelines v2024; Mohler JL et al, "Prostate Cancer, Version 2.2019, NCCN Clinical Practice Guidelines", J Natl Compr Canc Netw 2019;17:479.

- [ ] **Step 5: Verify tests pass**

Run: `pytest tests/modules/longitudinal/test_cancer_stage_yamls_load.py tests/modules/longitudinal/ -v`
Expected: all tests from Tasks 1-3 pass; full longitudinal regression green.

- [ ] **Step 6: Commit**

```bash
git add clinosim/locale/shared/longitudinal/stage/breast_cancer_stage_c50.yaml \
        clinosim/locale/shared/longitudinal/stage/prostate_cancer_stage_c61.yaml \
        tests/modules/longitudinal/test_cancer_stage_yamls_load.py
git commit -s -m "feat(longitudinal): add C50 breast + C61 prostate Markov stage ladders"
```

---

## Task 4: Integration — cancer stage in CIF, icd_base isolation, non-cancer invariance, terminal absorption

**Files:**
- Create: `tests/integration/test_cancer_stage_in_cif.py`

**Interfaces:**
- Consumes: all 6 Markov yamls from Tasks 1-3 + Phase 2 engine dispatch.
- Produces: cohort-level pin that each cancer family's chronic_stages key appears in affected patients' longitudinal_history, is absent for non-cancer patients, and is absorbed at the terminal stage.

- [ ] **Step 1: Write failing cohort tests**

```python
# tests/integration/test_cancer_stage_in_cif.py
"""Phase 4c — cancer Markov stage integration in CIF.

p=200 US seed=42 5y cohort end-to-end.
"""

from __future__ import annotations

import numpy as np
import pytest

from clinosim.modules.longitudinal.loader import load_attribute_specs
from clinosim.modules.population.aging import advance_population
from clinosim.modules.population.engine import generate_population


@pytest.fixture(autouse=True)
def _clear_loader() -> None:
    load_attribute_specs.cache_clear()
    yield
    load_attribute_specs.cache_clear()


CANCER_ICD_BASES = ["C16", "C18", "C22", "C34", "C50", "C61"]


@pytest.mark.integration
def test_cancer_patients_gain_stage_history_across_5y():
    """A C-code adult must carry its icd_base key in
    longitudinal_history[-1].chronic_stages after 5 sim years."""
    registry = generate_population(size=200, country="US", rng=np.random.default_rng(42), base_year=2024)
    for year in (2025, 2026, 2027, 2028):
        advance_population(registry, year=year, locale="US")

    found_counts = {b: 0 for b in CANCER_ICD_BASES}
    for person in registry.persons.values():
        if not person.longitudinal_history:
            continue
        last = person.longitudinal_history[-1]
        for b in CANCER_ICD_BASES:
            if any(c.startswith(b) for c in person.chronic_conditions):
                assert b in last.chronic_stages, f"{person.person_id} missing {b} stage"
                found_counts[b] += 1
    # At least one cancer family should appear in the sample.
    assert sum(found_counts.values()) >= 1, f"sample has no cancer patients — bump size or seed: {found_counts}"


@pytest.mark.integration
def test_non_cancer_patients_never_gain_cancer_stage_keys():
    """Review Focus #3: a patient with no C-code never has any of the
    six icd_base keys in chronic_stages (clinical_scope gate)."""
    registry = generate_population(size=200, country="US", rng=np.random.default_rng(42), base_year=2024)
    for year in (2025, 2026, 2027, 2028):
        advance_population(registry, year=year, locale="US")
    for person in registry.persons.values():
        if any(c.startswith(tuple(CANCER_ICD_BASES)) for c in person.chronic_conditions):
            continue
        for snap in person.longitudinal_history:
            leaked = [b for b in CANCER_ICD_BASES if b in snap.chronic_stages]
            assert not leaked, f"non-cancer person {person.person_id} picked up {leaked}"


@pytest.mark.integration
def test_cancer_stage_icd_base_isolation():
    """Review Focus #4: a C50-only patient must carry ONLY the C50
    icd_base key in chronic_stages, not any other cancer's icd_base."""
    registry = generate_population(size=200, country="US", rng=np.random.default_rng(42), base_year=2024)
    for year in (2025, 2026, 2027, 2028):
        advance_population(registry, year=year, locale="US")
    checked = 0
    for person in registry.persons.values():
        c_prefixes = {b for b in CANCER_ICD_BASES if any(c.startswith(b) for c in person.chronic_conditions)}
        if len(c_prefixes) != 1:
            continue
        checked += 1
        only = next(iter(c_prefixes))
        for snap in person.longitudinal_history:
            others = [b for b in CANCER_ICD_BASES if b != only and b in snap.chronic_stages]
            assert not others, f"{person.person_id} ({only}) leaked {others}"
    # Guard that we actually exercised the single-cancer path at least once;
    # if the sample has only zero or multi-cancer patients, bump size/seed.
    assert checked >= 1, "no single-cancer patient in sample — bump size or seed"


@pytest.mark.integration
def test_cancer_stage_terminal_is_absorbing_across_years():
    """Review Focus #5: once at AJCC IV (or BCLC D for C22), the stage
    stays there for every subsequent snapshot."""
    registry = generate_population(size=200, country="US", rng=np.random.default_rng(42), base_year=2024)
    for year in (2025, 2026, 2027, 2028):
        advance_population(registry, year=year, locale="US")
    for person in registry.persons.values():
        c_prefixes = {b for b in CANCER_ICD_BASES if any(c.startswith(b) for c in person.chronic_conditions)}
        for b in c_prefixes:
            terminal = "BCLC D" if b == "C22" else "AJCC IV"
            # Find the first snapshot that reached the terminal state; every
            # later snapshot must equal the terminal.
            hit = False
            for snap in person.longitudinal_history:
                if snap.chronic_stages.get(b) == terminal:
                    hit = True
                if hit:
                    assert snap.chronic_stages.get(b) == terminal, (
                        f"{person.person_id} ({b}) left terminal state"
                    )
```

- [ ] **Step 2: Run integration tests**

Run: `pytest tests/integration/test_cancer_stage_in_cif.py -v`
Expected: 4/4 pass. (If `test_cancer_patients_gain_stage_history_across_5y` reports zero cancer patients in the sample, bump `size` to 500 and ledger the ruling — the p=200 seed=42 cohort should carry at least one C-code adult per the US demographics yaml incidence rates.)

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_cancer_stage_in_cif.py
git commit -s -m "test(longitudinal): cancer stage integration + icd_base isolation + terminal absorption"
```

---

## Task 5: CHANGELOG + reproduce.sh + full regression

**Files:**
- Modify: `CHANGELOG.md` — append to the EXISTING `### Added` block under `## [Unreleased]`.

**Interfaces:**
- Consumes: Tasks 1-4.
- Produces: docs complete; CI gates green.

- [ ] **Step 1: Append CHANGELOG bullet**

Single physical line, NOT hard-wrapped, inside the existing `## [Unreleased]` `### Added` block (just below the Phase 4b.1 bullet):

```
- **Six cancer families (C16 gastric, C18 colon, C22 liver, C34 lung, C50 breast, C61 prostate) now carry AJCC 8 / BCLC Markov stage ladders instead of a frozen Layer-1 stage** (Issue #1701 partial — oncology stage ladder sub-item; Phase 4c of the longitudinal state-evolution subsystem; horizontal extension of Phase 2 Markov to the six C-code families already carrying regimen entries in `chronic_medications.yaml`). Six new yamls under `clinosim/locale/shared/longitudinal/stage/` (`gastric_cancer_stage_c16.yaml`, `colon_cancer_stage_c18.yaml`, `liver_cancer_stage_c22.yaml`, `lung_cancer_stage_c34.yaml`, `breast_cancer_stage_c50.yaml`, `prostate_cancer_stage_c61.yaml`) register one `AttributeSpec` each with cancer-type-appropriate per-year progression rates — C34 lung fastest (18/12/10 %/yr I→II→III→IV), C61 prostate slowest (5/4/3), C22 liver on BCLC not AJCC (20/18/15/20 across BCLC 0 → A → B → C → D). Terminal stage (AJCC IV / BCLC D) is absorbing; further mortality driven by existing `_condition_reactive_mortality` qx. Clinical basis: AJCC Cancer Staging Manual 8e (Amin et al 2017); NCCN 2024 Guidelines for each site; BCLC 2022 update (Reig et al, J Hepatol 2022); SEER 2024 adjusted survival. MINOR-track CIF change for C16/C18/C22/C34/C50/C61 patients only; non-cancer cohorts byte-identical.
```

- [ ] **Step 2: Full project test suite**

Run: `pytest -x tests/modules/longitudinal/ tests/integration/test_cancer_stage_in_cif.py tests/integration/test_longitudinal_engine_integration.py tests/integration/test_bmi_drift_in_cif.py tests/integration/test_dm_escalation_in_cif.py tests/integration/test_htn_lipid_escalation_in_cif.py`
Expected: all green.

- [ ] **Step 3: reproduce.sh gate**

Run: `scripts/reproduce.sh`
Expected: pass — byte-identical across US + JP seed=42 pop=50.

- [ ] **Step 4: Commit**

```bash
git add CHANGELOG.md
git commit -s -m "docs(changelog): Phase 4c cancer AJCC/BCLC Markov stage ladders"
```

---

## Self-review notes (plan author)

**1. Spec coverage.** Spec §4.2.2 Markov pattern already shipped under Phase 2 (#1711). The spec names cancer stage ladders as a Phase 2 horizontal extension (any ICD family with a discrete stage ontology). Six C-code families were deferred because Phase 2 shipped the 13 non-cancer chronic ladders first; this plan fills that gap under the "Phase 4c" label. The spec's clinical scope allows cancer families without naming them individually — the yamls' `source:` fields carry the AJCC 8 / BCLC authoritative anchors.

**2. Step scan.** Each step produces one artifact: a failing test with named assertions (stage names + exact transition rates), a yaml-authoring step pinned to a signature plus the exact calibration constants, or a commit. No step says "add appropriate X" or "handle edge cases" — every number in the plan is spec-grade.

**3. Type consistency.** `AJCC_STATES = ["AJCC I", "AJCC II", "AJCC III", "AJCC IV"]` is used verbatim in Tasks 1, 2 (lung), 3 (breast + prostate), and Task 4 integration. `BCLC_STATES` is defined once in Task 2 and used only there + Task 4 (via the terminal-detection helper `"BCLC D" if b == "C22" else "AJCC IV"`). `icd_base` strings match `requires_chronic_codes` prefixes exactly (C16, C18, C22, C34, C50, C61). attribute_ids follow `<label>_cancer_stage_<icd_base_lower>` convention (`gastric_cancer_stage_c16` etc.) — 1:1 with yaml filenames.

**4. Review Focus.** 5 items pinned, each in its owning task (Task 3 prefix match, Task 2 BCLC strings, Task 4 non-cancer invariance, Task 4 icd_base isolation, Task 4 terminal absorption). All exercise behaviors not pinned by Phase 2's own test suite for the 13 non-cancer Markov yamls.

**5. Proportion.** Plan is ~22 KB; the code it specifies is 6 yamls (~25 LOC each, ~150 total LOC YAML) + ~250 LOC Python tests. Ratio reasonable; the bulk of the plan is calibration citations and the exact transition-rate numbers each yaml must carry so an implementer transcribes rather than invents clinical values.

**Risks the plan accepts (not findings — settled):**

- **Transition rates are literature-anchored estimates, not per-patient-stratified** — AJCC 8 and NCCN guidelines report stage-conditional survival but not single-year transition probabilities directly. The plan's rates are derived from survival curves assuming exponential progression; a clinical SME may want to retune. Deferred to a Phase 4c.1 follow-up if cohort audit flags discrepancies.
- **No modifier wiring for cancer-specific comorbidity multipliers** — Phase 2 wires `_comorbidity_multiplier` on CKD/HF/etc, but there's no cancer-stage-conditional multiplier yet. All six yamls run at base rate. A future phase can add `comorbidity_progression_multipliers.yaml` entries for cancer-cancer interactions (e.g. hepatic metastasis of CRC accelerating C22 progression) without touching Phase 4c yamls.
- **No AJCC vs clinical-stage distinction** — the plan treats "AJCC I-IV" as the patient's current stage without distinguishing clinical from pathologic staging. A future refinement can split these; Phase 4c ships the single-axis ladder consistent with Phase 2's convention.
