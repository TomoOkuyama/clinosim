#!/usr/bin/env bash
# Boot 12 = JP p=10000 s=3532 with V12 retry code + max-model-len 32768 + max_tokens 8000 + guided_json
set -euo pipefail
source ~/vllm-env/bin/activate
cd ~/clinosim && export PYTHONPATH=.

CIF_DIR=/home/ubuntu/boot12_jp_p10000_s3532/cif
LLM_CONFIG=/home/ubuntu/verify/llm_service_vllm_guided.yaml
OUT_LOG=~/boot12_narrate.log

curl -s http://127.0.0.1:8000/metrics > ~/boot12_metrics_before.txt

START_TS=$(date +%s)
echo "boot12_start_epoch=$START_TS" | tee -a $OUT_LOG

time clinosim narrate \
    --cif-dir "$CIF_DIR" \
    --provider vllm \
    --llm-config "$LLM_CONFIG" \
    --country JP \
    --concurrency 64 \
    --version-id boot12_jp_p10000_s3532_guided 2>&1 | tee -a $OUT_LOG

END_TS=$(date +%s)
echo "boot12_end_epoch=$END_TS" | tee -a $OUT_LOG
echo "boot12_elapsed_seconds=$(( END_TS - START_TS ))" | tee -a $OUT_LOG

curl -s http://127.0.0.1:8000/metrics > ~/boot12_metrics_after.txt
