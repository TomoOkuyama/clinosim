# llm_service — LLM Integration Service

## Purpose
Single point of contact between clinosim and LLM providers. All LLM calls from every module pass through this service. Responsible for prompt construction, model selection, response parsing, caching, rate limiting, cost tracking, and fallback to template-based generation when LLM is unavailable.

No other module may call an LLM directly.

## Inputs
- `LLMRequest`: Structured request from any module (context + task type + constraints)
- Configuration: API keys, model selection, generation mode (`llm` / `template` / `none`), cost budget

## Outputs
- `LLMResponse`: Parsed, validated response (narrative text, clinical judgment, or consistency review result)

## Dependencies
- None (this module is a leaf service — other modules depend on it, not the reverse)

---

## Internal Design

### Architecture

```
┌─────────────────────────────────────────────────────────┐
│  Any clinosim module (diagnosis, treatment, encounter,  │
│  nursing, patient, validator, ...)                       │
│                                                          │
│  Calls: llm_service.request(LLMRequest) → LLMResponse   │
└─────────────────┬───────────────────────────────────────┘
                  │
                  ↓
┌─────────────────────────────────────────────────────────┐
│  llm_service                                             │
│                                                          │
│  1. Mode check: none → return empty / template → route   │
│     to template engine / llm → continue                  │
│                                                          │
│  2. Cache check: exact or similar request cached?        │
│     → return cached (with patient-specific adaptation)   │
│                                                          │
│  3. Prompt builder: request type → prompt template       │
│     + LLMClinicalContext → final prompt                  │
│                                                          │
│  4. Model selector: task tier → model endpoint           │
│                                                          │
│  5. API call: send prompt, receive raw response          │
│                                                          │
│  6. Response parser: validate structure, extract fields   │
│                                                          │
│  7. Cost tracker: log tokens used                        │
│                                                          │
│  8. Return LLMResponse to caller                         │
└─────────────────────────────────────────────────────────┘
```

### Folder structure

```
modules/llm_service/
├── SPEC.md
├── prompts/
│   ├── chief_complaint.yaml          ← prompt templates per task type
│   ├── admission_hp.yaml
│   ├── progress_note.yaml
│   ├── discharge_summary.yaml
│   ├── consultation_note.yaml
│   ├── operative_note.yaml
│   ├── nursing_note.yaml
│   ├── treatment_rationale.yaml
│   ├── diagnostic_reasoning.yaml
│   ├── clinical_judgment.yaml
│   ├── consistency_review.yaml
│   └── referral_letter.yaml
├── templates/                         ← template-mode fallback (no LLM)
│   ├── chief_complaint.txt
│   ├── progress_note_soap.txt
│   ├── discharge_summary.txt
│   └── ...
└── (implementation files)
```

### API — Responsibility split

**Key principle: Modules know WHAT happened. llm_service knows HOW to describe it.**

```
Module responsibility:
  - Collect structured event data (what diagnosis changed, what treatment was decided, what labs came back)
  - Pass a ClinicalEvent to llm_service

llm_service responsibility:
  - Determine which prompt template to use (based on task type)
  - Build the full prompt from the event data (modules never see prompts)
  - Select the model tier (defined per task type in prompt YAML, not by caller)
  - Call the LLM provider
  - Parse and validate the response
  - Handle caching, cost tracking, fallback
```

```python
class LLMService:
    def __init__(self, config: LLMServiceConfig):
        self.mode = config.mode              # "llm" | "template" | "none"
        self.provider = config.provider      # LLMProvider instance
        self.model_map = config.model_map
        self.cache = NarrativeCache()
        self.cost_tracker = CostTracker()
        self.prompt_registry = PromptRegistry("prompts/")
        self.template_registry = TemplateRegistry("templates/")

    def generate(self, task_type: LLMTaskType, event: ClinicalEventData) -> LLMResponse:
        """
        Single entry point. Modules call this with WHAT happened.
        llm_service decides HOW to generate text from it.
        
        Language handling:
          - JUDGMENT tasks: always English (input and output). Structured result.
          - NARRATIVE tasks: input in English, output in event.language (ja/en).
        
        Modules NEVER:
          - write prompt text
          - choose model tier, language, or max_output_tokens
          - provide 'instructions' strings
        
        All of these are defined in the prompt YAML for each task_type.
        """
        
        # Mode gate
        if self.mode == "none":
            return LLMResponse(text=None, source="none")
        
        # Determine language based on task category
        category = TASK_CATEGORY[task_type]
        if category == LLMTaskCategory.JUDGMENT:
            effective_language = "en"       # always English — better quality, fewer tokens
        else:
            effective_language = event.language  # target country's language (ja/en)
        
        # Load prompt config (contains model_tier, max_tokens, template, etc.)
        prompt_config = self.prompt_registry.load(task_type)
        
        if self.mode == "template":
            return self._template_generate(prompt_config, event, effective_language)
        
        # LLM mode
        cache_key = self._make_cache_key(task_type, event, effective_language)
        cached = self.cache.get(cache_key)
        if cached:
            return LLMResponse(text=cached.adapt(event), source="cache")
        
        # Build prompt (llm_service owns this entirely)
        prompt = prompt_config.render(event)
        model = self.model_map[prompt_config.model_tier]
        
        # Call LLM with graceful degradation
        raw = self._call_with_resilience(prompt, model, prompt_config, event, effective_language)
        
        # Parse response (task-type-specific parsing rules)
        parsed = prompt_config.parse_response(raw.text)
        
        # Cache
        self.cache.put(cache_key, parsed)
        
        # Track cost
        self.cost_tracker.record(model, raw.input_tokens, raw.output_tokens)
        
        return parsed
```

