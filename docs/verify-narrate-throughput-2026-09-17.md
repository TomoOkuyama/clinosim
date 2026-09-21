# narrate throughput verify report — 2026-09-17

> **Status (updated 2026-09-21, after Boot 13 completion)**:
> Empirical measurements completed across Boot 4-13. The v0.6.3
> production config was validated on **US p=10000 s=3532 (Boot 13,
> 59,004 documents, 0 fallbacks in 3h 39min)**. Read
> `verify/EMPIRICAL_RESULTS.md` for the actual value set and the
> Boot 11-13 audit trail — several concrete recommendations in this
> pre-boot report (specifically the "reduce max_tokens 3500→2500 +
> narrow max-model-len to 12288" thesis in Level-1) were **reversed
> in practice**: the Boot 13 winning config *increased* both
> `max_tokens` (3500→8000) and `max-model-len` (16384→32768). Keep
> this document as the pre-boot rationale, but treat the canonical
> tunings in `verify/EMPIRICAL_RESULTS.md` as authoritative.

**Original status header (2026-09-17)**: pre-boot analysis complete.
**Empirical measurements deferred** — 3 H100 boot attempts (¥2970) all
failed at vLLM engine core initialization due to JIT compilation
environment issues (details in
`verify/failed_run_[1-3]_2026-09-17_hour[1-3]/POSTMORTEM.md`). Report
below is based on pre-boot tokenizer + prompt-structure + KV-sizing
analysis; recommendations are actionable but require confirmation on
H100 once the toolchain environment is stabilized (see companion
`verify/H100_ENV_INVESTIGATION.md`).

## Executive summary

**Regression**: `narrate` throughput dropped from **1.35 doc/s** (pre-v22) to
**0.68 doc/s** (v22 = S117 = v0.6.2) — a ~50% regression that
threatens the economics of the LLM-polished narrative asset (JP p=10000
s=500 = ~20 h H100 billing).

**Root cause hypothesis (pre-boot verified from tokenizer + code walk)**:

The dominant regression driver is a **vLLM startup flag deviation from
its optimal setting**, not the v22 prompt content itself. Pre-boot
analysis showed prompt token deltas (Factor A = 6.1%, Factor B/C = 2.5%)
are far too small to explain a 50% throughput drop. The recovered S117
vLLM startup config confirms:

- `enable_prefix_caching: False` — prefix caching **DISABLED** in
  production S117 run
- `max_num_seqs: 32` — matches `--concurrency 32` in narrate
- `gpu_memory_utilization: 0.88` — 2% below vLLM default

**Recommended quality-neutral fixes** (ranked by expected impact):

1. **Fix C (highest confidence, ships v0.6.3)**: `--enable-prefix-caching`
   ON. Adding this single flag to the vLLM startup command in production
   is expected to recover most of the throughput regression. The v22
   system prompt is ~12k tokens and (per pre-boot analysis) is ~99.3%
   static across doc types; with prefix caching on, all 12k tokens
   should re-use the KV cache after the first request, dropping prefill
   from ~12k tokens/doc to ~500 tokens/doc.

2. **Fix A (highest confidence, ships v0.6.3)**: move `${document_type}`
   and `${target_language}` template variables from `system:` block
   (currently at char 22 and 121 respectively) to `user_prompt`. This
   removes the only two per-doc-type variance points in the system
   block, so prefix caching's hit rate goes from theoretical 0% (across
   doc-type changes) to theoretical 99% (across all doc types within a
   locale). Fix A + Fix C compound — without Fix A, prefix caching
   still only re-uses the first ~11 tokens across doc types.
   Pre-built variant: `verify/v22_prompt_ja_fixA.yaml`.

3. **Fix B (compound with above, ships v0.6.3)**: `--kv-cache-dtype fp8`.
   H100 KV cache theoretical calculation shows at realistic P95 prompt
   (~13k tokens) with default FP16 KV cache, max concurrent seqs
   ≈ 22 — meaning current `--concurrency 32` is queue-bound. FP8 KV
   cache halves per-token KV footprint, doubling capacity to ~45 seqs
   at 13k prompts. Zero measurable quality regression per vLLM 0.6+
   release notes.

4. **Level-1 (ships v0.6.3 or later)**: `max_tokens: 3500 → 2500` in the
   prompt yaml. Actual response lengths are typically 500-1500 tokens
   even for complex ICU discharge summaries. 3500 is over-provisioned
   and forced max-model-len to widen from 12288 → 16384 due to one
   outlier doc (S117 log showed prompt 8789 + max_tokens 3500 = 12289,
   1 token over). Reducing max_tokens allows max-model-len 12288 to
   accommodate current prompts with margin. Pre-built variant:
   `verify/v22_prompt_ja_fixA_maxtok2500.yaml`.

