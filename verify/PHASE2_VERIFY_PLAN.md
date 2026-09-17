# Phase 2 verify plan — multi-angle speedup with quality preservation

Base for comparison: **Case F = 3.448 doc/s** (v22 JA + Fix A + PC ON +
FP16 KV + max-num-seqs 32 + conc 32 + enable_thinking: false)

**Quality guardrails (must not regress)**:
- Rule 3 VERBATIM COPY (ICD label preservation) — measured via LLM output
  containing full ICD-10-CM labels for G20/E11/M17/F32 samples
- JA output localization (Delirium→せん妄、drug canonical katakana etc.)
- Per-doc-type block structure (each doc type has its expected sections)
- Fallback rate 0
- Response truncation rate 0 (avg gen tokens < 80% of max_tokens cap)

## 5 検討軸

### Axis 1: Cache hit rate 向上

**現状仮説** (Case F vs A_pc breakdown):
- Fix A で char 22 の `${document_type}` を user_prompt に移し、system prompt 全 11,989 tokens を prefix-cache 対象にした
- +22.5% throughput = 実測。ただし cache hit rate 実測値は未取得
- **計測: `/v1/metrics` の `vllm:prefix_cache_hits_total` / `_queries_total` 比を全 case で取得**

**未検証の cache 改善 lever**:
- **Static block ordering**: user_prompt 内の `document_type` / `target_language` header を可変後半に、context_json_block を末尾に。→ 同 doc_type 系列で user prompt 前半も cache 可能
- **Warmup narrate**: 実 measurement 前に 10-doc warmup で cache populate。既存 harness にある
- **Cross-cohort warm cache**: fresh cohort でも previous cohort の cache が hit ≠ true。cache is patient-independent 部分 (system prompt) が dominant なのでOK

**Case R1 (cache-optimized prompt structure)**: `verify/v22_prompt_ja_fixA_reorder.yaml`
- system prompt = Fix A と同一 static content
- user_prompt = 静的 header 除去、可変 context を先頭、instrument 用 `Document type / Output language` を末尾に
- Cache theoretical: user prompt 前半 (~200 tokens) が同 doc_type 内で cache 可能に

### Axis 2: Token size 調整

**Prompt-side**:
- system 11,989 tokens (Fix A base) → ~15% は "使わない per-doc-type block" (Phase 3 selective化前)
- **Case R2 (max_tokens 2500、prompt Fix A)**: response truncation 発生率チェック + throughput
- **Case R3 (max_tokens 2000)**: 更 aggressive、truncation risk 増、throughput 上限探し

**Prompt semantic compression (要 draft)**:
- v22 Rule 3 の JA hallucination 例 (G20/E11/M17/F32 各 4 行 × ~50 chars = 200 chars) を圧縮
- Rule 5 の localization table を最小限に
- 予想効果: system prompt -5-10% → prefill -5-10%
- Case R4: prompt shrinkage variant (要 pre-boot 準備)

### Axis 3: 多重度 (concurrency + max-num-seqs) 調整

**現状事実**:
- max-num-seqs 32 で client conc 32/128 の差 +1.4% only → **max-num-seqs が bottleneck**
- FP8 KV は逆効果 (Case G 2.275、F 3.448) → FP16 KV keeper
- FP16 KV @ realistic ~13k prompt = 理論 max ~22 seqs

**未検証**:
- **Case P1 (max-num-seqs 64、FP16 KV)**: KV budget 超過なら vLLM が queue、実効 seq 数を server metrics で確認
- **Case P2 (max-num-seqs 128)**: 明示的に KV 不足に、graceful degradation 確認
- **Case P3 (max-num-seqs 64 + max-model-len 12288)**: per-seq KV 縮小 → 実効 seq 数増可能
- **Case P4 (max-num-seqs 128 + max-model-len 10240 + max_tokens 2000)**: 更 aggressive

### Axis 4: vLLM 起動 flag 未検証 levers

- `--num-scheduler-steps`: batch scheduling granularity (default 1)。>1 で latency↑ throughput↑
- `--enable-chunked-prefill` (default True): chunked prefill toggle
- `--attention-backend`: FLASH_ATTN (現) / FLASHINFER / TRITON_ATTN / FLEX_ATTENTION
  - S117 flashinfer 系は JIT compile 失敗、避けたい。TRITON_ATTN は候補