### ClinicalEventData — what modules pass in

Modules pass structured data about what happened. No prompt text, no LLM-specific parameters.

```python
@dataclass
class ClinicalEventData:
    """Structured event data from any module. llm_service converts this to prompts."""
    
    # Patient context (always present)
    patient_summary: PatientSummary
    
    # Event-specific data (varies by task type)
    event_data: dict                       # task-type-specific structured data
    
    # Language (determined by country, not by module choice)
    language: str                          # "ja" | "en"

@dataclass
class PatientSummary:
    """Compact patient representation. Built once per encounter, reused across calls."""
    age: int
    sex: str
    country: str
    chief_complaint: str
    relevant_conditions: list[str]
    relevant_medications: list[str]
    allergies: list[str]
    current_diagnosis: str
    diagnosis_confidence: float
    hospital_day: int
    department: str
    hospital_type: str
```

### Task-specific event_data examples

Each task type has a defined schema for `event_data`. These schemas are documented in the prompt YAML files.

```python
# diagnosis module calls:
llm_service.generate(
    task_type=LLMTaskType.DIAGNOSTIC_REASONING,
    event=ClinicalEventData(
        patient_summary=patient_summary,
        event_data={
            "differential_before": {"pneumonia": 0.45, "heart_failure": 0.20, ...},
            "differential_after": {"pneumonia": 0.78, "heart_failure": 0.08, ...},
            "new_findings": ["CXR: lobar consolidation", "CRP 89 mg/L", "PCT 1.8 ng/mL"],
            "tests_pending": ["blood_culture", "sputum_culture"],
        },
        language="ja",
    )
)

# treatment module calls:
llm_service.generate(
    task_type=LLMTaskType.TREATMENT_RATIONALE,
    event=ClinicalEventData(
        patient_summary=patient_summary,
        event_data={
            "decision": "antibiotic_switch",
            "from_drug": "ABPC/SBT 3g IV q6h",
            "to_drug": "MEPM 1g IV q8h",
            "trigger": "no_defervescence_72h",
            "supporting_data": ["Day 3 Tmax 38.4°C", "CRP 142 (↑ from 89)", "blood culture: no growth yet"],
        },
        language="ja",
    )
)

# encounter module calls:
llm_service.generate(
    task_type=LLMTaskType.DISCHARGE_SUMMARY,
    event=ClinicalEventData(
        patient_summary=patient_summary,
        event_data={
            "admission_date": "2024-06-15",
            "discharge_date": "2024-06-29",
            "los_days": 14,
            "final_diagnosis": "Pneumonia due to Streptococcus pneumoniae (J13)",
            "key_events": [
                {"day": 0, "event": "Admitted via ER with fever 38.9°C, cough, dyspnea"},
                {"day": 0, "event": "CXR: RLL consolidation. ABPC/SBT started"},
                {"day": 3, "event": "Fever resolved. CRP trending down"},
                {"day": 7, "event": "CXR: partial resolution. Oral switch to AMPC"},
                {"day": 14, "event": "CRP 4. CXR near-complete resolution. Discharged"},
            ],
            "discharge_medications": ["AMPC 250mg TID x5 days"],
            "follow_up": "Outpatient Day 28, CXR + CRP",
        },
        language="ja",
    )
)

# validator module calls:
llm_service.generate(
    task_type=LLMTaskType.CONSISTENCY_REVIEW,
    event=ClinicalEventData(
        patient_summary=patient_summary,
        event_data={
            "timeline_summary": "...(condensed patient timeline)...",
            "rule_based_flags": ["CRP rose after antibiotic switch (unusual but possible)"],
        },
        language="en",  # review can be in English for efficiency
    )
)
```

### Prompt YAML owns everything about how to talk to the LLM

```yaml
# prompts/diagnostic_reasoning.yaml
task_type: diagnostic_reasoning
model_tier: medium
max_output_tokens: 800                     # sufficient for clinical reasoning paragraph in Japanese
temperature: 0.4                           # lower = more deterministic reasoning

# What event_data fields this task expects
event_data_schema:
  required: [differential_before, differential_after, new_findings]
  optional: [tests_pending]

system_prompt: |
  You are a {department} physician at a {hospital_type} hospital in {country}.
  Generate a brief clinical reasoning paragraph explaining why the differential
  diagnosis changed based on new findings.
  Write in {language}. Use appropriate medical terminology.
  Be concise (2-4 sentences).

user_prompt: |
  Patient: {age}yo {sex}, Hospital Day {hospital_day}
  Working diagnosis: {current_diagnosis}
  
  New findings today:
  {new_findings_formatted}
  
  Differential changed:
  Before: {differential_before_formatted}
  After: {differential_after_formatted}
  
  Explain the clinical reasoning for this change.

# How to format event_data into prompt variables
formatters:
  new_findings_formatted: "bullet_list(event_data.new_findings)"
  differential_before_formatted: "probability_table(event_data.differential_before)"
  differential_after_formatted: "probability_table(event_data.differential_after)"

# How to parse the LLM response back into structured data
response_parser:
  type: "text_only"                        # just return the text as-is
  # Other options: "json_extract", "structured_sections"
```

