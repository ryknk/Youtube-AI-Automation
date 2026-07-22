"""アライメントプラグインの選択ファクトリ。"""

from typing import Any

from youtube_generator.plugins.alignment.stable_ts_alignment import StableTSAlignmentProvider
from youtube_generator.plugins.base.alignment_provider import AlignmentProvider


def create_alignment_provider(alignment_provider_settings: dict[str, Any]) -> AlignmentProvider:
    """config.yamlの``subtitles.alignment_provider``設定からプロバイダーを組み立てる。"""
    provider_name = str(alignment_provider_settings.get("provider", "stable_ts")).lower()
    if provider_name == "stable_ts":
        return StableTSAlignmentProvider(
            model=str(alignment_provider_settings.get("model", "base")),
            language=str(alignment_provider_settings.get("language", "ja")),
        )
    raise ValueError(f"未対応のalignment_providerです: {provider_name}")
