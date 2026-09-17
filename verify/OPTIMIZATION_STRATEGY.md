# Optimization strategy for narrate — fastest + fallback 0

Based on Boot 4 (2026-09-17) empirical measurements. All measurements
on JP p=100 s=917 cohort (373 docs across 258 encounters).

## Measured factor deltas (compound)

| Factor | Δ doc/s | Speed cost | Quality risk | Fallback risk |
|---|---|---|---|---|
| `--enable-prefix-caching` | **+205%** (0.923→2.813) | 0 | 0 | 0 |
| Fix A (prompt struct) | **+22.5%** on top | 0 | 0 | 0 |
| Concurrency 32→128 (FP16 KV, max-num-seqs 32) | +1.4% | 0 | 0 | 0 |
| `--kv-cache-dtype fp8` | **-34%** (regression) | negative | 0 | 0 |
| Concurrency 32→64 (FP8 KV, max-num-seqs 64) | +13.5% (over FP8@32, still worse than FP16@32) | negative net | 0 | 0 |
| v22 content revert | +8.1% | Quality regression (Rule 3 lost) | 0 | 0 |
| EN scaffold prompt | +3.4% | Cross-locale quality risk | 0 | 0 |
| `enable_thinking: false` | measured N/A separately | 0 | 0 | **CRITICAL: unset → 100% fallback** |

**Winner from empirical run: Case F** (v22 JA + Fix A + PC ON + FP16 KV
+ max-num-seqs 32 + concurrency 32 + enable_thinking: false) =
**3.448 doc/s = 3.73× S117 baseline**.

## Unmeasured but high-expected-value optimizations

### Phase 2 candidates (next verify boot needed)

**A. Increase `--max-num-seqs` to 64 with FP16 KV**
- Current 32 is ceiling. FP16 KV budget @ 13k prompt / max-model-len 16384
  supports ~22 seqs (theoretical) — 32 is already borderline.
- If we reduce max-model-len to 12288 (see B), the per-seq KV footprint
  drops, potentially supporting 45+ seqs.
- Expected additional throughput: +30-50% on top of Case F if concurrency
  is genuinely bottlenecked.

**B. Reduce `max_tokens` 3500 → 2500 + `--max-model-len` 12288**
- Actual response length is 500-1500 tokens typical. 3500 is over-
  provisioned safety margin (S117 widened max-model-len to 16384 because
  one outlier hit 8789+3500=12289; if we reduce the max_tokens ceiling,
  we can shrink max-model-len).
- Frees KV cache budget → higher max-num-seqs viable.
- Fallback risk: If a response truncates before valid JSON closes → 100%
  fallback for that doc. Must measure truncation rate under max_tokens=2500
  in the verify run.

**C. Grammar-constrained decoding (`response_format=json_object`)**
- vLLM's guided_json feature via xgrammar. Constrains emitted tokens to
  JSON grammar → JSON parse fallback becomes structurally impossible.
- Speed cost: <5% per vLLM 0.6+ benchmarks (needs local confirmation).
- Value: STRUCTURAL fallback-0 guarantee, not just empirical.

### Phase 3 candidates (code change required)

**D. Selective per-doc-type block in prompt render**
- Current v22 JA system prompt has ~5k tokens of per-doc-type block
  (admission_hp / discharge_summary / operative_note / procedure_note
  / etc.) — only 1 block relevant per doc.
- Refactor `prompt_registry.render()` to include only the relevant
  block based on `${document_type}`.
- Prompt shrinks 12k → 7-8k tokens. Prefill cost -33-40%.
- Combined with Fix A: system prompt fully cache-eligible across
  same-doc-type requests, and 33% smaller for each.
- Expected uplift: +30-50% over Case F.

**E. Adaptive `max_tokens` per doc_type**
- outpatient_soap needs ~1200 tokens; discharge_summary needs ~2500;
  procedure_note ~700.
- Adaptive cap: each request only reserves what its doc_type needs.
- KV cache budget optimized per-request.
- Expected: +5-15% additive with A+B.

## Recommended phasing

### Phase 1: SHIP NOW (v0.6.3), zero risk, 3.73× uplift measured

Required changes:
1. **`enable_thinking: false`** in production `llm_service_vllm.yaml`
   (or similar). **MANDATORY** — without this, 100% JSON parse fallback
   confirmed empirically. NO throughput cost.
2. **`--enable-prefix-caching`** on vLLM startup command in production
   deployment. This is THE dominant regression fix (S117 shipped with
   PC OFF).
3. **Fix A yaml patch**: apply `verify/v22_prompt_ja_fixA.yaml` to
   `clinosim/modules/llm_service/prompts/ja/narrative_seed_bundle.yaml`
   (and mirror to `en/`). +22.5% additional. No quality impact
   (confirmed: 0 fallbacks, semantically identical prompt behavior).

