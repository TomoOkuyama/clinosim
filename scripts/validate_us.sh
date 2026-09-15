#!/usr/bin/env bash
#
# validate_us.sh — US FHIR (US Core) プロファイル適合性検証ブリッジ
#                  (S115, Issue #1418 Phase 3)
#
# 目的:
#   clinosim の US 出力 (FHIR R4 NDJSON) を HL7 公式 FHIR Validator と
#   US Core IG に対して検証する。JP 側 (`validate_jp.sh`) の mirror。
#
# 使い方:
#   # 単純実行 (validator jar 未設定なら sample 抽出まで、validation skip):
#   ./scripts/validate_us.sh
#
#   # 実際に validator を回す (推奨):
#   VALIDATOR_JAR=/path/to/validator_cli.jar ./scripts/validate_us.sh
#
# 環境変数:
#   VALIDATOR_JAR              HL7 公式 validator jar のパス。未設定なら
#                              サンプル生成 + 検証手順出力のみ (skip)。
#   CLINOSIM_US_VAL_POPULATION 生成 population (default 100)
#   CLINOSIM_US_VAL_SEED       乱数 seed (default 42)
#   CLINOSIM_US_VAL_END        snapshot date (default 2026-06-30)
#   CLINOSIM_US_VAL_PINS       pin file path (default .github/us-validator-pins.env)
#   CLINOSIM_US_VAL_STRICT     "1" のとき pin SHA256 mismatch を fail に
#
# 検証範囲:
#   US Core 8.0 の主要 must-support profile に対してサンプル 1 件ずつ:
#     - us-core-patient
#     - us-core-encounter
#     - us-core-condition-encounter-diagnosis
#     - us-core-condition-problems-health-concerns
#     - us-core-medicationrequest
#     - us-core-observation-lab
#     - us-core-allergyintolerance
#     - us-core-immunization
#     - us-core-diagnosticreport-lab
#
set -euo pipefail

POPULATION="${CLINOSIM_US_VAL_POPULATION:-100}"
SEED="${CLINOSIM_US_VAL_SEED:-42}"
END="${CLINOSIM_US_VAL_END:-2026-06-30}"

echo "validate_us.sh: US FHIR (US Core) profile validation bridge"
echo "  population=$POPULATION seed=$SEED end=$END"

# --------------------------------------------------------------------------- #
# Sanity: clinosim on PATH
if ! command -v clinosim >/dev/null 2>&1; then
    echo "validate_us.sh: clinosim CLI not on PATH — 'pip install -e .' first" >&2
    exit 2
fi

# --------------------------------------------------------------------------- #
# 作業一時ディレクトリ
TMP=$(mktemp -d -t clinosim-us-validate.XXXXXX)
cleanup() { rm -rf "$TMP"; }
trap cleanup EXIT

OUT="$TMP/out"
mkdir -p "$OUT"

# --------------------------------------------------------------------------- #
# 1. US コホート生成 (FHIR R4)
echo ""
echo "== Step 1: US cohort 生成 =="
clinosim generate \
    --country US \
    --population "$POPULATION" \
    --seed "$SEED" \
    --format fhir-r4 \
    --output "$OUT" \
    --end "$END"

# --------------------------------------------------------------------------- #
# 2. US Core profile 対応 resource から代表サンプルを抽出
echo ""
echo "== Step 2: 検証対象サンプル抽出 =="
SAMPLES="$TMP/samples"
mkdir -p "$SAMPLES"

python3 - "$OUT/fhir_r4" "$SAMPLES" << 'PYEOF'
import json, sys
from pathlib import Path

fhir_dir = Path(sys.argv[1])
sample_dir = Path(sys.argv[2])

# Pick one representative resource per US Core profile bucket.
# Condition uses two profiles keyed by category:
#   - us-core-condition-encounter-diagnosis (category="encounter-diagnosis")
#   - us-core-condition-problems-health-concerns (category="problem-list-item")
targets = {
    "Patient": lambda r: True,
    "Encounter": lambda r: True,
    "MedicationRequest": lambda r: True,
    "AllergyIntolerance": lambda r: True,
    "Immunization": lambda r: True,
    # Lab Observation: category.coding.code == "laboratory"
    "Observation": lambda r: any(
        cc.get("code") == "laboratory"
        for cat in r.get("category", []) or []
        for cc in cat.get("coding", []) or []
    ),
    # Lab DiagnosticReport: category.coding.code == "LAB"
    "DiagnosticReport": lambda r: any(
        cc.get("code") == "LAB"
        for cat in r.get("category", []) or []
        for cc in cat.get("coding", []) or []
    ),
}
picked: dict[str, dict] = {}

