# clinosim Design Guidelines

## 1. Grand Design Principle: Realism Above All

**The highest priority of clinosim is realism.** Every design decision, every parameter choice, every module behavior must be evaluated against a single question: _"Would this happen in a real hospital?"_

### What realism means in clinosim

Realism is not a single axis. It spans three dimensions, all of which must be satisfied simultaneously:

| Dimension | Question | Example |
|---|---|---|
| **Biological realism** | Is this physiologically and pathologically plausible? | CRP does not rise to 200 mg/L 2 hours after infection onset. Creatinine does not drop by 3 mg/dL overnight without dialysis. |
| **Behavioral realism** | Would a real clinician, nurse, or patient act this way? | A physician does not order a CT at 3 AM for a stable pneumonia patient. A 35-year-old does not present with hip fracture without trauma. A Japanese patient may stay hospitalized for 14 days with pneumonia; an American patient is discharged in 5. |
| **Systemic realism** | Would this happen within this healthcare system and institution? | A small community hospital does not perform cardiac catheterization. Night shift lab results take longer. Weekend consultant availability is limited. |

### Realism principles for every module

1. **Real-world distributions, not uniform randomness.** Age, sex, blood type, comorbidity prevalence, disease incidence — all must follow published epidemiological distributions, not arbitrary ranges. When a parameter is generated, it must be traceable to a real data source or published statistic.

2. **Correlation, not independence.** In reality, patient attributes are correlated: age with comorbidities, sex with disease incidence, socioeconomic status with health literacy, blood type distribution with ethnicity. Generated data must preserve these correlations.

3. **Temporal coherence.** Events happen in an order that makes clinical sense, with realistic time gaps. Lab results arrive after specimens are collected. Antibiotics are started after (not before) cultures are drawn. CRP peaks 48 hours after infection, not simultaneously.

4. **Institutional context.** The same clinical scenario produces different data in different settings. A university hospital has different staffing, equipment, and documentation patterns than a community clinic. Japan and the US differ in length of stay, test ordering frequency, discharge criteria, and documentation style.

5. **Imperfection is realistic.** Real data has missing values, measurement errors, delayed results, misdiagnoses, and workarounds. Perfectly clean data is itself unrealistic. Imperfections must be context-dependent and explainable, never random noise.

6. **Validate against reality.** Every module must define quantitative realism benchmarks: published statistics, clinical guidelines, or epidemiological data against which the generated output can be verified. If a module cannot cite a real-world reference for its parameters, those parameters are suspect.

### How this principle governs design decisions

When faced with a design choice:
- "Should we simplify X?" → Only if the simplification does not produce data that a domain expert would recognize as fake.
- "How much detail do we need?" → Enough that the generated data passes a clinician's sniff test. No more, no less.
- "Should we model Y?" → If omitting Y would create a noticeable gap in realism (e.g., missing nursing records, no weekend effect on lab turnaround), then yes.

### Validation: proving realism, not assuming it

Realism is not a subjective claim — it must be **measured**. clinosim uses a three-tier validation framework:

**Tier 1: Statistical validation (automated)**
Compare generated data distributions against published real-world statistics. These run automatically after every simulation and flag deviations.

**Tier 2: Clinical pattern validation (automated + expert review)**
Verify that temporal patterns, clinical sequences, and inter-variable correlations match known clinical behavior. Automated tests check structure; expert reviewers check clinical plausibility.

**Tier 3: Domain expert blind test**
Present generated records alongside real (anonymized) records to clinicians. If they cannot reliably distinguish generated from real, the realism target is met.

See `modules/validator/SPEC.md` for the full validation framework.

---

## 2. Modular Architecture Principles

### Why modularize

- **Context locality**: Each module can be designed and modified independently, without needing to comprehend the entire system at once
- **Parallel development**: Once inter-module interfaces are defined, modules can be implemented independently
- **Incremental design**: Open questions are managed per module; decisions are locked in as they are made

### Criteria for module boundaries

1. Each **pipeline stage** maps to one module
2. Every module has **clearly defined inputs and outputs**
3. Internal implementation details do not leak across module boundaries
4. **Data-driven configuration** (disease definitions, healthcare system rules) lives in dedicated modules

---

## 2. LLM Integration Architecture

### Why LLM

Rule-based simulation produces structurally correct data but lacks the nuance of real clinical documentation. Real clinical records contain:
- Natural language notes written by different physicians with different styles
- Diagnostic reasoning expressed in prose, not just probability updates
- Clinical judgment that considers context beyond what any rule system can capture
- Patient-reported symptoms in their own words
- Subtle inconsistencies and workarounds that reflect real-world practice

LLMs bridge the gap between "structurally valid" and "clinically indistinguishable from real."

### Design principle: Selective amplification

LLMs are used as **selective amplifiers** — they enhance specific outputs that benefit most from natural language generation or contextual reasoning, while all numerical and structural data remains rule-based.

```
Rule-based engine (fast, deterministic, cheap)
  │
  │  produces structured data: lab values, vitals, timestamps, codes, state variables
  │
  ↓
LLM layer (selective, contextual, expensive)
  │
  │  enhances: clinical notes, reasoning narratives, symptom descriptions,
  │            clinical judgment at ambiguous decision points,
  │            consistency review of generated records
  │
  ↓
Final output: Structured data + natural language that is clinically coherent
```

### Responsibility split: modules vs. llm_service

```
Module's job:                          llm_service's job:
  "This is what happened"     →        "This is how to describe it"
  (structured ClinicalEventData)       (prompt construction, model selection,
                                        response parsing, caching, cost tracking)
```

Modules NEVER write prompt text, choose model tiers, or set output token limits. All of that is defined in `llm_service/prompts/*.yaml` and managed centrally. This means:
- Prompt engineering happens in ONE place (the prompts/ folder)
- Switching LLM models requires changing ONE config, not every module
- Adding a new narrative type = adding one YAML file in llm_service

### LLM invocation points per module

| Module | Invocation point | What LLM does | What stays rule-based | Model tier | Context (in → out tokens) |
|---|---|---|---|---|---|
| **patient** | Chief complaint generation | Natural-language chief complaint from symptoms | Symptom selection and severity | Small | ~500 → 200 |
| **diagnosis** | Differential update at each decision point | Clinical reasoning narrative for assessment section | Probability calculations (Bayesian update), LR application | Medium | ~1,500 → 800 |
| **treatment** | Treatment selection / change decisions | Rationale for treatment choice with clinical context | Drug selection logic, dose calculation, interaction check | Medium | ~1,200 → 600 |
| **encounter** | Admission H&P | Full History & Physical document from structured data | Data collection itself | Large | ~2,500 → 4,000 |
| **encounter** | Progress notes (key days) | Daily SOAP note with clinical reasoning | Vitals/labs (inserted as structured data) | Medium | ~1,500 → 1,500 |
| **encounter** | Discharge summary | Comprehensive discharge document | Discharge criteria evaluation, timing | Large | ~4,000 → 5,000 |
| **encounter** | Consultation note | Specialist response with specialty-appropriate language | Consultation request routing | Medium | ~1,500 → 2,000 |
| **nursing** | Shift assessment notes | Nursing narrative from structured assessment | Assessment data collection, vital sign values | Small | ~800 → 500 |
| **procedure** | Operative note | Full operative report | Timing, team, complication determination | Large | ~2,000 → 3,000 |
| **validator** | Clinical consistency review | Review complete patient record for implausibility | Rate-of-change limits, mutual exclusion (rule-based) | Large | ~6,000 → 1,500 |
| **population** | Care-seeking decision (edge cases) | Simulate patient's decision reasoning | Threshold-based decisions for clear cases | Small | ~500 → 200 |

**Note on Japanese token counts:** Japanese text typically requires 1.5–2× more tokens than English for the same semantic content due to tokenizer characteristics. The estimates above assume Japanese output. English output would be ~30% fewer tokens.

**Note on system prompt overhead:** Each LLM call includes a system prompt (~200–500 tokens) that sets the physician/nurse persona, country context, and output format. This is included in the "in" estimates above.

### Model tier selection

| Tier | Model class | Use case | Cost/call (approx) |
|---|---|---|---|
| **Small** | Haiku-class | High-volume, simple generation (chief complaints, brief nursing notes, symptom descriptions) | Lowest |
| **Medium** | Sonnet-class | Clinical reasoning, treatment rationale, moderate-length notes | Medium |
| **Large** | Opus-class | Discharge summaries, H&P notes, consistency review, complex clinical judgment | Highest |

### Context minimization strategies

#### 1. Compact structured input (not raw data)

Instead of passing full patient history to the LLM, pass a **pre-summarized clinical context**:

```python
@dataclass
class LLMClinicalContext:
    """Minimal context sufficient for LLM to generate clinically appropriate output."""
    # Patient summary (~100 tokens)
    age: int
    sex: str
    chief_complaint: str
    relevant_conditions: list[str]       # only conditions relevant to current situation
    relevant_medications: list[str]
    allergies: list[str]
    
    # Current clinical state (~100 tokens)
    current_diagnosis: str
    diagnosis_confidence: float
    key_findings: list[str]              # e.g., ["CXR: lobar consolidation", "CRP 89", "PCT 1.8"]
    active_treatments: list[str]
    hospital_day: int
    
    # What changed since last note (~50 tokens)
    interval_events: list[str]           # e.g., ["fever resolved Day 3", "CRP trending down"]
    pending_results: list[str]
    
    # Country/institution context (~20 tokens)
    country: str
    hospital_type: str
    department: str
```

This keeps input under ~300 tokens for most calls, compared to sending the full patient record (~2000+ tokens).

#### 2. Template-guided generation

LLM fills in specific sections of a structured template, not free-form text:

```python
PROGRESS_NOTE_TEMPLATE = """
## Progress Note — Day {hospital_day}
**S (Subjective):** {llm_generates}
**O (Objective):**
- Vitals: {rule_based_vitals}
- Labs: {rule_based_labs}
- Exam: {llm_generates}
**A (Assessment):** {llm_generates_with_diagnosis_context}
**P (Plan):** {llm_generates_with_treatment_context}
"""
```

This constrains the LLM's output to specific fields, reducing token waste and ensuring structural consistency.

#### 3. Batch generation

Instead of calling the LLM at every time step, batch related calls:

```python
# BAD: Call LLM 14 times for 14-day stay (one per daily note)
for day in range(14):
    note = llm.generate_progress_note(day)

# GOOD: Generate key narrative points, then expand
key_events = rule_engine.identify_narrative_points(patient_timeline)
# Result: [Day 0: admission, Day 3: fever resolved, Day 7: CXR improved, Day 14: discharge]
# → Only 4 LLM calls instead of 14
# Intermediate days get template-based notes with minimal variation
```

#### 4. Caching and pattern reuse

Common clinical scenarios produce similar narratives:

```python
# Cache key: (disease, archetype, severity, hospital_day, country)
# Example: ("bacterial_pneumonia", "smooth_recovery", "moderate", 3, "JP")
# If a very similar note was generated before, reuse with minor variation (name, specific values)

narrative_cache = LRUCache(max_size=1000)
cache_key = (disease_id, archetype, severity_bucket, day_bucket, country)
if cache_key in narrative_cache:
    note = narrative_cache[cache_key].adapt(patient_specific_values)
else:
    note = llm.generate(context)
    narrative_cache[cache_key] = note.generalize()
```

#### 5. LLM-free mode

The system must be fully functional WITHOUT any LLM calls. LLM enhancement is an optional layer:

```python
class NarrativeGenerator:
    def __init__(self, mode: str = "llm"):  # "llm" | "template" | "none"
        self.mode = mode
    
    def generate_progress_note(self, context):
        if self.mode == "llm":
            return self.llm_generate(context)
        elif self.mode == "template":
            return self.template_generate(context)  # rule-based fill-in-the-blank
        else:
            return None  # no narrative, structured data only
```

- **`none`**: Structured data only. Fastest, zero LLM cost.
- **`template`**: Rule-based template filling. Fast, no LLM cost, but reads like form letters.
- **`llm`**: Full LLM enhancement. Slowest, costs money, but maximally realistic.

### Token budget per patient

For a typical 14-day pneumonia inpatient stay (Japan):

#### JUDGMENT tasks (always English — efficient tokens, high quality)

| Task | Count | Input | Output | Total | Model |
|---|---|---|---|---|---|
| Diagnostic reasoning | 3 | 800 × 3 | 400 × 3 | 3,600 | Medium |
| Treatment decision | 2 | 700 × 2 | 300 × 2 | 2,000 | Medium |
| Consistency review | 1 | 4,000 | 1,000 | 5,000 | Large |
| **Judgment subtotal** | **6** | **7,400** | **2,200** | **10,600** | |

#### NARRATIVE tasks (output in Japanese — larger token budget for natural text)

| Task | Count | Input (en) | Output (ja) | Total | Model |
|---|---|---|---|---|---|
| Chief complaint | 1 | 500 | 200 | 700 | Small |
| Admission H&P | 1 | 2,000 | 4,000 | 6,000 | Large |
| Progress notes (key days) | 4 | 1,200 × 4 | 1,500 × 4 | 10,800 | Medium |
| Discharge summary | 1 | 3,000 | 5,000 | 8,000 | Large |
| Nursing notes (key shifts) | 4 | 600 × 4 | 500 × 4 | 4,400 | Small |
| **Narrative subtotal** | **11** | **12,300** | **17,200** | **29,900** | |

#### Combined total

| | JP patient | US patient (all English) |
|---|---|---|
| Judgment tasks | 10,600 | 10,600 (same) |
| Narrative tasks | 29,900 | ~20,000 (English output is ~30% fewer tokens) |
| **Total per patient** | **~40,500** | **~30,600** |
| **LLM calls** | **17** | **17** |

#### Cost estimate per patient (approximate, Bedrock pricing 2025)

| Model tier | Calls | JP patient cost | US patient cost |
|---|---|---|---|
| Small (Haiku) | 5 | ~$0.003 | ~$0.002 |
| Medium (Sonnet) | 9 | ~$0.06 | ~$0.05 |
| Large (Opus) | 3 | ~$0.40 | ~$0.30 |
| **Total** | **17** | **~$0.46** | **~$0.35** |

#### Scale estimates (JP patients)

| Patients | Total tokens | Approx cost | With caching (~50% hit) |
|---|---|---|---|
| 10 | ~405K | ~$4.60 | ~$2.50 |
| 100 | ~4.05M | ~$46 | ~$25 |
| 1,000 | ~40.5M | ~$460 | ~$250 |

#### Budget control
When the configured budget limit is reached, llm_service automatically switches to template mode for remaining calls. This ensures cost predictability without stopping the simulation.

### Architecture decision record

| ID | Decision |
|---|---|
| AD-7 | LLM as selective amplifier: enhances narratives and clinical reasoning; all numerical/structural data remains rule-based |
| AD-8 | Three generation modes: `none` (structured only), `template` (rule-based text), `llm` (full LLM enhancement) |
| AD-9 | Compact context pattern: pre-summarized `LLMClinicalContext` (~300 tokens) instead of full patient record |
| AD-10 | Batch + cache strategy: LLM called at key narrative points only, with pattern caching |
| AD-11 | All LLM calls go through `llm_service` module. No other module may call LLM directly. Prompt templates and fallback logic are centralized here. |
| AD-13 | Two LLM task categories: JUDGMENT (always English, structured response) and NARRATIVE (output in target country language). Judgment in English maximizes quality and token efficiency. |
| AD-16 | Reproducibility via hierarchical seed management. Same seed + same config = identical structural data. LLM outputs cached for reproducibility. |
| AD-17 | Three-stage output: (1) Simulation (+ JUDGMENT LLM) → CIF structural (immutable, ~10.6K tokens/patient for JUDGMENT) → (2) CIF + NARRATIVE LLM → narrative layer (replaceable, re-generatable with different LLM, ~30K tokens/patient) → (3) structural + narrative → format adapters. |
| AD-18 | Pydantic BaseModel for all YAML-loaded config types (schema validation at load time). @dataclass for runtime-only types. |
| AD-19 | Preset + override configuration pattern: `SimulatorConfig.preset("japan_medium").override({...})` |
| AD-20 | LLM graceful degradation: retry (3x exponential backoff) → template fallback → structured-only. Simulation never halts on LLM failure. |
| AD-21 | Vertical slice implementation: v0.1-alpha (1 patient happy path) → v0.1-beta (population + archetypes) → v0.1 (full). |
| AD-22 | Three-level testing: unit (per module, <30s) → integration (module chains, <5min) → e2e (golden file, <30min). |
| AD-23 | Async LLM at patient level (Mode 1). Bounded concurrency via semaphore. Sync fallback always available. |
| AD-24 | JUDGMENT and NARRATIVE use independently configurable LLM providers/models. Can mix local + cloud, different model families, different tiers. Configuration in `llm_service.yaml` under `judgment:` and `narrative:` sections. |

