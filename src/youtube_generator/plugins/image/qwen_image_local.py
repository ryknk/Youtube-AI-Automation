"""Qwen-Imageをローカル実行するSelf-host画像生成プラグイン。

Hugging Face Diffusersを利用する。torch/diffusersはSelf-host専用の任意依存関係
（requirements-qwen-image-local.txt または pip install .[qwen-image-local]）のため、
モジュール読み込み時ではなく実際に利用する箇所（モデルロード時）で遅延importする。
"""

import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image
from PIL.PngImagePlugin import PngInfo

from youtube_generator.exceptions import ImageGenerationError
from youtube_generator.logger import get_logger
from youtube_generator.plugins.base.image_provider import ImageProvider


DEFAULT_MODEL_ID = "Qwen/Qwen-Image"
_ALLOWED_DEVICES = {"auto", "cuda", "cpu", "mps"}
_ALLOWED_DTYPES = {"auto", "float16", "bfloat16", "float32"}
_INSTALL_HINT = (
    "Self-host画像生成にはqwen-image-local用の任意依存関係が必要です。"
    "`pip install -r requirements-qwen-image-local.txt` または `pip install .[qwen-image-local]` を実行してください。"
)


@dataclass(frozen=True, slots=True)
class QwenImageLocalSettings:
    """``image.qwen_image_local`` 設定の型付き表現。"""

    model_id: str = DEFAULT_MODEL_ID
    device: str = "auto"
    dtype: str = "auto"
    num_inference_steps: int = 50
    # Qwen-Imageは公式サンプルでtrue_cfg_scale=4.0を使用している（distilled guidance_scaleではない）。
    true_cfg_scale: float = 4.0
    width: int = 1664
    height: int = 928
    seed: int | None = None
    # 公式サンプルはnegative_promptに空文字列を明示的に渡している。
    negative_prompt: str = ""
    # 任意のプロンプト追記文字列。プロンプト末尾に ", <prompt_suffix>" として付加される。
    # 既定は空文字列（何も付加しない）。config.yamlのimage.qwen_image_local.prompt_suffixで指定する。
    # 例: Qwen-Image公式ドキュメント推奨の品質向上用決まり文句や、画面内への意図しない
    # 文字描画を防ぐ制約など。
    prompt_suffix: str = ""
    enable_cpu_offload: bool = False
    enable_attention_slicing: bool = False
    low_vram_mode: bool = False
    model_cache_dir: str | None = None
    allow_cpu: bool = False
    fallback_provider: str | None = None

    @classmethod
    def from_mapping(cls, values: dict[str, Any]) -> "QwenImageLocalSettings":
        """config.yamlの ``image.qwen_image_local`` 辞書から設定を組み立てる。"""
        try:
            device = str(values.get("device", "auto")).lower()
            if device not in _ALLOWED_DEVICES:
                raise ValueError(f"device は {sorted(_ALLOWED_DEVICES)} のいずれかにしてください: {device}")
            dtype = str(values.get("dtype", "auto")).lower()
            if dtype not in _ALLOWED_DTYPES:
                raise ValueError(f"dtype は {sorted(_ALLOWED_DTYPES)} のいずれかにしてください: {dtype}")
            seed_value = values.get("seed")
            fallback_provider = values.get("fallback_provider")
            model_cache_dir = values.get("model_cache_dir")
            return cls(
                model_id=str(values.get("model_id", DEFAULT_MODEL_ID)),
                device=device,
                dtype=dtype,
                num_inference_steps=int(values.get("num_inference_steps", 50)),
                true_cfg_scale=float(values.get("true_cfg_scale", 4.0)),
                width=int(values.get("width", 1664)),
                height=int(values.get("height", 928)),
                seed=int(seed_value) if seed_value is not None else None,
                negative_prompt=str(values.get("negative_prompt", "")),
                prompt_suffix=str(values.get("prompt_suffix", "")),
                enable_cpu_offload=bool(values.get("enable_cpu_offload", False)),
                enable_attention_slicing=bool(values.get("enable_attention_slicing", False)),
                low_vram_mode=bool(values.get("low_vram_mode", False)),
                model_cache_dir=str(model_cache_dir) if model_cache_dir else None,
                allow_cpu=bool(values.get("allow_cpu", False)),
                fallback_provider=str(fallback_provider).lower() if fallback_provider else None,
            )
        except (TypeError, ValueError) as error:
            raise ValueError(f"config.yaml の image.qwen_image_local 設定が不正です: {error}") from error