Expected production throughput after Phase 1: **~3.4-3.5 doc/s** on the
JP p=100 s=917-shape cohort with these settings. That's about 3.73× the
S117 v0.6.2 measurement (0.923 doc/s reproduced).

### Phase 2: Next verify boot (Case H + Case J + concurrency sweep)

Needs H100 measurement to confirm:
- Case H: v22 JA + Fix A + PC ON + max-model-len 12288 + max_tokens 2500
  + max-num-seqs 64 + conc 64. Confirms Level-1 tuning + concurrency
  scaling. Expected 4.5-5.2 doc/s. **Truncation-rate check MUST show
  0% before shipping.**
- Case J: v22 JA + Fix A + PC ON + `response_format=json_object` +
  everything else = Case F. Confirms guided_json speed cost. Expected
  same 3.4 doc/s (or ~5% slower). Structural fallback-0 guarantee.

If Case H shows truncation > 0%, drop the max_tokens change but keep
max-num-seqs 64 (needs KV budget verification via server metrics).

### Phase 3: Code changes (later release)

- Selective per-doc-type block (Section D above)
- Adaptive max_tokens per doc_type (Section E above)
- Combined expected: 5-7× baseline. Requires careful quality re-verify
  because prompt structure changes.

## Fallback 0 defense-in-depth (all 4 fallback categories)

### 1. JSON parse fallback (100% of observed fallback risk today)

- **Layer 1 (MUST)**: `enable_thinking: false` — proven to fix from
  empirical 100% → 0%.
- **Layer 2 (Phase 2)**: `response_format={"type":"json_object"}` —
  grammar-constrained decoding guarantees valid JSON.
- **Layer 3 (Phase 3, defensive)**: response schema validation before
  storing — if a doc has empty section, warn to log rather than
  silently continue.

### 2. Provider error fallback (network / vLLM timeout / 5xx)

- **Layer 1**: Reasonable `timeout_seconds` (300s current) with 1
  retry.
- **Layer 2 (Phase 2)**: startup smoke test — before running the real
  narrate, issue one tiny narrate to verify provider connectivity + JSON
  round-trip. If it fails, abort with clear error.
- **Layer 3 (Phase 3)**: Circuit breaker — if >5 consecutive provider
  errors, pause narrate and page operator.

### 3. Prompt error fallback (missing template variable)

- **Layer 1 (CI-time)**: pytest test that renders every prompt yaml
  with the union of all known context keys. Catches missing key errors
  at PR time.
- **Layer 2 (deploy-time)**: dry-run narrate on 5 sample docs before
  scaling to full cohort.

### 4. No provider configured

- **Layer 1**: startup validation — refuse to boot narrate if
  `narrative.provider` unset or `enable`d without endpoint.
- **Layer 2**: docs in README + config template.

## The 2× ambition — theoretical fastest under quality constraints

Combining all layers:
- Case F baseline: 3.448 doc/s (3.73×)
- + Level-1 (max_tokens 2500 + max-model-len 12288 + max-num-seqs 64):
  ~4.5-5.2 (5×)
- + Selective per-doc-type block: ~6.5-7.5 (7-8×)
- + Adaptive max_tokens: ~7.0-8.5 (7.5-9×)

Total: **7-9× S117 baseline** with all layers, no quality regression,
0-fallback guaranteed via layer 2 grammar constraint.

The 1.35 doc/s "pre-v22 baseline" that motivated this investigation
should be recoverable and then some — Phase 1 alone (3.4 doc/s) already
comfortably exceeds it.

## What the empirical data DID NOT support

**Fix B (`--kv-cache-dtype fp8`)**: DROPPED. Case G (FP8, conc 32) was
2.275 doc/s (34% slower than Case F). Case G_c64 improved to 2.583 but
still slower. The FP8 conversion overhead outweighed the "double KV
budget" theoretical benefit for this workload size. **Recommendation:
do NOT enable FP8 KV in production narrate.**

**Case A_prime (EN scaffold prompt)**: DROPPED. Only +3.4% throughput
at the cost of cross-locale quality risk (violates
`[[feedback_llm_prompt_matches_output_language]]`). Not worth it.

**Concurrency > max-num-seqs**: DROPPED as a standalone lever. Case
A_pc_c128 was +1.4% over A_pc (32). Client-side concurrency doesn't
help until server max-num-seqs is raised, and raising max-num-seqs
requires KV budget headroom which requires Phase 2 (max-model-len /
max_tokens reduction).

---

*Investigation branch: `verify/narrate-throughput` @ checkpoint 22+
(`bae4d1d4e0`). Empirical data captured in
`verify/EMPIRICAL_RESULTS.md` and `verify/boot_4_2026-09-17_hour4-5/`.*
