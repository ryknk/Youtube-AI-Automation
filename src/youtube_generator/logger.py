"""アプリケーション共通のログと実行サマリーを扱う。"""

import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any


LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_active_logger: "Logger | None" = None


def configure_logging(log_level: str, log_dir: Path) -> Path:
    """コンソールと実行単位のログファイルに root logger を設定する。"""
    log_dir.mkdir(parents=True, exist_ok=True)
    # Windows のファイル名には ':' を使用できない。
    log_file = log_dir / f"{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.log"

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.handlers.clear()

    formatter = logging.Formatter(LOG_FORMAT)
    for handler in (logging.StreamHandler(), logging.FileHandler(log_file, encoding="utf-8")):
        handler.setLevel(log_level)
        handler.setFormatter(formatter)
        root_logger.addHandler(handler)
    return log_file


def get_logger(name: str) -> logging.Logger:
    """名前付きロガーを返す。"""
    return logging.getLogger(name)


class Logger:
    """1回の動画生成に関する集計と ``output/history.json`` への保存を担う。"""

    def __init__(self, run_id: str, output_dir: Path) -> None:
        self._run_id = run_id
        self._output_dir = output_dir
        self._logger = get_logger(__name__)
        self._started_at: datetime | None = None
        self._started_at_ticks: float | None = None
        self._theme: str | None = None
        self._api_call_count = 0
        self._retry_count = 0
        self._generated_files: list[Path] = []

    def start(self, theme: str | None) -> None:
        self._theme = theme
        self._started_at = datetime.now(UTC)
        self._started_at_ticks = perf_counter()
        self._logger.info("開始時間: %s", self._started_at.isoformat())
        self._logger.info("入力テーマ: %s", theme or "(未指定)")

    def add_generated_file(self, file_path: Path) -> None:
        """生成済みの成果物を記録する。"""
        if file_path not in self._generated_files:
            self._generated_files.append(file_path)
            self._logger.info("生成ファイル: %s", file_path)

    def increment_api_calls(self) -> None:
        self._api_call_count += 1

    def increment_retries(self) -> None:
        self._retry_count += 1

    def finish(self, success: bool, error: Exception | None = None) -> None:
        """実行結果をログと JSON 履歴へ確定する。"""
        ended_at = datetime.now(UTC)
        elapsed = perf_counter() - self._started_at_ticks if self._started_at_ticks is not None else 0.0
        self._logger.info("終了時間: %s", ended_at.isoformat())
        self._logger.info("実行時間: %.2f 秒", elapsed)
        self._logger.info("API使用回数: %d", self._api_call_count)
        self._logger.info("リトライ回数: %d", self._retry_count)
        if error is not None:
            self._logger.error("エラー内容: %s", error)
        self._append_history(ended_at, success)

    def _append_history(self, generated_at: datetime, success: bool) -> None:
        history_file = self._output_dir / "history.json"
        entries = self._load_history(history_file)
        video_path = self._find_generated_file(".mp4")
        thumbnail_path = next((path for path in self._generated_files if "thumbnail" in path.stem.lower()), None)
        title = self._read_title()
        entries.append({
            "theme": self._theme,
            "generated_at": generated_at.isoformat(),
            "video_path": str(video_path) if video_path else None,
            "thumbnail_path": str(thumbnail_path) if thumbnail_path else None,
            "title": title,
            "success": success,
        })
        try:
            history_file.parent.mkdir(parents=True, exist_ok=True)
            history_file.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            self._logger.exception("実行履歴を保存できませんでした: %s", history_file)

    def _find_generated_file(self, suffix: str) -> Path | None:
        return next((path for path in self._generated_files if path.suffix.lower() == suffix), None)

    def _read_title(self) -> str | None:
        title_file = next((path for path in self._generated_files if path.name == "titles.txt"), None)
        if title_file is None:
            return None
        try:
            return next((line.strip() for line in title_file.read_text(encoding="utf-8").splitlines() if line.strip()), None)
        except OSError:
            return None

    @staticmethod
    def _load_history(history_file: Path) -> list[dict[str, Any]]:
        if not history_file.exists():
            return []
        try:
            content = json.loads(history_file.read_text(encoding="utf-8"))
            return content if isinstance(content, list) else []
        except (OSError, json.JSONDecodeError):
            return []


def set_active_logger(logger: Logger | None) -> None:
    """API/リトライ共通処理から参照する実行ロガーを設定する。"""
    global _active_logger
    _active_logger = logger


def get_active_logger() -> Logger | None:
    """現在実行中のロガーを返す。"""
    return _active_logger