# Condition split by category
condition_targets = {
    "encounter-diagnosis": "EncounterDiagnosis",
    "problem-list-item": "ProblemListItem",
}
condition_picked: dict[str, dict] = {}

for ndjson_path in sorted(fhir_dir.rglob("*.ndjson")):
    rt = ndjson_path.stem
    if rt == "Condition":
        with open(ndjson_path) as f:
            for line in f:
                r = json.loads(line)
                for cat in r.get("category", []) or []:
                    for cc in cat.get("coding", []) or []:
                        code = cc.get("code", "")
                        if code in condition_targets and code not in condition_picked:
                            condition_picked[code] = r
                            break
        continue
    if rt not in targets:
        continue
    if rt in picked:
        continue
    with open(ndjson_path) as f:
        for line in f:
            r = json.loads(line)
            if targets[rt](r):
                picked[rt] = r
                break

for rt, r in picked.items():
    (sample_dir / f"{rt}.json").write_text(
        json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8"
    )
for code, r in condition_picked.items():
    label = condition_targets[code]
    (sample_dir / f"Condition_{label}.json").write_text(
        json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8"
    )

expected_count = len(picked) + len(condition_picked)
print(f"  抽出済: {expected_count} 種 ({sorted(picked.keys()) + sorted(condition_picked.keys())})")
if not expected_count:
    print("  警告: 抽出対象 0 件。cohort が小さすぎる可能性あり", file=sys.stderr)
PYEOF

SAMPLE_COUNT=$(find "$SAMPLES" -name "*.json" | wc -l | tr -d ' ')
echo "  サンプルディレクトリ: $SAMPLES ($SAMPLE_COUNT files)"

# --------------------------------------------------------------------------- #
# 3. Validator 実行 (VALIDATOR_JAR 指定時のみ)
echo ""
echo "== Step 3: HL7 FHIR Validator 実行 =="
if [ -z "${VALIDATOR_JAR:-}" ]; then
    cat << 'MSG'
  VALIDATOR_JAR が未設定のため、実行を skip します。
  以下の手順で手動検証してください:

    1. Java 11+ をインストール
    2. https://github.com/hapifhir/org.hl7.fhir.core/releases から
       validator_cli.jar を取得
    3. US Core IG package の指定 (例):
       -ig hl7.fhir.us.core#8.0.0
    4. 例:
       java -jar validator_cli.jar \
         -version 4.0.1 \
         -ig hl7.fhir.us.core#8.0.0 \
         -profile http://hl7.org/fhir/us/core/StructureDefinition/us-core-patient \
         Samples/Patient.json
    5. スクリプト再実行時に VALIDATOR_JAR=... を設定すれば自動 dispatch:
       VALIDATOR_JAR=/path/to/validator_cli.jar ./scripts/validate_us.sh
MSG
    echo ""
    echo "validate_us.sh: サンプル抽出まで完了 (VALIDATOR_JAR 未設定のため validation skip)"
    exit 0
fi

if ! command -v java >/dev/null 2>&1; then
    echo "validate_us.sh: Java コマンドが見つかりません (Java 11+ が必要)" >&2
    exit 2
fi

if [ ! -f "$VALIDATOR_JAR" ]; then
    echo "validate_us.sh: VALIDATOR_JAR=$VALIDATOR_JAR が存在しません" >&2
    exit 2
fi

# --------------------------------------------------------------------------- #
# 3a. IG package pinning
#
# `.github/us-validator-pins.env` を source すると US_CORE_PACKAGE_ID / _VERSION /
# _URL / _SHA256 が入り、validator の `-ig` オプションに変換する。
# 未指定なら profile URL 経由の online 解決に fallback (warn)。
#
# STRICT=1 のとき: pin 済み SHA256 と実測値が不一致 → exit 1 (CI gate)。
# STRICT=0 (default) でも placeholder が無設定なら警告のみ。
STRICT="${CLINOSIM_US_VAL_STRICT:-0}"

IG_ARGS=()

_verify_sha256() {
    local file="$1"; local expected="$2"; local label="$3"
    if [ -z "$expected" ]; then
        if [ "$STRICT" = "1" ]; then
            echo "validate_us.sh: STRICT モードで $label の SHA256 が未設定" >&2
            return 1
        fi
        echo "  warn: $label SHA256 未設定 (bootstrap モード扱い)"
        return 0
    fi
    local actual
    actual=$(shasum -a 256 "$file" | awk '{print $1}')
    if [ "$actual" != "$expected" ]; then
        echo "validate_us.sh: $label SHA256 mismatch" >&2
        echo "  expected: $expected" >&2
        echo "  actual:   $actual" >&2
        return 1
    fi
    echo "  ok: $label SHA256 verified"
    return 0
}

