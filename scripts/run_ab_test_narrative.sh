#!/usr/bin/env bash
# Run A/B test narrative generation on EC2 with Bedrock.
#
# Reads prompt JSON files from test_data/ab_test/prompts/<enc_id>/<task>.<variant>.json
# Calls Bedrock once per file, saves output text + metadata to
# test_data/ab_test/results/<enc_id>/<task>.<variant>.json
#
# Usage (session-safe):
#   nohup ./scripts/run_ab_test_narrative.sh > /dev/null 2>&1 &
#   tail -f test_data/ab_test/run.log
set -euo pipefail

PROMPTS_DIR="test_data/ab_test/prompts"
RESULTS_DIR="test_data/ab_test/results"
LOG_FILE="test_data/ab_test/run.log"
LLM_CONFIG="clinosim/config/llm_service.bedrock.yaml"

{
echo "============================================================"
echo "  A/B Test Narrative Generation (Bedrock)"
echo "  Date: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo "  PID: $$"
echo "============================================================"
echo ""

python3 scripts/run_ab_test_narrative.py \
    --prompts-dir "${PROMPTS_DIR}" \
    --results-dir "${RESULTS_DIR}" \
    --llm-config "${LLM_CONFIG}"

echo ""
echo "  DONE: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo "  Results: ${RESULTS_DIR}"
} 2>&1 | tee "${LOG_FILE}"
