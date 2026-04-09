# Bedrock Narrative Generation Setup Guide

## Overview

clinosim v0.1-beta now supports AWS Bedrock for generating high-quality clinical narratives. This document provides setup instructions and usage guidelines for the next Claude session.

## What Was Implemented (2026-04-09)

### 1. BedrockProvider Class
- Location: `clinosim/modules/llm_service/providers.py`
- Uses boto3 to call Bedrock Runtime API
- Supports Claude 3 models (Sonnet, Opus, Haiku)
- Error handling: ValidationException, ModelNotReadyException, ThrottlingException
- Retry logic: 3 attempts with exponential backoff
- Lazy client initialization

### 2. Five LOINC-Compliant Document Types

| LOINC | Type | Generation Condition | Count (30k catchment, 1yr) |
|---|---|---|---|
| 34117-2 | Admission H&P | All admissions | 171 |
| 18842-5 | Discharge Summary | All discharges | 171 |
| 11504-8 | Operative Note | Surgeries (hip fracture, etc.) | 11 |
| 28570-0 | Procedure Note | Invasive bedside procedures | 19 |
| 69730-0 | Death Note | Death discharges | 2 |
| **Total** | | | **374** |

**Token estimate**: ~1.8M tokens (vs ~90M if progress/nursing notes included)

### 3. Configuration Files

- **Default (Ollama)**: `clinosim/config/llm_service.yaml`
- **Bedrock**: `clinosim/config/llm_service.bedrock.yaml` ← NEW
- **Anthropic API**: `clinosim/config/llm_service.cloud.yaml`

### 4. Test Script

- **File**: `test_bedrock_narrative.py`
- **Purpose**: Test all 5 document types with Bedrock
- **Features**: Health check, narrative generation, token usage report

## AWS Setup

### Prerequisites

```bash
# Install boto3
pip install boto3

# Configure AWS credentials (choose one method)
# Method 1: AWS CLI
aws configure

# Method 2: Environment variables
export AWS_ACCESS_KEY_ID=AKIA...
export AWS_SECRET_ACCESS_KEY=...
export AWS_REGION=us-east-1

# Method 3: IAM role (on EC2/ECS)
# No configuration needed
```

### IAM Policy

Attach this policy to your IAM user/role:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "bedrock:InvokeModel",
      "Resource": "arn:aws:bedrock:*::foundation-model/anthropic.claude-*"
    }
  ]
}
```

### Supported Regions

- `us-east-1` (N. Virginia) ← Recommended
- `us-west-2` (Oregon)
- `ap-northeast-1` (Tokyo)
- `eu-west-3` (Paris)

Check [AWS Bedrock availability](https://docs.aws.amazon.com/bedrock/latest/userguide/what-is-bedrock.html#bedrock-regions) for updates.

### Supported Models (as of 2026-04-09)

| Model ID | Name | Use Case |
|---|---|---|
| `anthropic.claude-3-5-sonnet-20241022-v2:0` | Claude 3.5 Sonnet v2 | Recommended (best quality/cost) |
| `anthropic.claude-3-opus-20240229-v1:0` | Claude 3 Opus | Highest quality |
| `anthropic.claude-3-sonnet-20240229-v1:0` | Claude 3 Sonnet | Balanced |
| `anthropic.claude-3-haiku-20240307-v1:0` | Claude 3 Haiku | Fastest/cheapest |

## Testing

### Quick Test

```bash
python test_bedrock_narrative.py
```

Expected output:
```
Test 1: BedrockProvider Health Check
✓ BedrockProvider initialized successfully

Test 2: Narrative Generation (5 Document Types)
1. Admission H&P (LOINC 34117-2)
✓ Generated (1234 chars)

2. Discharge Summary (LOINC 18842-5)
✓ Generated (1567 chars)

...

Summary
Passed: 5/5

Token usage:
  Input:  12,345
  Output: 23,456
  Calls:  5
  Fallbacks: 0

✓ All tests passed!
```

### Troubleshooting

| Error | Cause | Solution |
|---|---|---|
| `ModuleNotFoundError: No module named 'boto3'` | boto3 not installed | `pip install boto3` |
| `Failed to create Bedrock client` | AWS credentials not configured | Run `aws configure` or set env vars |
| `Model not ready` | Model not available in region | Change region in config |
| `ThrottlingException` | Rate limit exceeded | Reduce concurrency or wait |
| `ValidationException` | Invalid request format | Check model ID and parameters |

## Usage in Code

### Basic Usage

```python
from clinosim.modules.llm_service.engine import (
    LLMService, LLMTaskType, PatientSummary, ClinicalEventData
)
from clinosim.modules.llm_service.providers import BedrockProvider

# Initialize provider
provider = BedrockProvider({
    "region": "us-east-1",
    "model": "anthropic.claude-3-5-sonnet-20241022-v2:0",
})

# Initialize service
llm = LLMService(
    mode="llm",
    narrative_provider=provider,
    narrative_model_map={"medium": "anthropic.claude-3-5-sonnet-20241022-v2:0"},
)

# Generate discharge summary
patient = PatientSummary(
    age=72, sex="M", country="JP",
    chief_complaint="呼吸困難と発熱",
    current_diagnosis="細菌性肺炎",
)

