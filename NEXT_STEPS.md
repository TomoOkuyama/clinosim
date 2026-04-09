# Next Steps for clinosim Development

**Last Updated**: 2026-04-09  
**Current Status**: v0.1-beta with Bedrock narrative generation + prompt optimization  
**For**: Next Claude Code session

## Recently Completed (2026-04-09)

✅ **Bedrock LLM Integration**
- BedrockProvider implementation (boto3-based)
- 5 LOINC-compliant narrative document types
- Token optimization (50x reduction: ~90M → ~1.8M tokens)
- Configuration files and test scripts
- See `BEDROCK_SETUP.md` for full details

✅ **Prompt Optimization & English-First Strategy**
- Added concise instructions to all prompts (500-800 chars target)
- **Results**: 52% time reduction (191s → 92s), 60% token reduction (9.1k → 3.6k)
- Fixed max_tokens bottleneck (4/5 types hitting limits)
- **English narratives prioritized** (project direction: EN first, then JP later)
- English narratives: 59% fewer tokens than Japanese for same content
- Bedrock Sonnet 4.6 throughput: 47.8 tokens/sec (within normal range)

✅ **CIF-Narrative Consistency Design**
- Documented 3-way consistency requirement in `NARRATIVE_CIF_MAPPING.md`:
  1. **CIF structured data** (vitals, labs, meds, procedures - actual measurements)
  2. **Disease Protocol YAML** (course_archetypes, discharge_criteria, standard treatment)
  3. **Encounter Scenario YAML** (severity, workup, treatment patterns)
- Defined BEFORE/AFTER temporal consistency principle
- Outlined implementation phases: extraction → validation → integration
- **Critical**: Narratives must reflect ACTUAL CIF outcomes, not hallucinated data

## Immediate Next Steps (v0.1 Completion)

### 1. Implement CIF Data Extraction Module ⏳ **HIGHEST PRIORITY**

**Status**: Design complete, implementation not started  
**Why first**: Current prompts contain minimal data (age, sex, diagnosis only) leading to hallucinated vitals/labs. Must extract real CIF data first before pipeline integration.

**Files to create**:
- `clinosim/modules/narrative/` (new module)
- `clinosim/modules/narrative/__init__.py`
- `clinosim/modules/narrative/cif_extractor.py` - Extract data from CIF+Protocol+Scenario
- `clinosim/modules/narrative/validator.py` - Validate narrative-CIF consistency

**Implementation**:
```python
# cif_extractor.py
def extract_admission_hp_data(
    cif_record: CIFPatientRecord,
    disease_protocol: dict,
    encounter_scenario: dict = None
) -> dict:
    """Extract all data needed for Admission H&P narrative."""
    # 1. Extract CIF vitals (AFTER admission)
    # 2. Extract CIF labs (AFTER admission, within 4h)
    # 3. Load disease protocol YAML
    # 4. Load encounter scenario YAML (if ED/outpatient)
    # 5. Resolve all codes to English via codes.lookup()
    # 6. Return dict with complete prompt data
```

**Functions to implement**:
- `extract_admission_hp_data()` - Admission vitals, labs, PMH
- `extract_discharge_summary_data()` - BEFORE/AFTER comparison, key events
- `extract_operative_note_data()` - Procedure details, intraop findings
- `extract_procedure_note_data()` - Procedure details, peri-procedure vitals
- `extract_death_note_data()` - Death circumstances, cause

**See**: `NARRATIVE_CIF_MAPPING.md` for complete data requirements

**Testing**:
- Unit tests with mock CIF data
- Integration tests with real disease protocol YAMLs
- Verify no hallucinated data in extracted dicts

---

### 2. Update Prompt Builder to Use Extracted Data ⏳ HIGH PRIORITY

