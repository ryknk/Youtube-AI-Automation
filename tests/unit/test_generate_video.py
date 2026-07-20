"""FFmpeg動画生成のユニットテスト。"""

import unittest
from pathlib import Path

from youtube_generator.infrastructure.ffmpeg_video_renderer import FfmpegVideoRenderer, RenderScene, VideoRenderSettings


class FakeDurationProvider:
    def get_duration_seconds(self, audio_file: Path) -> float:
        return 1.0


class GenerateVideoTests(unittest.TestCase):
    def test_build_command_uses_h264_zoom_subtitles_and_bgm_mix(self) -> None:
        renderer = FfmpegVideoRenderer(
            duration_provider=FakeDurationProvider(),
            settings=VideoRenderSettings(1920, 1080, 30, True, Path("assets/bgm.mp3"), 0.15),
        )
        scenes = (RenderScene(1, Path("scene01.png"), Path("scene01.mp3"), 2.0), RenderScene(2, Path("scene02.png"), Path("scene02.mp3"), 3.0))

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
        self.assertIn("amix=inputs=2:duration=first:weights='1 1'", filter_graph)
        self.assertEqual(command[command.index("-c:v") + 1], "libx264")
        self.assertEqual(command[command.index("-pix_fmt") + 1], "yuv420p")
        self.assertEqual(command[command.index("-r") + 1], "30")
        self.assertEqual(command.count("-framerate"), len(scenes))
        for image_file in ("scene01.png", "scene02.png"):
            image_index = command.index(image_file)
            self.assertEqual(command[image_index - 5:image_index - 3], ["-framerate", "30"])

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
            (RenderScene(1, Path("scene01.png"), Path("scene01.mp3"), 2.0),),
            Path("subtitles.srt"), Path("video.mp4"),
        )
        filter_graph = command[command.index("-filter_complex") + 1]

        self.assertIn("BorderStyle=3", filter_graph)
        self.assertIn("BackColour=&H40563412", filter_graph)
        self.assertIn("Outline=4,Shadow=0", filter_graph)
