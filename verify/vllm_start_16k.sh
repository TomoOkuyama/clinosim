#!/usr/bin/env bash
# verify/vllm_start_16k.sh — start vLLM with max-model-len 16384.
#
# Matches the S117 production config (from resume-prompt: user widened
# max-model-len from 8192 to 16384 in S117 to handle a 12289-token
# prompt+response overflow).
#
# CRITICAL flag choices (user reviews these):
#   --enable-prefix-caching  : Suspected under-utilized in v22. Explicit
#                              ON to test the "system prompt is not
#                              cached across requests" hypothesis.
#   --gpu-memory-utilization : 0.9 default. Higher values leave less
#                              room for KV cache; H100 has 80 GB HBM,
#                              Qwen3.8-27B-FP8 is ~27 GB, so KV budget
#                              = 0.9*80 - 27 = ~45 GB.
#   --max-num-seqs           : vLLM default is 256. With max-model-len
#                              16384 and ~45 GB KV budget, a single seq
#                              can occupy up to 16384 * 128 * 27 layers
#                              * 2 bytes = ~57 MB, so 256 concurrent
#                              seqs = ~14 GB. Comfortable.
#   --enforce-eager          : DEFAULT off (CUDA graph on). Explicitly
#                              omitted to keep CUDA graph enabled.
#   --dtype auto             : FP8 model → vLLM auto-detects.
#   --gdn-prefill-backend triton : REQUIRED — bypass flashinfer's GDN
#                              prefill JIT compile (needs nvcc, not
#                              installed on this H100). Failed Run 2+3
#                              root cause. Triton backend has similar
#                              perf without JIT.
#
# --- USER REVIEW POINTS ---
#   1. Should `--enable-prefix-caching` be on? (Recommend: YES for measurement)
#   2. `--gpu-memory-utilization 0.9` sufficient? (Recommend: YES; the
#       H100 has plenty of headroom for max-model-len 16384)
#   3. `--max-num-seqs 256` OK, or should we cap lower to avoid confounding
#       the concurrency sweep?

set -euo pipefail

MODEL="${VLLM_MODEL:-Qwen/Qwen3.8-27B-FP8}"

exec vllm serve "$MODEL" \
    --host 127.0.0.1 \
    --port 8000 \
    --max-model-len 16384 \
    --enable-prefix-caching \
    --gpu-memory-utilization 0.88 \
    --max-num-seqs 32 \
    --dtype auto \
    --gdn-prefill-backend triton \
    --served-model-name Qwen/Qwen3.8-27B-FP8
