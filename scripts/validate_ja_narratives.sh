#!/usr/bin/env bash
# Test Japanese narrative generation with Bedrock.
# Run on EC2 with Bedrock access.
#
# Usage:
#   ./scripts/validate_ja_narratives.sh
set -euo pipefail

CIF_DIR="test_data/ja_narr_test"
VERSION_ID="bedrock_ja_test"
LLM_CONFIG="clinosim/config/llm_service.bedrock.yaml"
RESULT_FILE="test_data/bedrock_ja_results.txt"

{
echo "============================================================"
echo "  Japanese Narrative Generation Test (Bedrock)"
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
echo "  Generated Documents (1 sample per type)"
echo "============================================================"

python3 -c "
import json, os

docs_root = '${CIF_DIR}/narratives/${VERSION_ID}/documents'
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
cat "${CIF_DIR}/narratives/${VERSION_ID}/manifest.json"

echo ""
echo "============================================================"
echo "  Results saved to: ${RESULT_FILE}"
echo "  To share: git add ${RESULT_FILE} && git commit -m 'ja narrative results' && git push"
echo "============================================================"
} 2>&1 | tee "${RESULT_FILE}"
