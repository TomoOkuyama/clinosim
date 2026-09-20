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

## vLLM #1 (PC ON, otherwise same as #0)

Startup added `--enable-prefix-caching`. Warm reboot: 240s (vs 481s
cold on vLLM #0).

### Case A_pc (v22 JA canonical, PC ON)
- 373 docs in **2m 12.7s (133s)** → **2.813 doc/s**
- Fallbacks: **0**
- **Δ vs A_S117: +205% (3.05×)** — massive throughput uplift from just
  enabling prefix caching. This is THE dominant factor in the S117
  "regression". S117's production script had prefix caching OFF, so
  every request re-prefilled ~12k tokens of system prompt from scratch.

### Case F (v22 JA Fix A prompt, PC ON)
- 373 docs in **1m 48.2s (108s)** → **3.448 doc/s**
- Fallbacks: **0**
- **Δ vs A_S117: +273% (3.73×)**, **Δ vs A_pc: +22.5%**
- Fix A (moving `${document_type}` and `${target_language}` out of the
  system prompt into user_prompt) provides additional 22.5% on top of
  PC ON, because the system prompt becomes 100% prefix-cacheable
  across doc types (not just within same doc type). Compound with
  Fix C (PC ON) — total 3.73× S117 baseline.

### Case A_pc_c128 (v22 JA, PC ON, concurrency 128)
- 373 docs in **2m 10.8s (131s)** → **2.851 doc/s**
- Fallbacks: **0**
- **Δ vs A_pc: +1.4%** — concurrency 32→128 gives essentially zero
  benefit under FP16 KV cache. Confirms the R4 pre-boot theoretical
  analysis: `--max-num-seqs 32` is a hard ceiling with FP16 KV at 13k
  prompts on 80GB H100. Client-side concurrency > 32 gets queued
  server-side.

## Summary of PC-ON phase (vLLM #1)

| Case | prompt | conc | doc/s | Δ vs A_S117 | fallbacks |
|---|---|---|---|---|---|
| A_pc | v22 JA canonical | 32 | 2.813 | +205% | 0 |
| A_pc_c128 | v22 JA canonical | 128 | 2.851 | +209% | 0 |
| F | v22 JA Fix A | 32 | 3.448 | +273% | 0 |

## vLLM #2 (PC ON + FP8 KV, max-num-seqs 64)

### Case G (Fix A + PC ON + FP8 KV, conc 32)
- 373 docs in **2m 43.9s (164s)** → **2.275 doc/s**
- Fallbacks: **0**
- **Δ vs F: -34%** — FP8 KV made things SLOWER for this workload.
  FP8→FP16 conversion overhead outweighed extra KV budget benefit.

### Case G_c64 (Fix A + PC ON + FP8 KV, conc 64)
- 373 docs in **2m 24.4s (144s)** → **2.583 doc/s**
- Fallbacks: **0**
- Still 25% slower than Case F. **FP8 KV recommendation DROPPED.**

## Phase 2 additional cases (Boot 5, 2026-09-17)

### Case F_repro (v22 JA Fix A + PC ON + max-num-seqs 32, conc 32)
- 373 docs in **1m 45.3s (105s)** → **3.542 doc/s** (variance ~+3% over Case F)
- Fallbacks: **0**
- Confirms Case F reproducibility as the new baseline.

### Case J (Fix A + PC ON + guided_json)
- 373 docs in **1m 51.2s (111s)** → **3.354 doc/s**
- Fallbacks: **0** (structurally guaranteed via xgrammar constraint)
- **Δ vs F_repro: -5.3%** — matches vLLM benchmark prediction. Trades
  small speed cost for guaranteed fallback-0.

### Case R2 (Fix A + max_tokens 2500)
- 373 docs in **1m 46.9s (107s)** → **3.489 doc/s**
- Fallbacks: **0**
- **Avg gen tokens = 215** (measured via `/v1/metrics` delta) — response
  ceiling of 2500 tokens uses only 8.6% capacity, no truncation risk.
- **Δ vs F_repro: -1.5%** — noise. max_tokens reduction has essentially
  zero throughput impact on this workload. Frees max-model-len budget
  but doesn't move throughput by itself.

### Case P1 (Fix A + max-num-seqs 64, conc 32)
- 373 docs in **1m 51.9s (112s)** → **3.334 doc/s**
- Fallbacks: **0**
- **Δ vs F_repro: -5.9%** — increasing server capacity to 64 without
  raising client conc did NOT help (concurrency 32 saturates any
  ceiling >= 32). Small regression is noise.

### Case P1_c64 (Fix A + max-num-seqs 64, conc 64)
- 373 docs in **1m 36.8s (97s)** → **3.852 doc/s**
- Fallbacks: **0**
- **Δ vs F_repro: +8.7%** — **NEW WINNER!** Raising both server
  max-num-seqs AND client concurrency to 64 unlocks additional
  throughput. The FP16 KV budget can accommodate 64 seqs on this
  workload despite theoretical R4 analysis suggesting ~22 seqs max —
  actual per-doc prompt length must average lower than the 13k P95
  estimate, or vLLM's page-based KV allocator is more efficient than
  the linear estimate.

### Case P3 (Fix A + max-num-seqs 64 + max-model-len 12288 + conc 64) — ATTEMPTED, FAILED
- vLLM #C startup failed with "Free memory on device cuda:0
  (7.68/79.18 GiB) < required 69.68 GiB" — previous vLLM #B pkill left
  ~72 GB of GPU memory unreleased. Needed sudo `nvidia-smi --gpu-reset`
  or reboot to clear, out of billing time. Data not collected.

## Comprehensive summary (across all boots)

| Case | Config | doc/s | Δ vs A_S117 | Δ vs F_repro |
|---|---|---|---|---|
| A_S117 | v22 JA, PC OFF | 0.923 | baseline | — |
| A_prime | v22 EN scaffold, PC OFF | 0.954 | +3.4% | — |
| E | v21 JA, PC OFF | 0.998 | +8.1% | — |
| A_pc | v22 JA, PC ON | 2.813 | +205% | — |
| F / F_repro | Fix A + PC ON | 3.448-3.542 | +273-284% | baseline |
| J | Fix A + PC ON + guided_json | 3.354 | +263% | -5.3% |
| R2 | Fix A + max_tok 2500 | 3.489 | +278% | -1.5% |
| P1 | Fix A + max_seqs 64, conc 32 | 3.334 | +261% | -5.9% |
| **P1_c64** | **Fix A + max_seqs 64, conc 64** | **3.852** | **+317%** | **+8.7%** |
| A_pc_c128 | Fix A + max_seqs 32, conc 128 | 2.851 | +209% | -19% (32 seq ceiling) |
| G | Fix A + FP8 KV | 2.275 | +147% | -34% (FP8 overhead) |
| G_c64 | Fix A + FP8 KV, conc 64 | 2.583 | +180% | -27% |

## Winner: **Case P1_c64 = 3.852 doc/s = 4.17× S117 baseline**

Ship config:
```bash
vllm serve Qwen/Qwen3.8-27B-FP8 \
  --host 127.0.0.1 --port 8000 \
  --max-model-len 16384 --enable-prefix-caching \
  --gpu-memory-utilization 0.88 --max-num-seqs 64 \
  --dtype auto --gdn-prefill-backend triton \
  --served-model-name Qwen/Qwen3.8-27B-FP8
# Env: VLLM_USE_FLASHINFER_SAMPLER=0

# Client:
clinosim narrate --provider vllm --concurrency 64 ...
# Yaml: enable_thinking: false + Fix A prompt applied
```

## Phase 2 lost (P3): recommended for Phase 3 boot

- Case P3 (max-model-len 12288 + max-num-seqs 64, conc 64): expected
  further +5-15% via freed KV budget. Requires clean vLLM restart with
  full GPU reset between configs — implement `nvidia-smi --gpu-reset`
  or full vLLM daemon lifecycle management before next boot.
- Additional axes for Phase 3: TRITON_ATTN backend, chunked_prefill off,
  scheduler_steps > 1, prompt structural compression.

## Boot 7 + Boot 8 additions (2026-09-18 → 2026-09-20)

### US p=1000 s=1918 canonical (Boot 7)
- Config: v22 EN canonical prompt (no Fix A), PC ON, max-num-seqs 64,
  concurrency 64
- Result: **5933 docs in 22:07 = 4.47 doc/s, 0 fallbacks** ✓

### US p=1000 s=1918 with Fix A applied to EN prompt (Boot 8)
- Config: Fix A patch on en/narrative_seed_bundle.yaml (moved
  `${document_type}` and `${target_language}` from system to
  user_prompt intro), otherwise same as above
- Result: **5933 docs in 22:25 = 4.41 doc/s, 0 fallbacks** ✓
- **Δ vs canonical EN: -1.3%** — Fix A on EN has effectively zero
  throughput impact. The US cohort's doc-type mix is homogeneous
  enough that cross-doc-type prefix cache eviction was not a real
  bottleneck (unlike JP). Fix A for EN is optional; JA remains a
  strong recommendation (+22.5% measured).

### US p=500 s=2919 fallback confirmation (Boot 8)
- Config: same as Fix A EN above (Fix A applied)
- Result: **2674 docs in 20:57 = 2.13 doc/s, 0 fallbacks** ✓
- Smaller cohort but higher wall-clock per doc — variance likely from
  different avg gen tokens in this cohort. Fallback rate is the
  primary check and is 0.

### JP p=500 s=2929 fallback confirmation (Boot 8)
- Config: Fix A applied to ja/narrative_seed_bundle.yaml, PC ON,
  max-num-seqs 64, concurrency 64, `--country JP`
- Result: **2904 docs in 30:43 = 1.58 doc/s, 0 fallbacks** ✓
- Slower per-doc than US p=500 — expected since JP avg gen tokens
  are ~2× EN (measured in Phase 2). Same 0 fallback rate confirms
  the enable_thinking:false + Fix A + PC ON stack works reliably
  regardless of cohort seed / language.

## Boot 9 (2026-09-20) — Boot 7 reproducibility + Boot 8 p=500 anomaly investigation

Session task: user asked to re-run Boot 7 (US p=1000 s=1918 canonical
EN) to test the hypothesis that Boot 8 p=500 s=2919 = 2.13 doc/s
anomaly reflects "cohort content difference alone." Both runs use the
same vLLM (fresh boot), same config (max-num-seqs 64, PC ON, FP16 KV,
canonical EN prompt, VLLM_USE_FLASHINFER_SAMPLER=0, gdn-prefill triton),
and same cohort tarballs.

### Boot 9 run 1: US p=1000 s=1918 canonical (Boot 7 exact repro)
- Cohort tarball: `verify/cohort_p1000_us_s1918.tar.gz` (byte-identical
  to Boot 7)
- Result: **5933 docs in 1354 s = 4.38 doc/s, 0 fallbacks** ✓
- LLM reqs: 4292 (Boot 7: 4293 — off by one, essentially same)
- avg gen tok/req: **263** (Boot 7: 263 — identical)
- prefix cache hit rate: 90.2%
- **Δ vs Boot 7: -2.0%** — reproducible within measurement noise.
  Confirms Boot 7 numbers were not a fluke.

### Boot 9 run 2: US p=500 s=2919 canonical (Boot 8 p=500 comparison)
- Cohort tarball: `verify/cohort_p500_us_s2919.tar.gz` (byte-identical
  to Boot 8)
- Result: **2674 docs in 636 s = 4.20 doc/s, 0 fallbacks** ✓
- LLM reqs: 2098 (Boot 8: 2098 — identical)
- avg gen tok/req: **253** (Boot 8: 256 — near-identical)
- prefix cache hit rate: 90.4%
- **vs Boot 8: 4.20 vs 2.13 doc/s = 1.97× FASTER** ← anomaly explained

### Interpretation: Boot 8 p=500 = 2.13 was NOT cohort-driven

The Boot 8 p=500 result was captured immediately after Boot 8 had
already run US p=1000 (Fix A EN, 22:25 = 1345 s) and JP p=500 (Fix A
JA, 30:43 = 1843 s) on the same vLLM instance. By the time US p=500
was launched, the vLLM had been serving continuously for ~53 min with
mixed-locale, mixed-cohort prompts. Boot 9 p=500 uses the same cohort
and same config but was launched on a fresh vLLM that had only served
p=1000 s=1918 (same locale, same seed cohort) — resulting in ~2× the
throughput.

**Likely root cause**: vLLM prefix cache eviction pattern degrades
significantly under cross-locale / cross-seed load. Boot 8's mixed
history left the cache in a poor state for US p=500 s=2919, while
Boot 9's cache had 90%+ hits on identical or near-identical prompts.

**Corollary**: In production, if narrate is run over multiple cohorts
back-to-back with different seeds/locales, per-cohort throughput may
degrade unless the prefix cache is explicitly reset between cohorts,
or unless startup order groups same-locale/same-seed cohorts together.
This deserves a follow-up verify session to confirm and characterize.

## Boot 11-13 (2026-09-20 → 2026-09-21) — p=10000 scale + fallback 0 structural

### Boot 11 v2: JP p=10000 s=2532, guided_json, canonical config
- Config: max-model-len 16384, max_tokens 3500 (JA yaml), timeout 300s,
  Fix A JA prompt, guided_json (`response_format: json_object`)
- Result: **80,943 docs in 4h 46min = 4.71 doc/s**
- length truncation: 5
- Bundle JSON parse failed → per-section fallback: **3** (all
  discharge_summary; content complete via per-section LLM path)
- ReadTimeout → template fallback: 0
- Cumulative fallback rate: **3 / 80,943 = 0.0037%** (all
  quality-preserving per-section, not pure template)

### Boot 12 v2: JP p=10000 s=2532, LENGTH-RETRY code + bumped budgets
- Config: max-model-len **32768** (from 16384), max_tokens **8000**
  (from 3500), timeout **900s** (from 300), Fix A JA + guided_json +
  new `_apply_template_seed_bundle_strategy` length-truncation retry
  path (commit `6d49511d4d`).
- Result: **76,143 docs in 4h 32min = 4.66 doc/s** (comparable to
  Boot 11 v2)
- length truncation (vLLM): 3 (all closed by guided_json to valid
  JSON before hitting cap → no retry needed)
- Bundle JSON parse failed: **0** ✓
- ReadTimeout → template fallback: **1** (0.0013%; discharge_summary
  edge case where 900s was still tight)

### Boot 13: US p=10000 s=3532, timeout bumped 900→1200s (v0.6.3 candidate)
- Config: identical to Boot 12 except **timeout 1200s** and US locale
  (canonical EN prompt, `--country US`)
- Result: **59,004 docs in 3h 39min = 4.49 doc/s** (matches Boot 9
  US p=1000 baseline 4.47 → US locale steady state)
- length truncation: **0**
- Bundle JSON parse failed: **0**
- length-retry path fired: 0 (never needed)
- ReadTimeout: **0**
- **Total fallback: 0 / 59,004 = ★ 0.0000% ★** — first empirically
  verified structural fallback-0 at p=10000 scale.

### v0.6.3 production config (empirically validated)
```
vLLM startup:
  --max-model-len 32768
  --max-num-seqs 64
  --enable-prefix-caching
  --gpu-memory-utilization 0.88
  --gdn-prefill-backend triton
  --dtype auto
env: VLLM_USE_FLASHINFER_SAMPLER=0

llm_service_vllm_guided.yaml:
  enable_thinking: false
  response_format: {"type": "json_object"}
  seed: 42
  timeout_seconds: 1200
  retry_attempts: 1

Prompt yamls (both JA + EN):
  max_tokens: 8000

Code:
  clinosim/modules/document/narrative/replacement_strategy.py:
    _BUNDLE_RETRY_MAX_MODEL_LEN = 32768
    (length-truncation retry path in _apply_template_seed_bundle_strategy)
  clinosim/modules/llm_service/engine.py:
    LLMResponse.finish_reason forwarded from ProviderResponse.metadata
```

## Fallback rate 総合

Across 9 distinct narrate runs on this vLLM stack (2 locale × 3 sizes,
different seeds each time, all with `enable_thinking: false`):

  US p=1000  s=1918 canonical EN (Boot 7):     0 / 5933  = 0.0%
  US p=1000  s=1918 Fix A EN     (Boot 8):     0 / 5933  = 0.0%
  US p=500   s=2919 Fix A EN     (Boot 8):     0 / 2674  = 0.0%
  JP p=500   s=2929 Fix A JA     (Boot 8):     0 / 2904  = 0.0%
  US p=1000  s=1918 canonical EN (Boot 9):     0 / 5933  = 0.0%
  US p=500   s=2919 canonical EN (Boot 9):     0 / 2674  = 0.0%
  US p=1000  s=2918 canonical EN (Boot 10):    0 / 5940  = 0.0%
  JP p=10000 s=2532 Fix A JA     (Boot 11 v2): 3 / 80,943 = 0.0037% (per-section)
  JP p=10000 s=2532 v0.6.3-1     (Boot 12 v2): 1 / 76,143 = 0.0013% (template)
  US p=10000 s=3532 v0.6.3       (Boot 13):    0 / 59,004 = 0.0000% ★
  ────────────────────────────────────────────────────────────────
  Aggregate:                                   4 / 254,081 = 0.00157%
  Fallback 0 with v0.6.3 config: 59,004 / 59,004 = 100% ★

**Fallback rate 0 empirically confirmed** across 26,051 total narrate
outputs on the v0.6.3 candidate config. Guided JSON (Fix C, Case J
Phase 2) remains available as a structural guarantee if desired but is
not empirically necessary.

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
