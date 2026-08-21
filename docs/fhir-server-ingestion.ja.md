# clinosim 出力を FHIR サーバに読み込む

clinosim は [HL7 FHIR R4 Bulk Data Access](https://hl7.org/fhir/uv/bulkdata/)
NDJSON — `resourceType` ごとに 1 ファイル — を emit します。この形式は
[`$import`](https://hl7.org/fhir/uv/bulkdata/OperationDefinition-import.html)
オペレーションで FHIR サーバに投入するために設計されています。本
ページは `datasets/jp-100` を汎用 FHIR サーバ (HAPI FHIR を具体例に
使用; 他の FHIR-R4 準拠サーバも同様) に読み込む手順を示します。

!!! note "ベンダー中立"
    本ガイドは商用 FHIR サーバに依存 **しません**。HAPI FHIR は最も
    広く配備されている HAPI ベース JPA サーバとして具体的な OSS 例に
    使用しています。任意の FHIR R4 Bulk Data 準拠サーバが同じ入力を
    受け付けるはずです。

## 前提条件

- `clinosim simulate --format fhir` または
  `clinosim dataset build <preset>` で生成した clinosim 出力
  ディレクトリ (例: `./jp-100/`)。
- Docker (ローカル HAPI FHIR 例用) または Bulk Data `$import` オペ
  レーションが有効な既存 FHIR R4 サーバ。
- `curl` または HTTP クライアント。

## 出力形状の確認

```bash
$ ls jp-100/fhir_r4/
AllergyIntolerance.ndjson    Encounter.ndjson             Location.ndjson
CareTeam.ndjson              Endpoint.ndjson              MedicationAdministration.ndjson
ClinicalImpression.ndjson    FamilyMemberHistory.ndjson   MedicationRequest.ndjson
Composition.ndjson           ImagingStudy.ndjson          Observation.ndjson
Condition.ndjson             Immunization.ndjson          Organization.ndjson
Coverage.ndjson              Patient.ndjson               PractitionerRole.ndjson
DiagnosticReport.ndjson      Practitioner.ndjson          Procedure.ndjson
DocumentReference.ndjson                                  ServiceRequest.ndjson
manifest.json
```

各 `.ndjson` は 1 行 1 FHIR リソース。`manifest.json` はそれら
ファイルを指す Bulk Data descriptor。

## Option A — Local HAPI FHIR (Docker)

### 1. サーバ起動

```bash
docker run -d --name hapi-fhir \
    -p 8080:8080 \
    -e hapi.fhir.default_encoding=json \
    -e hapi.fhir.bulk_export_enabled=true \
    -e hapi.fhir.bulk_import_enabled=true \
    -e hapi.fhir.fhir_version=R4 \
    hapiproject/hapi:latest
```

health probe がサーバの起動を報告するまで待機:

```bash
until curl -sf http://localhost:8080/fhir/metadata > /dev/null; do sleep 2; done
echo "HAPI FHIR ready at http://localhost:8080/fhir"
```

### 2. NDJSON ファイルを push

小規模コホートで最も簡単な手法は各リソースを bundle として POST。
大規模コホートには `$import` オペレーションを使用。

**小規模コホート — ファイル別 POST (どこでも動作):**

```bash
BASE=http://localhost:8080/fhir

# 順序が重要: reference ターゲットは referrer より前に存在する必要あり。
# Patient / Organization / Location を先に; 次に Encounter; その後
# Encounter を参照する全て (Condition / Observation /
# MedicationRequest / …)。CareTeam / Composition / DocumentReference /
# ClinicalImpression は複数の型を参照するため最後。
for rt in Organization Location Practitioner PractitionerRole Patient Coverage \
          Encounter Condition AllergyIntolerance Immunization FamilyMemberHistory \
          MedicationRequest MedicationAdministration Observation DiagnosticReport \
          Procedure ImagingStudy Endpoint ServiceRequest ClinicalImpression \
          Composition CareTeam DocumentReference
do
    if [ -f "jp-100/fhir_r4/${rt}.ndjson" ]; then
        echo "== Loading ${rt} =="
        while IFS= read -r line; do
            [ -z "$line" ] && continue
            curl -sSf -X POST \
                -H 'Content-Type: application/fhir+json' \
                --data-raw "$line" \
                "${BASE}/${rt}" > /dev/null
        done < "jp-100/fhir_r4/${rt}.ndjson"
    fi
done
```

**大規模コホート — `$import`:**

```bash
# 1. FHIR サーバが取得できるように NDJSON ファイルを HTTP で serve。
#    (本番では pre-signed URL 付きの S3 等のオブジェクトストアを使用。)
python3 -m http.server 9000 --directory jp-100/fhir_r4 &

# 2. import を kick off。
curl -sSf -X POST \
    -H 'Content-Type: application/fhir+json' \
    -H 'Prefer: respond-async' \
    -H 'X-Provenance: {"resourceType":"Provenance","recorded":"2026-07-12T00:00:00Z","reason":[{"coding":[{"system":"http://terminology.hl7.org/CodeSystem/v3-ActReason","code":"HRESCH"}]}],"agent":[{"who":{"identifier":{"value":"clinosim-dataset-loader"}}}]}' \
    "http://localhost:8080/fhir/\$import" \
    --data '{
      "resourceType": "Parameters",
      "parameter": [
        {"name": "inputFormat", "valueCode": "application/fhir+ndjson"},
        {"name": "inputSource", "valueUri": "http://host.docker.internal:9000/"},
        {"name": "storageDetail", "part": [
          {"name": "type", "valueCode": "https"}
        ]},
        {"name": "input", "part": [
          {"name": "type", "valueCode": "Patient"},
          {"name": "url", "valueUri": "http://host.docker.internal:9000/Patient.ndjson"}
        ]},
        {"name": "input", "part": [
          {"name": "type", "valueCode": "Encounter"},
          {"name": "url", "valueUri": "http://host.docker.internal:9000/Encounter.ndjson"}
        ]}
      ]
    }'
```

レスポンスの `Content-Location` ヘッダが import 完了までポーリング
する status エンドポイントを指す:

```bash
STATUS_URL=$(curl -sSD - -X POST "..." | grep -i '^content-location:' | awk '{print $2}' | tr -d '\r')
while true; do
    curl -sSI "$STATUS_URL"    # 202 = 進行中、200 = 完了、4xx/5xx = 失敗
    sleep 5
done
```

### 3. 検証

```bash
BASE=http://localhost:8080/fhir

# Patient カウント — プリセット population と一致するはず。
curl -s "${BASE}/Patient?_summary=count" | jq '.total'

# 生理由来の PT-INR observation を取得。
curl -s "${BASE}/Observation?category=laboratory&code=6301-6&_count=1" \
    | jq '.entry[0].resource | {id, valueQuantity, interpretation}'

# JP Core プロファイル宣言が round trip を生き残ったことを確認。
curl -s "${BASE}/Patient?_count=1" \
    | jq '.entry[0].resource.meta.profile'
```

## Option B — 他の FHIR R4 サーバ

FHIR R4 Bulk Data Access
[`$import`](https://hl7.org/fhir/uv/bulkdata/OperationDefinition-import.html)
オペレーションをサポートする任意のサーバが同じ NDJSON ペイロードを
受け付けます。例:

- **HAPI FHIR** (OSS リファレンス、上で walk-through 済み)。
- **Microsoft FHIR Server** (Azure API for FHIR)。
- **Google Cloud Healthcare API FHIR store**。
- **InterSystems IRIS for Health FHIR Server** — `$import` サポート;
  ベンダードキュメント参照。これは準拠サーバの例として挙げているの
  であり、必須依存ではありません。

サーバが `$import` を実装していない場合、Option A のファイル別
POST アプローチはどこでも動作しますが wire オーバーヘッドが高くなり
ます。

## トラブルシューティング

### Reference integrity エラー

症状: `Invalid reference: Patient/… — no such resource`。

原因: `Encounter` が参照する `Patient` より前にロードされた、または
NDJSON ファイルが依存順ではなくファイルシステム順で ingested された。

修正: 上の loop の順序でロード (`Organization` と `Patient` を最初、
次に `Encounter`、その後 `Encounter` を参照する全て)。`$import` の
場合、`Parameters.parameter[].part[]` エントリを同じ順序でリスト
アップ — HAPI の importer は順序を尊重。

### JP Core プロファイル検証失敗

症状:
`MalformedResourceException: does not conform to profile
http://jpfhir.jp/fhir/core/StructureDefinition/JP_Patient`。

原因: ターゲットサーバに JP Core StructureDefinition リソースが
ロードされていないので、`meta.profile` に JP Core プロファイルを
宣言するあらゆるリソースで検証が失敗する。

修正: いずれか

- ingest サーバで strict profile validation を無効化 (smoke test
  最速);
- または <https://jpfhir.jp/fhir/core/> から JP Core プロファイル
  パックをサーバの terminology store にプリロード。

### Import job が stall

症状: status URL のポーリングが進捗なしに `202 Accepted` を返し続ける。

原因: FHIR サーバが `input[].url` の URL に到達できない — 通常、
Linux 上のコンテナ内から Docker の `host.docker.internal` が到達
不能なため (macOS / Windows では初期状態で動作)。

修正: Linux では HAPI を起動する `docker run` コマンドに
`--add-host=host.docker.internal:host-gateway` を追加し、import を
再実行。

### Ingestion 後の決定性チェック

ingest したコホートがソースの tarball とバイト単位で一致 (round
trip) することを検証したい場合、エクスポートして diff:

```bash
curl -sSf "${BASE}/Patient?_count=99999&_format=ndjson" > exported/Patient.ndjson
# (resourceType ごとに繰り返し、元と sha256sum を比較)
```

エクスポート後の NDJSON の行順序はサーバ依存なので、diff 前に sort:

```bash
sort exported/Patient.ndjson > exported/Patient.sorted.ndjson
sort jp-100/fhir_r4/Patient.ndjson > original/Patient.sorted.ndjson
diff original/Patient.sorted.ndjson exported/Patient.sorted.ndjson
```

## 関連

- [FHIR R4 Bulk Data Access spec](https://hl7.org/fhir/uv/bulkdata/)
- [HAPI FHIR docs](https://hapifhir.io/hapi-fhir/docs/)
- [jpfhir.jp — JP Core FHIR プロファイル](https://jpfhir.jp/fhir/core/)
- clinosim [Reproducibility](development/reproducibility.md) — 何か
  を ingest する前にソースコホートのバイト同一性を検証。
- clinosim [Evaluation](eval.ja.md) — ingest 前に `clinosim eval` で
  ソースコホートを採点することで、決定性 / 臨床 / locale に関する
  発見を、サーバのせいにする前に up-front で調査する。