```yaml
# prompts/clinical_judgment.yaml
task_type: clinical_judgment
model_tier: large
max_output_tokens: 600                     # decision + reasoning + additional actions
temperature: 0.3

event_data_schema:
  required: [decision_type, options, rule_based_suggestion, supporting_data]

system_prompt: |
  You are a senior {department} physician making a clinical decision.
  Consider the patient context and available options.
  Choose the most appropriate option and explain your reasoning briefly.
  Respond in JSON format.

user_prompt: |
  Patient: {age}yo {sex}, Day {hospital_day}
  Diagnosis: {current_diagnosis}
  
  Decision needed: {decision_type}
  Rule-based suggestion: {rule_based_suggestion}
  
  Options:
  {options_formatted}
  
  Supporting data:
  {supporting_data_formatted}

response_parser:
  type: "json_extract"
  schema:
    chosen_option: string
    reasoning: string
    confidence: float
    additional_actions: list[string] | null
```

### What this means for calling modules

Modules become simpler. They don't think about LLM at all:

```python
# BEFORE (module manages prompt details):
response = llm_service.request(LLMRequest(
    task_type=LLMTaskType.DIAGNOSTIC_REASONING,
    context=llm_context,
    language="ja",
    model_tier="medium",           # module shouldn't decide this
    max_output_tokens=300,         # module shouldn't decide this
    instructions="Explain why...", # this IS a prompt fragment
))

# AFTER (module only provides structured data):
response = llm_service.generate(
    task_type=LLMTaskType.DIAGNOSTIC_REASONING,
    event=ClinicalEventData(
        patient_summary=patient_summary,
        event_data={
            "differential_before": {...},
            "differential_after": {...},
            "new_findings": [...],
        },
        language="ja",
    )
)
```

No `model_tier`. No `max_output_tokens`. No `instructions`. All of that lives in `prompts/diagnostic_reasoning.yaml`.

### LLMTaskType registry

```python
class LLMTaskCategory(str, Enum):
    JUDGMENT = "judgment"      # Always English. Returns structured decisions. Language-independent.
    NARRATIVE = "narrative"    # Output in target country's language. Generates clinical documents.

class LLMTaskType(str, Enum):
    # --- JUDGMENT tasks (always English in/out, structured response) ---
    # These produce decisions and reasoning that feed back into the simulation engine.
    # Output is parsed into structured data; the English text is stored for audit only.
    DIAGNOSTIC_REASONING = "diagnostic_reasoning"      # differential update rationale
    TREATMENT_DECISION = "treatment_decision"           # drug selection at ambiguous points
    CLINICAL_JUDGMENT = "clinical_judgment"              # generic decision (consult needed? ICU transfer?)
    CONSISTENCY_REVIEW = "consistency_review"            # validate patient record plausibility
    CARE_SEEKING_JUDGMENT = "care_seeking_judgment"      # edge-case visit decision

    # --- NARRATIVE tasks (output in target language: ja / en) ---
    # These produce clinical documents that appear in the generated EHR.
    # Must be in the language of the target country's medical records.
    CHIEF_COMPLAINT = "chief_complaint"
    ADMISSION_HP = "admission_hp"
    PROGRESS_NOTE = "progress_note"
    DISCHARGE_SUMMARY = "discharge_summary"
    CONSULTATION_NOTE = "consultation_note"
    OPERATIVE_NOTE = "operative_note"
    NURSING_NOTE = "nursing_note"
    REFERRAL_LETTER = "referral_letter"
    MEDICATION_INSTRUCTION = "medication_instruction"    # patient-facing discharge med instructions

# Task type → category mapping (used by llm_service internally)
TASK_CATEGORY = {
    LLMTaskType.DIAGNOSTIC_REASONING: LLMTaskCategory.JUDGMENT,
    LLMTaskType.TREATMENT_DECISION: LLMTaskCategory.JUDGMENT,
    LLMTaskType.CLINICAL_JUDGMENT: LLMTaskCategory.JUDGMENT,
    LLMTaskType.CONSISTENCY_REVIEW: LLMTaskCategory.JUDGMENT,
    LLMTaskType.CARE_SEEKING_JUDGMENT: LLMTaskCategory.JUDGMENT,
    LLMTaskType.CHIEF_COMPLAINT: LLMTaskCategory.NARRATIVE,
    LLMTaskType.ADMISSION_HP: LLMTaskCategory.NARRATIVE,
    LLMTaskType.PROGRESS_NOTE: LLMTaskCategory.NARRATIVE,
    LLMTaskType.DISCHARGE_SUMMARY: LLMTaskCategory.NARRATIVE,
    LLMTaskType.CONSULTATION_NOTE: LLMTaskCategory.NARRATIVE,
    LLMTaskType.OPERATIVE_NOTE: LLMTaskCategory.NARRATIVE,
    LLMTaskType.NURSING_NOTE: LLMTaskCategory.NARRATIVE,
    LLMTaskType.REFERRAL_LETTER: LLMTaskCategory.NARRATIVE,
    LLMTaskType.MEDICATION_INSTRUCTION: LLMTaskCategory.NARRATIVE,
}
```

