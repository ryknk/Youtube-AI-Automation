"""nunchaku(SVDQuant 4bit量子化)版Qwen-Image-Edit-2509をローカル実行する画像編集プラグイン。

生成済みシーン画像から、字幕・キャプション風の文字が写り込んだ場合に除去する後処理ステップ
として使う。Hugging Face Diffusers + nunchakuを利用する。torch/diffusers/nunchakuは
Self-host専用の任意依存関係（requirements-qwen-image-nunchaku-local.txt。
qwen_image_nunchaku_localと共通）のため、モジュール読み込み時ではなく実際に利用する箇所
（モデルロード時）で遅延importする。

実装はqwen_image_nunchaku_local.pyと同一の構成（NunchakuQwenImageTransformer2DModelで
transformerのみ量子化版に差し替え、GPU VRAM量に応じてenable_model_cpu_offload/
set_offload+enable_sequential_cpu_offloadを切り替える）に準拠している。
"""

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image
from PIL.PngImagePlugin import PngInfo

from youtube_generator.exceptions import ImageEditError
from youtube_generator.logger import get_logger
from youtube_generator.plugins.base.image_editor import ImageEditor


DEFAULT_BASE_MODEL_ID = "Qwen/Qwen-Image-Edit-2509"
DEFAULT_TRANSFORMER_REPO_ID = "nunchaku-tech/nunchaku-qwen-image-edit-2509"
DEFAULT_PROMPT = (
    "Remove the black caption bar and any text at the bottom of the image. "
    "Naturally extend the existing floor, wall, table, or background so the removed area "
    "blends in, matching the surrounding lighting and perspective. Do not mirror or "
    "duplicate any other part of the image. Do not change anything else in the image."
)
_ALLOWED_PRECISIONS = {"auto", "int4", "nvfp4"}
_ALLOWED_RANKS = {32, 128}
_ALLOWED_LIGHTNING_STEPS = {4, 8}
_INSTALL_HINT = (
    "Self-host画像編集にはqwen-image-nunchaku-local用の任意依存関係が必要です。"
    "`pip install -r requirements-qwen-image-nunchaku-local.txt` または "
    "`pip install .[qwen-image-nunchaku-local]` を実行してください。"
    "nunchakuは通常のpip install nunchakuでは導入できず、"
    "https://github.com/nunchaku-tech/nunchaku/releases のプリビルドwheelを"
    "お使いのtorch/CUDA/Pythonバージョンに合わせて個別にインストールする必要があります。"
)


