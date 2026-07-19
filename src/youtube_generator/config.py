"""アプリケーション設定を一元管理する。"""

from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    """環境変数と .env から読み込む設定値。"""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Youtube AI Automation"
    log_level: str = "INFO"
    output_dir: Path = Field(default=PROJECT_ROOT / "output")
    log_dir: Path = Field(default=PROJECT_ROOT / "logs")
    config_dir: Path = Field(default=PROJECT_ROOT / "config")
    templates_dir: Path = Field(default=PROJECT_ROOT / "templates")
    cache_dir: Path = Field(default=PROJECT_ROOT / "cache")
    data_dir: Path = Field(default=PROJECT_ROOT / "data")
    youtube_client_secrets_file: Path = Field(default=PROJECT_ROOT / "client_secret.json")
    youtube_token_file: Path = Field(default=PROJECT_ROOT / "youtube_token.json")
    history_file: Path = Field(default=PROJECT_ROOT / "logs" / "run_history.jsonl")
    ffprobe_executable: str = "ffprobe"
    openai_api_key: SecretStr | None = None
    bfl_api_key: SecretStr | None = None
    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, value: str) -> str:
        normalized_value = value.upper()
        allowed_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if normalized_value not in allowed_levels:
            message = f"LOG_LEVEL は {', '.join(sorted(allowed_levels))} のいずれかを指定してください。"
            raise ValueError(message)
        return normalized_value

    @field_validator("output_dir", "log_dir", "config_dir", "templates_dir", "cache_dir", "data_dir", "history_file", "youtube_client_secrets_file", "youtube_token_file")
    @classmethod
    def resolve_project_relative_path(cls, value: Path) -> Path:
        """.env の相対パスをプロジェクトルート基準に正規化する。"""
        return value if value.is_absolute() else PROJECT_ROOT / value

    def ensure_runtime_directories(self) -> None:
        """実行時に必要な出力・ログ用ディレクトリを作成する。"""
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.templates_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.data_dir.mkdir(parents=True, exist_ok=True)


def load_settings() -> Settings:
    """設定を読み込み、アプリケーションで必要なディレクトリを準備する。"""
    settings = Settings()
    settings.ensure_runtime_directories()
    return settings
