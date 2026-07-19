"""外部API・FFmpegなしで確認するエンディング結合フロー。"""

from pathlib import Path

from youtube_generator.ending.manager import EndingManager, EndingSettings
from youtube_generator.ending.renderer import EndingRenderRequest
from youtube_generator.services.quality_checker import QualityChecker, QualityRules
from youtube_generator.services.srt_builder import SrtBuilder
from youtube_generator.services.template_service import TemplateManager


class _Text:
    def generate_text(self, theme, template):  # type: ignore[no-untyped-def]
        return theme

    def generate_ending_narration(self, template, reference_text, minimum, maximum):  # type: ignore[no-untyped-def]
        return "チャンネルを楽しんでいただけたら、また次の動画でお会いしましょう。"


class _Tts:
    def generate_speech(self, text: str, output_file: Path) -> None:
        output_file.write_bytes(b"audio")


class _Duration:
    def get_duration_seconds(self, audio_file: Path) -> float:
        return 5.0


class _Renderer:
    def render(self, request: EndingRenderRequest) -> None:
        request.output_file.write_bytes(b"ending")

    def concat(self, main_video: Path, ending_video: Path, output_file: Path) -> None:
        output_file.write_bytes(main_video.read_bytes() + ending_video.read_bytes())


def test_main_and_template_ending_are_combined(tmp_path):
    template = tmp_path / "templates" / "default"
    template.mkdir(parents=True)
    for name in ("prompt.txt", "image_prompt.txt", "title_prompt.txt", "thumbnail_prompt.txt"):
        (template / name).write_text("共通素材", encoding="utf-8")
    (template / "video.yaml").write_text("scene_structure: [締め]\n", encoding="utf-8")
    main = tmp_path / "job" / "video" / "main.mp4"
    main.parent.mkdir(parents=True)
    main.write_bytes(b"main")
    manager = EndingManager(
        TemplateManager(tmp_path / "templates"), tmp_path / "generated", _Text(), _Tts(), _Duration(),
        SrtBuilder(), _Renderer(), QualityChecker(QualityRules(1, 100, 6, (), 2)), EndingSettings(),
    )

    final = manager.append_to(main, "default", main.with_name("final.mp4"))

    assert final == main.with_name("final.mp4")
    assert final.read_bytes() == b"mainending"