### Reproducibility and seed management

Reproducibility is essential for debugging, validation, and scientific use. Same configuration + same seed must produce identical results.

#### Challenge: deterministic simulation + non-deterministic LLM

The simulation engine (population, physiology, disease, order timing, etc.) is fully deterministic given a seed. But LLM calls introduce non-determinism (even with temperature=0, outputs may vary across API calls).

#### Solution: hierarchical seed + LLM cache separation

```python
class SeedManager:
    """Manages reproducible random number generation across all modules."""
    
    def __init__(self, master_seed: int):
        self.master_seed = master_seed
        self.rng = numpy.random.default_rng(master_seed)
        self._module_seeds = {}
    
    def get_module_seed(self, module_name: str) -> int:
        """Each module gets a deterministic sub-seed derived from master seed."""
        if module_name not in self._module_seeds:
            self._module_seeds[module_name] = self.rng.integers(0, 2**32)
        return self._module_seeds[module_name]
    
    def get_patient_seed(self, patient_id: str) -> int:
        """Each patient gets a deterministic sub-seed for their simulation."""
        return hash((self.master_seed, patient_id)) % (2**32)
```

#### Reproducibility levels

| Level | Guarantee | How achieved |
|---|---|---|
| **Level 1: Structural** | Same patients, same diseases, same encounters, same lab values, same timestamps | Deterministic seed for all rule-based modules. No LLM dependency. |
| **Level 2: Structural + cached LLM** | Level 1 + identical narrative text | LLM outputs cached to disk (keyed by task_type + event_data hash). On re-run, cache is loaded instead of calling LLM. |
| **Level 3: Full fresh** | Structural data identical. LLM text may vary slightly. | LLM called fresh (no cache). Structural data still deterministic. |

```python
class LLMResponseCache:
    """Persistent cache for LLM responses, enabling reproducible runs."""
    
    def __init__(self, cache_dir: str):
        self.cache_dir = cache_dir  # e.g., "./output/llm_cache/"
    
    def get(self, cache_key: str) -> LLMResponse | None:
        path = os.path.join(self.cache_dir, f"{cache_key}.json")
        if os.path.exists(path):
            return LLMResponse.from_json(path)
        return None
    
    def put(self, cache_key: str, response: LLMResponse):
        path = os.path.join(self.cache_dir, f"{cache_key}.json")
        response.to_json(path)
    
    def export_cache(self, archive_path: str):
        """Export cache for sharing / version control."""
        shutil.make_archive(archive_path, 'zip', self.cache_dir)
```

#### Seed hierarchy

```
master_seed (user-provided, e.g., 42)
  |
  +-- population_seed     -> population generation, household structure
  +-- disease_seed        -> disease onset timing, severity, archetype selection
  +-- staff_seed          -> staff generation, shift scheduling
  +-- encounter_seed      -> encounter timing, workflow variations
  +-- physiology_seed     -> measurement noise, state jitter
  +-- order_seed          -> order timing distributions
  +-- nursing_seed        -> documentation timing jitter, MAR status
  +-- observation_seed    -> Layer 3 noise, missingness, anomalies
  +-- llm_cache_key       -> deterministic cache key for LLM responses
```

Each module creates its own `numpy.random.Generator` from its sub-seed at initialization and uses only that generator. No module shares random state with another. This ensures that adding a new module or changing one module's random usage does not affect other modules' outputs.

#### Validation of reproducibility

```python
def test_reproducibility():
    result1 = Simulator(config, seed=42).run()
    result2 = Simulator(config, seed=42).run()
    
    # Structural data must be bit-identical
    assert result1.patients == result2.patients
    assert result1.lab_values == result2.lab_values
    assert result1.vital_signs == result2.vital_signs
    assert result1.timestamps == result2.timestamps
    
    # LLM text: identical only if cache is shared
    # (without cache, text may differ but structure is the same)
```

### Testing strategy

Three levels of testing, each with a clear purpose.

#### Level 1: Unit tests (per module, fast, no dependencies)

Each module is tested in isolation with mock inputs.

```
tests/unit/
  test_physiology.py         # given state X → derive_lab_values → CRP in expected range
  test_observation.py        # noise stays within 3*CV bounds, missingness rates correct
  test_diagnosis.py          # Bayesian update: known LR + known prior → expected posterior
  test_treatment.py          # penicillin allergy → no penicillin selected
  test_nursing.py            # vitals jitter within bounds, MAR hold conditions correct
  test_order.py              # timing distributions within expected ranges
  test_population.py         # age/sex distribution matches target, household types valid
  test_patient.py            # baseline vitals within age/sex norms, allergy rates plausible
  test_staff.py              # shift schedule covers all hours, no gaps
  test_validator.py          # known violations detected, known valid data passes
  test_code_mapper.py        # internal name → LOINC/JLAC10 mapping correct
```

Key properties to test:
- **Determinism**: Same seed → same output. Always.
- **Bounds**: No lab value below 0, no SpO2 above 100, no negative timestamps.
- **Physiological plausibility**: CRP from inflammation_level=0.5 is in 5–15 range, not 500.
- **Coupling correctness**: renal_function=0.3 → K elevated, HCO3 reduced.

#### Level 2: Integration tests (module chains, medium speed)

Test that connected modules produce coherent data flows.

```
tests/integration/
  test_disease_to_observation.py
    # Load pneumonia protocol → select smooth_recovery →
    # run physiology for 14 days → generate labs →
    # verify: CRP rises Day 0-2, peaks, then declines over 14 days
    
  test_order_to_lab.py
    # Place admission lab orders → timing engine schedules collection →
    # at collection time: physiology provides state → observation adds noise →
    # verify: result timestamp > order timestamp > collection timestamp
    # verify: result value is physiologically plausible for current state
    
  test_encounter_daily_cycle.py
    # Run one inpatient day → verify:
    # morning vitals exist (06-08), rounds events (08-11),
    # afternoon meds (13-17), evening vitals (17-20), sparse night
    
  test_population_to_patient.py
    # Generate population → trigger disease event → activate Layer 2 →
    # verify: PatientProfile has all required fields,
    # family history matches household members' conditions
```

#### Level 3: End-to-end / golden file tests (full simulation, slow)

Run a complete simulation with a fixed seed and compare against stored "golden" CIF.

```
tests/e2e/
  test_golden_1patient.py
    # seed=42 → 1 pneumonia patient (alpha scenario) →
    # compare CIF JSON against tests/golden/seed42_1patient.json
    # Any structural change = test failure → investigate: intentional or regression?
    
  test_golden_10patients.py
    # seed=42 → 10 patients → compare against golden CIF
    
  test_benchmark_100patients.py
    # seed=42 → 100 patients → run Tier 1 statistical benchmarks →
    # all benchmarks pass (within ±20% of expected)
```

Golden file update process:
1. Run simulation with new code
2. If test fails: diff against golden file
3. If changes are intentional: update golden file, commit with explanation
4. If changes are unintentional: fix the regression

#### Test execution strategy

```
make test-unit          # < 30s. Run on every commit.
make test-integration   # < 5 min. Run on every PR.
make test-e2e           # < 30 min. Run on merge to main.
make test-all           # Everything.
```

---

### Implementation conventions

#### INTERFACES file splitting

`modules/INTERFACES.md` is a single design-phase document. At implementation, split into Python modules by domain:

```
clinosim/types/
  __init__.py              # re-exports all types for convenience
  population.py            # PersonRecord, Household, LifeEvent, CareSeekingDecision, PregnancyState
  patient.py               # PatientProfile, PatientPhysiologicalProfile, BaselineVitals, ADLScore, ...
  clinical.py              # PhysiologicalState, StateChangeDirective, DifferentialDiagnosis, ...
  encounter.py             # Encounter, Order, OrderTimeline, ClinicalEvent, ...
  staff.py                 # StaffProfile, StaffAssignment, PersonName, StaffRole
  device.py                # DeviceReading, POCTResult
  output.py                # CIFPatientRecord, CIFDataset, CIFMetadata
  llm.py                   # ClinicalEventData, PatientSummary, LLMTaskType, LLMResponse
  config.py                # HealthcareSystemConfig, HospitalProfile, SimulatorConfig
```

All types use `@dataclass` (or Pydantic `BaseModel` — see YAML validation below). Import via `from clinosim.types import PatientProfile`.

#### YAML configuration validation

All YAML configs must be validated at load time. Use **Pydantic** for both type validation and documentation:

```python
# Example: disease protocol validation
from pydantic import BaseModel, field_validator

class IncidenceConfig(BaseModel):
    base_rate_per_100k_per_year: dict[str, dict[str, float]]  # age_band → {M: rate, F: rate}
    risk_multipliers: list[RiskMultiplier]
    seasonal_curve: dict[int, float]  # month (1-12) → multiplier
    
    @field_validator("seasonal_curve")
    def validate_months(cls, v):
        assert set(v.keys()) == set(range(1, 13)), "Must have all 12 months"
        return v

class DiseaseProtocol(BaseModel):
    disease_id: str
    display_name: dict[str, str]
    icd_codes: ICDConfig
    incidence: IncidenceConfig
    severity: SeverityConfig
    # ... etc

# At load time:
protocol = DiseaseProtocol(**yaml.safe_load(open("bacterial_pneumonia.yaml")))
# → Immediate error if schema is violated, with clear message
```

Benefits:
- Invalid YAML fails immediately at load, not silently at runtime
- Schema serves as documentation
- IDE autocompletion and type checking
- Same models serve as both validation AND the runtime type

**Decision: Use Pydantic BaseModel for all config types. Use @dataclass for runtime-only types that aren't loaded from YAML.**

#### Configuration preset + override

Users should be able to start with a single preset and override specific values:

```python
class SimulatorConfig:
    @classmethod
    def preset(cls, name: str) -> "SimulatorConfig":
        """Load a named preset configuration."""
        presets = {
            "japan_medium": {"country": "JP", "hospital_scale": "medium", "catchment_population": 100_000},
            "japan_small": {"country": "JP", "hospital_scale": "small", "catchment_population": 20_000},
            "japan_large": {"country": "JP", "hospital_scale": "large", "catchment_population": 300_000},
            "us_medium": {"country": "US", "hospital_scale": "medium", "catchment_population": 100_000},
            # ... etc
        }
        return cls(**presets[name])
    
    def override(self, overrides: dict) -> "SimulatorConfig":
        """Apply dot-notation overrides: {"facility.bed_count": 250, "population.size": 80000}"""
        for key, value in overrides.items():
            set_nested(self, key, value)
        return self

# Usage:
config = SimulatorConfig.preset("japan_medium")
config.override({
    "time_range": ("2024-04-01", "2025-03-31"),
    "random_seed": 42,
    "disease_modules": ["bacterial_pneumonia"],
    "llm.mode": "template",  # no LLM for this run
})
sim = Simulator(config)
```

#### Async LLM calls

LLM calls are the dominant bottleneck (~500ms–5s each). Since patient simulations are independent in Mode 1, LLM calls can be parallelized.

**Strategy: async at the patient level, not the call level.**

```python
# In simulator main loop:
async def run_async(self) -> SimulationResult:
    # Population and setup are sequential
    population = self.population_module.generate()
    events = list(self.population_module.generate_all_events(population))
    
    # Patient simulations run concurrently (bounded concurrency)
    semaphore = asyncio.Semaphore(self.config.max_concurrent_patients)  # default: 10
    
    async def simulate_one(event):
        async with semaphore:
            return await self._simulate_hospital_visit_async(event, population)
    
    tasks = [simulate_one(e) for e in events if e.requires_hospital_visit]
    records = await asyncio.gather(*tasks)
    
    return SimulationResult(records=records, population=population)
```

At the llm_service level, the provider supports async:

```python
class LLMProvider(ABC):
    @abstractmethod
    def complete(self, prompt, model, max_tokens) -> ProviderResponse: ...
    
    @abstractmethod
    async def complete_async(self, prompt, model, max_tokens) -> ProviderResponse: ...

class BedrockGatewayProvider(LLMProvider):
    async def complete_async(self, prompt, model, max_tokens) -> ProviderResponse:
        async with httpx.AsyncClient() as client:
            response = await client.post(f"{self.gateway_url}/v1/complete", json={...})
            return ProviderResponse(**response.json())
```

**v0.1-alpha**: Synchronous only (simpler implementation).
**v0.1**: Add async support. Synchronous remains available as fallback.

---

### Internationalization (i18n) architecture

CIF internal data is **language-neutral** (codes, numeric IDs, standardized enums). Country/language-specific rendering happens at defined boundaries.

#### Four i18n layers

```
Layer 1: Person names       -- generated at population/staff creation time → stored in CIF
Layer 2: Clinical terms     -- mapped at output adapter time (code_mapping YAML)
Layer 3: Units & formatting -- applied at output adapter time (per-country format rules)
Layer 4: Narrative text     -- generated at Stage 2 by llm_service (target language)
```

#### Layer 1: Person names (population, staff)

Names are part of identity — generated once at creation, stored in CIF.

```
modules/population/names/
  japan.yaml          # surnames (weighted), given names (M/F, era-appropriate)
  us.yaml             # surnames (census), given names (M/F, decade-appropriate)

modules/staff/names/
  (same structure — may share with population)
```

Name structure by country:

| Country | Structure | Family name position | Formal display | Example |
|---|---|---|---|---|
| JP | family + given | First | 田中 太郎 | 田中 太郎 (Tanaka Taro) |
| US | given + family | Last | John Smith | John Smith |

Household naming rules:
- JP: All members share family name (except married women who may keep maiden name ~5%)
- US: Children take father's surname (typically); married couples may differ

Data type in CIF:
```python
@dataclass
class PersonName:
    family_name: str          # "田中" / "Smith"
    given_name: str           # "太郎" / "John"
    display_name: str         # "田中 太郎" / "John Smith" (country-formatted)
    name_script: str          # "ja" / "en" (script the name is written in)
    phonetic: str | None      # "タナカ タロウ" (JP: katakana; US: None)
```

#### Layer 2: Clinical terminology translation (output/code_mapping)

All internal codes use standardized systems (ICD-10, LOINC/JLAC10, RxNorm/YJ). Display names are mapped at output time from authoritative sources.

```
modules/output/code_mapping/
  mappings/
    diagnosis_icd10_ja.yaml     # ICD-10 → Japanese display names (厚労省標準病名マスター)
    diagnosis_icd10cm_en.yaml   # ICD-10-CM → English display names (CMS)
    lab_jlac10_ja.yaml          # JLAC10 → Japanese lab names (日本臨床検査標準協議会)
    lab_loinc_en.yaml           # LOINC → English lab names (Regenstrief)
    drug_yj_ja.yaml             # YJ code → Japanese drug names (医薬品マスター)
    drug_rxnorm_en.yaml         # RxNorm → English drug names (NLM)
    procedure_kcode_ja.yaml     # K-code → Japanese procedure names (診療報酬点数表)
    procedure_cpt_en.yaml       # CPT → English procedure names (AMA)
```

**Authoritative data sources (must not use LLM for translation):**

| Domain | Japan source | US source |
|---|---|---|
| Diagnosis names | 厚生労働省 標準病名マスター | CMS ICD-10-CM Official Guidelines |
| Lab test names | JLAC10 マスター (日本臨床検査標準協議会) | LOINC (Regenstrief Institute) |
| Drug names | 医薬品マスター (PMDA) | RxNorm (NLM) |
| Procedure names | 診療報酬点数表 (厚労省) | CPT (AMA) |

**Rule: Clinical terminology is NEVER translated by LLM. Always use official master data.**

#### Layer 3: Units and formatting (output/adapters)

Each output adapter applies country-specific formatting rules:

| Item | Japan | US |
|---|---|---|
| Temperature | ℃ (always Celsius) | ℃ or ℉ (facility-dependent; most use ℃) |
| Weight | kg | kg (clinical) or lb (patient-facing) |
| Height | cm | cm (clinical) or ft/in (patient-facing) |
| Date format | yyyy年MM月dd日 or yyyy/MM/dd | MM/dd/yyyy |
| Time format | 24h (14:30) | 12h (2:30 PM) or 24h |
| Number format | 1,234.5 | 1,234.5 (same) |
| Drug dose | mg, g (metric) | mg, g (same in clinical context) |

These rules live in the adapter, not in CIF. The same CIF produces correctly formatted output for any country.

#### Layer 4: Narrative language (llm_service)

Clinical narratives are generated in the target country's language during Stage 2.

- JP hospital → Japanese narratives ("38.5℃の発熱を認め、胸部X線にて右下葉浸潤影あり。")
- US hospital → English narratives ("Fever of 38.5°C with RLL infiltrate on CXR.")

JUDGMENT tasks always use English (AD-13). NARRATIVE tasks use `event.language`.

