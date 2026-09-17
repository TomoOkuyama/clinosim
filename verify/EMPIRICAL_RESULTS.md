# Empirical verify results (H100 Boot 4, 2026-09-17)

**Cohort**: JP p=100 s=917 (`verify/cohort_p100_jp_s917.tar.gz`), 373
narrative documents across 258 encounters (mostly outpatient_soap +
progress_note + admission_hp).

**Model**: Qwen/Qwen3.8-27B-FP8 on H100 80GB.

**Fallback fix applied**: `enable_thinking: false` in
`verify/llm_service_vllm.yaml` — critical because Qwen3.8 emits a
`</think>` block prefix by default even when the prompt says
`/no_think`, breaking the bundle strategy's JSON parse. Without this
setting, all narrate docs fall back to per-section template rendering
(100% fallback rate). Fix passes
`chat_template_kwargs={"enable_thinking": false}` via the vLLM
provider's payload.

## vLLM #0 (S117 exact replay config)

Startup flags:
```
VLLM_USE_FLASHINFER_SAMPLER=0
--max-model-len 16384
--gpu-memory-utilization 0.88
--max-num-seqs 32
(NO --enable-prefix-caching)
```
Boot time: 481s cold start.

### Case A_S117 (v22 JA canonical prompt, PC OFF)
- 373 docs in **6m 44s (404s)** → **0.923 doc/s**
- Fallbacks: **0**
- S117 baseline reproduced (S117 reported ~0.68 doc/s; the discrepancy
  is cohort content variance — S117 measured different p=100 s=400/401
  cohorts, and doc size + section count vary)

### Case A_prime (v22 EN scaffold prompt, PC OFF)
- 373 docs in **6m 31s (391s)** → **0.954 doc/s**
- Fallbacks: **0**
- **Factor A delta: +3.4% throughput vs A_S117** — small, consistent
  with the pre-boot tokenizer analysis showing EN scaffold saves only
  ~6.1% of system-prompt tokens

### Case E (v21 JA prompt, PC OFF)
- 373 docs in **6m 13.8s (374s)** → **0.998 doc/s**
- Fallbacks: **0**
- **Factor B+C delta: +8.1% throughput vs A_S117** — matches the
  pre-boot analysis that v21→v22 added Rule 3 VERBATIM COPY (~14 lines
  in system prompt + longer ICD-10-CM labels in completion tokens per
  doc). Confirms the v22 prompt content is the largest single
  regression driver among prompt-level factors.

## Summary of PC-OFF phase (vLLM #0)

| Case | prompt | doc/s | Δ vs A_S117 | fallbacks |
|---|---|---|---|---|
| A_S117 | v22 JA (canonical) | 0.923 | — | 0 |
| A_prime | v22 EN scaffold | 0.954 | +3.4% | 0 |
| E | v21 JA (pre-v22 content) | 0.998 | +8.1% | 0 |

## vLLM #1 (PC ON) — cases pending

Startup: same as #0 plus `--enable-prefix-caching`. Boot in progress at
commit time. Cases planned: A_pc (v22 JA), F (v22 JA Fix A prompt),
A_pc_c128 (concurrency 128), and possibly more if hour 5 permits.

## Key discovery: `enable_thinking: false` is REQUIRED

Without this yaml config field, Qwen's `</think>` prefix breaks bundle
strategy's JSON parser 100% of the time. Historical S117 successful
runs (verified from `~/autonomous_run/vllm.log` from Sep 7) used the
env var pattern `VLLM_USE_FLASHINFER_SAMPLER=0` but the LLM output was
still working — suggesting the Qwen model behavior around thinking may
have shifted between Sep 7 and now. This fix is essential for future
narrate runs.

## Reproducibility

vLLM startup script (matches S117 successful pattern):
```bash
export VLLM_USE_FLASHINFER_SAMPLER=0
vllm serve Qwen/Qwen3.8-27B-FP8 \
    --host 127.0.0.1 --port 8000 \
    --max-model-len 16384 \
    --gpu-memory-utilization 0.88 \
    --max-num-seqs 32 \
    --dtype auto \
    --gdn-prefill-backend triton \
    --served-model-name Qwen/Qwen3.8-27B-FP8
```

clinosim LLM service yaml (essential):
```yaml
narrative:
  provider: "vllm"
  vllm:
    endpoint: "http://localhost:8000"
    model: "Qwen/Qwen3.8-27B-FP8"
    enable_thinking: false   # <— CRITICAL, else JSON parse fallback 100%
```
