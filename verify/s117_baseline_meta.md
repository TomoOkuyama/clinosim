# S117 baseline measurement metadata (0.68 / 1.35 doc/s)

**目的**: 事前解析と実測の対比 baseline を明示。

## 復元可能な事実 (from `.resume-prompt.md`)

### v22 (0.68 doc/s) 測定条件

| Field | Value | Source |
|---|---|---|
| Prompt version | v22 (with Rule 3 ICD VERBATIM) | `.resume-prompt.md` line 26 |
| Model | `Qwen/Qwen3.8-27B-FP8` | line 24 |
| vLLM `--max-model-len` | 16384 (widened from 12288 pre-existing) | line 24 |
| Cohort (iter 1) | JP p=100 s=400 (later US too? both audited) | line 24, 55 |
| Cohort (iter 2) | p=100 s=400 re-narrate + p=100 s=401 second run | line 56 |
| Cohort (iter 3, non-baseline) | JP p=10000 s=500 (LLM-polished release asset) | line 57 |
| Concurrency | 32 (implied — line 65 references "memory reference reported near-zero gain past 32") | line 65 |
| Wall-clock (iter 1) | ~55 min for narrate + verify combined | line 55 |
| Wall-clock (iter 2) | 56 min for 2× p=100 narrate | line 56 |

**Derived doc/s**: `.resume-prompt.md` line 62 quotes "0.68 doc/s at v22"
without showing the arithmetic. Reverse-checking:
- Iter 2 = ~2 × p=100 narrate = 200 docs in 56 min = ~ 0.06 doc/s
- That doesn't match 0.68 → the 55-56 min includes verify audit steps
  (content audit for G20/H40 etc.), not just narrate.
- Actual narrate-only time may have been shorter; 0.68 doc/s figure is
  likely from log output rather than wall-clock division.

### v-something-pre-22 (1.35 doc/s) baseline

| Field | Value | Source |
|---|---|---|
| Prompt version | pre-v22 (unclear exact version) | inferred |
| Wall-clock | not documented | — |
| Cohort | not documented | — |
| Concurrency | 32 (implied) | line 65 says "memory reference" reported this |

`.resume-prompt.md` line 65 says "memory reference reported near-zero
gain past 32, but that was pre-v22". So 1.35 doc/s came from an earlier
session's measurement — the memory reference itself is presumably in
one of the memory files under
`~/.claude/projects/-Users-tokuyama-workspace-clinosim/memory/` but I
did not chase this down in this session.

## Gaps (not recoverable in this session)

- **When exactly was 1.35 doc/s measured?** Not in `.resume-prompt.md`
  and not in `docs/history/session-prompts/` (stops at S78).
- **What prompt version generated 1.35 doc/s?** Likely v21 or v20 given
  the sessions before S117 (S114-S116 saw v18→v21).
- **Was the 1.35 measurement at max-model-len 12288 (pre-widening) or
  16384?** S117 widened it to 16384 mid-session (line 24). The 1.35
  baseline might therefore have been at 12288.

## Implication for our verify plan

Our Case E (v21 JA prompt, max-len 16384) is the closest apples-to-
apples comparison to reconstruct "1.35 doc/s at pre-v22". If Case E
recovers ~1.35 doc/s, the regression is fully explained by v21→v22
(Factor B + C). If Case E is still slow (near 0.68), then max-model-len
16384 (Factor D) is dominant regardless of prompt content.

**Post-run**: also test max-model-len 12288 explicitly if Case E is
still slow — mimicking the pre-widening config.

## Action for post-run report

1. Include the S117 iter-1 and iter-2 wall-clock in the report so future
   readers understand the baseline framing.
2. If our Case A reproduces ~0.68 doc/s on a fresh cohort s=917, that
   validates the reproducibility of the regression across seeds.
3. If our Case A shows something significantly different (e.g. 0.4 or
   0.9 doc/s), that's itself a finding — the regression is cohort-
   dependent, which would point at prompt+response size distribution
   rather than pure vLLM configuration.