Template mode generates both JP and EN narratives from stock phrases.
LLM mode (Ollama/Claude) generates natural-language narratives in the specified language.

#### Architecture decision

| AD | Decision |
|---|---|
| AD-25 | CIF is language-neutral. Person names are the only country-specific data stored in CIF at generation time. All other localization (term translation, units, formatting, narratives) happens at output/Stage 2. |
| AD-26 | Clinical terminology (diagnosis, drug, lab, procedure names) uses official master data only. Never LLM-translated. Mapping YAML files cite authoritative source. |

---

### Condition-first simulation model

#### Principle: symptoms before diagnosis

In real hospitals, patients arrive with **conditions** (symptoms, signs, abnormal values), not diagnoses. The diagnosis is the **output** of the clinical process, not the input.

clinosim simulates this forward process:

```
Ground truth          Clinical process         EHR record
(hidden, in CIF)      (simulated)              (output)
                                               
Cause:                Presentation:            Admission Dx:
  known disease   -->   symptoms/signs    -->    "Pneumonia, unspecified"
  mixed causes    -->   overlapping Sx    -->    "Pneumonia" (may be wrong)
  unknown cause   -->   nonspecific Sx    -->    "Fever, unspecified"
                            |
                        Workup:
                          labs, imaging
                            |
                        Differential:
                          updated by results
                            |
                        Working Dx:             Progress notes:
                          may change            "Pneumonia suspected"
                            |
                        Final Dx:               Discharge Dx:
                          may differ from       "Pneumonia due to S. pneumoniae"
                          ground truth          (or "Fever, unresolved" in 10%)
```

#### Three types of condition generators

**Type 1: Known-cause condition**
A specific disease drives the state changes. This is the current model.
- Ground truth: bacterial_pneumonia
- State trajectory: follows disease YAML archetype
- Diagnosis process: clinical workup should converge on the correct disease
- Clinical accuracy: ~85% correctly diagnosed (tunable)

**Type 2: Mixed-cause condition**
Multiple diseases contribute simultaneously. Common in elderly.
- Ground truth: pneumonia + heart_failure_exacerbation (both active)
- State trajectory: superposition of both disease impacts
- Diagnosis process: one disease may mask the other. Initial diagnosis may be incomplete.
- Example: 80yo with cough, dyspnea, bilateral infiltrates. Is it pneumonia, HF, or both?
  CXR shows infiltrates (could be either). BNP elevated (HF?). CRP elevated (infection?).
  Diuretic trial partially helps (HF component). Antibiotics also help (infection component).
  Final dx: "Pneumonia with acute HF exacerbation" — both are real.

**Type 3: Unknown-cause condition**
State changes occur without a clear disease mechanism.
- Ground truth: `unknown` or `idiopathic_{symptom_pattern}`
- State trajectory: stochastic but physiologically constrained
- Diagnosis process: extensive workup, may remain undiagnosed
- Examples:
  - Fever of unknown origin (FUO): inflammation rises without clear cause
  - Unexplained weight loss in elderly
  - Nonspecific malaise with mildly elevated inflammatory markers
  - Drug fever (cause is iatrogenic, not disease)
- Final dx: "R50.9 Fever, unspecified" (unresolved at discharge in ~10% of cases)

#### Ground truth vs clinical diagnosis

```python
@dataclass
class ConditionEvent:
    """What actually happens to the patient (hidden ground truth)."""
    condition_id: str
    condition_type: str           # "known_disease" | "mixed" | "unknown"
    
    # For known_disease:
    ground_truth_diseases: list[str]  # ["bacterial_pneumonia"] or ["bacterial_pneumonia", "heart_failure_exacerbation"]
    
    # For unknown:
    symptom_pattern: str          # "fever_unknown" | "weight_loss" | "malaise"
    
    # State impact is applied regardless of type
    state_impacts: dict[str, float]   # combined impact from all causes
    
@dataclass 
class ClinicalDiagnosis:
    """What the hospital concludes (may differ from ground truth)."""
    admission_diagnosis: str      # ICD code at admission (often vague)
    working_diagnoses: list       # evolves over stay
    discharge_diagnosis: str      # ICD code at discharge (may still be vague)
    
    diagnosis_correct: bool       # does discharge dx match ground truth? (CIF hidden field)
    missed_diagnoses: list[str]   # ground truth diseases not identified
    overcalled_diagnoses: list[str]  # diagnosed but not actually present
```

#### Diagnostic accuracy parameters

Real-world diagnostic accuracy varies. clinosim models this as a tunable parameter:

| Parameter | Default | Meaning |
|---|---|---|
| `initial_correct_rate` | 0.60 | Probability that first working diagnosis is correct |
| `final_correct_rate` | 0.85 | Probability that discharge diagnosis matches ground truth |
| `missed_secondary_rate` | 0.30 | Probability of missing a secondary diagnosis in mixed cases |
| `fuo_rate` | 0.05 | Probability that a fever case remains undiagnosed |
| `incidental_finding_rate` | 0.08 | Probability of finding an unrelated condition during workup |

These can be adjusted to generate data at different "clinical quality" levels:
- **Real-world default**: matches published misdiagnosis rates
- **High-quality setting**: better than average (for ideal-scenario testing)
- **Low-quality setting**: more errors (for error-detection algorithm training)

#### Architecture decision

| AD | Decision |
|---|---|
| AD-28 | Condition-first model: patients present with symptoms, not diagnoses. Ground truth (hidden) may differ from clinical diagnosis (recorded). Three condition types: known-disease, mixed-cause, unknown-cause. |
| AD-29 | Diagnostic accuracy is a tunable parameter. Default matches real-world rates (~85% correct). Can be adjusted for different use cases. |

---

## 3. Two Simulation Modes

clinosim supports two simulation modes. Mode 2 is a superset of Mode 1.

### Mode 1: Patient Record Generation

Generates clinically coherent EHR records for individual patients. The hospital environment exists only as context for plausible record attribution (who ordered what, who performed what).

- **Focus**: One patient at a time, clinical consistency
- **Hospital resources**: Assumed available (no bed shortages, no OR scheduling conflicts)
- **Staff**: Assigned per event for record plausibility, but no shift/workload simulation
- **Use cases**: EHR development/testing, research datasets, algorithm validation, ML training data

### Mode 2: Hospital Operations Simulation

Simulates an entire hospital over a time period. Multiple patients exist concurrently, competing for shared resources (beds, OR slots, staff time). Produces both patient records and operational data.

- **Focus**: Hospital as a system, resource contention, temporal parallelism
- **Hospital resources**: Finite and constrained (bed occupancy, OR schedule, staffing levels)
- **Staff**: Full shift simulation, workload tracking, on-call rotation
- **Use cases**: Hospital management analysis, workflow optimization, capacity planning, staffing models

### Architectural implication

Modules are designed with Mode 2 in mind (the full model). Mode 1 runs the same modules but:
- Skips resource contention logic (beds always available, OR always open)
- Simplifies staff assignment (picks a plausible practitioner, ignores shift load)
- Runs one patient at a time instead of a concurrent population
- Omits operational event generation (no bed management events, no shift handoff records)

Each module's SPEC.md documents which behaviors are Mode 2–only.

---

## 3. Population-Driven Simulation Architecture

### Core principle

clinosim does **not** generate patients. It generates a **population**, lets people live, and observes what happens when they visit the hospital. This is the fundamental difference from other synthetic data generators.

```
Traditional approach:    patient → disease → hospital record    (backwards)
clinosim approach:       population → life events → hospital visit → record    (forward, like reality)
```

### Two-layer population model

Simulating every person in detail is computationally prohibitive. The population uses a two-layer model:

**Layer 1 — Population Registry (lightweight)**
- Every person in the catchment area exists here
- Stores: demographics, household, chronic conditions (summary), healthcare engagement profile
- Updated annually: aging, new chronic disease onset (probabilistic), death, migration
- Cost: ~100 bytes per person. 100,000 people ≈ 10 MB
- People who never visit the hospital stay in this layer forever

**Layer 2 — Active Patient (detailed)**
- Activated when a person visits the hospital (any encounter type)
- Full `PatientProfile` with physiological parameters, detailed medical history, baseline vitals
- Full clinical simulation: physiology, diagnosis, treatment, observations
- After discharge and follow-up completion, person returns to Layer 1 (but history is retained)
- Reactivated on next hospital visit (with all prior data intact)

```
Population Registry (Layer 1)
  │
  │ ← life event triggers care-seeking
  ↓
Active Patient (Layer 2) ──→ Encounter ──→ Clinical Simulation ──→ Record
  │
  │ ← discharge + follow-up complete
  ↓
Population Registry (Layer 1) [with updated health status]
```

### Household-based generation

People are not generated as isolated individuals. They belong to **households**:

- Households are generated first, then populated with members
- Household types: single elderly, elderly couple, nuclear family (parents + children), three-generation, single working adult, etc.
- Members share: address, family physician, insurance type (partially), genetic risk factors
- Infectious disease can transmit within households (e.g., influenza)
- Family relationships are explicit: enables "family history" to be real, not randomly generated
- Living situation (alone vs. family) is derived from household, not independently assigned

### Life event engine

The population evolves over simulated time through life events:

**Annual resolution (all population):**
- Aging (+1 year)
- New chronic disease onset (age/sex-specific incidence rates)
- Chronic disease progression (e.g., CKD stage 3 → stage 4)
- Death (age/sex-specific mortality rates)
- Migration (move in/out of catchment area)
- Employment changes (retirement, job change → insurance change)

**Stochastic events (continuous, checked monthly or on finer resolution):**
- Acute disease onset (season-dependent incidence)
- Accidents / trauma (age/activity-dependent)
- Acute exacerbation of chronic disease
- Pregnancy (if relevant to hospital services)

**Care-seeking decision (per event):**
- Each life event that produces symptoms is evaluated against the person's care-seeking threshold
- Decision factors: symptom severity, health literacy, time of day, day of week, insurance/cost, family influence
- Outcome: no action, self-care, outpatient visit, ER visit, or call ambulance

### Referral pathway

Most hospital patients arrive via referral, not directly:

```
Person with symptoms
  ├── Mild → local clinic / GP (かかりつけ医 / PCP)
  │     └── If beyond clinic capability → referral letter → this hospital
  ├── Moderate → this hospital outpatient (with or without referral)
  ├── Severe → this hospital ER
  └── Emergency → ambulance → this hospital ER
```

The referring clinic is not fully simulated — it is represented as:
- A referral source with basic info (clinic name, referring physician)
- Prior records summary (key findings that led to referral)
- This is sufficient for generating realistic referral letters and admission context

### Transient visitors

People outside the catchment area who need care:
- Generated as temporary additions to the population
- Typically present via ER (accident, acute illness while traveling/working)
- Limited prior medical history (no records at this hospital)
- After treatment: discharged back to home area or transferred
- Volume: ~5–10% of ER encounters (higher in tourist/business areas)
- No longitudinal follow-up (one-time encounter)

### Architecture decision record

| ID | Decision | Rationale |
|---|---|---|
| AD-3 | Population-driven forward simulation | Realism: the real world generates patients by population dynamics, not by hospital demand |
| AD-4 | Two-layer population model (registry + active) | Performance: only hospital visitors need full simulation |
| AD-5 | Household-based generation | Realism: family structure drives insurance, living situation, genetic risk, infection transmission |
| AD-6 | Referring clinic as context, not simulation target | Scope: full GP simulation is out of scope; referral letters and prior records are sufficient |

---

## 4. Folder Structure

```
clinosim/
├── DESIGN.md              ← This document (design guidelines)
├── TODO.md                ← Project-wide TODO tracking
├── spec.md                ← Original full spec (reference)
├── README.md              ← Project introduction
│
├── modules/
│   ├── INTERFACES.md      ← Core data type definitions (inter-module contracts)
│   ├── population/        ← Catchment area population, households, life events
│   │   ├── SPEC.md
│   │   └── ...
│   │
│   ├── facility/          ← Hospital facility definition (scale, departments, beds)
│   │   ├── SPEC.md
│   │   └── ...
│   │
│   ├── staff/             ← Healthcare staff generation, lifecycle & assignment
│   │   ├── SPEC.md
│   │   └── ...
│   │
│   ├── patient/           ← Layer 1 → Layer 2 activation & clinical detail
│   │   ├── SPEC.md        ← Module specification
│   │   └── ...            ← Implementation (future)
│   │
│   ├── encounter/         ← Encounter types & workflow state machines
│   │   ├── SPEC.md
│   │   └── ...
│   │
│   ├── order/             ← Order lifecycle (order → execute → result)
│   │   ├── SPEC.md
│   │   └── ...
│   │
│   ├── physiology/        ← Physiological state variables & state space
│   │   ├── SPEC.md
│   │   └── ...
│   │
│   ├── disease/           ← Disease definitions & event scheduling
│   │   ├── SPEC.md
│   │   └── ...
│   │
│   ├── diagnosis/         ← Diagnostic reasoning engine
│   │   ├── SPEC.md
│   │   └── ...
│   │
│   ├── clinical_course/   ← Clinical course engine (archetypes, state transitions)
│   │   ├── SPEC.md
│   │   └── ...
│   │
│   ├── treatment/         ← Medication & treatment model
│   │   ├── SPEC.md
│   │   └── ...
│   │
│   ├── observation/       ← Lab & vital signs generation (3-layer engine)
│   │   ├── SPEC.md
│   │   └── ...
│   │
│   ├── nursing/           ← Nursing process & care records
│   │   ├── SPEC.md
│   │   └── ...
│   │
│   ├── procedure/         ← Surgical & procedural workflows
│   │   ├── SPEC.md
│   │   └── ...
│   │
│   ├── validator/         ← Consistency validation
│   │   ├── SPEC.md
│   │   └── ...
│   │
│   ├── healthcare_system/ ← Healthcare system configuration (Japan / US)
│   │   ├── SPEC.md
│   │   └── ...
│   │
│   ├── llm_service/       ← LLM integration service (single point of LLM contact)
│   │   ├── SPEC.md
│   │   ├── prompts/       ← Prompt templates (YAML)
│   │   └── templates/     ← Template-mode fallback (no LLM)
│   │
│   └── output/            ← Data export (FHIR R4, CSV)
│       ├── SPEC.md
│       └── ...
│
└── simulator/             ← Main orchestrator
    ├── SPEC.md
    └── ...
```

### Required files per module folder

| File | Contents |
|---|---|
| `SPEC.md` | Module purpose, input/output definitions, confirmed specs, open questions |

### SPEC.md template

```markdown
# Module Name

## Purpose
What this module does (1–2 sentences).

## Inputs
- What it receives (data types, source modules)

## Outputs
- What it produces (data types, consumer modules)

## Dependencies
- Which modules it depends on

## Confirmed Specifications
(Append confirmed design decisions here)

## Open Questions
(Module-specific open questions)

## Design Notes
(Ideas and options under discussion)
```

---

## 5. Inter-Module Interface Conventions

### Data flow — Population-driven simulation

```
┌─── World Setup (once) ──────────────────────────────────┐
│                                                          │
│  healthcare_system ──→ facility ──→ staff (roster)       │
│          │                                               │
│          └──→ population (generate catchment area)       │
│                  │                                       │
│                  ├── households                          │
│                  └── person registry (Layer 1)           │
└──────────────────────────────────────────────────────────┘

┌─── Time Simulation (continuous) ────────────────────────────────────────┐
│                                                                          │
│  population ──→ life events (disease onset, accident, aging, ...)       │
│       │              │                                                   │
│       │         care-seeking decision                                    │
│       │              │                                                   │
│       │         ┌────┴─── YES: visit hospital ───┐                      │
│       │         │                                 │                      │
│       │    patient (Layer 1 → Layer 2 activation) │                      │
│       │         │                                 │                      │
│       │    encounter ──→ clinical_course ──→ observation ──→ validator   │
│       │         │              ↑                  ↑              │       │
│       │      order ←─── diagnosis            treatment          │       │
│       │         │              │                  │              │       │
│       │      procedure     nursing               │              │       │
│       │         │              │                  │              │       │
│       │         └── staff (assign per event) ─────┘              │       │
│       │                                                          │       │
│       │    disease (protocols) ──────────────────────────────────┘       │
│       │                                                                  │
│       │    ──→ output (FHIR / CSV)                                      │
│       │                                                                  │
│       │    ──→ discharge ──→ Layer 2 → Layer 1 (with updated history)   │
│       │                                                                  │
│       └── NO: person stays in Layer 1 (no hospital data generated)      │
│                                                                          │
│  Mode 2 adds: bed contention, OR scheduling, staff workload, queues     │
└──────────────────────────────────────────────────────────────────────────┘
```

### Interface design principles

1. **Modules communicate via dataclasses / TypedDicts**
   - Each module's SPEC.md defines the types of its inputs and outputs
   - Implementation uses Python `dataclass` or `TypedDict`

