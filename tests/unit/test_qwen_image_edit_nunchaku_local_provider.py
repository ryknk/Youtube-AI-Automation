"""Qwen-Image-Edit-2509 nunchaku(SVDQuant 4bit量子化)版画像編集プロバイダーのユニットテスト。

torch/diffusers/nunchakuは実際にはインストールしない前提で、
``QwenImageEditNunchakuLocalImageEditor._import_torch``/``_import_diffusers``/
``_import_nunchaku`` をフェイク実装へ差し替えてテストする。実モデルのダウンロード・
ロード・推論は一切行わない。
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from youtube_generator.exceptions import ImageEditError
from youtube_generator.plugins.image.qwen_image_edit_nunchaku_local import (
    QwenImageEditNunchakuLocalImageEditor,
    QwenImageEditNunchakuLocalSettings,
)


class FakeCudaOutOfMemoryError(RuntimeError):
    pass


class FakeCuda:
    def __init__(self, available: bool = True) -> None:
        self._available = available
        self.empty_cache_calls = 0
        self.OutOfMemoryError = FakeCudaOutOfMemoryError

    def is_available(self) -> bool:
        return self._available

    def empty_cache(self) -> None:
        self.empty_cache_calls += 1


class FakeGenerator:
    def __init__(self, device: str) -> None:
        self.device = device
        self.seed: int | None = None

    def manual_seed(self, seed: int) -> "FakeGenerator":
        self.seed = seed
        return self


class FakeTorch:
    def __init__(self, cuda_available: bool = True) -> None:
        self.cuda = FakeCuda(cuda_available)
        self.bfloat16 = "bfloat16"
        self.generators: list[FakeGenerator] = []

    def Generator(self, device: str = "cpu") -> FakeGenerator:  # noqa: N802 - torch API名に合わせる
        generator = FakeGenerator(device)
        self.generators.append(generator)
        return generator


class FakePipelineResult:
    def __init__(self, image: Image.Image) -> None:
        self.images = [image]


class FakePipeline:
    def __init__(self, result_image: Image.Image, raise_error: Exception | None = None) -> None:
        self._result_image = result_image
        self._raise_error = raise_error
        self.calls: list[dict] = []
        self.model_cpu_offload_calls = 0
        self.sequential_cpu_offload_calls = 0
        self._exclude_from_cpu_offload: list[str] = []

    def enable_model_cpu_offload(self) -> None:
        self.model_cpu_offload_calls += 1

    def enable_sequential_cpu_offload(self) -> None:
        self.sequential_cpu_offload_calls += 1

    def __call__(self, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append(kwargs)
        if self._raise_error is not None:
            raise self._raise_error
        return FakePipelineResult(self._result_image)


class FakeTransformer:
    def __init__(self) -> None:
        self.set_offload_calls: list[dict] = []

    def set_offload(self, enabled: bool, use_pin_memory: bool = True, num_blocks_on_gpu: int = 1) -> None:
        self.set_offload_calls.append({
            "enabled": enabled, "use_pin_memory": use_pin_memory, "num_blocks_on_gpu": num_blocks_on_gpu,
        })


class FakeNunchakuTransformerClass:
    def __init__(self, transformer: FakeTransformer, load_error: Exception | None = None) -> None:
        self._transformer = transformer
        self._load_error = load_error
        self.from_pretrained_calls: list[dict] = []

    def from_pretrained(self, path: str, cache_dir=None):  # type: ignore[no-untyped-def]
        self.from_pretrained_calls.append({"path": path, "cache_dir": cache_dir})
        if self._load_error is not None:
            raise self._load_error
        return self._transformer


class FakeQwenImageEditPlusPipelineClass:
    def __init__(self, pipeline: FakePipeline) -> None:
        self._pipeline = pipeline
        self.from_pretrained_calls: list[dict] = []

    def from_pretrained(self, model_id: str, transformer=None, torch_dtype=None, cache_dir=None):  # type: ignore[no-untyped-def]
        self.from_pretrained_calls.append({
            "model_id": model_id, "transformer": transformer, "torch_dtype": torch_dtype, "cache_dir": cache_dir,
        })
        return self._pipeline


class FakeDiffusers:
    def __init__(self, pipeline: FakePipeline) -> None:
        self.QwenImageEditPlusPipeline = FakeQwenImageEditPlusPipelineClass(pipeline)


class FakeNunchakuUtils:
    def __init__(self, gpu_memory_gb: float = 24.0, precision: str = "int4") -> None:
        self._gpu_memory_gb = gpu_memory_gb
        self._precision = precision

    def get_gpu_memory(self) -> float:
        return self._gpu_memory_gb

    def get_precision(self) -> str:
        return self._precision


def _patch_imports(
    torch_module: FakeTorch, diffusers_module: FakeDiffusers,
    transformer_cls: FakeNunchakuTransformerClass, nunchaku_utils: FakeNunchakuUtils,
):
    return (
        patch.object(QwenImageEditNunchakuLocalImageEditor, "_import_torch", staticmethod(lambda: torch_module)),
        patch.object(QwenImageEditNunchakuLocalImageEditor, "_import_diffusers", staticmethod(lambda: diffusers_module)),
        patch.object(
            QwenImageEditNunchakuLocalImageEditor, "_import_nunchaku",
            staticmethod(lambda: (transformer_cls, nunchaku_utils)),
        ),
    )


class QwenImageEditNunchakuLocalSettingsTests(unittest.TestCase):
    def test_from_mapping_applies_defaults(self) -> None:
        settings = QwenImageEditNunchakuLocalSettings.from_mapping({})

        self.assertEqual(settings.base_model_id, "Qwen/Qwen-Image-Edit-2509")
        self.assertEqual(settings.transformer_repo_id, "nunchaku-tech/nunchaku-qwen-image-edit-2509")
        self.assertEqual(settings.precision, "auto")
        self.assertEqual(settings.rank, 32)
        self.assertEqual(settings.lightning_steps, 8)
        self.assertIsNone(settings.num_inference_steps)
        self.assertEqual(settings.resolved_num_inference_steps(), 8)
        self.assertEqual(settings.true_cfg_scale, 4.0)
        self.assertEqual(settings.negative_prompt, " ")
        self.assertEqual(settings.offload_threshold_gb, 18.0)
        self.assertIsNone(settings.seed)
        self.assertIsNone(settings.width)
        self.assertIsNone(settings.height)

    def test_from_mapping_reads_all_fields(self) -> None:
        settings = QwenImageEditNunchakuLocalSettings.from_mapping({
            "precision": "NVFP4", "rank": 128, "lightning_steps": 4, "num_inference_steps": 6,
            "true_cfg_scale": 2.0, "prompt": "remove text", "negative_prompt": "blurry",
            "offload_threshold_gb": 24.0, "low_vram_use_pin_memory": True,
            "low_vram_num_blocks_on_gpu": 2, "seed": 5, "model_cache_dir": "D:/custom/cache",
            "width": 1664, "height": 928,
        })

        self.assertEqual(settings.precision, "nvfp4")
        self.assertEqual(settings.rank, 128)
        self.assertEqual(settings.lightning_steps, 4)
        self.assertEqual(settings.num_inference_steps, 6)
        self.assertEqual(settings.resolved_num_inference_steps(), 6)
        self.assertEqual(settings.prompt, "remove text")
        self.assertEqual(settings.negative_prompt, "blurry")
        self.assertEqual(settings.seed, 5)
        self.assertEqual(settings.model_cache_dir, "D:/custom/cache")
        self.assertEqual(settings.width, 1664)
        self.assertEqual(settings.height, 928)

    def test_from_mapping_rejects_mismatched_width_height(self) -> None:
        with self.assertRaises(ValueError):
            QwenImageEditNunchakuLocalSettings.from_mapping({"width": 1664})
        with self.assertRaises(ValueError):
            QwenImageEditNunchakuLocalSettings.from_mapping({"height": 928})

    def test_lightning_steps_null_falls_back_to_40(self) -> None:
        settings = QwenImageEditNunchakuLocalSettings.from_mapping({"lightning_steps": None})

        self.assertIsNone(settings.lightning_steps)
        self.assertEqual(settings.resolved_num_inference_steps(), 40)

    def test_from_mapping_rejects_invalid_precision(self) -> None:
        with self.assertRaises(ValueError):
            QwenImageEditNunchakuLocalSettings.from_mapping({"precision": "int8"})

    def test_from_mapping_rejects_invalid_rank(self) -> None:
        with self.assertRaises(ValueError):
            QwenImageEditNunchakuLocalSettings.from_mapping({"rank": 64})

    def test_from_mapping_rejects_invalid_lightning_steps(self) -> None:
        with self.assertRaises(ValueError):
            QwenImageEditNunchakuLocalSettings.from_mapping({"lightning_steps": 5})


class QwenImageEditNunchakuLocalImageEditorTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp_dir.cleanup)
        self.image_file = Path(self._temp_dir.name) / "scene01_01.png"
        Image.new("RGB", (800, 600), color="red").save(self.image_file)
        self.settings = QwenImageEditNunchakuLocalSettings.from_mapping({"seed": 123})

    def test_requires_cuda(self) -> None:
        editor = QwenImageEditNunchakuLocalImageEditor(self.settings)
        torch_module = FakeTorch(cuda_available=False)

        with patch.object(QwenImageEditNunchakuLocalImageEditor, "_import_torch", staticmethod(lambda: torch_module)):
            with self.assertRaises(ImageEditError):
                editor.edit(self.image_file)

    def test_edit_uses_correct_arguments_and_original_size(self) -> None:
        result_image = Image.new("RGB", (500, 400), color="blue")
        pipeline = FakePipeline(result_image)
        transformer_cls = FakeNunchakuTransformerClass(FakeTransformer())
        torch_module = FakeTorch(cuda_available=True)
        diffusers_module = FakeDiffusers(pipeline)
        nunchaku_utils = FakeNunchakuUtils(gpu_memory_gb=24.0)
        editor = QwenImageEditNunchakuLocalImageEditor(self.settings)

        patches = _patch_imports(torch_module, diffusers_module, transformer_cls, nunchaku_utils)
        with patches[0], patches[1], patches[2]:
            editor.edit(self.image_file)

        call = pipeline.calls[0]
        self.assertEqual(call["prompt"], self.settings.prompt)
        self.assertEqual(call["negative_prompt"], " ")
        self.assertEqual((call["width"], call["height"]), (800, 600))
        self.assertEqual(call["num_inference_steps"], 8)
        self.assertEqual(call["true_cfg_scale"], 4.0)
        self.assertEqual(call["generator"].seed, 123)
        self.assertEqual(len(call["image"]), 1)

        pretrained_call = diffusers_module.QwenImageEditPlusPipeline.from_pretrained_calls[0]
        self.assertEqual(pretrained_call["model_id"], "Qwen/Qwen-Image-Edit-2509")
        transformer_call = transformer_cls.from_pretrained_calls[0]
        self.assertEqual(
            transformer_call["path"],
            "nunchaku-tech/nunchaku-qwen-image-edit-2509/"
            "svdq-int4_r32-qwen-image-edit-2509-lightningv2.0-8steps.safetensors",
        )

        # 出力ファイルは編集前と同じサイズへ整形して上書き保存される。
        with Image.open(self.image_file) as saved_image:
            self.assertEqual(saved_image.size, (800, 600))

    def test_edit_uses_configured_inference_size_and_restores_original_size(self) -> None:
        """width/height設定時は編集対象画像自身のサイズではなくその値で推論し、
        推論後に編集前と同じサイズへ戻して保存すること（処理時間短縮のための解像度分離）。"""
        settings = QwenImageEditNunchakuLocalSettings.from_mapping({
            "seed": 123, "width": 400, "height": 300,
        })
        result_image = Image.new("RGB", (400, 300), color="blue")
        pipeline = FakePipeline(result_image)
        transformer_cls = FakeNunchakuTransformerClass(FakeTransformer())
        torch_module = FakeTorch(cuda_available=True)
        diffusers_module = FakeDiffusers(pipeline)
        nunchaku_utils = FakeNunchakuUtils(gpu_memory_gb=24.0)
        editor = QwenImageEditNunchakuLocalImageEditor(settings)

        patches = _patch_imports(torch_module, diffusers_module, transformer_cls, nunchaku_utils)
        with patches[0], patches[1], patches[2]:
            editor.edit(self.image_file)

        # 元画像は800x600だが、推論はwidth/height設定（400x300）で行われる。
        call = pipeline.calls[0]
        self.assertEqual((call["width"], call["height"]), (400, 300))

        # 保存されるファイルは編集前と同じ800x600へ戻される。
        with Image.open(self.image_file) as saved_image:
            self.assertEqual(saved_image.size, (800, 600))

    def test_non_lightning_variant_uses_plain_filename(self) -> None:
        settings = QwenImageEditNunchakuLocalSettings.from_mapping({"lightning_steps": None})
        result_image = Image.new("RGB", (800, 600))
        pipeline = FakePipeline(result_image)
        transformer_cls = FakeNunchakuTransformerClass(FakeTransformer())
        torch_module = FakeTorch(cuda_available=True)
        diffusers_module = FakeDiffusers(pipeline)
        nunchaku_utils = FakeNunchakuUtils(gpu_memory_gb=24.0)
        editor = QwenImageEditNunchakuLocalImageEditor(settings)

        patches = _patch_imports(torch_module, diffusers_module, transformer_cls, nunchaku_utils)
        with patches[0], patches[1], patches[2]:
            editor.edit(self.image_file)

        transformer_call = transformer_cls.from_pretrained_calls[0]
        self.assertEqual(
            transformer_call["path"],
            "nunchaku-tech/nunchaku-qwen-image-edit-2509/svdq-int4_r32-qwen-image-edit-2509.safetensors",
        )
        self.assertEqual(pipeline.calls[0]["num_inference_steps"], 40)

    def test_high_vram_uses_model_cpu_offload(self) -> None:
        pipeline = FakePipeline(Image.new("RGB", (800, 600)))
        transformer = FakeTransformer()
        transformer_cls = FakeNunchakuTransformerClass(transformer)
        torch_module = FakeTorch(cuda_available=True)
        diffusers_module = FakeDiffusers(pipeline)
        nunchaku_utils = FakeNunchakuUtils(gpu_memory_gb=24.0)
        editor = QwenImageEditNunchakuLocalImageEditor(self.settings)

        patches = _patch_imports(torch_module, diffusers_module, transformer_cls, nunchaku_utils)
        with patches[0], patches[1], patches[2]:
            editor.edit(self.image_file)

        self.assertEqual(pipeline.model_cpu_offload_calls, 1)
        self.assertEqual(pipeline.sequential_cpu_offload_calls, 0)
        self.assertEqual(transformer.set_offload_calls, [])

    def test_low_vram_uses_sequential_offload(self) -> None:
        pipeline = FakePipeline(Image.new("RGB", (800, 600)))
        transformer = FakeTransformer()
        transformer_cls = FakeNunchakuTransformerClass(transformer)
        torch_module = FakeTorch(cuda_available=True)
        diffusers_module = FakeDiffusers(pipeline)
        nunchaku_utils = FakeNunchakuUtils(gpu_memory_gb=12.0)
        editor = QwenImageEditNunchakuLocalImageEditor(self.settings)

        patches = _patch_imports(torch_module, diffusers_module, transformer_cls, nunchaku_utils)
        with patches[0], patches[1], patches[2]:
            editor.edit(self.image_file)

        self.assertEqual(pipeline.model_cpu_offload_calls, 0)
        self.assertEqual(pipeline.sequential_cpu_offload_calls, 1)
        self.assertEqual(
            transformer.set_offload_calls,
            [{"enabled": True, "use_pin_memory": False, "num_blocks_on_gpu": 1}],
        )
        self.assertIn("transformer", pipeline._exclude_from_cpu_offload)

    def test_model_cache_dir_overrides_hf_hub_cache_constant(self) -> None:
        settings = QwenImageEditNunchakuLocalSettings.from_mapping({
            "seed": 123, "model_cache_dir": "D:/custom/edit-cache",
        })
        pipeline = FakePipeline(Image.new("RGB", (800, 600)))
        transformer_cls = FakeNunchakuTransformerClass(FakeTransformer())
        torch_module = FakeTorch(cuda_available=True)
        diffusers_module = FakeDiffusers(pipeline)
        nunchaku_utils = FakeNunchakuUtils(gpu_memory_gb=24.0)
        editor = QwenImageEditNunchakuLocalImageEditor(settings)

        from huggingface_hub import constants as hf_hub_constants
        original_hf_hub_cache = hf_hub_constants.HF_HUB_CACHE
        try:
            patches = _patch_imports(torch_module, diffusers_module, transformer_cls, nunchaku_utils)
            with patches[0], patches[1], patches[2]:
                editor.edit(self.image_file)

            self.assertEqual(hf_hub_constants.HF_HUB_CACHE, "D:/custom/edit-cache")
        finally:
            hf_hub_constants.HF_HUB_CACHE = original_hf_hub_cache

    def test_cuda_out_of_memory_raises_descriptive_error(self) -> None:
        oom_error = FakeCudaOutOfMemoryError("CUDA out of memory")
        pipeline = FakePipeline(Image.new("RGB", (800, 600)), raise_error=oom_error)
        transformer_cls = FakeNunchakuTransformerClass(FakeTransformer())
        torch_module = FakeTorch(cuda_available=True)
        diffusers_module = FakeDiffusers(pipeline)
        nunchaku_utils = FakeNunchakuUtils(gpu_memory_gb=24.0)
        editor = QwenImageEditNunchakuLocalImageEditor(self.settings)

        patches = _patch_imports(torch_module, diffusers_module, transformer_cls, nunchaku_utils)
        with patches[0], patches[1], patches[2]:
            with self.assertRaises(ImageEditError) as context:
                editor.edit(self.image_file)

        self.assertIn("cuda_oom=True", str(context.exception))

    def test_transformer_load_failure_raises_descriptive_error(self) -> None:
        transformer_cls = FakeNunchakuTransformerClass(FakeTransformer(), load_error=OSError("not found"))
        torch_module = FakeTorch(cuda_available=True)
        diffusers_module = FakeDiffusers(FakePipeline(Image.new("RGB", (800, 600))))
        nunchaku_utils = FakeNunchakuUtils(gpu_memory_gb=24.0)
        editor = QwenImageEditNunchakuLocalImageEditor(self.settings)

        patches = _patch_imports(torch_module, diffusers_module, transformer_cls, nunchaku_utils)
        with patches[0], patches[1], patches[2]:
            with self.assertRaises(ImageEditError) as context:
                editor.edit(self.image_file)

        self.assertIn("not found", str(context.exception))

    def test_release_clears_loaded_pipeline_and_frees_cuda_memory(self) -> None:
        pipeline = FakePipeline(Image.new("RGB", (800, 600)))
        transformer_cls = FakeNunchakuTransformerClass(FakeTransformer())
        torch_module = FakeTorch(cuda_available=True)
        diffusers_module = FakeDiffusers(pipeline)
        nunchaku_utils = FakeNunchakuUtils(gpu_memory_gb=24.0)
        editor = QwenImageEditNunchakuLocalImageEditor(self.settings)

        patches = _patch_imports(torch_module, diffusers_module, transformer_cls, nunchaku_utils)
        with patches[0], patches[1], patches[2]:
            editor.edit(self.image_file)
            editor.release()
            editor.edit(self.image_file)

        self.assertEqual(len(diffusers_module.QwenImageEditPlusPipeline.from_pretrained_calls), 2)
        self.assertEqual(torch_module.cuda.empty_cache_calls, 1)


if __name__ == "__main__":
    unittest.main()
