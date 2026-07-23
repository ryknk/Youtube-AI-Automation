# TASKS

今後実装予定・検討中のタスク一覧。

- 新しいタスクが見つかった場合はここへ追記する。
- 完了したタスクはこの一覧から削除し、必要であれば[DECISIONS.md](DECISIONS.md)へ経緯を残す。
- 推測で優先度・要否を判断せず、着手前に必ずユーザーへ確認する（[CLAUDE.md](CLAUDE.md)の開発方針に従う）。

---

## 未着手

### YouTubeUploader・OAuthフローのテスト追加

`src/youtube_generator/youtube/uploader.py`の`YouTubeUploader.upload`（`googleapiclient`を使う実処理）と`src/youtube_generator/youtube/auth.py`のOAuthフロー（`InstalledAppFlow.run_local_server`）には、モックを含めた単体テストが存在しない。既存の`MockYouTubeUploader`と`validate_publish_at`のみがテスト対象になっている。

- 対応方針: `googleapiclient`をモック化し、実ネットワーク呼び出しなしでリクエスト内容を検証するテストを追加する。
- 参照: 調査時点(2026-07-23)で確認済み。実装コードパス自体の回帰検知ができない状態。

---

## 検討中（要件が発生するまで着手しない）

### PluginManagerの複数textプロバイダー対応

`create_scene_splitter`/`create_metadata_generator`は`providers.text == "openai"`を前提にした分岐になっており、他のtextプロバイダー実装は存在しない。

- 現状判断: 実装するtextプロバイダーが増えるまでは対応しない（投機的な一般化を避けるため。[DECISIONS.md](DECISIONS.md)参照）。
- 着手条件: 2つ目のtextプロバイダー実装が必要になった場合。

---

## 関連ドキュメント

- [CLAUDE.md](CLAUDE.md) — 開発方針・アーキテクチャ・コーディング規約
- [DECISIONS.md](DECISIONS.md) — 技術選定の理由・設計意図
- [CONTRIBUTING.md](CONTRIBUTING.md) — Git運用ルール