**Status**: Not started (depends on #1)  
**Files to modify**:
- `clinosim/modules/llm_service/engine.py` - Update `_build_prompt()`

**Changes**:
```python
# OLD
def _build_prompt(task_type, event: ClinicalEventData, language: str):
    ps = event.patient_summary  # Minimal data
    ...

# NEW
def _build_prompt(task_type, extracted_data: dict, language: str):
    # extracted_data contains:
    # - CIF vitals/labs (actual values, with timestamps)
    # - Disease protocol context (typical course)
    # - Encounter scenario context (severity, workup)
    ...
```

**Example prompt (Admission H&P)**:
```
Patient: 72yo M
Chief complaint: Shortness of breath and fever (3 days)
PMH: Hypertension, Type 2 diabetes

Admission Vitals (2026-04-09 10:23):
- Temp: 38.8°C, HR: 102, BP: 138/82, RR: 22, SpO2: 91% on RA

Admission Labs (2026-04-09 10:45):
- WBC: 14.2 x10^9/L (H)
- CRP: 12.5 mg/dL (H)
- Glucose: 185 mg/dL (H)

Chest X-ray: Right lower lobe infiltrate

Admitting Diagnosis: Bacterial pneumonia (Streptococcus pneumoniae)

Write a concise admission H&P (500-800 chars).
```

**Testing**:
- Compare OLD vs NEW prompts side-by-side
- Verify no hallucinated vitals/labs in generated narratives
- Check narratives match CIF data exactly

---

### 3. Integrate Bedrock into Main Pipeline ⏳ HIGH PRIORITY

**Status**: Not started (depends on #1, #2)  
**Files to modify**:
- `clinosim/simulator/engine.py` - Add narrative generation stage
- `clinosim/modules/output/fhir_adapter.py` - Add DocumentReference resources

**Implementation steps**:
1. Load Bedrock config in simulator
2. Create LLMService instance after CIF generation
3. For each encounter in CIF:
   - Determine which narrative types to generate (based on encounter type)
   - Call `llm.generate()` for each type
   - Create FHIR DocumentReference resources
   - Link to Encounter via `context.encounter`
4. Add narratives to FHIR export

**Example code structure**:
```python
# In simulator/engine.py
def run_beta(config):
    # ... existing simulation ...
    cif_dataset = generate_structural_data(...)
    
    # NEW: Narrative generation stage
    if config.narrative_mode == "llm":
        llm_service = create_llm_service(config.llm_config)
        narratives = generate_all_narratives(cif_dataset, llm_service)
        cif_dataset.narratives = narratives
    
    # Export
    export_fhir(cif_dataset)
    export_csv(cif_dataset)
```

**Testing**:
- Run with 10 patients first
- Check DocumentReference resources in FHIR output
- Verify LOINC codes match (34117-2, 18842-5, etc.)
- Measure actual token consumption

---

### 4. Add DocumentReference Resources to FHIR Output ⏳ HIGH PRIORITY

**Status**: Not started  
**Files to modify**:
- `clinosim/types/output.py` - Add NarrativeDocument to CIFPatientRecord
- `clinosim/modules/output/fhir_adapter.py` - Add DocumentReference builder

**FHIR DocumentReference structure**:
```json
{
  "resourceType": "DocumentReference",
  "id": "doc-ENC-123-admission-hp",
  "status": "current",
  "type": {
    "coding": [{
      "system": "http://loinc.org",
      "code": "34117-2",
      "display": "History and physical note"
    }]
  },
  "subject": {"reference": "Patient/PAT-123"},
  "context": {
    "encounter": [{"reference": "Encounter/ENC-123"}],
    "period": {...}
  },
  "content": [{
    "attachment": {
      "contentType": "text/plain",
      "data": "<base64 encoded text>",
      "language": "ja"
    }
  }]
}
```

**Reference**:
- [FHIR DocumentReference](https://www.hl7.org/fhir/documentreference.html)
- [LOINC Document Codes](https://loinc.org/document-ontology/)

---

### 5. Full-Scale Test (30k Catchment) ⏳ MEDIUM PRIORITY

**Status**: Not started  
**Command**:
```bash
clinosim generate -o ./output_bedrock \
  --population 30000 \
  --country JP \
  --start 2025-01-01 \
  --end 2025-12-31 \
  --seed 42 \
  --llm-config clinosim/config/llm_service.bedrock.yaml
```

**What to measure**:
- Total token consumption (should be ~1.8M)
- Total cost (should be ~$18)
- Generation time (expect ~30-60 min for narratives)
- Quality of generated narratives (spot check 10-20 documents)

**Success criteria**:
- 171 Admission H&P documents
- 171 Discharge Summary documents
- ~11 Operative Notes
- ~19 Procedure Notes
- ~2 Death Notes
- All in Japanese
- Clinically plausible content

---

### 6. Cost Tracking and Budget Limits 🔧 MEDIUM PRIORITY

**Status**: Partial (token counting exists, budget enforcement not implemented)  
**Files to modify**:
- `clinosim/modules/llm_service/engine.py` - Add budget tracking

**Implementation**:
```python
class LLMService:
    def __init__(self, ..., max_tokens_budget: int = 10_000_000):
        self.max_tokens_budget = max_tokens_budget
        self.tokens_used = 0
    
    def generate(self, task_type, event):
        if self.tokens_used >= self.max_tokens_budget:
            # Switch to template mode
            return self._template_generate(task_type, event, language)
        
        # ... normal LLM generation ...
        self.tokens_used += response.input_tokens + response.output_tokens
```

---

## Key Findings & Design Decisions

### 🔑 English-First Strategy
- **Decision**: Prioritize English narratives first, add Japanese support later
- **Rationale**: 
  - English CIF is primary target (per project design)
  - English narratives: 59% fewer tokens than Japanese (same content)
  - Lower cost, faster generation
- **Status**: Test scripts updated to English, prompts optimized for EN

### 🔑 3-Way Consistency Requirement
- **Decision**: Narratives must be consistent with CIF + Disease Protocol + Encounter Scenario
- **Rationale**:
  - Current prompts only have age/sex/diagnosis → LLM hallucinates vitals/labs
  - CIF has actual measurements → must extract and include in prompts
  - Disease protocols define typical course → narratives should match archetype
  - Encounter scenarios define severity → narratives should reflect severity level
- **Implementation**: See `NARRATIVE_CIF_MAPPING.md`
- **Status**: Design complete, extraction module not implemented

### 🔑 BEFORE/AFTER Temporal Consistency
- **Decision**: All outcome statements ("normalized", "improved") must be backed by CIF data
- **Example**: "CRP normalized on Day 7" → MUST have lab_result with CRP < 1.0 on Day 7
- **Implementation**: validator.py will check narrative claims against CIF AFTER data
- **Status**: Design complete, validator not implemented

### 🔑 Prompt Optimization Results
- **Finding**: 4 out of 5 document types were hitting max_tokens limits
- **Solution**: Added "簡潔に (500-800文字程度)" instruction
- **Results**:
  - Time: 191s → 92s (52% reduction)
  - Tokens: 9.1k → 3.6k (60% reduction)
  - Quality: Maintained (all required sections present)
- **Status**: Implemented and tested

### 🔑 Bedrock Performance Baseline
- **Throughput**: 47.8 tokens/sec (within normal range 40-70 for Bedrock)
- **Bottleneck**: 100% in Bedrock API call, <0.1ms local overhead
- **Optimization potential**: 3.3x speedup with parallel generation (161s → 49s)
- **Cost**: ~$7 per 30k catchment/year with optimized prompts (was $18)

---

## Near-Term Improvements (v0.2)

### 1. Bedrock Prompt Caching 💰 HIGH VALUE

**Why**: Reduce input token costs by ~50% for repeated context

**How**: Use Bedrock's prompt caching feature
- Cache patient summary (changes per patient)
- Cache system prompts (same for all documents of a type)

**Reference**: [Bedrock Prompt Caching](https://docs.aws.amazon.com/bedrock/latest/userguide/prompt-caching.html)

**Expected savings**: Input tokens ~50% reduction → ~$1 saved per 30k catchment

---

### 2. Response Caching 🚀 PERFORMANCE

**Why**: Avoid redundant LLM calls for similar scenarios

**Implementation**:
```python
class NarrativeCache:
    def __init__(self, max_size=1000):
        self.cache = {}  # (disease, severity, doc_type, language) -> template
    
    def get(self, cache_key):
        if cache_key in self.cache:
            return self.cache[cache_key].adapt_to_patient(...)
        return None
    
    def put(self, cache_key, narrative):
        self.cache[cache_key] = narrative.generalize()
```

**Expected benefit**: 30-50% cache hit rate → significant speedup

---

### 3. Parallel Narrative Generation 🚀 PERFORMANCE

**Status**: Single-threaded (sequential)  
**Goal**: Async batch processing

**Implementation**:
```python
async def generate_all_narratives(cif_dataset, llm_service):
    tasks = []
    for record in cif_dataset.patients:
        for narrative_type in determine_narrative_types(record.encounter):
            task = llm_service.generate_async(narrative_type, ...)
            tasks.append(task)
    
    narratives = await asyncio.gather(*tasks, return_exceptions=True)
    return narratives
```

**Expected benefit**: 5-10x speedup with bounded concurrency

---

### 4. Multi-Model Strategy 💰 COST OPTIMIZATION

**Why**: Use cheaper models for simpler documents

**Strategy**:
| Document Type | Complexity | Recommended Model | Cost |
|---|---|---|---|
| Death Note | Simple | Haiku | Lowest |
| Procedure Note | Simple | Haiku | Lowest |
| Admission H&P | Medium | Sonnet | Medium |
| Discharge Summary | Complex | Sonnet | Medium |
| Operative Note | Medium | Sonnet | Medium |

**Expected savings**: ~20% cost reduction

---

## Known Issues / Tech Debt

### 1. Error Handling ⚠️

**Current**: Generic exception catching in `_llm_generate()`  
**Better**: Specific error types with contextual retry logic

```python
try:
    response = provider.complete(...)
except ThrottlingException:
    # Exponential backoff + retry
except ModelNotReadyException:
    # Switch to fallback model
except ValidationException:
    # Log and use template
```

---

### 2. Narrative Quality Validation ⚠️

**Current**: No automated quality checks  
**Needed**: 
- Length validation (too short = poor generation)
- Structure validation (contains expected sections)
- Code injection check (no SQL/script in output)

---

### 3. FHIR Validation ⚠️

**Current**: No validation of generated FHIR DocumentReference  
**Needed**: Run FHIR validator on output

```bash
java -jar validator_cli.jar output/fhir_r4/DocumentReference.ndjson \
  -version 4.0 -ig hl7.fhir.r4.core
```

---

## Long-Term Roadmap

### v0.3 - Advanced Features
- [ ] Streaming responses (for real-time UI)
- [ ] Custom fine-tuned models
- [ ] Multi-language support (EN, JA, DE, FR, ZH, KO)
- [ ] Narrative style customization (formal, informal, academic)

### v0.4 - Enterprise Features
- [ ] Audit trail (who generated what, when, with which model)
- [ ] PII redaction in narratives
- [ ] Compliance reports (HIPAA, GDPR)
- [ ] A/B testing framework for prompts

### v1.0 - Production Ready
- [ ] 1M+ patients with narratives
- [ ] <$100 for 100k catchment/year
- [ ] <1 hour generation time
- [ ] 95%+ quality score (expert review)

---

## Resources

### Documentation
- `BEDROCK_SETUP.md` - Complete setup guide
- `clinosim/modules/llm_service/README.md` - Module docs
- `TODO.md` - Overall project status

### Test Scripts
- `test_bedrock_narrative.py` - Test all 5 document types

### Configuration
- `clinosim/config/llm_service.bedrock.yaml` - Production config
- `clinosim/config/llm_service.yaml` - Local Ollama (dev)

### Code Files
- `clinosim/modules/llm_service/engine.py` - Core logic
- `clinosim/modules/llm_service/providers.py` - BedrockProvider

---

## Questions for Next Session

1. **Integration priority**: Should narrative generation be:
   - Part of main simulation (slower, all-in-one)
   - Separate post-processing step (faster, more flexible)

2. **Error strategy**: When Bedrock fails, should we:
   - Retry with different model
   - Fall back to template
   - Skip narrative entirely

3. **Quality vs Cost**: Which is more important:
   - Best quality (always use Sonnet/Opus)
   - Best cost (mix Haiku/Sonnet)

4. **Deployment**: Where will this run:
   - Local machine (developer testing)
   - EC2/ECS (production simulation)
   - Lambda (serverless, pay-per-use)

---

## Contact / Handoff Notes

**Implementation status as of 2026-04-09**:
- ✅ BedrockProvider working
- ✅ All 5 document types defined
- ✅ Templates implemented
- ✅ Test script passing
- ⏳ Not yet integrated into main pipeline
- ⏳ DocumentReference not in FHIR output yet

**To verify Bedrock is working**:
```bash
python test_bedrock_narrative.py
```

**To test with main simulation** (once integrated):
```bash
clinosim generate -o ./test_output --population 100 --country JP
```

**Git commit**: `4abacfb` - "feat(llm_service): Add Bedrock support and streamline to 5 narrative types"

**For help**: Check GitHub issues or `clinosim/modules/llm_service/README.md`
