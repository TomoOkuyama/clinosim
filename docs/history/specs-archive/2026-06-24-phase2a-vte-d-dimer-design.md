# Phase 2a — D-dimer derive + `causes_vte` scenario flag — Design Spec

- **Date:** 2026-06-24
- **Status:** DRAFT (pending user review)
- **Predecessors:** PR #80 (Coag panel activation), PR #74/#78 (AD-59 per-order lab RNG isolation)
- **Successor:** Phase 2b — `on_anticoagulation` axis (warfarin/heparin INR therapeutic-range modelling, I5) — separate PR
- **Branch:** `feat/phase2a-vte-d-dimer` (already created)

## 1. Goal

Activate the `D_dimer` analyte (LOINC 30240-9 / JLAC10 2B140) and introduce
a `causes_vte` scenario flag so VTE-spectrum patients (pulmonary embolism,
deep-vein thrombosis, cerebral infarction) show the clinically expected
high D-dimer signal, while non-VTE patients show baseline / mildly
elevated values driven by inflammation and DIC accumulation.

Currently:

- Seven disease YAMLs order `{test: "D_dimer"}` (PE, DVT, sepsis,
  acute_mi, cerebral_infarction, COPD exacerbation, AF-RVR) — but
  `physiology.derive_lab_values` does NOT derive D_dimer, so every
  order silently drops with no result.
- Locale `reference_range_lab.yaml` already declares ranges (US 0–0.50
  ug/mL FEU; JP 0–1.0 ug/mL FEU — JCCLS 共用基準範囲 2022).
- No `code_mapping_lab.yaml` entry maps `D_dimer` to its LOINC/JLAC10
  code yet (will fail to emit even after derive is added without the
  mapping).