2. **`healthcare_system` is a cross-cutting parameter provider**
   - Every module can receive country-specific parameters from it
   - `healthcare_system` itself has no dependencies on other modules

3. **`facility` defines the institutional context; `staff` populates it**
   - `facility` determines hospital scale, departments, and bed counts
   - `staff` generates practitioners and manages assignment to clinical events
   - Every EHR-recorded event must carry consistent staff attribution
   - `staff` assignment is called by the simulator at event generation time

4. **`encounter` controls the workflow; `order` manages the lifecycle of actions within it**
   - `encounter` defines the type of visit (outpatient, ED, inpatient, etc.) and the state machine governing its progression
   - `order` manages the order → execute → result cycle for all clinical actions (labs, imaging, medications, procedures)
   - `nursing` generates nursing-specific events (assessments, vital sign schedules, care records)
   - `procedure` handles surgical/procedural workflows (pre-op, operation, post-op recovery)
   - In Mode 1, encounter/order run without resource constraints
   - In Mode 2, encounter/order interact with facility resource management (bed allocation, OR scheduling, staff availability)

5. **`disease` provides protocol definitions**
   - Lab protocols, treatment protocols, and course patterns are defined in YAML
   - Engine modules reference disease definitions to drive their behavior

6. **`simulator` handles orchestration**
   - Manages execution order and dependency resolution across modules
   - Mediates data flow between modules
   - In Mode 1: processes one patient at a time
   - In Mode 2: runs a discrete-event simulation with concurrent patients

---

## 4. Design Workflow

### Principles

- **1 module = 1 context**: Design sessions focus on a single module at a time
- **Interface-first**: Define inputs/outputs before internal implementation
- **Record decisions immediately**: Write confirmed specs into SPEC.md as soon as agreed
- **Track open questions explicitly**: Both in TODO.md and in module SPEC.md

### Design priority order

1. Agree on inter-module interfaces (input/output types) across all modules
2. Then flesh out internal design of each module individually
3. Disease-specific configs (YAML) are added incrementally per disease

---

## 5. Naming Conventions

| Target | Convention | Example |
|---|---|---|
| Module folder | snake_case | `clinical_course/` |
| Python file | snake_case | `state_engine.py` |
| Class name | PascalCase | `PatientProfile` |
| State variable | snake_case | `inflammation_level` |
| Config file | snake_case.yaml | `pneumonia.yaml` |
| FHIR Resource id | type-encounter-suffix | `lab-ENC-POP-000001-000123-0042` |
| Code system key | lowercase-with-hyphens | `icd-10-cm`, `loinc`, `k-codes` |

---

# Part 6 — Architecture Updates (v0.1-beta, 2026-04-08)

This part documents major architectural decisions made after the initial v0.1-alpha
foundation. They are integrated into the live codebase but recorded here as ADRs for
historical reference.

## 6.1 Code System Module (`clinosim/codes/`)

### Problem

Initially, terminology files (e.g., ICD code → display name) lived under
`clinosim/locale/jp/terminology_diagnosis.yaml` and similar paths. This created two
issues:

1. **Misclassification**: ICD-10-CM is an international standard, not a culture-specific
   data set. Putting it under `locale/jp/` implied locale-scoped ownership when actually
   it's the same code values, just translated.
2. **Translation duplication**: When supporting JP and US, the same ICD code had
   separate entries in two files. Updating one but not the other led to mismatches.
3. **CIF redundancy**: `ClinicalDiagnosis` stored both `discharge_diagnosis_code` and
   `discharge_diagnosis_name`. The name was a derivative of the code + locale, but
   stored separately, allowing them to drift.

### Decision (AD-30, AD-33, AD-35)

Create a new `clinosim/codes/` module that is **locale-independent** and serves as the
single source of truth for clinical code systems.

```
clinosim/codes/
├── __init__.py          # public API
├── loader.py            # lookup() with language fallback
├── README.md            # module documentation
└── data/
    ├── icd-10-cm.yaml   # 224 codes, all with EN, most with JA
    ├── icd-10.yaml      # WHO version (110 codes)
    ├── loinc.yaml       # 59 codes
    ├── jlac10.yaml      # 30 codes
    ├── rxnorm.yaml      # 68 codes
    ├── yj.yaml          # 39 codes
    ├── cpt.yaml         # 25 codes
    └── k-codes.yaml     # 2 codes
```

### Schema

```yaml
metadata:
  name: "ICD-10-CM"
  uri: "http://hl7.org/fhir/sid/icd-10-cm"   # FHIR canonical system URI
  version: "2024"
  description: "..."

codes:
  N10:
    en: "Acute tubulo-interstitial nephritis"   # REQUIRED
    ja: "急性腎盂腎炎"                          # optional
  J18.9:
    en: "Pneumonia, unspecified organism"
    ja: "肺炎，詳細不明"
```

### Principles

1. **English-first**: Every code MUST have an `en` field. Other languages are optional
   translation attributes. The loader falls back to English if a requested language
   is missing, then to the code itself.

2. **Authoritative sources**: Code values and English text follow official definitions
   from CMS (ICD-10-CM), NLM (RxNorm), Regenstrief (LOINC), AMA (CPT), WHO (ICD-10),
   JCCLS (JLAC10), MHLW (YJ codes, K codes).

3. **Locale-independent**: `codes/` is at the same level as `locale/`, NOT inside it.
   Code systems are international standards.

4. **Single lookup API**:
   ```python
   from clinosim.codes import lookup, get_system_uri
   lookup("icd-10-cm", "N10", "en")  # → "Acute tubulo-interstitial nephritis"
   lookup("icd-10-cm", "N10", "ja")  # → "急性腎盂腎炎"
   get_system_uri("loinc")           # → "http://loinc.org"
   ```

### Impact on CIF

`ClinicalDiagnosis` was simplified — `*_name` fields removed, `*_system` added:

```python
# Before
@dataclass
class ClinicalDiagnosis:
    admission_diagnosis_code: str
    admission_diagnosis_name: str          # ← removed
    discharge_diagnosis_code: str
    discharge_diagnosis_name: str          # ← removed

# After
@dataclass
class ClinicalDiagnosis:
    admission_diagnosis_code: str
    admission_diagnosis_system: str = "icd-10-cm"   # ← added
    discharge_diagnosis_code: str
    discharge_diagnosis_system: str = "icd-10-cm"   # ← added
```

`ChronicCondition.name` was similarly removed. Display text is now resolved by output
adapters (FHIR, CSV, narrative) calling `clinosim.codes.lookup()` at output time.

### Locale module after migration

`clinosim/locale/` now contains only **culture/country-dependent** data:

- `names.yaml` — person name generation (kanji + reading for JP, given/family for US)
- `addresses.yaml` — 47 prefectures / 50 states + ZIP code patterns
- `demographics.yaml` — population age distribution, disease incidence rates
- `formatting.yaml` — date and unit formatting rules
- `reference_range_lab.yaml` — JCCLS / Tietz lab reference ranges
- `code_mapping_*.yaml` — internal test name → standard code (kept here because the
  internal name "WBC" is a clinosim implementation detail, not a standard)

The old `terminology_*.yaml` files were removed.

---

## 6.2 FHIR Bulk Data Export NDJSON (AD-31)

### Problem

The original FHIR R4 adapter wrote one Bundle JSON file per encounter
(`ENC-POP-XXXXXX-NNNNNN.json`). This worked but had drawbacks:

1. **File explosion**: 153,530 files for a 60k catchment hospital
2. **Wrapping overhead**: each Bundle had `Bundle.entry[]` wrapping that was redundant
3. **Resource id duplication**: vital sign IDs collided across patient encounters
   (`vs-{patient_id}-0000-heart_rate` recurred per encounter)
4. **Not standard format**: real EHR vendors (Epic, Cerner) export via FHIR Bulk Data
   Access spec (NDJSON files per resource type), not as per-patient bundles

### Decision (AD-31)

Replace per-encounter Bundle output with HL7 FHIR Bulk Data Access compliant NDJSON:

```
output/fhir_r4/
├── manifest.json                           # Bulk Data manifest
├── _facility.json                          # Org + Location master Bundle
├── Patient.ndjson                          # 1 patient per line
├── Encounter.ndjson                        # 1 encounter per line
├── Observation.ndjson                      # labs + vitals (LOINC)
├── Condition.ndjson                        # ICD-10-CM
├── MedicationRequest.ndjson                # RxNorm
├── MedicationAdministration.ndjson         # MAR
├── Procedure.ndjson                        # CPT
├── AllergyIntolerance.ndjson               # patient-level
├── Practitioner.ndjson                     # staff master
├── PractitionerRole.ndjson                 # specialty + ward
├── Organization.ndjson                     # hospital + departments
└── Location.ndjson                         # wards + beds
```

### Resource id uniqueness

A critical FHIR R4 invariant: `Resource.id` MUST be unique within its resource type.
The old per-encounter Bundle approach hid violations because each Bundle was
self-contained. Once aggregated into NDJSON, collisions became visible.

Fixed by including `encounter_id` in resource ids:

- Lab obs: `lab-{encounter_id}-{seq}` instead of `lab-{patient_id}-{seq}`
- Vital obs: `vs-{encounter_id}-{seq}-{field}`
- MAR: `mar-{encounter_id}-{seq}`
- MedRequest: `{encounter_id}-{order_id}` (prefixed)
- Procedure: `{encounter_id}-{procedure_id}` (prefixed)
- Condition (encounter dx): `cond-{encounter_id}-primary`
- Condition (chronic): `cond-{encounter_id}-chronic-{idx}`

Patient-level resources (Patient, Practitioner, AllergyIntolerance) are deduplicated
in the NDJSON writer rather than re-emitted.

### Manifest format

