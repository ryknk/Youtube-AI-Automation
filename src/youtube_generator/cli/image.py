"""ローカルSelf-host画像生成環境を確認するためのCLI。

`local-check` はモデルのダウンロードや画像生成、APIの呼び出しを一切行わない、
読み取り専用の接続・環境確認コマンド。`test-generate` のみ、明示操作時に
実際に1枚のテスト画像を生成する。

対象プロバイダーは config.yaml の `providers.image`（辞書形式なら`scene`）で
選択されたものを使用する。Self-host以外のプロバイダー（bfl/openai）が
選択されている場合、`local-check`は対応外である旨を表示する。
"""

import argparse
import importlib.metadata
import os
import sys
from pathlib import Path

from youtube_generator.config import load_settings
from youtube_generator.exceptions import ImageGenerationError
from youtube_generator.logger import configure_logging
from youtube_generator.plugins.image.flux_schnell_local_image import (
    FluxSchnellLocalImageProvider,
    FluxSchnellLocalSettings,
)
from youtube_generator.plugins.image.qwen_image_local import (
    QwenImageLocalImageProvider,
    QwenImageLocalSettings,
)
from youtube_generator.plugins.image.qwen_image_nunchaku_local import (
    QwenImageNunchakuLocalImageProvider,
    QwenImageNunchakuLocalSettings,
)
from youtube_generator.plugins.manager import PluginManager
from youtube_generator.services.retry import RetryPolicy
from youtube_generator.services.video_settings import load_video_settings


def run_image(arguments: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="main.py image")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("local-check")
    test_generate = commands.add_parser("test-generate")
    test_generate.add_argument(
        "--output", type=Path, default=None,
        help="テスト画像の保存先（既定: output/local_image_check/test_image.png）",
    )
    test_generate.add_argument(
        "--prompt", default="A calm landscape, clean 2D digital illustration, non-photorealistic.",
        help="テスト生成に使用するプロンプト",
    )
    args = parser.parse_args(arguments)

    settings = load_settings()
    configure_logging(settings.log_level, settings.log_dir)
    video_settings = load_video_settings(settings.config_dir / "config.yaml")
    values = video_settings.values
    image_values = values["image"]
    provider_settings = values["providers"]
    text_settings = values["text"]
    if not isinstance(image_values, dict) or not isinstance(provider_settings, dict) or not isinstance(text_settings, dict):
        raise ValueError("config.yaml の image / providers / text 設定が不正です。")

    plugin_manager = PluginManager(settings, provider_settings, text_settings)
    provider_name = plugin_manager.image_provider_name("scene")

    if args.command == "local-check":
        _run_local_check(provider_name, image_values)
        return
    _run_test_generate(
        plugin_manager, image_values, values["retry"], provider_name,
        args.prompt, args.output, settings.output_dir,
    )


def _run_local_check(provider_name: str, image_values: dict) -> None:
    """画像を生成せず、APIも呼ばずに実行環境のみを確認する。"""
    if provider_name == "flux_schnell_local":
        flux_values = image_values.get("flux_schnell_local", {})
        if not isinstance(flux_values, dict):
            raise ValueError("config.yaml の image.flux_schnell_local 設定が不正です。")
        _run_flux_local_check(FluxSchnellLocalSettings.from_mapping(flux_values), image_values)
        return
    if provider_name == "qwen_image_local":
        qwen_values = image_values.get("qwen_image_local", {})
        if not isinstance(qwen_values, dict):
            raise ValueError("config.yaml の image.qwen_image_local 設定が不正です。")
        _run_qwen_image_local_check(QwenImageLocalSettings.from_mapping(qwen_values), image_values)
        return
    if provider_name == "qwen_image_nunchaku_local":
        nunchaku_values = image_values.get("qwen_image_nunchaku_local", {})
        if not isinstance(nunchaku_values, dict):
            raise ValueError("config.yaml の image.qwen_image_nunchaku_local 設定が不正です。")
        _run_qwen_image_nunchaku_local_check(
            QwenImageNunchakuLocalSettings.from_mapping(nunchaku_values), image_values,
        )
        return
    print(f"providers.image.scene には現在 '{provider_name}' が設定されています。")
    print(
        "local-checkはSelf-hostプロバイダー"
        "（flux_schnell_local / qwen_image_local / qwen_image_nunchaku_local）専用です。"
    )