### LLMResponse (unchanged)

```python
@dataclass
class LLMResponse:
    text: str | None
    source: Literal["llm", "template", "cache", "none"]
    model: str | None
    
    # For judgment tasks (populated by response_parser)
    chosen_option: str | None
    reasoning: str | None
    confidence: float | None
    additional_actions: list[str] | None
    
    # For consistency review
    issues: list[ConsistencyIssue] | None
    
    # Cost
    input_tokens: int | None
    output_tokens: int | None
```

### Prompt template format (YAML)

Each prompt template is a YAML file with structured sections:

```yaml
# prompts/progress_note.yaml
task_type: progress_note
model_tier: medium
max_output_tokens: 1500                    # SOAP note in Japanese needs 800-1500 tokens

system_prompt: |
  You are a {specialty} physician at a {hospital_type} hospital in {country}.
  Write a concise daily progress note in SOAP format.
  Use medical terminology appropriate for the country.
  Language: {language}

user_prompt: |
  Patient: {age}yo {sex}, Hospital Day {hospital_day}
  Diagnosis: {current_diagnosis} (confidence: {diagnosis_confidence}%)
  
  Overnight events: {interval_events}
  Current vitals: {latest_vitals}
  Latest labs: {latest_labs}
  Active medications: {active_treatments}
  
  Write the progress note for today's morning round.
  Focus on: {focus_areas}

output_format: |
  **S:** [patient subjective complaints]
  **O:** [objective findings including vitals and labs provided above]
  **A:** [assessment with clinical reasoning]
  **P:** [plan for today]
```

### Caching strategy

```python
class NarrativeCache:
    """Cache LLM outputs by clinical scenario pattern, not by specific patient."""
    
    def __init__(self, max_size: int = 2000):
        self.cache = {}  # cache_key → CachedNarrative
    
    def get(self, key: str) -> CachedNarrative | None:
        if key in self.cache:
            return self.cache[key]
        return None
    
    def put(self, key: str, response: LLMResponse):
        # Generalize: strip patient-specific identifiers
        generalized = response.text
        generalized = re.sub(r'\d{1,3}歳', '{age}歳', generalized)
        generalized = re.sub(r'CRP \d+', 'CRP {crp_value}', generalized)
        # ... more generalizations
        self.cache[key] = CachedNarrative(template=generalized, original=response)

@dataclass
class CachedNarrative:
    template: str      # generalized narrative with placeholders
    original: LLMResponse
    
    def adapt(self, context: LLMClinicalContext) -> str:
        """Re-inject patient-specific values into cached template."""
        text = self.template
        text = text.replace('{age}', str(context.age))
        text = text.replace('{crp_value}', context.get_lab('CRP'))
        # ... more substitutions
        return text
```

### Cost tracking & budget control

```python
class CostTracker:
    def __init__(self, budget_limit_tokens: int | None = None):
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.calls_by_type = defaultdict(int)
        self.budget_limit = budget_limit_tokens
    
    def record(self, model: str, input_tokens: int, output_tokens: int):
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
    
    def check_budget(self) -> bool:
        if self.budget_limit is None:
            return True
        return (self.total_input_tokens + self.total_output_tokens) < self.budget_limit
    
    def report(self) -> dict:
        return {
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_calls": sum(self.calls_by_type.values()),
            "calls_by_type": dict(self.calls_by_type),
            "cache_hit_rate": self.cache_hits / max(1, self.total_requests),
        }
```

When budget is exceeded, the service automatically falls back to template mode for remaining calls.

### Provider abstraction layer

The llm_service communicates with LLMs through a **provider abstraction layer**. Each provider implements a common interface, allowing the system to switch between providers without changing any calling code.

```python
class LLMProvider(ABC):
    """Abstract base class for LLM providers."""
    
    @abstractmethod
    def complete(self, prompt: str, model: str, max_tokens: int) -> ProviderResponse:
        """Send a prompt and return a response."""
        pass
    
    @abstractmethod
    def list_models(self) -> list[str]:
        """Return available model IDs."""
        pass

@dataclass
class ProviderResponse:
    text: str
    input_tokens: int
    output_tokens: int
    model: str
    latency_ms: int
```

#### Initial provider: EC2 Bedrock Gateway

The primary deployment architecture uses an **EC2-hosted LLM gateway** that communicates with AWS Bedrock:

```
clinosim (host machine)
  │
  │  HTTPS (REST API)
  ↓
EC2 LLM Gateway (lightweight API server)
  │
  │  AWS SDK (boto3)
  ↓
AWS Bedrock
  ├── Anthropic Claude models (Haiku, Sonnet, Opus)
  ├── (future: other Bedrock models)
  └── (future: custom fine-tuned models)
```

**Why a gateway?**
- The host machine running clinosim may not have direct AWS SDK access or credentials
- The gateway handles authentication, rate limiting, retry logic, and model routing
- The gateway can add logging, cost tracking, and request queuing
- Multiple clinosim instances can share the same gateway

