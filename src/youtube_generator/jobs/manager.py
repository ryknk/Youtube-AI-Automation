"""SQLiteを利用した逐次ジョブキュー。"""

import csv
import json
import re
import sqlite3
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from uuid import uuid4


class JobStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class JobStage(StrEnum):
    SCRIPT_GENERATION = "SCRIPT_GENERATION"
    QUALITY_CHECK = "QUALITY_CHECK"
    SCENE_SPLIT = "SCENE_SPLIT"
    VOICE_GENERATION = "VOICE_GENERATION"
    IMAGE_GENERATION = "IMAGE_GENERATION"
    SUBTITLE_GENERATION = "SUBTITLE_GENERATION"
    VIDEO_RENDER = "VIDEO_RENDER"
    METADATA_GENERATION = "METADATA_GENERATION"
    THUMBNAIL_GENERATION = "THUMBNAIL_GENERATION"
    COMPLETED = "COMPLETED"


@dataclass(frozen=True, slots=True)
class Job:
    job_id: str
    theme: str
    template: str
    created_at: str
    started_at: str | None
    finished_at: str | None
    status: JobStatus
    stage: JobStage | None
    output_dir: Path
    error_message: str | None
    retry_count: int


JobProcessor = Callable[[Job, Callable[[JobStage], None]], None]
OutputDirectoryFactory = Callable[[str, str, str], Path]


