"""シーンテキスト群から画像ファイル群を生成するユースケース。"""

import re
from pathlib import Path

from youtube_generator.logger import get_logger
from youtube_generator.services.image_prompt_builder import ImagePromptBuilder
from youtube_generator.services.scene_image_timing import (
    ImageWindow,
    build_scene_segments,
    group_into_image_windows,
)
from youtube_generator.plugins.base.image_provider import ImageProvider


SCENE_TEXT_PATTERN = re.compile(r"scene(\d{2})\.txt$", re.IGNORECASE)


class GenerateSceneImagesUseCase:
    """sceneNN.txtを順に読み込み、文単位の自然な区切りでsceneNN_MM.pngを生成する。

    シーンの表示時間はcharacters_per_secondによる文字数からの推定値を使う。実際の音声長
    （TTS・ボイス設定等）には依存させないことで、TTS設定変更時に音声・字幕・動画のみが
    再生成され、シーン画像は不要に再生成されないというキャッシュ方針を維持する
    （実際の読み上げ時間・タイミングへの区切りの合わせ込みは動画レンダリング時に行う）。
    """

    def __init__(
        self,
        prompt_builder: ImagePromptBuilder,
        image_generator: ImageProvider,
        min_display_seconds: float,
        max_display_seconds: float,
        characters_per_second: float,
        max_images: int = 8,
    ) -> None:
        if min_display_seconds <= 0 or max_display_seconds < min_display_seconds:
            raise ValueError("image.min_display_seconds / max_display_seconds の設定が不正です。")
        if characters_per_second <= 0:
            raise ValueError("quality.characters_per_second の設定が不正です。")
        self._prompt_builder = prompt_builder
        self._image_generator = image_generator
        self._min_display_seconds = min_display_seconds
        self._max_display_seconds = max_display_seconds
        self._characters_per_second = characters_per_second
        self._max_images = max_images
        self._logger = get_logger(__name__)

    def execute(self, scenes_dir: Path) -> tuple[Path, ...]:
        """各シーンを番号順に画像化し、sceneNN_MM.png（MM=シーン内の通し番号）を保存する。"""
        scene_files = self._find_scene_files(scenes_dir)
        if not scene_files:
            raise FileNotFoundError(f"sceneNN.txt が見つかりません: {scenes_dir}")

        plan: list[tuple[Path, int, ImageWindow]] = []
        for scene_id, scene_file in enumerate(scene_files[:self._max_images], 1):
            text = scene_file.read_text(encoding="utf-8-sig")
            for sub_index, window in enumerate(self._resolve_windows(text, scene_id), 1):
                plan.append((scene_file, sub_index, window))

        total = len(plan)
        image_files: list[Path] = []
        for progress, (scene_file, sub_index, window) in enumerate(plan, 1):
            prompt = self._prompt_builder.build(window.text)
            image_file = scene_file.with_name(f"{scene_file.stem}_{sub_index:02d}.png")
            self._image_generator.generate_image(prompt, image_file)
            image_files.append(image_file)
            self._logger.info("画像生成: (%d/%d)", progress, total)
        return tuple(image_files)

    def _resolve_windows(self, text: str, scene_id: int) -> tuple[ImageWindow, ...]:
        normalized = re.sub(r"\s+", "", text)
        duration = max(len(normalized) / self._characters_per_second, 0.1)
        segments = build_scene_segments(text, duration, scene_id)
        windows = group_into_image_windows(segments, self._min_display_seconds, self._max_display_seconds)
        if windows:
            return windows
        return (ImageWindow(text=normalized, start_time=0.0, end_time=duration),)

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
