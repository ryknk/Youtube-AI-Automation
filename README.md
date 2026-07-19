# Youtube AI Automation

## Testing

Install development dependencies and run tests without calling any external API:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m pytest -m unit
.\.venv\Scripts\python.exe -m pytest -m integration
.\.venv\Scripts\python.exe -m pytest -m "not slow"
```

Coverage reports are available with:

```powershell
.\.venv\Scripts\python.exe -m pytest --cov=youtube_generator --cov-report=term-missing
.\.venv\Scripts\python.exe -m pytest --cov=youtube_generator --cov-report=html
```

`MockTextGenerator`, `MockTTSProvider`, `MockImageProvider`, and `MockYouTubeUploader` are used for ordinary tests. Tests marked `external` are skipped unless `RUN_EXTERNAL_TESTS=true` is set explicitly.

## YouTube upload

Uploads are separate from video generation and require an explicit command. `youtube.upload_enabled` defaults to `false` in `config/config.yaml`; change it to `true` only after reviewing the target account and video.

1. In Google Cloud Console, create a project, enable **YouTube Data API v3**, and create an OAuth 2.0 Desktop application client.
2. Download the client JSON as `client_secret.json` in the project root. It is ignored by Git.
3. Run `python main.py youtube auth` once and complete the browser authorization. The resulting `youtube_token.json` is also ignored by Git.

```powershell
python main.py youtube upload <job_id>
python main.py youtube upload <job_id> --privacy private
python main.py youtube schedule <job_id> --publish-at "2026-08-01T19:00:00+09:00"
python main.py youtube status <job_id>
```

Supported privacy values are `private`, `unlisted`, and `public`; the default is `private`. The command displays the upload details and asks for `Continue? [y/N]`. Only `--yes` skips that prompt. Upload history is stored in `data/jobs.db`, and a second upload for the same job is rejected unless `--force` is supplied.

## Job queue

Jobs are stored in `data/jobs.db` and their artifacts are stored under `output/<genre>/<job_id>_<theme>/`.

```powershell
python main.py queue add "宇宙の雑学" --template trivia
python main.py queue import topics.csv
python main.py queue list
python main.py queue status
python main.py queue run
python main.py queue retry <job_id>
python main.py queue cancel <job_id>
```

CSV files use `theme,template` headers. JSON files use an array of objects with `theme` and `template` fields. Jobs are executed one at a time in registration order. `queue.stop_on_error: false` lets later jobs continue after a failure.

## Templates

Genre templates are stored under `templates/<template_id>/`. Every template contains `prompt.txt`, `image_prompt.txt`, `title_prompt.txt`, `thumbnail_prompt.txt`, and `video.yaml`.

```powershell
python main.py --theme "宇宙の不思議" --template science
python main.py --theme "織田信長" --template history
```

If `--template` is omitted, `default` is used. Bundled templates are `default`, `zatsugaku`, `history`, `toshidensetsu`, `psychology`, and `science`.

## Plugin architecture

Provider implementations live in `src/youtube_generator/plugins/`. The video pipeline depends only on the `TextGenerator`, `TTSProvider`, and `ImageProvider` protocols.

```text
plugins/
├── base/       # common protocols
├── text/       # LLM providers
├── tts/        # speech providers
├── image/      # image providers
└── manager.py  # provider factory
```

### Switching providers

Set the selected provider in `config/config.yaml`. OpenAI is used for text and speech, while Black Forest Labs is used for image generation by default.

```yaml
providers:
  text: openai
  tts: openai
  image: bfl
```

Set `OPENAI_API_KEY` and `BFL_API_KEY` in `.env`. Scene images use `flux-2-pro`, and thumbnails use the higher-quality `flux-2-max`. To return image generation to OpenAI, set `providers.image` to `openai`; `image.openai_model` and `image.quality` will then be used.

### Adding a provider

1. Implement the relevant protocol under `plugins/text`, `plugins/tts`, or `plugins/image`.
2. Register its name in `PluginManager`.
3. Select that name in `config.yaml`.

The pipeline itself does not need to change. Plugins can use the common retry, logging, cache, configuration, and `.env` secret-management facilities.

テーマ入力からYouTube動画の素材・動画・メタデータを生成する、Python 3.12向けの自動生成ツールです。現在は開発の土台のみを実装しており、API連携や動画生成はまだ行いません。

## 必要環境

- Python 3.12以上（Python 3.14.6で動作確認済み）
- Windows PowerShell

## セットアップ

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python -m pip install -e .
Copy-Item .env.example .env
```

