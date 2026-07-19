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

Windows PowerShell 5.1では、すべてのコマンドを`run.cmd`経由で実行します。このラッパーは内部の`run.ps1`を実行し、PythonとPowerShellの文字コードを一時的にUTF-8へ揃え、標準出力と標準エラーを`Out-Host`へ渡します。処理後は元の文字コード設定へ戻るため、プロンプト位置の乱れと文字化けを共通して防止できます。PowerShellの実行ポリシーを変更する必要はありません。

PowerShell 7など、問題が発生しない環境では`python main.py`またはセットアップ時に登録される`youtube-ai-automation`コマンドも使用できます。

## テンプレート機能

テンプレートは、動画ジャンルごとの生成方針とシーン構成を切り替える機能です。`--template <テンプレートID>`で選択し、省略時は`default`が使用されます。

```powershell
.\run.cmd --theme "宇宙の不思議" --template science
```

同梱テンプレート：

| テンプレートID | 表示名 | 主な用途 |
| --- | --- | --- |
| `default` | Default | 汎用 |
| `zatsugaku` | 雑学 | 雑学・豆知識 |
| `history` | 歴史 | 歴史上の人物・出来事 |
| `toshidensetsu` | 都市伝説 | 噂・都市伝説の紹介と検証 |
| `psychology` | 心理学 | 心理学の解説と実践例 |
| `science` | 科学 | 科学知識・現象の解説 |

`trivia`は`zatsugaku`、`urban_legend`は`toshidensetsu`の別名としても使用できます。利用可能なテンプレートは次のコマンドで確認できます。

```powershell
.\run.cmd --list-templates
```

テンプレートは`templates/<テンプレートID>/`に配置し、次の5ファイルで構成します。

| ファイル | 用途 |
| --- | --- |
| `prompt.txt` | 台本の文体、内容、構成に関する指示 |
| `image_prompt.txt` | シーン画像の画風と表現方針 |
| `title_prompt.txt` | タイトル・概要欄・タグの生成方針 |
| `thumbnail_prompt.txt` | サムネイルの構図と表現方針 |
| `video.yaml` | 表示名とシーン構成 |

新しいテンプレートを追加する場合は、既存フォルダを複製して上記ファイルを編集します。`video.yaml`には少なくとも表示名とシーン構成を指定してください。

```yaml
display_name: 料理
scene_structure: [導入, 材料, 調理手順, まとめ]
```

フォルダ名が`cooking`の場合は、`--template cooking`で選択できます。`display_name`はジャンル名として出力フォルダの階層に使用されます。

## ジョブキューで動画を生成する

```powershell
.\run.cmd queue add "宇宙の雑学" --template science
.\run.cmd queue run
.\run.cmd queue status
```

ジョブは登録順に1件ずつ処理されます。成果物は次の構成で保存されます。

```text
output/<ジャンル名>/<実行ID>_<入力テーマ>/
├── script/
├── audio/
├── images/
├── subtitle/
├── video/
├── thumbnail/
├── metadata/
└── quality_report/
```

ジャンル別の階層を使用しない`output/jobs`直下へ保存する場合は、`output/jobs/<実行ID>_<ジャンル名>_<入力テーマ>/`という形式になります。

その他のキュー操作：

```powershell
.\run.cmd queue import topics.csv
.\run.cmd queue list
.\run.cmd queue retry <job_id>
.\run.cmd queue cancel <job_id>
.\run.cmd queue delete <job_id>
.\run.cmd queue clear
.\run.cmd queue clear --yes
```

CSVは`theme,template`ヘッダー、JSONは`theme`と`template`を持つオブジェクトの配列を使用します。

`queue list`と`queue status`は1ジョブを1行で表示します。これらを含むすべてのコマンド出力は`run.ps1`内部で`Out-Host`へ渡されます。

## キューを使わずに1件実行する

キューを使用しない場合は、対象動画の各工程を順番に実行します。まず台本を生成します。

```powershell
.\run.cmd --theme "宇宙の不思議" --template science
```

生成された台本は`output/<ジャンル名>/<実行ID>_<入力テーマ>/script.txt`へ保存されます。直前に作成されたフォルダをPowerShell変数へ設定し、残りの工程を実行します。

```powershell
$workDir = (Get-ChildItem output\科学 -Directory | Sort-Object LastWriteTime -Descending | Select-Object -First 1).FullName

.\run.cmd --split-script "$workDir\script.txt" --template science
.\run.cmd --generate-audio "$workDir" --template science
.\run.cmd --generate-images "$workDir" --template science
.\run.cmd --generate-subtitles "$workDir" --template science
.\run.cmd --generate-video "$workDir" --template science
.\run.cmd --generate-metadata "$workDir" --template science
.\run.cmd --generate-thumbnail "$workDir" --template science
```

`--template`には台本生成時と同じIDを指定してください。テンプレートが異なると、画像・タイトル・サムネイルの生成方針も変わります。`--theme`、`--split-script`、各`--generate-*`は同時指定できないため、工程ごとに個別実行します。

台本、シーン分割、音声、画像、メタデータ、サムネイルの生成では外部API利用料が発生します。字幕生成と動画レンダリングはローカルのFFmpegを使用します。

既存の台本文だけをAPIなしで品質チェックする場合は、次のように実行します。

```powershell
.\run.cmd --script "確認したい台本文" --template science
```

文字数、想定時間、禁止表現、重複文などが`config/config.yaml`の`quality`設定に基づいて検査されます。

同じ入力と設定で生成した中間成果物は`cache/`から再利用されます。工程イベントは`logs/run_history.jsonl`、実行ごとの集計は`output/history.json`、アプリケーションログは`logs/application.log`へ保存されます。

## テンプレート共通エンディング

各テンプレート配下を再帰的に検索し、`.txt`、`.png`、`.jpg`、`.jpeg`、`.webp`を共通エンディングの素材として利用します。テキストは口調・チャンネル方針の文脈、画像は背景やロゴ等として扱われます。生成結果は`generated_assets/endings/<template>/`に保存され、素材・TTS・動画・エンディング設定から計算したSHA-256ハッシュが一致する限り再利用されます。

```powershell
.\run.cmd ending generate --template zatsugaku
.\run.cmd ending generate --template zatsugaku --force
.\run.cmd ending generate-all
.\run.cmd ending list
.\run.cmd ending delete --template zatsugaku
```

`config/config.yaml` の `ending` セクションで、機能の有効化、3〜8秒の長さ、参照テキスト上限、画像選択（`first` / `random` / `sequence`）、本編への自動結合を設定できます。`auto_append: true`では動画レンダリング後に`main.mp4`、`ending.mp4`、`final.mp4`を作成します。YouTube投稿時は`final.mp4`を最優先で使用します。

## YouTubeへ投稿する

動画生成と投稿は分離されており、投稿は明示した場合だけ実行されます。

1. Google Cloud ConsoleでYouTube Data API v3を有効化します。
2. OAuth 2.0デスクトップアプリの認証情報を作成します。
3. クライアントJSONをプロジェクト直下の`client_secret.json`へ保存します。
4. `.\run.cmd youtube auth`を実行して認証します。
5. `config/config.yaml`の`youtube.upload_enabled`を`true`へ変更します。

```powershell
.\run.cmd youtube upload <job_id>
.\run.cmd youtube upload <job_id> --privacy private
.\run.cmd youtube schedule <job_id> --publish-at "2026-08-01T19:00:00+09:00"
.\run.cmd youtube status <job_id>
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