Follows the [HL7 FHIR Bulk Data Access spec](https://hl7.org/fhir/uv/bulkdata/):

```json
{
  "transactionTime": "2026-04-08T17:30:00",
  "request": "clinosim generate (country=US)",
  "requiresAccessToken": false,
  "output": [
    {"type": "Patient", "url": "Patient.ndjson"},
    {"type": "Encounter", "url": "Encounter.ndjson"},
    ...
  ],
  "error": []
}
```

This format is consumable by any FHIR client expecting Bulk Data export, including
Epic and Cerner integration tools.

### Size impact

For US 50-bed hospital, catchment 30k, 1 year:
- Old format: 153,530 files, 5.7 GB total
- New format: 13 files, 1.3 GB total (-77% size reduction from JSON wrapping removal)

---

## 6.3 Snapshot Date Semantics (AD-32)

### Problem

The simulator generated all encounters that fell within the simulation period to
completion (every encounter had `discharge_datetime` set). This produced "all patients
discharged" datasets, which don't reflect a real EHR snapshot where some patients are
currently admitted.

For visualization tools and AI models trained on EHR snapshots (e.g., NEWS2 alert
systems for currently admitted patients), this was a significant gap.

### Decision (AD-32)

Introduce **snapshot date** semantics:

- `--end YYYY-MM-DD` flag = the snapshot date (defaults to today)
- `--start YYYY-MM-DD` defaults to `--end - 1 year`
- No life events generated past the snapshot date
- Inpatients whose `discharge_datetime` would fall after the snapshot date are
  truncated:
  - `Encounter.status = "in-progress"`
  - `discharge_datetime = None`
  - `discharge_disposition = ""`
  - `discharging_physician_id = ""`
  - Lab/vital/order/MAR records filtered to ≤ snapshot day
  - Discharge prescription not issued
- Primary `Condition.clinicalStatus = "active"` for in-progress encounters (vs
  `resolved` for completed ones)
- Death is exempt from this rule (deceased patients are always "completed" with
  `dischargeDisposition = "exp"`)

### Result

A typical 50-bed hospital with avg LOS 5 days and ~3 admissions/day produces ~15
in-progress encounters at any point in time (~30% occupancy). With higher catchment
and longer LOS, this approaches realistic 80% bed occupancy.

This enables generating realistic EHR snapshots for:
- NEWS2 / early warning alert systems
- Bed management dashboards
- Real-time clinical decision support training data

---

## 6.4 Hospital Configuration-Driven Layout (AD-34)

### Problem

Hospital physical layout (which departments exist, which wards belong to which
specialty, how many beds per ward) was hardcoded or randomly assigned. This created:

1. **Inconsistent FHIR data**: encounters claimed to be in non-existent wards
2. **Staffing mismatches**: PractitionerRole specialties didn't match Encounter
   serviceType
3. **No bed capacity model**: no way to enforce occupancy limits

### Decision (AD-34)

Hospital configuration YAML defines the complete physical and organizational layout:

```yaml
# clinosim/config/hospital_operations.yaml (50-bed hospital)
recommended_population: 60000

available_departments:           # specialties this hospital supports
  - internal_medicine
  - cardiology
  - gastroenterology
  - general_surgery
  - orthopedics
  - emergency_medicine
  - primary_care

department_rollup:               # specialty → available department mapping
  pulmonology: internal_medicine    # disease YAML says pulmonology, hospital says IM
  neurology: internal_medicine
  neurosurgery: general_surgery
  trauma_surgery: general_surgery

wards:                           # which wards each department uses
  internal_medicine: ["4E", "4W"]
  cardiology: ["5E"]
  gastroenterology: ["5W"]
  general_surgery: ["3E"]
  orthopedics: ["3W"]
  emergency_medicine: ["ER"]
  primary_care: ["OPD"]

ward_capacity:                   # bed count per ward
  "4E": 10
  "4W": 10
  "5E": 8
  "5W": 8
  "3E": 8
  "3W": 6
```

### Cascading effects

1. **Disease → department resolution**: `disease.department` (granular) is rolled up
   via `department_rollup` to one of `available_departments`. So a `pulmonology` disease
   in a hospital that doesn't have pulmonology gets routed to `internal_medicine`.

2. **Staff generation**: `generate_roster()` creates physicians ONLY for
   `available_departments`. Nurses are distributed across `wards` (each ward gets
   ~6 nurses, scaled by `ward_capacity`).

3. **Bed assignment**: When an encounter is created, `bed_number` is sampled from
   `1..ward_capacity[ward_id]`. No more random "601-3" bed numbers.

4. **FHIR Location resources**: `_facility.json` contains one `Location` per ward
   (physicalType=wa) and one per bed (physicalType=bd, partOf the ward). Encounter
   references the bed Location, which references the ward via `partOf`.

5. **PractitionerRole.location**: nurses are assigned to a ward in their roster entry,
   which is reflected in PractitionerRole.location reference.

This means hospital templates (`hospital_operations.yaml` for 50-bed,
`hospital_small.yaml` for 10-bed) are now genuinely different hospitals, not just
size labels.

---

## 6.5 Updated module list

The current module count has grown beyond v0.1-alpha:

```
clinosim/
├── codes/                  ★ NEW (AD-30, AD-33, AD-35)
├── locale/
├── config/
├── types/
├── modules/
│   ├── disease/            (32 disease YAMLs)
│   ├── encounter/          (46 ED/outpatient YAMLs)
│   ├── physiology/
│   ├── clinical_course/
│   ├── diagnosis/
│   ├── observation/
│   ├── order/
│   ├── procedure/          ★ NEW (was empty, now 15 bedside procedures)
│   ├── population/
│   ├── patient/
│   ├── staff/              (ward-aware after AD-34)
│   ├── facility/           ★ NEW README (M/M/1 queueing)
│   ├── healthcare_system/
│   ├── output/             (Bulk Data NDJSON after AD-31)
│   ├── llm_service/
│   └── validator/
└── simulator/              (orchestration: engine, inpatient, emergency, outpatient)
```

Each module has its own README.md with API reference and design notes.

---

## 6.6 Realistic vital sign measurement patterns

### Problem

Initial implementation generated all 6 vital signs (T, HR, BP, RR, SpO2) at every
measurement time, with the same timestamp. This was unrealistic:

- Outpatient HTN visit: only BP and HR are measured (not all 6)
- Continuous monitoring: HR and SpO2 every 1-2h, but full vitals only q6h
- Same timestamp for all 6 fields is implausible (BP cuff and thermometer aren't
  simultaneous)

### Decision

1. **Inpatient**: separate routine full vitals (q4h–q8h based on acuity) from
   continuous monitoring (HR + SpO2 only every 2h for unstable/respiratory patients)
   plus event-driven recheck (T-only re-measurement after fever).

2. **Outpatient**: vital subset by visit type and chronic condition:
   - HTN/DM/IHD followup: BP + HR
   - HF: BP + HR + weight + SpO2
   - COPD: BP + HR + SpO2 + RR
   - Annual physical: full set

3. **Per-field timestamp offset** (in FHIR adapter):
   - HR / BP simultaneous (same device cycle)
   - SpO2: +5s
   - Temperature: +30s
   - RR: +60s

This produces NEWS2-compatible vital data while remaining clinically plausible.

---

## 6.7 NEWS2 / early warning vital data

To support NEWS2 (National Early Warning Score 2) alert systems, vitals now include:

- **AVPU consciousness level** (Alert / Voice / Pain / Unresponsive)
  - LOINC code 80288-4
  - SNOMED concept value (248234008 for Alert, etc.)
  - Inferred from `state.perfusion_status` and disease type

- **Supplemental oxygen flow rate** (L/min)
  - LOINC code 3151-8
  - Includes oxygen delivery device (nasal_cannula, simple_mask, non-rebreather)
  - Activated based on SpO2 < 92 or respiratory disease

These two additional Observation types are emitted alongside standard vitals when
applicable. NEWS2 score can be computed from any in-progress encounter's latest
observations.

---

## 6.8 Updated ADR list (Part 6 additions)

| ADR | Date | Title |
|---|---|---|
| AD-28 | 2026-04-06 | Diagnosis vs ground truth separation (ConditionEvent vs ClinicalDiagnosis) |
| AD-29 | 2026-04-06 | Diagnostic accuracy via likelihood ratios (Bayesian update) |
| AD-30 | 2026-04-08 | Code is the truth: CIF stores codes only, no display text |
| AD-31 | 2026-04-08 | FHIR Bulk Data Export NDJSON (replacing per-encounter Bundle) |
| AD-32 | 2026-04-08 | Snapshot date semantics with in-progress encounters |
| AD-33 | 2026-04-08 | English-first principle for code systems |
| AD-34 | 2026-04-08 | Hospital config-driven physical layout (departments, wards, beds) |
| AD-35 | 2026-04-08 | codes module separated from locale (international standards) |
| AD-36 | 2026-04-09 | FHIR Procedure structural fields via SNOMED CT (category, performer.function, bodySite, outcome, complication) |
| AD-37 | 2026-04-09 | Three explicit CLI stages: generate → narrate → export-fhir |
| AD-38 | 2026-04-09 | Clinical documents as FHIR DocumentReference (Tier A+B scope, LOINC-coded) |
| AD-39 | 2026-04-09 | LLM provider plugin registry + YAML-driven factory |
| AD-40 | 2026-04-09 | Prompt templates externalized as per-language YAML files |
| AD-41 | 2026-04-09 | SHA256 disk cache for LLM responses (reproducibility + cost control) |
| AD-42 | 2026-04-13 | Code-side unit conversion for Japanese locale (CRP mg/L → mg/dL in extractor/generator, not LLM prompt) |
| AD-43 | 2026-04-13 | Japanese narrative prompt quality rules (「医師」 suffix, 【】 section headers, no markdown) |
| AD-44 | 2026-04-15 | Enrichment is language-neutral (English structured data; LLM translates at output time) |
| AD-45 | 2026-04-15 | Occupation field on Patient/PersonRecord (12 categories; drives work-related injury incidence) |
| AD-46 | 2026-04-16 | Multilingual FHIR coding (Condition/Procedure emit dual coding: primary + interop language) |
| AD-47 | 2026-04-16 | FHIR Observation referenceRange + interpretation consistency (FHIR R5 Note 5) |
| AD-48 | 2026-04-16 | procedure_name removed from CIF (display resolved at output via code_lookup, AD-30 strict) |
| AD-49 | 2026-04-18 | Condition code.text with clinical abbreviations (_CONDITION_SHORT_NAME: COPD, CHF, CKD, DM, AF; coding[].display keeps official ICD name) |
| AD-50 | 2026-04-18 | Medication protocol prefix stripping (_strip_protocol_prefix removes DVT_prophylaxis:, antipyretic: from medicationCodeableConcept.text) |
| AD-51 | 2026-04-10 | YAML-driven medication_holds in disease protocols (replaces hardcoded disease_id lists in simulator) |
| AD-52 | 2026-04-10 | Country-specific recommended_population in hospital config (US: 40K, JP: 10K for 50-bed) |
| AD-53 | 2026-04-10 | Staff name resolution in narrative prompts (hospital.json roster → display names) |
| AD-54 | 2026-06-15 | Country-pluggable resident identifier & insurance numbering module (`modules/identity/`) |
| AD-55 | 2026-06-15 | EHR data enrichment split: near-essential data in Base (always-on, extends core), specialized/optional data in opt-in modules. **2026-06-25 PR3b-1 supplement** — third category formally added: **always-on Module = near-essential clinical cascade**. Modules where omission would produce a clinically incoherent state (e.g. `HAI present without antibiotic treatment`) violating CLAUDE.md clinical-coherence principle. Such modules register with `enabled=lambda c: True` and are no-ops only when the upstream `extensions[X]` slot they consume is empty. Examples: `device` (PR-A), `hai` (PR-B), `antibiotic` (PR3b-1). Distinguished from the **opt-in pattern** reserved for truly optional data (e.g. JP `identity` — only relevant if JP insurance numbering is desired) and from the original **Base** pattern that uses typed fields on the core record type. Selection rule when adding a new module: if its data would always be expected given upstream cascade, choose always-on; if it depends on a configuration flag at the simulator level (country, region, business arrangement), choose opt-in; if it extends a near-universally-emitted FHIR resource type, prefer Base typed-field. **2026-06-26 PR3b-2 = HAI culture S/I/R susceptibility chain**: second increment of the Phase 3b series. `modules/hai/_append_hai_culture()` extended with antibiogram-driven susceptibility sampling using `load_hai_antibiogram()` (new export in `modules/hai/__init__`). Data source: `reference_data/hai_antibiogram.yaml` (CDC NHSN AR 2018-2020), format `{hai_type: {organism_snomed: {antibiotic_key: [S, I, R]}}}`, import-time validated against `HAI_TYPES` + `hai_organisms.yaml` + `ANTIBIOTIC_LOINC_LOOKUP`. RNG uses existing HAI per-patient sub-rng (no new RNG stream; AD-16 preserved). Forward-compat: `MicrobiologyResult.hai_event_id` backref (links culture back to HAIEvent for PR3b-3 cross-reference) and `AntibioticRegimen.discontinuation_datetime` (reserve for PR3b-3 de-escalation) both added as typed fields. `ANTIBIOTIC_DRUGS` refactored tuple → `dict[str, dict[str, str]]` with `ANTIBIOTIC_LOINC_LOOKUP` as a new LOINC-lookup companion. LOINC orphan fix: `ciprofloxacin: "18879-7"` in `microbiology.yaml` was actually Cefepime → corrected to `18906-8` (NLM verified); `loinc.yaml` companion fix adds Ciprofloxacin `18879-7` with correct label + Cefepime `18906-8`. `run_forced` in `simulator/engine.py` now injects `scenario` into `config.forced_scenarios` when `force_hai_event is not None`, closing the silent-no-op gap discovered during Task 6. DQR: `docs/reviews/2026-06-26-phase-3b-2-hai-susceptibility-data-quality-review.md`. |
| AD-56 | 2026-06-15 | Extensibility foundation (Phase 0): FHIR resource-builder registry, simulator enricher registry, CIF extensions slot for modules, config module-enablement map. **PR1 2026-06-24 foundation refactor** added `clinosim/simulator/seeding.py:ENRICHER_SEED_OFFSETS` central registry for all enricher sub-seed offsets (7 modules: identity + microbiology grandfathered as decimals; immunization / code_status / family_history / care_level / nursing use 16-bit hex ASCII convention). Module-level assert catches accidental duplicate offsets at import. New enrichers register here and import via `ENRICHER_SEED_OFFSETS["my_module"]`. See CLAUDE.md "AD-55 enricher patterns" subsection + `docs/CONTRIBUTING-modules.md` for the contributor playbook. **PR2 2026-06-24 G2 SDOH integrity refactor** further established the "データ専用モジュール (variant)" pattern (`modules/sdoh/` — reference data + loader only, no enricher / no ENRICHER_SEED_OFFSETS entry — `clinosim/codes/` is the preexisting precedent); also split `_fhir_sdoh.py` into `_fhir_smoking_alcohol.py` + `_fhir_care_level.py` for single-responsibility separation, and promoted `_social_category` / `_value` helpers to `_fhir_common.py` for future SDOH builder reuse. **PR_docs 2026-06-24 comprehensive documentation update** added `MODULES.md` (top-level module map with 22-module inventory + dependency tree + typical call chains), `SCENARIO_FLAGS.md` (central reference for scenario + medication flags routed through `derive_lab_values`), `.github/TEMPLATE_MODULE_README.md` (standardized module README template), and "Consumers" sections to all 22 module READMEs for reverse-dependency visibility. Also extended `docs/CONTRIBUTING-modules.md` with PR verification guide (byte-diff vs 3-axis DQR decision matrix; the project's TRUE goal is FHIR R4 + JP Core compliance + 臨床整合性 + JP language quality, byte-diff is a refactor-PR mechanic only) and absorbed original G4 typed-field-vs-extensions decision tree. **PR3 2026-06-24 G3 Observation-family split** (final structural piece of the foundation refactor series) extracted the four unrelated builders inside `_fhir_observations.py` (727 lines / 31 KB) into three new per-theme files matching PR2's precedent: `_fhir_microbiology.py` (Specimen + Observation + DiagnosticReport), `_fhir_nursing.py` (NEWS2/GCS/Braden/Morse/Barthel/I&O survey Observations), `_fhir_immunization.py` (CVX Immunization). The residual `_fhir_observations.py` (~380 lines) is now the canonical numeric Observation builder (lab helper + vital builder). Pure mechanical refactor — all 33 NDJSON files (US 16 + JP 17) byte-identical to master for US p=2000 + JP p=2000, seed=42. Clears the runway for device + HAI feature builders to land in clean per-theme files (`_fhir_device.py` / `_fhir_hai.py`) without inheriting a multi-theme blob. **PR-A device module 2026-06-24** added Phase 1 of the device + HAI 4-PR series: `modules/device/` (AD-55 Module post_records enricher emitting CVC + indwelling catheter + mechanical ventilator on inpatient ICU encounters with state-based placement criteria), `_fhir_device.py` builder file (Device + DeviceUseStatement), `clinosim/types/device.py` (`DeviceRecord` dataclass under `extensions["device"]`), and `ENRICHER_SEED_OFFSETS["device"] = 0x4445`. SNOMED CT codes (`52124006` CVC / `23973005` Indwelling urinary catheter / `706172005` Ventilator) verified via tx.fhir.org `$expand` text-search; spec's tentative `467021000` replaced with the verified `23973005` (PR #80 LOINC `2B010` fabrication precedent applied). 3-axis DQR PASS at US p=10000 + JP p=5000: 353 + 20 devices respectively, all structural checks 100%, line-days within plausible bands. byte-diff supplement confirms zero regression on pre-existing NDJSON (AD-16 invariant). Phase 2 PR-B (`modules/hai`) will consume `extensions["device"]` for CLABSI/CAUTI/VAP onset sampling. **PR-B hai module 2026-06-24** added Phase 2 of the device + HAI 4-PR series: `modules/hai/` (AD-55 Module post_records enricher at order=80, consumes PR-A `extensions["device"]` line-days and samples CLABSI/CAUTI/VAP onsets via CDC NHSN baseline per-line-day risk rates 0.0010/0.0014/0.0015), `_fhir_hai.py` builder (HAI Condition only — cultures emit through the existing `_fhir_microbiology.py` builder via `record.microbiology.append(...)` with zero new wiring), `clinosim/types/hai.py` (`HAIEvent` dataclass under `extensions["hai"]`), and `ENRICHER_SEED_OFFSETS["hai"] = 0x4841`. Codes verified: 3 ICD-10-CM (T80.211A / T83.511A / J95.851) via NLM API; 3 WHO ICD-10 (T80.2 / T83.5 / J95.8); 3 HAI SNOMED (736442006 CLABSI / 68566005 UTI generic / 429271009 VAP — spec's tentative 433142000 + 425500004 not in SNOMED CT International, $expand verified replacements). 3-axis DQR PASS at US p=10000 + JP p=5000: US 4 HAI (3 CAUTI + 1 VAP) within Poisson 2σ of expected ~3.2; JP 0 HAI acceptable rare-event. First clean example of the cross-module enricher consumption pattern. **Phase 3a 2026-06-25 POST_ENCOUNTER stage** introduced a third enricher stage to `clinosim/simulator/enrichers.py` (alongside `POST_POPULATION` and `POST_RECORDS`): runs **per-encounter, immediately after the daily loop completes** but **inside** the encounter simulator. Migrated `device` (order=70) and `hai` (order=80) from `POST_RECORDS` to `POST_ENCOUNTER` because their sampling depends on full clinical course outcomes (`record.icu_transferred`, GCS, perfusion) that are only known after the daily loop — and their output (HAI events) needs to be visible to same-encounter post-processing. AD-55 Module classification now distinguishes **"encounter-bound Module"** (device/hai — POST_ENCOUNTER) from **"cross-record Module"** (nursing/immunization/family_history/code_status/care_level/sdoh — POST_RECORDS). Phase 3a then added `clinosim/modules/hai/lab_lift.apply_hai_lab_lift` which walks `extensions["hai"]` after the daily loop and adds a forward-delta lift to existing WBC + CRP `obs.value` using per-day state_history snapshots; this preserves the original noise + circadian while injecting the deterministic HAI inflammatory effect. byte-diff PASS: all 37 NDJSON files byte-identical at US p=2000 + JP p=2000 (HAI is Poisson rare-event at this size); the lift fires at p=10000 DQR with the expected clinical relative-delta. The forward-delta pattern is reusable for Phase 3b (antibiotic-day decay) and Phase 3c (Lactate / Plt / Temp / SBP sepsis cascade). |
| AD-57 | 2026-06-16 | Unify lab/vital generation across venues (inpatient/ED/outpatient) into one physiology-driven service (planned); replaces hardcoded ED/outpatient baselines. **Phase 3a 2026-06-25 forward-delta extension** — `modules/hai/lab_lift.apply_hai_lab_lift` adds the 4th example of the BNP-pattern surgical formula approach (after BNP wall-stress, D-dimer Phase 2a, PT_INR Phase 2b): instead of mutating `state` or re-running `derive_lab_values` for affected days, the post-encounter step computes `delta = derive(state_snap, lift>0) - derive(state_snap, lift=0)` on the per-day state_history snapshot and adds the delta to existing `obs.value`, preserving original noise + circadian. Future-proof for Phase 3b/c sepsis cascade (Lactate / Plt / Temp / SBP) and antibiotic-day decay using the same forward-delta pattern. |
| AD-62 | 2026-06-30 | **Imaging metadata-only chain with WADO-RS placeholder.** |
| AD-63 | 2026-07-01 | **Document narrative + structured event density foundation. Two new always-on POST_RECORDS Modules (allergy / document, order 65/95), 3 FHIR builders (DocumentReference / Composition / ClinicalImpression), 17-check lift_firing_proof. Closes Stage 1 document-density gap (DR 0→23,760, Comp 0→9,275, CI 0→23,760 US p=10k).** |
| AD-60 | 2026-06-25 | **clinosim audit framework.** Unified verification gate built as a `clinosim/audit/` package + CLI subcommand (`clinosim audit run/smoke/list`). Absorbs the previous 3-axis DQR scratchpad scripts and adds a fourth **silent_no_op** axis (canonical-constants cross-check + lift-firing proof) specifically designed to catch the PR-90 class of bug (case-mismatch silent no-op that left the entire Phase 3a HAI lift no-op'd in production while test green + byte-diff PASS + DQR cohort PASS still held). Architecture: `clinosim/audit/registry.py` (ModuleAuditSpec dataclass + register_audit_module + discover) + `clinosim/audit/engine.py` (AuditEngine orchestrates module × axis matrix) + `clinosim/audit/axes/` (4 axes: structural / clinical / jp_language / silent_no_op) + `clinosim/audit/reporter.py` (Markdown). Per-Module checks live in `clinosim/modules/<name>/audit.py` and side-effect-import register_audit_module(spec) at discovery; new Modules get all 4 axes for free by declaring `structural_obs_codes`, `clinical_acceptance`, `canonical_constants` + `yaml_keys_to_validate`, and `lift_firing_proof`. Phase 1 ships only `modules/hai/audit.py` (the absorption point for scratchpad/phase3a_lift_fired_proof.py). byte-diff vs master @ p=2000 seed=42 confirms 37/37 NDJSON byte-IDENTICAL — the audit framework is a pure read-only consumer of generated output, no simulation-path imports leaked, AD-16 preserved. First self-audit baseline report: `docs/reviews/2026-06-25-clinosim-audit-baseline.md`. byte-diff stays separate as a refactor-PR mechanic; the audit framework is for new-feature / realism PRs. See `docs/CONTRIBUTING-modules.md` "PR 検証ガイド" for the decision matrix. **2026-06-25 PR3b-1 = second per-Module plug-in**: `modules/antibiotic/audit.py` adds the second concrete plug-in after `hai`. Its `lift_firing_proof` drives the actual enricher path (`enrich_antibiotic`) against a synthetic CAUTI HAIEvent and asserts the closed-form Ceftriaxone q24h × 7d delta (1 regimen, 1 MedicationRequest, 7 MARs, first/last at exact expected datetimes). `clinosim audit list` now reports 2 modules with the same 4-axis matrix, confirming the framework's repeatability. **2026-06-26 PR3b-2 audit framework expansion**: `modules/antibiotic/audit.py` extended with (1) `_ABX_LOINCS` frozenset of 8 susceptibility LOINCs for structural axis Observation.code coverage; (2) `_NHSN_RESISTANCE_BANDS` metadata (CLABSI MRSA 40-55%, CAUTI ESBL 12-22%, VAP MRSA 30-45%) and `HAI_EMPTY_SUSCEPTIBILITIES_MAX_RATE = 0.05` — wired to clinical axis active enforcement in PR3b-3 (2026-06-27, per-(hai_type, antibiotic) R-rate gate + per-HAI cohort empty-rate gate + per-hai_type narrow-rate gate, each `n<30 → WARN` for rare-event safety); **PR3b-3 D1+D2 (2026-06-29, PR #112) completed the chain** by adding `_organism_per_encounter` (per-(hai_type, organism, antibiotic) R-rate filter) and `_panel_eligible_organisms` (panel-eligible empty-rate denominator via `load_hai_antibiogram()` keys — auto-excludes E.faecalis / C.albicans), removing both `# TODO(post-PR3b-3)` markers; (3) `antibiogram_firing_proof` using PR-94 `equality_checks` format — drives `_append_hai_culture()` against a synthetic CLABSI S. aureus record and asserts Vancomycin susceptibility = S via `ANTIBIOTIC_LOINC_LOOKUP["vancomycin"]` (not hardcoded LOINC), closing the same silent-no-op class of bug for the susceptibility chain. |
| AD-58 | 2026-06-17 | **Output-format adapter registry.** CIF→format adapters self-register via `register_output_adapter` (`clinosim/modules/output/adapter.py`); the CLI is registry-driven (`available_formats()` / `get_adapter()`). Adding a format (SS-MIX, FHIR R3, HL7 v2) = add one `OutputAdapter` (`format_id`/`description`/`subdir`/`convert`) — no CLI or core edits. Built-in CSV/FHIR-R4 are thin wrappers (output unchanged). Adapters depend only on CIF + `clinosim.codes` + `clinosim.locale` (AD-17/AD-25). Evolution path: setuptools entry-point discovery for external plugin packages. |
| AD-59 | 2026-06-23 | **Per-order lab RNG isolation.** Every lab order — panel children and individual scalar orders alike — draws its specimen-rejection / hemolysis / technician-assignment / observation-noise RNG from a per-order sub-stream, not from the patient-scoped master RNG. Panel children use `panel_specimen_seed(parent_order_id)` (modeling "one specimen per parent order"); individual non-panel orders use `individual_lab_seed(order_id)` (one specimen per order). Both live in `clinosim/simulator/seeding.py`. The structural property this preserves: editing a `{test:"X"}` line in a disease/encounter YAML, or extending `derive_lab_values` to produce a new analyte, **cannot** shift unrelated patients' cohorts via the master stream — completing what AD-16 requires across all lab paths in `inpatient.py` Pass 1, `emergency.py`, and `outpatient.py`. Established progressively: PR #74 introduced `panel_specimen_seed` for panel children; PR #78 added `individual_lab_seed` for the remaining individual lab paths; the Coag panel PR (2026-06-24) is the first follow-up to add new analytes (APTT / PT / Fibrinogen) through this isolation — byte-diff vs master @ p=2000 seed=42 confirms zero shift in unrelated NDJSONs on both US and JP. Phase 2a (2026-06-24, D-dimer + `causes_vte`) is the second follow-up: byte-diff again confirms zero shift in the 9 unrelated NDJSONs, plus the same PR introduces a `scenario_flags_from_protocol(protocol)` helper that centralizes every `derive_lab_values` scenario-flag read so future flags reach all `derive_lab_values` call sites (inpatient Pass-1 + lagged + emergency + outpatient) through one helper edit. Phase 2b (2026-06-24, `on_warfarin` PT_INR therapeutic-band override) extends the flag-helper pattern with a sibling `medication_flags_from_context(patient, medication_orders, admission_date, current_day)` that detects chronic + in-hospital warfarin use without any RNG draw — preserving AD-59 isolation while adding medication → lab coupling as a reusable pattern (future: steroid → glucose, diuretic → K, antibiotic → CRP). Call sites merge both helper dicts via `{**scenario_flags, **medication_flags}` to keep flag additions one-edit-safe (J5-prevention extended). Byte-diff vs master @ p=2000 seed=42 confirms 8 of 9 NDJSONs sha256-identical; only Observation changes (same-count, PT_INR/PT value shift for warfarin-detected patients only). Integration guards: `tests/integration/test_individual_lab_isolation.py` (analyte) + `tests/integration/test_medication_flags_isolation.py` (medication flag). |

---

## 6.9 Resident identifier & insurance numbering (AD-54)

### Problem

Layer-1 residents and Layer-2 patients carried no payer identity beyond an
internal MRN. Realistic EHR/claims data requires the patient's **insurance
enrollment** (被保険者番号 / member id, 保険者番号 / insurer number, 記号 / group
symbol, 枝番 / branch number) and — for Japan — the My-Number card / マイナ保険証
state. These are **country-specific**, **household-correlated**, and
**time-varying**, so they cannot be hardcoded.

### Key domain facts (drove the design)

- The 12-digit My Number (個人番号) is **not** stored in clinical EHRs by law
  (number use is limited to social-security/tax/disaster). Even when a マイナ保険証
  is presented, the provider receives the **insurance qualification**, never the
  raw 個人番号. → My Number is a Layer-1 simulation attribute only; clinical
  outputs (FHIR/CSV) must **not** emit it.
- The EHR/claims identifier is the **被保険者番号 + 保険者番号**, represented in FHIR
  as a **`Coverage`** resource (`subscriberId`, `payor` → insurer Organization),
  not as a `Patient.identifier` slice (consistent with JP Core's design).
  - **JP Core Coverage mapping (verified against jpfhir.jp/fhir/core):**
    記号/番号/枝番 → `JP_Coverage_InsuredPersonSymbol` / `…InsuredPersonNumber` /
    `…InsuredPersonSubNumber` extensions (valueString); `subscriberId` = `記号:番号`;
    `dependent` = 枝番; `identifier.value` = `保険者番号:記号:番号:枝番`
    (system `JP_Insurance_memberID`); `payor` → Organization with
    `jp-insurer-number-namingsystem` identifier (= 保険者番号). Mandatory: `status`,
    `beneficiary` (1..1), `payor` (1..*). Canonical URIs stored in
    `locale/jp/identity.yaml:fhir_coverage`.
  - **FHIR conformance details:** payor Organization carries `type` coding
    `organization-type#pay` and a real insurer **name** resolved from
    `locale/jp/identity.yaml:payers` (number → name at output; AD-30 — display text
    never stored in CIF). `Coverage.relationship` = `self` (subscriber) / `other`
    (被扶養者). `Coverage.type` is a text-only CodeableConcept (Japanese scheme label;
    no fabricated codes). Representative payers carry valid 検証番号 / check digits.
    US export emits **no** `Coverage` (no JP insurance leakage).
- 記号 sharing granularity differs by scheme: 社保 (employee) shares 記号 at the
  **employer (事業所)** level; 国保 shares at the **household** level; 後期高齢者
  (75+) is **per-individual**.
- "My-Number assignment" for a long-standing patient changes the **qualification
  verification method** (紙 → online) but **not** the 被保険者番号. The data that
  actually changes over time is the **payer** (転職/退職, and the deterministic
  **75-yr → 後期高齢者** transition). Hence insurance is modeled as a
  **period-bounded enrollment history**, and each encounter references the
  enrollment valid on its date (`Coverage.period`).

### Decision

A new leaf-ish module `clinosim/modules/identity/` owns numbering:

- `base.py` — `IdentityProvider` Protocol (country-pluggable seam; interface only)
- `registry.py` — `country → provider` resolution (mirrors `healthcare_system`)
- `generators.py` — check-digit number generators (国共通 pure functions)
- `providers/jp.py` — JP rules (employer-level 記号, 社保/国保/後期高齢, 枝番,
  card/保険証 dated flags, 75-yr transition)
- `providers/us.py` — thin (existing `_sample_insurance` behavior preserved)

Adding a country = new `providers/<cc>.py` + `locale/<cc>/identity.yaml`; no engine
changes (same philosophy as disease/encounter YAMLs).

**Determinism (AD-16):** numbering runs as a **separate pass after population
generation**, using a **dedicated sub-seed Generator** so the existing random
stream (and golden files) are untouched.

**Privacy chokepoint:** `national_id` may live in CIF/`PersonRecord` for future
マイナ-workflow extensibility, but output adapters carry a **sensitive-field
default-exclude** policy — FHIR/CSV never emit `national_id` unless explicitly
opted in.

### Defaults (locale/jp/identity.yaml — researched, `# TODO: verify` where provisional)

- マイナンバーカード保有率 (age-banded): 0–14 ≈0.70, 15–49 ≈0.77, 50s ≈0.82,
  60s ≈0.90, 70s ≈0.91 (peak), 80+ ≈0.72 (総務省/デジタル庁 2025)
- マイナ保険証 登録率: lower, same age shape (peak 60–70s)
- 世帯内相関は `household_icc` (Gaussian-copula preserving marginal card rates)
- **被用者保険 vs 国保 は occupation-driven**: the household's most-likely-employed
  working-age member becomes the 被保険者 (others 被扶養者) via
  `employee_probability_by_occupation`. Calibrated so the emergent <75 split is
  ≈ 73:27 (MHLW 医療保険 基礎資料), with `insurance_category_distribution` as fallback.
- **マイナ保険証 marginal**: registration is conditional on card holding at rate
  `ins_rate/card_rate`, so the population linked marginal = configured `ins_rate`.
- **`insurance_type` unified**: for JP, `PatientProfile.insurance_type` is set from the
  enrollment `category` (single source of truth → consistent CSV/Coverage; was empty before).

### Phasing

1. Module skeleton + JP numbering + snapshot single enrollment + Coverage + payor Org
2. Period-bounded enrollment history + 75-yr transition + `Coverage.period`
3. Employment transitions (light probabilistic) + card/保険証 dates + verification method
4. US compat tests + docs/ADR finalize

---

## 6.10 EHR data enrichment split — Base vs Module (AD-55)

### Principle

When adding EHR data classes (benchmarked against Synthea / USCDI v5 / MIMIC-IV):

- **Base** — data that a realistic EHR essentially *always* carries (and that is cheaply
  derivable from the existing physiology / clinical-course state). Generated on **every
  run** by extending the **existing core** (`types/`, `population`, `observation`,
  `simulator/*`, `output`). No new opt-in module, no flag.
- **Module** — specialized or optional data. Implemented as an **opt-in, pluggable
  module under `clinosim/modules/`** (same pattern as `identity`: own README +
  Dependencies, types in `types/`, FHIR built in the `output` module reading CIF,
  dedicated sub-seed, gated by a CLI flag / config). **One module per theme**
  (e.g. billing, devices, care-coordination) — never a catch-all "extras" module,
  consistent with the existing one-theme-per-module layout.

Avoid over-modularizing: small near-universal *attributes* (family history, code status,
extended SDOH) live in Base as patient/encounter fields, not as their own modules.

### Scope guard (carried from the enrichment research)

Imaging / modality-dependent data is **out of scope** (CT/MRI/X-ray/US, echo, ECG
tracings, endoscopy findings, spirometry, pathology). Lab/bedside/administrative data is
in scope (clinosim already derives labs from physiology, so the same applies to
microbiology, blood gas, cardiac markers, nursing flowsheets).

### Classification

| Tier | Data | Lives in |
|---|---|---|
| Base | Microbiology + susceptibility; lactate / ABG / cardiac markers; `DiagnosticReport` grouping; nursing flowsheets (I/O, NEWS2, pain, GCS, Braden); immunization history; family history; code status / advance directive; extended SDOH (incl. JP 要介護度) | core: `types`, `population`, `observation`, `simulator`, `output` |
| Module | Billing (`modules/billing/` — JP DPC / US Claim+EOB); Devices + HAI (`modules/device/` — CLABSI/CAUTI/VAP); Care coordination (`modules/care_coordination/` — CarePlan/CareTeam/Goal) | one opt-in module per theme |

See `TODO.md` for the phased implementation plan.

---

## 6.11 Extensibility foundation — Phase 0 (AD-56)

### Problem

Adding a new FHIR resource type or opt-in module currently requires editing several
central hot spots, so the AD-55 roadmap (8 Base items + 3 modules) would touch the same
monoliths repeatedly:

- `output/fhir_r4_adapter.py` `_build_bundle()` (~3,000-line file) — every new resource
  is hand-appended into one function, plus the dedup set.
- `simulator/engine.py` `run_beta()` — every post-population pass is inlined (e.g.
  `if config.jp_insurance_numbers: assign_identities(...)`), order-sensitive.
- `types/output.py` `CIFPatientRecord` — fixed dataclass; every new data class adds a field.
- `types/config.py` `SimulatorConfig` — one boolean per opt-in module.

### Decision — do these enabling refactors *before* the AD-55 enrichment work

1. **FHIR resource-builder registry.** A registry of builders `(record, ctx) -> list[resource]`;
   the core loop iterates and emits. Each builder declares its dedup behaviour
   (patient-level vs per-encounter). New resource = register a builder (co-located with its
   domain) — no edit to `_build_bundle`.
2. **Simulator enricher registry.** Post-population passes register with
   `name` / `order` / `enabled(config)` / `run(...)`; `run_beta` iterates in declared order.
   New module = register an enricher — no edit to `run_beta`. **Order is explicit and fixed
   to preserve determinism (AD-16).**
3. **CIF extensions slot.** Add `CIFPatientRecord.extensions: dict[str, Any]`. **Base** data
   keeps typed fields (Base *is* core); **Modules** write to `extensions[<module>]` and never
   edit the core type — module independence enforced at the type level (aligns with AD-55).
4. **Config module-enablement map.** `SimulatorConfig.modules: dict[str, bool]` +
   `module_enabled(name)` helper; `jp_insurance_numbers` kept as a back-compat alias.
   Per-module structured config (e.g. billing country options) lives in its own block.

Secondary: externalize the `observation` lab catalog (CV / precision / units) to YAML
(done alongside the microbiology Base item). CSV adapter registry is **deferred** (low
leverage — a new table is ~3 lines).

### Constraint

These refactor working code. Regression is gated by the existing golden / e2e suites and
determinism (AD-16): any change in resource emission order or RNG draw order must be proven
equivalent, not a true regression.

---

## 7. Clinical documents via FHIR DocumentReference

### Problem

Before Milestone 1 (early 2026-04-09), clinosim had no way to produce narrative clinical
documents as first-class FHIR resources. The legacy `narrative_generator` wrote loose
JSON files under `cif/narratives/<version>/patients/*.json`, but these never made it into
the FHIR Bulk Data export. Downstream consumers had patient, encounter, observation, and
procedure resources but no discharge summary, no operative note, no admission H&P — the
exact documents clinicians use to read and review a patient's story.

This gap was blocking:
- Readmission prediction and outcome research (discharge summary is the primary data source)
- Mortality review (death note is a legal document for every inpatient death)
- Surgical quality analysis (operative note is CMS §482.51-mandated)
- NLP/LLM training pipelines that expect clinical notes as DocumentReference resources

### Decision (AD-36, AD-37, AD-38)

**AD-36 — FHIR Procedure gets structural fields via SNOMED CT.**
Every `Procedure.ndjson` entry now includes:
- `category` — SNOMED 387713003 (surgical) / 103693007 (diagnostic) / 277132007 (therapeutic)
- `performer[].function` — SNOMED 304292004 (surgeon) / 158967008 (anaesthetist)
- `recorder` — Practitioner reference (defaults to surgeon)
- `reasonReference` — link to the encounter's primary Condition
- `bodySite` — SNOMED anatomy code
- `location` — Operating room Location reference (surgeries only)
- `outcome` — SNOMED 385669000 (successful) / 385670004 (partial) / 385671000 (unsuccessful)
- `complication` — SNOMED codes mapped from `ProcedureRecord.intraop_complications`

`clinosim/codes/data/snomed-ct.yaml` contains the minimal SNOMED subset required for
these fields, following the English-first principle (AD-33).

**AD-37 — Three explicit CLI stages: `generate` → `narrate` → `export-fhir`.**
Stage 1 (`generate`) produces the structural CIF. Stage 2 (`narrate`) generates clinical
documents from an existing CIF and writes them to `cif/narratives/<version>/documents/`.
Stage 3 (`export-fhir`) reads the CIF (and optionally a narrative version) and emits the
FHIR NDJSON files, including `DocumentReference.ndjson` when a narrative version is
provided.

Rationale:
- **Reproducibility (AD-16)** — Stage 1 is deterministic from seed. Stage 2 has
  reproducibility via prompt cache (AD-41). Stage 3 is a pure function of CIF.
- **Cost isolation** — Stage 2 is the only stage that may call a paid LLM API. On a
  host without network access to the LLM (e.g. a laptop that cannot reach Bedrock), the
  CIF directory can be shipped to an EC2 instance for Stage 2 only, then pulled back for
  Stage 3.
- **Experimentation** — multiple narrative versions from the same structural CIF can
  coexist and be compared (template vs Ollama vs Bedrock, English vs Japanese, prompt
  version 1 vs 2).
- **CIF stays the single source of truth (AD-17, AD-30)** — structural/ is immutable,
  narratives/ is a replaceable layer.

**AD-38 — Clinical documents as FHIR DocumentReference (Tier A+B scope).**
clinosim produces these documents out of the box:

| Tier | Document | LOINC | Per-encounter count | Justification |
|---|---|---|---|---|
| A | Discharge Summary | 18842-5 | 1 per inpatient | CMS §482.24 mandated for every discharge |
| A | Death Note | 69730-0 | 1 per death | Legal document; M&M review |
| A | Operative Note | 11504-8 | 1 per surgical procedure | CMS §482.51 mandated |
| B | Admission H&P | 34117-2 | 1 per inpatient | Standard US admission documentation |
| B | Procedure Note | 28570-0 | 0..N per inpatient | Only for invasive bedside procedures with clinical significance |

Procedure Note scope is restricted to **eight invasive bedside procedures** that require
a formal note: `central_line`, `lumbar_puncture`, `thoracentesis`, `paracentesis`,
`chest_tube`, `intubation`, `bronchoscopy`, `cardioversion`. Lower-complexity bedside
procedures (urinary catheter, NG tube, echocardiography, blood transfusion, dialysis,
arterial line, wound debridement) are documented in nursing or ancillary records and do
not produce a separate DocumentReference.

Progress Note (LOINC 11506-3) is **reserved for a future Tier C scope** because real-world
progress notes are ~80% redundant with structured vitals/labs/MAR data and generating them
at every hospital day would inflate token cost by an order of magnitude for minimal
incremental research value.

### Storage format: narrative CIF

A new type `ClinicalDocument` (in `clinosim/types/clinical.py`) represents one clinical
document. It is written as one JSON file per document under:

```
cif/narratives/<version_id>/documents/<encounter_id>/<task_type>[_suffix].json
```

Each file contains:
- **Identity** — document_id, task_type, LOINC code
- **References** — patient_id, encounter_id, author_practitioner_id, related_procedure_id
- **Timing** — authored_datetime, period_start, period_end
- **Content** — language, content_type, text
- **Provenance** — text_source (llm/template/cache/none), llm_model, llm_provider,
  input/output tokens, prompt_version, cache_hit, generated_at, fallback_reason

The document_generator extracts a deterministic list of facts (via
`hospital_course_extractor`) for each encounter and passes them as `${variables}` to the
LLM prompt. This keeps the LLM honest: it narrates facts rather than inventing them.

### FHIR DocumentReference mapping

```
DocumentReference.id          = <document_id>
  .status                     = "current"
  .docStatus                  = "final" (or "preliminary" for template fallback)
  .type.coding                = LOINC code + display (resolved via clinosim.codes)
  .category                   = us-core-documentreference-category: clinical-note
  .subject                    = Patient/<patient_id>
  .date                       = authored_datetime
  .author                     = Practitioner/<author_practitioner_id>
  .content[0].attachment
      .contentType            = text/plain; charset=utf-8
      .language               = en | ja
      .data                   = base64(text)
      .size                   = byte length
      .hash                   = base64(sha1(text))
  .context.encounter          = Encounter/<encounter_id>
  .context.period             = { start, end }
  .context.related            = Procedure/<related_procedure_id>  (operative/procedure)
```

Empty documents (Stage 1 stubs with no Stage 2 text) are **not emitted** — a
DocumentReference with empty attachment data is useless to downstream consumers and
would violate the FHIR profile implied by attaching a `clinical-note` category.

---

## 8. LLM service architecture: pluggable providers + YAML prompts

### Problem

The Milestone 0 `llm_service` supported only local Ollama and had all prompts hardcoded
in `engine._build_prompt()`. Adding a new provider required editing `engine.py`, adding
a new language required editing Python code, and adding a new document type required
both. Bedrock was not implemented at all. There was no response cache, so re-running
Stage 2 always re-invoked the LLM.

### Decision (AD-39, AD-40, AD-41)

**AD-39 — LLM provider plugin registry.**
Providers live in `clinosim/modules/llm_service/providers/` as a subpackage. Every
provider implements the `LLMProvider` Protocol (structural typing, no inheritance):

```python
class LLMProvider(Protocol):
    def complete(self, prompt, model, max_tokens, system_prompt,
                 temperature=0.4, stop_sequences=None) -> ProviderResponse: ...
    def health_check(self) -> bool: ...
```

A registry in `providers/__init__.py` maps provider keys (`ollama`, `bedrock`, `mock`,
`local`) to builder callables. Third-party code can extend the registry via
`register_provider(name, builder)` without touching clinosim source.

A new `factory.build_from_config_file(path)` reads `llm_service.yaml`, builds the
appropriate providers for the `judgment:` and `narrative:` sections, and returns a fully
wired `LLMService`. The Bedrock provider lazy-imports `boto3`, so users who never touch
Bedrock do not need to install it.

**AD-40 — Prompt templates as per-language YAML files.**
Prompts live under `clinosim/modules/llm_service/prompts/<language>/<task_type>.yaml`:

```yaml
task_type: discharge_summary
version: 1
max_tokens: 2000
temperature: 0.4
system: |
  You are an attending physician writing a comprehensive discharge summary ...
user_template: |
  Patient: ${age}yo ${sex}
  Admission date: ${admission_date}
  ...
```

`PromptRegistry.get(task_type, language)` loads and caches specs lazily. Rendering uses
Python's standard-library `string.Template` (zero external dependencies) with
`substitute()` on the user template (raises on missing keys — fail loud) and
`safe_substitute()` on the system prompt (natural-language content may contain
accidental `${...}` sequences).

Language fallback mirrors the codes module behavior: if `ja/<task>.yaml` is missing, the
registry falls back to `en/<task>.yaml` and logs via the PromptSpec's `language` field.

Rationale:
- **Clinician-editable** — non-programmers can improve prompt quality without touching
  Python code.
- **Language addition is a folder, not a PR review** — adding German means creating
  `prompts/de/*.yaml`, no engine changes.
- **Versioning + A/B testing** — the `version:` field is recorded on each generated
  document, enabling reproducibility and controlled rollouts.
- **JUDGMENT English-only invariant (AD-13)** is enforced at the yaml-tree level: only
  put English prompts under judgment tasks.

**AD-41 — SHA256 disk cache for LLM responses.**
`PromptCache` in `clinosim/modules/llm_service/cache.py` stores one JSON file per cached
response, keyed by `SHA256(system || user || model)`. Entries are written by
`LLMService._llm_generate` after a successful provider call and read before every
provider call when the cache is enabled.

Rationale:
- **Reproducibility (AD-16)** — re-running Stage 2 with the same inputs and same seed
  produces byte-identical output.
- **Cost control** — Bedrock Claude Sonnet runs on 5,000-patient datasets cost on the
  order of $1–5 per run; cache hits make re-runs free.
- **Partial re-run recovery** — if Stage 2 is interrupted mid-run, resuming only
  re-invokes the LLM for documents that were not yet cached.

Cache location defaults to `<cif>/narratives/<version>/cache/` or an explicit
`cache.directory` in the YAML config. Cache is disabled for template and mock modes.

### Data model: LLMService.generate

`LLMService.generate(task_type, event, variables=None)` is the single entry point for
all modules. `variables` is the new parameter that routes to PromptRegistry; when None,
the legacy `_build_prompt` hardcoded path is used (kept for backward compatibility with
admission H&P / discharge summary template code).

The returned `LLMResponse` now carries:
- `source` — `llm` | `template` | `cache` | `none`
- `input_tokens` / `output_tokens`
- `prompt_version` — from the PromptSpec
- `cache_hit` — True when served from `PromptCache`
- `fallback_reason` — populated on template fallback with a short error tag
- `provider` — the configured provider key (e.g. `bedrock`) for provenance

All of these are recorded on the `ClinicalDocument.generation` block and propagate into
the narrative CIF manifest, enabling per-document cost analysis and audit.

---

## Part 9: Japanese narrative localization (2026-04-13)

### AD-42: Code-side unit conversion for Japanese locale

CIF stores lab values in SI units (CRP in mg/L). Japanese clinical convention uses mg/dL for CRP.
Rather than asking the LLM to convert (which was inconsistent), conversion happens in code:

- `hospital_course_extractor.format_lab_trends(trends, language="ja")` applies `_JA_CONVERSION` factors
- `document_generator._initial_labs(record, language="ja")` applies the same conversion
- `_JA_CONVERSION = {"CRP": 0.1}` — multiply mg/L by 0.1 to get mg/dL
- Prompts say "use input units as-is" — no LLM-side conversion

This is extensible: add entries to `_JA_CONVERSION` and `_UNIT_MAP_JA` for other locale-specific units.

### AD-43: Japanese narrative prompt quality rules

All 5 Japanese prompts (`prompts/ja/*.yaml`) enforce:

1. **Staff name suffix**: "医師名には必ず「医師」を付けてください" — prevents inconsistent Dr./no-prefix output
2. **Unit passthrough**: "検査値の単位は入力データのまま使用してください" — prevents LLM from annotating "(換算値)" or showing conversion work
3. **No fabrication**: all prompts prohibit inventing data not present in input (consistent with EN prompts)

### Chronic medication base code fallback

`chronic_medications.yaml` keys are specific ICD codes (e.g., `E11.9`). After discharge,
`_deactivate_to_layer1()` normalizes codes to base form (`E11`). The medication lookup in
`inpatient.py` now falls back to base code:

```python
spec = chronic_meds.get(code) or chronic_meds.get(code.split(".")[0])
```

This matches the existing fallback in `activator.py:326` and prevents medication loss on readmission.

### JP FHIR localization summary

The FHIR R4 adapter applies Japanese localization when `country="JP"`:

| Resource | Field | JP value |
|---|---|---|
| Location | name | `4E病棟`, `4E-01号室` |
| Encounter | type | `入院`, `外来`, `救急` |
| Encounter | serviceType | `内科`, `外科`, etc. |
| Patient | maritalStatus | `既婚`, `未婚` |
| MedicationRequest | dosageInstruction.route | `経口`, `静注`, `皮下注` |
| MedicationRequest | dosageInstruction.timing | `1日1回`, `1日2回`, `6時間毎` |
| Practitioner | qualification | `医師` |

All localization is at FHIR output time (AD-30). CIF remains language-neutral.

---

## Part 10: FHIR standards compliance + occupational injuries (2026-04-19)

### AD-44: Enrichment is language-neutral

A/B test on 8 patients × 2 document types (admission_hp, discharge_summary) confirmed:

| Aspect | A (pre-localized JP) | B (English, LLM translates) |
|--------|---------------------|---------------------------|
| Drug/procedure names | Both correct | Both correct |
| Natural Japanese flow | Slightly mechanical | More natural |
| CRP unit | Correct (mg/dL) | **Wrong** (mg/L leaked) |
| Diagnosis short names | Correct | ICD full names (unnatural) |
| Token usage | 9,219 | 9,231 (≈ identical) |

**Conclusion**: LLM translates free text well, but fails at math (CRP) and code normalization
(ICD display). Keep code_lookup + CRP conversion only. Everything else English.

### AD-45: Occupation model

```
PersonRecord.occupation: str  →  PatientProfile.occupation: str
                                  ↓
                         FHIR Observation (LOINC 11341-5, social-history)
```

Categories: manufacturing, construction, agriculture, healthcare, service, office,
transportation, education, homemaker, student, retired, unemployed, other.

`demographics.yaml` provides:
- `occupation_distribution.working_age` — per-country labor statistics
- `occupation_risk_multipliers` — per-injury-type risk by occupation (e.g. crush_injury_hand × 6.0 for manufacturing)

### AD-46: Multilingual FHIR coding

Condition and Procedure resources emit dual `coding[]` entries:

```json
{
  "coding": [
    {"system": "icd-10", "code": "J44.1", "display": "その他の慢性閉塞性肺疾患"},
    {"system": "icd-10", "code": "J44.1", "display": "Other chronic obstructive pulmonary disease"}
  ],
  "text": "COPD（慢性閉塞性肺疾患）"
}
```

`_build_diagnosis_codeable_concept()` tries `icd-10` → falls back to `icd-10-cm` → `"(display unavailable)"`.
`code.text` uses `_CONDITION_SHORT_NAME` for search-friendly abbreviations (AD-49).

### AD-47: Observation referenceRange + interpretation consistency

Per FHIR R5 Note 5: "The interpretation should be consistent with the reference range when both
are provided."

- Lab interpretation recomputed from value vs normal range (not CIF flag alone)
- Critical flags (H*/L*/critical) → directional LL/HH (not generic AA)
- Vital signs emit two referenceRange entries: `type=normal` and `type=treatment` (critical/panic)
- SpO2: `crit_high=None` (no upper critical — 100% is normal, not HH)

### AD-48: procedure_name removed from CIF

Strict AD-30 compliance: `ProcedureRecord` no longer has `procedure_name` field.
Display is resolved at output time via `code_lookup("k-codes"|"cpt", code, lang)`.
Both `procedure_code_jp` and `procedure_code_us` are stored for multilingual output.
`_resolve_procedure_name(proc_dict, lang)` is the shared helper across all consumers.

### Work-related injury YAMLs

4 inpatient (disease/reference_data/):
- `crush_injury_hand.yaml` (S67.2, ICD)
- `industrial_burn_severe.yaml` (T31.2, ICD)
- `fall_from_height.yaml` (T07, ICD)
- `electrical_injury.yaml` (T75.4, ICD)

2 ED (encounter/reference_data/):
- `eye_foreign_body.yaml` (T15.0, ICD)
- `chemical_exposure.yaml` (T54.9, ICD)

All have `probability` (for ED weighted selection) and age_rates/sex_ratio (for inpatient
incidence). Occupation risk multipliers concentrate events in industrial workers.

---

### AD-61: Lab ServiceRequest emission, panel-aware grouping

**Status:** Accepted (PR1, 2026-06-29)
**Context:** EHR/EMR sample dataset target (Tier 1 #1) requires FHIR
ServiceRequest for lab order lifecycle. JP Core / US Core idiomatic
emission is panel-level (1 SR per CBC, not 1 SR per WBC/Hb/Hct/Plt).
**Decision:** Add `Order.panel_key` 1 field (empty = stand-alone). Order
engine reuses lab_panel_groups.yaml (canonical loader unified in
`order/panel_grouping.py`) to assign panel_key + shared ordered_datetime
to panel members. New `_fhir_service_request.py` builder groups Orders by
`(encounter_id, panel_key, ordered_datetime)` to emit 1 SR per panel
instance; stand-alone Orders emit 1 SR each. JP Core compliance via HL7
v2-0203 PLAC identifier type + dual category coding (SNOMED 108252007 +
v2-0074 LAB).
**Consequences:** rng draw count change for lab orders (per-panel rather
than per-test draw). e2e attribute-based tests unchanged (run_alpha golden
patient FORCED-0001 not affected). Production scale verified at US p=10k
+ JP p=5k (362k+42k SR, 0 dangling refs, audit silent_no_op 7/7 PASS).
ServiceRequest is the foundation for Tier 1 #2-#7 (Imaging / NutritionOrder
/ ADT / DocumentReference / Appointment / CarePlan).

### AD-62: Imaging metadata-only chain with WADO-RS placeholder

**Status:** Accepted (Tier 1 #2, 2026-06-30)
**Context:** Tier 1 #2 EHR/EMR sample dataset extension required imaging
metadata foundation for radiology NLP/IE/CDSS/revenue-cycle/PACS-migration
evaluation. DICOM pixel data generation deferred to external image-gen AI.

**Decision:** Adopt always-on Module pattern (device/hai/antibiotic precedent)
with `ImagingStudyRecord` in `extensions["imaging"]`. Emit 4 FHIR resources:
ServiceRequest (imaging category, SNOMED 363679005 + v2-0074 RAD),
ImagingStudy (with urn:dicom:uid identifier, DCM modality, multi-series),
DiagnosticReport (radiology variant with findings + impression in `text.div` +
`conclusion`), Endpoint (WADO-RS placeholder URL via
`hospital_config.imaging.wado_base_url`). Polymorphic `_fhir_service_request`
dispatches LAB + IMAGING category from one builder.

**Consequences:**
- CIF → FHIR no-drop invariant enforced (emission matrix: every
  `ImagingStudyRecord` maps 1:1 to ImagingStudy + Endpoint + radiology DR
  + imaging SR)
- Future image-gen AI integration point: Endpoint.address substitution +
  urn:dicom:uid lookup
- AD-55 always-on Module count increases to 4 (device, hai, antibiotic,
  imaging). POST_ENCOUNTER order=90 (after antibiotic=85)
- 15-check `lift_firing_proof` (AD-60 audit) verifies non-zero ImagingStudy
  + Endpoint + radiology DR + imaging SR emission and JP locale display
  correctness (modality display / bodySite display / DR.code / conclusion)
- Legacy IMAGING orders (Chest_Xray / CT_abdomen_pelvis without
  `imaging_modality` metadata) are silently skipped by the enricher and
  remain as Order-only records without ImagingStudy (tracked for migration
  in TODO.md)

### AD-63: Document narrative + structured event density foundation

**Status:** Accepted (Tier 1 #3 α-min-1, 2026-07-01)
**Context:** Tier 1 #3 EHR/EMR sample dataset extension required clinical
document density foundation. Pre-chain baseline: DocumentReference = 0 (Stage 1
`generate` only; Stage 2 `narrate` required separate LLM step), Composition = 0,
ClinicalImpression = 0. Target: default Stage 1 template-based emission of the
3 core document types for all inpatient/ICU/rehab encounters. AllergyIntolerance
schema was 3-field (allergen string only); upgrade to 8-field SNOMED-coded schema
(allergen code + reaction manifestation + category + criticality + clinical status +
verification status + onset period + note) per JP Core Allergy profile.

**Decision:** Two new always-on Modules (same `enabled=lambda c: True`
pattern as device/hai/antibiotic/imaging):
- `allergy` (POST_POPULATION order=10): replaces activator.py inline 15% allergy sampling with a
  proper enricher that writes `PersonRecord.allergies: list[Allergy] | None`
  (None = not-yet-enriched sentinel; [] = no allergy after sampling). Produces
  SNOMED-coded `AllergyIntolerance` via new `_fhir_allergy_intolerance.py` builder.
- `document` (order=95): emits `ClinicalDocument` records (free_text for DR + CI,
  composition for Composition) via a `TemplateNarrativeGenerator` 5-step fallback chain.
  LLM-driven generation deferred (Task 15 will wire the existing LLM provider integration).

CIF storage: `CIFPatientRecord.documents` (typed field) stores `list[ClinicalDocument]`;
`extensions["clinical_impressions"]` stores `list[ClinicalImpressionRecord]`. Core type
`ClinicalDocument` gains two fields: `sections: dict[str, str]` (section name → text,
required for Composition.section[] reconstruction) and `format_type: str` (dispatch key
for builder selection: "free_text" vs "composition").

Three new FHIR builders:
- `_fhir_documents.py` (DOC_REFERENCE_ID_PREFIX = "doc-")
- `_fhir_composition.py` (COMPOSITION_ID_PREFIX = "comp-")
- `_fhir_clinical_impression.py` (CLINICAL_IMPRESSION_ID_PREFIX = "ci-")

**Consequences:**
- Stage 1 `generate` now emits 3 document-class FHIR resource types by default,
  closing the EHR sample dataset document-density gap without requiring `narrate`
- Task 15 (same branch) completed the migration: legacy `narrative_generator.py` /
  `document_generator.py` are deleted; activator.py allergy inline sampling is removed.
  No dedup guard needed — no coexistence path remains.
- CIF→FHIR no-drop invariant enforced via `ClinicalDocument.sections` field:
  Composition builder reads sections directly without re-parsing raw_text (Task 8
  fix lesson — "sections authoritative for COMPOSITION; raw_text for FREE_TEXT only")
- AD-55 always-on Module count increases to 6 (device, hai, antibiotic, imaging,
  allergy, document). Stages: allergy (POST_POPULATION order=10) → document (POST_ENCOUNTER order=95)
- 17-check `lift_firing_proof` (AD-60 audit) verifies 4 canonical ID prefixes,
  4 emission gates, 3 ID-prefix format checks, 5 no-drop invariants (spec §3.4)
- Future phases: α-min-3 (outpatient/ED POST_ENCOUNTER gap fix + Practitioner roster expansion),
  β-JP-1 (full JP localization / QuestionnaireResponse / 厚労省必須文書),
  β-2 (手術記録 / MedicationDispense / Procedure density)

### AD-64: Nursing + Outpatient + ED + CareTeam density foundation

**Status:** Accepted (Tier 1 #3 α-min-2, 2026-07-01)
**Context:** α-min-1 (AD-63) established the Stage 1 document emission infrastructure for
inpatient encounters only. Three major gaps remained: (1) CareTeam = 0 across all encounter
types, (2) nursing domain documents = 0 (no nursing-domain always-on Module), (3) outpatient /
emergency encounter documents = 0 (no outpatient SOAP / ED note / triage note). The EHR/EMR
sample dataset target requires nurse-authored document density and primary team allocation for
all encounter types.

**Decision:** Three new always-on POST_ENCOUNTER Modules (same `enabled=lambda c: True` pattern
as device/hai/antibiotic/imaging precedents):

1. **`triage` (POST_ENCOUNTER order=93)**: ED-only enricher. Samples JTAS (JP) / ESI (US) triage
   level, arrival_mode (ambulance/walk-in), and acuity_score from `triage_protocols.yaml`.
   Writes `EncounterRecord.triage_data` (new field). Consumed by document_enricher for
   `ED_TRIAGE_NOTE` LOINC 54094-8 dispatch.

2. **`nursing_assignment` (POST_ENCOUNTER order=94)**: Inpatient/ICU/rehab enricher. Assigns a
   primary nurse from the StaffRoster for the encounter's ward. Writes
   `EncounterRecord.primary_nurse_id` (new field). Consumed by `_fhir_care_team.py` builder
   for CareTeam.participant[1]. **Naming note**: the module directory is `modules/nursing/` but
   the enricher function is `nursing_enricher` (POST_ENCOUNTER). The existing POST_RECORDS nursing
   module (`observation/nursing.py`) handles NEWS2/GCS/Braden/Morse — these are DIFFERENT modules
   registered in DIFFERENT stages under the same directory.

3. **`_fhir_care_team.py` builder**: New FHIR builder registered via `register_bundle_builder()`
   as `_bb_care_teams`. Emits one CareTeam resource per encounter (ALL encounter types). Two-name
   scope: participant[0] = attending physician, participant[1] = primary nurse (when assigned).
   CareTeam ID = `careteam-{encounter_id}` (CARE_TEAM_ID_PREFIX canonical constant).

4. **6 new DocumentType specs** in `document_type_specs.yaml`:
   - `admission_nursing_assessment` (78390-2, Composition, admission_once, inpatient)
   - `nursing_shift_note` (34746-8, DocumentReference free_text, daily, inpatient)
   - `nursing_discharge_summary` (34745-0, Composition, discharge_once, inpatient)
   - `outpatient_soap` (34131-3, Composition, encounter_once, outpatient)
   - `ed_note` (34878-9, Composition, encounter_once, emergency)
   - `ed_triage_note` (54094-8, DocumentReference free_text, encounter_once, emergency)

   `DocumentTypeSpec.encounter_types_supported` field (introduced in α-min-2 Task 10) controls
   dispatch per encounter_type. α-min-1 specs now carry explicit `[inpatient, icu, rehab_inpatient]`
   allowlists (Task 10 data-quality fix: prevents leaking inpatient docs into outpatient/ED).

5. **46 encounter YAML narrative extensions**: All 46 encounter YAML files received a `narrative:`
   block with outpatient_soap / ed_note / ed_triage templates for outpatient_soap + ED encounter
   types. 5 priority conditions have detailed narrative; 41 use baseline template text.

6. **Task 8 LOINC verification**: 3 of 6 candidate LOINC codes were corrected via NLM
   verification (ADMISSION_NURSING_ASSESSMENT 34820-1→78390-2, OUTPATIENT_SOAP 11488-4→34131-3,
   ED_NOTE 51841-6→34878-9). All codes registered in `codes/data/loinc.yaml` (EN + JA bilingual).

**Consequences:**
- CIF → FHIR no-drop invariant: CareTeam (1:1 with Encounter) + 3 nursing document types
  (1:1 with inpatient encounters) enforced via lift_firing_proof equality_checks 18-25
- AD-55 always-on Module count increases to 8 (device, hai, antibiotic, imaging, triage,
  nursing_assignment, allergy, document). POST_ENCOUNTER ordering: 70/80/85/90/93/94/95
- **Known production gap**: outpatient.py + emergency.py do NOT invoke POST_ENCOUNTER enrichers
  (only inpatient.py does). OUTPATIENT_SOAP / ED_NOTE / ED_TRIAGE_NOTE produce 0 resources in
  production. Dispatch logic is correct (verified by audit proof checks 22-25); fix requires
  adding `run_stage(POST_ENCOUNTER, ...)` to outpatient.py + emergency.py (targeted for α-min-3).
- **Naming collision guard**: `modules/nursing/` contains both `nursing_enricher` (POST_ENCOUNTER
  order=94, primary_nurse assignment) and `nursery_enricher` (POST_RECORDS observation).
  Always specify the enricher name when referencing. `nursing_assignment` = POST_ENCOUNTER.
  `nursing` (observation) = POST_RECORDS.
- **CareTeam 2-name scope**: β-JP-1 will expand to 6-name multi-disciplinary team
  (pharmacist / nutritionist / rehab / MSW / charge nurse). AD-64 scope = physician + nurse only.
- 25-check `lift_firing_proof` (17 α-min-1 + 8 α-min-2). silent_no_op PASS both US + JP cohorts.
  Clinical axis PASS: 158,811 US / 16,046 JP CareTeam, 0 unknown_attending.
- Production cohort: US p=10k (158,811 CareTeam + 46,558 DR + 17,946 Composition) +
  JP p=5k (16,046 CareTeam + 7,416 DR + 970 Composition). DQR:
  `docs/reviews/2026-07-01-tier1-3-document-density-alpha-min-2-dqr.md`

### AD-65: Structural + Narrative CIF file separation (two-pass generation)

**Status:** Accepted (Tier 1 #3 α-min-2b, 2026-07-02, session 28)

**Context:**
- clinosim's initial architecture (`clinosim/modules/output/SPEC.md`) defines a three-stage
  pipeline: structural CIF Stage 1 (immutable) / narrative Stage 2 (separate version dir) /
  Stage 3 (adapter merge).
- α-min-1 Task 15 (commit `2c09b6a099`) removed the legacy narrative subsystem
  (`document_generator.py` 951 lines, `narrative_generator.py` 205 lines) and folded narrative
  generation into `document_enricher`. At the time, this closure of Stage 1 default-emission gaps
  was correct; however, as a long-term Stage 2 replacement architecture, it was a premature
  deletion, causing drift from the `clinosim/modules/output/SPEC.md` Stage 2 design.
- Session 27 Clinical Integrity review uncovered three Critical narrative bugs. The inline-only
  pattern requires full cohort regeneration to fix them, destroying development velocity.
- User explicitly indicated (session 27→28): the original design assumed structural CIF and
  narrative CIF as separate files = restoration of the SPEC.md original design.

**Decision:**
1. Refactor `ClinicalDocument` to stub-only: metadata + author + encounter binding, with
   `narrative: ClinicalDocumentNarrative | None` field (new type). Narrative content
   (text/sections/facts_used) population is forbidden in Stage 1.
2. Restore two-pass CIF generation pipeline (SPEC.md original design intent, fully restored).
3. Reinstate `clinosim narrate` CLI verb (template mode as fallback; LLM actual invocation deferred
   to β-JP-1).
4. Establish Bedrock prompt-cache-friendly walk order contract: `NarrativePass` base class
   guarantees `(doc_type, language)` group serial iteration.
5. Extend `NarrativeContext` with three enhancements: `NarrativeSpine` (scenario anchoring),
   `materialized_facts` (fact-first generation), `section_facts` (COMPOSITION section extraction).
6. Fix silent CLI override (Bug D): `-p` explicit values no longer silently overridden by
   `recommended_population`.
7. Add dev iteration facility: `test-disease --format` + `test-encounter --format` +
   `--output` flag + standalone `narrate` verb enable narrative bug verification cycle to
   10–30 seconds (vs. 5–50 min full generate).

**Consequences:**
- Narrative bug verification: `narrate --tasks <task>` (~30 sec) + structural via `test-disease
  --format all` (~10 sec) = 100× faster development cycle.
- FHIR builders now exclusively access narrative content via `doc.narrative.*` → single source
  of truth (prevents `document_enricher` and Stage 2 pass from conflicting).
- β-JP-1 can implement `LLMNarrativePass` as drop-in subclass of `NarrativePass` base class,
  inheriting Bedrock walk-order contract without modification.
- All 39 existing e2e goldens require full regeneration (no backwards compatibility).
- Five new AD-65 rules added to `CLAUDE.md` (prevents next-session drift: two-pass invariant,
  stub-only enricher, narrative post-simulation, walk order, FHIR builder wrapper).

**Alternatives considered:**
- **Approach A** (Inline populate + writer split): Lower silent-no-op risk; weaker Stage 2
  replacement symmetry → rejected.
- **Approach B** (Explicit two-pass without auto-invoke): Larger UX change → rejected in favor
  of inline default (preserves `clinosim generate` user experience).
- **Approach C** (Flat field + physical split without wrapper): Weaker defense-in-depth → rejected
  in favor of `ClinicalDocumentNarrative` wrapper type.

**Related ADRs:** AD-30 / AD-55 / AD-56 / AD-60 / AD-63 / AD-64

---

### AD-66 · Canonical patient profile fixture library for narrative regression

**Date:** 2026-07-03 (α-min-2c chain)

**Status:** Accepted

**Context:**
The AD-65 two-pass CIF architecture enables template narrative output to be
compared against a canonical baseline. β-JP-1 will introduce `LLMNarrativePass`
which produces non-deterministic LLM output. To detect narrative regression
(template drift, LLM drift, semantic changes), we need a canonical set of
deterministic patient profiles + expected narrative outputs to diff against.

**Decision:**
Ship 6 canonical patient profile YAML fixtures in `tests/fixtures/patient_profiles/`,
each accompanied by a `<profile>.golden.json` file containing the expected
template narrative output at seed 42. A `pytest -m regression` suite
subprocess-invokes `clinosim test-disease --patient-profile <id>` and byte-diffs
the generated narrative against the golden.

Introduce a new `PatientProfile` Pydantic type in `clinosim/types/config.py`
with `.to_forced_scenario()` transform, and a `clinosim regenerate-goldens`
CLI subcommand for bootstrap + re-generation.

Scope-in for α-min-2c: 6 disease-based inpatient/ICU profiles only.
Scope-out (deferred to β-JP-1 or later): ED/outpatient encounter profiles
(requires symmetric `test-encounter --patient-profile` extension), LLM
semantic diff mechanism, GitHub Actions CI integration, clinical review loop.

**Consequences:**

Positive:
- β-JP-1 unblocked — deterministic canonical patients for template vs LLM narrative regression
- Adding new profiles is a documented workflow (regenerate + review + commit)
- Determinism enforced at seed 42 via existing AD-16 discipline

Negative:
- Additional maintenance burden when template narrative logic changes
  (all goldens need regeneration)
- Fixture library is separate from disease YAMLs (contributors need to
  understand both)

Neutral:
- 6 profiles × ~10-76 documents/profile × N sections = ~100-500 KB of golden
  JSON checked into git (acceptable)

**Alternatives considered:**

- **Input + narrative expectations in single YAML**: rejected — LLM output
  cannot be represented as expected substrings without semantic diff engine
  (deferred to β-JP-1 scope)
- **Input + reference golden narrative embedded (base64 in YAML)**: rejected
  — YAML would grow to 100-500 lines/profile, git diff becomes noisy, LLM
  parallel storage difficult
- **Integrated into existing AD-60 `audit run` framework**: rejected —
  fixture regression is per-profile deterministic byte-diff, not cohort
  statistics; overloading audit purpose

**Related ADRs:** AD-16 / AD-56 / AD-63 / AD-65

**Related documents:**
- Spec: `docs/superpowers/specs/2026-07-03-tier1-3-alpha-min-2c-fixture-library-design.md`
- Plan: `docs/superpowers/plans/2026-07-03-tier1-3-alpha-min-2c-fixture-library-plan.md`
