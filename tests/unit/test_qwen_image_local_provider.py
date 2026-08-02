"""Qwen-Image Self-hostプロバイダーのユニットテスト。

torch/diffusersは実際にはインストールしない前提で、
``QwenImageLocalImageProvider._import_torch``/``_import_diffusers`` を
フェイク実装へ差し替えてテストする。実モデルのダウンロード・ロード・
推論は一切行わない。
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from youtube_generator.exceptions import ImageGenerationError
from youtube_generator.plugins.image.qwen_image_local import (
    QwenImageLocalImageProvider,
    QwenImageLocalSettings,
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
    def __init__(
        self, source_image: Image.Image | list[Image.Image], raise_error: Exception | None = None,
        lora_error: Exception | None = None,
    ) -> None:
        self._source_images = source_image if isinstance(source_image, list) else [source_image]
        self._raise_error = raise_error
        self._lora_error = lora_error
        self.calls: list[dict] = []
        self.to_calls: list[str] = []
        self.attention_slicing_enabled = False
        self.cpu_offload_enabled = False
        self.load_lora_weights_calls: list[dict] = []

    def to(self, device: str) -> "FakePipeline":
        self.to_calls.append(device)
        return self

    def enable_attention_slicing(self) -> None:
        self.attention_slicing_enabled = True

    def enable_model_cpu_offload(self) -> None:
        self.cpu_offload_enabled = True

    def load_lora_weights(self, repo_id: str, weight_name: str, cache_dir: str | None = None) -> None:
        self.load_lora_weights_calls.append({
            "repo_id": repo_id, "weight_name": weight_name, "cache_dir": cache_dir,
        })
        if self._lora_error is not None:
            raise self._lora_error

    def __call__(self, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append(kwargs)
        if self._raise_error is not None:
            raise self._raise_error
        # 呼び出し回数に応じて画像を切り替える（末尾到達後は最後の画像を使い続ける）。
        index = min(len(self.calls) - 1, len(self._source_images) - 1)
        return FakePipelineResult(self._source_images[index])


class FakeDiffusionPipelineClass:
    def __init__(self, pipeline: FakePipeline, load_error: Exception | None = None) -> None:
        self._pipeline = pipeline
        self._load_error = load_error
        self.from_pretrained_calls = 0
        self.from_pretrained_kwargs: list[dict] = []

    def from_pretrained(self, model_id: str, torch_dtype=None, cache_dir=None, scheduler=None):  # type: ignore[no-untyped-def]
        self.from_pretrained_calls += 1
        self.from_pretrained_kwargs.append({
            "model_id": model_id, "torch_dtype": torch_dtype, "cache_dir": cache_dir, "scheduler": scheduler,
        })
        if self._load_error is not None:
            raise self._load_error
        return self._pipeline


class FakeScheduler:
    def __init__(self, config: dict) -> None:
        self.config = config


class FakeFlowMatchEulerDiscreteSchedulerClass:
    def from_config(self, config: dict) -> FakeScheduler:
        return FakeScheduler(config)


class FakeDiffusers:
    def __init__(self, pipeline: FakePipeline, load_error: Exception | None = None) -> None:
        self.DiffusionPipeline = FakeDiffusionPipelineClass(pipeline, load_error)
        self.FlowMatchEulerDiscreteScheduler = FakeFlowMatchEulerDiscreteSchedulerClass()


class QwenImageLocalSettingsTests(unittest.TestCase):
    def test_from_mapping_applies_defaults(self) -> None:
        settings = QwenImageLocalSettings.from_mapping({})

        self.assertEqual(settings.model_id, "Qwen/Qwen-Image")
        self.assertEqual(settings.device, "auto")
        self.assertEqual(settings.num_inference_steps, 50)
        self.assertEqual(settings.true_cfg_scale, 4.0)
        self.assertEqual(settings.negative_prompt, "")
        self.assertEqual(settings.prompt_suffix, "")
        self.assertIsNone(settings.seed)
        self.assertIsNone(settings.fallback_provider)
        self.assertFalse(settings.allow_cpu)
        self.assertTrue(settings.letterbox_detection_enabled)
        self.assertFalse(settings.lightning_lora_enabled)
        self.assertEqual(settings.lightning_lora_repo_id, "lightx2v/Qwen-Image-Lightning")
        self.assertEqual(settings.lightning_lora_weight_name, "Qwen-Image-Lightning-8steps-V2.0.safetensors")

    def test_from_mapping_reads_all_fields(self) -> None:
        settings = QwenImageLocalSettings.from_mapping({
            "model_id": "org/model", "device": "CUDA", "dtype": "FLOAT16",
            "num_inference_steps": 30, "true_cfg_scale": 2.5, "width": 512, "height": 512,
            "seed": 42, "negative_prompt": "blurry", "prompt_suffix": "Ultra HD, 4K.",
            "enable_cpu_offload": True,
            "enable_attention_slicing": True, "low_vram_mode": True,
            "model_cache_dir": "/tmp/cache", "allow_cpu": True, "fallback_provider": "BFL",
            "letterbox_detection_enabled": False, "lightning_lora_enabled": True,
            "lightning_lora_repo_id": "org/lora-repo", "lightning_lora_weight_name": "weights.safetensors",
        })

        self.assertEqual(settings.model_id, "org/model")
        self.assertEqual(settings.device, "cuda")
        self.assertEqual(settings.dtype, "float16")
        self.assertEqual(settings.num_inference_steps, 30)
        self.assertEqual(settings.true_cfg_scale, 2.5)
        self.assertEqual(settings.seed, 42)
        self.assertEqual(settings.negative_prompt, "blurry")
        self.assertEqual(settings.prompt_suffix, "Ultra HD, 4K.")
        self.assertEqual(settings.fallback_provider, "bfl")
        self.assertTrue(settings.allow_cpu)
        self.assertFalse(settings.letterbox_detection_enabled)
        self.assertTrue(settings.lightning_lora_enabled)
        self.assertEqual(settings.lightning_lora_repo_id, "org/lora-repo")
        self.assertEqual(settings.lightning_lora_weight_name, "weights.safetensors")

    def test_from_mapping_rejects_invalid_device(self) -> None:
        with self.assertRaises(ValueError):
            QwenImageLocalSettings.from_mapping({"device": "tpu"})

    def test_from_mapping_rejects_invalid_dtype(self) -> None:
        with self.assertRaises(ValueError):
            QwenImageLocalSettings.from_mapping({"dtype": "int8"})


class QwenImageLocalImageProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._temp_dir.cleanup)
        self.output_file = Path(self._temp_dir.name) / "scene01.png"
        self.settings = QwenImageLocalSettings.from_mapping({
            "seed": 123, "allow_cpu": True, "width": 800, "height": 600,
        })

    def test_generate_image_uses_correct_generation_arguments(self) -> None:
        source_image = Image.new("RGB", (800, 600), color="red")
        pipeline = FakePipeline(source_image)
        torch_module = FakeTorch(cuda_available=False)
        diffusers_module = FakeDiffusers(pipeline)
        provider = QwenImageLocalImageProvider(self.settings, "640x360")

        with patch.object(QwenImageLocalImageProvider, "_import_torch", staticmethod(lambda: torch_module)), \
             patch.object(QwenImageLocalImageProvider, "_import_diffusers", staticmethod(lambda: diffusers_module)):
            provider.generate_image("a calm landscape", self.output_file)

        call = pipeline.calls[0]
        self.assertEqual(call["prompt"], "a calm landscape")
        self.assertEqual(call["negative_prompt"], "")
        self.assertEqual((call["width"], call["height"]), (800, 600))
        self.assertEqual(call["num_inference_steps"], 50)
        self.assertEqual(call["true_cfg_scale"], 4.0)
        self.assertEqual(call["generator"].seed, 123)

    def test_prompt_suffix_is_appended_when_configured(self) -> None:
        settings = QwenImageLocalSettings.from_mapping({
            "seed": 123, "allow_cpu": True, "prompt_suffix": "Ultra HD, 4K, cinematic composition. No text.",
        })
        source_image = Image.new("RGB", (800, 600), color="red")
        pipeline = FakePipeline(source_image)
        torch_module = FakeTorch(cuda_available=False)
        diffusers_module = FakeDiffusers(pipeline)
        provider = QwenImageLocalImageProvider(settings, "640x360")

        with patch.object(QwenImageLocalImageProvider, "_import_torch", staticmethod(lambda: torch_module)), \
             patch.object(QwenImageLocalImageProvider, "_import_diffusers", staticmethod(lambda: diffusers_module)):
            provider.generate_image("a calm landscape", self.output_file)

        self.assertEqual(
            pipeline.calls[0]["prompt"],
            "a calm landscape, Ultra HD, 4K, cinematic composition. No text.",
        )

    def test_prompt_suffix_defaults_to_empty(self) -> None:
        settings = QwenImageLocalSettings.from_mapping({"seed": 123, "allow_cpu": True})
        source_image = Image.new("RGB", (800, 600), color="red")
        pipeline = FakePipeline(source_image)
        torch_module = FakeTorch(cuda_available=False)
        diffusers_module = FakeDiffusers(pipeline)
        provider = QwenImageLocalImageProvider(settings, "640x360")

        with patch.object(QwenImageLocalImageProvider, "_import_torch", staticmethod(lambda: torch_module)), \
             patch.object(QwenImageLocalImageProvider, "_import_diffusers", staticmethod(lambda: diffusers_module)):
            provider.generate_image("a calm landscape", self.output_file)

        self.assertEqual(pipeline.calls[0]["prompt"], "a calm landscape")

    def test_lightning_lora_disabled_by_default_skips_lora_and_default_scheduler(self) -> None:
        source_image = Image.new("RGB", (800, 600), color="red")
        pipeline = FakePipeline(source_image)
        torch_module = FakeTorch(cuda_available=False)
        diffusers_module = FakeDiffusers(pipeline)
        provider = QwenImageLocalImageProvider(self.settings, "640x360")

        with patch.object(QwenImageLocalImageProvider, "_import_torch", staticmethod(lambda: torch_module)), \
             patch.object(QwenImageLocalImageProvider, "_import_diffusers", staticmethod(lambda: diffusers_module)):
            provider.generate_image("prompt", self.output_file)

        self.assertEqual(pipeline.load_lora_weights_calls, [])
        self.assertIsNone(diffusers_module.DiffusionPipeline.from_pretrained_kwargs[0]["scheduler"])

    def test_lightning_lora_enabled_loads_lora_and_dedicated_scheduler(self) -> None:
        settings = QwenImageLocalSettings.from_mapping({
            "seed": 123, "allow_cpu": True, "true_cfg_scale": 1.0, "lightning_lora_enabled": True,
        })
        source_image = Image.new("RGB", (800, 600), color="red")
        pipeline = FakePipeline(source_image)
        torch_module = FakeTorch(cuda_available=False)
        diffusers_module = FakeDiffusers(pipeline)
        provider = QwenImageLocalImageProvider(settings, "640x360")

        with patch.object(QwenImageLocalImageProvider, "_import_torch", staticmethod(lambda: torch_module)), \
             patch.object(QwenImageLocalImageProvider, "_import_diffusers", staticmethod(lambda: diffusers_module)):
            provider.generate_image("prompt", self.output_file)

        self.assertEqual(pipeline.load_lora_weights_calls, [{
            "repo_id": "lightx2v/Qwen-Image-Lightning",
            "weight_name": "Qwen-Image-Lightning-8steps-V2.0.safetensors",
            "cache_dir": None,
        }])
        scheduler = diffusers_module.DiffusionPipeline.from_pretrained_kwargs[0]["scheduler"]
        self.assertIsInstance(scheduler, FakeScheduler)
        self.assertEqual(scheduler.config["shift"], 1.0)
        self.assertTrue(scheduler.config["use_dynamic_shifting"])

    def test_lightning_lora_load_failure_raises_descriptive_error(self) -> None:
        settings = QwenImageLocalSettings.from_mapping({
            "seed": 123, "allow_cpu": True, "true_cfg_scale": 1.0, "lightning_lora_enabled": True,
        })
        pipeline = FakePipeline(
            Image.new("RGB", (800, 600)), lora_error=OSError("network unreachable"),
        )
        torch_module = FakeTorch(cuda_available=False)
        diffusers_module = FakeDiffusers(pipeline)
        provider = QwenImageLocalImageProvider(settings, "640x360")

        with patch.object(QwenImageLocalImageProvider, "_import_torch", staticmethod(lambda: torch_module)), \
             patch.object(QwenImageLocalImageProvider, "_import_diffusers", staticmethod(lambda: diffusers_module)):
            with self.assertRaises(ImageGenerationError) as context:
                provider.generate_image("prompt", self.output_file)

        self.assertIn("network unreachable", str(context.exception))

    def test_negative_prompt_is_configurable(self) -> None:
        settings = QwenImageLocalSettings.from_mapping({
            "seed": 1, "allow_cpu": True, "negative_prompt": "blurry, low quality",
        })
        source_image = Image.new("RGB", (800, 600), color="red")
        pipeline = FakePipeline(source_image)
        torch_module = FakeTorch(cuda_available=False)
        diffusers_module = FakeDiffusers(pipeline)
        provider = QwenImageLocalImageProvider(settings, "640x360")

        with patch.object(QwenImageLocalImageProvider, "_import_torch", staticmethod(lambda: torch_module)), \
             patch.object(QwenImageLocalImageProvider, "_import_diffusers", staticmethod(lambda: diffusers_module)):
            provider.generate_image("prompt", self.output_file)

        self.assertEqual(pipeline.calls[0]["negative_prompt"], "blurry, low quality")

    def test_generate_image_saves_image_resized_to_output_size_preserving_aspect(self) -> None:
        source_image = Image.new("RGB", (800, 600), color="blue")
        pipeline = FakePipeline(source_image)
        torch_module = FakeTorch(cuda_available=False)
        diffusers_module = FakeDiffusers(pipeline)
        provider = QwenImageLocalImageProvider(self.settings, "640x360")

        with patch.object(QwenImageLocalImageProvider, "_import_torch", staticmethod(lambda: torch_module)), \
             patch.object(QwenImageLocalImageProvider, "_import_diffusers", staticmethod(lambda: diffusers_module)):
            provider.generate_image("prompt", self.output_file)

        with Image.open(self.output_file) as saved_image:
            self.assertEqual(saved_image.size, (640, 360))

    def test_generate_image_skips_resize_when_resize_to_output_size_is_false(self) -> None:
        """シーン画像生成用途ではresize_to_output_size=Falseとなり、生成解像度のまま
        保存される（scene_sizeへの整形は動画レンダリング時にffmpegが行うため不要）。"""
        source_image = Image.new("RGB", (800, 600), color="blue")
        pipeline = FakePipeline(source_image)
        torch_module = FakeTorch(cuda_available=False)
        diffusers_module = FakeDiffusers(pipeline)
        provider = QwenImageLocalImageProvider(self.settings, "640x360", resize_to_output_size=False)

        with patch.object(QwenImageLocalImageProvider, "_import_torch", staticmethod(lambda: torch_module)), \
             patch.object(QwenImageLocalImageProvider, "_import_diffusers", staticmethod(lambda: diffusers_module)):
            provider.generate_image("prompt", self.output_file)

        with Image.open(self.output_file) as saved_image:
            self.assertEqual(saved_image.size, (800, 600))

    def test_generate_image_embeds_seed_metadata_for_reproducibility(self) -> None:
        source_image = Image.new("RGB", (800, 600), color="green")
        pipeline = FakePipeline(source_image)
        torch_module = FakeTorch(cuda_available=False)
        diffusers_module = FakeDiffusers(pipeline)
        provider = QwenImageLocalImageProvider(self.settings, "640x360")

        with patch.object(QwenImageLocalImageProvider, "_import_torch", staticmethod(lambda: torch_module)), \
             patch.object(QwenImageLocalImageProvider, "_import_diffusers", staticmethod(lambda: diffusers_module)):
            provider.generate_image("prompt", self.output_file)

        with Image.open(self.output_file) as saved_image:
            self.assertEqual(saved_image.text.get("qwen_image_local:seed"), "123")

    def test_pipeline_is_lazily_loaded_and_reused_across_calls(self) -> None:
        source_image = Image.new("RGB", (800, 600), color="yellow")
        pipeline = FakePipeline(source_image)
        torch_module = FakeTorch(cuda_available=False)
        diffusers_module = FakeDiffusers(pipeline)
        provider = QwenImageLocalImageProvider(self.settings, "640x360")

        with patch.object(QwenImageLocalImageProvider, "_import_torch", staticmethod(lambda: torch_module)), \
             patch.object(QwenImageLocalImageProvider, "_import_diffusers", staticmethod(lambda: diffusers_module)):
            self.assertEqual(diffusers_module.DiffusionPipeline.from_pretrained_calls, 0)
            provider.generate_image("prompt one", self.output_file)
            provider.generate_image("prompt two", Path(self._temp_dir.name) / "scene02.png")

        self.assertEqual(diffusers_module.DiffusionPipeline.from_pretrained_calls, 1)
        self.assertEqual(len(pipeline.calls), 2)

    def test_regenerates_with_new_seed_when_letterbox_bars_detected(self) -> None:
        """レターボックス帯を検出した場合、seed未指定なら別seedで再生成すること。"""
        letterboxed_image = Image.new("RGB", (800, 600), color=(0, 0, 0))
        clean_image = Image.new("RGB", (800, 600), color=(120, 140, 160))
        pipeline = FakePipeline([letterboxed_image, clean_image])
        torch_module = FakeTorch(cuda_available=False)
        diffusers_module = FakeDiffusers(pipeline)
        settings = QwenImageLocalSettings.from_mapping({"allow_cpu": True, "width": 800, "height": 600})
        provider = QwenImageLocalImageProvider(settings, "640x360", resize_to_output_size=False)

        with patch.object(QwenImageLocalImageProvider, "_import_torch", staticmethod(lambda: torch_module)), \
             patch.object(QwenImageLocalImageProvider, "_import_diffusers", staticmethod(lambda: diffusers_module)):
            provider.generate_image("prompt", self.output_file)

        self.assertEqual(len(pipeline.calls), 2)
        with Image.open(self.output_file) as saved_image:
            self.assertEqual(saved_image.getpixel((0, 0)), (120, 140, 160))

    def test_fixed_seed_does_not_retry_even_if_letterbox_detected(self) -> None:
        """seedが固定されている場合は再生成しても同じ画像になるため、検出しても再試行しないこと。"""
        letterboxed_image = Image.new("RGB", (800, 600), color=(0, 0, 0))
        pipeline = FakePipeline(letterboxed_image)
        torch_module = FakeTorch(cuda_available=False)
        diffusers_module = FakeDiffusers(pipeline)
        provider = QwenImageLocalImageProvider(self.settings, "640x360", resize_to_output_size=False)

        with patch.object(QwenImageLocalImageProvider, "_import_torch", staticmethod(lambda: torch_module)), \
             patch.object(QwenImageLocalImageProvider, "_import_diffusers", staticmethod(lambda: diffusers_module)):
            provider.generate_image("prompt", self.output_file)

        self.assertEqual(len(pipeline.calls), 1)
        with Image.open(self.output_file) as saved_image:
            self.assertEqual(saved_image.getpixel((0, 0)), (0, 0, 0))

    def test_letterbox_detection_disabled_skips_retry(self) -> None:
        """letterbox_detection_enabled=falseの場合、検出しても再生成せず1回のみ生成すること。"""
        letterboxed_image = Image.new("RGB", (800, 600), color=(0, 0, 0))
        pipeline = FakePipeline(letterboxed_image)
        torch_module = FakeTorch(cuda_available=False)
        diffusers_module = FakeDiffusers(pipeline)
        settings = QwenImageLocalSettings.from_mapping({
            "allow_cpu": True, "width": 800, "height": 600, "letterbox_detection_enabled": False,
        })
        provider = QwenImageLocalImageProvider(settings, "640x360", resize_to_output_size=False)

        with patch.object(QwenImageLocalImageProvider, "_import_torch", staticmethod(lambda: torch_module)), \
             patch.object(QwenImageLocalImageProvider, "_import_diffusers", staticmethod(lambda: diffusers_module)):
            provider.generate_image("prompt", self.output_file)

        self.assertEqual(len(pipeline.calls), 1)
        with Image.open(self.output_file) as saved_image:
            self.assertEqual(saved_image.getpixel((0, 0)), (0, 0, 0))

    def test_release_clears_loaded_pipeline_and_frees_cuda_memory(self) -> None:
        source_image = Image.new("RGB", (800, 600), color="black")
        pipeline = FakePipeline(source_image)
        torch_module = FakeTorch(cuda_available=True)
        diffusers_module = FakeDiffusers(pipeline)
        settings = QwenImageLocalSettings.from_mapping({"seed": 1})
        provider = QwenImageLocalImageProvider(settings, "640x360")

        with patch.object(QwenImageLocalImageProvider, "_import_torch", staticmethod(lambda: torch_module)), \
             patch.object(QwenImageLocalImageProvider, "_import_diffusers", staticmethod(lambda: diffusers_module)):
            provider.generate_image("prompt", self.output_file)
            provider.release()
            provider.generate_image("prompt again", Path(self._temp_dir.name) / "scene02.png")

        # release()後の再生成でモデルが再ロードされること（=一度解放されたこと）を確認する。
        self.assertEqual(diffusers_module.DiffusionPipeline.from_pretrained_calls, 2)
        self.assertEqual(torch_module.cuda.empty_cache_calls, 1)

    def test_cuda_out_of_memory_raises_descriptive_error(self) -> None:
        source_image = Image.new("RGB", (800, 600))
        oom_error = FakeCudaOutOfMemoryError("CUDA out of memory")
        pipeline = FakePipeline(source_image, raise_error=oom_error)
        torch_module = FakeTorch(cuda_available=True)
        diffusers_module = FakeDiffusers(pipeline)
        provider = QwenImageLocalImageProvider(self.settings, "640x360")

        with patch.object(QwenImageLocalImageProvider, "_import_torch", staticmethod(lambda: torch_module)), \
             patch.object(QwenImageLocalImageProvider, "_import_diffusers", staticmethod(lambda: diffusers_module)):
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
        provider = QwenImageLocalImageProvider(self.settings, "640x360")

        with patch.object(QwenImageLocalImageProvider, "_import_torch", staticmethod(lambda: torch_module)), \
             patch.object(QwenImageLocalImageProvider, "_import_diffusers", staticmethod(lambda: diffusers_module)):
            with self.assertRaises(ImageGenerationError) as context:
                provider.generate_image("prompt", self.output_file)

        message = str(context.exception)
        self.assertIn(self.settings.model_id, message)
        self.assertIn("network unreachable", message)

    def test_device_cpu_requires_allow_cpu(self) -> None:
        settings = QwenImageLocalSettings.from_mapping({"device": "cpu", "allow_cpu": False})
        pipeline = FakePipeline(Image.new("RGB", (800, 600)))
        torch_module = FakeTorch(cuda_available=False)
        diffusers_module = FakeDiffusers(pipeline)
        provider = QwenImageLocalImageProvider(settings, "640x360")

        with patch.object(QwenImageLocalImageProvider, "_import_torch", staticmethod(lambda: torch_module)), \
             patch.object(QwenImageLocalImageProvider, "_import_diffusers", staticmethod(lambda: diffusers_module)):
            with self.assertRaises(ImageGenerationError):
                provider.generate_image("prompt", self.output_file)

    def test_auto_device_without_cuda_requires_allow_cpu(self) -> None:
        settings = QwenImageLocalSettings.from_mapping({"device": "auto", "allow_cpu": False})
        pipeline = FakePipeline(Image.new("RGB", (800, 600)))
        torch_module = FakeTorch(cuda_available=False)
        diffusers_module = FakeDiffusers(pipeline)
        provider = QwenImageLocalImageProvider(settings, "640x360")

        with patch.object(QwenImageLocalImageProvider, "_import_torch", staticmethod(lambda: torch_module)), \
             patch.object(QwenImageLocalImageProvider, "_import_diffusers", staticmethod(lambda: diffusers_module)):
            with self.assertRaises(ImageGenerationError):
                provider.generate_image("prompt", self.output_file)

    def test_torch_missing_raises_actionable_error(self) -> None:
        provider = QwenImageLocalImageProvider(self.settings, "640x360")

        with patch.object(
            QwenImageLocalImageProvider, "_import_torch",
            staticmethod(lambda: (_ for _ in ()).throw(ImageGenerationError("torchがインストールされていません。"))),
        ):
            with self.assertRaisesRegex(ImageGenerationError, "torch"):
                provider.generate_image("prompt", self.output_file)


if __name__ == "__main__":
    unittest.main()
