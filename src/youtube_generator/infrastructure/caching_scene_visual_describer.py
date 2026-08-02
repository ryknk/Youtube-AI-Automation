"""SceneVisualDescriberの呼び出し結果をキャッシュするデコレータ。

画像生成の設定（qwen_image_nunchaku_local等）だけを変更して--generate-imagesを
再実行するようなケースでは、シーン画像自体のキャッシュ（image_cache_key）はミスするが、
ナレーション文と場面説明の設定は変わっていないため、場面説明（OpenAI API呼び出し・
追加課金あり）は本来再実行不要である。GenerateSceneImagesUseCase.execute()は
画像生成とセットで場面説明を呼び出す構成のため、シーン画像のキャッシュとは独立に
場面説明だけをキャッシュすることで、この不要なAPI呼び出しを避ける。
"""

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from youtube_generator.infrastructure.cache import CacheManager
from youtube_generator.plugins.base.scene_visual_describer import SceneVisualDescriber


class CachingSceneVisualDescriber:
    """委譲先のSceneVisualDescriberの結果を、ナレーション文＋fingerprint単位でキャッシュする。"""

    _ARTIFACT_NAME = "scene_descriptions"

    def __init__(
        self, delegate: SceneVisualDescriber, cache_manager: CacheManager, fingerprint: str,
    ) -> None:
        self._delegate = delegate
        self._cache_manager = cache_manager
        self._fingerprint = fingerprint

    def describe_scenes(self, narration_texts: tuple[str, ...]) -> tuple[str, ...]:
        cache_key = CacheManager.make_key(self._fingerprint, *narration_texts)
        cached = self._restore(cache_key)
        if cached is not None:
            return cached
        descriptions = self._delegate.describe_scenes(narration_texts)
        self._save(cache_key, descriptions)
        return descriptions

    def _restore(self, cache_key: str) -> tuple[str, ...] | None:
        if not self._cache_manager.exists(cache_key, self._ARTIFACT_NAME):
            return None
        with TemporaryDirectory() as temp_dir:
            restored_files = self._cache_manager.restore_files(cache_key, self._ARTIFACT_NAME, Path(temp_dir))
            payload = json.loads(restored_files[0].read_text(encoding="utf-8"))
        return tuple(payload)

    def _save(self, cache_key: str, descriptions: tuple[str, ...]) -> None:
        with TemporaryDirectory() as temp_dir:
            temp_file = Path(temp_dir) / "descriptions.json"
            temp_file.write_text(json.dumps(list(descriptions), ensure_ascii=False), encoding="utf-8")
            self._cache_manager.save_files(cache_key, self._ARTIFACT_NAME, (temp_file,))