event = ClinicalEventData(
    patient_summary=patient,
    event_data={
        "final_diagnosis": "細菌性肺炎（Streptococcus pneumoniae）",
        "los_days": 14,
        "discharge_medications": ["アモキシシリン", "アセトアミノフェン"],
    },
    language="ja",
)

response = llm.generate(LLMTaskType.DISCHARGE_SUMMARY, event)
print(response.text)
```

### With Configuration File

```python
import yaml

# Load Bedrock config
with open("clinosim/config/llm_service.bedrock.yaml") as f:
    config = yaml.safe_load(f)

provider = BedrockProvider(config["narrative"]["bedrock"])
llm = LLMService(
    mode=config["narrative"]["mode"],
    narrative_provider=provider,
    narrative_model_map=config["narrative"]["model_map"],
)
```

## Integration Points

### Where Narratives Are Generated

1. **output module** - During FHIR export
   - Calls `llm_service.generate()` for each encounter
   - Attaches DocumentReference resources to FHIR bundle

2. **simulator** - Post-simulation narrative layer (Stage 2)
   - Separate from structural data generation
   - Can be re-run with different LLM settings

### Document Type Selection Logic

```python
# In output module (pseudo-code)
def generate_narratives(encounter):
    narratives = []
    
    # All admissions get Admission H&P
    if encounter.encounter_type == "inpatient":
        narratives.append(generate(LLMTaskType.ADMISSION_HP, ...))
    
    # All discharges (except death) get Discharge Summary
    if encounter.discharge_datetime and not encounter.died:
        narratives.append(generate(LLMTaskType.DISCHARGE_SUMMARY, ...))
    
    # Surgeries get Operative Note
    if encounter.has_surgery:
        narratives.append(generate(LLMTaskType.OPERATIVE_NOTE, ...))
    
    # Invasive procedures get Procedure Note
    for proc in encounter.procedures:
        if proc.is_invasive:
            narratives.append(generate(LLMTaskType.PROCEDURE_NOTE, ...))
    
    # Deaths get Death Note
    if encounter.died:
        narratives.append(generate(LLMTaskType.DEATH_NOTE, ...))
    
    return narratives
```

## Next Steps

### Immediate (v0.1 completion)

- [ ] Integrate BedrockProvider into main simulation pipeline
- [ ] Add DocumentReference resources to FHIR output
- [ ] Test with full 30k catchment simulation
- [ ] Measure actual token consumption and cost

### Near-term (v0.2)

- [ ] Implement Bedrock Prompt Caching (reduce input token costs)
- [ ] Add response caching (LRU cache for common scenarios)
- [ ] Parallel narrative generation (async batch processing)
- [ ] Cost tracking and budget limits

### Future

- [ ] Support for streaming responses
- [ ] Multi-model ensemble (Haiku for simple, Opus for complex)
- [ ] Custom fine-tuned models on Bedrock
- [ ] A/B testing framework for prompt optimization

## Cost Management

### Estimated Costs (Claude 3.5 Sonnet on Bedrock, as of 2026-04)

- Input: $3 per 1M tokens
- Output: $15 per 1M tokens

For 374 documents (~1.8M tokens total, ~40% input, ~60% output):
- Input cost: 0.72M × $3/M = **$2.16**
- Output cost: 1.08M × $15/M = **$16.20**
- **Total: ~$18.36 per 30k catchment year**

Scaling:
- 60k catchment: ~$36.72/year
- 120k catchment: ~$73.44/year

### Budget Control

In `llm_service.bedrock.yaml`:

```yaml
narrative:
  max_tokens_per_run: 10000000  # Hard limit (10M tokens)
  fallback_on_budget_exceeded: "template"  # Switch to template mode
```

When limit reached, service automatically falls back to template-based generation (no cost, lower quality).

## File Locations

```
clinosim/
├── config/
│   ├── llm_service.yaml              # Default (Ollama)
│   ├── llm_service.bedrock.yaml      # Bedrock config ← NEW
│   └── llm_service.cloud.yaml        # Anthropic API
├── modules/llm_service/
│   ├── __init__.py
│   ├── README.md                     # Updated with Bedrock docs
│   ├── engine.py                     # LLMService, LLMTaskType (5 types only)
│   └── providers.py                  # OllamaProvider, BedrockProvider, MockProvider
├── test_bedrock_narrative.py        # Test script ← NEW
└── BEDROCK_SETUP.md                  # This file ← NEW
```

## References

- [AWS Bedrock Documentation](https://docs.aws.amazon.com/bedrock/)
- [Claude on Bedrock](https://docs.aws.amazon.com/bedrock/latest/userguide/model-parameters-claude.html)
- [Bedrock Pricing](https://aws.amazon.com/bedrock/pricing/)
- [boto3 Bedrock Runtime](https://boto3.amazonaws.com/v1/documentation/api/latest/reference/services/bedrock-runtime.html)
- [LOINC Document Codes](https://loinc.org/document-ontology/)

## Contact

For issues or questions about this implementation, refer to:
- `clinosim/modules/llm_service/README.md` - Module documentation
- `test_bedrock_narrative.py` - Working examples
- GitHub Issues: https://github.com/TomoOkuyama/clinosim/issues
