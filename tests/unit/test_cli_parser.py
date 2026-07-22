"""CLI引数パーサーのテスト。"""

import unittest
from pathlib import Path

from youtube_generator.cli.main import create_parser


class CliParserForceFlagTests(unittest.TestCase):
    def test_force_defaults_to_false(self) -> None:
        args = create_parser().parse_args(["--theme", "テスト"])
        self.assertFalse(args.force)

    def test_force_flag_is_parsed_alongside_generate_video(self) -> None:
        args = create_parser().parse_args(["--generate-video", "output/job", "--force"])
        self.assertTrue(args.force)
        self.assertEqual(args.generate_video, Path("output/job"))


if __name__ == "__main__":
    unittest.main()
