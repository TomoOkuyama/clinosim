# Next Steps for clinosim Development

**Last Updated**: 2026-04-09  
**Current Status**: v0.1-beta with Bedrock narrative generation  
**For**: Next Claude Code session

## Recently Completed (2026-04-09)

✅ **Bedrock LLM Integration**
- BedrockProvider implementation (boto3-based)
- 5 LOINC-compliant narrative document types
- Token optimization (50x reduction: ~90M → ~1.8M tokens)
- Configuration files and test scripts
- See `BEDROCK_SETUP.md` for full details

## Immediate Next Steps (v0.1 Completion)

### 1. Integrate Bedrock into Main Pipeline ⏳ HIGH PRIORITY

**Status**: Not started  
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

### 2. Add DocumentReference Resources to FHIR Output ⏳ HIGH PRIORITY

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

### 3. Full-Scale Test (30k Catchment) ⏳ MEDIUM PRIORITY

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

### 4. Cost Tracking and Budget Limits 🔧 MEDIUM PRIORITY

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
