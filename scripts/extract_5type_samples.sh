#!/usr/bin/env bash
# Extract one sample of each document type for clinical review.
# Run AFTER narrate completes.
#
# Usage:
#   ./scripts/extract_5type_samples.sh [cif_dir] [version_id]
set -euo pipefail

CIF_DIR="${1:-./output_validation/cif}"
VERSION="${2:-bedrock_5types_check}"
DOCS_ROOT="${CIF_DIR}/narratives/${VERSION}/documents"
OUT="test_data/bedrock_5type_samples.txt"

if [ ! -d "${DOCS_ROOT}" ]; then
    echo "ERROR: ${DOCS_ROOT} not found. Run narrate first."
    exit 1
fi

{
echo "============================================================"
echo "  5-Type Clinical Document Samples"
echo "  CIF: ${CIF_DIR}"
echo "  Version: ${VERSION}"
echo "  Date: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo "============================================================"

# Show manifest summary
echo ""
echo "=== MANIFEST ==="
python3 -c "
import json
m = json.load(open('${CIF_DIR}/narratives/${VERSION}/manifest.json'))
print(f'Patients:  {m[\"patient_count\"]}')
print(f'Documents: {m[\"total_documents\"]}')
for t, n in sorted(m['document_counts_by_type'].items()):
    print(f'  {t:20s} {n}')
c = m['llm_cost_report']
print(f'LLM calls: {c[\"total_calls\"]}  cache_hits: {c[\"cache_hit_count\"]}  fallbacks: {c[\"fallback_count\"]}')
print(f'Tokens: in={c[\"total_input_tokens\"]:,}  out={c[\"total_output_tokens\"]:,}')
"

# For each of the 5 types, find one sample and print it with its CIF source data
for DOC_TYPE in admission_hp discharge_summary death_summary operative_note procedure_note; do
    echo ""
    echo "============================================================"
    echo "  SAMPLE: ${DOC_TYPE}"
    echo "============================================================"

    python3 -c "
import json, os, glob

doc_type = '${DOC_TYPE}'
docs_root = '${DOCS_ROOT}'
cif_structural = '${CIF_DIR}/structural/patients'

# Find first matching document
found = False
for enc_dir in sorted(os.listdir(docs_root)):
    enc_path = os.path.join(docs_root, enc_dir)
    if not os.path.isdir(enc_path):
        continue
    for fn in sorted(os.listdir(enc_path)):
        if not fn.startswith(doc_type):
            continue
        doc_path = os.path.join(enc_path, fn)
        d = json.load(open(doc_path))

        # Load corresponding CIF record for context
        cif_file = os.path.join(cif_structural, f'{enc_dir}.json')
        cif = json.load(open(cif_file)) if os.path.exists(cif_file) else {}
        patient = cif.get('patient', {})
        encounter = (cif.get('encounters') or [{}])[0]
        cd = cif.get('clinical_diagnosis', {})
        condition = cif.get('condition_event', {})

        print(f'Encounter: {enc_dir}')
        print(f'Patient:   {patient.get(\"age\",\"?\")}yo {patient.get(\"sex\",\"?\")}')
        print(f'Ground truth: {condition.get(\"ground_truth_diseases\", [])}')
        print(f'Admit Dx:  {cd.get(\"admission_diagnosis_code\",\"\")}')
        print(f'Disch Dx:  {cd.get(\"discharge_diagnosis_code\",\"\")}')
        print(f'Deceased:  {cif.get(\"deceased\", False)}')
        print(f'Procedures: {len(cif.get(\"procedures\",[]))}')
        chief = encounter.get('chief_complaint', '')
        print(f'Chief:     {chief}')
        print(f'LOS:       {encounter.get(\"discharge_disposition\",\"?\")}')
        print()
        print(f'LOINC:     {d[\"loinc_code\"]}')
        print(f'Source:    {d[\"text_source\"]} (model: {d[\"llm_model\"]})')
        print(f'Tokens:    in={d[\"llm_input_tokens\"]}  out={d[\"llm_output_tokens\"]}')
        print(f'Cache:     {d[\"cache_hit\"]}')
        print('------------------------------------------------------------')
        print(d['text'])
        found = True
        break
    if found:
        break

if not found:
    print(f'(no {doc_type} document found in this version)')
"
done

echo ""
echo "============================================================"
echo "  Extraction complete."
echo "  To share: git add ${OUT} && git commit -m 'bedrock 5-type samples' && git push"
echo "============================================================"
} 2>&1 | tee "${OUT}"
