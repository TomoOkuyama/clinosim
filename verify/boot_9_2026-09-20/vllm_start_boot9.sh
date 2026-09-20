#!/usr/bin/env bash
# Boot 9 = Boot 7 exact repro. max-num-seqs 64, PC ON, FP16 KV.
set -euo pipefail
export VLLM_USE_FLASHINFER_SAMPLER=0
exec vllm serve Qwen/Qwen3.8-27B-FP8 \
    --host 127.0.0.1 \
    --port 8000 \
    --max-model-len 16384 \
    --enable-prefix-caching \
    --gpu-memory-utilization 0.88 \
    --max-num-seqs 64 \
    --dtype auto \
    --gdn-prefill-backend triton \
    --served-model-name Qwen/Qwen3.8-27B-FP8
