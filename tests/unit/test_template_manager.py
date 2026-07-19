"""ファイルベーステンプレートのテスト。"""

import tempfile
import unittest
from pathlib import Path

from youtube_generator.services.template_service import TemplateManager


class TemplateManagerTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
