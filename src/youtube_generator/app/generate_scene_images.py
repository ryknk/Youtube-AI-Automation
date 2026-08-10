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
from youtube_generator.plugins.base.image_editor import ImageEditor
from youtube_generator.plugins.base.image_provider import ImageProvider
from youtube_generator.plugins.base.scene_visual_describer import SceneVisualDescriber


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
        scene_visual_describer: SceneVisualDescriber | None = None,
        image_editor: ImageEditor | None = None,
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
        # 未指定（None）の場合は、ナレーション文をそのまま画像プロンプトへ渡す従来動作を維持する。
        self._scene_visual_describer = scene_visual_describer
        # 未指定（None）の場合は、生成した画像をそのまま使う従来動作を維持する（編集ステップをスキップ）。
        self._image_editor = image_editor
        self._logger = get_logger(__name__)

    def execute(
        self, scenes_dir: Path, force: bool = False, only_files: tuple[Path, ...] | None = None,
    ) -> tuple[Path, ...]:
        """各シーンを番号順に画像化し、sceneNN_MM.png（MM=シーン内の通し番号）を保存する。

        force=Trueの場合、既存の画像ファイルの有無を無視してすべて生成し直す。
        only_filesを指定した場合、計画上のsceneNN_MM.pngのうち該当するファイルのみを対象にし、
        既存ファイルの有無に関わらず常にそれらだけを生成し直す（他の画像には触れない）。
        全件を対象にすると時間がかかるため、一部の画像だけ作り直したい場合に使う。
        """
        plan = self.build_plan(
            scenes_dir, self._min_display_seconds, self._max_display_seconds,
            self._characters_per_second, self._max_images,
        )

        if only_files is not None:
            requested = {image_file.resolve() for image_file in only_files}
            plan_files = {image_file.resolve() for _, image_file in plan}
            missing = requested - plan_files
            if missing:
                raise ValueError(
                    "指定された画像はシーン計画に含まれていません: "
                    + ", ".join(str(image_file) for image_file in sorted(missing))
                )
            pending = [entry for entry in plan if entry[1].resolve() in requested]
            skipped = 0
            total = len(pending)
            image_files: list[Path] = [image_file for _, image_file in pending]
        else:
            total = len(plan)
            # 中断されたジョブの再試行等で一部の画像が既に生成済みの場合、同名ファイルが既に
            # あれば生成済みとみなして再生成しない（無駄なAPI課金・GPU処理の防止）。
            # force=Trueの場合はこの判定を無視し、常に全件生成し直す。
            pending = list(plan) if force else [entry for entry in plan if not entry[1].exists()]
            skipped = total - len(pending)
            if skipped:
                self._logger.info("生成済みの画像 %d/%d 件をスキップします。", skipped, total)
            image_files = [image_file for _, image_file in plan]

        prompt_sources = self._describe_scenes(tuple(pending))
        for progress, ((window, image_file), prompt_source) in enumerate(
            zip(pending, prompt_sources), 1,
        ):
            prompt = self._prompt_builder.build(prompt_source)
            self._image_generator.generate_image(prompt, image_file)
            self._logger.info("画像生成: (%d/%d)", skipped + progress, total)

        if self._image_editor is not None:
            # 生成用モデルを解放してから編集用モデルをロードする。両方を同時にVRAMへ
            # 乗せようとすると、1枚ごとに交互ロードする方式ではVRAM不足になりうるため、
            # 「全画像生成→生成Provider解放→全画像編集」の2段階に分離している。
            self._release_if_supported(self._image_generator)
            for progress, image_file in enumerate(image_files, 1):
                self._image_editor.edit(image_file)
                self._logger.info("画像編集: (%d/%d)", progress, total)
        return tuple(image_files)

    @staticmethod
    def _release_if_supported(provider: object) -> None:
        release = getattr(provider, "release", None)
        if callable(release):
            release()

    def _describe_scenes(self, pending: tuple[tuple[ImageWindow, Path], ...]) -> tuple[str, ...]:
        """設定されていれば動画1本分をまとめて1回のAPI呼び出しで英語の場面説明へ変換し、
        生の日本語ナレーション文が画像プロンプトへ直接渡ることによる字幕的な文字描画を避ける。
        未設定時は従来どおり原文をそのまま返す。

        GenerateSceneDescriptionsUseCase（--generate-scene-descriptions）が独立した工程として
        sceneNN_MM.description.txtを書き出し済みの場合は、それを使いAPI呼び出しを省略する。"""
        narration_texts = tuple(window.text for window, _ in pending)
        precomputed = self._load_precomputed_descriptions(pending)
        if precomputed is not None:
            return precomputed
        if self._scene_visual_describer is None:
            return narration_texts
        descriptions = self._scene_visual_describer.describe_scenes(narration_texts)
        if len(descriptions) != len(narration_texts):
            raise ValueError(
                "場面説明の件数がシーン画像数と一致しません: "
                f"expected={len(narration_texts)}, actual={len(descriptions)}"
            )
        return descriptions

    def _load_precomputed_descriptions(
        self, pending: tuple[tuple[ImageWindow, Path], ...],
    ) -> tuple[str, ...] | None:
        if self._scene_visual_describer is None or not pending:
            return None
        description_files = [self.description_file_for(image_file) for _, image_file in pending]
        if not all(description_file.is_file() for description_file in description_files):
            return None
        return tuple(
            description_file.read_text(encoding="utf-8-sig").strip() for description_file in description_files
        )

    @staticmethod
    def description_file_for(image_file: Path) -> Path:
        """画像ファイルパスから、対応する場面説明ファイル（sceneNN_MM.description.txt）を求める。
        GenerateSceneDescriptionsUseCaseとの間で共有する命名規則。"""
        return image_file.with_name(f"{image_file.stem}.description.txt")

    @classmethod
    def build_plan(
        cls,
        scenes_dir: Path,
        min_display_seconds: float,
        max_display_seconds: float,
        characters_per_second: float,
        max_images: int = 8,
    ) -> tuple[tuple[ImageWindow, Path], ...]:
        """sceneNN.txtから、画像1枚ごとの(ImageWindow, 出力先パス)計画を組み立てる。

        GenerateSceneImagesUseCase.execute()とGenerateSceneDescriptionsUseCase.execute()が
        同一の枚数・区切り・ファイル名を共有するための共通処理。"""
        scene_files = cls._find_scene_files(scenes_dir)
        if not scene_files:
            raise FileNotFoundError(f"sceneNN.txt が見つかりません: {scenes_dir}")

        plan: list[tuple[ImageWindow, Path]] = []
        for scene_id, scene_file in enumerate(scene_files[:max_images], 1):
            text = scene_file.read_text(encoding="utf-8-sig")
            windows = cls._resolve_windows(
                text, scene_id, min_display_seconds, max_display_seconds, characters_per_second,
            )
            for sub_index, window in enumerate(windows, 1):
                image_file = scene_file.with_name(f"{scene_file.stem}_{sub_index:02d}.png")
                plan.append((window, image_file))
        return tuple(plan)

    @staticmethod
    def _resolve_windows(
        text: str, scene_id: int, min_display_seconds: float, max_display_seconds: float,
        characters_per_second: float,
    ) -> tuple[ImageWindow, ...]:
        normalized = re.sub(r"\s+", "", text)
        duration = max(len(normalized) / characters_per_second, 0.1)
        segments = build_scene_segments(text, duration, scene_id)
        windows = group_into_image_windows(segments, min_display_seconds, max_display_seconds)
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