```python
class BedrockGatewayProvider(LLMProvider):
    """Communicates with EC2-hosted gateway that proxies to AWS Bedrock."""
    
    def __init__(self, gateway_url: str, api_key: str | None = None):
        self.gateway_url = gateway_url    # e.g., "https://llm-gateway.internal:8443"
        self.api_key = api_key
    
    def complete(self, prompt: str, model: str, max_tokens: int) -> ProviderResponse:
        response = httpx.post(
            f"{self.gateway_url}/v1/complete",
            json={
                "prompt": prompt,
                "model": model,          # e.g., "anthropic.claude-3-5-haiku-20251001-v1:0"
                "max_tokens": max_tokens,
            },
            headers={"Authorization": f"Bearer {self.api_key}"} if self.api_key else {},
        )
        data = response.json()
        return ProviderResponse(
            text=data["text"],
            input_tokens=data["usage"]["input_tokens"],
            output_tokens=data["usage"]["output_tokens"],
            model=data["model"],
            latency_ms=data["latency_ms"],
        )
```

#### EC2 Gateway API specification

```yaml
# Gateway endpoints
POST /v1/complete
  Request:
    prompt: string
    model: string              # Bedrock model ID
    max_tokens: int
    temperature: float (default 0.7)
    system_prompt: string (optional)
  Response:
    text: string
    usage: {input_tokens: int, output_tokens: int}
    model: string
    latency_ms: int

GET /v1/models
  Response:
    models: [{id: string, provider: string, tier: string}]

GET /v1/health
  Response:
    status: "ok" | "degraded" | "down"
    bedrock_status: "ok" | "error"
```

#### Provider implementations

##### OllamaProvider (v0.1 default — local, no API key needed)

Ollama runs Llama models locally. This is the default provider for development and testing.

**Setup:**
```bash
# Install Ollama (macOS)
brew install ollama

# Pull recommended models
ollama pull llama3.1:8b      # JUDGMENT: fast, 8B params, sufficient for structured decisions
ollama pull llama3.1:70b     # NARRATIVE (if VRAM allows): better text quality
# or for lower memory:
ollama pull llama3.1:8b      # use 8B for both JUDGMENT and NARRATIVE
```

```python
class OllamaProvider(LLMProvider):
    """Local Llama via Ollama. Default provider for v0.1."""
    
    def __init__(self, config: dict):
        self.base_url = config.get("endpoint", "http://localhost:11434")
        self.default_model = config.get("model", "llama3.1:8b")
    
    def complete(self, prompt: str, model: str, max_tokens: int) -> ProviderResponse:
        response = httpx.post(
            f"{self.base_url}/api/generate",
            json={
                "model": model or self.default_model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "num_predict": max_tokens,
                    "temperature": 0.4,
                },
            },
            timeout=120,  # local models can be slow on first load
        )
        data = response.json()
        return ProviderResponse(
            text=data["response"],
            input_tokens=data.get("prompt_eval_count", 0),
            output_tokens=data.get("eval_count", 0),
            model=model,
            latency_ms=int(data.get("total_duration", 0) / 1_000_000),
        )
    
    async def complete_async(self, prompt: str, model: str, max_tokens: int) -> ProviderResponse:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": model or self.default_model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"num_predict": max_tokens, "temperature": 0.4},
                },
                timeout=120,
            )
            data = response.json()
            return ProviderResponse(
                text=data["response"],
                input_tokens=data.get("prompt_eval_count", 0),
                output_tokens=data.get("eval_count", 0),
                model=model,
                latency_ms=int(data.get("total_duration", 0) / 1_000_000),
            )
    
    def list_models(self) -> list[str]:
        response = httpx.get(f"{self.base_url}/api/tags")
        return [m["name"] for m in response.json().get("models", [])]
    
    def health_check(self) -> bool:
        try:
            response = httpx.get(f"{self.base_url}/api/tags", timeout=5)
            return response.status_code == 200
        except Exception:
            return False
```

**Recommended local model selection:**

| Use case | Model | VRAM | Quality | Speed |
|---|---|---|---|---|
| JUDGMENT (dev) | `llama3.1:8b` | ~6 GB | Sufficient for structured decisions | Fast (~5 tokens/s on CPU, ~50 on GPU) |
| JUDGMENT (quality) | `llama3.1:70b` | ~40 GB | Near-cloud quality | Slower |
| NARRATIVE (dev) | `llama3.1:8b` | ~6 GB | Acceptable for testing | Fast |
| NARRATIVE (quality) | `llama3.1:70b` | ~40 GB | Good narrative quality | Slower |
| NARRATIVE (best local) | `llama3.3:70b` | ~40 GB | Best open-source narrative | Slower |
| Japanese NARRATIVE | `llama3.1:70b` or `Qwen2.5:72b` | ~40 GB | Qwen2.5 has stronger Japanese | Slower |

**Note on Japanese output quality:** Llama 3.1/3.3 produces acceptable but imperfect Japanese. For production-quality Japanese narratives, consider `Qwen2.5:72b` (strong Japanese capability) for local, or Claude/GPT-4o via cloud API.

##### BedrockGatewayProvider (cloud — production quality)

