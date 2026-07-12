#!/usr/bin/env bash
#
# validate_jp.sh — JP FHIR プロファイル適合性検証ブリッジ(session 47 PR3 sub-PR-C)
#
# 目的:
#   clinosim の JP 出力(FHIR R4 NDJSON)を HL7 公式 FHIR Validator と
#   JP Core / JP-CLINS / JP-eCheckup IG に対して検証する。
#
# 使い方:
#   # 単純実行(validator jar 環境変数指定不要、自動 skip):
#   ./scripts/validate_jp.sh
#
#   # 実際に validator を回す(推奨):
#   VALIDATOR_JAR=/path/to/validator_cli.jar ./scripts/validate_jp.sh
#
# 環境変数:
#   VALIDATOR_JAR              HL7 公式 validator jar のパス。未設定なら
#                              サンプル生成 + 検証手順出力のみ(skip)。
#   CLINOSIM_JP_VAL_POPULATION 生成 population(default 10)
#   CLINOSIM_JP_VAL_SEED       乱数 seed(default 42)
#   CLINOSIM_JP_VAL_END        snapshot date(default 2026-06-30)
#   CLINOSIM_JP_VAL_HEALTH     "1" のとき health_checkup opt-in module を有効化
#
# validator jar 取得(手動):
#   https://github.com/hapifhir/org.hl7.fhir.core/releases から
#   validator_cli.jar を取得(Java 11+ 必要)。
#
# JP IG パッケージ:
#   JP Core:      https://jpfhir.jp/fhir/core/
#   JP-CLINS:     https://jpfhir.jp/fhir/clins/
#   JP-eCheckup:  https://jpfhir.jp/fhir/eCheckup/
#
# 検証範囲(MVP):
#   - JP Core Bundle 生成後、以下の profile 対象 resource 各 1 件を抽出:
#     JP_Condition_eCS / JP_AllergyIntolerance_eCS /
#     JP_Observation_LabResult_eCS / JP_MedicationRequest_eCS /
#     JP_Procedure_eCS / JP_Composition_eDischargeSummary /
#     JP_Composition_eReferral / JP_Composition_eCheckupGeneral(opt-in 時)
#   - 各サンプルに対して validator を実行、結果を集約。
#   将来 sub-PR で:全 resource 検証 / CI 自動 fail gate / 実 IG package
#   URL 更新への追従を追加可能。
#
set -euo pipefail

POPULATION="${CLINOSIM_JP_VAL_POPULATION:-10}"
SEED="${CLINOSIM_JP_VAL_SEED:-42}"
END="${CLINOSIM_JP_VAL_END:-2026-06-30}"
HEALTH="${CLINOSIM_JP_VAL_HEALTH:-1}"

echo "validate_jp.sh: JP FHIR profile validation bridge"
echo "  population=$POPULATION seed=$SEED end=$END health_checkup=$HEALTH"

# --------------------------------------------------------------------------- #
# Sanity: clinosim on PATH
if ! command -v clinosim >/dev/null 2>&1; then
    echo "validate_jp.sh: clinosim CLI not on PATH — 'pip install -e .' first" >&2
    exit 2
fi

# --------------------------------------------------------------------------- #
# 作業一時ディレクトリ
TMP=$(mktemp -d -t clinosim-jp-validate.XXXXXX)
cleanup() { rm -rf "$TMP"; }
trap cleanup EXIT

OUT="$TMP/out"
mkdir -p "$OUT"

# --------------------------------------------------------------------------- #
# 1. JP コホート生成(FHIR R4)
echo ""
echo "== Step 1: JP cohort 生成 =="
GEN_ARGS=(
    generate
    --country JP
    --population "$POPULATION"
    --seed "$SEED"
    --format fhir-r4
    --output "$OUT"
    --end "$END"
)
if [ "$HEALTH" = "1" ]; then
    # health_checkup opt-in を有効化するために --enable-module 相当の CLI が
    # 現状無いため、SimulatorConfig 直接指定は Python 経由で行う。将来
    # sub-PR で CLI --enable-module <name> を追加すれば簡潔になる。
    echo "  health_checkup opt-in を Python 経由で有効化"
    python3 - "$OUT" "$POPULATION" "$SEED" "$END" << 'PYEOF'
import sys, tempfile
from pathlib import Path
from clinosim.simulator.engine import run_beta
from clinosim.types.config import SimulatorConfig
from clinosim.modules.output.cif_writer import write_cif
from clinosim.modules.output.fhir_r4_adapter import convert_cif_to_fhir
from clinosim.modules.document.narrative.passes import TemplateNarrativePass

out_dir, pop, seed, end = sys.argv[1:]
cfg = SimulatorConfig(
    country="JP", random_seed=int(seed),
    catchment_population=int(pop),
    snapshot_date=end,
    modules={"health_checkup": True},
)
dataset = run_beta(cfg)
out = Path(out_dir)
cif_dir = out / "cif"
fhir_dir = out / "fhir_r4"
write_cif(dataset, str(cif_dir))
TemplateNarrativePass(cif_dir=str(cif_dir), country="JP").run()
convert_cif_to_fhir(str(cif_dir), str(fhir_dir), country="JP")
print(f"  generated: {len(dataset.patients)} records into {out}")
PYEOF
else
    clinosim "${GEN_ARGS[@]}"
