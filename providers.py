# -*- coding: utf-8 -*-
"""AI Provider 适配层：LLM 分镜 / 生图 / TTS

所有模型调用都做成可插拔配置，默认提供 mock 模式（无需 API Key 即可跑通全流程）。
"""

import json
import os
import re
import uuid

import requests

ROOT = os.path.dirname(os.path.abspath(__file__))


def load_config() -> dict:
    """加载 config.json（不存在时回退到 config.example.json，即 mock 模式）。"""
    path = os.path.join(ROOT, "config.json")
    fallback = os.path.join(ROOT, "config.example.json")
    src = path if os.path.exists(path) else fallback
    with open(src, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------- LLM：剧本 → 分镜

STORYBOARD_PROMPT = """你是一名专业漫画分镜师。请把下面的故事/剧本改编成 {scene_count} 个漫画分镜。

要求：
1. 先提炼主要角色的外貌特征（发型、服装、气质），保证后续每格画面里角色形象一致；
2. 每个分镜包含：title（分镜标题）、narration（旁白，1-2句）、dialogue（角色台词，可为空字符串）、
   image_prompt（画面描述，中文，包含人物外貌+动作+场景+氛围，40字以内）、characters（该分镜出场角色）；
3. 只输出 JSON 数组，不要输出任何其他文字。格式示例：
[{{"title":"...","narration":"...","dialogue":"...","image_prompt":"...","characters":["..."]}}]

画风要求：{style}

故事/剧本：
{script}
"""


def _strip_json(text: str):
    """从 LLM 输出中提取 JSON 数组（容错处理 markdown 代码块等）。"""
    text = re.sub(r"```(?:json)?", "", text).strip().strip("`")
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1:
        return json.loads(text[start:end + 1])
    raise ValueError("LLM 输出中未找到 JSON 数组")


def gen_storyboard(script: str, style: str, scene_count: int) -> dict:
    """调用 LLM 生成分镜。返回 {"characters": ..., "scenes": [...]}"""
    cfg = load_config()["llm"]
    if cfg.get("mock"):
        return _mock_storyboard(script, style, scene_count)

    prompt = STORYBOARD_PROMPT.format(
        scene_count=scene_count, style=style, script=script[:6000]
    )
    resp = requests.post(
        cfg["base_url"].rstrip("/") + "/chat/completions",
        headers={"Authorization": "Bearer " + cfg["api_key"]},
        json={
            "model": cfg["model"],
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.8,
        },
        timeout=120,
    )
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]
    scenes = _strip_json(content)

    # 从分镜中汇总角色表，用于图片提示词保持角色一致性
    characters = {}
    for sc in scenes:
        for name in sc.get("characters", []):
            if name and name not in characters:
                characters[name] = ""
        # 尝试从旁白/画面描述中提取角色描述
        for name in list(characters):
            if name and name in sc.get("image_prompt", ""):
                desc = characters[name]
                if not desc:
                    characters[name] = sc["image_prompt"]
    return {"characters": characters, "scenes": scenes}


def _mock_storyboard(script: str, style: str, scene_count: int) -> dict:
    """mock 模式：按段落切分剧本，不调用任何 API。"""
    paras = [p.strip() for p in re.split(r"[\n。！？]+", script) if p.strip()]
    step = max(1, len(paras) // scene_count)
    scenes = []
    for i in range(scene_count):
        seg = "。".join(paras[i * step:(i + 1) * step]) or f"第{i+1}幕"
        scenes.append({
            "title": f"第{i + 1}幕",
            "narration": seg[:120],
            "dialogue": "",
            "image_prompt": f"{style}，漫画分镜第{i + 1}格：{seg[:40]}",
            "characters": [],
        })
    return {"characters": {}, "scenes": scenes}


# ---------------------------------------------------------------- 生图

def gen_image(prompt: str, project_dir: str, style: str = "") -> str:
    """生成一张分镜图片，返回文件名。"""
    cfg = load_config()["image"]
    filename = "img_%s.png" % uuid.uuid4().hex[:10]
    filepath = os.path.join(project_dir, filename)

    if cfg.get("mock"):
        # mock：用 ffmpeg 生成一张带提示词的纯色占位图
        import subprocess
        ffmpeg = _ffmpeg_bin()
        safe = (prompt or style)[:28].replace(":", " ").replace("'", "")
        subprocess.run(
            [ffmpeg, "-y", "-f", "lavfi",
             "-i", "color=c=0x2c3e50:s=1280x720",
             "-vf", f"drawtext=text='{safe}':fontcolor=white:fontsize=48:x=(w-tw)/2:y=(h-th)/2:fontfile='C\\:/Windows/Fonts/msyh.ttc'",
             "-frames:v", "1", filepath],
            check=True, capture_output=True)
        return filename

    full_prompt = f"{prompt}，{style}" if style else prompt
    resp = requests.post(
        cfg["base_url"].rstrip("/") + "/images/generations",
        headers={"Authorization": "Bearer " + cfg["api_key"]},
        json={"model": cfg["model"], "prompt": full_prompt,
              "size": cfg.get("size", "1344x768")},
        timeout=180,
    )
    resp.raise_for_status()
    data = resp.json()["data"][0]
    if "b64_json" in data and data["b64_json"]:
        import base64
        with open(filepath, "wb") as f:
            f.write(base64.b64decode(data["b64_json"]))
    elif "url" in data:
        img = requests.get(data["url"], timeout=120)
        img.raise_for_status()
        with open(filepath, "wb") as f:
            f.write(img.content)
    return filename


# ---------------------------------------------------------------- TTS 配音

def gen_tts(text: str, voice: str, project_dir: str) -> str:
    """生成配音，返回音频文件名。edge-tts 免费，失败时回退为静音。"""
    filename = "tts_%s.mp3" % uuid.uuid4().hex[:10]
    filepath = os.path.join(project_dir, filename)

    try:
        import asyncio
        import edge_tts
        asyncio.run(edge_tts.Communicate(text, voice).save(filepath))
    except Exception:
        # 网络不通等异常 → 生成 3 秒静音兜底
        import subprocess
        subprocess.run(
            [_ffmpeg_bin(), "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
             "-t", "3", "-c:a", "libmp3lame", filepath],
            check=True, capture_output=True)
    return filename


# ---------------------------------------------------------------- ffmpeg 工具

def _ffmpeg_bin() -> str:
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def audio_duration(filepath: str) -> float:
    """用 ffmpeg stderr 解析音频时长（秒）。"""
    import subprocess
    r = subprocess.run([_ffmpeg_bin(), "-i", filepath],
                       capture_output=True, text=True)
    m = re.search(r"Duration: (\d+):(\d+):(\d+\.\d+)", r.stderr)
    if not m:
        return 3.0
    h, mn, s = m.groups()
    return int(h) * 3600 + int(mn) * 60 + float(s)
