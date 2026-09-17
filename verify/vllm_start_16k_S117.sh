#!/usr/bin/env bash
# verify/vllm_start_16k_S117.sh — EXACT S117 baseline replay.
# Recovered from H100 ~/vllm_p100_v5.log + ~/vllm_jp_p10k.log:
#   {model: Qwen/Qwen3.8-27B-FP8, host: 127.0.0.1, max_model_len: 16384,
#    gpu_memory_utilization: 0.88, max_num_seqs: 32,
#    enable_prefix_caching: False, kv_cache_dtype: auto (FP16),
#    dtype: bfloat16, quantization: fp8}
# NO --enable-prefix-caching flag — matches the S117 v0.6.2 production run.

set -euo pipefail
MODEL="${VLLM_MODEL:-Qwen/Qwen3.8-27B-FP8}"

exec vllm serve "$MODEL" \
    --host 127.0.0.1 \
    --port 8000 \
    --max-model-len 16384 \
    --gpu-memory-utilization 0.88 \
    --max-num-seqs 32 \
    --dtype auto \
    --gdn-prefill-backend triton \
    --served-model-name Qwen/Qwen3.8-27B-FP8