- `--speculative-config`: 投機的デコード (小型 draft model 必要、S117 単一 model 前提外れる)

**Case S1 (scheduler_steps=4)**: batch grouping で throughput 期待
**Case S2 (chunked_prefill=false)**: 現 default 逆
**Case S3 (attention_backend=TRITON_ATTN)**: JIT 不要の attention backend

### Axis 5: Fallback 0 保証機構 (quality-neutral)

- **Case J (guided_json)**: `response_format={"type":"json_object"}` — xgrammar constraint。Fix A 前提、実測 speed cost 未知
- 期待: 3.448 → 3.28 doc/s (5% cost) 程度に留まり、fallback 0 structural guarantee

## Verify matrix (Phase 2 boot)

11 cases、5 vLLM startup configs、~1 hour billing (¥990) 内に完走目標:

| # | Case | max_seqs | max_len | max_tok | Attn | Sched | Chunk | Guided | Prompt | vLLM cfg |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | F_repro | 32 | 16384 | 3500 | FLASH_ATTN | 1 | on | no | Fix A | #A |
| 2 | J | 32 | 16384 | 3500 | FLASH_ATTN | 1 | on | **yes** | Fix A | #A |
| 3 | R2 | 32 | 16384 | 2500 | FLASH_ATTN | 1 | on | no | Fix A | #A |
| 4 | R1 | 32 | 16384 | 3500 | FLASH_ATTN | 1 | on | no | Fix A reorder | #A |
| 5 | P1 | 64 | 16384 | 3500 | FLASH_ATTN | 1 | on | no | Fix A | #B |
| 6 | P2 | 128 | 16384 | 3500 | FLASH_ATTN | 1 | on | no | Fix A | #C |
| 7 | P3 | 64 | 12288 | 2500 | FLASH_ATTN | 1 | on | no | Fix A | #D |
| 8 | P4 | 128 | 10240 | 2000 | FLASH_ATTN | 1 | on | no | Fix A | #E |
| 9 | S1 | 32 | 16384 | 3500 | FLASH_ATTN | **4** | on | no | Fix A | #F |
| 10 | S2 | 32 | 16384 | 3500 | FLASH_ATTN | 1 | **off** | no | Fix A | #G |
| 11 | S3 | 32 | 16384 | 3500 | **TRITON_ATTN** | 1 | on | no | Fix A | #H |

**vLLM restart × 8 = 40 min、cases × 11 × 2 min = 22 min + startup 8 min + shutdown 2 min = 72 min** — hour 5 越境。

**scope 削減案** (推奨、hour 5 内完走):
- Cases 1, 2, 3, 5, 7 (5 cases、5 vLLM restart) = ~45 min
- Drop 4, 6, 8, 9, 10, 11 (次 phase 3 で)

## Quality preservation checks per case

各 case narrate 完了後、以下 metric を集約:

1. **fallback_count**: `grep -c "JSON parse failed" <log>` = 0 必須
2. **truncation_rate**: `L1_avg_gen_tokens_per_req / max_tokens` — > 0.8 なら warning
3. **prefix cache hit rate**: `/v1/metrics` の hits/queries 比 (Fix A で >90% 期待)
4. **doc_type coverage sanity**: すべての doc_type がある割合の narrative 生成できているか
5. **sample content diff**: 3 doc 選んで Case F baseline と semantic 一致確認 (per-doc-type expected sections が揃っているか)

## Cost 見積り

- Phase 2 verify: 1 hour billing (¥990) if scope-reduced
- Grand total this session: **¥4950 (5 hour) + ¥990 = ¥5940**

Alternative: Phase 2 を **2 sessions に分割**して 1 hour × 2 = ¥1980、
scope 拡張可能。

## User 判断項目

1. Phase 2 verify を booting するか (今か / 次 session か)
2. Case matrix scope: 削減 (5 cases、1 hour) or 全 (11 cases、~2 hour)
3. Phase 3 (prompt selective + adaptive max_tokens) の code 変更は verify 完了後別 iteration とするか
