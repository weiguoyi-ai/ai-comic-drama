# -*- coding: utf-8 -*-
"""本地生图：Stable Diffusion 1.5（DreamShaper 8）+ LCM 加速，纯 CPU 运行。

CPU 上采用 512×896（竖屏）/ 896×512（横屏）+ 4~8 步 LCM 采样，
单张约 30~90 秒；最终由 ffmpeg 放大到 720×1280。
"""

import os
import threading

ROOT = os.path.dirname(os.path.abspath(__file__))
MODELS = os.path.join(ROOT, "models")
SD_DIR = os.path.join(MODELS, "sd-base")
LORA_DIR = os.path.join(MODELS, "lcm-lora")

_lock = threading.Lock()
_pipe = None


def is_ready() -> bool:
    """本地生图模型是否就绪。"""
    return os.path.isdir(SD_DIR) and os.path.isdir(LORA_DIR)


def _load():
    global _pipe
    if _pipe is not None:
        return _pipe
    import torch
    from diffusers import LCMScheduler, StableDiffusionPipeline

    torch.set_num_threads(min(4, os.cpu_count() or 4))
    pipe = StableDiffusionPipeline.from_pretrained(
        SD_DIR, torch_dtype=torch.float32, safety_checker=None,
        requires_safety_checker=False, local_files_only=True,
    )
    pipe.scheduler = LCMScheduler.from_config(pipe.scheduler.config)
    lora_file = os.path.join(LORA_DIR, "pytorch_lora_weights.safetensors")
    pipe.load_lora_weights(lora_file if os.path.exists(lora_file) else LORA_DIR,
                           adapter_name="lcm")
    pipe.set_adapters(["lcm"], adapter_weights=[1.0])
    pipe.to("cpu")
    pipe.enable_attention_slicing()
    try:
        pipe.enable_vae_slicing()
    except Exception:
        pass
    _pipe = pipe
    return pipe


NEGATIVE = ("lowres, bad anatomy, bad hands, extra fingers, watermark, text, "
            "signature, blurry, jpeg artifacts, deformed, ugly")


def generate(prompt: str, out_path: str, aspect: str = "9:16",
             steps: int = 6, guidance: float = 1.6, seed: int = -1) -> str:
    """生成一张图并保存，返回文件路径。"""
    import torch

    with _lock:
        pipe = _load()
        w, h = (512, 896) if aspect == "9:16" else (896, 512)
        generator = None
        if seed >= 0:
            generator = torch.Generator("cpu").manual_seed(seed)
        image = pipe(
            prompt=prompt, negative_prompt=NEGATIVE,
            width=w, height=h, num_inference_steps=steps,
            guidance_scale=guidance, generator=generator,
        ).images[0]
        image.save(out_path, quality=95)
    return out_path
