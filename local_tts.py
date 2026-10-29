# -*- coding: utf-8 -*-
"""本地配音（离线、免费）。

优先级：
1. Piper（音质好；注意 piper-tts 1.8.0 的 Windows 轮子有 espeak 路径 bug，
   合成出空音频时自动跳过）
2. Windows SAPI 语音（系统自带 zh-CN 语音包，完全离线、零依赖）
3. 都不可用时抛错，由 providers 回退 edge-tts（免费但需联网）
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
_piper_broken = False   # piper 产出空音频时置 True，避免每次都白跑


def is_ready() -> bool:
    """本地是否有可用的离线配音能力（Piper 模型或 Windows SAPI 中文语音）。"""
    return (os.path.exists(ONNX) and os.path.exists(CONFIG)) or _sapi_has_zh()


def _load():
    global _voice
    if _voice is not None:
        return _voice
    from piper import PiperVoice
    _voice = PiperVoice.load(ONNX, config_path=CONFIG)
    return _voice


# ---------------------------------------------------------------- Piper

def _piper_synth(text: str, path: str, rate: int = 0) -> None:
    voice = _load()
    sample_rate = getattr(getattr(voice, "config", None), "sample_rate", 22050)
    syn_cfg = None
    if rate:
        try:
            from piper import SynthesisConfig
            # length_scale 越大越慢：语速 +20% → length_scale 0.83
            syn_cfg = SynthesisConfig(length_scale=max(0.5, 1.0 / (1.0 + rate / 100.0)))
        except Exception:
            syn_cfg = None
    with wave.open(path, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        if syn_cfg is not None:
            voice.synthesize(text, wav, syn_config=syn_cfg)
        else:
            voice.synthesize(text, wav)


def _wav_seconds(path: str) -> float:
    try:
        with wave.open(path) as w:
            return w.getnframes() / max(1, w.getframerate())
    except Exception:
        return 0.0


# ---------------------------------------------------------------- Windows SAPI

def _sapi_has_zh() -> bool:
    try:
        import win32com.client
        v = win32com.client.Dispatch("SAPI.SPVoice")
        return v.GetVoices("Language=804").Count > 0
    except Exception:
        return False


def _sapi_synth(text: str, path: str, rate: int = 0) -> None:
    """用 Windows 自带语音合成 WAV（完全离线）。

    rate 为百分比（-50~50），SAPI 的 Rate 是 -10~10 档，这里做折算。
    """
    import pythoncom
    import win32com.client

    pythoncom.CoInitialize()
    try:
        voice = win32com.client.Dispatch("SAPI.SPVoice")
        try:
            zh = voice.GetVoices("Language=804")
            if zh.Count > 0:
                voice.Voice = zh.Item(0)
        except Exception:
            pass  # 没有中文语音包就用默认语音
        try:
            voice.Rate = max(-10, min(10, round(rate / 5.0)))
        except Exception:
            pass
        stream = win32com.client.Dispatch("SAPI.SpFileStream")
        stream.Open(path, 3)          # SSFMCreateForWrite
        voice.AudioOutputStream = stream
        try:
            voice.Speak(text)
        finally:
            voice.AudioOutputStream = None
            stream.Close()
    finally:
        pythoncom.CoUninitialize()


# ---------------------------------------------------------------- 对外接口

def synth(text: str, out_dir: str, rate: int = 0) -> str:
    """离线合成语音，返回 wav 文件名；失败抛异常。"""
    global _piper_broken
    name = "tts_%s.wav" % uuid.uuid4().hex[:10]
    path = os.path.join(out_dir, name)

    # 1) Piper（若 wheel 正常）
    if not _piper_broken and os.path.exists(ONNX) and os.path.exists(CONFIG):
        try:
            _piper_synth(text, path, rate)
            if _wav_seconds(path) >= 0.5:
                return name
            _piper_broken = True     # 空音频 → piper 环境有问题，后续不再尝试
        except Exception:
            _piper_broken = True
        finally:
            if _piper_broken and os.path.exists(path):
                os.remove(path)

    # 2) Windows SAPI（系统自带，完全离线）
    _sapi_synth(text, path, rate)
    if _wav_seconds(path) < 0.5:
        os.remove(path)
        raise RuntimeError("Windows SAPI 合成失败（请检查系统语音包）")
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