fi

# --------------------------------------------------------------------------- #
# 2. JP profile 対応 resource から代表サンプルを抽出
echo ""
echo "== Step 2: 検証対象サンプル抽出 =="
SAMPLES="$TMP/samples"
mkdir -p "$SAMPLES"

# jq 使用可否
if ! command -v jq >/dev/null 2>&1; then
    echo "validate_jp.sh: jq が見つからないため Python で抽出" >&2
fi

python3 - "$OUT/fhir_r4" "$SAMPLES" << 'PYEOF'
import json, sys
from pathlib import Path

fhir_dir = Path(sys.argv[1])
sample_dir = Path(sys.argv[2])

# 各 JP profile 対応 resource type から代表 1 件を抽出。
# Composition は type.coding.code で内訳を分けて 3 種すべて拾う。
picked: dict[str, dict] = {}
targets = {
    "Condition": lambda r: True,
    "AllergyIntolerance": lambda r: True,
    "Observation": lambda r: any(
        cc.get("code") == "laboratory"
        for cat in r.get("category", []) or []
        for cc in cat.get("coding", []) or []
    ),
    "MedicationRequest": lambda r: True,
    "Procedure": lambda r: True,
}
composition_targets = {"18842-5", "57133-1", "53576-5"}
composition_picked: dict[str, dict] = {}

for ndjson_path in sorted(fhir_dir.rglob("*.ndjson")):
    rt = ndjson_path.stem
    if rt == "Composition":
        with open(ndjson_path) as f:
            for line in f:
                r = json.loads(line)
                for cc in r.get("type", {}).get("coding", []):
                    code = cc.get("code", "")
                    if code in composition_targets and code not in composition_picked:
                        composition_picked[code] = r
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

# 書き出し
for rt, r in picked.items():
    (sample_dir / f"{rt}.json").write_text(
        json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8"
    )
for code, r in composition_picked.items():
    label = {
        "18842-5": "DischargeSummary",
        "57133-1": "ReferralNote",
        "53576-5": "HealthCheckupReport",
    }.get(code, code)
    (sample_dir / f"Composition_{label}.json").write_text(
        json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8"
    )

expected_count = len(picked) + len(composition_picked)
print(f"  抽出済: {expected_count} 種 ({sorted(picked.keys()) + sorted(composition_picked.keys())})")
if not expected_count:
    print("  警告: 抽出対象 0 件。cohort が小さすぎる可能性あり", file=sys.stderr)
PYEOF

SAMPLE_COUNT=$(find "$SAMPLES" -name "*.json" | wc -l | tr -d ' ')
echo "  サンプルディレクトリ: $SAMPLES ($SAMPLE_COUNT files)"

# --------------------------------------------------------------------------- #
# 3. Validator 実行(VALIDATOR_JAR 指定時のみ)
echo ""
echo "== Step 3: HL7 FHIR Validator 実行 =="
if [ -z "${VALIDATOR_JAR:-}" ]; then
    cat << 'MSG'
  VALIDATOR_JAR が未設定のため、実行を skip します。
  以下の手順で手動検証してください:

    1. Java 11+ をインストール
    2. https://github.com/hapifhir/org.hl7.fhir.core/releases から
       validator_cli.jar を取得
    3. JP IG パッケージを取得(将来 sub-PR で URL 固定化予定):
       - JP Core:     https://jpfhir.jp/fhir/core/
       - JP-CLINS:    https://jpfhir.jp/fhir/clins/
       - JP-eCheckup: https://jpfhir.jp/fhir/eCheckup/
    4. 例:
       java -jar validator_cli.jar \
         -version 4.0.1 \
         -ig <path-to-jp-core-package.tgz> \
         -ig <path-to-jp-clins-package.tgz> \
         -profile http://jpfhir.jp/fhir/eCS/StructureDefinition/JP_MedicationRequest_eCS \
         Samples/MedicationRequest.json
    5. スクリプト再実行時に VALIDATOR_JAR=... を設定すれば自動 dispatch:
       VALIDATOR_JAR=/path/to/validator_cli.jar ./scripts/validate_jp.sh
MSG
    echo ""
    echo "validate_jp.sh: サンプル抽出まで完了(VALIDATOR_JAR 未設定のため validation skip)"
    exit 0
fi

if ! command -v java >/dev/null 2>&1; then
    echo "validate_jp.sh: Java コマンドが見つかりません(Java 11+ が必要)" >&2
    exit 2
fi

if [ ! -f "$VALIDATOR_JAR" ]; then
    echo "validate_jp.sh: VALIDATOR_JAR=$VALIDATOR_JAR が存在しません" >&2
    exit 2
fi

