# -*- coding: utf-8 -*-
"""本地配音：Piper（离线、CPU 秒级出音）。

Piper 模型缺失时自动回退到 edge-tts（免费但需联网）。
"""

import os
import subprocess
import uuid
import wave

ROOT = os.path.dirname(os.path.abspath(__file__))
PIPER_DIR = os.path.join(ROOT, "models", "piper_text", "zh", "zh_CN", "huayan", "medium")
ONNX = os.path.join(PIPER_DIR, "zh_CN-huayan-medium.onnx")
CONFIG = ONNX + ".json"

_voice = None


def is_ready() -> bool:
    return os.path.exists(ONNX) and os.path.exists(CONFIG)


def _load():
    global _voice
    if _voice is not None:
        return _voice
    from piper import PiperVoice
    _voice = PiperVoice.load(ONNX, config_path=CONFIG)
    return _voice


def synth(text: str, out_dir: str) -> str:
    """用 Piper 合成语音，返回 wav 文件名。"""
    voice = _load()
    name = "tts_%s.wav" % uuid.uuid4().hex[:10]
    path = os.path.join(out_dir, name)
    sample_rate = getattr(getattr(voice, "config", None), "sample_rate", 22050)
    with wave.open(path, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        try:
            voice.synthesize(text, wav)          # piper-tts >= 1.2
        except TypeError:                        # 旧版 API
            voice.synthesize_wav(text, wav)
    return name


def wav_to_mp3(wav_path: str) -> str:
    """转 mp3（体积小一些），失败则返回原 wav。"""
    import providers
    mp3 = os.path.splitext(wav_path)[0] + ".mp3"
    try:
        subprocess.run(
            [providers._ffmpeg_bin(), "-y", "-i", wav_path,
             "-c:a", "libmp3lame", "-b:a", "128k", mp3],
            check=True, capture_output=True)
        os.remove(wav_path)
        return os.path.basename(mp3)
    except Exception:
        return os.path.basename(wav_path)
