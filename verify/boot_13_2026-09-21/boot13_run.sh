#!/usr/bin/env bash
# Boot 13 = US p=10000 s=3532, fresh vLLM, max-model-len 32768, max_tokens 8000, timeout 1200s, guided_json
set -euo pipefail
source ~/vllm-env/bin/activate
cd ~/clinosim && export PYTHONPATH=.

CIF_DIR=/home/ubuntu/boot13_us_p10000_s3532/cif
LLM_CONFIG=/home/ubuntu/verify/llm_service_vllm_guided.yaml
OUT_LOG=~/boot13_narrate.log

curl -s http://127.0.0.1:8000/metrics > ~/boot13_metrics_before.txt

START_TS=$(date +%s)
echo "boot13_start_epoch=$START_TS" | tee -a $OUT_LOG

time clinosim narrate \
    --cif-dir "$CIF_DIR" \
    --provider vllm \
    --llm-config "$LLM_CONFIG" \
    --country US \
    --concurrency 64 \
    --version-id boot13_us_p10000_s3532_guided 2>&1 | tee -a $OUT_LOG

END_TS=$(date +%s)
echo "boot13_end_epoch=$END_TS" | tee -a $OUT_LOG
echo "boot13_elapsed_seconds=$(( END_TS - START_TS ))" | tee -a $OUT_LOG

curl -s http://127.0.0.1:8000/metrics > ~/boot13_metrics_after.txt
