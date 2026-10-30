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
AllergyIntolerance.ndjson    DocumentReference.ndjson     Observation.ndjson
CareTeam.ndjson              Encounter.ndjson             Organization.ndjson
ClinicalImpression.ndjson    Endpoint.ndjson              Patient.ndjson
Composition.ndjson           FamilyMemberHistory.ndjson   Practitioner.ndjson
Condition.ndjson             ImagingStudy.ndjson          PractitionerRole.ndjson
Coverage.ndjson              Immunization.ndjson          Procedure.ndjson
Device.ndjson                Location.ndjson              ServiceRequest.ndjson
DeviceUseStatement.ndjson    MedicationAdministration.ndjson  Specimen.ndjson
DiagnosticReport.ndjson      MedicationRequest.ndjson
manifest.json
```

実際のファイル集合はコホートで発火するモジュールに依存する —
`DeviceUseStatement.ndjson` (と患者ごとの `Device` 行) は ICU 転棟
した入院患者に CVC / 留置カテーテル / 人工呼吸器が使われた時のみ emit
(`Device.ndjson` には施設共用の輸液ポンプが常に含まれる)、
`Specimen.ndjson` は 微生物培養 encounter chain が発火した時のみ emit。

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
    -e hapi.fhir.enforce_referential_integrity_on_write=false \
    hapiproject/hapi:latest
```

