# -*- coding: utf-8 -*-
"""AI Provider 适配层：LLM 分镜 / 生图 / TTS

默认对接火山方舟（豆包 Seedream + 豆包 Seed），一个 API Key 同时搞定分镜文案与画面。
若未填写 Key，则自动降级为 mock 模式（占位图 + 段落切分），保证流程始终可跑通。
"""

import base64
import json
import os
import re
import uuid

import requests

ROOT = os.path.dirname(os.path.abspath(__file__))

ARK_BASE = "https://ark.cn-beijing.volces.com/api/v3"


# ---------------------------------------------------------------- 配置

def load_config() -> dict:
    """加载 config.json（不存在时回退到 config.example.json）。环境变量 ARK_API_KEY 优先。"""
    path = os.path.join(ROOT, "config.json")
    fallback = os.path.join(ROOT, "config.example.json")
    src = path if os.path.exists(path) else fallback
    with open(src, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    env_key = os.environ.get("ARK_API_KEY", "").strip()
    for section in ("llm", "image"):
        cfg.setdefault(section, {})
        cfg[section].setdefault("base_url", ARK_BASE)
        cfg[section].setdefault("api_key", "")
        if env_key:
            cfg[section]["api_key"] = env_key
    cfg.setdefault("tts", {"voice": "zh-CN-XiaoxiaoNeural"})
    return cfg


def _has_key(cfg: dict) -> bool:
    """判断某个 provider 是否已具备真实调用条件。"""
    if cfg.get("mock"):
        return False
    key = (cfg.get("api_key") or "").strip()
    return bool(key) and "你的" not in key and "your" not in key.lower()


def config_status() -> dict:
    """返回给前端的配置状态。"""
    cfg = load_config()
    llm, img = cfg["llm"], cfg["image"]
    return {
        "llm": {"ready": _has_key(llm), "model": llm.get("model", "")},
        "image": {"ready": _has_key(img), "model": img.get("model", "")},
    }


# ---------------------------------------------------------------- 画风预设

STYLE_PRESETS = {
    "日系动漫风": "日系动漫风格，赛璐璐上色，清晰线条，明快色彩",
    "国风水墨": "中国风水墨画风格，留白意境，淡雅笔墨",
    "美式漫画风": "美式漫画风格，粗线条勾勒，高对比阴影，分格张力",
    "赛博朋克": "赛博朋克风格，霓虹夜景，雨夜都市，高科技低生活",
    "治愈手绘风": "治愈系手绘风格，柔和笔触，暖色调，温馨氛围",
    "仙侠玄幻·唯美写实": (
        "中国仙侠玄幻风格，唯美写实CG质感，仙气缭绕，冰蓝色调梦幻光效，"
        "飘逸长发与轻纱衣袂，粒子光斑与辉光点缀，电影级打光，超高细节，电影级构图"
    ),
}


def style_prompt(style: str) -> str:
    """把画风名称映射为完整提示词（未知画风原样返回）。"""
    return STYLE_PRESETS.get(style, style)


# ---------------------------------------------------------------- LLM：剧本 → 分镜

STORYBOARD_PROMPT = """你是一名专业漫剧分镜师。请把下面的故事/剧本改编成 {scene_count} 个分镜。

要求：
1. 主要角色的外貌特征必须统一（发型、发色、服装、气质），每格画面都要能看出是同一个人；
2. 每个分镜包含：title（分镜标题）、narration（旁白，1-2句，口语化）、dialogue（角色台词，可为空字符串）、
   image_prompt（画面描述，中文，60字以内，写清：人物外貌+动作表情+场景+镜头景别+光线氛围）、
   characters（该分镜出场角色名数组）；
3. 只输出 JSON 数组，不要输出任何解释文字。格式：
[{{"title":"...","narration":"...","dialogue":"...","image_prompt":"...","characters":["..."]}}]

画风要求：{style}

故事/剧本：
{script}
"""


def _strip_json(text):
    """从 LLM 输出中提取 JSON 数组（容错 markdown 代码块、前后缀文字）。"""
    if isinstance(text, list):  # 多模态返回结构
        text = "".join(p.get("text", "") for p in text if isinstance(p, dict))
    text = re.sub(r"```(?:json)?", "", str(text)).strip().strip("`")
    start, end = text.find("["), text.rfind("]")
    if start != -1 and end != -1:
        return json.loads(text[start:end + 1])
    raise ValueError("模型返回内容中没有找到 JSON 数组，请重试或换用更强的模型")


def gen_storyboard(script: str, style: str, scene_count: int) -> dict:
    """调用 LLM 生成分镜。返回 {"characters": ..., "scenes": [...], "mock": bool}"""
    cfg = load_config()["llm"]
    if not _has_key(cfg):
        return {**_mock_storyboard(script, style, scene_count), "mock": True}

    prompt = STORYBOARD_PROMPT.format(
        scene_count=scene_count, style=style_prompt(style), script=script[:6000]
    )
    body = {
        "model": cfg["model"],
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.8,
        "thinking": {"type": "disabled"},
    }
    content = _ark_chat(cfg, body)

    scenes = _strip_json(content)
    # 规范化字段
    for i, sc in enumerate(scenes, 1):
        sc.setdefault("title", f"第{i}幕")
        sc.setdefault("narration", "")
        sc.setdefault("dialogue", "")
        sc.setdefault("image_prompt", "")
        sc.setdefault("characters", [])
        sc["image"] = ""
        sc["tts"] = ""
    return {"characters": {}, "scenes": scenes, "mock": False}


def _ark_chat(cfg: dict, body: dict) -> str:
    """调用 chat/completions，thinking 参数不被支持时自动降级重试。"""
    url = cfg["base_url"].rstrip("/") + "/chat/completions"
    headers = {"Authorization": "Bearer " + cfg["api_key"]}
    for attempt_body in (body, {k: v for k, v in body.items() if k != "thinking"}):
        resp = requests.post(url, headers=headers, json=attempt_body, timeout=180)
        if resp.status_code == 400 and "thinking" in resp.text and attempt_body is body:
            continue
        if resp.status_code != 200:
            raise RuntimeError(f"分镜生成失败（HTTP {resp.status_code}）：{_short(resp.text)}")
        data = resp.json()
        return data["choices"][0]["message"]["content"]
    raise RuntimeError("分镜生成失败：模型参数不被支持")


def _mock_storyboard(script: str, style: str, scene_count: int) -> dict:
    """mock 模式：按段落切分剧本。"""
    paras = [p.strip() for p in re.split(r"[\n。！？]+", script) if p.strip()]
    step = max(1, len(paras) // scene_count)
    scenes = []
    for i in range(scene_count):
        seg = "。".join(paras[i * step:(i + 1) * step]) or f"第{i + 1}幕"
        scenes.append({
            "title": f"第{i + 1}幕", "narration": seg[:120], "dialogue": "",
            "image_prompt": f"{style}，漫画分镜第{i + 1}格：{seg[:40]}",
            "characters": [], "image": "", "tts": "",
        })
    return {"characters": {}, "scenes": scenes}


# ---------------------------------------------------------------- 生图（豆包 Seedream）

def gen_image(prompt: str, project_dir: str, style: str = "", aspect: str = "9:16",
              ref_image: str = "") -> tuple:
    """生成一张分镜图片，返回 (文件名, 是否 mock)。

    ref_image: 参考图文件名（同一 project 目录下），用于保持角色形象一致。
    """
    cfg = load_config()["image"]
    filename = "img_%s.jpeg" % uuid.uuid4().hex[:10]
    filepath = os.path.join(project_dir, filename)
    full_prompt = f"{prompt}，{style_prompt(style)}" if style else prompt

    if not _has_key(cfg):
        _mock_image(full_prompt, filepath, aspect)
        return filename.replace(".jpeg", ".png"), True

    # 尺寸：竖屏 / 横屏，取配置值，失败时自动降级到官方预设比例
    if aspect == "9:16":
        sizes = [cfg.get("size_portrait", "1152x2048"), "9:16", "2K"]
    else:
        sizes = [cfg.get("size_landscape", "2048x1152"), "16:9", "2K"]

    payload_base = {
        "model": cfg["model"],
        "prompt": full_prompt[:1000],
        "watermark": False,
        "response_format": "url",
        "output_format": "jpeg",
    }
    if ref_image:
        ref_path = os.path.join(project_dir, ref_image)
        if os.path.exists(ref_path):
            payload_base["image"] = [_data_uri(ref_path)]
            payload_base["prompt"] = "保持参考图中人物的五官、发型、服饰与画风完全一致。" + full_prompt[:1000]

    last_err = ""
    for size in sizes:
        payload = dict(payload_base, size=size)
        for attempt in (payload, {k: v for k, v in payload.items() if k != "image"}):
            resp = requests.post(
                cfg["base_url"].rstrip("/") + "/images/generations",
                headers={"Authorization": "Bearer " + cfg["api_key"]},
                json=attempt, timeout=300,
            )
            if resp.status_code == 200:
                data = resp.json()["data"][0]
                _save_image(data, filepath)
                return filename, False
            last_err = f"HTTP {resp.status_code}：{_short(resp.text)}"
            if attempt is payload:  # 参考图模式失败 → 退回纯文生图
                continue
            break  # 该尺寸不可用，换下一个尺寸
    raise RuntimeError("生图失败：" + last_err)


def _save_image(item: dict, filepath: str):
    if item.get("b64_json"):
        with open(filepath, "wb") as f:
            f.write(base64.b64decode(item["b64_json"]))
    elif item.get("url"):
        img = requests.get(item["url"], timeout=180)
        img.raise_for_status()
        with open(filepath, "wb") as f:
            f.write(img.content)
    else:
        raise RuntimeError("生图返回里没有图片数据")


def _data_uri(path: str) -> str:
    ext = os.path.splitext(path)[1].lower().lstrip(".") or "jpeg"
    mime = "jpeg" if ext in ("jpg", "jpeg") else ext
    with open(path, "rb") as f:
        return f"data:image/{mime};base64," + base64.b64encode(f.read()).decode()


def _mock_image(prompt: str, filepath: str, aspect: str):
    """mock：ffmpeg 生成占位图（带提示词文字）。"""
    import subprocess
    size = "768x1344" if aspect == "9:16" else "1344x768"
    safe = prompt[:28].replace(":", " ").replace("'", "").replace("\\", " ")
    font = "C\\:/Windows/Fonts/msyh.ttc"
    subprocess.run(
        [_ffmpeg_bin(), "-y", "-f", "lavfi", "-i", "color=c=0x2c3e50:s=" + size,
         "-vf", f"drawtext=text='{safe}':fontcolor=white:fontsize=44:"
                f"x=(w-tw)/2:y=(h-th)/2:fontfile='{font}'",
         "-frames:v", "1", filepath.replace(".jpeg", ".png")],
        check=True, capture_output=True)


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
        import subprocess
        subprocess.run(
            [_ffmpeg_bin(), "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
             "-t", "3", "-c:a", "libmp3lame", filepath],
            check=True, capture_output=True)
    return filename


# ---------------------------------------------------------------- 工具

def _short(text: str, n: int = 300) -> str:
    return (text or "").replace("\n", " ")[:n]


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
