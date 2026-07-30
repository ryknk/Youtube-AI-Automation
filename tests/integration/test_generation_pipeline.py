"""外部APIなしの生成パイプライン統合テスト。"""

from pathlib import Path

import pytest

from youtube_generator.app.generate_scene_audio import GenerateSceneAudioUseCase
from youtube_generator.app.generate_scene_images import GenerateSceneImagesUseCase
from youtube_generator.app.generate_script import GenerateScriptUseCase
from youtube_generator.app.generate_subtitles import GenerateSubtitlesUseCase
from youtube_generator.app.split_script import SplitScriptUseCase
from youtube_generator.domain.template import VideoTemplate
from youtube_generator.services.image_prompt_builder import ImagePromptBuilder
from youtube_generator.services.srt_builder import SrtBuilder


class MockSplitter:
    def split(self, script: str) -> tuple[str, ...]:
        return ("最初のシーンです。", "次のシーンです。")


class MockDurationProvider:
    def get_duration_seconds(self, file: Path) -> float:
        return 1.0


@pytest.mark.integration
def test_mocked_generation_pipeline_creates_all_intermediate_artifacts(
    temp_output_dir, mock_text_provider, mock_tts_provider, mock_image_provider
):
    template = VideoTemplate("default", "Default", "test", "realistic", ("導入", "解説"))
    script_file = GenerateScriptUseCase(mock_text_provider, temp_output_dir).execute("テストテーマ", template, "run-1")
    scene_files = SplitScriptUseCase(MockSplitter()).execute(script_file)
    audio_files = GenerateSceneAudioUseCase(mock_tts_provider).execute(script_file.parent)
    image_files = GenerateSceneImagesUseCase(
        ImagePromptBuilder("realistic"), mock_image_provider,
        min_display_seconds=5.0, max_display_seconds=10.0, characters_per_second=6.0,
    ).execute(script_file.parent)
    subtitle_file = GenerateSubtitlesUseCase(MockDurationProvider(), SrtBuilder()).execute(script_file.parent)

    assert script_file.is_file()
    assert len(scene_files) == len(audio_files) == len(image_files) == 2
    assert subtitle_file.read_text(encoding="utf-8").count("-->") == 2