@dataclass(frozen=True, slots=True)
class QwenImageEditNunchakuLocalSettings:
    """``image.qwen_image_edit_nunchaku_local`` 設定の型付き表現。"""

    base_model_id: str = DEFAULT_BASE_MODEL_ID
    transformer_repo_id: str = DEFAULT_TRANSFORMER_REPO_ID
    # auto: nunchaku.utils.get_precision()でGPU世代から自動判定（Blackwell系はnvfp4、
    # それ以外はint4）。int4 / nvfp4 も明示指定可。
    precision: str = "auto"
    # 32: 高速（軽量） / 128: 高品質（重い）
    rank: int = 32
    # 4 または 8 を指定するとLightning蒸留版（その step数専用に最適化）を使用する。
    # nullの場合は非蒸留版を使用し、num_inference_stepsは自由に指定できる
    # （公式サンプルは40 stepsを使用）。
    lightning_steps: int | None = 8
    # nullの場合、lightning_steps指定時はその値、非指定時は40を既定値として使用する。
    num_inference_steps: int | None = None
    true_cfg_scale: float = 4.0
    # 除去・編集内容を指示するプロンプト。既定値は字幕・キャプション帯の除去指示。
    prompt: str = DEFAULT_PROMPT
    # Qwen-Image-Edit系は空文字列だとエラーになるため、公式サンプルに合わせ半角スペースを既定値とする。
    negative_prompt: str = " "
    # 公式サンプルの分岐しきい値（GB）。GPU VRAMがこれを超える場合はenable_model_cpu_offload、
    # 以下の場合はtransformer.set_offload+enable_sequential_cpu_offloadを使う。
    offload_threshold_gb: float = 18.0
    low_vram_use_pin_memory: bool = False
    low_vram_num_blocks_on_gpu: int = 1
    seed: int | None = None
    model_cache_dir: str | None = None

    @classmethod
    def from_mapping(cls, values: dict[str, Any]) -> "QwenImageEditNunchakuLocalSettings":
        """config.yamlの ``image.qwen_image_edit_nunchaku_local`` 辞書から設定を組み立てる。"""
        try:
            precision = str(values.get("precision", "auto")).lower()
            if precision not in _ALLOWED_PRECISIONS:
                raise ValueError(f"precision は {sorted(_ALLOWED_PRECISIONS)} のいずれかにしてください: {precision}")
            rank = int(values.get("rank", 32))
            if rank not in _ALLOWED_RANKS:
                raise ValueError(f"rank は {sorted(_ALLOWED_RANKS)} のいずれかにしてください: {rank}")
            lightning_steps_value = values.get("lightning_steps", 8)
            lightning_steps = int(lightning_steps_value) if lightning_steps_value is not None else None
            if lightning_steps is not None and lightning_steps not in _ALLOWED_LIGHTNING_STEPS:
                raise ValueError(
                    f"lightning_steps は {sorted(_ALLOWED_LIGHTNING_STEPS)} またはnullにしてください: {lightning_steps}"
                )
            num_inference_steps_value = values.get("num_inference_steps")
            num_inference_steps = (
                int(num_inference_steps_value) if num_inference_steps_value is not None else None
            )
            seed_value = values.get("seed")
            model_cache_dir = values.get("model_cache_dir")
            return cls(
                base_model_id=str(values.get("base_model_id", DEFAULT_BASE_MODEL_ID)),
                transformer_repo_id=str(values.get("transformer_repo_id", DEFAULT_TRANSFORMER_REPO_ID)),
                precision=precision,
                rank=rank,
                lightning_steps=lightning_steps,
                num_inference_steps=num_inference_steps,
                true_cfg_scale=float(values.get("true_cfg_scale", 4.0)),
                prompt=str(values.get("prompt", DEFAULT_PROMPT)),
                negative_prompt=str(values.get("negative_prompt", " ")),
                offload_threshold_gb=float(values.get("offload_threshold_gb", 18.0)),
                low_vram_use_pin_memory=bool(values.get("low_vram_use_pin_memory", False)),
                low_vram_num_blocks_on_gpu=int(values.get("low_vram_num_blocks_on_gpu", 1)),
                seed=int(seed_value) if seed_value is not None else None,
                model_cache_dir=str(model_cache_dir) if model_cache_dir else None,
            )
        except (TypeError, ValueError) as error:
            raise ValueError(
                f"config.yaml の image.qwen_image_edit_nunchaku_local 設定が不正です: {error}"
            ) from error

    def resolved_num_inference_steps(self) -> int:
        if self.num_inference_steps is not None:
            return self.num_inference_steps
        return self.lightning_steps if self.lightning_steps is not None else 40


