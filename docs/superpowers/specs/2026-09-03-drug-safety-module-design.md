# drug_safety module — design spec

- **Status**: Draft (awaiting user review)
- **Date**: 2026-09-03
- **Owner**: session 99
- **Tracks**: Issue #1066 (B1 contraindication gate) — primary driver.
  Adjacent issue tie-ins noted per section (#1074 progress note density,
  Issue #437 dead-data revive).
- **Anticipated release**: v0.6.0 (MINOR bump per
  `feedback_versioning_policy_cif_narrative_consistency` — CIF field
  additions + RNG shape change from candidate substitution).

## 1. Purpose

Introduce a **drug-safety gate** that prevents contraindicated
medication co-prescriptions from appearing in generated CIF/FHIR
records, matching how a real EHR CPOE (Computerized Physician Order
Entry) system suppresses them at order-entry time. Where the current
sim emits ~150 contraindicated pairs per 10,000 US patients
(warfarin+aspirin 98, warfarin+NSAID 52, β-blocker+non-DHP CCB 7,
ACEi+K supplement 3 — measured on p=10000 seed=500), the fix reduces
that count to zero via a **class-based** rule engine invoked from
`order` and `patient` modules, with **alternative drug substitution**
for indication-known cases and **narrative surfacing** of the
avoidance reasoning across both template and LLM narrative pipelines.

## 2. Scope

### In scope (MVP)

1. New `clinosim.modules.drug_safety` foundation-layer library:
   - `check_pair`, `check_candidate_against_active`, `suggest_alternative` API
   - `SafetyVerdict` dataclass (severity + rationale EN/JA + rule_id + matched_classes)
   - YAML-driven drug taxonomy (`drug_classes.yaml`) + rule set (`contraindications.yaml`)
2. Contraindication rule set covering the 4 pair classes causing the
   ~150 defects, plus ~10 additional well-established
   contraindications (target: ~15 rules total).
3. Alternative drug substitution:
   - Revive 4 dead-data blocks in existing disease YAML
     (`alternative_penicillin_allergy`, `alternative_beta_blocker_contraindicated`,
     `mrsa_coverage`, `hyperkalemia_management`) — closes Issue #437 sibling scope.
   - New `locale/shared/drug_substitution.yaml` for generic
     indications (pain_management, prophylactic_anticoag, etc.).
4. Caller integration:
   - `order.engine._emit_medication_order` (acute MR emission)
   - `patient.activator._derive_home_medications` (chronic med chain)
5. CIF trace field: `PatientRecord.safety_skip_log: list[SafetySkipEntry]`
   carrying (candidate, active_conflict, verdict, substituted_with,
   context_hint) — sim-internal, never emitted to FHIR structured
   resources.
6. Narrative integration — all 4 layers:
   - **Layer 1 (Context)**: `NarrativeContext.safety_skips` field +
     `build_narrative_context` extension.
   - **Layer 2 (Template)**: `template_generator.py` +
     `_chronic_soap.py` A&P section renderers surface avoidance +
     substitution.
   - **Layer 3 (Production LLM)**: `narrative_seed_bundle.yaml`
     (`en` + `ja`) user_template + system-prompt guidance.
   - **Layer 4 (Reserved prompts)**: `admission_hp.yaml`,
     `discharge_summary.yaml`, `death_discharge_summary_treatment_course.yaml`
     synced (`en` + `ja` each) for future audit-doc consistency.
7. FHIR surface (limited):
   - `MedicationRequest.note[]` carries caution text for
     moderate/minor severity co-prescriptions that are still emitted.
   - No `DetectedIssue` resource emission (see §7 Out-of-scope).
8. Tests: unit + integration + cohort verification
   (`verify_medical_stats.py` gains `contraindicated_pair_count`).

### Out of scope (post-MVP, follow-up issues)

- **`DetectedIssue` resource emission** — the CPOE workflow suppresses
  contraindicated pairs at order entry (no chart trace), which is
  what MVP models. `DetectedIssue` is the surface for a pharmacist /
  medication-reconciliation *post-hoc* workflow; that workflow is not
  currently modeled by the sim, so emitting `DetectedIssue` would be
  semantically hollow.
- **`allow_if_indication` whitelist** — real practice permits certain
  contraindicated combinations under specific indications (warfarin +
  aspirin in AF + recent PCI). MVP treats all contraindicated pairs
  as skip; whitelist logic + `Provenance`-anchored override
  documentation defers to a follow-up issue.
- **`antibiotic` module integration** — the `antibiotic` narrow-ladder
  path (POST_ENCOUNTER order=85) will call `drug_safety` in a
  follow-up PR; MVP relies on `order` module coverage.
- **`patient` module substitution** — chronic-med contraindication
  triggers `skip only` in MVP (no alternative chronic med selection);
  substitution requires a chronic-med alternatives table that is
  deferred.
- **LLM prompt production evaluation** — the H100 narrate run to
  clinician-eye review the LLM-generated avoidance narrative is a
  post-merge activity; MVP ships the prompt tuning + template
  fallback and verifies both via unit tests.

## 3. Architecture

### 3.1 Module shape

Package layout (canonical 11-section README, per `docs/CONTRIBUTING-modules.md`):

```
clinosim/modules/drug_safety/
├── __init__.py                       # public API re-export
├── engine.py                         # check_pair, check_candidate_against_active, suggest_alternative
├── classifier.py                     # drug-name → drug_class[] resolver (alias-aware)
├── verdict.py                        # SafetyVerdict + SafetySkipEntry dataclasses
├── audit.py                          # AD-60 audit plug-in
├── reference_data/
│   ├── drug_classes.yaml             # drug → class[] taxonomy
│   ├── contraindications.yaml        # class × class rules
│   └── README.md                     # data-file schema doc
├── README.md
└── README.ja.md
```

**Layer placement**: Foundation. No clinosim cross-dependencies except
`clinosim/locale/` (for locale-shared substitution) and reads its own
`reference_data/`. Not registered as an enricher — invoked
synchronously by callers.

`locale/shared/drug_substitution.yaml` is new data owned by
`drug_safety` but sits under `locale/shared/` to match existing
locale-shared conventions (`chronic_medications.yaml`,
`iv_infusion_defaults.yaml`).

### 3.2 Data-flow diagram

```
disease_ctx / indication ──┐
patient.active_meds ───────┼──> check_candidate_against_active(candidate, active)
candidate drug ────────────┘                       │
                                                   ▼
                                     list[SafetyVerdict] (empty = safe)
                                                   │
                        ┌──────────────────────────┼──────────────────────────┐
                        │                                                     │
                    verdict.severity ∈ {contraindicated, major}     verdict.severity ∈ {moderate, minor}
                        │                                                     │
                        ▼                                                     ▼
              suggest_alternative(candidate, indication, ctx)          MR emitted; MR.note += caution
                        │
              ┌─────────┴─────────┐
              │                   │
       alt = AlternativeDrug   alt = None
              │                   │
              ▼                   ▼
      MR built from alt      MR skipped entirely
              │                   │
              └────────┬──────────┘
                       ▼
   patient.safety_skip_log.append(SafetySkipEntry(
       candidate, active_conflict, verdict, substituted_with, context_hint))
                       │
                       ▼
    build_narrative_context reads safety_skip_log per encounter
                       │
        ┌──────────────┴──────────────┐
        ▼                             ▼
Layer 2 template render      Layer 3/4 LLM prompt substitution vars
```

## 4. Data model

### 4.1 `drug_classes.yaml` (new)

```yaml
# clinosim/modules/drug_safety/reference_data/drug_classes.yaml
#
# Schema
#   mappings:
#     <Canonical Drug Name>:
#       aliases:      [<additional names, case-insensitive substring match — EN + JP + brand>]
#       drug_ja:      "<JP display>"
#       classes:      [<class tags, dot-notated: family.subfamily>]
#
# Class taxonomy conventions
#   anticoagulant.vka / anticoagulant.doac / anticoagulant.heparin
#   antiplatelet.cox_inhibitor / antiplatelet.p2y12 / antiplatelet.gp2b3a
#   nsaid.non_selective / nsaid.cox2_selective  (aspirin is BOTH antiplatelet.cox_inhibitor AND nsaid.non_selective)
#   ccb.dhp / ccb.non_dhp
#   beta_blocker.cardioselective / beta_blocker.non_selective
#   acei / arb / acei_arb (union)
#   potassium_supplement
#   diuretic.loop / diuretic.thiazide / diuretic.k_sparing
#
# When adding a new drug, assign every class it belongs to. Rules are matched
# by class, so drug added to an existing class automatically inherits rules.

mappings:
  Warfarin:
    aliases: ["ワルファリン", "coumadin", "warf"]
    drug_ja: "ワルファリン"
    classes: ["anticoagulant.vka", "anticoagulant"]

  Apixaban:
    aliases: ["アピキサバン", "eliquis"]
    drug_ja: "アピキサバン"
    classes: ["anticoagulant.doac", "anticoagulant"]

  # ~40 drugs total for MVP — drawn from
  # clinosim/locale/shared/chronic_medications.yaml + drug_names_ja.yaml +
  # disease YAML `first_line` blocks. Full list expanded during
  # implementation phase.
```

### 4.2 `contraindications.yaml` (new)

```yaml
# clinosim/modules/drug_safety/reference_data/contraindications.yaml
#
# Schema
#   rules:
#     - id:              <kebab-case unique identifier>
#       lhs:             <class expression>
#       rhs:             <class expression>
#       severity:        allowed | minor | moderate | major | contraindicated
#       rationale_en:    "<one-sentence clinical justification>"
#       rationale_ja:    "<Japanese translation>"
#       substitution_hint: <optional indication tag suggested_alternative should use as prior>
#       source:          "<citation: guideline / DDI database / textbook>"
#
# Order-independent: check_pair(A, B) matches both {lhs:A, rhs:B} and {lhs:B, rhs:A}.

rules:
  - id: vka-plus-antiplatelet
    lhs: anticoagulant.vka
    rhs: antiplatelet
    severity: contraindicated
    rationale_en: "VKA + antiplatelet substantially raises major bleeding risk. Allowed only under specific indications (recent PCI + AF ≤12mo, mechanical valve + secondary prevention) with GI protection."
    rationale_ja: "ワルファリン (VKA) と抗血小板薬の併用は重大出血リスクを大幅に上昇。特定 indication (PCI 後 12 か月以内かつ AF、機械弁 + 二次予防) 下でのみ、消化管保護と併用。"
    substitution_hint: pain_management
    source: "CHEST 2016 antithrombotic guidelines; JCS 2020 抗血栓療法"

  - id: anticoagulant-plus-nsaid
    lhs: anticoagulant
    rhs: nsaid
    severity: contraindicated
    rationale_en: "Anticoagulant + NSAID raises GI bleeding risk ~3-4x. Use acetaminophen instead."
    rationale_ja: "抗凝固薬と NSAID の併用は消化管出血リスクを 3-4 倍に上昇。アセトアミノフェン等の代替を選択。"
    substitution_hint: pain_management
    source: "BMJ 2011;343:d4094"

  - id: bb-plus-non-dhp-ccb
    lhs: beta_blocker
    rhs: ccb.non_dhp
    severity: major
    rationale_en: "β-blocker + non-DHP CCB (verapamil / diltiazem) risks bradycardia, AV block, heart failure exacerbation."
    rationale_ja: "β遮断薬と非 DHP CCB (ベラパミル/ジルチアゼム) の併用は徐脈・房室ブロック・心不全増悪リスク。"
    substitution_hint: hypertension_or_rate_control
    source: "ACC/AHA 2019 chronic coronary disease; JCS 2018 心不全"

  - id: acei-arb-plus-potassium
    lhs: acei_arb
    rhs: potassium_supplement
    severity: major
    rationale_en: "ACEi/ARB + K supplementation risks hyperkalemia; monitor K+ closely if combined."
    rationale_ja: "ACEi/ARB と K 補充の併用は高 K 血症リスク。併用時は K+ モニタリング必須。"
    substitution_hint: null   # K supplementation itself is the therapy — no drop-in alternative
    source: "KDIGO 2024 CKD management"

  # ~11 additional established contraindication rules for MVP (allopurinol+azathioprine,
  # ssri+maoi, statin+cyp3a4-strong-inhibitor, etc.) — enumerated in implementation plan.
```

### 4.3 `locale/shared/drug_substitution.yaml` (new)

```yaml
# clinosim/locale/shared/drug_substitution.yaml
#
# Generic indication-driven alternative drug pool.
# Called by drug_safety.suggest_alternative when disease-YAML alternative_* blocks
# do not carry an indication-specific candidate.
#
# Schema
#   indications:
#     <indication_tag>:
#       description: "<one-line explanation>"
#       alternatives:
#         - drug: "<generic drug name>"
#           drug_ja: "<JP display>"
#           default_dose: "<neutral dose string, matches chronic_medications.yaml format>"
#           default_route: "<PO | IV | SC | INH>"
#           default_frequency: "<daily | bid | tid | qid | prn>"
#           # each alternative must itself pass check_pair against the active med list —
#           # the caller re-invokes check_pair on the alternative to avoid selecting
#           # a second contraindicated drug (e.g. suggesting ibuprofen after
#           # NSAID is blocked)

indications:
  pain_management:
    description: "General analgesia when NSAID or opioid is contraindicated."
    alternatives:
      - drug: "Acetaminophen"
        drug_ja: "アセトアミノフェン"
        default_dose: "500mg"
        default_route: "PO"
        default_frequency: "q6h_prn"

  hypertension_or_rate_control:
    description: "BP or heart-rate control when specific antihypertensive class is contraindicated."
    alternatives:
      - drug: "Amlodipine"
        drug_ja: "アムロジピン"
        default_dose: "5mg"
        default_route: "PO"
        default_frequency: "daily"

  # ~8 additional indication tags: prophylactic_anticoag, gerd_management,
  # constipation_relief, mild_sedation, cough_suppression, antiemetic,
  # electrolyte_correction, fluid_replacement. Enumerated in implementation plan.
```

### 4.4 Revived disease YAML blocks

The Issue #437 dead-data blocks are re-wired via `suggest_alternative`,
which will scan the current `disease_ctx.protocol.medications` for the
indication-matched `alternative_*` block before falling back to
`locale/shared/drug_substitution.yaml`. Example lookup chain for a
warfarin-blocked NSAID request:

1. `disease_ctx.protocol.medications.alternative_beta_blocker_contraindicated` —
   miss (indication is `pain_management`, not β-blocker contraindication)
2. `disease_ctx.protocol.medications.alternative_penicillin_allergy` — miss
3. `locale/shared/drug_substitution.yaml[pain_management].alternatives[0]` →
   Acetaminophen

The 4 revived blocks and their intended trigger indications:

| Block | Trigger indication | Disease coverage |
|---|---|---|
| `alternative_penicillin_allergy` | `antimicrobial_penicillin_class` | bacterial_pneumonia, aspiration_pneumonia, sepsis, urinary_tract_infection, acute_cholecystitis, acute_pancreatitis, copd_exacerbation |
| `alternative_beta_blocker_contraindicated` | `hypertension_or_rate_control` | (fewer disease YAMLs — enumerated during implementation) |
| `mrsa_coverage` | `antimicrobial_gram_positive_resistant` | sepsis, aspiration_pneumonia, hemorrhagic_stroke wound coverage |
| `hyperkalemia_management` | `electrolyte_correction` | acute_pancreatitis, deep_vein_thrombosis, pulmonary_embolism |

**Revival mechanism**: `disease/protocol.py` gains an `alternatives`
accessor exposing these blocks; `drug_safety.suggest_alternative`
reads them. No change to existing `first_line` reader behavior.

### 4.5 `SafetyVerdict` and `SafetySkipEntry` (verdict.py)

```python
from dataclasses import dataclass, field
from typing import Literal

Severity = Literal["allowed", "minor", "moderate", "major", "contraindicated"]

SEVERITY_RANK: dict[Severity, int] = {
    "allowed": 0, "minor": 1, "moderate": 2, "major": 3, "contraindicated": 4,
}

@dataclass(frozen=True)
class SafetyVerdict:
    severity: Severity
    rule_id: str | None                 # None when severity == "allowed"
    matched_classes: tuple[str, str] | None
    matched_active_drug: str | None     # canonical name of the offending active med
    rationale_en: str | None
    rationale_ja: str | None
    substitution_hint: str | None

    @property
    def is_allowed(self) -> bool:
        return self.severity == "allowed"

    @property
    def default_action(self) -> Literal["emit", "emit_with_note", "skip"]:
        return {
            "allowed": "emit",
            "minor": "emit",              # note optional — caller decides
            "moderate": "emit_with_note",
            "major": "skip",
            "contraindicated": "skip",
        }[self.severity]

@dataclass
class SafetySkipEntry:
    encounter_id: str
    candidate_drug: str
    candidate_drug_ja: str
    active_conflict: str
    active_conflict_ja: str
    verdict: SafetyVerdict
    substituted_with: str | None        # canonical name of alternative, None if skip
    substituted_with_ja: str | None
    context_hint: str | None            # indication tag ("pain_management", etc.)
    timestamp: str                      # ISO-8601, encounter-relative
```

## 5. API

```python
# clinosim/modules/drug_safety/__init__.py — public surface
from .engine import (
    check_pair,
    check_candidate_against_active,
    suggest_alternative,
    resolve_classes,
)
from .verdict import SafetyVerdict, SafetySkipEntry, Severity, SEVERITY_RANK

# clinosim/modules/drug_safety/engine.py

def check_pair(drug_a: str, drug_b: str) -> SafetyVerdict:
    """Return the highest-severity contraindication verdict for the pair.
    Order-independent: check_pair(A, B) == check_pair(B, A).
    Returns SafetyVerdict(severity="allowed") when no rule matches."""

def check_candidate_against_active(
    candidate: str,
    active_meds: Sequence[str],
) -> list[SafetyVerdict]:
    """Check candidate against each active med; return list of non-allowed verdicts,
    each carrying its matched_active_drug.  Empty list means the candidate is safe."""

def suggest_alternative(
    candidate: str,
    indication: str | None,
    *,
    active_meds: Sequence[str] = (),
    disease_ctx: DiseaseProtocol | None = None,
) -> AlternativeDrug | None:
    """Pick an alternative drug for `candidate` given the current active_meds
    (to avoid selecting a second contraindicated drug) and optional disease
    context. Priority order:
        1. disease_ctx.alternatives[<indication-matched block>] if present
        2. locale/shared/drug_substitution.yaml[indication].alternatives
        3. None (fully skipped — caller must handle)
    Every returned alternative has been re-checked via check_pair against
    every entry in active_meds and is guaranteed conflict-free."""

def resolve_classes(drug_name: str) -> list[str]:
    """Utility: bare drug name → class tags (via alias resolution).
    Returns [] when the drug is unknown to drug_classes.yaml."""
```

**Return contract for `suggest_alternative`**:
- `AlternativeDrug` is a lightweight dataclass carrying `drug`,
  `drug_ja`, `default_dose`, `default_route`, `default_frequency`,
  `source_path` (yaml provenance string, for CIF trace).
- When the alternatives table itself contains a drug that would form
  a new contraindication with active meds, the function iterates and
  picks the next candidate; if all fail, returns `None`.

## 6. Determinism

- **Verdict is pure YAML lookup, no RNG consumption.**
- **Substitution picks the first conflict-free alternative in list order**
  — no random draw. Deterministic across seeds. When multiple
  conflict-free alternatives exist, the first entry in the YAML wins,
  and users controlling ordering (edit the YAML) fully control
  substitution selection. This avoids introducing a new sub-RNG stream
  that would shift the master RNG.
- **RNG shape impact on the master stream**:
  - A skipped candidate does NOT emit its normal downstream MR/MA, so
    the master RNG stream skips forward compared to baseline
    (previously the emit consumed noise draws; now it does not).
  - A substituted alternative emits its own MR/MA, which consumes RNG
    at a slightly different site than the skipped original.
  - **Consequence**: the change is a documented cohort-scale RNG shift
    (per `feedback_rng_shift_patient_cache_cascade`). CHANGELOG notes
    the shift; version bump = MINOR per
    `feedback_versioning_policy_cif_narrative_consistency`. Cohort
    statistics (HTN prev, mortality, encounter mix) should stay within
    tolerance — verified via `verify_medical_stats.py` diff.
- **Cross-platform bit-reproducibility**: the module performs no
  transcendental math, no libm calls, and no random draws — outputs
  are purely dictionary lookups + string comparisons. Safe under the
  `_DeterministicRngProxy` regime
  (`feedback_deterministic_rng_proxy_pattern`).

## 7. FHIR emit surface

### 7.1 What IS emitted

- `MedicationRequest` for the substituted alternative (when
  substitution succeeds) — a normal MR indistinguishable from any
  other, so downstream FHIR consumers require no schema change.
- `MedicationRequest.note[]` gains a caution entry for `moderate`
  severity co-prescriptions that are still emitted, e.g.:

  ```json
  {
    "text": "併用注意: β遮断薬と非 DHP CCB の併用は徐脈・房室ブロック・心不全増悪のリスクがあります。心拍数・血圧の追加モニタリングを検討してください。",
    "authorReference": {"display": "clinosim drug_safety v1"}
  }
  ```

  For `minor` severity, note emission is optional (default: no note —
  matches real chart practice where minor DDIs are routine).

### 7.2 What is NOT emitted

- **No `DetectedIssue` resource** — see §2 out-of-scope rationale
  (CPOE workflow model).
- **No trace of skipped candidates in the FHIR bundle** — matches real
  EHR where a rejected CPOE order leaves no chart artifact. Developer
  trace lives in CIF-only `patient.safety_skip_log`.
- **No `Provenance` linking the substitution** — a follow-up issue
  can add `Provenance.entity` chaining the substituted MR back to the
  intended-but-skipped candidate. MVP omits to keep scope tight.

### 7.3 Downstream consumer impact

- Consumer ETLs that historically counted "warfarin+aspirin co-prescription"
  events will see the count drop to zero. CHANGELOG notes this
  explicitly with the pre/post count.
- New note authorReference `clinosim drug_safety v1` — allowlist-based
  note parsers may need to include it.
- MedicationRequest total count will shift (some skipped, some
  substituted). `verify_medical_stats.py` gains a per-class MR count
  baseline to catch unexpected drift.

## 8. Narrative surface (all 4 layers)

### 8.1 Layer 1 — Context

- `clinosim/types/document.py::NarrativeContext` gains:
  ```python
  safety_skips: list[dict[str, Any]] = field(default_factory=list)
  # each dict: {considered, considered_ja, avoided_due_to, avoided_due_to_ja,
  #             rationale_en, rationale_ja, substituted_with, substituted_with_ja,
  #             context, severity}
  ```
- `clinosim/modules/document/narrative/context.py::build_narrative_context`
  extended to filter `record.safety_skip_log` by `encounter.id` and
  populate the field.

### 8.2 Layer 2 — Template fallback (`template_generator.py` + `_chronic_soap.py`)

Deterministic narrative renderers gain an `_render_safety_skips`
helper called from A&P / Plan section builders. Output style
(Japanese):

```
【アセスメント / プラン】
・疼痛管理: NSAID (イブプロフェン) はワルファリンとの併用禁忌のため回避し、
  アセトアミノフェン 500mg 経口 6 時間毎頓用を処方。抗凝固療法中の消化管出血
  リスクを考慮した代替選択。
```

English style:

```
Assessment & Plan
- Pain management: NSAID (ibuprofen) avoided due to concurrent warfarin
  (bleeding risk); acetaminophen 500mg PO q6h prn prescribed instead.
```

Fully skipped case (no substitution):

```
・NSAID は抗凝固療法との併用禁忌のため処方せず。疼痛強度に応じてアセト
  アミノフェンまたは非薬理学的対応を検討。
```

### 8.3 Layer 3 — Production LLM prompt (`narrative_seed_bundle.yaml`)

Both `en/narrative_seed_bundle.yaml` and `ja/narrative_seed_bundle.yaml`:

- `user_template` gains a `${safety_skips}` block that renders as:
  ```
  Considered but not prescribed:
  - Ibuprofen (avoided due to Warfarin - bleeding risk); substituted with Acetaminophen 500mg PO q6h prn
  - (empty if no skips this encounter)
  ```
- `system` prompt gets an appended instruction:
  ```
  If the "Considered but not prescribed" section is non-empty, include
  the clinical reasoning ("~ was avoided due to ~; ~ was chosen
  instead") in the Assessment & Plan section using natural clinical
  prose. Do not fabricate any avoidance not present in the input.
  ```
- Version bump on the YAML (`version: N+1`).

### 8.4 Layer 4 — Reserved individual prompts (sync per audit doc)

Same treatment applied to:
- `admission_hp.yaml` (EN + JA) — Home medications section
- `discharge_summary.yaml` (EN + JA) — Discharge medications section
- `death_discharge_summary_treatment_course.yaml` (EN + JA) — Treatment course
- (Others not affected by safety skip semantics remain unchanged.)

Header comment on each edited file updated with the new sync date and
audit-doc pointer.

### 8.5 CIF ↔ narrative consistency guarantee

- Every drug name mentioned in the narrative (both the skipped candidate
  AND the substituted alternative) must trace to either:
  - a `SafetySkipEntry.candidate_drug` (never emitted as MR)
  - a `SafetySkipEntry.substituted_with` (emitted as MR — MR
    physically present in the bundle)
- Test: `test_narrative_avoidance_consistency` iterates every
  narrative note containing "回避" / "avoid", extracts substituted
  drug names, asserts each has a matching MR in the same encounter.
  This closes the class of CIF-drift defects covered by
  `feedback_versioning_policy_cif_narrative_consistency`.

## 9. Caller integration

### 9.1 `order.engine._emit_medication_order`

```python
# Simplified — actual signature adapts to existing call sites.

def _emit_medication_order(
    candidate: MedSpec,
    active_meds: list[Med],
    patient: PatientRecord,
    encounter: Encounter,
    indication: str | None = None,
    disease_ctx: DiseaseProtocol | None = None,
    ...
) -> MedicationOrder | None:
    verdicts = drug_safety.check_candidate_against_active(
        candidate.drug, [m.drug for m in active_meds],
    )
    worst = max(
        (v for v in verdicts if not v.is_allowed),
        key=lambda v: SEVERITY_RANK[v.severity],
        default=None,
    )

    if worst and worst.default_action == "skip":
        alt = drug_safety.suggest_alternative(
            candidate.drug,
            indication or worst.substitution_hint,
            active_meds=[m.drug for m in active_meds],
            disease_ctx=disease_ctx,
        )
        patient.safety_skip_log.append(SafetySkipEntry(
            encounter_id=encounter.id,
            candidate_drug=candidate.drug,
            candidate_drug_ja=drug_names_ja.lookup(candidate.drug),
            active_conflict=worst.matched_active_drug,
            active_conflict_ja=drug_names_ja.lookup(worst.matched_active_drug),
            verdict=worst,
            substituted_with=alt.drug if alt else None,
            substituted_with_ja=alt.drug_ja if alt else None,
            context_hint=indication or worst.substitution_hint,
            timestamp=encounter.current_time.isoformat(),
        ))
        if alt is None:
            return None
        return _build_order_from_alternative(alt, ...)

    order = _build_order(candidate, ...)
    if worst and worst.default_action == "emit_with_note":
        order.notes.append(_verdict_to_note(worst, patient.locale))
    return order
```

### 9.2 `patient.activator._derive_home_medications`

```python
for chronic_condition in patient.chronic_conditions:
    for med_template in home_med_pool_for(chronic_condition):
        verdicts = drug_safety.check_candidate_against_active(
            med_template.drug, [m.drug for m in accepted_home_meds],
        )
        worst = max(
            (v for v in verdicts if not v.is_allowed),
            key=lambda v: SEVERITY_RANK[v.severity], default=None,
        )
        if worst and worst.default_action == "skip":
            patient.safety_skip_log.append(SafetySkipEntry(
                encounter_id="__home_med_derivation__",
                candidate_drug=med_template.drug,
                ...
                substituted_with=None,   # MVP: no chronic substitution
                context_hint="home_med_derivation",
                timestamp=patient.activation_time.isoformat(),
            ))
            continue
        med = _build_home_med(med_template, ...)
        if worst and worst.default_action == "emit_with_note":
            med.notes.append(_verdict_to_note(worst, patient.locale))
        accepted_home_meds.append(med)
```

**Why `patient` module has no substitution in MVP**: home meds are
chronic-disease-specific (HTN → antihypertensive), and picking a
class-appropriate alternative for chronic use requires additional
alternative-class data not yet in `chronic_medications.yaml`. Deferred
to a follow-up issue.

### 9.3 Enricher / audit registration

- No enricher registration in `simulator/enrichers.py` (drug_safety
  is a library, not a POST-stage enricher).
- `drug_safety/audit.py` registers an AD-60 audit plug-in that
  post-hoc scans the CIF for any `active_meds` combinations that
  should have triggered a skip but did not (defensive
  regression-catch — validates the gate fired everywhere it should).

## 10. Testing

### 10.1 Unit tests (`tests/modules/drug_safety/`)

| Test file | Coverage |
|---|---|
| `test_verdict.py` | Severity ranking, is_allowed, default_action mapping, SafetySkipEntry serialization |
| `test_classifier.py` | Drug-name (EN / JA / brand / mixed-case) → class tags; unknown drug returns [] |
| `test_engine_check_pair.py` | Rule hit/miss, order-independence, severity ranking, no RNG consumption gate |
| `test_engine_suggest_alternative.py` | disease_ctx alternative_* preferred over shared pool; iteration when alternative itself blocked; returns None when all blocked |
| `test_audit.py` | AD-60 plug-in catches synthetic missed-gate cases |

### 10.2 Integration tests (`tests/integration/`)

| Test file | Coverage |
|---|---|
| `test_drug_safety_order_hook.py` | Warfarin active + NSAID candidate → NSAID MR absent, Acetaminophen MR present, safety_skip_log entry populated |
| `test_drug_safety_patient_hook.py` | Home med derivation for AF + coronary patient → warfarin present, aspirin skipped (skip-only, no substitution) |
| `test_drug_safety_fhir_emit.py` | Bundle contains no DetectedIssue; MR.note carries moderate caution text; substituted MR has clinosim drug_safety v1 in note authorReference |
| `test_narrative_avoidance_template.py` | Template fallback renders JP + EN A&P avoidance text; safety_skips empty → no line rendered |
| `test_narrative_avoidance_consistency.py` | Every drug named in narrative "回避 / avoid" clauses has matching MR in the same encounter (CIF ↔ narrative consistency gate) |
| `test_llm_prompt_seed_bundle.py` | `safety_skips` block correctly substituted into narrative_seed_bundle user_template; empty input yields empty block |

### 10.3 Cohort verification

- `scripts/verify_medical_stats.py` gains:
  - `contraindicated_pair_count` metric — target: 0 (was ~150 on
    US p=10k seed=500)
  - `substituted_prescription_count` per indication — new baseline
  - `mr_class_distribution` diff — expect substitution shifts (NSAID
    ↓, acetaminophen ↑, etc.)
- `scripts/verify_bundle.py` — no schema change (existing FHIR
  integrity checks continue to pass; new MR.note authorReference
  passes existing "no unknown authorReference" check via allowlist
  update).
- **verify script CI integration** (B25) deferred; MVP runs verify
  scripts manually on p=1000 seed=500 in the PR description.

### 10.4 RNG-preservation gate

- Deterministic sim run p=100 seed=500 fix-vs-baseline byte diff.
- Expected: **intentional differences only** — the delta list is
  the set of patients touched by any contraindication rule (a small,
  enumerable subset). Non-touched patients' MRs, MAs, and downstream
  resources remain byte-identical.
- p=1000 seed=500 cohort fingerprint compared to baseline — cohort
  statistics stay within tolerance (HTN prev, mortality, encounter
  mix).

### 10.5 Cross-platform bit-reproducibility

- Mac (ARM) ↔ H100 (x86) p=100 seed=500 byte-identical
  verification (per `feedback_deterministic_rng_proxy_pattern`).

## 11. Release / migration

### 11.1 Version bump

- **v0.6.0 MINOR bump** (already staged as user Go-only at session-98
  wrap). B1 fits within the pending 0.6.0 scope — CHANGELOG
  `[Unreleased]` gains a new subsection.
- Rationale: cohort-scale RNG shape shift + new required CIF field
  (`safety_skip_log`) = CIF drift = MINOR per
  `feedback_versioning_policy_cif_narrative_consistency`.

### 11.2 CHANGELOG entry (skeleton)

```
### Added
- New `clinosim.modules.drug_safety` foundation module: class-based
  contraindication rule engine with severity-graded verdicts and
  alternative-drug substitution.
- `MedicationRequest.note[]` caution text for moderate DDI
  co-prescriptions (authorReference: "clinosim drug_safety v1").
- Narrative surfacing of drug-safety-driven substitution across
  template and LLM pipelines (all 4 narrative layers).
- `CIF.PatientRecord.safety_skip_log` field for developer/audit
  traceability of blocked candidates.

### Changed
- Contraindicated co-prescription pairs (warfarin+aspirin,
  warfarin+NSAID, β-blocker+non-DHP CCB, ACEi+K supplement, +11 more
  rules) now blocked at order-entry time, matching real CPOE
  behaviour. US p=10000 seed=500 pair count: 153 → 0.
- Total MR count shifts slightly per cohort due to
  skip-and-substitute selection (baseline diff in verify report).
- Revived Issue #437 dead-data YAML blocks:
  `alternative_penicillin_allergy`, `alternative_beta_blocker_contraindicated`,
  `mrsa_coverage`, `hyperkalemia_management` now consumed by
  `drug_safety.suggest_alternative`.

### Fixed
- Closes #1066 (B1 contraindication gate).
- Partially addresses #1074 (B9 progress-note clinical reasoning
  visibility) via avoidance-narrative surfacing.
```

### 11.3 Migration notes for downstream consumers

- ETLs counting `warfarin+aspirin` co-prescription events will see
  the count drop to zero. If a consumer relied on the presence of
  these pairs, they must re-baseline against v0.6.0.
- New MR.note authorReference `clinosim drug_safety v1` — allowlists
  must include it (documented in `docs/CONSUMER_MIGRATION.md`
  followup section).
- No FHIR schema change; no new resource types emitted; no bundle
  structural change.

### 11.4 Maintainer copy refresh

Per `feedback_iris_ai_copy`:
- `~/workspace/iris4h-ai/fhir_r4/` — refresh post-merge
- `~/workspace/fhir-jp-validator/fhir_r4/` — refresh post-merge

## 12. Risks and mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| RNG shift breaks unrelated cohort statistics | Medium | Cohort statistic diff at p=1000/p=10000; hold if HTN prev, mortality, encounter mix move beyond noise band |
| Substitution introduces its own contraindications (cascade) | Low-Medium | `suggest_alternative` re-invokes `check_pair` on candidates in list order; returns None if all fail |
| Narrative fabricates avoidance not in CIF (LLM hallucination) | Medium | test_narrative_avoidance_consistency enforces "every named drug traces to CIF"; LLM prompt explicitly instructs "do not fabricate" |
| Reserved individual prompt drift vs narrative_seed_bundle | Low | Header comment + audit doc pointer; follow-up audit issue tracks drift |
| Missing drug from drug_classes.yaml silently allowed | Medium | `test_all_chronic_meds_have_classes` iterates chronic_medications.yaml + disease first_line lists, asserts every drug resolves to at least one class |
| Substitution alternative unavailable in `locale/shared/drug_substitution.yaml` for a common indication | Low-Medium | Fully skipped case is documented as narrative fallback ("疼痛強度に応じて対応"); follow-up issue can extend the substitution table |

## 13. Open questions

None outstanding as of this draft (all resolved in the design
brainstorm — class-based taxonomy, rich verdict, severity-driven
default, order+patient MVP callers, disease-YAML revive + generic
pool, all 4 narrative layers, no DetectedIssue in MVP).

## 14. Follow-up issues (post-MVP)

To be filed as separate issues after B1 lands:

- `DetectedIssue` resource emission + pharmacist-review workflow model
- `allow_if_indication` whitelist + Provenance override chain
- `antibiotic` module drug_safety integration (narrow ladder path)
- `patient` module chronic-med substitution (chronic alternatives table)
- Reserved individual prompt audit doc update (2026-08-30 doc refresh)
- LLM production evaluation on H100 (JUDGMENT template integration)
- `verify_medical_stats.py` `contraindicated_pair_count` CI gate
  (part of B25)

---

## Approval

- Design brainstorm iterations: 5 rounds (2026-09-03 session 99)
- Awaiting user review of this spec before invoking `writing-plans`
  skill.
