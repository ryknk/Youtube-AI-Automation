"""nunchaku(SVDQuant 4bit量子化)版Qwen-Imageをローカル実行するSelf-host画像生成プラグイン。

Hugging Face Diffusers + nunchakuを利用する。torch/diffusers/nunchakuはSelf-host専用の
任意依存関係（requirements-qwen-image-nunchaku-local.txt または
pip install .[qwen-image-nunchaku-local]）のため、モジュール読み込み時ではなく実際に
利用する箇所（モデルロード時）で遅延importする。

nunchakuは通常のpipパッケージインデックスではなく、torch/CUDA/Pythonバージョンに
対応したプリビルドwheelを個別に導入する形式で配布されている
（https://github.com/nunchaku-tech/nunchaku/releases）。2026-08-01時点でcp310〜cp313
向けのwheelのみが提供されており、Python 3.14環境では追加対応（別環境の用意やソース
ビルド）が必要になる場合がある。

実装はnunchaku公式サンプル
（https://github.com/nunchaku-tech/nunchaku/blob/main/examples/v1/qwen-image.py）の
構成（NunchakuQwenImageTransformer2DModelでtransformerのみ量子化版に差し替え、
GPU VRAM量に応じてenable_model_cpu_offload/set_offload+enable_sequential_cpu_offloadを
切り替える）に準拠している。
"""

import gc
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


DEFAULT_BASE_MODEL_ID = "Qwen/Qwen-Image"
DEFAULT_TRANSFORMER_REPO_ID = "nunchaku-tech/nunchaku-qwen-image"
_ALLOWED_PRECISIONS = {"auto", "int4", "nvfp4"}
_ALLOWED_RANKS = {32, 128}
_INSTALL_HINT = (
    "Self-host画像生成にはqwen-image-nunchaku-local用の任意依存関係が必要です。"
    "`pip install -r requirements-qwen-image-nunchaku-local.txt` または "
    "`pip install .[qwen-image-nunchaku-local]` を実行してください。"
    "nunchakuは通常のpip install nunchakuでは導入できず、"
    "https://github.com/nunchaku-tech/nunchaku/releases のプリビルドwheelを"
    "お使いのtorch/CUDA/Pythonバージョンに合わせて個別にインストールする必要があります。"
)


@dataclass(frozen=True, slots=True)
class QwenImageNunchakuLocalSettings:
    """``image.qwen_image_nunchaku_local`` 設定の型付き表現。"""

    base_model_id: str = DEFAULT_BASE_MODEL_ID
    transformer_repo_id: str = DEFAULT_TRANSFORMER_REPO_ID
    # auto: nunchaku.utils.get_precision()でGPU世代から自動判定（Blackwell系はnvfp4、
    # それ以外はint4）。int4 / nvfp4 も明示指定可。
    precision: str = "auto"
    # 32: 高速（軽量） / 128: 高品質（重い）
    rank: int = 32
    # 公式サンプルの分岐しきい値（GB）。これを超える場合はenable_model_cpu_offload、
    # 以下の場合はtransformer.set_offload+enable_sequential_cpu_offloadを使う。
    offload_threshold_gb: float = 18.0
    # 低VRAM時（offload_threshold_gb以下）のtransformer.set_offload()に渡すパラメータ。
    # 公式サンプルの既定値（use_pin_memory=False, num_blocks_on_gpu=1）に合わせている。
    # use_pin_memory=Trueにすると、環境によってはpin_memory()確保時にCUDAメモリ不足で
    # 失敗することがある。
    low_vram_use_pin_memory: bool = False
    low_vram_num_blocks_on_gpu: int = 1
    num_inference_steps: int = 50
    true_cfg_scale: float = 4.0
    width: int = 1664
    height: int = 928
    seed: int | None = None
    negative_prompt: str = ""
    # 任意のプロンプト追記文字列。プロンプト末尾に ", <prompt_suffix>" として付加される。
    # 既定は空文字列（何も付加しない）。config.yamlのimage.qwen_image_nunchaku_local.prompt_suffixで
    # 指定する。例: Qwen-Image公式ドキュメント推奨の品質向上用決まり文句や、画面内への意図しない
    # 文字描画を防ぐ制約など。
    prompt_suffix: str = ""
    model_cache_dir: str | None = None
    fallback_provider: str | None = None

    @classmethod
    def from_mapping(cls, values: dict[str, Any]) -> "QwenImageNunchakuLocalSettings":
        """config.yamlの ``image.qwen_image_nunchaku_local`` 辞書から設定を組み立てる。"""
        try:
            precision = str(values.get("precision", "auto")).lower()
            if precision not in _ALLOWED_PRECISIONS:
                raise ValueError(f"precision は {sorted(_ALLOWED_PRECISIONS)} のいずれかにしてください: {precision}")
            rank = int(values.get("rank", 32))
            if rank not in _ALLOWED_RANKS:
                raise ValueError(f"rank は {sorted(_ALLOWED_RANKS)} のいずれかにしてください: {rank}")
            seed_value = values.get("seed")
            fallback_provider = values.get("fallback_provider")
            model_cache_dir = values.get("model_cache_dir")
            return cls(
                base_model_id=str(values.get("base_model_id", DEFAULT_BASE_MODEL_ID)),
                transformer_repo_id=str(values.get("transformer_repo_id", DEFAULT_TRANSFORMER_REPO_ID)),
                precision=precision,
                rank=rank,
                offload_threshold_gb=float(values.get("offload_threshold_gb", 18.0)),
                low_vram_use_pin_memory=bool(values.get("low_vram_use_pin_memory", False)),
                low_vram_num_blocks_on_gpu=int(values.get("low_vram_num_blocks_on_gpu", 1)),
                num_inference_steps=int(values.get("num_inference_steps", 50)),
                true_cfg_scale=float(values.get("true_cfg_scale", 4.0)),
                width=int(values.get("width", 1664)),
                height=int(values.get("height", 928)),
                seed=int(seed_value) if seed_value is not None else None,
                negative_prompt=str(values.get("negative_prompt", "")),
                prompt_suffix=str(values.get("prompt_suffix", "")),
                model_cache_dir=str(model_cache_dir) if model_cache_dir else None,
                fallback_provider=str(fallback_provider).lower() if fallback_provider else None,
            )
        except (TypeError, ValueError) as error:
            raise ValueError(
                f"config.yaml の image.qwen_image_nunchaku_local 設定が不正です: {error}"
            ) from error


