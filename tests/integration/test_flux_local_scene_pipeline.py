"""Mock FluxパイプラインからPipelineを通り、既存レンダラーでの動画生成までを確認する統合テスト。

FluxSchnellLocalImageProvider自体はtorch/diffusersを実際にはインストールせず、
遅延importの差し替え（フェイクモジュール）でモデルロード・推論をシミュレートする。
FFmpeg/FFprobeが必要なため、両方が無い環境ではスキップする。
"""

import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
from PIL import Image

from youtube_generator.app.generate_scene_images import GenerateSceneImagesUseCase
from youtube_generator.infrastructure.ffmpeg_video_renderer import FfmpegVideoRenderer, VideoRenderSettings
from youtube_generator.infrastructure.ffprobe_audio_duration_provider import FfprobeAudioDurationProvider
from youtube_generator.plugins.image.flux_schnell_local_image import (
    FluxSchnellLocalImageProvider,
    FluxSchnellLocalSettings,
)
from youtube_generator.services.image_prompt_builder import ImagePromptBuilder


class _FakeCuda:
    def is_available(self) -> bool:
        return False


class _FakeTorch:
    def __init__(self) -> None:
        self.cuda = _FakeCuda()
        self.float32 = "float32"

    def Generator(self, device: str = "cpu"):  # noqa: N802 - torch API名に合わせる
        return _FakeGenerator()


class _FakeGenerator:
    def manual_seed(self, seed: int) -> "_FakeGenerator":
        return self


class _FakePipeline:
    """FLUX.1 Schnellの代わりに、シーンごとに異なる色のダミー画像を返す。"""

    def __init__(self) -> None:
        self._colors = iter(["red", "green", "blue", "yellow"])

    def to(self, device: str) -> "_FakePipeline":
        return self

    def __call__(self, **kwargs):  # type: ignore[no-untyped-def]
        color = next(self._colors, "gray")
        # 生成サイズ(4:3)を意図的に出力サイズ(16:9)と変え、cover+中央クロップが機能することを確認する。
        image = Image.new("RGB", (kwargs["width"], kwargs["height"]), color=color)

        class _Result:
            images = [image]

        return _Result()


class _FakeFluxPipelineClass:
    def __init__(self, pipeline: _FakePipeline) -> None:
        self._pipeline = pipeline

    def from_pretrained(self, model_id: str, torch_dtype=None, cache_dir=None):  # type: ignore[no-untyped-def]
        return self._pipeline


class _FakeDiffusers:
    def __init__(self, pipeline: _FakePipeline) -> None:
        self.FluxPipeline = _FakeFluxPipelineClass(pipeline)


@pytest.mark.slow
def test_mock_flux_pipeline_scene_images_render_with_existing_renderer(tmp_path: Path) -> None:
    ffmpeg = shutil.which("ffmpeg")
    ffprobe = shutil.which("ffprobe")
    if ffmpeg is None or ffprobe is None:
        pytest.skip("FFmpeg/FFprobeがないため統合テストをスキップします。")

    scenes_dir = tmp_path / "scenes"
    scenes_dir.mkdir()
    (scenes_dir / "scene01.txt").write_text("最初のシーンです。", encoding="utf-8")
    (scenes_dir / "scene02.txt").write_text("次のシーンです。", encoding="utf-8")

    output_width, output_height = 640, 360
    flux_settings = FluxSchnellLocalSettings.from_mapping({
        "width": 800, "height": 600, "seed": 1, "allow_cpu": True,
    })
    provider = FluxSchnellLocalImageProvider(flux_settings, f"{output_width}x{output_height}")
    pipeline = _FakePipeline()
    diffusers_module = _FakeDiffusers(pipeline)
    torch_module = _FakeTorch()

    with patch.object(FluxSchnellLocalImageProvider, "_import_torch", staticmethod(lambda: torch_module)), \
         patch.object(FluxSchnellLocalImageProvider, "_import_diffusers", staticmethod(lambda: diffusers_module)):
        image_files = GenerateSceneImagesUseCase(
            ImagePromptBuilder("clean 2D digital illustration, non-photorealistic"), provider,
        ).execute(scenes_dir)
        provider.release()

    assert [file.name for file in image_files] == ["scene01.png", "scene02.png"]
    for image_file in image_files:
        with Image.open(image_file) as image:
            # Self-host生成サイズ(4:3)とは異なる最終シーンサイズ(16:9)へ、
            # 縦横比を保ったまま整形されていることを確認する。
            assert image.size == (output_width, output_height)

    for image_file in image_files:
        audio_file = image_file.with_suffix(".mp3")
        subprocess.run(
            [ffmpeg, "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=1", str(audio_file)],
            check=True, capture_output=True,
        )
    (scenes_dir / "subtitles.srt").write_text(
        "1\n00:00:00,000 --> 00:00:01,000\n最初のシーンです。\n\n"
        "2\n00:00:01,000 --> 00:00:02,000\n次のシーンです。\n",
        encoding="utf-8",
    )

    renderer = FfmpegVideoRenderer(
        duration_provider=FfprobeAudioDurationProvider(ffprobe),
        settings=VideoRenderSettings(
            width=output_width, height=output_height, fps=24,
            bgm_enabled=False, bgm_file=tmp_path / "unused-bgm.mp3", bgm_volume=0.1,
        ),
        executable=ffmpeg,
    )
    video_file = scenes_dir / "video.mp4"
    renderer.render(scenes_dir, video_file)

    assert video_file.is_file()
    assert video_file.stat().st_size > 0
