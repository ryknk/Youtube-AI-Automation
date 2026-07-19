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


@dataclass(frozen=True, slots=True)
class MetadataGenerationContext:
    """タイトル生成に必要な、読み込み済みのテンプレート情報。"""

    topic: str
    script: str
    template_name: str
    title_prompt: str | None = None


@dataclass(frozen=True, slots=True)
class MetadataDetails:
    """タイトル以外のYouTubeメタデータ。"""

    description: str
    tags: tuple[str, ...]
    hashtags: tuple[str, ...]
    thumbnail_copies: tuple[str, ...]


class MetadataGenerator(Protocol):
    def generate(self, context: MetadataGenerationContext) -> VideoMetadata:
        """台本とテンプレート情報からメタデータ全体を生成する。"""

    def generate_titles(self, context: MetadataGenerationContext) -> tuple[str, ...]:
        """テンプレート固有方針を用いてタイトルだけを生成する。"""

    def generate_details(self, script: str) -> MetadataDetails:
        """タイトル以外のメタデータだけを生成する。"""
