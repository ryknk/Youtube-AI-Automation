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


if __name__ == "__main__":
    unittest.main()
