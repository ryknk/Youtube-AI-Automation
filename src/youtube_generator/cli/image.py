"""FLUX.1 Schnell Self-host環境を確認するためのCLI。

`local-check` はモデルのダウンロードや画像生成、APIの呼び出しを一切行わない、
読み取り専用の接続・環境確認コマンド。`test-generate` のみ、明示操作時に
実際に1枚のテスト画像を生成する。
"""

import argparse
import os
from pathlib import Path

from youtube_generator.config import load_settings
from youtube_generator.exceptions import ImageGenerationError
from youtube_generator.logger import configure_logging
from youtube_generator.plugins.image.flux_schnell_local_image import (
    FluxSchnellLocalImageProvider,
    FluxSchnellLocalSettings,
)
from youtube_generator.services.video_settings import load_video_settings


def run_image(arguments: list[str]) -> None:
    parser = argparse.ArgumentParser(prog="main.py image")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("local-check")
    test_generate = commands.add_parser("test-generate")
    test_generate.add_argument(
        "--output", type=Path, default=None,
        help="テスト画像の保存先（既定: output/flux_local_check/test_image.png）",
    )
    test_generate.add_argument(
        "--prompt", default="A calm landscape, clean 2D digital illustration, non-photorealistic.",
        help="テスト生成に使用するプロンプト",
    )
    args = parser.parse_args(arguments)

    settings = load_settings()
    configure_logging(settings.log_level, settings.log_dir)
    values = load_video_settings(settings.config_dir / "config.yaml").values
    image_values = values["image"]
    if not isinstance(image_values, dict):
        raise ValueError("config.yaml の image 設定が不正です。")
    flux_values = image_values.get("flux_schnell_local", {})
    if not isinstance(flux_values, dict):
        raise ValueError("config.yaml の image.flux_schnell_local 設定が不正です。")
    flux_settings = FluxSchnellLocalSettings.from_mapping(flux_values)

    if args.command == "local-check":
        _run_local_check(flux_settings, image_values)
        return
    _run_test_generate(flux_settings, image_values, args.prompt, args.output, settings.output_dir)


def _run_local_check(flux_settings: FluxSchnellLocalSettings, image_values: dict) -> None:
    """画像を生成せず、APIも呼ばずに実行環境のみを確認する。"""
    print("=== FLUX.1 Schnell Self-host 環境確認 ===")
    print(f"model_id: {flux_settings.model_id}")
    print(f"設定device: {flux_settings.device} / 設定dtype: {flux_settings.dtype}")
    print(f"allow_cpu: {flux_settings.allow_cpu}")
    print(f"scene_size: {image_values.get('scene_size')} / thumbnail_size: {image_values.get('thumbnail_size')}")
    print(f"生成size(width x height): {flux_settings.width}x{flux_settings.height}")

    try:
        import torch
    except ImportError:
        print("[NG] torch が見つかりません。requirements-flux-local.txt をインストールしてください。")
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
        print(f"     CPU実行を許可する設定(allow_cpu)は現在 {flux_settings.allow_cpu} です。")

    try:
        import diffusers
        print(f"[OK] diffusers: {diffusers.__version__}")
    except ImportError:
        print("[NG] diffusers が見つかりません。requirements-flux-local.txt をインストールしてください。")

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


def _run_test_generate(
    flux_settings: FluxSchnellLocalSettings, image_values: dict, prompt: str,
    output: Path | None, default_output_dir: Path,
) -> None:
    """明示操作時のみ、実際に1枚のテスト画像を生成する。"""
    output_file = output or (default_output_dir / "flux_local_check" / "test_image.png")
    provider = FluxSchnellLocalImageProvider(flux_settings, str(image_values.get("scene_size", "1920x1080")))
    print(f"テスト画像を生成します: {output_file}")
    try:
        provider.generate_image(prompt, output_file)
    except ImageGenerationError as error:
        print(f"[NG] テスト画像の生成に失敗しました: {error}")
        raise SystemExit(1) from error
    finally:
        provider.release()
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
