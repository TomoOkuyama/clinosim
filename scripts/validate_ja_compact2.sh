#!/usr/bin/env bash
# Compact JP narrative test v2: 8 patients (new seed/diseases), all 5 document types
set -euo pipefail

CIF_DIR="test_data/jp_compact2"
VERSION_ID="bedrock_ja_compact2"
LLM_CONFIG="clinosim/config/llm_service.bedrock.yaml"
RESULT_FILE="test_data/bedrock_ja_compact2_results.txt"

{
echo "============================================================"
echo "  JP Compact Narrative Test v2 (8 patients, 5 types)"
echo "  Date: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo "============================================================"
echo ""

python3 -m clinosim.simulator.cli narrate \
    --cif-dir "${CIF_DIR}" \
    --llm-config "${LLM_CONFIG}" \
    --language ja \
    --version-id "${VERSION_ID}"

echo ""
echo "============================================================"
echo "  All Generated Documents"
echo "============================================================"

python3 -c "
import json, os

docs_root = '${CIF_DIR}/narratives/${VERSION_ID}/documents'
for enc_dir in sorted(os.listdir(docs_root)):
    enc_path = os.path.join(docs_root, enc_dir)
    if not os.path.isdir(enc_path): continue
    for fn in sorted(os.listdir(enc_path)):
        d = json.load(open(os.path.join(enc_path, fn)))
        print()
        print('=' * 60)
        print(f'  {enc_dir} / {d[\"task_type\"]}')
        print(f'  LOINC={d[\"loinc_code\"]} tokens=in:{d[\"llm_input_tokens\"]}/out:{d[\"llm_output_tokens\"]}')
        print('=' * 60)
        print(d['text'])
"

echo ""
echo "=== Manifest ==="
cat "${CIF_DIR}/narratives/${VERSION_ID}/manifest.json"

echo ""
echo "============================================================"
echo "  Results: ${RESULT_FILE}"
echo "  git add ${RESULT_FILE} && git commit -m 'ja compact v2 results' && git push"
echo "============================================================"
} 2>&1 | tee "${RESULT_FILE}"
