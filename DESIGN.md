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
