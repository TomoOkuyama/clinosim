# Phase 3a: HAI WBC + CRP lift via `hai_flags_from_record` helper

**Date**: 2026-06-25
**Author**: Tomo Okuyama (with Claude Opus 4.7)
**Status**: APPROVED — ready for plan
**Predecessor**: PR #88 (modules/device) + PR #89 (modules/hai) — device + HAI 4-PR シリーズ Phase 2
**Successor candidates**: Phase 3b (antibiotic empirical → narrow + S/I/R + WBC/CRP decay), Phase 3c (mortality coupling, sepsis cascade Lactate / Plt / 体温 / SBP)

---

## 1. Motivation

After PR #89 (modules/hai), the synthetic EHR has HAI patients with:

- HAI Condition resource (ICD-10-CM + SNOMED dual-coded, JP WHO 4-char fold)
- Specimen + Observation + DiagnosticReport culture chain (reused from `_fhir_microbiology.py`)

…but the patient's **WBC and CRP are still driven only by baseline `inflammation_level`** from the underlying disease/encounter. A CLABSI bacteremia in a CHF patient or a VAP in a stroke patient shows the same baseline WBC ~9,000 / CRP ~30 mg/L as the matched non-HAI cohort. This is **clinical incoherence** — every CDC NHSN HAI is by definition an inflammatory event (≥48h after admission, with culture confirmation), so labs must reflect it.

Phase 3a closes this gap by reading the HAI events out of `record.extensions["hai"]` at **observation time** (BNP-pattern surgical, AD-57) and lifting the effective inflammation contribution to WBC + CRP for any patient who has reached HAI onset day.

### Scope decisions (from brainstorming 2026-06-25)

| Decision | Choice | Rationale |
|---|---|---|
| Magnitude calibration | **(C) HAI type 別 inflammation lift YAML 駆動** | CDC clinical severity 区別 (CLABSI/VAP 強 / CAUTI 中) を data-driven に。`modules/hai/reference_data/hai_lab_lift.yaml` 1 ファイル中央集約 |
| Onset timing | **(B) 2-day ramp + flat** | `lift_factor = min(1.0, max(0, days_since_onset) / 2.0)`。CRP 動態 ~48h で peak と臨床整合、formula 1 行追加 |
| Lift 合成方法 | **effective_infl 経路** | `effective_infl = min(1.0, infl + lift)` を既存 CRP/WBC 式に渡す。既存 cubic (CRP) + linear (WBC) 完全再利用、基礎炎症 + HAI で natural superposition |
| Clamp 上限 | **1.0** | CRP 上限 400 mg/L saturate、現実上限 ~500 と整合 |
| Helper call site | **5 sites 全部統一** | inpatient Pass-1 main + lagged + unknown-condition + ED + outpatient。ED/outpatient は `extensions["hai"]` 空で 0.0 自然帰結。Phase 2b medication_flags と同型 |
| Helper signature | **`hai_flags_from_record(record, encounter_id, current_day)`** | encounter object 全体不要、id だけで HAI を絞り込み + onset_date 比較 |
| Lift 対象 analyte | **WBC + CRP のみ** | Lactate / Plt / 体温 / SBP は Phase 3b/c 以降。YAGNI、scope title 厳守 |
| 複数 HAI 同時発症 | **max lift 採用** | 同一 encounter で >1 HAI は稀。加算は over-lift で CRP saturate → 弁別性 loss を防ぐ |
| 既存 inflammation cascade との関係 | **無干渉** | `state.inflammation_level` を変えないので line 188-205 (DIC / chronic-anemia coupling) は不発火 = Phase 3a scope 外、Phase 3b で扱う |

---

## 2. Architecture

```
┌─ Source (PR #89, unchanged) ─────────────────────────────────┐
│ modules/hai/enricher writes:                                 │
│   record.extensions["hai"] = [HAIEvent(hai_id,encounter_id,  │
│     hai_type, onset_date, ...)]                              │
└──────────────────────────────────────────────────────────────┘
                              ↓ read-only consume
┌─ Helper (新規) ──────────────────────────────────────────────┐
│ physiology.engine.hai_flags_from_record(                     │
│     record,           # CIFPatientRecord                     │
│     encounter_id,     # str                                  │
│     current_day,      # datetime.date                        │
│ ) -> dict[str, float]                                        │
│  └ {"hai_inflammation_lift": 0.0..0.35}                      │
│  └ 0.0 if no extensions["hai"] / no event for encounter      │
│        / current_day < onset_date                            │
│  └ otherwise: max(event.lift * ramp_factor for matching evt) │
└──────────────────────────────────────────────────────────────┘
                              ↓ {**flags} merge (5 sites)
┌─ Site: inpatient.py:579 (Pass-1 main) ──────────────────────┐
│ flags = {                                                    │
│   **scenario_flags_from_protocol(protocol),                  │
│   **medication_flags_from_context(...),                      │
│   **hai_flags_from_record(record, encounter.id, day_date),   │
│ }                                                            │
│ derive_lab_values(state, ..., **flags)                       │
└──────────────────────────────────────────────────────────────┘
                              ↓
┌─ derive_lab_values (新 kwarg) ──────────────────────────────┐
│ def derive_lab_values(state, ...,                            │
│                       hai_inflammation_lift: float = 0.0):   │
│   infl = state.inflammation_level                            │
│   effective_infl = min(1.0, infl + hai_inflammation_lift)    │
│   labs["CRP"] = 0.3 + 400 * effective_infl ** 3              │
│   if effective_infl <= 0.8:                                  │
│       labs["WBC"] = 7000 + effective_infl * 12000            │
│   else:                                                      │
│       labs["WBC"] = max(1500,                                │
│           7000 + 0.8 * 12000 - (effective_infl - 0.8)*30000) │
└──────────────────────────────────────────────────────────────┘
```

