#!/usr/bin/env bash
# Boot 11 v2 = JP p=10000 s=2532 with Fix C (guided_json), same vLLM
set -euo pipefail
source ~/vllm-env/bin/activate
cd ~/clinosim && export PYTHONPATH=.

CIF_DIR=/home/ubuntu/boot11_jp_p10000_s2532/cif
LLM_CONFIG=/home/ubuntu/verify/llm_service_vllm_guided.yaml
OUT_LOG=~/boot11_v2_narrate.log

curl -s http://127.0.0.1:8000/metrics > ~/boot11_v2_metrics_before.txt

START_TS=$(date +%s)
echo "boot11_v2_start_epoch=$START_TS" | tee -a $OUT_LOG

time clinosim narrate \
    --cif-dir "$CIF_DIR" \
    --provider vllm \
    --llm-config "$LLM_CONFIG" \
    --country JP \
    --concurrency 64 \
    --version-id boot11_v2_jp_p10000_s2532_guided 2>&1 | tee -a $OUT_LOG

END_TS=$(date +%s)
echo "boot11_v2_end_epoch=$END_TS" | tee -a $OUT_LOG
echo "boot11_v2_elapsed_seconds=$(( END_TS - START_TS ))" | tee -a $OUT_LOG

curl -s http://127.0.0.1:8000/metrics > ~/boot11_v2_metrics_after.txt