- The `causes_myocardial_injury` scenario-flag pattern (PR #15 era) is
  established in `acute_mi.yaml:6` and `inpatient.py:559–560` but is
  **only wired into the inpatient Pass-1 lab loop** — `emergency.py`,
  `outpatient.py`, and a second inpatient lab path
  (`inpatient.py:1680`) call `derive_lab_values` without the flag,
  so MI patients presenting through the ED have no MI-grade troponin
  upshift today (silent latent defect, **J5** below).

## 2. Scope

### In-scope (this PR — Phase 2a)

1. **Physiology** (`physiology/engine.py`):
   - New `causes_vte: bool = False` parameter on `derive_lab_values`
     (signature mirrors `myocardial_injury: bool = False`)
   - `D_dimer` derive: multi-axis (`coagulation_status` + `inflammation_level`
     + age + `causes_vte`), clamp `[0.15, 20.0]` ug/mL FEU
2. **Disease YAML scenario flags** (`modules/disease/reference_data/`):
   - `causes_vte: true` on `pulmonary_embolism.yaml`, `deep_vein_thrombosis.yaml`,
     `cerebral_infarction.yaml` (3 diseases)
   - **Boundary decisions documented in section 3 (J1/J2)**:
     - `hemorrhagic_stroke.yaml` does NOT get `causes_vte`. Its D-dimer
       elevation comes from `coagulation_status` (intracerebral
       fibrinolysis activation), not from venous-thrombus-derived
       fibrin breakdown. The mechanism is different and the formula
       captures it via `coagulation_status` alone.
     - `cerebral_infarction.yaml` DOES get `causes_vte`. Mechanistically
       most cerebral infarctions are embolic (cardioembolic or
       large-artery thrombo-embolic), and clinically D-dimer behaves
       like VTE in those patients. The `vte` label is shorthand for
       "elevated D-dimer driven by clot generation + fibrinolysis",
       not strictly "venous origin".
3. **Scenario-flag wiring fix (improvement J5, same PR)**:
   - `derive_lab_values` call sites at `inpatient.py:1680`,
     `emergency.py:122`, `outpatient.py:148` will read the disease
     YAML's `causes_myocardial_injury` and `causes_vte` and pass both
     to `derive_lab_values`. Today only Pass-1 inpatient wires
     `myocardial_injury` — the other three sites pass nothing, so MI
     patients in the ED have no troponin upshift, and the new VTE
     flag would replicate the same silent gap if simply added to
     Pass-1 only.
4. **Locale code mapping** (`locale/{us,jp}/code_mapping_lab.yaml`):
   - US: `D_dimer: "30240-9"` (LOINC, NLM-verified)
   - JP: `D_dimer: "2B140"` (JLAC10, JSLM v137 verified —
     `D-Dダイマー / D-D dimer`)
5. **Authoritative code data** (`codes/data/`):
   - `loinc.yaml`: add `30240-9` with NLM-verified English (clean
     short form per TestLoincDisplay rule)
   - `jlac10.yaml`: add `2B140` with JCCLS-official Japanese `ja`
     (PR #76 enforcement; from JSLM v137 master)
6. **AD-59 invariant guard** (`tests/integration/test_individual_lab_isolation.py`):
   - Add a guard analogous to the Fibrinogen / Cl guards: pulmonary
     embolism patients now produce `RESULTED` D-dimer orders with
     physiologic values.
7. **Byte-diff invariant**: `Patient/Encounter/Condition/Medication*/
   Procedure/Imaging/Immunization/FamilyMemberHistory` NDJSONs must
   stay byte-identical vs master `b6bc8eab` @ p=2000 seed=42. Two
   exceptions:
   - **`Observation.ndjson`** changes (new D_dimer Observations across
     the seven disease cohorts).
   - **For the J5 fix**: ED MI patients gain higher troponin / CK-MB
     values, so existing Troponin/CK-MB Observations for those
     patients change too. This is an **intentional defect fix** —
     byte-diff cannot be asserted for those Observations. The
     non-Observation invariants still hold; the J5 fix is
     formula-only (no state mutation, no master-RNG draw change), so
     unrelated patients' cohorts remain identical.
8. **3-axis DQR** (US p ≥ 10000 + JP p ≥ 5000, seed=42):
   - Structural: refRange 100%, display≠code 100%, new
     LOINC/JLAC10 codes resolve
   - Clinical: PE/DVT/cerebral_infarction D-dimer p50 ≥ 4 (clinically
     positive); non-VTE cohort D-dimer p50 ≤ 1 (specificity); ED MI
     patients now show troponin upshift (J5 fix proof)
   - JP language: zero US Japanese leak, JP D-dimer display in
     Japanese, JLAC10 `ja` JCCLS-official
9. **Docs sync in same PR** (PR #79 lesson): README.md, README.ja.md,
   DESIGN.md (AD-59 entry extension only — no new ADR), `modules/physiology/README.md`,
   CLAUDE.md (only if a new guideline emerges), TODO.md.

### Out of scope (deferred)

- **Phase 2b — `on_anticoagulation` axis** (warfarin/heparin INR
  therapeutic-range modelling, I5). Currently `PT_INR` cannot represent
  the 2.0–3.0 therapeutic range of anticoagulated patients. The right
  scope for the next PR is a fresh brainstorming because three valid
  designs exist (patient attribute / scenario flag / state axis /
  medication-physiology coupling). Defer.
- **Adding `causes_vte` to non-VTE-spectrum DR-ordering diseases**:
  COPD exacerbation, AF-RVR, sepsis, acute_mi already order D-dimer at
  some probability; none of them get the flag. Their D-dimer rises only
  via `inflammation_level` (sepsis, AF) or `coagulation_status` (DIC).
  This is clinically correct — these are non-specific elevations, not
  VTE-driven.
- **D-dimer assay unit harmonization** (J3 already verified): US uses
  `< 0.50 ug/mL FEU` (Mayo / Tietz), JP uses `< 1.0 ug/mL FEU` (JCCLS
  2022). Both are FEU (fibrinogen equivalent units), not DDU. The unit
  in the YAML is already `ug/mL` for both; the cutoff difference is a
  laboratory-policy difference, not a unit mismatch. **No change needed
  in this PR**.

## 3. Existing-code improvements adopted (uniform rule applied)

Per the uniform rule "既存コードは所与でなく 4 軸で見直し、改善点を提案する"
(memory `feedback_propose_improvements_to_existing`):

| # | Improvement | 4-axis | This PR |
|---|---|---|---|
| **J1** | `causes_vte` boundary: hemorrhagic_stroke must NOT get the flag (mechanism is intracerebral fibrinolysis, captured by `coagulation_status` alone — not the VTE path). Document the boundary in the spec + a code comment so future contributors don't extend incorrectly. | clinical ◎ / concept ◎ | **adopted** (boundary documented above + a comment in the YAML for cerebral_infarction.yaml's flag) |
| **J2** | `causes_vte` includes `cerebral_infarction` because the D-dimer behavior is shared with VTE (clot generation + fibrinolysis), not because the clot is venous. Flag name reads as "VTE-spectrum D-dimer elevation". | clinical ◎ | **adopted** (flag scope expanded to embolic ischemic stroke, comment notes the mechanism) |
| **J3** | D-dimer unit (FEU vs DDU): verified US/JP both use FEU at different cutoffs. No code change. | data ◎ | **verified, no action** |
| **J5** | `derive_lab_values` scenario-flag wiring gap: `myocardial_injury` is only passed by `inpatient.py:559–560` (Pass-1 daily loop). The second inpatient call (`:1680`), `emergency.py:122`, and `outpatient.py:148` pass nothing — so MI patients in the ED have no troponin upshift today, and new `causes_vte` would silently miss the same call sites. | clinical ◎ / maintainability ◎ | **adopted** (single helper to read both flags from the disease YAML and pass both at all four call sites — formula-only, no state mutation, byte-diff invariant for unrelated patients) |

Deferred to follow-ups:
- **I5** `on_anticoagulation` axis → Phase 2b PR
- **I4 / I6 / I7** carried from PR #80 backlog

## 4. Design

### 4.1 Physiology formula (`physiology/engine.py:derive_lab_values`)

```python
def derive_lab_values(
    state: PhysiologicalState,
    sex: str,
    age: int,
    has_diabetes: bool = False,
    rng: np.random.Generator | None = None,
    hour: int = 6,
    myocardial_injury: bool = False,
    causes_vte: bool = False,   # NEW — VTE-spectrum D-dimer flag
) -> dict[str, float]:
    ...
    # In the existing Coag section (right after the Fibrinogen line),
    # add:
    #
    # D-dimer (ug/mL FEU). Baseline 0.3, age-adjusted (older patients run
    # slightly higher even without disease — well-documented), modestly
    # raised in inflammation (sepsis, infection) and DIC. The decisive
    # signal comes from `causes_vte`: PE/DVT/embolic stroke push D-dimer
    # to clinically positive 5-20 ug/mL territory. Clamp floor 0.15
    # (laboratory detection floor), ceiling 20 (assay upper limit).
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

Reference values from this formula at sample states:

| State | infl | coag | causes_vte | age | D-dimer |
|---|---|---|---|---|---|
| healthy 35 | 0.03 | 0 | False | 35 | ~0.32 |
| healthy 75 | 0.03 | 0 | False | 75 | ~0.45 |
| sepsis no DIC | 0.85 | 0 | False | 60 | ~0.77 (mildly elevated) |
| DIC severe | 0.85 | 1.0 | False | 60 | ~2.32 |
| PE, no DIC | 0.20 | 0.05 | True | 60 | ~4.52 |
| PE + sepsis-DIC | 0.85 | 0.8 | True | 60 | ~5.97 |

These bands match clinical expectation: VTE always >4 (positive),
sepsis without VTE often borderline, DIC alone can hit positive without
VTE, age elevates baseline.

### 4.2 Disease YAML metadata

Three additions, all with a one-line comment naming the mechanism:

```yaml
# pulmonary_embolism.yaml
causes_vte: true   # PE itself; clot generation + fibrinolysis → D-dimer ↑↑

# deep_vein_thrombosis.yaml
causes_vte: true   # DVT; same mechanism as PE

# cerebral_infarction.yaml
causes_vte: true   # Embolic ischemic stroke (cardioembolic / large-artery
                   # thrombo-embolic); D-dimer behaves like VTE. NOT for
                   # hemorrhagic_stroke (mechanism is intracerebral
                   # fibrinolysis, captured by coagulation_status alone).
```

Atrial fibrillation (AF-RVR) does NOT get the flag despite ordering
D-dimer (`{test: "D_dimer", probability: 0.40}`): AF orders D-dimer to
*screen* for embolic complications, but the disease itself is not the
embolic event. If a stroke happens (PE / cerebral_infarction), that
encounter's primary protocol carries `causes_vte`.

### 4.3 Scenario-flag wiring (J5 fix)

A single helper in `physiology/engine.py` consolidates flag extraction:

```python
def scenario_flags_from_protocol(protocol) -> dict[str, bool]:
    """Read all `derive_lab_values` scenario flags from a disease YAML.

    Centralizes the `getattr(protocol, "causes_X", False)` calls so a
    new flag added to `derive_lab_values` only needs wiring in ONE
    place — not at every call site across inpatient / emergency /
    outpatient.
    """
    if protocol is None:
        return {"myocardial_injury": False, "causes_vte": False}
    g = lambda name: bool(getattr(protocol, name, None) or
                          (protocol.get(name) if isinstance(protocol, dict) else False))
    return {
        "myocardial_injury": g("causes_myocardial_injury"),
        "causes_vte": g("causes_vte"),
    }
```

Call sites:
- `inpatient.py:559–560` (Pass-1 daily loop) — replace
  `myocardial_injury=mi_injury` with `**flags`
- `inpatient.py:566` (lagged variant of Pass-1) — same
- `inpatient.py:1680` (second lab path; investigate at implementation
  time what it is, then wire the flags consistently)
- `emergency.py:122` (`_true_labs` for ED scoring) — pass `**flags`
- `outpatient.py:148` (`_true_labs` for outpatient scoring) — pass
  `**flags`

The dict-style `**flags` spread is the right interface here because it
lets future flags reach all five sites with a single helper change.

### 4.4 Locale + code data

`locale/us/code_mapping_lab.yaml`:
```yaml
D_dimer: "30240-9"
```

`locale/jp/code_mapping_lab.yaml`:
```yaml
D_dimer: "2B140"
```

`codes/data/loinc.yaml` — add (verified at implementation time via
`https://clinicaltables.nlm.nih.gov/api/loinc_items/v3/search?terms=30240-9`):
```yaml
30240-9:
  en: "D-dimer"   # clean short form; full LONG_COMMON_NAME has [Mass/volume] which TestLoincDisplay rejects
  ja: "D ダイマー"
```

`codes/data/jlac10.yaml` — add (verified against JSLM v137 sheet
「分析物コード」, row `2B140 / D-Dダイマー / FDP Dダイマー / D-D dimer`):
```yaml
2B140:
  en: "D-D dimer"
  ja: "D-Dダイマー"
```

### 4.5 AD-59 invariant guard

In `tests/integration/test_individual_lab_isolation.py`:

```python
@pytest.mark.integration
def test_pe_individual_d_dimer_order_now_resulted():
    """pulmonary_embolism.yaml orders {test:"D_dimer", urgency:"stat"}
    at admission. After this PR's derive_lab_values extension D-dimer
    results with a positive (>4 ug/mL FEU) value driven by the new
    `causes_vte` scenario flag.

    Counterpart to the Cl (PR #78) and Fibrinogen (PR #80) guards:
    same AD-59 invariant exercised for the VTE-flag path."""
    scenario = ForcedScenario(disease_id="pulmonary_embolism",
                              count=3, severity="moderate")
    cfg = SimulatorConfig(random_seed=42, country="US")
    dataset = run_forced(scenario, cfg)
    for record in dataset.patients:
        dd = [o for o in record.orders
              if o.display_name == "D_dimer"
              and o.status == OrderStatus.RESULTED]
        assert dd, "PE patient must have ≥1 RESULTED D_dimer order"
        for o in dd:
            assert 4.0 <= o.result.value <= 20.0, \
                f"PE D-dimer should be clinically positive, got {o.result.value}"
```

### 4.6 Determinism and byte-diff invariant

vs master `b6bc8eab` @ p=2000 seed=42:

- **IDENTICAL** (sha256): Patient, Encounter, Condition, MedicationRequest,
  MedicationAdministration, Procedure, ImagingStudy, Immunization,
  FamilyMemberHistory.
- **CHANGED** (expected):
  - `Observation.ndjson`:
    - new D-dimer Observations for the seven D-dimer-ordering disease
      cohorts (count ≈ disease incidence × order probability)
    - **J5 fix side-effect**: ED MI patients now produce
      MI-grade Troponin / CK-MB instead of type-2 background, so the
      existing Troponin / CK-MB Observations for those patients
      change (intentional defect fix)
  - `DiagnosticReport.ndjson`: Coag DRs assembled with D-dimer **do
    not change** because LOINC 24373-3 Coag panel does not include
    D-dimer (it's individual). DRs may gain D-dimer Observation refs
    only if a broader future DIC panel (LOINC 48995-7) is registered.

### 4.7 Three-axis DQR

US p ≥ 10000 + JP p ≥ 5000, seed=42:

**Structural**:
- LOINC 30240-9 / JLAC10 2B140 resolve to authoritative display
- D-dimer Observations: 100% have referenceRange
- No `display == code` in new codings

**Clinical**:
- PE (I26) admit-day D-dimer p50 ≥ 4 ug/mL (clinically positive)
- DVT (I80) admit-day D-dimer p50 ≥ 4
- Cerebral_infarction (I63) admit-day D-dimer p50 ≥ 4
- Sepsis (A41) admit-day D-dimer p50 < 2 (non-specific elevation, not VTE-grade)
- Healthy / non-VTE outpatient D-dimer < 1 in ≥ 80% of samples
- **J5 fix evidence**: ED-route MI patients (`acute_mi` via emergency)
  show troponin p75 ≥ 10 ng/mL (was ~0.5 before fix)

**JP language**:
- US output: zero Japanese in D-dimer fields
- JP output: D-dimer Observation display in Japanese
- `jlac10.yaml` 2B140 `ja` is `D-Dダイマー` (not English abbreviation)

DQR script: `scratchpad/dqr_phase2a_vte_review.py` adapted from
`scratchpad/dqr_coag_panel_review.py`.

Output saved as `docs/reviews/2026-06-24-phase2a-vte-data-quality-review.md`.

### 4.8 Docs sync (in same PR — PR #79 lesson)

- `README.md` / `README.ja.md`: add a bullet for the VTE-spectrum
  D-dimer activation + the J5 fix.
- `DESIGN.md`: extend AD-59 entry (this is the second follow-up after
  Coag PR to use the AD-59 invariant for a new analyte).
- `clinosim/modules/physiology/README.md`: D-dimer added to the
  derivation table; scenario-flag table updated with `causes_vte`
  next to `causes_myocardial_injury`.
- `CLAUDE.md`: update the scenario-flag bullet to name
  `scenario_flags_from_protocol` as the canonical entry point.
- `TODO.md`: mark Phase 2a done; carry forward Phase 2b (on_anticoagulation)
  and I4/I6/I7.

## 5. Risks

- **J5 fix cascade**: changing ED Troponin values for MI patients
  changes their Observation count for `Troponin_I` / `CK_MB`. Since
  the existing `apply_coupling_rules` does NOT propagate troponin
  back into state, this is a **formula-only change** and unrelated
  patients' cohorts stay byte-identical. Mitigation: byte-diff
  script asserts non-Observation invariants and reports Observation
  delta separately.
- **`cerebral_infarction` D-dimer cutoff calibration**: if PE / DVT
  hit p50 ≈ 5 but cerebral_infarction lands at p50 ≈ 3.8, the +4.0
  flag bump may need to be 4.5 or 5.0. Mitigation: DQR is the
  calibration gate; adjust coefficient and re-run.
- **JP cohort size for VTE diseases**: PE / DVT are not high-incidence;
  the JP p=5000 DQR may see < 10 VTE cases. Acceptance thresholds use
  distribution stats (p50) with `n ≥ 5` minimum; cohort < 5 reported
  as N/A with US results carrying the verdict.

## 6. Open questions

- **Q1**: Should `acute_mi.yaml` also gain `causes_vte`? MI patients
  *can* throw clots (mural thrombus, but that's the etiology rather
  than a complication). **Resolution**: No. MI's D-dimer behavior is
  best modelled by the existing inflammation + coag axes (acute
  inflammatory response can lift D-dimer modestly without VTE).
  Adding the flag would create false-positive VTE territory in plain
  MI, defeating the specificity.

- **Q2**: Should the J5 fix include `outpatient.py:148` even though no
  outpatient encounter today carries `causes_myocardial_injury`?
  **Resolution**: Yes. Wiring is cheap, and any future outpatient
  acute presentation (e.g. unstable angina screen with delayed
  diagnosis) would benefit. Defending all four call sites costs ~5
  lines.

## 7. Implementation order (high-level)

To be expanded into a writing-plans plan in the next step:

1. Authoritative code data (LOINC 30240-9 + JLAC10 2B140 + locale
   mappings).
2. `causes_vte` scenario flag — extend `derive_lab_values` signature
   and add D_dimer derive (TDD per analyte).
3. Disease YAML scenario-flag additions (PE, DVT, cerebral_infarction).
4. J5 wiring fix — introduce `scenario_flags_from_protocol` and
   replace all five call sites.
5. AD-59 isolation invariant test extension.
6. Byte-diff invariant verification.
7. 3-axis DQR with calibration loop.
8. Full docs sync.
9. PR.
