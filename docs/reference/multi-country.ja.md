<!-- README.md から抽出 (Issue #568 PR A2)。本ファイルの見出しが変更されたら README のポインタを更新。 -->

# 多国対応

| 項目 | US (デフォルト) | JP (`--country JP`) |
| --- | --- | --- |
| 診断コード | ICD-10-CM | ICD-10 (WHO) |
| 検査コード | LOINC | JLAC10 |
| 薬剤コード | RxNorm | YJ codes |
| 手技コード | CPT | K codes |
| Display 言語 | 英語 | 日本語 (英語フォールバック) |
| 患者氏名 | 英語 | 漢字 + カナ拡張 |
| 住所 | マサチューセッツ州 (人口加重の 15 市町) | 東京近郊 (東京都 / 埼玉県 / 神奈川県 / 千葉県)。都道府県コードは JIS X 0401 |
| 検査 reference range | Tietz/Mayo | JCCLS Reference Intervals 2022 |
| Marital status | HL7 v3 (S/M/D/W) | 同じ |
| 言語 | en-US | ja-JP |

---
