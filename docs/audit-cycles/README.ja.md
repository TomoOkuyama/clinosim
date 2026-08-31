# CIF/FHIR 監査サイクル — Issue Tracker

このディレクトリは **session 41 以降** clinosim のデフォルトワーク
フローとなった逐次的 CIF/FHIR データ品質監査サイクルを記録する
(session 40 まとめ時のユーザ指示、2026-07-07)。

**Cycle 2 以降: JP first + サイクルあたり 30 issue** (cycle 1 開始時
および mid-fix 時のユーザ指示、2026-07-07)。Cycle 1 は US p=10000 +
JP p=10000 mixed で開始し当初の 20-issue ルールを使用
(grandfathered); cycle 2 以降、生成 / 再生成 / レビューは JP-first
(JP-focused、multi-language アーキテクチャは両 locale で維持) で、
サイクル目標は 30 issue。レビューポイントはデータ品質 / 臨床整合性 /
リアリズムに加えて **日本の医療機関記録としての適切性** と **JP Core
FHIR プロファイル準拠** を優先する。

## ワークフロー (サイクルごと)

1. US p=10000 + JP p=10000 CIF/FHIR を生成 (サイクル 1 回)。
2. NDJSON のグローバルレビュー — FHIR spec 準拠、display フォール
   バック、reference 整合性、spec 違反 datetime、silent-drop、
   統計異常等。**cycle の issue リストに observation を追加する前**
   に [`by-design-registry.md`](by-design-registry.md) を確認 —
   observation が登録された by-design エントリの Signature と一致
   すれば、追加せず `cycle-<N>.md` に 1 行だけ記録:
   `By-design confirmed (see by-design-registry.md#<slug>)`。full-scan
   の記録は保持される。
3. N 患者をランダムサンプル (5–10 推奨) しその患者の全 FHIR resource
   をレビュー (データ品質 / 臨床整合性 / データリアリズム)。同じ
   by-design-registry チェックがここにも適用される。
4. サイクルに対して **正確に 30 issue** が列挙されるまで 2 + 3 を
   繰り返す (by-design 確認は 30 にカウントしない)。
5. 30 issue 全てを fix。**FHIR 整合性の矛盾が追加なしに解決できない
   場合のみ新規追加を行う** (memory `feedback_cif_fhir_quality_focus.md`
   参照)。
6. 同 seed / 集団で CIF/FHIR を再生成。
7. Issue 単位で解決を検証 (resolved / not resolved / newly discovered)。
8. **サイクル終了 fix レビュー** (必須、2026-07-08 ユーザ指示で追加):
   サイクル末に、再生成 + issue 単位検証の後、**さらにサイクル内で
   適用された全 fix をリスク、検証品質、正確性でレビュー**。同 3-axis
   (データ品質 / 臨床整合性 / リアリズム) に加えて新 code / URL /
   mapping には権威ソース検証。docs 更新に進む前に findings をユーザ
   に報告。これは cycle 2 の improvements の mid-cycle 3 レビューを
   ミラーする — このパターンは今後 permanent。
9. **サイクル境界 documentation 更新 + cross-session resume prompt
   記録** (ステップ 10 のユーザプロンプト前に必須):
   - 検証結果 (resolved / carried over / newly discovered) を
     `docs/audit-cycles/cycle-<N>.md` に append。
   - サイクルが新しい durable rule や知識を surfacing した場合は
     memory を更新。
   - warranted な場合は新 FP エントリを
     `docs/design-notes/2026-07-06-fix-point-registry.md` に追加。
   - `.session-resume-prompt.md` を refresh、現サイクル状態 (cycle N
     progress n/20、carry-over リスト、master HEAD、次アクション) が
     別 session の cold-start に十分となるように。
   - GitHub Issues board (`docs/roadmap.ja.md` 参照) 上の該当 META /
     scope issue に現サイクル進捗を反映。旧 `TODO.md` 台帳は Issues 化
     に伴い廃止。
   - 全てを commit + push (clean state で終える)。
10. **次サイクル開始前にユーザに確認** — 解決状況 + carry-over count
    + doc 更新結果を報告。自動継続は禁止。
11. 未解決 issue は次サイクル冒頭リストに carry over; その後レビュー
    + サンプリングを進めそのサイクル合計 30 issue に達する。
    **★ サイクル内 carry-over 判断はユーザ同意なしに禁止**
    (2026-07-08 追加)。fix がサイクル内に land できない場合、
    within-cycle 試行するか defer するかをユーザに確認 — 静かに
    次サイクルリストに移動しない。

## 進捗表示 (fix 中は必須)

各 fix ステップで `[Cycle N · n/30] <short description>` を表示、
ユーザが常にサイクル番号 + 進捗を見られるように。サイクル末サマリは
resolved X / carried-over Y / newly discovered Z を表示。

## 判断優先度

1. **データ品質** — FHIR spec 準拠、display フォールバックゼロ、
   reference 整合性。
2. **臨床整合性** — 値の生理学的妥当性、時間整合性、疾患 → workup
   → treatment 因果関係。
3. **データリアリズム** — 統計分布、rare-event incidence、臨床
   プラクティス現実との一致。

## サイクルごとの記録

各サイクルは `cycle-<N>.md` の独自ファイルを持ち以下を含む:

- サイクル番号、開始日、サイクル開始時の master HEAD。
- 生成コマンド、seed、出力パス。
- **Issue リスト (30 件)** — 各 id、要約、検出パス、サンプルデータ
  or コード、影響、カテゴリ (FHIR spec / 臨床 / リアリズム /
  silent-drop / 等)。
- **Fix 内容** — commit hash、変更要約、および (issue ごとに) 解決
  アプローチを選ぶ前に検討した代替案。
- **検証結果** — 次サイクル冒頭に append: どの issue が close された
  か、どれが carry-over したか、どの新 issue が surfacing したか。

## Index

_(サイクル進行に伴い populate される — session 41 が cycle 1 を開く)_

- [Cycle 1](cycle-1.md) — CLOSED 2026-07-07 (session 41): 20 issue
  対応 (13 resolved / 5 not-a-bug / 2 carry-over to cycle 2)。
  US p=10000 + JP p=10000 監査; 検証用に JP p=10000 再生成。
- Cycle 2 — 未開始。Carry-over: C1-09 rules 拡張、
  C1-10 ImagingStudy density、C1-18 JP chronic conditions 根本原因。

## 関連文書

- `docs/design-notes/2026-07-06-fix-point-registry.md` — session 38
  FP-* registry (この監査サイクルワークフロー以前の completeness
  作業からの背景)。
- `docs/design-guides/data-model-and-completeness-conventions.md` —
  codebase 横断で共有される C1/C2/C3 completeness convention。
- Memory `feedback_audit_cycle_workflow.md` — durable ワークフロー
  ルール。
- Memory `feedback_cif_fhir_quality_focus.md` — cycle 5 (fix) 判断を
  gate する「厳密に required な場合のみ追加」ルール。
