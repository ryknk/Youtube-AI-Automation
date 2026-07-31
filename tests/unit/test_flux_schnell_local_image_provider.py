"""FLUX.1 Schnell Self-hostプロバイダーのユニットテスト。

torch/diffusersは実際にはインストールしない前提で、
``FluxSchnellLocalImageProvider._import_torch``/``_import_diffusers`` を
フェイク実装へ差し替えてテストする。実モデルのダウンロード・ロード・
推論は一切行わない。
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from youtube_generator.exceptions import ImageGenerationError
from youtube_generator.plugins.image.flux_schnell_local_image import (
    FluxSchnellLocalImageProvider,
    FluxSchnellLocalSettings,
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

    def get_device_name(self, index: int) -> str:
        return "Fake GPU"

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
        self.float16 = "float16"
        self.bfloat16 = "bfloat16"
        self.float32 = "float32"
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
        self.to_calls: list[str] = []
        self.attention_slicing_enabled = False
        self.cpu_offload_enabled = False

    def to(self, device: str) -> "FakePipeline":
        self.to_calls.append(device)
        return self

    def enable_attention_slicing(self) -> None:
        self.attention_slicing_enabled = True

    def enable_model_cpu_offload(self) -> None:
        self.cpu_offload_enabled = True

    def __call__(self, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append(kwargs)
        if self._raise_error is not None:
            raise self._raise_error
        return FakePipelineResult(self._source_image)


class FakeFluxPipelineClass:
    def __init__(self, pipeline: FakePipeline, load_error: Exception | None = None) -> None:
        self._pipeline = pipeline
        self._load_error = load_error
        self.from_pretrained_calls = 0
        self.from_pretrained_kwargs: list[dict] = []

    def from_pretrained(self, model_id: str, torch_dtype=None, cache_dir=None, transformer=None):  # type: ignore[no-untyped-def]
        self.from_pretrained_calls += 1
        self.from_pretrained_kwargs.append({
            "model_id": model_id, "torch_dtype": torch_dtype, "cache_dir": cache_dir, "transformer": transformer,
        })
        if self._load_error is not None:
            raise self._load_error
        return self._pipeline


class FakeTransformer:
    pass


class FakeFluxTransformer2DModelClass:
    def __init__(self, transformer: "FakeTransformer", load_error: Exception | None = None) -> None:
        self._transformer = transformer
        self._load_error = load_error
        self.from_single_file_calls: list[dict] = []

    def from_single_file(self, pretrained_model_link_or_path: str, torch_dtype=None):  # type: ignore[no-untyped-def]
        self.from_single_file_calls.append({
            "path": pretrained_model_link_or_path, "torch_dtype": torch_dtype,
        })
        if self._load_error is not None:
            raise self._load_error
        return self._transformer


class FakeDiffusers:
    def __init__(self, pipeline: FakePipeline, load_error: Exception | None = None) -> None:
        self.FluxPipeline = FakeFluxPipelineClass(pipeline, load_error)
        self.FluxTransformer2DModel = FakeFluxTransformer2DModelClass(FakeTransformer())


def _patched_provider(
    provider: FluxSchnellLocalImageProvider, torch_module: FakeTorch, diffusers_module: FakeDiffusers,
):
    return (
        patch.object(FluxSchnellLocalImageProvider, "_import_torch", staticmethod(lambda: torch_module)),
        patch.object(FluxSchnellLocalImageProvider, "_import_diffusers", staticmethod(lambda: diffusers_module)),
    )


class FluxSchnellLocalSettingsTests(unittest.TestCase):
    def test_from_mapping_applies_defaults(self) -> None:
        settings = FluxSchnellLocalSettings.from_mapping({})

        self.assertEqual(settings.model_id, "black-forest-labs/FLUX.1-schnell")
        self.assertEqual(settings.device, "auto")
        self.assertIsNone(settings.seed)
        self.assertIsNone(settings.fallback_provider)
        self.assertFalse(settings.allow_cpu)
        self.assertIsNone(settings.transformer_path)

    def test_from_mapping_reads_all_fields(self) -> None:
        settings = FluxSchnellLocalSettings.from_mapping({
            "model_id": "org/model", "device": "CUDA", "dtype": "FLOAT16",
            "num_inference_steps": 6, "guidance_scale": 1.5, "width": 512, "height": 512,
            "seed": 42, "enable_cpu_offload": True, "enable_attention_slicing": True,
            "low_vram_mode": True, "model_cache_dir": "/tmp/cache", "allow_cpu": True,
            "fallback_provider": "BFL", "negative_prompt": "blurry",
            "transformer_path": "huggingface/checkpoints/pixelwave_flux1_schnell_v04_bf16.safetensors",
        })

        self.assertEqual(settings.model_id, "org/model")
        self.assertEqual(settings.device, "cuda")
        self.assertEqual(settings.dtype, "float16")
        self.assertEqual(settings.seed, 42)
        self.assertEqual(settings.fallback_provider, "bfl")
        self.assertEqual(settings.negative_prompt, "blurry")
        self.assertTrue(settings.allow_cpu)
        self.assertEqual(
            settings.transformer_path, "huggingface/checkpoints/pixelwave_flux1_schnell_v04_bf16.safetensors",
        )

    def test_from_mapping_rejects_invalid_device(self) -> None:
        with self.assertRaises(ValueError):
            FluxSchnellLocalSettings.from_mapping({"device": "tpu"})

    def test_from_mapping_rejects_invalid_dtype(self) -> None:
        with self.assertRaises(ValueError):
            FluxSchnellLocalSettings.from_mapping({"dtype": "int8"})


class FluxSchnellLocalImageProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp_dir.cleanup)
        self.output_file = Path(self._temp_dir.name) / "scene01.png"
        self.settings = FluxSchnellLocalSettings.from_mapping({
            "seed": 123, "allow_cpu": True, "width": 800, "height": 600,
        })

    def test_generate_image_uses_correct_generation_arguments(self) -> None:
        source_image = Image.new("RGB", (800, 600), color="red")
        pipeline = FakePipeline(source_image)
        torch_module = FakeTorch(cuda_available=False)
        diffusers_module = FakeDiffusers(pipeline)
        provider = FluxSchnellLocalImageProvider(self.settings, "640x360")

        with patch.object(FluxSchnellLocalImageProvider, "_import_torch", staticmethod(lambda: torch_module)), \
             patch.object(FluxSchnellLocalImageProvider, "_import_diffusers", staticmethod(lambda: diffusers_module)):
            provider.generate_image("a calm landscape", self.output_file)

        call = pipeline.calls[0]
        self.assertEqual(call["prompt"], "a calm landscape")
        self.assertEqual((call["width"], call["height"]), (800, 600))
        self.assertEqual(call["num_inference_steps"], 4)
        self.assertEqual(call["guidance_scale"], 0.0)
        self.assertEqual(call["max_sequence_length"], 256)
        self.assertEqual(call["generator"].seed, 123)

    def test_max_sequence_length_defaults_to_256_and_is_configurable(self) -> None:
        default_settings = FluxSchnellLocalSettings.from_mapping({})
        self.assertEqual(default_settings.max_sequence_length, 256)

        custom_settings = FluxSchnellLocalSettings.from_mapping({"max_sequence_length": 512, "allow_cpu": True})
        self.assertEqual(custom_settings.max_sequence_length, 512)

        source_image = Image.new("RGB", (800, 600), color="red")
        pipeline = FakePipeline(source_image)
        torch_module = FakeTorch(cuda_available=False)
        diffusers_module = FakeDiffusers(pipeline)
        provider = FluxSchnellLocalImageProvider(custom_settings, "640x360")

        with patch.object(FluxSchnellLocalImageProvider, "_import_torch", staticmethod(lambda: torch_module)), \
             patch.object(FluxSchnellLocalImageProvider, "_import_diffusers", staticmethod(lambda: diffusers_module)):
            provider.generate_image("prompt", self.output_file)

        self.assertEqual(pipeline.calls[0]["max_sequence_length"], 512)

    def test_generate_image_saves_image_resized_to_output_size_preserving_aspect(self) -> None:
        source_image = Image.new("RGB", (800, 600), color="blue")
        pipeline = FakePipeline(source_image)
        torch_module = FakeTorch(cuda_available=False)
        diffusers_module = FakeDiffusers(pipeline)
        provider = FluxSchnellLocalImageProvider(self.settings, "640x360")

        with patch.object(FluxSchnellLocalImageProvider, "_import_torch", staticmethod(lambda: torch_module)), \
             patch.object(FluxSchnellLocalImageProvider, "_import_diffusers", staticmethod(lambda: diffusers_module)):
            provider.generate_image("prompt", self.output_file)

        with Image.open(self.output_file) as saved_image:
            self.assertEqual(saved_image.size, (640, 360))

    def test_generate_image_embeds_seed_metadata_for_reproducibility(self) -> None:
        source_image = Image.new("RGB", (800, 600), color="green")
        pipeline = FakePipeline(source_image)
        torch_module = FakeTorch(cuda_available=False)
        diffusers_module = FakeDiffusers(pipeline)
        provider = FluxSchnellLocalImageProvider(self.settings, "640x360")

        with patch.object(FluxSchnellLocalImageProvider, "_import_torch", staticmethod(lambda: torch_module)), \
             patch.object(FluxSchnellLocalImageProvider, "_import_diffusers", staticmethod(lambda: diffusers_module)):
            provider.generate_image("prompt", self.output_file)

        with Image.open(self.output_file) as saved_image:
            self.assertEqual(saved_image.text.get("flux_schnell_local:seed"), "123")

    def test_transformer_path_loads_single_file_transformer_and_reuses_base_pipeline(self) -> None:
        transformer_path = "huggingface/checkpoints/pixelwave_flux1_schnell_v04_bf16.safetensors"
        settings = FluxSchnellLocalSettings.from_mapping({
            "seed": 123, "allow_cpu": True, "width": 800, "height": 600,
            "transformer_path": transformer_path,
        })
        source_image = Image.new("RGB", (800, 600), color="red")
        pipeline = FakePipeline(source_image)
        fake_transformer = FakeTransformer()
        torch_module = FakeTorch(cuda_available=False)
        diffusers_module = FakeDiffusers(pipeline)
        diffusers_module.FluxTransformer2DModel = FakeFluxTransformer2DModelClass(fake_transformer)
        provider = FluxSchnellLocalImageProvider(settings, "640x360")

        with patch.object(FluxSchnellLocalImageProvider, "_import_torch", staticmethod(lambda: torch_module)), \
             patch.object(FluxSchnellLocalImageProvider, "_import_diffusers", staticmethod(lambda: diffusers_module)):
            provider.generate_image("a calm landscape", self.output_file)

        self.assertEqual(len(diffusers_module.FluxTransformer2DModel.from_single_file_calls), 1)
        self.assertEqual(
            diffusers_module.FluxTransformer2DModel.from_single_file_calls[0]["path"], transformer_path,
        )
        self.assertEqual(diffusers_module.FluxPipeline.from_pretrained_calls, 1)
        pretrained_call = diffusers_module.FluxPipeline.from_pretrained_kwargs[0]
        self.assertIs(pretrained_call["transformer"], fake_transformer)
        self.assertEqual(pretrained_call["model_id"], settings.model_id)

        with Image.open(self.output_file) as saved_image:
            self.assertEqual(saved_image.text.get("flux_schnell_local:transformer_path"), transformer_path)

    def test_transformer_path_load_failure_raises_descriptive_error(self) -> None:
        transformer_path = "huggingface/checkpoints/missing.safetensors"
        settings = FluxSchnellLocalSettings.from_mapping({
            "allow_cpu": True, "transformer_path": transformer_path,
        })
        pipeline = FakePipeline(Image.new("RGB", (800, 600)))
        torch_module = FakeTorch(cuda_available=False)
        diffusers_module = FakeDiffusers(pipeline)
        diffusers_module.FluxTransformer2DModel = FakeFluxTransformer2DModelClass(
            FakeTransformer(), load_error=OSError("file not found"),
        )
        provider = FluxSchnellLocalImageProvider(settings, "640x360")

        with patch.object(FluxSchnellLocalImageProvider, "_import_torch", staticmethod(lambda: torch_module)), \
             patch.object(FluxSchnellLocalImageProvider, "_import_diffusers", staticmethod(lambda: diffusers_module)):
            with self.assertRaises(ImageGenerationError) as context:
                provider.generate_image("prompt", self.output_file)

        message = str(context.exception)
        self.assertIn(transformer_path, message)
        self.assertIn("file not found", message)

    def test_pipeline_is_lazily_loaded_and_reused_across_calls(self) -> None:
        source_image = Image.new("RGB", (800, 600), color="yellow")
        pipeline = FakePipeline(source_image)
        torch_module = FakeTorch(cuda_available=False)
        diffusers_module = FakeDiffusers(pipeline)
        provider = FluxSchnellLocalImageProvider(self.settings, "640x360")

        with patch.object(FluxSchnellLocalImageProvider, "_import_torch", staticmethod(lambda: torch_module)), \
             patch.object(FluxSchnellLocalImageProvider, "_import_diffusers", staticmethod(lambda: diffusers_module)):
            self.assertEqual(diffusers_module.FluxPipeline.from_pretrained_calls, 0)
            provider.generate_image("prompt one", self.output_file)
            provider.generate_image("prompt two", Path(self._temp_dir.name) / "scene02.png")

        self.assertEqual(diffusers_module.FluxPipeline.from_pretrained_calls, 1)
        self.assertEqual(len(pipeline.calls), 2)

    def test_release_clears_loaded_pipeline_and_frees_cuda_memory(self) -> None:
        source_image = Image.new("RGB", (800, 600), color="black")
        pipeline = FakePipeline(source_image)
        torch_module = FakeTorch(cuda_available=True)
        diffusers_module = FakeDiffusers(pipeline)
        settings = FluxSchnellLocalSettings.from_mapping({"seed": 1})
        provider = FluxSchnellLocalImageProvider(settings, "640x360")

        with patch.object(FluxSchnellLocalImageProvider, "_import_torch", staticmethod(lambda: torch_module)), \
             patch.object(FluxSchnellLocalImageProvider, "_import_diffusers", staticmethod(lambda: diffusers_module)):
            provider.generate_image("prompt", self.output_file)
            provider.release()
            provider.generate_image("prompt again", Path(self._temp_dir.name) / "scene02.png")

        # release()後の再生成でモデルが再ロードされること（=一度解放されたこと）を確認する。
        self.assertEqual(diffusers_module.FluxPipeline.from_pretrained_calls, 2)
        self.assertEqual(torch_module.cuda.empty_cache_calls, 1)

    def test_cuda_out_of_memory_raises_descriptive_error(self) -> None:
        source_image = Image.new("RGB", (800, 600))
        oom_error = FakeCudaOutOfMemoryError("CUDA out of memory")
        pipeline = FakePipeline(source_image, raise_error=oom_error)
        torch_module = FakeTorch(cuda_available=True)
        diffusers_module = FakeDiffusers(pipeline)
        provider = FluxSchnellLocalImageProvider(self.settings, "640x360")

        with patch.object(FluxSchnellLocalImageProvider, "_import_torch", staticmethod(lambda: torch_module)), \
             patch.object(FluxSchnellLocalImageProvider, "_import_diffusers", staticmethod(lambda: diffusers_module)):
            with self.assertRaises(ImageGenerationError) as context:
                provider.generate_image("prompt", self.output_file)

        message = str(context.exception)
        self.assertIn("cuda_oom=True", message)
        self.assertIn(self.settings.model_id, message)
        self.assertIn("device=cuda", message)

    def test_model_load_failure_raises_descriptive_error(self) -> None:
        pipeline = FakePipeline(Image.new("RGB", (800, 600)))
        torch_module = FakeTorch(cuda_available=False)
        diffusers_module = FakeDiffusers(pipeline, load_error=OSError("network unreachable"))
        provider = FluxSchnellLocalImageProvider(self.settings, "640x360")

        with patch.object(FluxSchnellLocalImageProvider, "_import_torch", staticmethod(lambda: torch_module)), \
             patch.object(FluxSchnellLocalImageProvider, "_import_diffusers", staticmethod(lambda: diffusers_module)):
            with self.assertRaises(ImageGenerationError) as context:
                provider.generate_image("prompt", self.output_file)

        message = str(context.exception)
        self.assertIn(self.settings.model_id, message)
        self.assertIn("network unreachable", message)

    def test_device_cpu_requires_allow_cpu(self) -> None:
        settings = FluxSchnellLocalSettings.from_mapping({"device": "cpu", "allow_cpu": False})
        pipeline = FakePipeline(Image.new("RGB", (800, 600)))
        torch_module = FakeTorch(cuda_available=False)
        diffusers_module = FakeDiffusers(pipeline)
        provider = FluxSchnellLocalImageProvider(settings, "640x360")

        with patch.object(FluxSchnellLocalImageProvider, "_import_torch", staticmethod(lambda: torch_module)), \
             patch.object(FluxSchnellLocalImageProvider, "_import_diffusers", staticmethod(lambda: diffusers_module)):
            with self.assertRaises(ImageGenerationError):
                provider.generate_image("prompt", self.output_file)

    def test_auto_device_without_cuda_requires_allow_cpu(self) -> None:
        settings = FluxSchnellLocalSettings.from_mapping({"device": "auto", "allow_cpu": False})
        pipeline = FakePipeline(Image.new("RGB", (800, 600)))
        torch_module = FakeTorch(cuda_available=False)
        diffusers_module = FakeDiffusers(pipeline)
        provider = FluxSchnellLocalImageProvider(settings, "640x360")

        with patch.object(FluxSchnellLocalImageProvider, "_import_torch", staticmethod(lambda: torch_module)), \
             patch.object(FluxSchnellLocalImageProvider, "_import_diffusers", staticmethod(lambda: diffusers_module)):
            with self.assertRaises(ImageGenerationError):
                provider.generate_image("prompt", self.output_file)

    def test_torch_missing_raises_actionable_error(self) -> None:
        provider = FluxSchnellLocalImageProvider(self.settings, "640x360")

        with patch.object(
            FluxSchnellLocalImageProvider, "_import_torch",
            staticmethod(lambda: (_ for _ in ()).throw(ImageGenerationError("torchがインストールされていません。"))),
        ):
            with self.assertRaisesRegex(ImageGenerationError, "torch"):
                provider.generate_image("prompt", self.output_file)


if __name__ == "__main__":
    unittest.main()
