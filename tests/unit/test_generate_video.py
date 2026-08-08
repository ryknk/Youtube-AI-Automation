"""FFmpeg動画生成のユニットテスト。"""

import unittest
from pathlib import Path
from unittest.mock import patch

from youtube_generator.infrastructure.ffmpeg_video_renderer import (
    FfmpegVideoRenderer,
    RenderImage,
    RenderScene,
    VideoRenderSettings,
)


class FakeDurationProvider:
    def get_duration_seconds(self, audio_file: Path) -> float:
        return 1.0


def _single_image_scene(index: int, duration: float) -> RenderScene:
    return RenderScene(
        index,
        (RenderImage(Path(f"scene{index:02d}_01.png"), duration),),
        Path(f"scene{index:02d}.mp3"),
        duration,
    )


class GenerateVideoTests(unittest.TestCase):
    def test_build_command_uses_h264_zoom_subtitles_and_bgm_mix(self) -> None:
        renderer = FfmpegVideoRenderer(
            duration_provider=FakeDurationProvider(),
            settings=VideoRenderSettings(1920, 1080, 30, True, Path("assets/bgm.mp3"), 0.15),
        )
        scenes = (_single_image_scene(1, 2.0), _single_image_scene(2, 3.0))

        command = renderer.build_command(scenes, Path("subtitles.srt"), Path("video.mp4"))
        filter_graph = command[command.index("-filter_complex") + 1]

        self.assertIn("zoompan", filter_graph)
        self.assertIn("subtitles=filename=", filter_graph)
        self.assertIn(
            "force_style='FontName=Arial,FontSize=36,PrimaryColour=&H00FFFFFF,"
            "Alignment=2,MarginV=80,BorderStyle=1,BackColour=&H66000000'",
            filter_graph,
        )
        self.assertIn("volume=0.15", filter_graph)
        self.assertIn("amix=inputs=2:duration=first:weights='1 1':normalize=0", filter_graph)
        self.assertEqual(command[command.index("-c:v") + 1], "libx264")
        self.assertEqual(command[command.index("-pix_fmt") + 1], "yuv420p")
        self.assertEqual(command[command.index("-r") + 1], "30")
        self.assertEqual(command.count("-framerate"), len(scenes))
        for image_file in ("scene01_01.png", "scene02_01.png"):
            image_index = command.index(image_file)
            self.assertEqual(command[image_index - 5:image_index - 3], ["-framerate", "30"])

    def test_gap_seconds_extends_last_scene_image_within_same_zoompan_and_pads_audio(self) -> None:
        renderer = FfmpegVideoRenderer(
            duration_provider=FakeDurationProvider(),
            settings=VideoRenderSettings(1920, 1080, 30, True, Path("assets/bgm.mp3"), 0.15, gap_seconds=1.0),
        )
        scenes = (_single_image_scene(1, 2.0), _single_image_scene(2, 3.0))

        command = renderer.build_command(scenes, Path("subtitles.srt"), Path("video.mp4"))
        filter_graph = command[command.index("-filter_complex") + 1]

        # 最後のシーン(scene02_01.png)は同じ入力のまま表示秒数だけ延長され、zoompanフィルターも1つしか生成されない
        # （別セグメントに分けないため、ズームが on=0 にリセットされない）。
        self.assertEqual(command.count("scene02_01.png"), 1)
        scene02_index = command.index("scene02_01.png")
        self.assertEqual(command[scene02_index - 2], "4.000")
        self.assertEqual(filter_graph.count("zoompan"), 2)
        self.assertNotIn("anullsrc", filter_graph)
        # ナレーション終了後は無音でpadされ、映像の延長秒数と音声の長さが揃う。
        self.assertIn("apad=pad_dur=1.000", filter_graph)
        self.assertIn("concat=n=2:v=1:a=1", filter_graph)
        # BGMのatrim対象秒数にも延長分(2.0+3.0+1.0=6.0秒)が反映される。
        self.assertIn("atrim=duration=6.000", filter_graph)

    def test_gap_seconds_zero_keeps_original_duration_and_no_padding(self) -> None:
        renderer = FfmpegVideoRenderer(
            duration_provider=FakeDurationProvider(),
            settings=VideoRenderSettings(1920, 1080, 30, False, Path("unused.mp3"), 0.0),
        )
        scenes = (_single_image_scene(1, 2.0), _single_image_scene(2, 3.0))

        command = renderer.build_command(scenes, Path("subtitles.srt"), Path("video.mp4"))
        filter_graph = command[command.index("-filter_complex") + 1]

        scene02_index = command.index("scene02_01.png")
        self.assertEqual(command[scene02_index - 2], "3.000")
        self.assertNotIn("apad", filter_graph)
        self.assertIn("concat=n=2:v=1:a=1", filter_graph)

    def test_multi_image_scene_concatenates_images_before_scene_level_concat(self) -> None:
        renderer = FfmpegVideoRenderer(
            duration_provider=FakeDurationProvider(),
            settings=VideoRenderSettings(1920, 1080, 30, False, Path("unused.mp3"), 0.0),
        )
        scene = RenderScene(
            1,
            (RenderImage(Path("scene01_01.png"), 5.0), RenderImage(Path("scene01_02.png"), 4.0)),
            Path("scene01.mp3"), 9.0,
        )

        command = renderer.build_command((scene,), Path("subtitles.srt"), Path("video.mp4"))
        filter_graph = command[command.index("-filter_complex") + 1]

        self.assertEqual(command.count("-framerate"), 2)
        self.assertEqual(filter_graph.count("zoompan"), 2)
        self.assertIn("concat=n=2:v=1:a=0", filter_graph)
        self.assertIn("concat=n=1:v=1:a=1", filter_graph)

    def test_find_scenes_distributes_duration_across_multiple_images_at_sentence_boundaries(self) -> None:
        import tempfile

        class FixedDurationProvider:
            def get_duration_seconds(self, audio_file: Path) -> float:
                return 10.0

        with tempfile.TemporaryDirectory() as raw_dir:
            scenes_dir = Path(raw_dir)
            (scenes_dir / "scene01_01.png").write_bytes(b"img1")
            (scenes_dir / "scene01_02.png").write_bytes(b"img2")
            (scenes_dir / "scene01.mp3").write_bytes(b"audio")
            (scenes_dir / "scene01.txt").write_text("あ" * 30 + "。" + "い" * 30 + "。", encoding="utf-8")

            renderer = FfmpegVideoRenderer(
                duration_provider=FixedDurationProvider(),
                settings=VideoRenderSettings(1920, 1080, 30, False, Path("unused.mp3"), 0.0),
            )

            scenes = renderer._find_scenes(scenes_dir)

            self.assertEqual(len(scenes), 1)
            scene = scenes[0]
            self.assertEqual(len(scene.images), 2)
            # 2文が均等な長さのため、文の境界(5秒付近)にスナップして概ね半分ずつに分かれる。
            self.assertAlmostEqual(sum(image.duration_seconds for image in scene.images), 10.0, places=2)
            self.assertAlmostEqual(scene.images[0].duration_seconds, 5.0, delta=1.0)

    def test_extend_last_subtitle_cue_only_shifts_final_cue_end_time(self) -> None:
        srt_text = (
            "1\n00:00:00,000 --> 00:00:02,000\n最初の字幕\n\n"
            "2\n00:00:02,000 --> 00:00:05,000\n最後の字幕\n"
        )

        extended = FfmpegVideoRenderer._extend_last_subtitle_cue(srt_text, 1.5)

        self.assertIn("00:00:00,000 --> 00:00:02,000", extended)
        self.assertIn("00:00:02,000 --> 00:00:06,500", extended)
        self.assertNotIn("00:00:02,000 --> 00:00:05,000", extended)

    def test_render_uses_extended_temporary_subtitle_file_and_cleans_up(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as raw_dir:
            scenes_dir = Path(raw_dir)
            (scenes_dir / "scene01_01.png").write_bytes(b"img")
            (scenes_dir / "scene01.mp3").write_bytes(b"audio")
            (scenes_dir / "subtitles.srt").write_text(
                "1\n00:00:00,000 --> 00:00:01,000\n字幕\n", encoding="utf-8",
            )
            renderer = FfmpegVideoRenderer(
                duration_provider=FakeDurationProvider(),
                settings=VideoRenderSettings(1920, 1080, 30, False, Path("unused.mp3"), 0.0, gap_seconds=1.0),
            )
            output_file = scenes_dir / "video.mp4"
            captured_commands: list[list[str]] = []
            temp_subtitle_file = scenes_dir / ".subtitles_gap.srt"
            captured_temp_subtitle_text: list[str] = []

            def fake_run(command, **kwargs):  # type: ignore[no-untyped-def]
                captured_commands.append(command)
                captured_temp_subtitle_text.append(temp_subtitle_file.read_text(encoding="utf-8"))
                output_file.write_bytes(b"video")

                class Result:
                    returncode = 0

                return Result()

            with patch("youtube_generator.infrastructure.ffmpeg_video_renderer.subprocess.run", side_effect=fake_run):
                renderer.render(scenes_dir, output_file)

            self.assertFalse(temp_subtitle_file.exists())
            filter_graph = captured_commands[0][captured_commands[0].index("-filter_complex") + 1]
            self.assertIn(".subtitles_gap.srt", filter_graph)
            # 元の終了時刻(00:00:01,000)ではなく、gap_seconds分延長された時刻が焼き込み対象になる。
            self.assertIn("00:00:02,000", captured_temp_subtitle_text[0])
            self.assertNotIn("00:00:01,000", captured_temp_subtitle_text[0])

    def test_fade_out_seconds_zero_adds_no_fade_filter(self) -> None:
        renderer = FfmpegVideoRenderer(
            duration_provider=FakeDurationProvider(),
            settings=VideoRenderSettings(1920, 1080, 30, False, Path("unused.mp3"), 0.0),
        )
        scenes = (_single_image_scene(1, 2.0), _single_image_scene(2, 3.0))

        command = renderer.build_command(scenes, Path("subtitles.srt"), Path("video.mp4"))
        filter_graph = command[command.index("-filter_complex") + 1]

        self.assertNotIn("fade=t=", filter_graph)

    def test_fade_out_seconds_applies_fade_at_end_of_total_duration(self) -> None:
        renderer = FfmpegVideoRenderer(
            duration_provider=FakeDurationProvider(),
            settings=VideoRenderSettings(
                1920, 1080, 30, False, Path("unused.mp3"), 0.0, gap_seconds=1.0, fade_out_seconds=0.5,
            ),
        )
        scenes = (_single_image_scene(1, 2.0), _single_image_scene(2, 3.0))

        command = renderer.build_command(scenes, Path("subtitles.srt"), Path("video.mp4"))
        filter_graph = command[command.index("-filter_complex") + 1]

        # 合計秒数(2.0+3.0+1.0=6.0)の末尾0.5秒だけ画面がフェードアウトする。
        self.assertIn("fade=t=out:st=5.500:d=0.500", filter_graph)
        self.assertIn("[video_subtitled]fade=t=out", filter_graph)

    def test_subtitle_background_box_is_added_to_force_style(self) -> None:
        renderer = FfmpegVideoRenderer(
            duration_provider=FakeDurationProvider(),
            settings=VideoRenderSettings(
                1920, 1080, 30, False, Path("unused.mp3"), 0.0,
                subtitle_box_enabled=True, subtitle_background_color="#123456",
                subtitle_background_opacity=0.75,
            ),
        )

        command = renderer.build_command(
            (_single_image_scene(1, 2.0),),
            Path("subtitles.srt"), Path("video.mp4"),
        )
        filter_graph = command[command.index("-filter_complex") + 1]

        self.assertIn("BorderStyle=4", filter_graph)
        self.assertIn("BackColour=&H40563412", filter_graph)
        self.assertIn("Outline=0,Shadow=4", filter_graph)
