"""アライメントプロバイダー選択ファクトリのテスト。"""

import unittest

from youtube_generator.plugins.alignment.factory import create_alignment_provider
from youtube_generator.plugins.alignment.stable_ts_alignment import StableTSAlignmentProvider


class CreateAlignmentProviderTests(unittest.TestCase):
    def test_creates_stable_ts_provider_with_settings(self) -> None:
        provider = create_alignment_provider({"provider": "stable_ts", "language": "en", "model": "medium"})

        self.assertIsInstance(provider, StableTSAlignmentProvider)
        self.assertEqual(provider._model_name, "medium")  # noqa: SLF001
        self.assertEqual(provider._language, "en")  # noqa: SLF001

    def test_defaults_to_stable_ts_when_provider_omitted(self) -> None:
        provider = create_alignment_provider({})

        self.assertIsInstance(provider, StableTSAlignmentProvider)
        self.assertEqual(provider._model_name, "base")  # noqa: SLF001
        self.assertEqual(provider._language, "ja")  # noqa: SLF001

    def test_rejects_unsupported_provider(self) -> None:
        with self.assertRaisesRegex(ValueError, "alignment_provider"):
            create_alignment_provider({"provider": "unknown"})


if __name__ == "__main__":
    unittest.main()
