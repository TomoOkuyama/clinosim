<!-- README.md から抽出 (Issue #568 PR A2)。本ファイルの見出しが変更されたら README のポインタを更新。 -->

# モジュール依存グラフ

```mermaid
flowchart TD
    codes["codes<br/>(国際コードシステム)"]
    locale["locale<br/>(国別)"]
    output["output<br/>(FHIR / CIF / CSV)"]
    patient["patient activator"]
    encounter["encounter"]
    disease["disease (YAML)"]
    facility["facility (queue)"]
    population["population"]
    staff["staff"]
    healthcare["healthcare_system"]
    identity["identity<br/>(JP 保険、opt-in)"]

    subgraph loop["daily simulation loop"]
        cc["clinical_course"] --> phys["physiology"]
        phys --> obs["observation"]
        phys --> dx["diagnosis"]
        dx --> cc
        obs --> proc["procedure + MAR"]
        dx --> order["order"]
        order --> proc
    end

    codes -->|lookup| output
    locale --> output
    locale --> patient
    patient --> encounter
    encounter --> loop
    disease --> loop
    facility --> loop
    loop --> output
    population --> disease
    population --> facility
    population --> staff
    healthcare --> staff
    population --> identity
    identity --> output
```

`llm_service` と `validator` は cross-cutting (専用フェーズで使用)。
`identity` は opt-in enricher (AD-54): enricher registry (AD-56) 経由
の post-population pass として走行、そのデータは `output` が FHIR
`Coverage` として emit。

詳細は各モジュールの `clinosim/modules/<module>/README.md` 参照。

---
