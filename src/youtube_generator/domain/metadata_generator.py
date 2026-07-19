"""動画メタデータ生成の抽象インターフェース。"""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class VideoMetadata:
    titles: tuple[str, ...]
    description: str
    tags: tuple[str, ...]
    hashtags: tuple[str, ...]
    thumbnail_copies: tuple[str, ...]


class MetadataGenerator(Protocol):
    def generate(self, script: str) -> VideoMetadata:
        """台本からYouTube向けのメタデータを生成する。"""