_resolve_ig() {
    local label="$1"; local pkg_id="$2"; local pkg_ver="$3"
    local pkg_url="$4"; local pkg_sha="$5"
    if [ -n "$pkg_url" ]; then
        local dest="$TMP/${label}.tgz"
        echo "  fetch: $label from $pkg_url"
        curl -sSL -o "$dest" "$pkg_url" || {
            echo "validate_us.sh: $label のダウンロード失敗 ($pkg_url)" >&2
            return 1
        }
        _verify_sha256 "$dest" "$pkg_sha" "$label" || return 1
        IG_ARGS+=("-ig" "$dest")
        return 0
    fi
    if [ -n "$pkg_id" ] && [ -n "$pkg_ver" ]; then
        echo "  pin: $label -> $pkg_id#$pkg_ver (validator が package registry から解決)"
        IG_ARGS+=("-ig" "${pkg_id}#${pkg_ver}")
        return 0
    fi
    echo "  warn: $label 未 pin (validator が profile URL からオンライン解決を試みる)"
    return 0
}

if [ -n "${CLINOSIM_US_VAL_PINS:-}" ] && [ -f "${CLINOSIM_US_VAL_PINS}" ]; then
    echo ""
    echo "== Step 3a: IG package pin 解決 =="
    # shellcheck source=/dev/null
    set -a; source "${CLINOSIM_US_VAL_PINS}"; set +a
    _resolve_ig "us-core" \
        "${US_CORE_PACKAGE_ID:-}" "${US_CORE_PACKAGE_VERSION:-}" \
        "${US_CORE_PACKAGE_URL:-}" "${US_CORE_PACKAGE_SHA256:-}" \
        || exit 1
fi

# 各サンプルを検証 (profile URL は US Core 8.0 IG の canonical URL を使用)
declare -A PROFILES=(
    ["Patient.json"]="http://hl7.org/fhir/us/core/StructureDefinition/us-core-patient"
    ["Encounter.json"]="http://hl7.org/fhir/us/core/StructureDefinition/us-core-encounter"
    ["Condition_EncounterDiagnosis.json"]="http://hl7.org/fhir/us/core/StructureDefinition/us-core-condition-encounter-diagnosis"
    ["Condition_ProblemListItem.json"]="http://hl7.org/fhir/us/core/StructureDefinition/us-core-condition-problems-health-concerns"
    ["MedicationRequest.json"]="http://hl7.org/fhir/us/core/StructureDefinition/us-core-medicationrequest"
    ["Observation.json"]="http://hl7.org/fhir/us/core/StructureDefinition/us-core-observation-lab"
    ["AllergyIntolerance.json"]="http://hl7.org/fhir/us/core/StructureDefinition/us-core-allergyintolerance"
    ["Immunization.json"]="http://hl7.org/fhir/us/core/StructureDefinition/us-core-immunization"
    ["DiagnosticReport.json"]="http://hl7.org/fhir/us/core/StructureDefinition/us-core-diagnosticreport-lab"
)

TOTAL=0
PASSED=0
FAILED=0
for sample in "$SAMPLES"/*.json; do
    filename=$(basename "$sample")
    if [ -z "${PROFILES[$filename]:-}" ]; then
        continue
    fi
    profile="${PROFILES[$filename]}"
    TOTAL=$((TOTAL + 1))
    echo "  validating $filename against $profile"
    if java -jar "$VALIDATOR_JAR" \
            -version 4.0.1 \
            "${IG_ARGS[@]}" \
            -profile "$profile" \
            "$sample" >"$TMP/val_${filename}.log" 2>&1; then
        PASSED=$((PASSED + 1))
        echo "    PASS"
    else
        FAILED=$((FAILED + 1))
        echo "    FAIL — see $TMP/val_${filename}.log"
        tail -5 "$TMP/val_${filename}.log" | sed 's/^/      /'
    fi
done

echo ""
echo "== Summary =="
echo "  total=$TOTAL passed=$PASSED failed=$FAILED"
if [ "$FAILED" -gt 0 ]; then
    echo "validate_us.sh: FAIL — $FAILED / $TOTAL profile checks failed"
    exit 1
fi
if [ "$TOTAL" -eq 0 ]; then
    # STRICT モードでサンプル 0 は silent-no-op として fail
    echo "validate_us.sh: no samples validated (extraction may be broken)" >&2
    [ "$STRICT" = "1" ] && exit 1
fi
echo "validate_us.sh: PASS — all $TOTAL profile checks passed"