5. **Fix E (fallback 0 target — Phase 2 acceptable)**: vLLM
   `guided_json` / structured output. User-stated priority: JSON parse
   fallback rate should be 0 across all runs; user later added "Phase 2
   でも良いよ" (deferring the guarantee mechanism is acceptable). vLLM
   0.27+ supports `response_format={"type":"json_object"}` which
   triggers xgrammar-based grammar-constrained decoding, guaranteeing
   valid JSON output. Client-side code patch in
   `clinosim/modules/llm_service/providers/vllm.py` (added on this
   branch) forwards the config to vLLM's payload. Yaml variant:
   `verify/llm_service_vllm_guided.yaml`. Expected zero JSON parse
   fallbacks post-adoption. Speed cost: <5% per vLLM benchmarks.

   **v0.6.2 empirical baseline (measured 2026-09-17 from release
   asset)**: 0 unexpected fallbacks across 79,000 docs
   (`clinosim-v0.6.2-jp-p10000-s500-llm-polished-narrative`). 55.5%
   LLM-generated, 44.5% by-design template (triage / care plans /
   assessments — no LLM narrative section). User's hypothesis that
   "large fallback rate might have inflated wall-clock" is falsified —
   the throughput regression is a real per-LLM-doc slowdown, not a
   masking effect.

   Corrected LLM-only doc/s (accounting for 44.5% template
   pass-through): baseline ~2.43 doc/s → v22 ~1.23 doc/s. Same 2×
   slowdown at the actual-LLM level. See
   `verify/FALLBACK_ANALYSIS.md` §v0.6.2 release analysis.

## Non-actionable (documented for completeness)

- Case A' (v22 JA scaffold ported to EN framing): diagnostic tool
  only, not a ship candidate. Cross-references
  `[[feedback_llm_prompt_matches_output_language]]` (S113→S114 rule).
- Content prompt trimming (removing per-doc-type block for unused doc
  types): would save ~5k tokens per request but requires prompt-render
  code change and careful quality re-verify. Defer to follow-up.
- Reverting to v21 prompt: reintroduces the G20 → "glaucoma"
  hallucination that v22 Rule 3 (VERBATIM COPY on ICD-coded conditions)
  fixed. Blocked by quality guardrail in `verify/WORK.md`.

## Measurement design (pending H100 verify)

11-case matrix designed in `verify/WORK.md`, harness in
`verify/run_all_cases.sh` + `verify/run_case.sh`, analysis harness in
`verify/analyze.py`. Once H100 environment is fixed (see companion
investigation doc), the same run should:

- Reproduce Case A_S117 at 0.68 doc/s (baseline recovery validation)
- Isolate Factor E (prefix-caching effect) via Case A_S117 → Case A_pc
- Confirm Fix A prefix-cache uplift via Case F
- Confirm Fix B concurrency uplift via Case G_c64
- Confirm Fix E fallback-0 via Case J

Estimated compute cost for full 11-case verify once env is fixed:
~2 H100 billing hours (¥1980).

## Pre-boot analysis artifacts

Preserved in `verify/`:
- `WORK.md` — case matrix + Factor table + quality guardrails
- `RESEARCH_FINDINGS.md` — R1 (actual prompt tokens) / R2 (prefix cache
  structure) / R3 (narrate call graph) / R4 (KV cache sizing) / R5
  (max_tokens over-provisioning)
- `FALLBACK_ANALYSIS.md` — 4-kind fallback taxonomy + Fix C plan
- `tokens_precount.json` — Qwen tokenizer counts for v22 JA / v22 EN
  scaffold / v21 JA (Factor A/B/C bounds)
- `actual_prompts_precount.json` — rendered prompt token distributions
  on the p=100 cohort
- Prompt yaml variants: `v22_prompt_ja.yaml` / `v22_prompt_en.yaml` /
  `v21_prompt_ja.yaml` / `v22_prompt_ja_fixA.yaml` /
  `v22_prompt_ja_fixA_maxtok2500.yaml`

## Ship recommendation (pending env fix)

If the H100 environment can be stabilized (see
`verify/H100_ENV_INVESTIGATION.md`), a single verify run under
~2 hours (¥1980) should be enough to empirically confirm the priority-
ordered fixes above. Under the pre-boot theoretical model, **Fix C +
Fix A** alone should recover most of the 0.68 → 1.35 doc/s gap, with
zero quality regression. Fix B + Level-1 + Fix E are additive
optimizations.

Cumulative H100 debug cost to date: **¥2970** (3 failed hours) — for
lessons learned in the investigation doc + these fix recommendations.

---

*Investigator: Claude Opus 4.7 via `claude-code` session
`session_01HHkAc5sBQH7Cmo6hEjVtDt` (S117 mid-session).*

*Report generated from `verify/narrate-throughput` branch @ checkpoint
18 (`fd02e83b81`).*
