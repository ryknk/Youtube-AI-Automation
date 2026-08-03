"""ファイルベーステンプレートのテスト。"""

import tempfile
import unittest
from pathlib import Path

from youtube_generator.services.template_service import TemplateManager


class TemplateManagerTests(unittest.TestCase):
    @staticmethod
    def _write_template(root: Path, template_id: str, video_yaml: str) -> None:
        template_dir = root / template_id
        template_dir.mkdir(parents=True)
        for name in ("prompt.txt", "image_prompt.txt", "title_prompt.txt", "thumbnail_prompt.txt"):
            (template_dir / name).write_text("テスト", encoding="utf-8")
        (template_dir / "video.yaml").write_text(
            f"scene_structure: []\n{video_yaml}", encoding="utf-8",
        )

    def test_loads_template_directory_and_all_prompt_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            template_dir = Path(temporary_directory) / "history"
            template_dir.mkdir()
            (template_dir / "prompt.txt").write_text("台本方針", encoding="utf-8")
            (template_dir / "image_prompt.txt").write_text("画像方針", encoding="utf-8")
            (template_dir / "title_prompt.txt").write_text("タイトル方針", encoding="utf-8")
            (template_dir / "thumbnail_prompt.txt").write_text("サムネイル方針", encoding="utf-8")
            (template_dir / "video.yaml").write_text("display_name: 歴史\nscene_structure: [導入, 解説]\n", encoding="utf-8")

            template = TemplateManager(Path(temporary_directory)).get("history")

        self.assertEqual(template.display_name, "歴史")
        self.assertEqual(template.script_instruction, "台本方針")
        self.assertEqual(template.scene_structure, ("導入", "解説"))
        self.assertEqual(template.title_instruction, "タイトル方針")

    def test_loads_provider_specific_prompt_overrides_when_present(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            template_dir = Path(temporary_directory) / "default"
            template_dir.mkdir()
            (template_dir / "prompt.txt").write_text("台本方針", encoding="utf-8")
            (template_dir / "image_prompt.txt").write_text("既定の画像方針", encoding="utf-8")
            (template_dir / "image_prompt.qwen_image_nunchaku_local.txt").write_text(
                "Qwen専用の画像方針", encoding="utf-8",
            )
            (template_dir / "title_prompt.txt").write_text("タイトル方針", encoding="utf-8")
            (template_dir / "thumbnail_prompt.txt").write_text("既定のサムネイル方針", encoding="utf-8")
            (template_dir / "thumbnail_prompt.bfl.txt").write_text("BFL専用のサムネイル方針", encoding="utf-8")
            (template_dir / "video.yaml").write_text("scene_structure: []\n", encoding="utf-8")

            template = TemplateManager(Path(temporary_directory)).get("default")

        self.assertEqual(template.image_style, "既定の画像方針")
        self.assertEqual(template.image_style_for("qwen_image_nunchaku_local"), "Qwen専用の画像方針")
        self.assertEqual(template.image_style_for("bfl"), "既定の画像方針")
        self.assertEqual(template.thumbnail_instruction, "既定のサムネイル方針")
        self.assertEqual(template.thumbnail_instruction_for("bfl"), "BFL専用のサムネイル方針")
        self.assertEqual(template.thumbnail_instruction_for("openai"), "既定のサムネイル方針")

    def test_resolves_voicevox_settings_from_global_default_and_selected_template(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self._write_template(root, "default", """audio:
  voicevox:
    speaker_id: 3
    speed_scale: 1.1
""")
            self._write_template(root, "history", """audio:
  voicevox:
    speaker_id: 13
    pitch_scale: -0.05
""")
            manager = TemplateManager(root)

            settings = manager.voicevox_audio_settings({
                "model": "unused", "voicevox": {
                    "base_url": "http://127.0.0.1:50021",
                    "speaker_id": 1,
                    "speed_scale": 1.0,
                    "volume_scale": 0.9,
                },
            }, "history")

        self.assertEqual(settings["model"], "unused")
        self.assertEqual(settings["voicevox"], {
            "base_url": "http://127.0.0.1:50021",
            "speaker_id": 13,
            "speed_scale": 1.1,
            "volume_scale": 0.9,
            "pitch_scale": -0.05,
        })

    def test_rejects_invalid_template_voicevox_settings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self._write_template(root, "history", "audio:\n  voicevox: invalid\n")

            with self.assertRaisesRegex(ValueError, "audio.voicevox"):
                TemplateManager(root).voicevox_audio_settings(
                    {"voicevox": {}}, "history",
                )

    def test_resolves_subtitle_settings_from_global_default_and_selected_template(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self._write_template(root, "default", """subtitles:
  font: Noto Sans JP
  size: 28
  max_lines: 2
  background_color: "#000000"
  background_opacity: 0.5
""")
            self._write_template(root, "psychology", """subtitles:
  size: 32
  color: "&H0000FFFF"
  max_chars_per_line: 18
  box_enabled: true
  background_opacity: 0.7
""")
            manager = TemplateManager(root)

            settings = manager.subtitle_settings({
                "font": "Arial", "size": 24, "color": "&H00FFFFFF",
                "max_lines": 1, "timing_mode": "character_ratio",
                "box_enabled": False,
            }, "psychology")

        self.assertEqual(settings, {
            "font": "Noto Sans JP", "size": 32, "color": "&H0000FFFF",
            "max_lines": 2, "timing_mode": "character_ratio",
            "max_chars_per_line": 18, "box_enabled": True,
            "background_color": "#000000", "background_opacity": 0.7,
        })

    def test_rejects_invalid_template_subtitle_settings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            self._write_template(root, "psychology", "subtitles: invalid\n")

            with self.assertRaisesRegex(ValueError, "subtitles"):
                TemplateManager(root).subtitle_settings({}, "psychology")


if __name__ == "__main__":
    unittest.main()
