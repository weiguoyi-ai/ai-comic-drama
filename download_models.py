# -*- coding: utf-8 -*-
"""本地模型下载器（一次性，约 5GB）

用法:
    python download_models.py           # 下载全部
    python download_models.py image     # 只下生图模型
    python download_models.py llm       # 只下分镜模型
    python download_models.py tts       # 只下本地配音模型

ModelScope 走 HTTP 直连（国内快、无需额外依赖），LCM LoRA 与配音声线走 hf-mirror。
支持断点续跑：已存在的文件会跳过。
"""

import os
import sys

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

ROOT = os.path.dirname(os.path.abspath(__file__))
MODELS = os.path.join(ROOT, "models")

MS_API = "https://www.modelscope.cn/api/v1/models/%s/repo/files?Revision=master&Recursive=True"
MS_FILE = "https://www.modelscope.cn/models/%s/resolve/master/%s"

MODELSCOPE = {
    "image": [("AI-ModelScope/stable-diffusion-v1-5", "sd-base")],
    "llm": [("Qwen/Qwen2.5-1.5B-Instruct", "qwen-1.5b")],
}

HF = {
    "image": [("latent-consistency/lcm-lora-sdv1-5", "lcm-lora", ["*.json", "*.safetensors"])],
    "tts": [("rhasspy/piper-voices", "piper_text", ["zh/zh_CN/huayan/medium/*"])],
}

SKIP_NAMES = ("readme", "license", "usage", ".gitattributes", ".gitignore")
# 体积冗余、diffusers 加载不需要的文件（省 10GB+ 流量）
SKIP_PARTS = ("safety_checker/",)
SKIP_SUFFIX = (".bin", ".ckpt", ".msgpack", ".h5")


def _has_files(d: str) -> bool:
    return os.path.isdir(d) and any(os.scandir(d))


def _skip(path: str) -> bool:
    low = path.lower()
    if any(low == n or low.startswith(n) for n in SKIP_NAMES):
        return True
    if any(p in low for p in SKIP_PARTS):
        return True
    if low.endswith(SKIP_SUFFIX):
        return True
    return "pruned" in low


def from_modelscope(repo: str, local: str):
    import requests

    dest = os.path.join(MODELS, local)
    os.makedirs(dest, exist_ok=True)
    print(f"[ModelScope] {repo} → models/{local}")
    files = requests.get(MS_API % repo, timeout=30).json()["Data"]["Files"]
    blobs = [f["Path"] for f in files if f.get("Type") == "blob" and not _skip(f["Path"])]
    for i, path in enumerate(blobs, 1):
        out = os.path.join(dest, path.replace("/", os.sep))
        os.makedirs(os.path.dirname(out) or dest, exist_ok=True)
        if os.path.exists(out) and os.path.getsize(out) > 1024:
            print(f"  [{i}/{len(blobs)}] 已存在 {path}")
            continue
        with requests.get(MS_FILE % (repo, path), stream=True, timeout=120) as r:
            r.raise_for_status()
            with open(out, "wb") as f:
                for chunk in r.iter_content(1024 * 512):
                    f.write(chunk)
        print(f"  [{i}/{len(blobs)}] ✅ {path}  ({os.path.getsize(out)/1048576:.1f} MB)")
    print(f"[完成] {local}")


def from_hf(repo: str, local: str, patterns):
    from huggingface_hub import snapshot_download

    dest = os.path.join(MODELS, local)
    print(f"[hf-mirror] {repo} → models/{local}")
    snapshot_download(repo_id=repo, local_dir=dest,
                      allow_patterns=patterns, max_workers=4)
    print(f"[完成] {local}")


def download(group: str):
    for repo, local in MODELSCOPE.get(group, []):
        from_modelscope(repo, local)   # 内部逐文件判断，已下载的会自动跳过
    for repo, local, patterns in HF.get(group, []):
        from_hf(repo, local, patterns)


def main():
    arg = (sys.argv[1] if len(sys.argv) > 1 else "all").lower()
    os.makedirs(MODELS, exist_ok=True)
    if arg not in ("all", "image", "llm", "tts"):
        print("可选参数: all / image / llm / tts")
        return 1
    for g in (["image", "llm", "tts"] if arg == "all" else [arg]):
        print(f"\n===== {g} =====")
        try:
            download(g)
        except Exception as e:
            print(f"[失败] {g}: {e}\n  可重跑本脚本续传。")
    print("\n结束。启动 python server.py 会自动使用本地模型。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