`enforce_referential_integrity_on_write=false` は、まだロードされて
いないリソースへの reference をサーバに受け付けさせる設定です。
clinosim の出力は、どの順序でロードしても前方参照が残るため、この
設定が必要です ([ロード順だけでは足りない理由](#ロード順だけでは足りない理由) 参照)。

health probe がサーバの起動を報告するまで待機:

```bash
until curl -sf http://localhost:8080/fhir/metadata > /dev/null; do sleep 2; done
echo "HAPI FHIR ready at http://localhost:8080/fhir"
```

### 2. NDJSON ファイルを push

clinosim のリソースは互いを clinosim 自身の id
(`Encounter/enc-…`、`Patient/pt-…`) で参照します。すべてのリソースを
`PUT [base]/[type]/[id]` でロードし、サーバに同じ id で保存させて
ください。`[base]/[type]` への `POST` は **使わない** でください:
create はサーバ側で新しい id を割り当てるため、元の id への reference
がすべて解決できなくなります。

まだ存在しない id への `PUT` はリソースを作成します ("update as
create")。サーバがクライアント指定 id を許可している必要があります。
HAPI FHIR は数字だけでない id ならデフォルトで許可しており、clinosim
の id はすべてこれに該当します。各 NDJSON 行の `id` は URL と一致して
おり、FHIR が `PUT` に求める条件を満たしています。

**小規模コホート — リソースごとに 1 回 `PUT` (update-as-create を
サポートする任意の FHIR R4 サーバで動作):**

```bash
BASE=http://localhost:8080/fhir
SRC=jp-100/fhir_r4

# clinosim が emit しうる全リソース型を、大半の reference が既にロード
# 済みのリソースを指す順序で並べたもの。コホートが生成しなかった型は
# skip される。
for rt in Organization Endpoint Practitioner Location PractitionerRole \
          Patient Coverage Device Encounter Condition AllergyIntolerance \
          FamilyMemberHistory Immunization ServiceRequest Specimen Observation \
          ImagingStudy DiagnosticReport MedicationRequest MedicationAdministration \
          Procedure DeviceUseStatement ClinicalImpression CareTeam \
          DocumentReference Composition
do
    [ -f "${SRC}/${rt}.ndjson" ] || continue
    echo "== Loading ${rt} =="
    while IFS= read -r line; do
        [ -z "$line" ] && continue
        id=$(printf '%s' "$line" | jq -r '.id')
        printf '%s' "$line" | curl -sSf -X PUT \
            -H 'Content-Type: application/fhir+json' \
            --data-binary @- \
            "${BASE}/${rt}/${id}" > /dev/null
    done < "${SRC}/${rt}.ndjson"
done
```

上のリストは FHIR writer が emit しうる 26 リソース型すべてを含み
ます。コホートに loop が skip する型が無いことは `manifest.json` と
突き合わせて確認できます:

```bash
jq -r '.output[].type' "${SRC}/manifest.json" | sort
```

**中規模コホート — `PUT` エントリの transaction Bundle:** リソース
ごとではなく chunk ごとに 1 回の HTTP 往復で済みます。各エントリは
`request.method = PUT` と `request.url = [type]/[id]` を持つため、
上の loop と同じく id はそのまま保たれます。

```bash
for rt in Organization Endpoint Practitioner Location PractitionerRole \
          Patient Coverage Device Encounter Condition AllergyIntolerance \
          FamilyMemberHistory Immunization ServiceRequest Specimen Observation \
          ImagingStudy DiagnosticReport MedicationRequest MedicationAdministration \
          Procedure DeviceUseStatement ClinicalImpression CareTeam \
          DocumentReference Composition
do
    [ -f "${SRC}/${rt}.ndjson" ] || continue
    echo "== Loading ${rt} =="
    # 1 transaction あたり 500 リソース
    jq -c -n --arg rt "$rt" '
        def chunks(n): [inputs] | range(0; length; n) as $i | .[$i:$i+n];
        chunks(500)
        | {resourceType: "Bundle", type: "transaction",
           entry: [ .[] | {resource: .,
                           request: {method: "PUT", url: "\($rt)/\(.id)"}} ]}
    ' "${SRC}/${rt}.ndjson" |
    while IFS= read -r bundle; do
        printf '%s' "$bundle" | curl -sSf -X POST \
            -H 'Content-Type: application/fhir+json' \
            --data-binary @- \
            "${BASE}" > /dev/null
    done
done
```

transaction はサーバの base に送信します (`POST [base]`)。これは
Bundle を送る標準の方法であり、内部の `PUT` エントリに新しい id を
割り当てることはありません。

#### ロード順だけでは足りない理由

上の順序は大半の reference 先を先にロードしますが、clinosim の出力
には必ず前方を指す reference が含まれます:

- `Encounter.diagnosis.condition` と `Encounter.reasonReference` は
  `Condition` を指し、`Condition.encounter` は `Encounter` を指し
  返す — 両方を満たす順序は存在しません。
- 同一ファイル内でも、`Location.partOf`・`Organization.partOf`・
  `DocumentReference.relatesTo.target` が同じファイルの後方の行を
  指すことがあります。

したがってサーバは、まだ存在しないリソースへの reference を受け付け
る必要があります。HAPI FHIR では
`hapi.fhir.enforce_referential_integrity_on_write=false` (上の
`docker run` で設定済み)、他のサーバではロード中だけ同等の書き込み
時 reference チェックを無効にしてください。全ファイルのロードが終わ
れば、すべての reference が解決します。

**大規模コホート — `$import`:**

Bulk Data `$import` は NDJSON ファイルを直接読み込み、各行の `id` を
保持するため、`PUT` と同じく reference が解決します。`input` はファ
イルごとに 1 つ並べます。下の例はそのうち 2 つだけを示しています —
全リストは `manifest.json` から生成してください (例:
`jq '[.output[] | {name: "input", part: [{name: "type", valueCode: .type}, {name: "url", valueUri: ("http://host.docker.internal:9000/" + .url)}]}]' jp-100/fhir_r4/manifest.json`)。

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

サーバが `$import` を実装していない場合、Option A の `PUT` による
手法 (リソースごとの 1 リクエスト、または `PUT` エントリの
transaction Bundle) は update-as-create をサポートする任意のサーバ
で動作しますが、wire オーバーヘッドが高くなります。

## トラブルシューティング

### Reference integrity エラー

症状: `Invalid reference: Patient/… — no such resource`、または
(HAPI FHIR) `Encounter` のロード中に `HAPI-1094: Resource
Condition/… not found, specified in path: Encounter.reasonReference`。

原因: サーバが書き込み時に reference をチェックしており、ロード中の
リソースがまだロードされていないリソースを指している。このような
前方参照の一部は避けられない
([ロード順だけでは足りない理由](#ロード順だけでは足りない理由) 参照)。

修正: ロード中は書き込み時の reference チェックを無効にし (HAPI FHIR
では `hapi.fhir.enforce_referential_integrity_on_write=false`)、上の
loop の順序でロードする。以後の書き込みでチェックが必要なら、ロード
後に再度有効にする。

### reference が存在しない id を指す

症状: ロードは成功するが、`Encounter?subject=Patient/pt-…` などの
検索が何も返さない、または reference が未解決として表示される。

原因: リソースが `POST [base]/[type]` で作成されたため、サーバが新し
い id を割り当て、reference 中の clinosim の id がどれとも一致しなく
なった。

修正: ロードしたデータを削除し、上に示した
`PUT [base]/[type]/[id]` (または `PUT` エントリの transaction
Bundle) でロードし直す。

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
- clinosim [Reproducibility](development/reproducibility.ja.md) — 何か
  を ingest する前にソースコホートのバイト同一性を検証。
- clinosim [Evaluation](eval.ja.md) — ingest 前に `clinosim eval` で
  ソースコホートを採点することで、決定性 / 臨床 / locale に関する
  発見を、サーバのせいにする前に up-front で調査する。