def _print_common_torch_diffusers_status() -> None:
    try:
        import torch
    except ImportError:
        print("[NG] torch が見つかりません。")
        return
    print(f"[OK] torch: {torch.__version__}")

    cuda_available = torch.cuda.is_available()
    if cuda_available:
        device_name = torch.cuda.get_device_name(0)
        total_memory_gb = torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
        free_bytes, _total_bytes = torch.cuda.mem_get_info(0)
        free_memory_gb = free_bytes / (1024 ** 3)
        bf16_supported = torch.cuda.is_bf16_supported()
        print(f"[OK] CUDA利用可能: GPU={device_name}, VRAM合計={total_memory_gb:.1f}GB, VRAM空き={free_memory_gb:.1f}GB")
        print(f"[{'OK' if bf16_supported else 'NG'}] bfloat16サポート: {bf16_supported}")
    else:
        print("[NG] CUDAが利用可能なGPUを検出できませんでした。")

    try:
        import diffusers
        print(f"[OK] diffusers: {diffusers.__version__}")
    except ImportError:
        print("[NG] diffusers が見つかりません。")


def _run_flux_local_check(flux_settings: FluxSchnellLocalSettings, image_values: dict) -> None:
    print("=== FLUX.1 Schnell Self-host 環境確認 ===")
    print(f"model_id: {flux_settings.model_id}")
    if flux_settings.transformer_path:
        transformer_file = Path(flux_settings.transformer_path)
        if transformer_file.is_file():
            print(f"[OK] transformer_path を検出しました: {transformer_file}")
        else:
            print(f"[NG] transformer_path が見つかりません: {transformer_file}")
    print(f"設定device: {flux_settings.device} / 設定dtype: {flux_settings.dtype}")
    print(f"allow_cpu: {flux_settings.allow_cpu}")
    print(f"scene_size: {image_values.get('scene_size')} / thumbnail_size: {image_values.get('thumbnail_size')}")
    print(f"生成size(width x height): {flux_settings.width}x{flux_settings.height}")
    print(f"requirements-flux-local.txt / pip install .[flux-local] が未導入の場合は依存関係エラーになります。")

    _print_common_torch_diffusers_status()

    cache_dir = _resolve_model_cache_dir(flux_settings.model_cache_dir)
    repo_dir = _model_repo_dir(cache_dir, flux_settings.model_id)
    if repo_dir.is_dir() and any(repo_dir.rglob("*.safetensors")):
        print(f"[OK] モデルのローカルキャッシュを検出しました: {repo_dir}")
    else:
        print(f"[NG] モデルのローカルキャッシュが見つかりません（初回実行時にダウンロードされます）: {repo_dir}")

    try:
        FluxSchnellLocalImageProvider(flux_settings, str(image_values.get("scene_size", "1920x1080")))
        print("[OK] Providerの構築に成功しました（モデルロード・画像生成は未実施）。")
    except ValueError as error:
        print(f"[NG] Providerの構築に失敗しました: {error}")


def _run_qwen_image_local_check(qwen_settings: QwenImageLocalSettings, image_values: dict) -> None:
    print("=== Qwen-Image Self-host 環境確認 ===")
    print(f"model_id: {qwen_settings.model_id}")
    print(f"設定device: {qwen_settings.device} / 設定dtype: {qwen_settings.dtype}")
    print(f"allow_cpu: {qwen_settings.allow_cpu}")
    print(f"scene_size: {image_values.get('scene_size')} / thumbnail_size: {image_values.get('thumbnail_size')}")
    print(f"生成size(width x height): {qwen_settings.width}x{qwen_settings.height}")
    print("requirements-qwen-image-local.txt / pip install .[qwen-image-local] が未導入の場合は依存関係エラーになります。")

    _print_common_torch_diffusers_status()

    cache_dir = _resolve_model_cache_dir(qwen_settings.model_cache_dir)
    repo_dir = _model_repo_dir(cache_dir, qwen_settings.model_id)
    if repo_dir.is_dir() and any(repo_dir.rglob("*.safetensors")):
        print(f"[OK] モデルのローカルキャッシュを検出しました: {repo_dir}")
    else:
        print(f"[NG] モデルのローカルキャッシュが見つかりません（初回実行時にダウンロードされます）: {repo_dir}")

    try:
        QwenImageLocalImageProvider(qwen_settings, str(image_values.get("scene_size", "1920x1080")))
        print("[OK] Providerの構築に成功しました（モデルロード・画像生成は未実施）。")
    except ValueError as error:
        print(f"[NG] Providerの構築に失敗しました: {error}")


