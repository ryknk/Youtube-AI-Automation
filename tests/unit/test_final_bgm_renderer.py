"""最終段階での単一BGMミックスを検証する。"""

from pathlib import Path

from youtube_generator.infrastructure.cache import CacheManager
from youtube_generator.infrastructure.final_bgm_renderer import FinalBGMRenderer, FinalRenderSettings
from youtube_generator.services.bgm_manager import BgmSettings


class FakeFinalBGMRenderer(FinalBGMRenderer):
    def __init__(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        super().__init__(*args, **kwargs)
        self.mix_count = 0

    def _combine(self, main_file: Path, ending_file: Path | None, output_file: Path) -> None:
        output_file.write_bytes(main_file.read_bytes() + (ending_file.read_bytes() if ending_file else b""))

    def _duration(self, video_file: Path) -> float:
        return 5.0

    def _has_audio(self, video_file: Path) -> bool:
        return True

    def _run(self, command: list[str], action: str) -> None:
        self.mix_count += 1
        Path(command[-1]).write_bytes(b"final-video")


def _inputs(tmp_path: Path):
    main = tmp_path / "main.mp4"
    ending = tmp_path / "ending.mp4"
    bgm = tmp_path / "theme.mp3"
    main.write_bytes(b"main")
    ending.write_bytes(b"ending")
    bgm.write_bytes(b"bgm")
    return main, ending, bgm


def test_final_mix_builds_single_continuous_bgm_filter(tmp_path):
    main, _, bgm_file = _inputs(tmp_path)
    renderer = FakeFinalBGMRenderer(FinalRenderSettings(320, 180, 1))
    bgm = BgmSettings(True, bgm_file, 0.08, True, 1.0, 2.0)

    command = renderer._build_mix_command(main, tmp_path / "final.mp4", bgm, 5.0)
    graph = command[command.index("-filter_complex") + 1]

    assert "-stream_loop" in command
    assert "atrim=duration=5.000" in graph
    assert "volume=0.08" in graph
    assert "afade=t=in:st=0:d=1.000" in graph
    assert "afade=t=out:st=3.000:d=2.000" in graph
    assert "[0:a]volume=1.0[narration]" in graph
    assert "amix=inputs=2:duration=first:weights='1 1':normalize=0" in graph


def test_loop_false_does_not_loop_bgm(tmp_path):
    main, _, bgm_file = _inputs(tmp_path)
    command = FakeFinalBGMRenderer(FinalRenderSettings(320, 180, 1))._build_mix_command(
        main, tmp_path / "final.mp4", BgmSettings(True, bgm_file, 0.1, False), 5.0
    )
    assert "-stream_loop" not in command


def test_final_mix_cache_reuses_main_and_ending(tmp_path):
    main, ending, bgm_file = _inputs(tmp_path)
    renderer = FakeFinalBGMRenderer(FinalRenderSettings(320, 180, 1), CacheManager(tmp_path / "cache"))
    bgm = BgmSettings(True, bgm_file)

    first = renderer.render(main, ending, tmp_path / "video", bgm)
    second = renderer.render(main, ending, tmp_path / "video", bgm)

    assert first == second
    assert renderer.mix_count == 1


def test_bgm_or_input_change_remixes_only_final(tmp_path):
    main, ending, bgm_file = _inputs(tmp_path)
    renderer = FakeFinalBGMRenderer(FinalRenderSettings(320, 180, 1), CacheManager(tmp_path / "cache"))
    bgm = BgmSettings(True, bgm_file)
    renderer.render(main, ending, tmp_path / "video", bgm)
    bgm_file.write_bytes(b"changed-bgm")
    renderer.render(main, ending, tmp_path / "video", bgm)
    main.write_bytes(b"changed-main")
    renderer.render(main, ending, tmp_path / "video", bgm)
    ending.write_bytes(b"changed-ending")
    renderer.render(main, ending, tmp_path / "video", bgm)

    assert renderer.mix_count == 4


def test_bgm_disabled_keeps_combined_narration_video(tmp_path):
    main, ending, _ = _inputs(tmp_path)
    renderer = FakeFinalBGMRenderer(FinalRenderSettings(320, 180, 1))
    final = renderer.render(main, ending, tmp_path / "video", BgmSettings(False))

    assert final.read_bytes() == b"mainending"


def test_video_without_audio_receives_silent_track_before_combining(tmp_path):
    main, _, _ = _inputs(tmp_path)

    class AudioLessRenderer(FinalBGMRenderer):
        def _has_audio(self, video_file: Path) -> bool:
            return False

        def _duration(self, video_file: Path) -> float:
            return 1.0

        def _run(self, command: list[str], action: str) -> None:
            Path(command[-1]).write_bytes(b"video-with-silence")

    renderer = AudioLessRenderer(FinalRenderSettings(320, 180, 1))
    temporary_files: list[Path] = []
    prepared = renderer._with_silence_if_needed(main, tmp_path / "combined.mp4", "main", temporary_files)

    assert prepared.is_file()
    assert temporary_files == [prepared]