class QwenImageEditNunchakuLocalImageEditor(ImageEditor):
    """nunchaku(SVDQuant 4bit量子化)版Qwen-Image-Edit-2509をローカル実行する画像編集プラグイン。

    モデルは初回編集時に遅延ロードし、以後は同一インスタンス内で再利用する。
    APIキーは不要。nunchakuはCUDA専用の量子化推論カーネルを使うため、CPU実行には対応しない。
    """

    def __init__(self, settings: QwenImageEditNunchakuLocalSettings) -> None:
        self._settings = settings
        self._pipeline: Any = None
        self._logger = get_logger(__name__)

    def edit(self, image_file: Path) -> None:
        torch = self._import_torch()
        pipeline = self._ensure_pipeline()
        seed = self._settings.seed if self._settings.seed is not None else self._random_seed()
        generator = torch.Generator(device="cuda").manual_seed(seed)

        source_image = Image.open(image_file).convert("RGB")
        target_size = source_image.size
        num_inference_steps = self._settings.resolved_num_inference_steps()
        self._logger.info(
            "Qwen-Image-Edit(nunchaku)による画像編集を開始します: file=%s, base_model_id=%s, "
            "transformer_repo_id=%s, steps=%d, true_cfg_scale=%s, size=%dx%d, seed=%d",
            image_file, self._settings.base_model_id, self._settings.transformer_repo_id,
            num_inference_steps, self._settings.true_cfg_scale, target_size[0], target_size[1], seed,
        )
        edit_kwargs: dict[str, Any] = {
            "image": [source_image],
            "prompt": self._settings.prompt,
            "negative_prompt": self._settings.negative_prompt,
            "true_cfg_scale": self._settings.true_cfg_scale,
            "num_inference_steps": num_inference_steps,
            "width": target_size[0],
            "height": target_size[1],
            "generator": generator,
        }

        started_at = time.perf_counter()
        try:
            result = pipeline(**edit_kwargs)
        except Exception as error:  # diffusers/torch/nunchaku側の例外は多様なため広く捕捉する
            raise self._wrap_edit_error(error, torch) from error
        edit_seconds = time.perf_counter() - started_at

        edited_image = self._fit_to_size(result.images[0], target_size)
        self._save_with_metadata(edited_image, image_file, seed, num_inference_steps)
        self._logger.info(
            "Qwen-Image-Edit(nunchaku)による画像編集が完了しました: file=%s, edit_seconds=%.2f",
            image_file, edit_seconds,
        )

    def release(self) -> None:
        """ジョブ終了時にロード済みモデルを明示的に解放する。"""
        if self._pipeline is None:
            return
        self._logger.info("Qwen-Image-Edit(nunchaku)ローカルモデルを解放します。")
        self._pipeline = None
        try:
            torch = self._import_torch()
        except ImageEditError:
            return
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    def _ensure_pipeline(self) -> Any:
        """同一設定であればロード済みPipelineを再利用し、画像ごとの再ロードを避ける。"""
        if self._pipeline is not None:
            return self._pipeline
        torch = self._import_torch()
        if not torch.cuda.is_available():
            raise ImageEditError(
                "nunchaku版Qwen-Image-EditはCUDA専用の量子化推論カーネルを使用するため、"
                "CUDAが利用可能なGPUが必要です。CUDA対応PyTorchの導入状況を確認してください。"
            )
        diffusers = self._import_diffusers()
        nunchaku_transformer_cls, nunchaku_utils = self._import_nunchaku()
        self._apply_transformer_cache_dir()

        precision = self._settings.precision
        if precision == "auto":
            precision = nunchaku_utils.get_precision()

        filename = self._transformer_filename(precision)
        transformer_path = f"{self._settings.transformer_repo_id}/{filename}"
        self._logger.info(
            "Qwen-Image-Edit(nunchaku)ローカルモデルをロードします: base_model_id=%s, "
            "transformer_path=%s, cache_dir=%s",
            self._settings.base_model_id, transformer_path,
            self._settings.model_cache_dir or "(既定のHFキャッシュ)",
        )
        started_at = time.perf_counter()
        try:
            transformer = nunchaku_transformer_cls.from_pretrained(
                transformer_path, cache_dir=self._settings.model_cache_dir,
            )
            pipeline = diffusers.QwenImageEditPlusPipeline.from_pretrained(
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
        self._logger.info("Qwen-Image-Edit(nunchaku)ローカルモデルのロードが完了しました: %.2f秒", load_seconds)
        self._pipeline = pipeline
        return pipeline

    def _transformer_filename(self, precision: str) -> str:
        if self._settings.lightning_steps is not None:
            return (
                f"svdq-{precision}_r{self._settings.rank}-qwen-image-edit-2509-"
                f"lightningv2.0-{self._settings.lightning_steps}steps.safetensors"
            )
        return f"svdq-{precision}_r{self._settings.rank}-qwen-image-edit-2509.safetensors"

    def _apply_transformer_cache_dir(self) -> None:
        """量子化transformerのダウンロード先をconfig.yamlのmodel_cache_dirへ反映する。

        NunchakuQwenImageTransformer2DModel.from_pretrained()はcache_dir引数を受け取っても
        内部のhf_hub_download()呼び出しへ転送しないため無視される（nunchaku 1.2.1で確認済み。
        qwen_image_nunchaku_local.pyと同一の既知の挙動）。hf_hub_download()はcache_dir未指定時に
        huggingface_hub.constants.HF_HUB_CACHEを呼び出しごとに参照するため、この定数を直接
        上書きすることでmodel_cache_dirを反映する。diffusers側のfrom_pretrained()はcache_dirを
        明示的に渡しておりこちらが優先されるため、この上書きによる影響を受けない。
        """
        if not self._settings.model_cache_dir:
            return
        from huggingface_hub import constants as hf_hub_constants
        hf_hub_constants.HF_HUB_CACHE = self._settings.model_cache_dir

    @staticmethod
    def _fit_to_size(image: "Image.Image", target_size: tuple[int, int]) -> "Image.Image":
        """アスペクト比を維持したまま、中央クロップ（cover）で編集前と同じサイズへ整形する。

        QwenImageEditPlusPipelineはwidth/heightを指定しても内部の解像度バケットへ丸める場合が
        あるため、生成後に確実に編集前と同じサイズへ戻す。
        """
        if image.size == target_size:
            return image
        target_width, target_height = target_size
        source_width, source_height = image.size
        scale = max(target_width / source_width, target_height / source_height)
        resized_size = (round(source_width * scale), round(source_height * scale))
        resized = image.resize(resized_size, Image.LANCZOS)
        left = (resized_size[0] - target_width) // 2
        top = (resized_size[1] - target_height) // 2
        return resized.crop((left, top, left + target_width, top + target_height))

    def _save_with_metadata(
        self, image: "Image.Image", output_file: Path, seed: int, num_inference_steps: int,
    ) -> None:
        """再現性のため、使用seedなどをPNGメタデータへ埋め込んで保存する（元画像のメタデータは置き換わる）。"""
        metadata = PngInfo()
        metadata.add_text("qwen_image_edit_nunchaku_local:base_model_id", self._settings.base_model_id)
        metadata.add_text("qwen_image_edit_nunchaku_local:transformer_repo_id", self._settings.transformer_repo_id)
        metadata.add_text("qwen_image_edit_nunchaku_local:precision", self._settings.precision)
        metadata.add_text("qwen_image_edit_nunchaku_local:rank", str(self._settings.rank))
        metadata.add_text("qwen_image_edit_nunchaku_local:seed", str(seed))
        metadata.add_text("qwen_image_edit_nunchaku_local:num_inference_steps", str(num_inference_steps))
        metadata.add_text("qwen_image_edit_nunchaku_local:true_cfg_scale", str(self._settings.true_cfg_scale))
        image.convert("RGB").save(output_file, format="PNG", pnginfo=metadata)

    def _wrap_load_error(self, error: Exception, transformer_path: str) -> ImageEditError:
        self._logger.exception(
            "Qwen-Image-Edit(nunchaku)ローカルモデルのロードに失敗しました: "
            "base_model_id=%s, transformer_path=%s",
            self._settings.base_model_id, transformer_path,
        )
        return ImageEditError(
            f"Qwen-Image-Edit(nunchaku)ローカルモデルのロードに失敗しました。"
            f"base_model_id={self._settings.base_model_id}, transformer_path={transformer_path}。"
            "nunchakuのバージョンとお使いのtorch/CUDA/Pythonの組み合わせが対応しているか、"
            "指定したprecision/rank/lightning_stepsの量子化ファイルが存在するかを、"
            "https://huggingface.co/nunchaku-tech/nunchaku-qwen-image-edit-2509 で確認してください。"
            f"詳細: {error}"
        )

    def _wrap_edit_error(self, error: Exception, torch: Any) -> ImageEditError:
        is_cuda_oom = self._is_cuda_out_of_memory(error, torch)
        self._logger.exception(
            "Qwen-Image-Edit(nunchaku)による画像編集に失敗しました: base_model_id=%s, cuda_oom=%s",
            self._settings.base_model_id, is_cuda_oom,
        )
        guidance = (
            "CUDAメモリ不足の可能性があります。offload_threshold_gbを下げてsequential offloadを"
            "使う、rankを32に下げる、他のGPUプロセスを終了する等を検討してください。"
            if is_cuda_oom else
            "編集パラメータ（prompt・true_cfg_scale等）を確認してください。"
        )
        return ImageEditError(
            "Qwen-Image-Edit(nunchaku)による画像編集に失敗しました。"
            f" base_model_id={self._settings.base_model_id}, cuda_oom={is_cuda_oom}。"
            f"失敗理由: {error}。{guidance}"
        )

    @staticmethod
    def _is_cuda_out_of_memory(error: Exception, torch: Any) -> bool:
        oom_type = getattr(getattr(torch, "cuda", None), "OutOfMemoryError", None)
        if oom_type is not None and isinstance(error, oom_type):
            return True
        return "out of memory" in str(error).lower()

    @staticmethod
    def _random_seed() -> int:
        import random
        return random.randint(0, 2**31 - 1)

    @staticmethod
    def _import_torch() -> Any:
        try:
            import torch
        except ImportError as error:
            raise ImageEditError(f"torchがインストールされていません。{_INSTALL_HINT}") from error
        return torch

    @staticmethod
    def _import_diffusers() -> Any:
        try:
            import diffusers
        except ImportError as error:
            raise ImageEditError(f"diffusersがインストールされていません。{_INSTALL_HINT}") from error
        return diffusers

    @staticmethod
    def _import_nunchaku() -> tuple[Any, Any]:
        try:
            from nunchaku.models.transformers.transformer_qwenimage import (
                NunchakuQwenImageTransformer2DModel,
            )
            from nunchaku import utils as nunchaku_utils
        except ImportError as error:
            raise ImageEditError(f"nunchakuがインストールされていません。{_INSTALL_HINT}") from error
        return NunchakuQwenImageTransformer2DModel, nunchaku_utils