```python
class BedrockGatewayProvider(LLMProvider):
    """EC2-hosted gateway proxying to AWS Bedrock. Production quality."""
    # (implementation as previously designed)
```

##### AnthropicDirectProvider (cloud — simplest cloud setup)

```python
class AnthropicDirectProvider(LLMProvider):
    """Direct Anthropic API. Simplest cloud setup — just needs API key."""
    
    def __init__(self, config: dict):
        import anthropic
        self.client = anthropic.Anthropic(api_key=os.environ[config.get("api_key_env", "ANTHROPIC_API_KEY")])
    
    def complete(self, prompt: str, model: str, max_tokens: int) -> ProviderResponse:
        response = self.client.messages.create(
            model=model,
            max_tokens=max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        return ProviderResponse(
            text=response.content[0].text,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            model=model,
            latency_ms=0,  # not easily available from SDK
        )
```

##### OpenAICompatibleProvider (vLLM, Azure, OpenAI, any compatible API)

```python
class OpenAICompatibleProvider(LLMProvider):
    """Works with any OpenAI-compatible API endpoint."""
    
    def __init__(self, config: dict):
        self.base_url = config.get("base_url", "https://api.openai.com/v1")
        self.api_key = os.environ.get(config.get("api_key_env", "OPENAI_API_KEY"), "")
    
    def complete(self, prompt: str, model: str, max_tokens: int) -> ProviderResponse:
        response = httpx.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens,
                "temperature": 0.4,
            },
            timeout=60,
        )
        data = response.json()
        return ProviderResponse(
            text=data["choices"][0]["message"]["content"],
            input_tokens=data["usage"]["prompt_tokens"],
            output_tokens=data["usage"]["completion_tokens"],
            model=model,
            latency_ms=0,
        )
```

##### Provider factory

```python
def create_provider(config: LLMProviderConfig) -> LLMProvider | None:
    if config.mode == "none":
        return None
    
    match config.provider:
        case "local":
            return OllamaProvider(config.local)
        case "bedrock_gateway":
            return BedrockGatewayProvider(config.bedrock_gateway)
        case "anthropic_direct":
            return AnthropicDirectProvider(config.anthropic_direct)
        case "openai_compatible":
            return OpenAICompatibleProvider(config.openai_compatible)
        case _:
            raise ValueError(f"Unknown provider: {config.provider}")
```
    pass
```

#### Provider configuration — separate JUDGMENT and NARRATIVE

JUDGMENT and NARRATIVE can use **different providers, different models, or even different services**. This enables:
- JUDGMENT on a fast local model (low latency, no API cost) + NARRATIVE on a cloud API (high quality text)
- JUDGMENT on Haiku (cheap, fast, sufficient for structured decisions) + NARRATIVE on Opus (best text quality)
- JUDGMENT on one region's Bedrock + NARRATIVE on another
- Both on the same provider but different model tiers

```yaml
# config/llm_service.yaml

# === JUDGMENT configuration (used during simulation, Stage 1) ===
judgment:
  mode: "llm"                            # "llm" | "template" | "none"
  provider: "bedrock_gateway"            # "bedrock_gateway" | "anthropic_direct" | "openai_compatible" | "local"
  
  # Provider-specific settings
  bedrock_gateway:
    url: "https://llm-gateway.internal:8443"
    api_key_env: "CLINOSIM_LLM_GATEWAY_KEY"
    timeout_seconds: 15                  # JUDGMENT needs low latency (in simulation hot path)
    retry_attempts: 3
    retry_backoff_seconds: 1
  
  # Model map for JUDGMENT tasks
  model_map:
    small: "anthropic.claude-3-5-haiku-20251001-v1:0"    # care_seeking_judgment
    medium: "anthropic.claude-3-5-haiku-20251001-v1:0"   # diagnostic_reasoning, treatment_decision
    large: "anthropic.claude-sonnet-4-6-20250514-v1:0"   # consistency_review
  
  budget:
    max_tokens_per_run: 2000000          # ~10.6K/patient × ~200 patients
    fallback_on_budget_exceeded: "template"

# === NARRATIVE configuration (used in Stage 2, separate from simulation) ===
narrative:
  mode: "llm"                            # "llm" | "template" | "none"
  provider: "bedrock_gateway"            # can be different from judgment provider
  
  bedrock_gateway:
    url: "https://llm-gateway.internal:8443"
    api_key_env: "CLINOSIM_LLM_GATEWAY_KEY"
    timeout_seconds: 60                  # NARRATIVE can tolerate higher latency (batch processing)
    retry_attempts: 3
    retry_backoff_seconds: 2
  
  # Model map for NARRATIVE tasks
  model_map:
    small: "anthropic.claude-3-5-haiku-20251001-v1:0"    # chief_complaint, nursing_note
    medium: "anthropic.claude-sonnet-4-6-20250514-v1:0"  # progress_note, treatment_rationale
    large: "anthropic.claude-opus-4-6-20250610-v1:0"     # admission_hp, discharge_summary
  
  budget:
    max_tokens_per_run: 10000000         # ~30K/patient × ~200 patients
    fallback_on_budget_exceeded: "template"

# === Shared settings ===
cache:
  enabled: true
  max_entries: 5000
  persist_to_disk: true                  # save cache in CIF for reproducibility
