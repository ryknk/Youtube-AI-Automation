"""投稿用データモデル。"""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

Privacy = Literal["private", "unlisted", "public"]


@dataclass(frozen=True, slots=True)
class UploadRequest:
    job_id: str
    video_file: Path
    thumbnail_file: Path | None
    title: str
    description: str
    tags: tuple[str, ...]
    privacy: Privacy
    category_id: str
    publish_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class UploadResult:
    video_id: str
    uploaded_at: datetime
    privacy: Privacy
    publish_at: datetime | None

    @property
    def url(self) -> str:
        return f"https://www.youtube.com/watch?v={self.video_id}"
