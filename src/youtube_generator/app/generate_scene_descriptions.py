"""シーンテキスト群から画像プロンプト用の場面説明ファイル群を独立して生成するユースケース。"""

from pathlib import Path

from youtube_generator.app.generate_scene_images import GenerateSceneImagesUseCase
from youtube_generator.logger import get_logger
from youtube_generator.plugins.base.scene_visual_describer import SceneVisualDescriber


class GenerateSceneDescriptionsUseCase:
    """sceneNN.txtから、画像生成時と同じ区切り単位でsceneNN_MM.description.txtを生成する。

    --generate-images実行時に都度行っていた場面説明生成（OpenAI API呼び出し・追加課金あり）を
    独立した工程として切り出したもの。画像生成側の設定だけを変更したい場合でも場面説明の
    再呼び出しが発生しないよう、--generate-imagesはここで書き出したファイルがあればそれを使う
    （GenerateSceneImagesUseCase._load_precomputed_descriptions参照）。
    """

    def __init__(
        self,
        scene_visual_describer: SceneVisualDescriber | None,
        min_display_seconds: float,
        max_display_seconds: float,
        characters_per_second: float,
        max_images: int = 8,
    ) -> None:
        self._scene_visual_describer = scene_visual_describer
        self._min_display_seconds = min_display_seconds
        self._max_display_seconds = max_display_seconds
        self._characters_per_second = characters_per_second
        self._max_images = max_images
        self._logger = get_logger(__name__)

    def execute(self, scenes_dir: Path, force: bool = False) -> tuple[Path, ...]:
        """各画像windowに対応するsceneNN_MM.description.txtを保存する。

        force=Trueの場合、既存ファイルの有無を無視してすべて生成し直す。
        image.scene_description.enabled=falseの場合（scene_visual_describerが未設定）は
        何もせず空のタプルを返す。
        """
        if self._scene_visual_describer is None:
            self._logger.info("image.scene_description.enabled が false のため場面説明生成をスキップします。")
            return ()

        plan = GenerateSceneImagesUseCase.build_plan(
            scenes_dir, self._min_display_seconds, self._max_display_seconds,
            self._characters_per_second, self._max_images,
        )
        description_files = tuple(
            GenerateSceneImagesUseCase.description_file_for(image_file) for _, image_file in plan
        )
        total = len(description_files)
        pending_indices = (
            list(range(total)) if force
            else [index for index in range(total) if not description_files[index].is_file()]
        )
        skipped = total - len(pending_indices)
        if skipped:
            self._logger.info("生成済みの場面説明 %d/%d 件をスキップします。", skipped, total)
        if pending_indices:
            narration_texts = tuple(plan[index][0].text for index in pending_indices)
            descriptions = self._scene_visual_describer.describe_scenes(narration_texts)
            if len(descriptions) != len(narration_texts):
                raise ValueError(
                    "場面説明の件数がシーン画像数と一致しません: "
                    f"expected={len(narration_texts)}, actual={len(descriptions)}"
                )
            for index, description in zip(pending_indices, descriptions):
                description_files[index].write_text(description, encoding="utf-8")
            self._logger.info("場面説明を生成しました: (%d/%d)", len(pending_indices), total)
        return description_files