```

#### Default configuration (v0.1: local Ollama)

```yaml
# config/llm_service.yaml — DEFAULT (no cloud API needed)
judgment:
  mode: "llm"
  provider: "local"
  local:
    endpoint: "http://localhost:11434"
    model: "llama3.1:8b"
  model_map:
    small: "llama3.1:8b"
    medium: "llama3.1:8b"
    large: "llama3.1:8b"
  timeout_seconds: 120
  retry_attempts: 2

narrative:
  mode: "llm"
  provider: "local"
  local:
    endpoint: "http://localhost:11434"
    model: "llama3.1:8b"
  model_map:
    small: "llama3.1:8b"
    medium: "llama3.1:8b"
    large: "llama3.1:8b"           # upgrade to 70b if VRAM available
  timeout_seconds: 180              # narrative generation can be slow locally
  retry_attempts: 2

cache:
  enabled: true
  max_entries: 5000
  persist_to_disk: true
```

**To use this default**: just install Ollama and `ollama pull llama3.1:8b`. No API keys, no cloud accounts.

#### Example configurations

```yaml
# Config 1: Local model for JUDGMENT, cloud for NARRATIVE
judgment:
  mode: "llm"
  provider: "local"
  local:
    endpoint: "http://localhost:11434/api/generate"   # Ollama
    model: "llama3.1:8b"                              # fast local model
  model_map:
    small: "llama3.1:8b"
    medium: "llama3.1:8b"
    large: "llama3.1:70b"

narrative:
  mode: "llm"
  provider: "bedrock_gateway"
  bedrock_gateway:
    url: "https://llm-gateway.internal:8443"
  model_map:
    small: "anthropic.claude-3-5-haiku-20251001-v1:0"
    medium: "anthropic.claude-sonnet-4-6-20250514-v1:0"
    large: "anthropic.claude-opus-4-6-20250610-v1:0"
```

```yaml
# Config 2: No LLM at all (template/rule-based only)
judgment:
  mode: "template"
narrative:
  mode: "none"       # structural data only, no narratives generated
```

```yaml
# Config 3: Same provider, different model tiers
judgment:
  mode: "llm"
  provider: "anthropic_direct"
  anthropic_direct:
    api_key_env: "ANTHROPIC_API_KEY"
  model_map:
    small: "claude-haiku-4-5-20251001"
    medium: "claude-haiku-4-5-20251001"
    large: "claude-sonnet-4-6-20250514"

narrative:
  mode: "llm"
  provider: "anthropic_direct"
  anthropic_direct:
    api_key_env: "ANTHROPIC_API_KEY"
  model_map:
    small: "claude-haiku-4-5-20251001"
    medium: "claude-sonnet-4-6-20250514"
    large: "claude-opus-4-6-20250610"
```

```yaml
# Config 4: OpenAI-compatible (vLLM, Azure OpenAI, etc.)
judgment:
  mode: "llm"
  provider: "openai_compatible"
  openai_compatible:
    base_url: "https://my-vllm-server:8000/v1"
    api_key_env: "VLLM_API_KEY"
    model: "meta-llama/Llama-3.1-70B-Instruct"
  model_map:
    small: "meta-llama/Llama-3.1-8B-Instruct"
    medium: "meta-llama/Llama-3.1-70B-Instruct"
    large: "meta-llama/Llama-3.1-70B-Instruct"

narrative:
  mode: "llm"
  provider: "openai_compatible"
  openai_compatible:
    base_url: "https://api.openai.com/v1"
    api_key_env: "OPENAI_API_KEY"
  model_map:
    small: "gpt-4o-mini"
    medium: "gpt-4o"
    large: "gpt-4o"
```

#### LLMService internal routing

```python
class LLMService:
    def __init__(self, config: LLMServiceConfig):
        # Separate providers for JUDGMENT and NARRATIVE
        self.judgment_provider = create_provider(config.judgment)
        self.narrative_provider = create_provider(config.narrative)
        self.judgment_config = config.judgment
        self.narrative_config = config.narrative
    
    def generate(self, task_type: LLMTaskType, event: ClinicalEventData) -> LLMResponse:
        category = TASK_CATEGORY[task_type]
        
        if category == LLMTaskCategory.JUDGMENT:
            provider = self.judgment_provider
            mode = self.judgment_config.mode
            model_map = self.judgment_config.model_map
            budget = self.judgment_budget_tracker
        else:
            provider = self.narrative_provider
            mode = self.narrative_config.mode
            model_map = self.narrative_config.model_map
            budget = self.narrative_budget_tracker
        
        if mode == "none":
            return LLMResponse(text=None, source="none")
        if mode == "template":
            return self._template_generate(...)
        
        # LLM mode — use the appropriate provider
        prompt_config = self.prompt_registry.load(task_type)
        model = model_map[prompt_config.model_tier]
        
        return self._call_with_resilience(prompt, model, provider, budget, ...)
```

### Cache
cache:
  enabled: true
  max_entries: 2000
```

### Caller pattern (how modules use the service)

Each module calls `llm_service.request()` with a structured request:

