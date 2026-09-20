#!/usr/bin/env bash
# Boot 12 = max-model-len 32768 (bumped from 16384) + max-num-seqs 64
set -euo pipefail
export VLLM_USE_FLASHINFER_SAMPLER=0
exec vllm serve Qwen/Qwen3.8-27B-FP8 \
    --host 127.0.0.1 \
    --port 8000 \
    --max-model-len 32768 \
    --enable-prefix-caching \
    --gpu-memory-utilization 0.88 \
    --max-num-seqs 64 \
    --dtype auto \
    --gdn-prefill-backend triton \
    --served-model-name Qwen/Qwen3.8-27B-FP8
