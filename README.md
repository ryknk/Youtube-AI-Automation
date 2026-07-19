# Youtube AI Automation

**Youtube AI Automation**は、テーマから台本、シーン音声、画像、字幕、動画、メタデータ、サムネイルを生成するPythonアプリケーションです。ジョブキューによる一括実行と、明示操作によるYouTube投稿にも対応しています。

## 必要環境

- Python 3.12以上
- FFmpeg（`ffmpeg`と`ffprobe`をPATHへ追加）
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

`.env`へ次のAPIキーを設定します。

```dotenv
OPENAI_API_KEY=
BFL_API_KEY=
```

OpenAIは台本・シーン分割・音声・メタデータ生成、Black Forest Labsは画像生成に使用します。ログレベルなど、APIキー以外の環境固有設定も`.env`で管理します。

## 設定

実行設定は[config/config.yaml](config/config.yaml)へ集約されています。主な項目は次のとおりです。

- 動画：`1920×1080`、30fps
- シーン画像：FLUX.2 Pro、`1920×1080`
- サムネイル：FLUX.2 Max、`1280×720`
- 最大シーン数：30
- 音声、字幕、BGM、品質検査、キャッシュ、リトライ
- YouTubeの公開範囲とアップロード許可

ジャンルごとの台本・画像・タイトル・サムネイル方針は`templates/<template_id>/`で管理します。各テンプレートには`prompt.txt`、`image_prompt.txt`、`title_prompt.txt`、`thumbnail_prompt.txt`、`video.yaml`があります。

利用可能なテンプレートは次のコマンドで確認できます。

```powershell
python main.py --list-templates
```

## ジョブキューで動画を生成する

```powershell
python main.py queue add "宇宙の雑学" --template science
python main.py queue run
python main.py queue status
```

ジョブは登録順に1件ずつ処理されます。成果物は次の構成で保存されます。

```text
output/<ジャンル名>/<実行ID>_<テンプレート名>_<入力テーマ>/
├── script/
├── audio/
├── images/
├── subtitle/
├── video/
├── thumbnail/
├── metadata/
└── quality_report/
```

その他のキュー操作：

```powershell
python main.py queue import topics.csv
python main.py queue list
python main.py queue retry <job_id>
python main.py queue cancel <job_id>
```

CSVは`theme,template`ヘッダー、JSONは`theme`と`template`を持つオブジェクトの配列を使用します。

## 工程ごとに実行する

台本生成：

```powershell
python main.py --theme "宇宙の不思議" --template science
```

生成された台本は`output/<ジャンル名>/<実行ID>_<テンプレート名>_<入力テーマ>/script.txt`へ保存されます。以降は同じ作業フォルダを指定して各工程を実行します。

```powershell
python main.py --split-script <作業フォルダ>\script.txt --template science
python main.py --generate-audio <作業フォルダ> --template science
python main.py --generate-images <作業フォルダ> --template science
python main.py --generate-subtitles <作業フォルダ> --template science
python main.py --generate-video <作業フォルダ> --template science
python main.py --generate-metadata <作業フォルダ> --template science
python main.py --generate-thumbnail <作業フォルダ> --template science
```

同じ入力と設定で生成した中間成果物は`cache/`から再利用されます。工程イベントは`logs/run_history.jsonl`、実行ごとの集計は`output/history.json`、アプリケーションログは`logs/application.log`へ保存されます。

## YouTubeへ投稿する

動画生成と投稿は分離されており、投稿は明示した場合だけ実行されます。

1. Google Cloud ConsoleでYouTube Data API v3を有効化します。
2. OAuth 2.0デスクトップアプリの認証情報を作成します。
3. クライアントJSONをプロジェクト直下の`client_secret.json`へ保存します。
4. `python main.py youtube auth`を実行して認証します。
5. `config/config.yaml`の`youtube.upload_enabled`を`true`へ変更します。

```powershell
python main.py youtube upload <job_id>
python main.py youtube upload <job_id> --privacy private
python main.py youtube schedule <job_id> --publish-at "2026-08-01T19:00:00+09:00"
python main.py youtube status <job_id>
```

公開範囲は`private`、`unlisted`、`public`です。投稿前には確認が表示され、`--yes`を付けた場合だけ省略されます。同じジョブを再投稿する場合は`--force`が必要です。

## 画像プロバイダーをOpenAIへ戻す

既定の画像プロバイダーはBFLです。OpenAIへ切り替える場合は`config/config.yaml`を次のように変更します。

```yaml
providers:
  image: openai
```

この場合は`image.openai_model`と`image.quality`が使用されます。

## テスト

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest
python -m pytest -m unit
python -m pytest -m integration
python -m pytest --cov=youtube_generator --cov-report=term-missing
```

通常のテストでは外部APIを呼び出しません。`external`マーカー付きテストは、`RUN_EXTERNAL_TESTS=true`を明示した場合だけ実行されます。

## ソース構成

- `src/youtube_generator/app/`：生成フローのユースケース
- `src/youtube_generator/domain/`：ドメインモデル
- `src/youtube_generator/infrastructure/`：API、FFmpeg、永続化
- `src/youtube_generator/plugins/`：テキスト、音声、画像プロバイダー
- `src/youtube_generator/services/`：品質検査や補助処理
- `src/youtube_generator/jobs/`：ジョブキューと一括生成
- `src/youtube_generator/youtube/`：YouTube投稿
- `tests/`：ユニット・結合テスト