class QwenImageNunchakuLocalImageProvider(ImageProvider):
    """nunchaku(SVDQuant 4bit量子化)版Qwen-Imageをローカル実行する画像生成プラグイン。

    モデルは初回生成時に遅延ロードし、以後は同一インスタンス内で再利用する。
    APIキーは不要。nunchakuはCUDA専用の量子化推論カーネルを使うため、CPU実行には対応しない。
    """

    def __init__(
        self, settings: QwenImageNunchakuLocalSettings, output_size: str,
        resize_to_output_size: bool = True,
    ) -> None:
        self._settings = settings
        self._output_width, self._output_height = self._parse_size(output_size)
        # シーン画像は動画レンダリング時にffmpegのscaleフィルタで最終解像度へ引き伸ばされるため、
        # ここでの整形は不要（Falseにして生成解像度のまま保存し、cover-crop分の処理を省略する）。
        # サムネイル用途はレンダリング側でリサイズされないため、Trueのままthumbnail_sizeへ
        # 正確に整形する必要がある（PluginManager._create_qwen_image_nunchaku_local_provider参照）。
        self._resize_to_output_size = resize_to_output_size
        self._pipeline: Any = None
        self._logger = get_logger(__name__)

    def generate_image(self, prompt: str, output_file: Path) -> None:
        if not prompt.strip():
            raise ImageGenerationError("画像生成プロンプトが空です。")
        effective_prompt = self._apply_prompt_suffix(prompt)
        torch = self._import_torch()
        pipeline = self._ensure_pipeline()
        seed = self._settings.seed if self._settings.seed is not None else random.randint(0, 2**31 - 1)
        generator = torch.Generator(device="cuda").manual_seed(seed)
        self._logger.info(
            "Qwen-Image(nunchaku)ローカル画像生成を開始します: base_model_id=%s, "
            "transformer_repo_id=%s, precision=%s, rank=%d, steps=%d, true_cfg_scale=%s, "
            "size=%dx%d, seed=%d",
            self._settings.base_model_id, self._settings.transformer_repo_id,
            self._settings.precision, self._settings.rank, self._settings.num_inference_steps,
            self._settings.true_cfg_scale, self._settings.width, self._settings.height, seed,
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
        except Exception as error:  # diffusers/torch/nunchaku側の例外は多様なため広く捕捉する
            raise self._wrap_generation_error(error, torch) from error
        generation_seconds = time.perf_counter() - started_at

        image = result.images[0]
        fitted_image = self._fit_to_output_size(image) if self._resize_to_output_size else image
        output_file.parent.mkdir(parents=True, exist_ok=True)
        self._save_with_metadata(fitted_image, output_file, seed)
        self._logger.info(
            "Qwen-Image(nunchaku)ローカル画像生成が完了しました: file=%s, generation_seconds=%.2f, "
            "generated_size=%dx%d, output_size=%dx%d, resized=%s",
            output_file, generation_seconds, self._settings.width, self._settings.height,
            self._output_width, self._output_height, self._resize_to_output_size,
        )

    def release(self) -> None:
        """ジョブ終了時にロード済みモデルを明示的に解放する。"""
        if self._pipeline is None:
            return
        self._logger.info("Qwen-Image(nunchaku)ローカルモデルを解放します。")
        self._pipeline = None
        # enable_sequential_cpu_offload/transformer.set_offloadが張るフックはmodule<->hookの
        # 参照循環を作るため、self._pipeline = Noneだけでは即座に解放されない場合がある。
        # 次に別の大きなモデル（編集用モデル等）をロードする前に、確実にCPU/GPUメモリを
        # 解放するためgc.collect()を明示的に呼ぶ。
        gc.collect()
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
        if not torch.cuda.is_available():
            raise ImageGenerationError(
                "nunchaku版Qwen-ImageはCUDA専用の量子化推論カーネルを使用するため、"
                "CUDAが利用可能なGPUが必要です。CUDA対応PyTorchの導入状況を確認してください。"
            )
        diffusers = self._import_diffusers()
        nunchaku_transformer_cls, nunchaku_utils = self._import_nunchaku()
        self._apply_transformer_cache_dir()

        precision = self._settings.precision
        if precision == "auto":
            precision = nunchaku_utils.get_precision()

        transformer_path = (
            f"{self._settings.transformer_repo_id}/"
            f"svdq-{precision}_r{self._settings.rank}-qwen-image.safetensors"
        )
        self._logger.info(
            "Qwen-Image(nunchaku)ローカルモデルをロードします: base_model_id=%s, "
            "transformer_path=%s, cache_dir=%s",
            self._settings.base_model_id, transformer_path,
            self._settings.model_cache_dir or "(既定のHFキャッシュ)",
        )
        started_at = time.perf_counter()
        try:
            transformer = nunchaku_transformer_cls.from_pretrained(
                transformer_path, cache_dir=self._settings.model_cache_dir,
            )
            pipeline = diffusers.QwenImagePipeline.from_pretrained(
                self._settings.base_model_id, transformer=transformer, torch_dtype=torch.bfloat16,
                cache_dir=self._settings.model_cache_dir,
            )
        except Exception as error:  # huggingface_hub/diffusers/nunchaku側の例外は多様なため広く捕捉する
            raise self._wrap_load_error(error, transformer_path) from error

        gpu_memory_gb = nunchaku_utils.get_gpu_memory()
        if gpu_memory_gb > self._settings.offload_threshold_gb:
            pipeline.enable_model_cpu_offload()
            self._logger.info(
                "GPU VRAM %.1fGB > しきい値 %.1fGBのため enable_model_cpu_offload を使用します。",
                gpu_memory_gb, self._settings.offload_threshold_gb,
            )
        else:
            transformer.set_offload(
                True,
                use_pin_memory=self._settings.low_vram_use_pin_memory,
                num_blocks_on_gpu=self._settings.low_vram_num_blocks_on_gpu,
            )
            # transformerはnunchaku独自のoffload管理下にあるため、diffusers側の
            # sequential offloadフックの対象から明示的に除外する（公式サンプル準拠）。
            pipeline._exclude_from_cpu_offload.append("transformer")
            pipeline.enable_sequential_cpu_offload()
            self._logger.info(
                "GPU VRAM %.1fGB <= しきい値 %.1fGBのため "
                "transformer.set_offload(use_pin_memory=%s, num_blocks_on_gpu=%d) + "
                "enable_sequential_cpu_offload を使用します。",
                gpu_memory_gb, self._settings.offload_threshold_gb,
                self._settings.low_vram_use_pin_memory, self._settings.low_vram_num_blocks_on_gpu,
            )

        load_seconds = time.perf_counter() - started_at
        self._logger.info("Qwen-Image(nunchaku)ローカルモデルのロードが完了しました: %.2f秒", load_seconds)
        self._pipeline = pipeline
        return pipeline

    def _apply_transformer_cache_dir(self) -> None:
        """量子化transformerのダウンロード先をconfig.yamlのmodel_cache_dirへ反映する。

        NunchakuQwenImageTransformer2DModel.from_pretrained()はcache_dir引数を受け取っても
        内部のhf_hub_download()呼び出しへ転送しないため無視される（nunchaku 1.2.1で確認済み）。
        hf_hub_download()はcache_dir未指定時にhuggingface_hub.constants.HF_HUB_CACHEを
        呼び出しごとに参照するため、この定数を直接上書きすることでmodel_cache_dirを反映する。
        diffusers側のQwenImagePipeline.from_pretrained()はcache_dirを明示的に渡しており
        こちらが優先されるため、この上書きによる影響を受けない。
        """
        if not self._settings.model_cache_dir:
            return
        from huggingface_hub import constants as hf_hub_constants
        hf_hub_constants.HF_HUB_CACHE = self._settings.model_cache_dir

    def _apply_prompt_suffix(self, prompt: str) -> str:
        """config.yamlで指定された任意の文字列をプロンプト末尾に付加する。"""
        if not self._settings.prompt_suffix:
            return prompt
        return f"{prompt}, {self._settings.prompt_suffix}"

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

    def _save_with_metadata(self, image: "Image.Image", output_file: Path, seed: int) -> None:
        """再現性のため、使用seedなどをPNGメタデータへ埋め込んで保存する。"""
        metadata = PngInfo()
        metadata.add_text("qwen_image_nunchaku_local:base_model_id", self._settings.base_model_id)
        metadata.add_text("qwen_image_nunchaku_local:transformer_repo_id", self._settings.transformer_repo_id)
        metadata.add_text("qwen_image_nunchaku_local:precision", self._settings.precision)
        metadata.add_text("qwen_image_nunchaku_local:rank", str(self._settings.rank))
        metadata.add_text("qwen_image_nunchaku_local:seed", str(seed))
        metadata.add_text("qwen_image_nunchaku_local:num_inference_steps", str(self._settings.num_inference_steps))
        metadata.add_text("qwen_image_nunchaku_local:true_cfg_scale", str(self._settings.true_cfg_scale))
        image.convert("RGB").save(output_file, format="PNG", pnginfo=metadata)

    def _wrap_load_error(self, error: Exception, transformer_path: str) -> ImageGenerationError:
        self._logger.exception(
            "Qwen-Image(nunchaku)ローカルモデルのロードに失敗しました: base_model_id=%s, transformer_path=%s",
            self._settings.base_model_id, transformer_path,
        )
        return ImageGenerationError(
            f"Qwen-Image(nunchaku)ローカルモデルのロードに失敗しました。"
            f"base_model_id={self._settings.base_model_id}, transformer_path={transformer_path}。"
            "nunchakuのバージョンとお使いのtorch/CUDA/Pythonの組み合わせが対応しているか、"
            "指定したprecision/rankの量子化ファイルが存在するかを、"
            "https://huggingface.co/nunchaku-tech/nunchaku-qwen-image で確認してください。"
            f"詳細: {error}"
        )

    def _wrap_generation_error(self, error: Exception, torch: Any) -> ImageGenerationError:
        is_cuda_oom = self._is_cuda_out_of_memory(error, torch)
        self._logger.exception(
            "Qwen-Image(nunchaku)ローカル画像生成に失敗しました: base_model_id=%s, size=%dx%d, cuda_oom=%s",
            self._settings.base_model_id, self._settings.width, self._settings.height, is_cuda_oom,
        )
        guidance = (
            "CUDAメモリ不足の可能性があります。offload_threshold_gbを下げてsequential offloadを"
            "使う、rankを32に下げる、width/height・num_inference_stepsを減らす、"
            "他のGPUプロセスを終了する等を検討してください。"
            if is_cuda_oom else
            "生成パラメータ（プロンプト・width/height・true_cfg_scale等）を確認してください。"
        )
        return ImageGenerationError(
            "Qwen-Image(nunchaku)ローカル画像生成に失敗しました。"
            f" base_model_id={self._settings.base_model_id}, "
            f"size={self._settings.width}x{self._settings.height}, cuda_oom={is_cuda_oom}。"
            f"失敗理由: {error}。{guidance}"
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

    @staticmethod
    def _import_nunchaku() -> tuple[Any, Any]:
        try:
            from nunchaku.models.transformers.transformer_qwenimage import (
                NunchakuQwenImageTransformer2DModel,
            )
            from nunchaku import utils as nunchaku_utils
        except ImportError as error:
            raise ImageGenerationError(f"nunchakuがインストールされていません。{_INSTALL_HINT}") from error
        return NunchakuQwenImageTransformer2DModel, nunchaku_utils
