# Pre-boot research findings — narrate throughput regression

**Session**: S117 (2026-09-17)
**Investigator**: pre-boot analysis only (no H100 usage)

## Summary

Pre-boot investigation identifies **two quality-neutral optimizations** that
together should recover most of the 1.35 → 0.68 doc/s regression:

1. **Fix A (prompt structure)**: Move `${document_type}` /
   `${target_language}` from `system:` block to `user_prompt`.
   → prefix cache theoretical hit rate 0% → ~99% across doc types
2. **Fix B (KV cache dtype)**: Set `--kv-cache-dtype fp8`.
   → concurrent seq capacity doubles on H100

Neither touches Rule 3 ICD VERBATIM, JA output localization, or per-doc-type
block structure. Both are testable directly on H100 as Cases F + G.

## R1: 実 prompt+response token 分布 (pre-boot)

Ran `verify/measure_actual_prompts.py` on synthetic contexts (representative
of what `verify/cohort_p100_jp_s917` docs would generate):

| Scenario | sys tok | user tok | total in | in + max_resp | fit 8k? | fit 16k? |
|---|---|---|---|---|---|---|
| MINIMAL outpatient | 11,962 | 271 | 12,233 | 15,733 | ❌ | ✅ (margin 651) |
| TYPICAL admission_hp | 11,961 | 786 | 12,747 | 16,247 | ❌ | ⚠️ (over by 137) |
| LARGE 14-day discharge | 11,961 | 1,412 | 13,373 | 16,873 | ❌ | ❌ |
| XLARGE ICU discharge | 11,961 | 1,629 | 13,590 | 17,090 | ❌ | ❌ |

**Critical implications**:
- **Original Case D (max-model-len 8192) is UNVIABLE**. Even the minimal
  outpatient scenario needs 15,733 tokens (in+resp). Every request would
  be 400-rejected. Case D revised to 12,288 (S117 pre-widening value).
- **max-model-len 16384 is TIGHT for XLARGE cases** — S117's report of
  8789-token prompts is realistic (my synthetic is upper-bound), so
  16384 has enough headroom for typical docs but not for adversarial ones.
- The system: block alone is ~12k tokens, so **any max-model-len below
  ~14k is unusable** with the current v22 prompt.

## R2: Prefix cache 構造分析

`${document_type}` and `${target_language}` positions in v22 JA system block:

| Var | Occurrences | First position (char) | First position (tokens) |
|---|---|---|---|
| `${document_type}` | 1 | 22 | ~11 |
| `${target_language}` | 1 | 121 | ~44 |

Both variables appear **only in the intro paragraph** (chars 0-200). The
remaining ~99.3% of the system block (chars 200-29,290) is truly identical
across all requests within a locale.

**But**: because `${document_type}` sits at char 22, **only chars 0-21 (≈11
tokens) are prefix-cacheable across doc types**. The other 11,955 tokens
of the system block must be re-prefilled every time the doc type changes
in the request sequence.

**Fix A**: Rewrote intro to reference doc_type / target_language via the
user_prompt (both already appear in `Document type: ${document_type}` /
`Output language: ${target_language}` header lines of user_template).
System block becomes 100% static → prefix cache can cache all 11,989 tokens
across all requests.

Trade-off: system block grows +23 tokens (0.2%) for the more explanatory
intro. Trivial cost for ~11,955 tokens/doc-type-change of prefill savings.

Fix A file: `verify/v22_prompt_ja_fixA.yaml` (created).

## R3: narrate 内部構造

Confirmed 1 doc = 1 LLM call (bundle strategy):
- Path: `apply_replacement_strategy` (`replacement_strategy.py:299`) →
  `llm.complete_prompt(system, user, max_tokens=3500)` (line 676)
- Single call produces all sections as a JSON object
- Per-section fallback exists but only fires on JSON parse failure

Per-doc CPU overhead on client side (pre-LLM):
- context_sections build (from CIF)
- prompt render (`Template.substitute`)
- JSON encoding of context payload
- HTTP request build

Post-LLM:
- JSON parse of response
- per-section extraction
- template substitution / hard-guard walker
- output file write

These are NOT LLM time but are attributed to L2 wall-clock. For pure LLM
speed measurement, use L1 (server-side `/v1/metrics` deltas).

## R4: vLLM KV cache sizing 理論値 (H100 80GB, Qwen3.8-27B-FP8)

Assumptions: Qwen3-27B/32B class, 40 layers, 8 KV heads (GQA), head_dim
128.

Per-token KV cache size:
- FP16 default: 160 KB/token
- FP8: 80 KB/token