`.env` にAPIキーなどの設定を記載します。現段階では `OPENAI_API_KEY` は未設定でも起動できます。

## 起動方法

```powershell
python main.py --theme "宇宙の不思議"
```

テーマを指定すると、OpenAI Responses APIで生成した台本を `output/{ジャンル名}/{実行ID}_{入力テーマ}/script.txt` にUTF-8で保存します。ジャンル名にはテンプレートの表示名が使われます。事前に `.env` の `OPENAI_API_KEY` を設定してください。

既存の台本は、GPTに意味単位で最大30シーンへ分割させられます。出力は入力した `script.txt` と同じフォルダの `scene01.txt`、`scene02.txt` のような連番ファイルです。

```powershell
.\.venv\Scripts\youtube-video-generator --split-script output\{ジャンル名}\{実行ID}_{入力テーマ}\script.txt
```

シーンテキストがあるフォルダを指定すると、すべての `sceneNN.txt` を番号順に音声化し、同じフォルダへ `sceneNN.mp3` として保存します。

```powershell
.\.venv\Scripts\youtube-video-generator --generate-audio output\{ジャンル名}\{実行ID}_{入力テーマ}
```

シーンテキストから統一したリアル調の画像プロンプトを作成し、16:9の高品質PNGを生成します。

```powershell
.\.venv\Scripts\youtube-video-generator --generate-images output\{ジャンル名}\{実行ID}_{入力テーマ}
```

台本の内容から、`config/config.yaml` の `image.thumbnail_size` で指定したサイズのサムネイル画像を生成します。

```powershell
.\.venv\Scripts\youtube-video-generator --generate-thumbnail output\{ジャンル名}\{実行ID}_{入力テーマ}
```

出力先は `output\{ジャンル名}\{実行ID}_{入力テーマ}\thumbnail.png` です。

FFmpegに含まれる `ffprobe` を使い、各 `sceneNN.mp3` の再生時間に対応したSRT字幕を生成します。FFmpegをPATHへ追加してから実行してください。

```powershell
.\.venv\Scripts\youtube-video-generator --generate-subtitles output\{ジャンル名}\{実行ID}_{入力テーマ}
```

出力先は `output\{ジャンル名}\{実行ID}_{入力テーマ}\subtitles.srt` です。

以下が作成・利用されます。

- `output/`: 将来の動画・字幕・音声などの成果物
- `logs/application.log`: 実行ログ

## 構成

- `src/youtube_generator/app/`: 生成フローのユースケース
- `src/youtube_generator/domain/`: ドメインモデル・抽象インターフェース
- `src/youtube_generator/infrastructure/`: API・FFmpeg・ファイル連携
- `src/youtube_generator/services/`: 台本分割・字幕生成などのロジック
- `src/youtube_generator/cli/`: コマンドライン起点
- `tests/`: ユニット・結合テスト

## 設定・品質管理

コードを変更せずに、`config/config.yaml` とテンプレートファイルを編集して挙動を切り替えられます。

- `templates/{テンプレートID}/`: ジャンル別の台本指示、画像・タイトル・サムネイル方針、動画設定
- `config/config.yaml`: モデル、動画、音声、画像、字幕、品質チェック、キャッシュ、アップロードなどの全体設定

テンプレートの確認と品質チェックは、APIなしで実行できます。

```powershell
.\.venv\Scripts\youtube-video-generator --list-templates
.\.venv\Scripts\youtube-video-generator --theme "江戸時代" --template history --script "確認したい台本文"
```

同一のテーマ・テンプレート・動画設定では `.cache/` の中間成果物を再利用する設計です。実行の開始・完了・失敗・キャッシュ利用・品質検査は `logs/run_history.jsonl` に記録されます。`logs/application.log` には詳細なアプリケーションログが残ります。

`services/retry.py` の `retry_on_failure` は、OpenAI・画像生成APIの実装に適用します。`config/config.yaml` の `retry` で、再試行回数と指数バックオフの待機時間を調整できます。

## 今後の実装予定

1. 台本とメタデータの生成
2. シーン分割・音声・画像・字幕の生成
3. FFmpegによるMP4とサムネイルの出力
