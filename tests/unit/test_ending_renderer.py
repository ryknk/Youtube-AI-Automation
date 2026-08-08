"""エンディング動画レンダラーのテスト。"""

from pathlib import Path

from youtube_generator.ending.renderer import EndingRenderRequest, FfmpegEndingRenderer
from youtube_generator.infrastructure.ffmpeg_video_renderer import VideoRenderSettings


def test_ending_images_are_fixed_without_zoom_movement_or_fade(tmp_path: Path) -> None:
    renderer = FfmpegEndingRenderer(
        VideoRenderSettings(
            width=1920, height=1080, fps=30, bgm_enabled=False,
            bgm_file=tmp_path / "unused.mp3", bgm_volume=0.0,
        )
    )
    request = EndingRenderRequest(
        audio_file=tmp_path / "ending.mp3", subtitle_file=None,
        image_files=(tmp_path / "ending.png",), output_file=tmp_path / "ending.mp4",
        duration_seconds=5.0,
    )

    command = renderer.build_command(request)
    filters = command[command.index("-filter_complex") + 1]

    assert "zoompan" not in filters
    assert "fade=t=" not in filters
    assert "scale=1920:1080:force_original_aspect_ratio=decrease" in filters
    assert "pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=black" in filters
    assert "trim=duration=5.000" in filters


def test_fade_in_seconds_applies_fade_at_start_of_ending(tmp_path: Path) -> None:
    renderer = FfmpegEndingRenderer(
        VideoRenderSettings(
            width=1920, height=1080, fps=30, bgm_enabled=False,
            bgm_file=tmp_path / "unused.mp3", bgm_volume=0.0,
            fade_in_seconds=0.5,
        )
    )
    request = EndingRenderRequest(
        audio_file=tmp_path / "ending.mp3", subtitle_file=None,
        image_files=(tmp_path / "ending.png",), output_file=tmp_path / "ending.mp4",
        duration_seconds=5.0,
    )

    command = renderer.build_command(request)
    filters = command[command.index("-filter_complex") + 1]

    assert "[visual]fade=t=in:st=0:d=0.500[video]" in filters


def test_multiple_ending_images_remain_fixed_and_are_concatenated(tmp_path: Path) -> None:
    renderer = FfmpegEndingRenderer(
        VideoRenderSettings(
            width=1280, height=720, fps=30, bgm_enabled=False,
            bgm_file=tmp_path / "unused.mp3", bgm_volume=0.0,
        )
    )
    request = EndingRenderRequest(
        audio_file=tmp_path / "ending.mp3", subtitle_file=None,
        image_files=(tmp_path / "first.png", tmp_path / "second.png"),
        output_file=tmp_path / "ending.mp4", duration_seconds=6.0,
    )

    command = renderer.build_command(request)
    filters = command[command.index("-filter_complex") + 1]

    assert "zoompan" not in filters
    assert filters.count("trim=duration=3.000") == 2
    assert "[v0][v1]concat=n=2:v=1:a=0[visual]" in filters


def test_end_padding_extends_last_image_and_pads_silent_audio(tmp_path: Path) -> None:
    renderer = FfmpegEndingRenderer(
        VideoRenderSettings(
            width=1920, height=1080, fps=30, bgm_enabled=False,
            bgm_file=tmp_path / "unused.mp3", bgm_volume=0.0,
        )
    )
    request = EndingRenderRequest(
        audio_file=tmp_path / "ending.mp3", subtitle_file=None,
        image_files=(tmp_path / "first.png", tmp_path / "second.png"),
        output_file=tmp_path / "ending.mp4", duration_seconds=6.0,
        end_padding_seconds=1.0,
    )

    command = renderer.build_command(request)
    filters = command[command.index("-filter_complex") + 1]

    # 最初の画像は元の秒数のまま、最後の画像だけend_padding_seconds分延びる。
    assert filters.count("trim=duration=3.000") == 1
    assert filters.count("trim=duration=4.000") == 1
    last_image_index = command.index(str(tmp_path / "second.png"))
    assert command[last_image_index - 2] == "4.000"
    assert "apad=pad_dur=1.000" in filters


def test_start_padding_extends_first_image_and_delays_narration_audio(tmp_path: Path) -> None:
    renderer = FfmpegEndingRenderer(
        VideoRenderSettings(
            width=1920, height=1080, fps=30, bgm_enabled=False,
            bgm_file=tmp_path / "unused.mp3", bgm_volume=0.0,
        )
    )
    request = EndingRenderRequest(
        audio_file=tmp_path / "ending.mp3", subtitle_file=None,
        image_files=(tmp_path / "first.png", tmp_path / "second.png"),
        output_file=tmp_path / "ending.mp4", duration_seconds=6.0,
        start_padding_seconds=0.5,
    )

    command = renderer.build_command(request)
    filters = command[command.index("-filter_complex") + 1]

    # 最初の画像だけstart_padding_seconds分延び、最後の画像は元の秒数のまま。
    assert filters.count("trim=duration=3.500") == 1
    assert filters.count("trim=duration=3.000") == 1
    first_image_index = command.index(str(tmp_path / "first.png"))
    assert command[first_image_index - 2] == "3.500"
    assert "adelay=delays=500:all=1,apad=pad_dur=0.000" in filters