```python
# In diagnosis module:
def generate_diagnostic_reasoning(context, differential_before, differential_after, new_findings):
    llm_context = build_clinical_context(context)
    llm_context.interval_events = new_findings
    
    response = llm_service.request(LLMRequest(
        task_type=LLMTaskType.DIAGNOSTIC_REASONING,
        context=llm_context,
        language=context.country_language,
        model_tier="medium",
        max_output_tokens=300,
        instructions=f"Explain why differential changed from {differential_before} to {differential_after}",
    ))
    
    return response.text  # may be None if mode="none", template text if mode="template"
```

```python
# In encounter module:
def generate_discharge_summary(patient, encounter, timeline):
    llm_context = build_clinical_context_from_encounter(patient, encounter, timeline)
    
    response = llm_service.request(LLMRequest(
        task_type=LLMTaskType.DISCHARGE_SUMMARY,
        context=llm_context,
        language=patient.country_language,
        model_tier="large",
        max_output_tokens=1200,
    ))
    
    return response.text
```

---

### Graceful degradation (error handling)

**Principle: LLM failure never stops the simulation.** The system degrades gracefully from LLM → template → structured-only.

```python
def _call_with_resilience(self, prompt: str, model: str, 
                           prompt_config, event, language) -> LLMResponse:
    """Call LLM with retry, fallback, and graceful degradation."""
    
    # Check budget before calling
    if not self.cost_tracker.check_budget():
        self._log("warn", "Budget exceeded. Falling back to template mode.")
        return self._template_generate(prompt_config, event, language)
    
    # Retry with exponential backoff
    last_error = None
    for attempt in range(self.config.retry_attempts):  # default: 3
        try:
            raw = self.provider.complete(prompt, model, prompt_config.max_output_tokens)
            
            # Parse response
            parsed = prompt_config.parse_response(raw.text)
            
            # Track cost
            self.cost_tracker.record(model, raw.input_tokens, raw.output_tokens)
            
            # Cache successful response
            cache_key = self._make_cache_key(prompt_config.task_type, event, language)
            self.cache.put(cache_key, parsed)
            
            return parsed
        
        except ProviderTimeoutError as e:
            last_error = e
            wait = self.config.retry_backoff_seconds * (2 ** attempt)
            self._log("warn", f"LLM timeout (attempt {attempt+1}/{self.config.retry_attempts}). "
                              f"Retrying in {wait}s.")
            time.sleep(wait)
        
        except ProviderRateLimitError as e:
            last_error = e
            wait = e.retry_after or (self.config.retry_backoff_seconds * (2 ** attempt))
            self._log("warn", f"Rate limited. Waiting {wait}s.")
            time.sleep(wait)
        
        except ProviderError as e:
            last_error = e
            self._log("error", f"LLM provider error: {e}")
            break  # non-retryable error
        
        except ResponseParseError as e:
            last_error = e
            self._log("warn", f"Failed to parse LLM response (attempt {attempt+1}). Retrying.")
            continue
    
    # All retries exhausted — fallback to template
    self._log("warn", f"LLM unavailable after {self.config.retry_attempts} attempts. "
                      f"Falling back to template for {prompt_config.task_type}. Error: {last_error}")
    self.metrics.llm_fallback_count += 1
    
    return self._template_generate(prompt_config, event, language)
```

**Degradation chain:**

```
LLM mode (full quality)
  |  failure / timeout / budget exceeded
  v
Template mode (rule-based text, no LLM cost)
  |  template not available for this task type
  v
Structured-only mode (no text, just data)
  |  this always succeeds
  v
Simulation continues. Never halts.
```

**Logging and metrics:**

Every fallback is logged with:
- Task type that failed
- Error type (timeout, rate limit, parse error, budget)
- Fallback level used (template or structured-only)
- Patient ID and encounter context

End-of-run report includes:
```python
@dataclass
class LLMHealthReport:
    total_calls: int
    successful_llm_calls: int
    cache_hits: int
    template_fallbacks: int
    structured_only_fallbacks: int
    total_retries: int
    errors_by_type: dict[str, int]        # {"timeout": 3, "rate_limit": 1, ...}
    llm_availability_rate: float           # successful / (successful + fallback)
```

## Open Questions
- [ ] ~~LLM provider abstraction~~ **Resolved**: Provider abstraction layer with BedrockGatewayProvider as primary. Pluggable for future providers.
- [ ] Prompt versioning: how to track and A/B test prompt changes
- [ ] Async / parallel LLM calls for batch patient generation
- [ ] Quality scoring: how to automatically evaluate generated narrative quality
- [ ] Language mixing: JP hospital may have some English medical terms in notes (realistic)
- [ ] EC2 Gateway deployment: instance type, auto-scaling, authentication scheme
- [ ] Bedrock model availability by region (Claude model access may vary)

## Design Notes
- This module is the ONLY place where LLM API calls happen. Period.
- Prompt templates are external YAML files, not hardcoded strings. This allows prompt engineering without code changes.
- Template-mode fallback ensures the system works without any LLM provider configured.
- Cost tracking enables users to set a budget and know exactly how much LLM usage each run costs.
- Cache key design is critical: too specific = low hit rate; too general = inappropriate reuse. The current approach caches by (task_type, disease, severity_bucket, hospital_day_bucket, country) which should give ~40–60% hit rate for common diseases.
