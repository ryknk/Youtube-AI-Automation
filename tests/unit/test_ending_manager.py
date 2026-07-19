"""テンプレート共通エンディングの単体テスト。"""

from pathlib import Path

from youtube_generator.ending.manager import EndingManager, EndingSettings
from youtube_generator.ending.renderer import EndingRenderRequest
from youtube_generator.infrastructure.cache import CacheManager
from youtube_generator.services.quality_checker import QualityChecker, QualityRules
from youtube_generator.services.srt_builder import SrtBuilder
from youtube_generator.services.template_service import TemplateManager


class FakeTextGenerator:
    def __init__(self) -> None:
        self.calls = 0

    def generate_text(self, theme, template):  # type: ignore[no-untyped-def]
        return theme

    def generate_ending_narration(self, template, reference_text, minimum, maximum):  # type: ignore[no-untyped-def]
        self.calls += 1
        return "今回の内容が役立ったなら、また次の動画でお会いしましょう。"


class FakeTTS:
    def generate_speech(self, text: str, output_file: Path) -> None:
        output_file.write_bytes(b"fake-mp3")


class FakeDuration:
    def get_duration_seconds(self, audio_file: Path) -> float:
        assert audio_file.is_file()
        return 4.0


class FakeRenderer:
    def __init__(self) -> None:
        self.requests: list[EndingRenderRequest] = []

    def render(self, request: EndingRenderRequest) -> None:
        self.requests.append(request)
        request.output_file.write_bytes(b"fake-mp4")

    def concat(self, main_video: Path, ending_video: Path, output_file: Path) -> None:
        output_file.write_bytes(main_video.read_bytes() + ending_video.read_bytes())


def _write_template(root: Path, template_id: str = "science", with_image: bool = True) -> Path:
    directory = root / template_id
    directory.mkdir(parents=True)
    (directory / "prompt.txt").write_text("親しみやすい科学チャンネルです。", encoding="utf-8")
    (directory / "image_prompt.txt").write_text("realistic science", encoding="utf-8")
    (directory / "title_prompt.txt").write_text("短いタイトル", encoding="utf-8")
    (directory / "thumbnail_prompt.txt").write_text("明るい表紙", encoding="utf-8")
    (directory / "extra.txt").write_text("視聴者にやさしく呼びかけます。", encoding="utf-8")
    (directory / "video.yaml").write_text("display_name: 科学\nscene_structure: [導入]\n", encoding="utf-8")
    if with_image:
        (directory / "nested").mkdir()
        (directory / "nested" / "logo.png").write_bytes(b"image")
    return directory


def _manager(tmp_path: Path, with_image: bool = True, auto_append: bool = True):
    templates_root = tmp_path / "templates"
    _write_template(templates_root, with_image=with_image)
    generator = FakeTextGenerator()
    renderer = FakeRenderer()
    manager = EndingManager(
        TemplateManager(templates_root), tmp_path / "generated", generator, FakeTTS(), FakeDuration(), SrtBuilder(),
        renderer, QualityChecker(QualityRules(1, 4000, 6, (), 2)),
        EndingSettings(min_duration=3, max_duration=8, image_mode="sequence", auto_append=auto_append),
        CacheManager(tmp_path / "cache"), "test-settings",
    )
    return manager, generator, renderer, templates_root


def test_collects_all_text_and_images_recursively(tmp_path):
    manager, _, _, _ = _manager(tmp_path)

    materials = manager.collect_materials("science")

    assert len(materials.text_files) == 5
    assert len(materials.image_files) == 1
    assert "親しみやすい" in materials.reference_text


def test_generates_and_reuses_cached_ending(tmp_path):
    manager, generator, renderer, _ = _manager(tmp_path)

    first = manager.ensure("science")
    second = manager.ensure("science")

    assert first is not None and first.video_file.is_file()
    assert second is not None and second.reused is True
    assert generator.calls == 1
    assert len(renderer.requests) == 1


def test_no_images_is_not_an_error_and_force_regenerates(tmp_path):
    manager, generator, renderer, _ = _manager(tmp_path, with_image=False)

    manager.ensure("science")
    manager.ensure("science", force=True)

    assert generator.calls == 2
    assert renderer.requests[0].image_files == ()


def test_material_change_invalidates_existing_ending(tmp_path):
    manager, generator, _, templates_root = _manager(tmp_path)
    manager.ensure("science")
    (templates_root / "science" / "extra.txt").write_text("新しい方針です。", encoding="utf-8")

    manager.ensure("science")

    assert generator.calls == 2


def test_auto_append_can_be_disabled(tmp_path):
    manager, _, _, _ = _manager(tmp_path, auto_append=False)
    main = tmp_path / "main.mp4"
    main.write_bytes(b"main")

    result = manager.append_to(main, "science", tmp_path / "final.mp4")

    assert result == main
    assert not (tmp_path / "final.mp4").exists()


def test_appends_ending_to_main_video(tmp_path):
    manager, _, _, _ = _manager(tmp_path)
    main = tmp_path / "main.mp4"
    main.write_bytes(b"main")

    final = manager.append_to(main, "science", tmp_path / "final.mp4")

    assert final.read_bytes() == b"mainfake-mp4"


def test_delete_removes_generated_asset_and_cache(tmp_path):
    manager, _, _, _ = _manager(tmp_path)
    asset = manager.ensure("science")
    assert asset is not None

    assert manager.delete("science") is True

    assert not asset.directory.exists()
    assert not (tmp_path / "cache" / asset.cache_key).exists()
