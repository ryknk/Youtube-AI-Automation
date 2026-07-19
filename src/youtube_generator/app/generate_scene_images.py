"""シーンテキスト群から画像ファイル群を生成するユースケース。"""

import re
from pathlib import Path

from youtube_generator.services.image_prompt_builder import ImagePromptBuilder
from youtube_generator.plugins.base.image_provider import ImageProvider


SCENE_TEXT_PATTERN = re.compile(r"scene(\d{2})\.txt$", re.IGNORECASE)


class GenerateSceneImagesUseCase:
    """sceneNN.txtを順に読み込み、sceneNN.pngを生成する。"""

    def __init__(self, prompt_builder: ImagePromptBuilder, image_generator: ImageProvider, max_images: int = 8) -> None:
        self._prompt_builder = prompt_builder
        self._image_generator = image_generator
        self._max_images = max_images

    def execute(self, scenes_dir: Path) -> tuple[Path, ...]:
        """各シーンを番号順に画像化し、同名のPNGファイルを保存する。"""
        scene_files = self._find_scene_files(scenes_dir)
        if not scene_files:
            raise FileNotFoundError(f"sceneNN.txt が見つかりません: {scenes_dir}")

        image_files: list[Path] = []
        for scene_file in scene_files[:self._max_images]:
            prompt = self._prompt_builder.build(scene_file.read_text(encoding="utf-8"))
            image_file = scene_file.with_suffix(".png")
            self._image_generator.generate_image(prompt, image_file)
            image_files.append(image_file)
        return tuple(image_files)

    @staticmethod
    def _find_scene_files(scenes_dir: Path) -> tuple[Path, ...]:
        if not scenes_dir.is_dir():
            raise FileNotFoundError(f"シーンフォルダが見つかりません: {scenes_dir}")
        numbered_files = []
        for path in scenes_dir.glob("scene*.txt"):
            match = SCENE_TEXT_PATTERN.fullmatch(path.name)
            if match:
                numbered_files.append((int(match.group(1)), path))
        return tuple(path for _, path in sorted(numbered_files))
