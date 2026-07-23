# Project

Youtube AI Automation

このプロジェクトは、AIを利用してYouTube動画を自動生成するPythonアプリケーションです。

目的は

テーマ
→ 台本
→ 音声
→ 画像
→ 字幕
→ 動画
→ エンディング
→ メタデータ
→ サムネイル
→ YouTube投稿

までを自動化することです。

---

# 開発方針

最優先事項

- 既存機能を壊さない
- 後方互換性を維持する
- 大規模リファクタリングは禁止
- 変更範囲は必要最小限
- 推測で実装しない
- 実コードを確認してから修正する

---

# アーキテクチャ

基本構成

Provider
↓
Manager
↓
Pipeline
↓
Renderer

Providerを直接利用するコードを増やさないこと。

ProviderはFactoryまたはPluginManager経由で取得すること。

---

# Provider構造

利用しているProvider

Text Provider
TTS Provider
Image Provider
Alignment Provider（stable-ts）

新しいProviderを追加する場合は既存インターフェースを利用すること。

動画生成PipelineへProvider固有処理を書かないこと。

---

# TTS

既定

VOICEVOX

OpenAI TTSは削除しない。

config.yamlから切り替える。

VOICEVOX固有処理は

VOICEVOXTTSProvider

へ閉じ込める。

---

# 字幕

字幕は

Scene
↓
SubtitleSegment
↓
SRT
↓
FFmpeg

で生成する。

Scene=字幕ではない。

SubtitleSegmentを利用する。

字幕は

- 最大2行
- 最大文字数を守る
- 画面下部
- semantic分割

を基本とする。

---

# 字幕タイミング

優先順位

stable-ts
↓

character_ratio

stable-ts失敗時でも動画生成は停止しない。

alignment.jsonをキャッシュすること。

---

# stable-ts

Whisperは利用しない。

WhisperXも利用しない。

既知の台本を利用したalignmentのみ行う。

生成するファイル

sceneNN.alignment.json（例: scene01.alignment.json。sceneNN.mp3と同じ2桁採番）

SubtitleSplitterが分割したSubtitleSegmentへ、alignment.jsonのタイミングを反映する。

---

# キャッシュ

非常に重要。

設定変更時は必要最小限のみ再生成すること。

例

title_prompt変更

↓

タイトルのみ再生成

TTS変更

↓

音声
字幕
動画

のみ再生成

字幕設定変更

↓

字幕・動画のみ再生成

BGM変更

↓

render_mode: final_mixの場合はfinal_renderのみ再生成
render_mode: per_sectionの場合は本編動画（video.mp4）を再生成

不要な再生成は禁止。

---

# テンプレート

テンプレートごとの差分は

templates/<template>

のみで表現する。

コード側でジャンル分岐を書かない。

設定は

default
↓

template

の順でマージする。

---

# 設定

config.yaml

が基本設定。

テンプレートはvideo.yamlで上書きする。

新しい設定は

config.yaml

と

video.yaml

両方対応すること。

---

# エンディング

テンプレートごとに共通。

素材・TTS（音声合成）設定・text（台本生成）設定・BGM/字幕設定の変更時に再生成する。
テンプレート別VOICEVOX上書きも本編と同様に適用される。

本編とは独立してキャッシュする。

字幕表示は

ending.subtitles.enabled

で制御する。

---

# BGM

render_mode

- per_section
- final_mix

両方壊さないこと。

BGM変更時の再生成範囲はrender_modeに依存する。

final_mix: final_renderのみ
per_section: 本編動画（video.mp4）

---

# ログ

Loggerを利用する。

printは禁止。

DEBUGログ以外へ大量データを書かない。

---

# エラー処理

例外を握りつぶさない。

ユーザーが原因を理解できるメッセージを返す。

---

# テスト

pytest必須。

追加機能には

- unit
- integration

を追加する。

通常テストでは

OpenAI
VOICEVOX
YouTube
BFL

など外部APIは呼ばない。

Mockを利用する。

実APIテストは

external

マーカーを利用する。

---

# Git

勝手に

commit
push
branch作成

しない。

ユーザーが明示した場合のみ行う。

---

# YouTube

upload_enabled=false

を変更しない。

勝手に動画投稿しない。

---

# API

API料金が発生する処理は

ユーザーの明示的な指示なしに実行しない。

---

# Assets

assetsフォルダ内の素材は削除・変更しない。

素材が存在しない場合は生成せずユーザーへ確認する。

---

# Windows

Windows環境を優先する。

PowerShellで動作すること。

FFmpegはPATHから利用する。

---

# コーディング規約

- 型ヒントを付ける
- dataclassまたはPydanticを利用する
- マジックナンバー禁止
- コメントは理由を書く
- 命名は既存コードに合わせる
- 不要な依存ライブラリを追加しない

---

# 実装前

実装前に必ず

1. 関連コードを読む
2. データフローを確認
3. 影響範囲を確認

してから修正すること。

---

# 実装後

必ず報告する。

- 変更ファイル
- 実装内容
- テスト結果
- 既存機能への影響
- 未確認事項

推測は禁止。

確認できない場合は

「未確認」

と記載すること。

---

# 関連ドキュメント

作業時はこのファイルに加えて以下も参照すること。

- [TASKS.md](TASKS.md) — 今後実装予定のタスク一覧
- [DECISIONS.md](DECISIONS.md) — 技術選定の理由・設計意図
- [CONTRIBUTING.md](CONTRIBUTING.md) — Git運用ルール