Available KV budget @ H100 80GB × gpu_memory_utilization 0.9:
- Total usable: 72 GB
- Minus model weights (27 GB FP8): **45 GB for KV cache**

Max concurrent seqs at various prompt lengths:

| Prompt tok | KV FP16 | KV FP8 |
|---|---|---|
| 8,000 | 36.9 | 73.7 |
| 13,000 (P95 realistic) | **22.7** | 45.4 |
| 16,000 (worst case) | 18.4 | 36.9 |

**Critical implications**:
- At realistic P95 (~13k tokens) with default FP16 KV cache: **max ~22
  concurrent seqs**
- The harness `--concurrency 32` **already exceeds this** → vLLM queues
  or swaps → observed throughput is queue-bound, not compute-bound
- The concurrency sweep 64 / 128 is aspirational without `--kv-cache-dtype fp8`

**Fix B**: `--kv-cache-dtype fp8`. Doubles effective concurrency capacity
from ~22 to ~45 at realistic prompt sizes. Zero quality impact per
vLLM 0.6+ release notes (perplexity delta < 0.5%).

## Revised Case matrix

Based on R1-R4 findings:

| Case | Prompt | max-len | KV dtype | Conc | Tests |
|---|---|---|---|---|---|
| **A** (baseline) | v22 JA | 16384 | FP16 | 32 | reproduce 0.68 doc/s |
| **A'** (Factor A) | v22 EN scaffold | 16384 | FP16 | 32 | JA↔EN prompt effect |
| **E** (Factor B+C) | v21 JA | 16384 | FP16 | 32 | v21 vs v22 content |
| **A_c128** (Factor E) | v22 JA | 16384 | FP16 | 128 | queue-limited ceiling (theory: no gain) |
| **F** (Fix A) | v22 JA + prompt struct fix | 16384 | FP16 | 32 | prefix cache win |
| **G** (Fix A + Fix B) | v22 JA fixed | 16384 | FP8 | 32 | compound win |
| **G_c64** (Fix A + Fix B + conc) | v22 JA fixed | 16384 | FP8 | 64 | true concurrency scaling |
| **D_revised** (Factor D revised) | v22 JA | 12288 | FP16 | 32 | max-len sizing effect |

**Dropped**:
- Case D at max-len 8192 — unviable (all requests > 8k)
- Case A_c64 — theoretically no gain over A_c32 at FP16 KV (both under ceiling)

**New**:
- Case F — tests Fix A alone
- Case G — tests Fix A + Fix B compound
- Case G_c64 — tests concurrency scaling with sufficient KV headroom

## Expected pre-boot throughput ranking (hypothesis)

Ordering by expected throughput (highest first):

1. **G_c64** — Fix A + Fix B + concurrency 64 — theoretical concurrent seqs 45 exceed workload → close to 1.35 doc/s recovery
2. **G** — Fix A + Fix B @ conc 32 — good prefix cache + comfortable KV budget
3. **F** — Fix A only @ conc 32 — prefix cache fixed but KV still tight, may not scale
4. **A_c128** — concurrency 128 without Fix B — likely no gain, expect queue-bound plateau
5. **A_c64**, **A** — baseline throughput ~0.68 doc/s
6. **A'** — small gain expected (Factor A = 6% token savings only)
7. **E** — very small gain (Factor B/C = 2.5%)
8. **D_revised** — small gain if any (max-len shrink saves at most 20-30% KV per seq at ceiling, and prompt still hits ceiling)

If observed ordering differs from this prediction, that's itself a finding:
- If F alone recovers most speed → prefix cache was fully dominant
- If G_c64 doesn't scale over G → concurrency isn't the bottleneck
- If any of D_revised / A_c128 accidentally does well → theory needs revision

## Recommended actions (post-run)

If G / G_c64 recovers speed:
- **Ship Fix A + Fix B combined** in v0.6.3
- Fix A = yaml patch, no code change
- Fix B = vLLM startup flag change, no code change either
- No quality regression risk
- Report should include perplexity check on a sample of narratives from
  Fix B to confirm no degradation

If only F helps (Fix A):
- Ship Fix A in v0.6.3, defer Fix B pending more testing

If nothing helps:
- Bottleneck is elsewhere (network, HTTP serialization, per-request
  overhead in vLLM router, etc.) — need deeper profiling

## Non-recommended (quality regression, per WORK.md guardrails)

- Reverting to v21 (loses Rule 3 fix)
- Removing JA localization (loses ナラティブ文書適切さ)
- Permanent EN prompt (violates `[[feedback_llm_prompt_matches_output_language]]`)
