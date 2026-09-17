#!/usr/bin/env bash
# verify/vllm_start_16k_fp8kv.sh — vLLM with max-model-len 16384 AND
# --kv-cache-dtype fp8, testing the KV cache size reduction optimization.
#
# R4 analysis showed: on H100 80GB with FP16 KV cache and P95 prompt
# ~13k tokens, max concurrent seqs ≈ 22. Setting KV cache to FP8 halves
# per-token KV footprint and lets us serve ~44 concurrent seqs.
# Quality-neutral: FP8 KV is a tested vLLM feature with negligible
# perplexity impact (per vLLM 0.6+ release notes).

set -euo pipefail

MODEL="${VLLM_MODEL:-Qwen/Qwen3.8-27B-FP8}"

exec vllm serve "$MODEL" \
    --host 127.0.0.1 \
    --port 8000 \
    --max-model-len 16384 \
    --enable-prefix-caching \
    --gpu-memory-utilization 0.88 \
    --max-num-seqs 64 \
    --dtype auto \
    --kv-cache-dtype fp8 \
    --served-model-name Qwen/Qwen3.8-27B-FP8
