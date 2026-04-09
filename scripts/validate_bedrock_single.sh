#!/usr/bin/env bash
# Validate Bedrock narrative generation with a single hip fracture patient.
# Run on EC2 with Bedrock access.
#
# Output is saved to test_data/bedrock_results.txt AND printed to terminal.
# After running, commit and push to share results:
#   git add test_data/bedrock_results.txt && git commit -m "bedrock results" && git push
#
# Usage:
#   ./scripts/validate_bedrock_single.sh
set -euo pipefail

CIF_DIR="test_data/bedrock_single_patient"
VERSION_ID="bedrock_validation_v2"
LLM_CONFIG="clinosim/config/llm_service.bedrock.yaml"
RESULT_FILE="test_data/bedrock_results.txt"

# Run everything and tee to file
{
echo "============================================================"
echo "  Bedrock Single-Patient Narrative Validation"
echo "  Patient: 56yo Female, hip fracture, hemiarthroplasty"
echo "  Date: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo "============================================================"
echo ""

# Stage 2: Generate narratives (force fresh by removing old version)
rm -rf "${CIF_DIR}/narratives/${VERSION_ID}" 2>/dev/null || true

python3 -m clinosim.simulator.cli narrate \
    --cif-dir "${CIF_DIR}" \
    --llm-config "${LLM_CONFIG}" \
    --language en \
    --version-id "${VERSION_ID}"

DOCS_DIR="${CIF_DIR}/narratives/${VERSION_ID}/documents/ENC-POP-000085-000061"

echo ""
echo "============================================================"
echo "  Generated Documents"
echo "============================================================"

for f in "${DOCS_DIR}"/*.json; do
    filename=$(basename "$f")
    echo ""
    echo "============================================================"
    echo "  ${filename}"
    echo "============================================================"
    python3 -c "
import json
d = json.load(open('${f}'))
print(f'LOINC:      {d[\"loinc_code\"]}')
print(f'Source:     {d[\"text_source\"]} (model: {d[\"llm_model\"]})')
print(f'Tokens:     in={d[\"llm_input_tokens\"]}  out={d[\"llm_output_tokens\"]}')
print(f'Cache hit:  {d[\"cache_hit\"]}')
print('------------------------------------------------------------')
print(d['text'])
"
done

echo ""
echo "============================================================"
echo "  Manifest"
echo "============================================================"
cat "${CIF_DIR}/narratives/${VERSION_ID}/manifest.json"

echo ""
echo "============================================================"
echo "  Validation complete."
echo "  Results saved to: ${RESULT_FILE}"
echo "  To share: git add ${RESULT_FILE} && git commit -m 'bedrock validation results' && git push"
echo "============================================================"
} 2>&1 | tee "${RESULT_FILE}"
