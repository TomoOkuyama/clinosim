#!/usr/bin/env bash
# Full US run: CIF generation + English narrative generation (Bedrock)
# Run on EC2 with Bedrock access.
#
# Usage (session-safe):
#   nohup ./scripts/full_run_us.sh > /dev/null 2>&1 &
#   tail -f test_data/bedrock_us_full_results.txt
set -euo pipefail

OUTPUT_DIR="output/us_full"
VERSION_ID="bedrock_en_full"
LLM_CONFIG="clinosim/config/llm_service.bedrock.yaml"
RESULT_FILE="test_data/bedrock_us_full_results.txt"

{
echo "============================================================"
echo "  Full US Run (CIF + English Narrative)"
echo "  Date: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo "  PID: $$"
echo "============================================================"
echo ""

# Step 1: Generate CIF (US, 40K population, 50-bed hospital, seed=42)
echo ">>> Step 1: CIF generation"
python3 -m clinosim.simulator.cli generate \
    -o "${OUTPUT_DIR}" \
    -s 42 \
    --country US \
    --format cif

echo ""
echo ">>> Step 2: English narrative generation (Bedrock)"
python3 -m clinosim.simulator.cli narrate \
    --cif-dir "${OUTPUT_DIR}/cif" \
    --llm-config "${LLM_CONFIG}" \
    --language en \
    --version-id "${VERSION_ID}"

echo ""
echo "============================================================"
echo "  Generated Documents (1 sample per type)"
echo "============================================================"

python3 -c "
import json, os

docs_root = '${OUTPUT_DIR}/cif/narratives/${VERSION_ID}/documents'
seen = set()
for enc_dir in sorted(os.listdir(docs_root)):
    enc_path = os.path.join(docs_root, enc_dir)
    if not os.path.isdir(enc_path): continue
    for fn in sorted(os.listdir(enc_path)):
        d = json.load(open(os.path.join(enc_path, fn)))
        tt = d['task_type']
        if tt in seen: continue
        seen.add(tt)
        print()
        print('=' * 60)
        print(f'  {tt} (LOINC {d[\"loinc_code\"]})')
        print(f'  source={d[\"text_source\"]} model={d[\"llm_model\"]}')
        print(f'  tokens: in={d[\"llm_input_tokens\"]} out={d[\"llm_output_tokens\"]}')
        print('=' * 60)
        print(d['text'])
    if len(seen) >= 5: break
"

echo ""
echo "=== Manifest ==="
cat "${OUTPUT_DIR}/cif/narratives/${VERSION_ID}/manifest.json"

echo ""
echo "============================================================"
echo "  DONE: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo "  Results: ${RESULT_FILE}"
echo "============================================================"
} 2>&1 | tee "${RESULT_FILE}"
