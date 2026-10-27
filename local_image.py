# -*- coding: utf-8 -*-
"""本地生图：Stable Diffusion 1.5（DreamShaper 8）+ LCM 加速，纯 CPU 运行。

CPU 优化要点：
- 关闭 attention/vae slicing（那是省显存用的，在 CPU 上只会更慢）
- UNet/VAE 使用 channels_last，配合 oneDNN 提速
- 线程数交给 torch 吃满物理核心（可配置）
- LCM 4 步采样，画质档位可调（fast / normal / high）

最终由 ffmpeg 放大到 720×1280（竖屏）或 1280×720（横屏）。
"""

import os
import threading

ROOT = os.path.dirname(os.path.abspath(__file__))
MODELS = os.path.join(ROOT, "models")
SD_DIR = os.path.join(MODELS, "sd-base")
LORA_DIR = os.path.join(MODELS, "lcm-lora")

_lock = threading.Lock()
_pipe = None
_pipe_opts = {}

# 画质档位 → (竖屏宽高, 横屏宽高)；全部为 64 的整数倍
RESOLUTIONS = {
    "fast": {"9:16": (448, 768), "16:9": (768, 448)},
    "normal": {"9:16": (512, 896), "16:9": (896, 512)},
    "high": {"9:16": (576, 1024), "16:9": (1024, 576)},
}

NEGATIVE = ("lowres, bad anatomy, bad hands, extra fingers, watermark, text, "
            "signature, blurry, jpeg artifacts, deformed, ugly, "
            "extra limbs, mutated hands, worst quality, low quality")

# 给本地 SD1.5 补一层通用质感词（英文模型对这类词最敏感）
QUALITY_BOOST = ("masterpiece, best quality, highly detailed, sharp focus, "
                 "cinematic lighting, depth of field")


def is_ready() -> bool:
    """本地生图模型是否就绪。"""
    return os.path.isdir(SD_DIR) and os.path.isdir(LORA_DIR)


def _default_threads() -> int:
    return max(2, os.cpu_count() or 4)


def _load(threads: int = 0, low_mem: bool = False):
    """加载流水线。threads/low_mem 变化时自动重建。"""
    global _pipe, _pipe_opts
    opts = {"threads": threads or _default_threads(), "low_mem": bool(low_mem)}
    if _pipe is not None and _pipe_opts == opts:
        return _pipe

    import torch
    from diffusers import LCMScheduler, StableDiffusionPipeline

    torch.set_num_threads(opts["threads"])
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

    # channels_last：让 oneDNN 走更快的卷积路径（CPU 上通常有 10~20% 提升）
    try:
        pipe.unet.to(memory_format=torch.channels_last)
        pipe.vae.to(memory_format=torch.channels_last)
    except Exception:
        pass

    # 内存紧张时才开启分片（16G 内存无需，开了反而慢）
    if opts["low_mem"]:
        pipe.enable_attention_slicing()
        try:
            pipe.enable_vae_slicing()
        except Exception:
            pass

    _pipe, _pipe_opts = pipe, opts
    return pipe


def _size_for(aspect: str, preset: str):
    table = RESOLUTIONS.get(preset) or RESOLUTIONS["normal"]
    return table.get("16:9" if aspect.startswith("16") else "9:16")


def generate(prompt: str, out_path: str, aspect: str = "9:16",
             steps: int = 4, guidance: float = 1.6, seed: int = -1,
             preset: str = "normal", threads: int = 0,
             low_mem: bool = False, quality_boost: bool = True) -> str:
    """生成一张图并保存，返回文件路径。"""
    import torch

    w, h = _size_for(aspect, preset)
    full_prompt = prompt
    if quality_boost and "masterpiece" not in prompt.lower():
        full_prompt = QUALITY_BOOST + ", " + prompt

    with _lock:
        pipe = _load(threads, low_mem)
        generator = None
        if seed >= 0:
            generator = torch.Generator("cpu").manual_seed(seed)
        image = pipe(
            prompt=full_prompt, negative_prompt=NEGATIVE,
            width=w, height=h, num_inference_steps=max(1, int(steps)),
            guidance_scale=guidance, generator=generator,
        ).images[0]
        os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
        image.save(out_path, quality=95)
    return out_path
