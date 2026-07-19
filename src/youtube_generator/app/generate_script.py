"""台本生成ユースケース。"""

from pathlib import Path
import re

from youtube_generator.domain.template import VideoTemplate
from youtube_generator.plugins.base.text_generator import TextGenerator


class GenerateScriptUseCase:
    """台本を生成し、実行単位の出力フォルダへ保存する。"""

    def __init__(self, generator: TextGenerator, output_dir: Path) -> None:
        self._generator = generator
        self._output_dir = output_dir

    def execute(self, theme: str, template: VideoTemplate, run_id: str) -> Path:
        """台本を生成して output/{ジャンル名}/{run_id}_{テンプレート名}_{テーマ}/script.txt に保存する。"""
        script = self._generator.generate_text(theme, template)
        script_file = self.output_directory(self._output_dir, theme, template, run_id) / "script.txt"
        script_file.parent.mkdir(parents=True, exist_ok=True)
        script_file.write_text(script + "\n", encoding="utf-8")
        return script_file

    @classmethod
    def output_directory(
        cls, output_root: Path, theme: str, template: VideoTemplate, run_id: str
    ) -> Path:
        """テンプレートのジャンル名と入力テーマから実行単位の出力先を返す。"""
        genre_name = cls._safe_path_component(template.display_name, fallback=template.template_id)
        template_name = cls._safe_path_component(
            template.display_name, fallback=template.template_id
        )
        theme_name = cls._safe_path_component(theme, fallback="テーマ未指定")
        return output_root / genre_name / f"{run_id}_{template_name}_{theme_name}"

    @staticmethod
    def _safe_path_component(value: str, fallback: str) -> str:
        normalized = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value.strip())
        normalized = normalized.rstrip(" .")
        return normalized[:80].rstrip(" .") or fallback
