<!-- Extracted from `README.md` (Issue #568 PR A). Update the pointer in README when this file's heading changes. -->

# LLM Integration (Optional)

clinosim uses LLMs only for **clinical documents** (Stage 2). All structural data (labs, vitals, diagnoses, meds) is deterministic and does not require an LLM.

### Architecture

- Single entry point: `clinosim.modules.llm_service.LLMService` (AD-11). No other module may call an LLM SDK directly.
- Two task categories (AD-13, AD-24):
  - **JUDGMENT** — clinical reasoning, always English, structured output (reserved for future use).
  - **NARRATIVE** — clinical documents, target language, free text.
- Pluggable providers via `clinosim.modules.llm_service.providers`:
  - `ollama` — local Ollama server (default)
  - `bedrock` — AWS Bedrock via Converse API (for EC2 deployment)
  - `vllm` — OpenAI-compatible `/v1/chat/completions` endpoint
    (vLLM, SGLang, or any other OpenAI-compatible server; supports
    continuous batching via `--concurrency` on `clinosim narrate`)
  - `openai_compatible` — alias for `vllm`
  - `mock` — deterministic stub for tests
  - New providers can be registered via `providers.register_provider()`.
- Prompt templates live as YAML under `clinosim/modules/llm_service/prompts/<lang>/<task>.yaml` and are rendered with `string.Template`.
- All responses are cached by SHA256(system + user + model) on disk for reproducibility and cost control.

### Local Ollama (default)

```bash
brew install ollama
ollama serve
ollama pull llama3.1:8b

clinosim narrate --cif-dir ./output/cif \
  --llm-config clinosim/config/llm_service.yaml \
  --version-id ollama_en_v1
```

### AWS Bedrock (EC2)

```bash
pip install 'clinosim[bedrock]'   # installs boto3

# On an EC2 instance with an IAM role that grants bedrock:Converse:
clinosim narrate --cif-dir ./cif \
  --llm-config clinosim/config/llm_service.bedrock.yaml \
  --version-id bedrock_sonnet_en_v1
```

See [../bedrock_setup.md](../bedrock_setup.md) for full EC2 + IAM setup.

### Template mode (no LLM)

```bash
clinosim narrate --cif-dir ./output/cif --version-id template_v1
```

Template mode runs Stage 2 without any network call and produces deterministic placeholder content. Useful for CI, reproducibility tests, and sanity checks.

### Extending to new providers

```python
from clinosim.modules.llm_service.providers import register_provider

class MyProvider:
    def __init__(self, config): ...
    def complete(self, prompt, model, max_tokens, system_prompt, **kwargs): ...
    def health_check(self): return True

register_provider("my_provider", lambda cfg: MyProvider(cfg))
```

Then reference `provider: my_provider` in your `llm_service.yaml`.

Details: [../clinical_documents.md](../clinical_documents.md), `clinosim/modules/llm_service/README.md`

---
