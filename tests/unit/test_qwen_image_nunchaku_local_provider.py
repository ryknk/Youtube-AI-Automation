"""Qwen-Image nunchaku(SVDQuant 4bit量子化)版Self-hostプロバイダーのユニットテスト。

torch/diffusers/nunchakuは実際にはインストールしない前提で、
``QwenImageNunchakuLocalImageProvider._import_torch``/``_import_diffusers``/
``_import_nunchaku`` をフェイク実装へ差し替えてテストする。実モデルのダウンロード・
ロード・推論は一切行わない。
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from youtube_generator.exceptions import ImageGenerationError
from youtube_generator.plugins.image.qwen_image_nunchaku_local import (
    QwenImageNunchakuLocalImageProvider,
    QwenImageNunchakuLocalSettings,
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
    def __init__(self, source_image: Image.Image, raise_error: Exception | None = None) -> None:
        self._source_image = source_image
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
        return FakePipelineResult(self._source_image)


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


class FakeQwenImagePipelineClass:
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
        self.QwenImagePipeline = FakeQwenImagePipelineClass(pipeline)


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
        patch.object(QwenImageNunchakuLocalImageProvider, "_import_torch", staticmethod(lambda: torch_module)),
        patch.object(QwenImageNunchakuLocalImageProvider, "_import_diffusers", staticmethod(lambda: diffusers_module)),
        patch.object(
            QwenImageNunchakuLocalImageProvider, "_import_nunchaku",
            staticmethod(lambda: (transformer_cls, nunchaku_utils)),
        ),
    )


class QwenImageNunchakuLocalSettingsTests(unittest.TestCase):
    def test_from_mapping_applies_defaults(self) -> None:
        settings = QwenImageNunchakuLocalSettings.from_mapping({})

        self.assertEqual(settings.base_model_id, "Qwen/Qwen-Image")
        self.assertEqual(settings.transformer_repo_id, "nunchaku-tech/nunchaku-qwen-image")
        self.assertEqual(settings.precision, "auto")
        self.assertEqual(settings.rank, 32)
        self.assertEqual(settings.offload_threshold_gb, 18.0)
        self.assertFalse(settings.low_vram_use_pin_memory)
        self.assertEqual(settings.low_vram_num_blocks_on_gpu, 1)
        self.assertEqual(settings.num_inference_steps, 50)
        self.assertEqual(settings.true_cfg_scale, 4.0)
        self.assertEqual(settings.prompt_suffix, "")
        self.assertIsNone(settings.fallback_provider)

    def test_from_mapping_reads_all_fields(self) -> None:
        settings = QwenImageNunchakuLocalSettings.from_mapping({
            "precision": "NVFP4", "rank": 128, "offload_threshold_gb": 24.0,
            "low_vram_use_pin_memory": True, "low_vram_num_blocks_on_gpu": 2,
            "num_inference_steps": 8, "true_cfg_scale": 2.0, "seed": 5,
            "negative_prompt": "blurry", "prompt_suffix": "Ultra HD, 4K.", "fallback_provider": "BFL",
        })

        self.assertEqual(settings.precision, "nvfp4")
        self.assertEqual(settings.rank, 128)
        self.assertEqual(settings.offload_threshold_gb, 24.0)
        self.assertTrue(settings.low_vram_use_pin_memory)
        self.assertEqual(settings.low_vram_num_blocks_on_gpu, 2)
        self.assertEqual(settings.seed, 5)
        self.assertEqual(settings.prompt_suffix, "Ultra HD, 4K.")
        self.assertEqual(settings.fallback_provider, "bfl")

    def test_from_mapping_rejects_invalid_precision(self) -> None:
        with self.assertRaises(ValueError):
            QwenImageNunchakuLocalSettings.from_mapping({"precision": "int8"})

    def test_from_mapping_rejects_invalid_rank(self) -> None:
        with self.assertRaises(ValueError):
            QwenImageNunchakuLocalSettings.from_mapping({"rank": 64})


class QwenImageNunchakuLocalImageProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp_dir.cleanup)
        self.output_file = Path(self._temp_dir.name) / "scene01.png"
        self.settings = QwenImageNunchakuLocalSettings.from_mapping({
            "seed": 123, "width": 800, "height": 600,
        })

    def test_requires_cuda(self) -> None:
        provider = QwenImageNunchakuLocalImageProvider(self.settings, "640x360")
        torch_module = FakeTorch(cuda_available=False)

        with patch.object(QwenImageNunchakuLocalImageProvider, "_import_torch", staticmethod(lambda: torch_module)):
            with self.assertRaises(ImageGenerationError):
                provider.generate_image("prompt", self.output_file)

    def test_generate_image_uses_correct_generation_arguments(self) -> None:
        source_image = Image.new("RGB", (800, 600), color="red")
        pipeline = FakePipeline(source_image)
        transformer_cls = FakeNunchakuTransformerClass(FakeTransformer())
        torch_module = FakeTorch(cuda_available=True)
        diffusers_module = FakeDiffusers(pipeline)
        nunchaku_utils = FakeNunchakuUtils(gpu_memory_gb=24.0)
        provider = QwenImageNunchakuLocalImageProvider(self.settings, "640x360")

        patches = _patch_imports(torch_module, diffusers_module, transformer_cls, nunchaku_utils)
        with patches[0], patches[1], patches[2]:
            provider.generate_image("a calm landscape", self.output_file)

        call = pipeline.calls[0]
        self.assertEqual(call["prompt"], "a calm landscape")
        self.assertEqual(call["negative_prompt"], "")
        self.assertEqual((call["width"], call["height"]), (800, 600))
        self.assertEqual(call["num_inference_steps"], 50)
        self.assertEqual(call["true_cfg_scale"], 4.0)
        self.assertEqual(call["generator"].seed, 123)

        pretrained_call = diffusers_module.QwenImagePipeline.from_pretrained_calls[0]
        self.assertEqual(pretrained_call["model_id"], "Qwen/Qwen-Image")
        transformer_call = transformer_cls.from_pretrained_calls[0]
        self.assertEqual(
            transformer_call["path"],
            "nunchaku-tech/nunchaku-qwen-image/svdq-int4_r32-qwen-image.safetensors",
        )

    def test_prompt_suffix_is_appended_when_configured(self) -> None:
        settings = QwenImageNunchakuLocalSettings.from_mapping({
            "seed": 123, "width": 800, "height": 600,
            "prompt_suffix": "Ultra HD, 4K, cinematic composition. No text.",
        })
        source_image = Image.new("RGB", (800, 600), color="red")
        pipeline = FakePipeline(source_image)
        transformer_cls = FakeNunchakuTransformerClass(FakeTransformer())
        torch_module = FakeTorch(cuda_available=True)
        diffusers_module = FakeDiffusers(pipeline)
        nunchaku_utils = FakeNunchakuUtils(gpu_memory_gb=24.0)
        provider = QwenImageNunchakuLocalImageProvider(settings, "640x360")

        patches = _patch_imports(torch_module, diffusers_module, transformer_cls, nunchaku_utils)
        with patches[0], patches[1], patches[2]:
            provider.generate_image("a calm landscape", self.output_file)

        self.assertEqual(
            pipeline.calls[0]["prompt"],
            "a calm landscape, Ultra HD, 4K, cinematic composition. No text.",
        )

    def test_high_vram_uses_model_cpu_offload(self) -> None:
        source_image = Image.new("RGB", (800, 600))
        pipeline = FakePipeline(source_image)
        transformer = FakeTransformer()
        transformer_cls = FakeNunchakuTransformerClass(transformer)
        torch_module = FakeTorch(cuda_available=True)
        diffusers_module = FakeDiffusers(pipeline)
        nunchaku_utils = FakeNunchakuUtils(gpu_memory_gb=24.0)
        provider = QwenImageNunchakuLocalImageProvider(self.settings, "640x360")

        patches = _patch_imports(torch_module, diffusers_module, transformer_cls, nunchaku_utils)
        with patches[0], patches[1], patches[2]:
            provider.generate_image("prompt", self.output_file)

        self.assertEqual(pipeline.model_cpu_offload_calls, 1)
        self.assertEqual(pipeline.sequential_cpu_offload_calls, 0)
        self.assertEqual(transformer.set_offload_calls, [])

    def test_low_vram_uses_sequential_offload(self) -> None:
        source_image = Image.new("RGB", (800, 600))
        pipeline = FakePipeline(source_image)
        transformer = FakeTransformer()
        transformer_cls = FakeNunchakuTransformerClass(transformer)
        torch_module = FakeTorch(cuda_available=True)
        diffusers_module = FakeDiffusers(pipeline)
        nunchaku_utils = FakeNunchakuUtils(gpu_memory_gb=12.0)
        provider = QwenImageNunchakuLocalImageProvider(self.settings, "640x360")

        patches = _patch_imports(torch_module, diffusers_module, transformer_cls, nunchaku_utils)
        with patches[0], patches[1], patches[2]:
            provider.generate_image("prompt", self.output_file)

        self.assertEqual(pipeline.model_cpu_offload_calls, 0)
        self.assertEqual(pipeline.sequential_cpu_offload_calls, 1)
        self.assertEqual(
            transformer.set_offload_calls,
            [{"enabled": True, "use_pin_memory": False, "num_blocks_on_gpu": 1}],
        )
        self.assertIn("transformer", pipeline._exclude_from_cpu_offload)

    def test_low_vram_offload_params_are_configurable(self) -> None:
        settings = QwenImageNunchakuLocalSettings.from_mapping({
            "seed": 123, "width": 800, "height": 600,
            "low_vram_use_pin_memory": True, "low_vram_num_blocks_on_gpu": 3,
        })
        source_image = Image.new("RGB", (800, 600))
        pipeline = FakePipeline(source_image)
        transformer = FakeTransformer()
        transformer_cls = FakeNunchakuTransformerClass(transformer)
        torch_module = FakeTorch(cuda_available=True)
        diffusers_module = FakeDiffusers(pipeline)
        nunchaku_utils = FakeNunchakuUtils(gpu_memory_gb=12.0)
        provider = QwenImageNunchakuLocalImageProvider(settings, "640x360")

        patches = _patch_imports(torch_module, diffusers_module, transformer_cls, nunchaku_utils)
        with patches[0], patches[1], patches[2]:
            provider.generate_image("prompt", self.output_file)

        self.assertEqual(
            transformer.set_offload_calls,
            [{"enabled": True, "use_pin_memory": True, "num_blocks_on_gpu": 3}],
        )

    def test_auto_precision_resolved_from_nunchaku_utils(self) -> None:
        source_image = Image.new("RGB", (800, 600))
        pipeline = FakePipeline(source_image)
        transformer_cls = FakeNunchakuTransformerClass(FakeTransformer())
        torch_module = FakeTorch(cuda_available=True)
        diffusers_module = FakeDiffusers(pipeline)
        nunchaku_utils = FakeNunchakuUtils(gpu_memory_gb=24.0, precision="nvfp4")
        provider = QwenImageNunchakuLocalImageProvider(self.settings, "640x360")

        patches = _patch_imports(torch_module, diffusers_module, transformer_cls, nunchaku_utils)
        with patches[0], patches[1], patches[2]:
            provider.generate_image("prompt", self.output_file)

        transformer_call = transformer_cls.from_pretrained_calls[0]
        self.assertIn("svdq-nvfp4_r32-qwen-image.safetensors", transformer_call["path"])

    def test_generate_image_saves_image_resized_to_output_size_preserving_aspect(self) -> None:
        source_image = Image.new("RGB", (800, 600), color="blue")
        pipeline = FakePipeline(source_image)
        transformer_cls = FakeNunchakuTransformerClass(FakeTransformer())
        torch_module = FakeTorch(cuda_available=True)
        diffusers_module = FakeDiffusers(pipeline)
        nunchaku_utils = FakeNunchakuUtils(gpu_memory_gb=24.0)
        provider = QwenImageNunchakuLocalImageProvider(self.settings, "640x360")

        patches = _patch_imports(torch_module, diffusers_module, transformer_cls, nunchaku_utils)
        with patches[0], patches[1], patches[2]:
            provider.generate_image("prompt", self.output_file)

        with Image.open(self.output_file) as saved_image:
            self.assertEqual(saved_image.size, (640, 360))

    def test_generate_image_embeds_seed_metadata_for_reproducibility(self) -> None:
        source_image = Image.new("RGB", (800, 600), color="green")
        pipeline = FakePipeline(source_image)
        transformer_cls = FakeNunchakuTransformerClass(FakeTransformer())
        torch_module = FakeTorch(cuda_available=True)
        diffusers_module = FakeDiffusers(pipeline)
        nunchaku_utils = FakeNunchakuUtils(gpu_memory_gb=24.0)
        provider = QwenImageNunchakuLocalImageProvider(self.settings, "640x360")

        patches = _patch_imports(torch_module, diffusers_module, transformer_cls, nunchaku_utils)
        with patches[0], patches[1], patches[2]:
            provider.generate_image("prompt", self.output_file)

        with Image.open(self.output_file) as saved_image:
            self.assertEqual(saved_image.text.get("qwen_image_nunchaku_local:seed"), "123")

    def test_cuda_out_of_memory_raises_descriptive_error(self) -> None:
        source_image = Image.new("RGB", (800, 600))
        oom_error = FakeCudaOutOfMemoryError("CUDA out of memory")
        pipeline = FakePipeline(source_image, raise_error=oom_error)
        transformer_cls = FakeNunchakuTransformerClass(FakeTransformer())
        torch_module = FakeTorch(cuda_available=True)
        diffusers_module = FakeDiffusers(pipeline)
        nunchaku_utils = FakeNunchakuUtils(gpu_memory_gb=24.0)
        provider = QwenImageNunchakuLocalImageProvider(self.settings, "640x360")

        patches = _patch_imports(torch_module, diffusers_module, transformer_cls, nunchaku_utils)
        with patches[0], patches[1], patches[2]:
            with self.assertRaises(ImageGenerationError) as context:
                provider.generate_image("prompt", self.output_file)

        self.assertIn("cuda_oom=True", str(context.exception))

    def test_transformer_load_failure_raises_descriptive_error(self) -> None:
        transformer_cls = FakeNunchakuTransformerClass(FakeTransformer(), load_error=OSError("not found"))
        torch_module = FakeTorch(cuda_available=True)
        diffusers_module = FakeDiffusers(FakePipeline(Image.new("RGB", (800, 600))))
        nunchaku_utils = FakeNunchakuUtils(gpu_memory_gb=24.0)
        provider = QwenImageNunchakuLocalImageProvider(self.settings, "640x360")

        patches = _patch_imports(torch_module, diffusers_module, transformer_cls, nunchaku_utils)
        with patches[0], patches[1], patches[2]:
            with self.assertRaises(ImageGenerationError) as context:
                provider.generate_image("prompt", self.output_file)

        self.assertIn("not found", str(context.exception))

    def test_release_clears_loaded_pipeline_and_frees_cuda_memory(self) -> None:
        source_image = Image.new("RGB", (800, 600))
        pipeline = FakePipeline(source_image)
        transformer_cls = FakeNunchakuTransformerClass(FakeTransformer())
        torch_module = FakeTorch(cuda_available=True)
        diffusers_module = FakeDiffusers(pipeline)
        nunchaku_utils = FakeNunchakuUtils(gpu_memory_gb=24.0)
        provider = QwenImageNunchakuLocalImageProvider(self.settings, "640x360")

        patches = _patch_imports(torch_module, diffusers_module, transformer_cls, nunchaku_utils)
        with patches[0], patches[1], patches[2]:
            provider.generate_image("prompt", self.output_file)
            provider.release()
            provider.generate_image("prompt again", Path(self._temp_dir.name) / "scene02.png")

        self.assertEqual(len(diffusers_module.QwenImagePipeline.from_pretrained_calls), 2)
        self.assertEqual(torch_module.cuda.empty_cache_calls, 1)


if __name__ == "__main__":
    unittest.main()