**Invariants**:
- **State unchanged** (BNP-pattern surgical, AD-57). No new `PhysiologicalState` field.
- **AD-16 preserved** — no master RNG impact; `hai_flags_from_record` is a deterministic peek (no RNG draw).
- **AD-59 preserved** — per-order sub-rng pattern intact; `hai_inflammation_lift` is a plain float kwarg.
- **scenario_flags + medication_flags helper pattern unchanged** (Phase 2a/b + J5 architecture). New parallel helper for HAI-driven coupling.
- **No new type** — reads existing `HAIEvent` only.

**Extended CLAUDE.md architecture rule** (extension of Phase 2b):

> Lab derivation now reads THREE flag dicts: `scenario_flags_from_protocol(protocol)` for disease-driven flags (`causes_vte`, `causes_myocardial_injury`), `medication_flags_from_context(patient, mar_today, day_into_stay)` for medication-driven flags (`on_warfarin`), and `hai_flags_from_record(record, encounter_id, current_day)` for HAI-driven flags (`hai_inflammation_lift`). Call sites merge all three via `**flags` to `derive_lab_values`. NEVER add a `flag=value` named argument directly at a call site — extend the appropriate helper instead. This prevents J5-style wiring defects (one call site reads the flag, others silently don't).

---

## 3. New helper: `hai_flags_from_record`

Location: `clinosim/modules/physiology/engine.py` (sibling of `scenario_flags_from_protocol` + `medication_flags_from_context`).

```python
def hai_flags_from_record(
    record,                      # CIFPatientRecord
    encounter_id: str | None,    # str | None — None routes (ED/outpatient pre-HAI) return 0.0
    current_day,                 # datetime.date | None — None returns 0.0
) -> dict[str, float]:
    """Detect HAI-driven inflammation lift from extensions["hai"] context.

    Centralizes the HAI → lab coupling reads so a new HAI lift type added to
    `derive_lab_values` only needs wiring in ONE place — same J5-prevention
    rationale as `scenario_flags_from_protocol` / `medication_flags_from_context`.
    Dict keys match `derive_lab_values` parameter names so callers can spread
    with `**flags`.

    Returns 0.0 lift when:
      - record has no extensions["hai"] (HAI module disabled or non-HAI patient)
      - encounter_id is None
      - current_day is None
      - no HAI event matches encounter_id
      - all matching events have onset_date > current_day (pre-onset)

    Otherwise: returns max(event.lift_value × ramp_factor) over matching events.
      - ramp_factor = min(1.0, max(0, days_since_onset) / ramp_peak_days)
      - lift_value resolved from hai_lab_lift.yaml by hai_type
    """
```

**Detection algorithm**:

1. `events = record.extensions.get("hai", [])` — short-circuit `[]` returns `{"hai_inflammation_lift": 0.0}`
2. `matching = [e for e in events if e.encounter_id == encounter_id]` — encounter scope filter
3. For each matching event:
   - `days_since_onset = (current_day - parse(e.onset_date)).days`
   - skip if `days_since_onset < 0` (pre-onset)
   - `ramp_factor = min(1.0, days_since_onset / ramp_peak_days)`  # 2 by default
   - `lift_value = hai_lift_config[e.hai_type]`  # from YAML
   - `effective_lift = lift_value * ramp_factor`
4. Return `{"hai_inflammation_lift": max(effective_lifts, default=0.0)}`

**Config loader** (cached):

```python
@lru_cache(maxsize=1)
def _load_hai_lift_config() -> tuple[float, dict[str, float]]:
    """Return (ramp_peak_days, {hai_type: lift_value})."""
    path = Path(clinosim.modules.hai.__file__).parent / "reference_data/hai_lab_lift.yaml"
    data = yaml.safe_load(path.read_text())
    return float(data["ramp_peak_days"]), dict(data["hai_lift"])
```

---

## 4. `derive_lab_values` change

Single new kwarg added with default `0.0`. Modifies CRP + WBC blocks only.

```python
def derive_lab_values(
    state: PhysiologicalState,
    sex: str,
    age: int,
    *,
    has_diabetes: bool = False,
    causes_myocardial_injury: bool = False,
    causes_vte: bool = False,
    on_warfarin: bool = False,
    hai_inflammation_lift: float = 0.0,   # ← new
    hour: int = 8,
) -> dict[str, float]:
    ...
    infl = state.inflammation_level
    effective_infl = min(1.0, infl + hai_inflammation_lift)  # ← new

    # CRP: now uses effective_infl
    labs["CRP"] = 0.3 + 400 * effective_infl ** 3

    # WBC: now uses effective_infl
    if effective_infl <= 0.8:
        labs["WBC"] = 7000 + effective_infl * 12000
    else:
        labs["WBC"] = max(1500, 7000 + 0.8 * 12000 - (effective_infl - 0.8) * 30000)
    ...
```

**Critical invariant** — all OTHER analytes continue to read `state.inflammation_level` **directly** (not `effective_infl`). HAI lift is **scoped to WBC + CRP only**. This keeps Phase 3a YAGNI strict and preserves the following analytes/derivations for Phase 3b/c surgical extension:

| Reads `state.inflammation_level` directly (unchanged) | Where |
|---|---|
| Fibrinogen biphasic (acute-phase ↑) | physiology.engine line ~446 |
| pO2 (lung-injury proxy) | line ~507 |
| Ca depression (sepsis) | line ~525 |
| Temperature (fever) | line ~595 |
| SBP/DBP (distributive hypotension) | line ~613 |
| DIC coupling cascade | line ~187 |
| Chronic anemia coupling | line ~199 |

These will be revisited in Phase 3c as part of the sepsis cascade extension, but staying off them in Phase 3a is what guarantees the clean byte-diff (only WBC + CRP shift).

---

## 5. YAML config: `hai_lab_lift.yaml`

Location: `clinosim/modules/hai/reference_data/hai_lab_lift.yaml`

```yaml
# Phase 3a: HAI WBC + CRP lift via inflammation_level offset
# Reads at observation time by physiology.engine.hai_flags_from_record.
# CDC NHSN clinical severity proxy:
#   CLABSI = bacteremia (strong systemic response)
#   VAP    = severe pneumonia (strong systemic response)
#   CAUTI  = urinary tract (moderate, often localized)
ramp_peak_days: 2

hai_lift:
  CLABSI: 0.35
  VAP:    0.35
  CAUTI:  0.20
```

**Calibration rationale** (CRP, with baseline infl = 0.4 typical inpatient):
- baseline alone: `0.3 + 400 * 0.4^3 ≈ 26 mg/L`
- baseline + CLABSI/VAP lift 0.35 → effective 0.75 → `0.3 + 400 * 0.75^3 ≈ 169 mg/L` ✓ (typical bacteremia / severe pneumonia)
- baseline + CAUTI lift 0.20 → effective 0.60 → `0.3 + 400 * 0.6^3 ≈ 86 mg/L` ✓ (典型的 UTI 上昇)

**Calibration rationale** (WBC, baseline infl = 0.4):
- baseline alone: `7000 + 0.4 * 12000 = 11,800` (上昇傾向)
- + CLABSI/VAP 0.35 → effective 0.75 → `7000 + 0.75 * 12000 = 16,000` ✓
- + CAUTI 0.20 → effective 0.60 → `7000 + 0.6 * 12000 = 14,200` ✓

---

## 6. Wiring: 5 call sites

All sites mutate `flags` dict, never add `flag=value` directly.

### 6.1 `clinosim/simulator/inpatient.py:579` (Pass-1 main)

```python
flags = {
    **scenario_flags_from_protocol(protocol),
    **medication_flags_from_context(patient, all_orders, admission_date, day_into_stay),
    **hai_flags_from_record(record, encounter.id, day_date),  # ← new
}
true_labs = derive_lab_values(state, sex=patient.sex, age=patient.age,
                              has_diabetes=has_diabetes, hour=lab_hour, **flags)
```

### 6.2 `clinosim/simulator/inpatient.py:585` (Pass-1 lagged for Cr/BUN lag)

Same `flags` reused (lagged is the same calendar day, just 6h-lag state). No new merge needed.

```python
lagged_labs = derive_lab_values(lagged_state, sex=patient.sex, age=patient.age,
                                has_diabetes=has_diabetes, hour=lab_hour, **flags)
```

### 6.3 `clinosim/simulator/inpatient.py:1706` (unknown-condition Pass-1)

```python
_flags_unknown = {
    **scenario_flags_from_protocol(protocol),  # protocol = None → empty dict
    **medication_flags_from_context(patient, None, None, None),  # chronic-meds-only path
    **hai_flags_from_record(record, encounter.id, day_date),  # ← new
}
true_labs = derive_lab_values(state, sex=patient.sex, age=patient.age,
                              has_diabetes=has_diabetes, **_flags_unknown)
```

### 6.4 `clinosim/simulator/emergency.py:134` (ED encounter)

```python
_flags = {
    **scenario_flags_from_protocol(protocol),
    **medication_flags_from_context(patient, None, None, None),
    **hai_flags_from_record(record, _encounter_id, _visit_date),  # ← new, naturally 0.0
}
_true_labs = derive_lab_values(_state, sex=patient.sex, age=patient.age,
                               has_diabetes=_has_dm, **_flags)
```

ED は HAI 不発生(modules/hai は inpatient ICU-stay 限定) → `extensions["hai"]` filter で `[]` → `{"hai_inflammation_lift": 0.0}` 自然帰結。

### 6.5 `clinosim/simulator/outpatient.py:163` (Outpatient followup)

```python
_flags = {
    **scenario_flags_from_protocol(protocol),
    **medication_flags_from_context(patient, None, None, None),
    **hai_flags_from_record(record, _encounter_id, _visit_date),  # ← new, naturally 0.0
}
_true_labs = derive_lab_values(_state, sex=patient.sex, age=patient.age,
                               has_diabetes=_has_dm, **_flags)
```

Outpatient followup の visit_date は HAI onset 後の十分後だが encounter_id mismatch で 0.0 帰結。Phase 3b で「過去 HAI の SSI 再診」を扱う際は別軸で追加(現状 scope 外)。

---

## 7. Tests (TDD)

### 7.1 Unit tests for `hai_flags_from_record` (新規)

Location: `tests/unit/test_hai_flags_from_record.py`

| Case | Setup | Expected `hai_inflammation_lift` |
|---|---|---|
| No extensions["hai"] | record without HAI key | 0.0 |
| Empty list | extensions["hai"] = [] | 0.0 |
| HAI in different encounter | extensions["hai"] = [HAIEvent(encounter_id="OTHER", ...)] | 0.0 |
| HAI matched, pre-onset | onset_date = day + 1 | 0.0 |
| HAI matched, onset day (day 0) | days_since_onset = 0 | 0.0 (ramp_factor = 0/2 = 0.0) |
| HAI matched, day 1 (mid-ramp) | days_since_onset = 1 | lift * 0.5 = 0.175 (CLABSI) |
| HAI matched, day 2+ (full lift) | days_since_onset = 2 | lift * 1.0 = 0.35 (CLABSI) |
| Multi-day (day 7) | days_since_onset = 7 | lift * 1.0 = 0.35 (flat, no decay in Phase 3a) |
| CAUTI lift value | hai_type = "CAUTI", day 2+ | 0.20 |
| VAP lift value | hai_type = "VAP", day 2+ | 0.35 |
| Multiple HAI same encounter | CLABSI day 2 + CAUTI day 2 | max(0.35, 0.20) = 0.35 |
| encounter_id None | encounter_id=None | 0.0 |
| current_day None | current_day=None | 0.0 |

### 7.2 Unit tests for `derive_lab_values` HAI lift (新規)

Location: `tests/unit/test_derive_lab_values_hai.py`

All numbers computed from the formulas in §4. WBC has a post-peak descending leg above effective_infl=0.8 (immune exhaustion).

| Case | infl | lift | effective_infl | CRP (mg/L) | WBC |
|---|---|---|---|---|---|
| Baseline (no HAI) | 0.4 | 0.0 | 0.4 | 25.9 | 11,800 |
| Baseline + CLABSI/VAP full | 0.4 | 0.35 | 0.75 | 169.0 | 16,000 |
| Baseline + CAUTI full | 0.4 | 0.20 | 0.60 | 86.7 | 14,200 |
| Mid-baseline + CLABSI mid-ramp | 0.4 | 0.175 (day 1) | 0.575 | 76.3 | 13,900 |
| Clamp boundary (high infl + max lift) | 0.8 | 0.35 | clamp → 1.0 | 400.3 | 10,600 |
| High-infl baseline (no HAI) for comparison | 0.95 | 0.0 | 0.95 | 343.2 | 12,100 |
| High-infl + lift (descending leg) | 0.95 | 0.35 | clamp → 1.0 | 400.3 | 10,600 |
| Zero infl + CLABSI | 0.0 | 0.35 | 0.35 | 17.4 | 11,200 |

Note: The high-infl + lift case **decreases WBC** vs the same baseline alone — this is the intentional immune-exhaustion curve baked into the existing formula (sepsis-late leukopenia). Phase 3a does not alter this behavior.

### 7.3 Integration test — wiring isolation (J5 prevention)

Location: `tests/integration/test_hai_lift_wiring.py`

- Build minimal CIF with HAIEvent on encounter X day 2+ → call all 5 derive_lab_values sites with appropriate state → assert CRP/WBC all reflect lift in inpatient sites
- Same record, ED encounter Y (no HAI) → assert ED CRP/WBC NOT lifted
- Same record, outpatient encounter Z → assert outpatient CRP/WBC NOT lifted (encounter_id mismatch)
- Assert all 5 sites import `hai_flags_from_record` (grep `_meta` test from Phase 2b precedent)

### 7.4 Integration test — clinical relative-delta (1 simulation)

Location: `tests/integration/test_hai_lift_clinical.py`

- US p=2000 seed=42 with hai module enabled
- HAI cohort (extensions["hai"] non-empty) vs non-HAI inpatient cohort
- Assert: HAI cohort CRP p50 > non-HAI CRP p50 + 20 mg/L
- Assert: HAI cohort WBC p50 > non-HAI WBC p50 + 1500

---

## 8. byte-diff expectations

Tool: `scratchpad/phase3a_byte_diff.py` (Phase 2b/2a 同型)

Compare master `42657293` vs branch at US/JP p=2000 seed=42:

| NDJSON | Expected delta | Reason |
|---|---|---|
| Patient | **IDENTICAL** | main RNG 不動 |
| Encounter | **IDENTICAL** | 同上 |
| Condition | **IDENTICAL** | HAI Condition は前 PR で発症済 |
| MedicationRequest | **IDENTICAL** | 同上 |
| MedicationAdministration | **IDENTICAL** | 同上 |
| Procedure | **IDENTICAL** | 同上 |
| ImagingStudy | **IDENTICAL** | 同上 |
| Immunization | **IDENTICAL** | enricher 出力不変 |
| FamilyMemberHistory | **IDENTICAL** | 同上 |
| Device | **IDENTICAL** | PR #88 出力不変 |
| DeviceUseStatement | **IDENTICAL** | 同上 |
| Specimen | **IDENTICAL** | culture chain 不変 |
| DiagnosticReport | **IDENTICAL** | DR は Observation ID 参照のみ(Phase 2b で実証) |
| Observation | **same-count shift** | WBC + CRP only — HAI 発症 cohort のみ数値 shift、他 analyte は state.inflammation 直読で不動 |

Phase 2b PT_INR と同型の clean byte-diff(13/14 NDJSON IDENTICAL + Observation same-count shift)を期待。

---

## 9. 3-axis DQR acceptance criteria

Tool: `scratchpad/phase3a_dqr.py` (Phase 2b 同型)

Run at US p=10000 + JP p=5000, seed=42, hai module enabled.

### 9.1 構造的品質

| Check | Acceptance |
|---|---|
| WBC + CRP refRange 100% | PASS |
| WBC + CRP interpretation 100% | PASS |
| LOINC 6690-2 (WBC) + 1988-5 (CRP) 不変 | PASS |
| JLAC10 2A020 (WBC) + 5C070 (CRP) 不変 | PASS |
| display ≠ code 100% | PASS |
| reference integrity (no orphan refs) | PASS |

### 9.2 臨床整合 (relative-delta)

HAI 発症 = `extensions["hai"]` non-empty かつ encounter 中の admit_day >= onset_date + 2(full lift)で観測された WBC/CRP。

Threshold は §7.2 unit-test calibration から導出(baseline infl=0.4 で CLABSI/VAP の theoretical delta = +143 mg/L CRP / +4,200 WBC、CAUTI = +61 / +2,400)。cohort p50 は mid-ramp + 多様な baseline infl で薄まるため、acceptance は theoretical の ~50% に conservative 設定:

| HAI type | WBC p50 vs non-HAI baseline | CRP p50 vs non-HAI baseline | Stretch goal (p75 / p90) |
|---|---|---|---|
| CLABSI | delta ≥ +3,000 | delta ≥ +50 mg/L | CRP p75 ≥ 120 |
| VAP | delta ≥ +3,000 | delta ≥ +50 mg/L | CRP p75 ≥ 120 |
| CAUTI | delta ≥ +1,500 | delta ≥ +25 mg/L | CRP p75 ≥ 60 |

**Rare-event acceptance** (memory `feedback_pr_merge_dqr_required` + 本 session 学習):
- JP p=5000 では HAI 発症 0 件もあり得る(Poisson tail、P(X=0) ≈ 0.71)。その場合 JP 臨床整合 axis は "N/A — too few HAI events for delta analysis" として受容、US p=10000 cohort で gate
- US p=10000 でも CLABSI/VAP は各 1-3 件想定(CDC NHSN baseline 0.001/day)。cohort-level p50 は HAI-type 横断(CLABSI + VAP merged)で計算可
- 高 baseline infl 患者(state.inflammation 既に 0.8+)の HAI lift は WBC を **下げる**(immune-exhaustion 曲線、§7.2 表参照)= cohort p50 calc から outlier として除外せず、全 HAI 患者で aggregate(臨床的に正しい挙動)

### 9.3 JP 言語

| Check | Acceptance |
|---|---|
| US output 日本語混入 0 | PASS |
| JP WBC display 日本語(白血球数 等)| 既存維持 |
| JP CRP display 日本語(C反応性蛋白 等)| 既存維持 |
| JP 全 Condition / Procedure display 日本語 | 既存維持 |
| JP CM-granular ICD leak 0 | 既存維持 |

---

## 10. Docs sync (本 PR 同梱)

| Doc | 変更 |
|---|---|
| `CLAUDE.md` | "AD-55 enricher patterns" に hai_flags_from_record helper を追加(scenario_flags + medication_flags + hai_flags の 3-helper merge pattern 明示) |
| `MODULES.md` | hai module の Consumers に "physiology.engine (Phase 3a observation-time lift)" 追加 |
| `SCENARIO_FLAGS.md` | "All current flags" に `hai_inflammation_lift` 追加、helper architecture に hai_flags_from_record 追加、"Adding a new flag" guide を 3-helper merge pattern に更新 |
| `clinosim/modules/hai/README.md` | "Phase 3a" section 追加(observation-time consume pattern + WBC/CRP lift) |
| `clinosim/modules/physiology/README.md` | 新 helper `hai_flags_from_record` を public API に追加 |
| `DESIGN.md` | AD-55 entry の "Phase 3" mention 更新、必要なら新 ADR は不要(AD-57 BNP-pattern surgical の 4 例目で entry に一行追記) |
| `TODO.md` | Phase 3a 完了 mark、Phase 3b(antibiotic / S/I/R / decay)を新 entry に |
| `docs/reviews/2026-06-25-phase3a-hai-lab-lift-data-quality-review.md` | 3-axis DQR 結果記録(PR evidence) |
| `scratchpad/phase3a_byte_diff_results.md` | byte-diff 結果記録 |

---

## 11. Out of scope (Phase 3b/c に保留)

| 項目 | 理由 |
|---|---|
| antibiotic empirical → narrow | Phase 3b 本命、scope 大(empirical 選択 + culture-driven narrowing + S/I/R + dosing) |
| susceptibility S/I/R 詳細モデル | 同上(culture chain を拡張、organism-antibiotic matrix YAML 駆動) |
| WBC/CRP decay(抗菌薬反応) | antibiotic empirical と coupled なので Phase 3b 同 PR |
| mortality 影響(HAI → outcome_benchmarks) | Phase 3c、outcome benchmarks 連動は感度高い修正 |
| Lactate / Plt / 体温 / SBP sepsis cascade | Phase 3c、scope 大(BNP-pattern surgical の 4-5 analyte 同時、各 analyte 個別 calibration 必要) |
| ED/outpatient での過去 HAI 再診(SSI 等) | Phase 3 全体外、別軸(encounter chain 機構) |
| HAI による在院日数延長 | clinical_course YAML 駆動の構造変更が必要、別 PR スコープ |
| decay phase の YAML 化 | 抗菌薬反応 + decay は coupled に Phase 3b で同時実装 |

---

## 12. Design pivot (2026-06-25, mid-execution)

実装中に重要な前提誤りを発見:現状 `modules/device` + `modules/hai` は `POST_RECORDS` stage 登録 = **全 patient の全 encounter 生成が終わった後**に走るため、daily loop 内の `derive_lab_values` 時点で `extensions["hai"]` は常に空。spec §2 の前提「helper が `extensions["hai"]` を read-only consume」は post_records 設計のままでは成立しない。

### 採用 pivot: B-2 v3 = POST_ENCOUNTER stage(daily loop **直後** 走) + forward-delta lift

実装中に **二段階の発見** があった:
1. (第一発見)device + hai は POST_RECORDS で全 patient 完了後に走るため、daily loop 内 `derive_lab_values` 時点で `extensions["hai"]` は空。
2. (第二発見)device + hai の sampling は **clinical course の outcome に依存**(`record.icu_transferred` は ICU 転送の有無 = daily loop 中の disease severity 進行で確定、GCS / perfusion_status / respiratory_fraction も daily loop の state 派生)。よって device + hai は loop の **前** には走れない。

正しい timing は **「daily loop 完了直後 + 最終 CIFPatientRecord 返却前」**。これを `POST_ENCOUNTER` の semantics として定義する。

### 採用 pivot: B-2 v3 = enricher framework に POST_ENCOUNTER stage を追加

| 設計点 | 採用 | 4 軸根拠 |
|---|---|---|
| enricher stage 構成 | `POST_RECORDS` に加え新規 `POST_ENCOUNTER` を追加 | コンセプト ◎(forward-derivation 哲学整合、post-hoc CIF mutation 回避)、メンテ ◎(Phase 3b/c の足場)、データ品質 ◎(formula forward 評価、逆算なし)|
| device + hai migrate | `POST_RECORDS` → `POST_ENCOUNTER` | encounter-bound semantics に正分類、Phase 2 の post_records 配置は実は Phase 3 の lab consume を見越していなかった結果 |
| 呼出 hook | `simulator/inpatient.py` で daily loop 完了直後、最終 record 返却前に `run_stage(POST_ENCOUNTER, ...)` を呼ぶ | device + hai は full clinical course outcome に依存できる、HAI events が見える状態で次の lift step が走る |
| HAI lift 適用方式 | **forward-delta**: `_apply_hai_lab_lift(record, encounter, state_history)` が state_history(daily loop が保存)を使って WBC + CRP の各 obs で `delta = derive(state, lift>0) - derive(state, lift=0)` を計算 → 既存 obs.value_numeric に加算 | A 案の逆算 noise loss を回避、forward formula 数学整合、既存 noise + circadian 保持 = byte-diff も「HAI cohort obs.value_numeric のみ change」で clean |
| AD-55 Module 分類 refine | "encounter-bound Module"(device/hai, post-loop sampling)vs "cross-record Module"(immunization/family_history/code_status/care_level/sdoh, post-everything walk)| 将来 Module 追加時の判断軸が明示。Phase 3b/c の antibiotic empirical / sepsis cascade も同じ POST_ENCOUNTER + delta pattern で清潔に拡張可 |

**byte-diff invariant 維持の根拠**: device + hai enricher の per-patient sub-seed は `derive_sub_seed(master_seed, ENRICHER_SEED_OFFSETS[name], patient_id)` で導出され、enricher の **走るタイミングが変わっても sub-seed は不変** = same RNG sequence → same device placements + same HAI events。違いが出るとすれば `_id` 生成が encounter 巡回順に依存する場合のみ(現状 hai_id は encounter_id + hai_type + counter で構成、device_id も encounter-scoped → 安定)。

### 却下案

- **A 案(enricher 内 post-hoc lift)**: 逆算 noise loss + Phase 3b/c で post-hoc mutation 連鎖 → メンテ性 / コンセプト適切性で劣る
- **B-1 案(state snapshot を CIF type に保存)**: forward 数学整合は得られるがメモリ 5% 増 + CIF type 変更 + 既存 test 影響 → 過剰投資
- **B-3 lite 案(framework 介さず直接呼出)**: pragmatic だが「enricher は inpatient.py が直接呼ぶ」前例が pattern を崩す

### 既存 spec sections への影響

- §2 architecture: アーキ図は **新規 forward-delta path に置換**:
  - 旧: `extensions["hai"]` → `hai_flags_from_record` → derive_lab_values 5 sites
  - 新: daily loop → state_history → POST_ENCOUNTER (device → hai) → `_apply_hai_lab_lift` (forward delta via derive_lab_values)
- §3 helper(`hai_flags_from_record`): **未使用に変化**(Phase 3a で wire しない)。Phase 3b/c で antibiotic_flags_from_record などの sibling と共に再利用候補。本 PR では実装維持 + 13 unit tests も維持(将来再利用の primitive)
- §4 derive_lab_values: **不変**(kwarg は `_apply_hai_lab_lift` 内部で forward 評価に使われる、5 site wire しない)
- §5 YAML: 不変
- §6 wiring (5 sites): **削除**(forward-delta 設計では derive_lab_values 5 site の wire は不要)。J5 prevention は別の statemic guard(全 derive sites を wire しないが、新 `_apply_hai_lab_lift` 呼出は 1 ヶ所のみ)
- §8 byte-diff: device + hai migrate による NDJSON 差異の予想を refine — Patient/Encounter/Condition/MedReq/MedAdmin/Procedure/Imaging/Immunization/FamilyHistory/**Device/DeviceUseStatement/HAI Condition/Specimen/DiagnosticReport** は IDENTICAL を期待(per-patient sub-seed 同一、device + hai outcomes 同一)、Observation のみ HAI cohort の WBC + CRP が delta shift
- §10 docs sync: AD-55 / AD-56 の "encounter-bound vs cross-record Module" 分類を追加、`CLAUDE.md` "AD-55 enricher patterns" に POST_ENCOUNTER stage 説明追加、`_apply_hai_lab_lift` 設計を physiology/README に

## 13. Open questions

なし。設計確定(B-2 採用、2026-06-25 mid-execution pivot)。

---

## 13a. Post-PR-90 xhigh review hardening (2026-06-25 second pass)

PR #90 was opened with **byte-diff 37/37 IDENTICAL + 3-axis DQR PASS + 691 tests** — but a workflow-backed xhigh code review caught **13 confirmed + 2 plausible bugs**. The critical one: YAML hai_type keys were UPPERCASE (`CLABSI`/`VAP`/`CAUTI`) while the enricher writes lowercase (`clabsi`/`cauti`/`vap`), so `lift_table.get` always returned 0.0 — **the entire Phase 3a lift was a silent no-op in production**, and the DQR's +2,135 WBC / +50.4 CRP CAUTI delta was a confounder of UTI disease state, not the lift code.

### Why all three gates missed it

| Gate | Why it missed |
|---|---|
| Unit + integration tests | Constructed HAIEvent with UPPERCASE by hand, accidentally matching the YAML; the enricher path was never driven end-to-end. |
| byte-diff at p=2000 | HAI is Poisson rare (~0 events at p=2000) → the lift code never ran. |
| 3-axis DQR at p=10k | The CAUTI cohort delta vs non-HAI baseline looked plausible, but UTI patients have elevated WBC + CRP regardless — the metric was confounded with disease state, not pinned to the lift formula. |

### Fixes applied (commit `4dd36a55`)

| # | Severity | Fix |
|---|---|---|
| 1 | critical | `modules/hai/__init__.HAI_TYPES = ('clabsi','cauti','vap')` single source of truth; YAML keys lowercased; `load_hai_lab_lift_config` validates keys against `HAI_TYPES` at import → raises on mismatch. |
| 2 | high | Multi-event lift = `max(effective_lift)` over matching events (not sum). Refactored to iterate observations first, then find the best lift across events. |
| 3 | high | `state_history[day_index + 1]` (post-day-N state — index 0 is admission). |
| 4 | high | `obs.flag` recomputed via `determine_flag` after lift. |
| 5 | medium | `round_to_precision(lab_name, ...)` so WBC stays integer. |
| 6 | medium | Draw hour from `order.ordered_datetime`, not `obs.result_datetime`. |
| 7 | high | Snapshot-date truncation runs again after POST_ENCOUNTER to drop HAI events + cultures past snapshot. |
| 8 | critical | `run_forced` calls `register_builtin_enrichers()` so `clinosim test-disease` actually fires the POST_ENCOUNTER stage. |
| 9 | critical | Removed the 29-line dead POST_ENCOUNTER block from `_simulate_unknown_condition` (icu_transferred never set there). |
| 10 / 11 / 13 / 15 | medium | `hai_flags_from_record` deleted (dead code, module-boundary violation, type contract conflict — all gone at once). |
| 12 | medium | `_hai_lift_delta` closed-form (~10 lines) replaces double-`derive_lab_values` (30+ analyte pipeline). |
| 14 | high | Closed-form approach makes the recompute moot — only WBC + CRP need re-evaluation, no scenario / medication flags involved. |

### New regression guards

- `tests/integration/test_hai_lab_lift.py` rewritten (13 cases) — pins state_history index, multi-event max, draw-hour, integer precision, flag recompute, YAML integrity, and closed-form-vs-derive_lab_values equivalence.
- `tests/integration/test_hai_forced_e2e.py` new — drives the actual enricher path through `run_forced` and asserts the POST_ENCOUNTER registry has `device` + `hai`. Catches the Finding 8 class of bug.

### Audit-script strengthening (next-session backlog)

The DQR script's CAUTI delta acceptance is **confounded with disease state** (UTI patients have elevated WBC + CRP regardless). To catch the silent-no-op class of bug at the gate, the DQR should:
- Cross-verify hai_type strings against `HAI_TYPES` and fail loudly if any unexpected key appears in the cohort.
- Compute the **theoretical** lift from `_hai_lift_delta` per affected obs and assert observed-minus-baseline ≥ theoretical-minus-baseline × 0.5 (not just a baseline-vs-cohort gap which can come from disease state alone).
- Add a "lift fired" counter that the DQR prints — zero indicates the lift code is a no-op even when the cohort shows a positive delta.

These are filed in `[[project_realism_gaps]]` as "DQR script strengthening" and recorded in PR #90's TODO follow-up.

---

## 14. References

- Phase 2a spec: `docs/superpowers/specs/2026-06-24-phase2a-vte-d-dimer-design.md`
- Phase 2b spec: `docs/superpowers/specs/2026-06-24-phase2b-on-anticoagulation-design.md`
- HAI module spec: `docs/superpowers/specs/2026-06-24-hai-module-design.md`
- AD-55 / AD-56 / AD-57: `DESIGN.md`
- CDC NHSN HAI definitions: https://www.cdc.gov/nhsn/psc/
- LOINC 6690-2 (WBC) / 1988-5 (CRP): NLM
- JLAC10 2A020 (WBC) / 5C070 (CRP): JSLM v137