def _run_qwen_image_nunchaku_local_check(
    nunchaku_settings: QwenImageNunchakuLocalSettings, image_values: dict,
) -> None:
    print("=== Qwen-Image (nunchaku 4bit量子化) Self-host 環境確認 ===")
    print(f"base_model_id: {nunchaku_settings.base_model_id}")
    print(f"transformer_repo_id: {nunchaku_settings.transformer_repo_id}")
    print(f"precision: {nunchaku_settings.precision} / rank: {nunchaku_settings.rank}")
    print(f"scene_size: {image_values.get('scene_size')} / thumbnail_size: {image_values.get('thumbnail_size')}")
    print(f"生成size(width x height): {nunchaku_settings.width}x{nunchaku_settings.height}")
    print(
        "requirements-qwen-image-nunchaku-local.txt / pip install .[qwen-image-nunchaku-local] "
        "が未導入の場合は依存関係エラーになります。"
    )

    print(f"Pythonバージョン: {sys.version.split()[0]}")
    if sys.version_info[:2] >= (3, 14):
        print(
            "[NG] nunchakuのプリビルドwheelは現時点でPython 3.10〜3.13向けのみ配布されています"
            "（https://github.com/nunchaku-tech/nunchaku/releases）。"
            "現在の環境はPython 3.14以上のため、別途Python 3.10〜3.13の環境を用意するか、"
            "nunchakuをソースからビルドする必要があります。"
        )

    _print_common_torch_diffusers_status()

    try:
        from nunchaku.models.transformers.transformer_qwenimage import (  # noqa: F401
            NunchakuQwenImageTransformer2DModel,
        )
        nunchaku_version = importlib.metadata.version("nunchaku")
        print(f"[OK] nunchaku: {nunchaku_version}")
    except ImportError as error:
        print(f"[NG] nunchaku が見つかりません: {error}")
    except importlib.metadata.PackageNotFoundError:
        print("[OK] nunchaku: (バージョン不明)")

    try:
        QwenImageNunchakuLocalImageProvider(
            nunchaku_settings, str(image_values.get("scene_size", "1920x1080")),
        )
        print("[OK] Providerの構築に成功しました（モデルロード・画像生成は未実施）。")
    except ValueError as error:
        print(f"[NG] Providerの構築に失敗しました: {error}")


def _run_test_generate(
    plugin_manager: PluginManager, image_values: dict, retry_settings: object, provider_name: str,
    prompt: str, output: Path | None, default_output_dir: Path,
) -> None:
    """明示操作時のみ、config.yamlで選択中のプロバイダーで実際に1枚のテスト画像を生成する。"""
    if not isinstance(retry_settings, dict):
        raise ValueError("config.yaml の retry 設定が不正です。")
    output_file = output or (default_output_dir / "local_image_check" / "test_image.png")
    provider = plugin_manager.create_image_provider(image_values, RetryPolicy.from_settings(retry_settings))
    print(f"プロバイダー '{provider_name}' でテスト画像を生成します: {output_file}")
    try:
        provider.generate_image(prompt, output_file)
    except ImageGenerationError as error:
        print(f"[NG] テスト画像の生成に失敗しました: {error}")
        raise SystemExit(1) from error
    finally:
        release = getattr(provider, "release", None)
        if callable(release):
            release()
    print(f"[OK] テスト画像を保存しました: {output_file}")


def _resolve_model_cache_dir(model_cache_dir: str | None) -> Path:
    if model_cache_dir:
        return Path(model_cache_dir)
    hf_home = os.environ.get("HF_HOME")
    if hf_home:
        return Path(hf_home) / "hub"
    return Path.home() / ".cache" / "huggingface" / "hub"


def _model_repo_dir(cache_dir: Path, model_id: str) -> Path:
    return cache_dir / ("models--" + model_id.replace("/", "--"))
