# narrate throughput verify — <YYYY-MM-DD>

Post-run report template. **Fill in the `<TBD>` placeholders after
running `python verify/analyze.py --out-dir verify/out_<timestamp>`.**

Recommended final location: `docs/verify-narrate-throughput-<YYYY-MM-DD>.md`

---

## Executive summary (3 lines)

<TBD — Fill after analysis. Suggested structure:>

- **Regression**: 1.35 → 0.68 doc/s at v22 (S117). Reproduced at
  `<measured L2 doc/s>` on Case A (v22 JA, max-len 16384, conc 32).
- **Dominant factor**: `<factor with largest absolute delta>` accounts
  for `~<X>%` of the slowdown.
- **Recommendation**: `<top actionable, quality-preserving fix>`.
  Expected recovery: `<Y>%` toward 1.35 doc/s baseline.

## Measurement setup

| | |
|---|---|
| Investigation branch | `verify/narrate-throughput` |
| Prompt versions tested | v22 JA (Case A, baseline), v22 EN scaffold (Case A'), v21 JA (Case E), v22 JA @ 8k max-len (Case D) |
| Cohort | JP p=100 s=917 (`verify/cohort_p100_jp_s917.tar.gz`) |
| Warmup cohort | JP p=10 s=918 |
| Model | `Qwen/Qwen3.8-27B-FP8` (Sakura H100 1×) |
| vLLM flags (16k config) | `--max-model-len 16384 --enable-prefix-caching --gpu-memory-utilization 0.9 --max-num-seqs 256 --dtype auto` |
| vLLM flags (8k config, Case D) | same as above with `--max-model-len 8192` |
| clinosim SHA | `<git rev-parse HEAD from verify/narrate-throughput at run time>` |
| Total H100 wall-clock | `<X> min` (billed `<Y>` hours) |

### Pre-boot tokenizer precount

From `verify/tokens_precount.json` (Qwen3-8B tokenizer):

| Case | version | system tokens | Δ vs v22 JA |
|---|---|---|---|
| v22 JA (current)   | 22 | 11,966 | — |
| v22 EN Case A'     | 22 | 11,239 | -727 (-6.1%) |
| v21 JA (Case E)    | 21 | 11,669 | -297 (-2.5%) |

**Sanity signal**: Factor A/B/C alone cannot linearly explain 50%
throughput drop.

## Factor breakdown (from analyze.py)

<TBD table — analyze.py output copied here>

```
case         L2 wall  L2 doc/s  L1 gen tok/s  avg prompt  avg gen  PC hit  SM util
====================================================================================================
A              <TBD>    <TBD>       <TBD>       <TBD>     <TBD>    <TBD>   <TBD>
A_prime        <TBD>    <TBD>       <TBD>       <TBD>     <TBD>    <TBD>   <TBD>
E              <TBD>    <TBD>       <TBD>       <TBD>     <TBD>    <TBD>   <TBD>
A_c64          <TBD>    <TBD>       <TBD>       <TBD>     <TBD>    <TBD>   <TBD>
A_c128         <TBD>    <TBD>       <TBD>       <TBD>     <TBD>    <TBD>   <TBD>
D              <TBD>    <TBD>       <TBD>       <TBD>     <TBD>    <TBD>   <TBD>
```

### Factor attribution

- **Factor A** (JA vs EN prompt): Case A → A' delta = `<TBD>%`
- **Factor B+C** (v21→v22 content): Case A → E delta = `<TBD>%`
- **Factor D** (max-len 16k → 8k): Case A → D delta = `<TBD>%`
- **Factor E** (concurrency): 32 → 64 → 128 sweep = `<TBD>`

## Prefix cache hit rate analysis

Prefix cache hit rate per case (system prompt is identical within a
case's measurement window, so hit rate should climb to ~100% by end):

| Case | hit rate | hypothesis |
|---|---|---|
| A          | `<TBD>%` | v22 JA prompt, expected high (~90%) if caching healthy |
| A_prime    | `<TBD>%` | different prompt, same order of magnitude |
| E          | `<TBD>%` | v21 JA prompt, same order of magnitude |
| A_c128     | `<TBD>%` | concurrency 128 — check if hit rate drops with parallelism |

Interpretation:
- If hit rate is `<50%` on Case A, the system prompt is being re-prefilled
  more than needed → prompt render order optimization is a candidate
  quality-neutral fix.
- If hit rate `>90%` on Case A but throughput is still low, prefix cache
  is fine and the bottleneck is elsewhere.

## GPU utilization

From nvidia-smi dmon (SM occupancy):

| Case | SM util mean | SM util max | FB max MB | interpretation |
|---|---|---|---|---|
| A   | `<TBD>%` | `<TBD>%` | `<TBD>` | GPU-bound if mean `>80%`, otherwise scheduling / concurrency bound |
| A_c128 | `<TBD>%` | `<TBD>%` | `<TBD>` | if concurrency=128 pushes util up, we know 32 was under-utilized |

## Recommended improvements

**Constraint**: quality-preserving only. See `verify/WORK.md` quality
guardrails section. Rule 3 ICD VERBATIM, JA localization rules,
per-doc-type block structure MUST NOT be removed.

Priority-ordered:

1. **<top rec>** — expected gain `<X>%`, quality risk: none.
   - Rationale: `<TBD>`
   - Implementation: `<TBD>`
2. `<next rec>` — `<TBD>`
3. `<next rec>` — `<TBD>`

## Explicitly NOT recommended (quality regression)

- **Reverting to v21**: reintroduces G20 → "glaucoma" hallucination (S117
  fix #1445). Rule 3 must stay.
- **Removing JA output localization**: makes Delirium → 谵妄 leak,
  drug canonical katakana breaks, Kanji headings degrade. Blocks
  ナラティブ文書としての適切さ requirement.
- **Permanent switch to EN prompt (Case A' → prod)**: `[[feedback_llm_prompt_matches_output_language]]`
  (S113→S114 rule). Case A' is a diagnostic tool only.

## Next steps

1. Implement top recommendation in a fix PR (target v0.6.3 or v0.7.0).
2. Re-run this verify after the fix to confirm the throughput recovery.
3. If total recovery is `<70%` toward 1.35 doc/s, iterate on the next
   recommendation.

## Appendix: raw data

- `verify/out_<timestamp>/case_A/` — raw per-case artifacts
- `verify/out_<timestamp>/analysis.json` — machine-readable summary
- `verify/out_<timestamp>/master.log` — orchestration log
