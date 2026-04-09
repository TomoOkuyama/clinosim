#!/usr/bin/env bash
# Validate Bedrock narrative generation with a single hip fracture patient.
# Run on EC2 with Bedrock access.
#
# Usage:
#   ./scripts/validate_bedrock_single.sh
set -euo pipefail

CIF_DIR="test_data/bedrock_single_patient"
VERSION_ID="bedrock_validation"
LLM_CONFIG="clinosim/config/llm_service.bedrock.yaml"
DOCS_DIR="${CIF_DIR}/narratives/${VERSION_ID}/documents/ENC-POP-000085-000061"

echo "============================================================"
echo "  Bedrock Single-Patient Narrative Validation"
echo "  Patient: 56yo Female, hip fracture, hemiarthroplasty"
echo "============================================================"
echo ""

# Stage 2: Generate narratives
python3 -m clinosim.simulator.cli narrate \
    --cif-dir "${CIF_DIR}" \
    --llm-config "${LLM_CONFIG}" \
    --language en \
    --version-id "${VERSION_ID}"

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
echo "  Validation complete. Review the output above."
echo "============================================================"