class JobManager:
    """ジョブを登録順に処理するSQLite永続キュー。"""

    def __init__(
        self, database_file: Path, jobs_output_dir: Path,
        output_directory_factory: OutputDirectoryFactory | None = None,
    ) -> None:
        self._database_file = database_file
        self._jobs_output_dir = jobs_output_dir
        self._output_directory_factory = output_directory_factory
        database_file.parent.mkdir(parents=True, exist_ok=True)
        jobs_output_dir.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def add(self, theme: str, template: str) -> Job:
        if not theme.strip() or not template.strip():
            raise ValueError("テーマとテンプレートを指定してください。")
        job_id = uuid4().hex
        output_dir = (
            self._output_directory_factory(theme.strip(), template.strip(), job_id)
            if self._output_directory_factory is not None
            else self._jobs_output_dir / (
                f"{job_id}_{self._safe_path_component(template)}_"
                f"{self._safe_path_component(theme)}"
            )
        )
        for name in ("script", "audio", "images", "subtitle", "video", "thumbnail", "metadata", "quality_report"):
            (output_dir / name).mkdir(parents=True, exist_ok=True)
        created_at = self._now()
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO jobs VALUES (?, ?, ?, ?, NULL, NULL, ?, NULL, ?, NULL, 0)",
                (job_id, theme.strip(), template.strip(), created_at, JobStatus.PENDING.value, str(output_dir)),
            )
        return self.get(job_id)

    @staticmethod
    def _safe_path_component(value: str) -> str:
        """入力テーマをWindowsでも利用できるフォルダ名へ変換する。"""
        normalized = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value.strip())
        normalized = normalized.rstrip(" .")
        return normalized[:80].rstrip(" .") or "テーマ未指定"

    def import_file(self, source_file: Path) -> tuple[Job, ...]:
        suffix = source_file.suffix.lower()
        if suffix == ".csv":
            with source_file.open(encoding="utf-8-sig", newline="") as file:
                rows = list(csv.DictReader(file))
        elif suffix == ".json":
            rows = json.loads(source_file.read_text(encoding="utf-8"))
            if not isinstance(rows, list):
                raise ValueError("JSONはテーマ一覧の配列で指定してください。")
        else:
            raise ValueError("CSVまたはJSONファイルを指定してください。")
        jobs = []
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("各行には theme と template が必要です。")
            jobs.append(self.add(str(row.get("theme", "")), str(row.get("template", "trivia"))))
        return tuple(jobs)

    def list(self) -> tuple[Job, ...]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM jobs ORDER BY created_at, rowid").fetchall()
        return tuple(self._from_row(row) for row in rows)

    def get(self, job_id: str) -> Job:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        if row is None:
            raise KeyError(f"ジョブが見つかりません: {job_id}")
        return self._from_row(row)

    def cancel(self, job_id: str) -> Job:
        job = self.get(job_id)
        if job.status is JobStatus.RUNNING:
            raise ValueError("実行中のジョブはキャンセルできません。")
        if job.status in (JobStatus.COMPLETED, JobStatus.FAILED):
            raise ValueError("完了・失敗済みジョブはキャンセルできません。")
        self._update(job_id, status=JobStatus.CANCELLED, stage=None)
        return self.get(job_id)

    def delete(self, job_id: str) -> bool:
        """指定ジョブをキューDBから削除する。成果物フォルダは保持する。"""
        job = self.get(job_id)
        if job.status is JobStatus.RUNNING:
            raise ValueError("実行中のジョブは削除できません。")
        with self._connect() as connection:
            connection.execute("DELETE FROM youtube_uploads WHERE job_id=?", (job_id,))
            cursor = connection.execute("DELETE FROM jobs WHERE job_id=?", (job_id,))
        return cursor.rowcount == 1

    def clear(self) -> int:
        """実行中でないすべてのジョブをキューDBから削除する。"""
        with self._connect() as connection:
            running_count = connection.execute(
                "SELECT COUNT(*) FROM jobs WHERE status=?", (JobStatus.RUNNING.value,)
            ).fetchone()[0]
            if running_count:
                raise ValueError("実行中のジョブがあるためキューをクリアできません。")
            connection.execute("DELETE FROM youtube_uploads")
            cursor = connection.execute("DELETE FROM jobs")
        return cursor.rowcount

    def retry(self, job_id: str) -> Job:
        job = self.get(job_id)
        if job.status not in (JobStatus.FAILED, JobStatus.CANCELLED):
            raise ValueError("FAILEDまたはCANCELLEDのジョブだけ再試行できます。")
        with self._connect() as connection:
            connection.execute(
                "UPDATE jobs SET status=?, stage=NULL, started_at=NULL, finished_at=NULL, error_message=NULL, retry_count=retry_count+1 WHERE job_id=?",
                (JobStatus.PENDING.value, job_id),
            )
        return self.get(job_id)

    def recover_interrupted(self) -> int:
        """異常終了でRUNNINGのまま残ったジョブを安全にPENDINGへ戻す。"""
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE jobs SET status=?, stage=NULL, started_at=NULL, error_message=? WHERE status=?",
                (JobStatus.PENDING.value, "前回実行が中断されたため再実行待ちに戻しました。", JobStatus.RUNNING.value),
            )
        return cursor.rowcount

    def run_pending(self, processor: JobProcessor, stop_on_error: bool = False) -> None:
        self.recover_interrupted()
        while True:
            job = self._next_pending()
            if job is None:
                return
            self._update(job.job_id, status=JobStatus.RUNNING, started_at=self._now(), error_message=None)
            try:
                processor(self.get(job.job_id), lambda stage: self._update(job.job_id, stage=stage))
            except Exception as error:
                self._update(job.job_id, status=JobStatus.FAILED, finished_at=self._now(), error_message=str(error))
                if stop_on_error:
                    return
            else:
                self._update(job.job_id, status=JobStatus.COMPLETED, stage=JobStage.COMPLETED, finished_at=self._now())

    def get_youtube_upload(self, job_id: str) -> dict[str, str] | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM youtube_uploads WHERE job_id=?", (job_id,)).fetchone()
        return dict(row) if row is not None else None

    def save_youtube_upload(self, job_id: str, video_id: str, privacy: str, publish_at: str | None, status: str) -> None:
        with self._connect() as connection:
            connection.execute("""INSERT OR REPLACE INTO youtube_uploads
                (job_id, video_id, uploaded_at, privacy, publish_at, url, status)
                VALUES (?, ?, ?, ?, ?, ?, ?)""", (job_id, video_id, self._now(), privacy, publish_at,
                f"https://www.youtube.com/watch?v={video_id}", status))

    def _next_pending(self) -> Job | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE status=? ORDER BY created_at, rowid LIMIT 1", (JobStatus.PENDING.value,)).fetchone()
        return self._from_row(row) if row else None

    def _update(self, job_id: str, **values: object) -> None:
        columns = ", ".join(f"{key}=?" for key in values)
        parameters = [value.value if isinstance(value, StrEnum) else value for value in values.values()]
        with self._connect() as connection:
            connection.execute(f"UPDATE jobs SET {columns} WHERE job_id=?", (*parameters, job_id))

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS jobs (
                job_id TEXT PRIMARY KEY, theme TEXT NOT NULL, template TEXT NOT NULL, created_at TEXT NOT NULL,
                started_at TEXT, finished_at TEXT, status TEXT NOT NULL, stage TEXT, output_dir TEXT NOT NULL,
                error_message TEXT, retry_count INTEGER NOT NULL DEFAULT 0)""")
            connection.execute("""CREATE TABLE IF NOT EXISTS youtube_uploads (
                job_id TEXT PRIMARY KEY, video_id TEXT NOT NULL, uploaded_at TEXT NOT NULL,
                privacy TEXT NOT NULL, publish_at TEXT, url TEXT NOT NULL, status TEXT NOT NULL,
                FOREIGN KEY(job_id) REFERENCES jobs(job_id))""")

    @contextmanager
    def _connect(self):  # type: ignore[no-untyped-def]
        connection = sqlite3.connect(self._database_file)
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    @staticmethod
    def _now() -> str:
        return datetime.now(UTC).isoformat()

    @staticmethod
    def _from_row(row: sqlite3.Row) -> Job:
        return Job(row["job_id"], row["theme"], row["template"], row["created_at"], row["started_at"], row["finished_at"],
            JobStatus(row["status"]), JobStage(row["stage"]) if row["stage"] else None, Path(row["output_dir"]), row["error_message"], row["retry_count"])