class QwenImageLocalImageProvider(ImageProvider):
    """Diffusers経由でQwen-Imageをローカル実行する画像生成プラグイン。

    モデルは初回生成時に遅延ロードし、以後は同一インスタンス内で再利用する。
    APIキーは不要。CUDAメモリ不足・モデル未取得時は原因が分かるエラーを送出する。
    """

    def __init__(
        self, settings: QwenImageLocalSettings, output_size: str,
        resize_to_output_size: bool = True,
    ) -> None:
        self._settings = settings
        self._output_width, self._output_height = self._parse_size(output_size)
        # シーン画像は動画レンダリング時にffmpegのscaleフィルタで最終解像度へ引き伸ばされるため、
        # ここでの整形は不要（Falseにして生成解像度のまま保存し、cover-crop分の処理を省略する）。
        # サムネイル用途はレンダリング側でリサイズされないため、Trueのままthumbnail_sizeへ
        # 正確に整形する必要がある（PluginManager._create_qwen_image_local_provider参照）。
        self._resize_to_output_size = resize_to_output_size
        self._pipeline: Any = None
        self._resolved_device: str | None = None
        self._resolved_dtype: str | None = None
        self._logger = get_logger(__name__)

    def generate_image(self, prompt: str, output_file: Path) -> None:
        if not prompt.strip():
            raise ImageGenerationError("画像生成プロンプトが空です。")
        effective_prompt = self._apply_prompt_suffix(prompt)
        torch = self._import_torch()
        pipeline = self._ensure_pipeline()
        seed = self._settings.seed if self._settings.seed is not None else random.randint(0, 2**31 - 1)
        generator = torch.Generator(device=self._generator_device()).manual_seed(seed)
        self._logger.info(
            "Qwen-Imageローカル画像生成を開始します: model_id=%s, device=%s, dtype=%s, "
            "steps=%d, true_cfg_scale=%s, size=%dx%d, seed=%d",
            self._settings.model_id, self._resolved_device, self._resolved_dtype,
            self._settings.num_inference_steps, self._settings.true_cfg_scale,
            self._settings.width, self._settings.height, seed,
        )
        generation_kwargs: dict[str, Any] = {
            "prompt": effective_prompt,
            "negative_prompt": self._settings.negative_prompt,
            "width": self._settings.width,
            "height": self._settings.height,
            "num_inference_steps": self._settings.num_inference_steps,
            "true_cfg_scale": self._settings.true_cfg_scale,
            "generator": generator,
        }

        started_at = time.perf_counter()
        try:
            result = pipeline(**generation_kwargs)
        except Exception as error:  # diffusers/torch側の例外は多様なため広く捕捉する
            raise self._wrap_generation_error(error, torch) from error
        generation_seconds = time.perf_counter() - started_at

        image = result.images[0]
        fitted_image = self._fit_to_output_size(image) if self._resize_to_output_size else image
        output_file.parent.mkdir(parents=True, exist_ok=True)
        self._save_with_metadata(fitted_image, output_file, seed)
        self._logger.info(
            "Qwen-Imageローカル画像生成が完了しました: file=%s, generation_seconds=%.2f, "
            "generated_size=%dx%d, output_size=%dx%d, resized=%s",
            output_file, generation_seconds, self._settings.width, self._settings.height,
            self._output_width, self._output_height, self._resize_to_output_size,
        )

    def release(self) -> None:
        """ジョブ終了時にロード済みモデルを明示的に解放する。"""
        if self._pipeline is None:
            return
        self._logger.info("Qwen-Imageローカルモデルを解放します。")
        self._pipeline = None
        self._resolved_device = None
        self._resolved_dtype = None
        try:
            torch = self._import_torch()
        except ImageGenerationError:
            return
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    def _ensure_pipeline(self) -> Any:
        """同一設定であればロード済みPipelineを再利用し、画像ごとの再ロードを避ける。"""
        if self._pipeline is not None:
            return self._pipeline
        torch = self._import_torch()
        diffusers = self._import_diffusers()
        device = self._resolve_device(torch)
        dtype = self._resolve_dtype(torch, device)
        self._logger.info(
            "Qwen-Imageローカルモデルをロードします: model_id=%s, device=%s, dtype=%s, cache_dir=%s",
            self._settings.model_id, device, dtype, self._settings.model_cache_dir or "(既定のHFキャッシュ)",
        )
        started_at = time.perf_counter()
        try:
            pipeline = diffusers.DiffusionPipeline.from_pretrained(
                self._settings.model_id, torch_dtype=dtype, cache_dir=self._settings.model_cache_dir,
            )
        except Exception as error:  # huggingface_hub/diffusers側の例外は多様なため広く捕捉する
            raise self._wrap_load_error(error) from error

        if self._settings.low_vram_mode and hasattr(pipeline, "enable_sequential_cpu_offload"):
            pipeline.enable_sequential_cpu_offload()
        elif self._settings.enable_cpu_offload and hasattr(pipeline, "enable_model_cpu_offload"):
            pipeline.enable_model_cpu_offload()
        else:
            pipeline = pipeline.to(device)
        if self._settings.enable_attention_slicing and hasattr(pipeline, "enable_attention_slicing"):
            pipeline.enable_attention_slicing()

        load_seconds = time.perf_counter() - started_at
        self._logger.info("Qwen-Imageローカルモデルのロードが完了しました: %.2f秒", load_seconds)
        self._pipeline = pipeline
        self._resolved_device = device
        self._resolved_dtype = str(dtype)
        return pipeline

    def _generator_device(self) -> str:
        if self._settings.low_vram_mode or self._settings.enable_cpu_offload:
            return "cpu"
        return self._resolved_device or "cpu"

    def _resolve_device(self, torch: Any) -> str:
        requested = self._settings.device
        if requested != "auto":
            if requested == "cpu" and not self._settings.allow_cpu:
                raise ImageGenerationError(
                    "device=cpuが指定されましたが、allow_cpuがfalseのため停止しました。"
                    "CPU実行は長時間かかります。意図する場合はconfig.yamlの"
                    "image.qwen_image_local.allow_cpuをtrueにしてください。"
                )
            if requested == "cuda" and not torch.cuda.is_available():
                raise ImageGenerationError(
                    "device=cudaが指定されましたが、CUDAが利用できません。"
                    "GPU/ドライバ/CUDA対応PyTorchの導入状況を確認してください。"
                )
            self._logger.info("画像生成deviceを使用します（設定で明示指定）: %s", requested)
            return requested
        if torch.cuda.is_available():
            device_name = torch.cuda.get_device_name(0)
            self._logger.info("画像生成deviceを自動検出しました: cuda (%s)", device_name)
            return "cuda"
        if not self._settings.allow_cpu:
            raise ImageGenerationError(
                "利用可能なGPU（CUDA）を検出できませんでした。CPU実行は非常に長時間かかるため、"
                "意図せず停止したように見えることを避けるため自動実行しませんでした。"
                "CPU実行を許可する場合はconfig.yamlのimage.qwen_image_local.allow_cpuをtrueにしてください。"
            )
        self._logger.info("画像生成deviceを自動検出しました: cpu（CUDA未検出、allow_cpu=true）")
        return "cpu"

    def _resolve_dtype(self, torch: Any, device: str) -> Any:
        requested = self._settings.dtype
        if requested == "auto":
            return torch.bfloat16 if device == "cuda" else torch.float32
        if requested == "float16":
            return torch.float16
        if requested == "bfloat16":
            return torch.bfloat16
        return torch.float32

    def _fit_to_output_size(self, image: "Image.Image") -> "Image.Image":
        """アスペクト比を維持したまま、中央クロップ（cover）で最終サイズへ整形する。"""
        target_size = (self._output_width, self._output_height)
        if image.size == target_size:
            return image
        source_width, source_height = image.size
        scale = max(self._output_width / source_width, self._output_height / source_height)
        resized_size = (round(source_width * scale), round(source_height * scale))
        resized = image.resize(resized_size, Image.LANCZOS)
        left = (resized_size[0] - self._output_width) // 2
        top = (resized_size[1] - self._output_height) // 2
        return resized.crop((left, top, left + self._output_width, top + self._output_height))

    def _apply_prompt_suffix(self, prompt: str) -> str:
        """config.yamlで指定された任意の文字列をプロンプト末尾に付加する。"""
        if not self._settings.prompt_suffix:
            return prompt
        return f"{prompt}, {self._settings.prompt_suffix}"

    def _save_with_metadata(self, image: "Image.Image", output_file: Path, seed: int) -> None:
        """再現性のため、使用seedなどをPNGメタデータへ埋め込んで保存する。"""
        metadata = PngInfo()
        metadata.add_text("qwen_image_local:model_id", self._settings.model_id)
        metadata.add_text("qwen_image_local:seed", str(seed))
        metadata.add_text("qwen_image_local:num_inference_steps", str(self._settings.num_inference_steps))
        metadata.add_text("qwen_image_local:true_cfg_scale", str(self._settings.true_cfg_scale))
        metadata.add_text("qwen_image_local:generated_width", str(self._settings.width))
        metadata.add_text("qwen_image_local:generated_height", str(self._settings.height))
        image.convert("RGB").save(output_file, format="PNG", pnginfo=metadata)

    def _wrap_load_error(self, error: Exception) -> ImageGenerationError:
        self._logger.exception(
            "Qwen-Imageローカルモデルのロードに失敗しました: model_id=%s, cache_dir=%s",
            self._settings.model_id, self._settings.model_cache_dir or "(既定のHFキャッシュ)",
        )
        return ImageGenerationError(
            f"Qwen-Imageローカルモデルのロードに失敗しました。model_id={self._settings.model_id}, "
            f"cache_dir={self._settings.model_cache_dir or '(既定のHFキャッシュ)'}。"
            "モデル未取得（初回ダウンロード失敗・ネットワーク不通）や、diffusersのバージョンが"
            "QwenImagePipelineに対応していない可能性があります。ネットワーク接続と"
            "https://huggingface.co/Qwen/Qwen-Image のモデルカード、"
            "diffusersのバージョン（`pip install -U diffusers`での最新化）を確認してください。"
            f"詳細: {error}"
        )

    def _wrap_generation_error(self, error: Exception, torch: Any) -> ImageGenerationError:
        is_cuda_oom = self._is_cuda_out_of_memory(error, torch)
        self._logger.exception(
            "Qwen-Imageローカル画像生成に失敗しました: model_id=%s, device=%s, dtype=%s, "
            "size=%dx%d, cuda_oom=%s",
            self._settings.model_id, self._resolved_device, self._resolved_dtype,
            self._settings.width, self._settings.height, is_cuda_oom,
        )
        guidance = (
            "CUDAメモリ不足の可能性があります。Qwen-Imageは約20Bパラメータと大きいモデルです。"
            "width/heightやnum_inference_stepsを減らす、enable_cpu_offload/low_vram_modeを"
            "有効化する、他のGPUプロセスを終了する等を検討してください。"
            if is_cuda_oom else
            "生成パラメータ（プロンプト・width/height・true_cfg_scale等）を確認してください。"
        )
        return ImageGenerationError(
            "Qwen-Imageローカル画像生成に失敗しました。"
            f" model_id={self._settings.model_id}, device={self._resolved_device}, "
            f"dtype={self._resolved_dtype}, size={self._settings.width}x{self._settings.height}, "
            f"cuda_oom={is_cuda_oom}。失敗理由: {error}。{guidance}"
        )

    @staticmethod
    def _is_cuda_out_of_memory(error: Exception, torch: Any) -> bool:
        oom_type = getattr(getattr(torch, "cuda", None), "OutOfMemoryError", None)
        if oom_type is not None and isinstance(error, oom_type):
            return True
        return "out of memory" in str(error).lower()

    @staticmethod
    def _parse_size(size: str) -> tuple[int, int]:
        try:
            width_text, height_text = size.lower().split("x", maxsplit=1)
            return int(width_text), int(height_text)
        except (ValueError, AttributeError) as error:
            raise ValueError(f"画像サイズの形式が不正です: {size}") from error

    @staticmethod
    def _import_torch() -> Any:
        try:
            import torch
        except ImportError as error:
            raise ImageGenerationError(f"torchがインストールされていません。{_INSTALL_HINT}") from error
        return torch

    @staticmethod
    def _import_diffusers() -> Any:
        try:
            import diffusers
        except ImportError as error:
            raise ImageGenerationError(f"diffusersがインストールされていません。{_INSTALL_HINT}") from error
        return diffusers