# --------------------------------------------------------------------------- #
# 3a. IG package pinning(sub-PR-C 高度化, session 48)
#
# `.github/jp-validator-pins.env` を source すると *_PACKAGE_ID / _VERSION /
# _URL / _SHA256 が入り、validator の `-ig` オプションに変換する。
# 未指定なら profile URL 経由の online 解決に fallback(v0.2 挙動、warn)。
#
# STRICT=1 のとき:pin 済み SHA256 と実測値が不一致 → exit 1(CI gate)。
# STRICT=0(default)でも placeholder が無設定なら警告のみ。
STRICT="${CLINOSIM_JP_VAL_STRICT:-0}"

IG_ARGS=()

_verify_sha256() {
    local file="$1"; local expected="$2"; local label="$3"
    if [ -z "$expected" ]; then
        if [ "$STRICT" = "1" ]; then
            echo "validate_jp.sh: STRICT モードで $label の SHA256 が未設定" >&2
            return 1
        fi
        echo "  warn: $label SHA256 未設定(bootstrap モード扱い)"
        return 0
    fi
    local actual
    actual=$(shasum -a 256 "$file" | awk '{print $1}')
    if [ "$actual" != "$expected" ]; then
        echo "validate_jp.sh: $label SHA256 mismatch" >&2
        echo "  expected: $expected" >&2
        echo "  actual:   $actual" >&2
        return 1
    fi
    echo "  ok: $label SHA256 verified"
    return 0
}

# JP Core:優先順位 = 直接 URL > package id#version > profile URL fallback
_resolve_ig() {
    local label="$1"; local pkg_id="$2"; local pkg_ver="$3"
    local pkg_url="$4"; local pkg_sha="$5"
    if [ -n "$pkg_url" ]; then
        local dest="$TMP/${label}.tgz"
        echo "  fetch: $label from $pkg_url"
        curl -sSL -o "$dest" "$pkg_url" || {
            echo "validate_jp.sh: $label のダウンロード失敗($pkg_url)" >&2
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
    echo "  warn: $label 未 pin(validator が profile URL からオンライン解決を試みる)"
    return 0
}

if [ -n "${CLINOSIM_JP_VAL_PINS:-}" ] && [ -f "${CLINOSIM_JP_VAL_PINS}" ]; then
    echo ""
    echo "== Step 3a: IG package pin 解決 =="
    # shellcheck source=/dev/null
    set -a; source "${CLINOSIM_JP_VAL_PINS}"; set +a
    _resolve_ig "jp-core" \
        "${JP_CORE_PACKAGE_ID:-}" "${JP_CORE_PACKAGE_VERSION:-}" \
        "${JP_CORE_PACKAGE_URL:-}" "${JP_CORE_PACKAGE_SHA256:-}" \
        || exit 1
    _resolve_ig "jp-clins" \
        "${JP_CLINS_PACKAGE_ID:-}" "${JP_CLINS_PACKAGE_VERSION:-}" \
        "${JP_CLINS_PACKAGE_URL:-}" "${JP_CLINS_PACKAGE_SHA256:-}" \
        || exit 1
    _resolve_ig "jp-eCheckup" \
        "${JP_ECHECKUP_PACKAGE_ID:-}" "${JP_ECHECKUP_PACKAGE_VERSION:-}" \
        "${JP_ECHECKUP_PACKAGE_URL:-}" "${JP_ECHECKUP_PACKAGE_SHA256:-}" \
        || exit 1
fi

# 各サンプルを検証(profile URL は JP FHIR IG の canonical URL を使用)
declare -A PROFILES=(
    ["Condition.json"]="http://jpfhir.jp/fhir/eCS/StructureDefinition/JP_Condition_eCS"
    ["AllergyIntolerance.json"]="http://jpfhir.jp/fhir/eCS/StructureDefinition/JP_AllergyIntolerance_eCS"
    ["Observation.json"]="http://jpfhir.jp/fhir/eCS/StructureDefinition/JP_Observation_LabResult_eCS"
    ["MedicationRequest.json"]="http://jpfhir.jp/fhir/eCS/StructureDefinition/JP_MedicationRequest_eCS"
    ["Procedure.json"]="http://jpfhir.jp/fhir/eCS/StructureDefinition/JP_Procedure_eCS"
    ["Composition_DischargeSummary.json"]="http://jpfhir.jp/fhir/eDischargeSummary/StructureDefinition/JP_Composition_eDischargeSummary"
    ["Composition_ReferralNote.json"]="http://jpfhir.jp/fhir/eReferral/StructureDefinition/JP_Composition_eReferral"
    ["Composition_HealthCheckupReport.json"]="http://jpfhir.jp/fhir/eCheckup/StructureDefinition/JP_Composition_eCheckupGeneral"
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
    echo "validate_jp.sh: FAIL — $FAILED / $TOTAL profile checks failed"
    exit 1
fi
if [ "$TOTAL" -eq 0 ]; then
    # STRICT モードでサンプル 0 は silent-no-op として fail(sub-PR-C 高度化)
    echo "validate_jp.sh: no samples validated (extraction may be broken)" >&2
    [ "$STRICT" = "1" ] && exit 1
fi
echo "validate_jp.sh: PASS — all $TOTAL profile checks passed"