def test_start_and_end_padding_both_extend_single_image(tmp_path: Path) -> None:
    renderer = FfmpegEndingRenderer(
        VideoRenderSettings(
            width=1920, height=1080, fps=30, bgm_enabled=False,
            bgm_file=tmp_path / "unused.mp3", bgm_volume=0.0,
        )
    )
    request = EndingRenderRequest(
        audio_file=tmp_path / "ending.mp3", subtitle_file=None,
        image_files=(tmp_path / "ending.png",), output_file=tmp_path / "ending.mp4",
        duration_seconds=5.0, start_padding_seconds=0.5, end_padding_seconds=1.0,
    )

    command = renderer.build_command(request)
    filters = command[command.index("-filter_complex") + 1]

    # 1枚のみの場合は最初=最後の画像なので、start+end両方が加算される。
    assert "trim=duration=6.500" in filters
    assert "adelay=delays=500:all=1,apad=pad_dur=1.000" in filters


def test_start_padding_zero_omits_adelay_filter(tmp_path: Path) -> None:
    renderer = FfmpegEndingRenderer(
        VideoRenderSettings(
            width=1920, height=1080, fps=30, bgm_enabled=False,
            bgm_file=tmp_path / "unused.mp3", bgm_volume=0.0,
        )
    )
    request = EndingRenderRequest(
        audio_file=tmp_path / "ending.mp3", subtitle_file=None,
        image_files=(tmp_path / "ending.png",), output_file=tmp_path / "ending.mp4",
        duration_seconds=5.0,
    )

    command = renderer.build_command(request)
    filters = command[command.index("-filter_complex") + 1]

    assert "adelay" not in filters


def test_end_padding_extends_bgm_trim_to_total_duration(tmp_path: Path) -> None:
    bgm_file = tmp_path / "bgm.mp3"
    bgm_file.write_bytes(b"bgm")
    renderer = FfmpegEndingRenderer(
        VideoRenderSettings(
            width=1920, height=1080, fps=30, bgm_enabled=True,
            bgm_file=bgm_file, bgm_volume=0.08,
        )
    )
    request = EndingRenderRequest(
        audio_file=tmp_path / "ending.mp3", subtitle_file=None,
        image_files=(tmp_path / "ending.png",), output_file=tmp_path / "ending.mp4",
        duration_seconds=5.0, end_padding_seconds=1.0,
    )

    command = renderer.build_command(request)
    filters = command[command.index("-filter_complex") + 1]

    assert "atrim=duration=6.000" in filters
    assert "apad=pad_dur=1.000" in filters


def test_ending_bgm_mix_disables_amix_normalize(tmp_path: Path) -> None:
    bgm_file = tmp_path / "bgm.mp3"
    bgm_file.write_bytes(b"bgm")
    renderer = FfmpegEndingRenderer(
        VideoRenderSettings(
            width=1920, height=1080, fps=30, bgm_enabled=True,
            bgm_file=bgm_file, bgm_volume=0.08,
        )
    )
    request = EndingRenderRequest(
        audio_file=tmp_path / "ending.mp3", subtitle_file=None,
        image_files=(tmp_path / "ending.png",), output_file=tmp_path / "ending.mp4",
        duration_seconds=5.0,
    )

    command = renderer.build_command(request)
    filters = command[command.index("-filter_complex") + 1]

    assert "amix=inputs=2:duration=shortest:weights='1 1':normalize=0" in filters


def test_ending_subtitle_style_uses_position_alignment_and_margin(tmp_path: Path) -> None:
    renderer = FfmpegEndingRenderer(
        VideoRenderSettings(
            width=1280, height=720, fps=30, bgm_enabled=False,
            bgm_file=tmp_path / "unused.mp3", bgm_volume=0.0,
            subtitle_font="Noto Sans JP", subtitle_size=30,
            subtitle_color="&H0000FFFF", subtitle_position="top",
            subtitle_alignment="right", subtitle_bottom_margin=42,
            subtitle_box_enabled=True, subtitle_background_color="#102030",
            subtitle_background_opacity=0.5,
        )
    )
    request = EndingRenderRequest(
        audio_file=tmp_path / "ending.mp3", subtitle_file=tmp_path / "ending.srt",
        image_files=(tmp_path / "ending.png",), output_file=tmp_path / "ending.mp4",
        duration_seconds=5.0,
    )

    command = renderer.build_command(request)
    filters = command[command.index("-filter_complex") + 1]

    assert "FontName=Noto Sans JP,FontSize=30,PrimaryColour=&H0000FFFF" in filters
    assert "Alignment=9,MarginV=42" in filters
    assert "BorderStyle=4,BackColour=&H80302010,Outline=0,Shadow=4" in filters
