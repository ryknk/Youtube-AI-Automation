"""シーンテキスト群から音声ファイル群を生成するユースケース。"""

import re
from pathlib import Path

from youtube_generator.plugins.base.tts_provider import TTSProvider


SCENE_TEXT_PATTERN = re.compile(r"scene(\d{2})\.txt$", re.IGNORECASE)


class GenerateSceneAudioUseCase:
    """sceneNN.txtを順に読み込み、sceneNN.mp3を生成する。"""

    def __init__(self, synthesizer: TTSProvider) -> None:
        self._synthesizer = synthesizer

    def execute(self, scenes_dir: Path) -> tuple[Path, ...]:
        """シーンテキストをファイル番号順に音声化する。"""
        scene_files = self._find_scene_files(scenes_dir)
        if not scene_files:
            raise FileNotFoundError(f"sceneNN.txt が見つかりません: {scenes_dir}")

        audio_files: list[Path] = []
        for scene_file in scene_files:
            text = scene_file.read_text(encoding="utf-8")
            audio_file = scene_file.with_suffix(".mp3")
            self._synthesizer.generate_speech(text, audio_file)
            audio_files.append(audio_file)
        return tuple(audio_files)

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
