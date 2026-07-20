"""ディレクトリ単位で定義した動画テンプレートを読み込む。"""

import yaml
from pathlib import Path
from typing import Any

from youtube_generator.domain.template import VideoTemplate


class TemplateNotFoundError(ValueError):
    """指定テンプレートが存在しない場合の例外。"""


class TemplateManager:
    """templates/<template_id> 配下のファイルを読み込むテンプレート管理。"""

    _ALIASES = {"trivia": "zatsugaku", "urban_legend": "toshidensetsu"}

    def __init__(self, templates_dir: Path) -> None:
        self._templates_dir = templates_dir

    def get(self, template_id: str | None = None) -> VideoTemplate:
        requested_id = template_id or "default"
        resolved_id = self._ALIASES.get(requested_id, requested_id)
        template_dir = self._templates_dir / resolved_id
        if template_dir.is_dir():
            return self._load_directory(resolved_id, template_dir)
        raise TemplateNotFoundError(f"テンプレート '{requested_id}' が見つかりません。")

    def list(self) -> tuple[VideoTemplate, ...]:
        templates = tuple(
            self._load_directory(directory.name, directory)
            for directory in sorted(self._templates_dir.iterdir())
            if directory.is_dir() and (directory / "video.yaml").is_file()
        ) if self._templates_dir.is_dir() else ()
        return templates

    def directory_for(self, template_id: str | None = None) -> Path:
        """解決済みテンプレートの素材ディレクトリを返す。"""
        template = self.get(template_id)
        return self._templates_dir / template.template_id

    def ending_subtitles_enabled(self, template_id: str | None = None, default: bool = True) -> bool:
        """テンプレートのエンディング字幕表示設定。未指定時はdefault、最終的にtrue。"""
        template = self.get(template_id)
        value = self._ending_subtitle_value(template)
        if (
            value is None
            and template.template_id != "default"
            and (self._templates_dir / "default").is_dir()
        ):
            value = self._ending_subtitle_value(self.get("default"))
        return default if value is None else value

    @staticmethod
    def _ending_subtitle_value(template: VideoTemplate) -> bool | None:
        ending = (template.video_settings or {}).get("ending")
        if not isinstance(ending, dict):
            return None
        subtitles = ending.get("subtitles")
        if not isinstance(subtitles, dict) or "enabled" not in subtitles:
            return None
        return bool(subtitles["enabled"])

    @staticmethod
    def _load_directory(template_id: str, template_dir: Path) -> VideoTemplate:
        required_files = ("prompt.txt", "image_prompt.txt", "title_prompt.txt", "thumbnail_prompt.txt", "video.yaml")
        missing = [name for name in required_files if not (template_dir / name).is_file()]
        if missing:
            raise ValueError(f"テンプレート {template_id} に必要なファイルがありません: {', '.join(missing)}")
        try:
            video_config = yaml.safe_load((template_dir / "video.yaml").read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as error:
            raise ValueError(f"video.yaml を読み込めません: {template_dir}") from error
        if not isinstance(video_config, dict):
            raise ValueError(f"video.yaml はマッピング形式で指定してください: {template_dir}")
        structure = video_config.get("scene_structure", [])
        if not isinstance(structure, list) or not all(isinstance(item, str) for item in structure):
            raise ValueError(f"scene_structure は文字列配列で指定してください: {template_dir}")
        return VideoTemplate(
            template_id=template_id,
            display_name=str(video_config.get("display_name", template_id)),
            script_instruction=(template_dir / "prompt.txt").read_text(encoding="utf-8").strip(),
            image_style=(template_dir / "image_prompt.txt").read_text(encoding="utf-8").strip(),
            scene_structure=tuple(structure),
            title_instruction=(template_dir / "title_prompt.txt").read_text(encoding="utf-8").strip(),
            thumbnail_instruction=(template_dir / "thumbnail_prompt.txt").read_text(encoding="utf-8").strip(),
            video_settings=video_config,
        )
