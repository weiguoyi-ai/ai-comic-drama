# -*- coding: utf-8 -*-
"""AI Provider 适配层：分镜 / 生图 / 配音，支持「云端免费」与「本地离线」自动切换。

运行模式（config.json 的 "mode"）：
  auto  —— 有云端 Key 就用云端，没 Key 自动落本地，本地也没模型才用占位图（默认）
  local —— 强制本地模型，完全断网可用
  cloud —— 强制云端（火山方舟）

三条链路：
  分镜：火山方舟豆包 Seed  /  本地 Qwen2.5-1.5B  /  规则切分占位
  生图：火山方舟 Seedream  /  本地 SD1.5+LCM    /  纯色占位图
  配音：Piper 本地离线      /  edge-tts 免费在线
"""

import base64
import json
import os
import re
import uuid

import requests

import local_image
import local_llm
import local_tts

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

    cfg.setdefault("mode", "auto")
    env_key = os.environ.get("ARK_API_KEY", "").strip()
    for section in ("llm", "image"):
        cfg.setdefault(section, {})
        cfg[section].setdefault("base_url", ARK_BASE)
        cfg[section].setdefault("api_key", "")
        if env_key:
            cfg[section]["api_key"] = env_key
    cfg.setdefault("tts", {"engine": "auto", "voice": "zh-CN-XiaoxiaoNeural"})
    cfg.setdefault("local", {"steps": 6, "guidance": 1.6})
    return cfg


def _has_key(cfg: dict) -> bool:
    """云端 Key 是否可用。"""
    if cfg.get("mock"):
        return False
    key = (cfg.get("api_key") or "").strip()
    return bool(key) and "你的" not in key and "your" not in key.lower()


def _pick_backend(section_cfg: dict, local_ready: bool, mode: str) -> str:
    """返回 cloud / local / placeholder。"""
    cloud_ok = _has_key(section_cfg)
    if mode == "local":
        return "local" if local_ready else "placeholder"
    if mode == "cloud":
        return "cloud" if cloud_ok else ("local" if local_ready else "placeholder")
    return "cloud" if cloud_ok else ("local" if local_ready else "placeholder")


def config_status() -> dict:
    """返回给前端的运行模式与各环节后端状态。"""
    cfg = load_config()
    mode = cfg.get("mode", "auto")
    img_local, llm_local, tts_local = local_image.is_ready(), local_llm.is_ready(), local_tts.is_ready()
    return {
        "mode": mode,
        "llm": {"backend": _pick_backend(cfg["llm"], llm_local, mode),
                "model": cfg["llm"].get("model", ""),
                "local_model": "Qwen2.5-1.5B"},
        "image": {"backend": _pick_backend(cfg["image"], img_local, mode),
                  "model": cfg["image"].get("model", ""),
                  "local_model": "SD1.5 DreamShaper8 + LCM"},
        "tts": {"backend": "local" if tts_local else "cloud",
                "engine": "Piper（离线）" if tts_local else "edge-tts（在线免费）"},
        "local_ready": {"image": img_local, "llm": llm_local, "tts": tts_local},
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


# 本地 SD1.5 只认英文，画风需映射为英文提示词
STYLE_PRESETS_EN = {
    "日系动漫风": "anime style, cel shading, clean lineart, vibrant colors, japanese animation",
    "国风水墨": "chinese ink painting style, minimalist, elegant brush strokes",
    "美式漫画风": "american comic style, bold outlines, high contrast shading",
    "赛博朋克": "cyberpunk style, neon night city, rain, high-tech low-life",
    "治愈手绘风": "healing hand-drawn style, soft brush, warm colors, cozy",
    "仙侠玄幻·唯美写实": ("chinese xianxia fantasy style, ethereal, ice blue magical glow, "
                      "flowing hair and silk robes, particles of light, cinematic lighting, "
                      "highly detailed, beautiful anime illustration"),
}


def style_prompt_en(style: str) -> str:
    return STYLE_PRESETS_EN.get(style, style)


# ---------------------------------------------------------------- 分镜：剧本 → 分镜

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

LOCAL_STORYBOARD_PROMPT = """You are a comic storyboard artist. Split the story below into {scene_count} shots.

Output ONLY a JSON array in this exact format:
[{{"title":"shot 1","narration":"one sentence narration in Chinese","dialogue":"character line in Chinese or empty","image_prompt":"ENGLISH scene description for an image model: subject appearance + action + environment + lighting, under 35 words","characters":["name"]}}]

Rules: keep the same character appearance across shots; image_prompt MUST be in English; narration/dialogue in Chinese.

Style: {style_en}

Story:
{script}

JSON array:
"""


def _strip_json(text):
    """从模型输出中提取 JSON 数组（容错 markdown 代码块、前后缀文字）。"""
    if isinstance(text, list):
        text = "".join(p.get("text", "") for p in text if isinstance(p, dict))
    text = re.sub(r"```(?:json)?", "", str(text)).strip().strip("`")
    start, end = text.find("["), text.rfind("]")
    if start != -1 and end != -1:
        return json.loads(text[start:end + 1])
    raise ValueError("模型返回内容中没有找到 JSON 数组")


def _normalize(scenes, count):
    out = []
    for i, sc in enumerate(scenes[:count] if count else scenes, 1):
        if not isinstance(sc, dict):
            continue
        out.append({
            "title": str(sc.get("title") or f"第{i}幕"),
            "narration": str(sc.get("narration") or ""),
            "dialogue": str(sc.get("dialogue") or ""),
            "image_prompt": str(sc.get("image_prompt") or sc.get("narration") or ""),
            "characters": sc.get("characters") or [],
            "image": "", "tts": "",
        })
    return out


def gen_storyboard(script: str, style: str, scene_count: int) -> dict:
    """生成分镜。返回 {"scenes": [...], "backend": "cloud|local|placeholder"}"""
    cfg = load_config()
    mode = cfg.get("mode", "auto")
    backend = _pick_backend(cfg["llm"], local_llm.is_ready(), mode)

    if backend == "cloud":
        try:
            scenes = _storyboard_cloud(cfg["llm"], script, style, scene_count)
            return {"scenes": _normalize(scenes, scene_count), "backend": "cloud"}
        except Exception as e:
            if mode == "cloud":
                raise
            backend = "local" if local_llm.is_ready() else "placeholder"
            if backend == "local":
                scenes = _storyboard_local(script, style, scene_count)
                return {"scenes": scenes, "backend": "local", "note": str(e)[:120]}
            raise

    if backend == "local":
        return {"scenes": _storyboard_local(script, style, scene_count), "backend": "local"}

    return {"scenes": _mock_storyboard(script, style, scene_count), "backend": "placeholder"}


def _storyboard_cloud(cfg, script, style, scene_count):
    prompt = STORYBOARD_PROMPT.format(
        scene_count=scene_count, style=style_prompt(style), script=script[:6000])
    body = {
        "model": cfg["model"],
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.8,
        "thinking": {"type": "disabled"},
    }
    return _strip_json(_ark_chat(cfg, body))


def _storyboard_local(script, style, scene_count):
    prompt = LOCAL_STORYBOARD_PROMPT.format(
        scene_count=scene_count, style_en=style_prompt_en(style), script=script[:1200])
    for _ in range(2):
        try:
            raw = local_llm.chat(prompt, max_new_tokens=1100)
            return _normalize(_strip_json(raw), scene_count)
        except Exception:
            continue
    return _mock_storyboard(script, style, scene_count)


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
        return resp.json()["choices"][0]["message"]["content"]
    raise RuntimeError("分镜生成失败：模型参数不被支持")


def _mock_storyboard(script: str, style: str, scene_count: int):
    """占位：按标点切分剧本。"""
    paras = [p.strip() for p in re.split(r"[\n。！？]+", script) if p.strip()]
    step = max(1, len(paras) // scene_count) if paras else 1
    scenes = []
    for i in range(scene_count):
        seg = "。".join(paras[i * step:(i + 1) * step]) or f"第{i + 1}幕"
        scenes.append({
            "title": f"第{i + 1}幕", "narration": seg[:120], "dialogue": "",
            "image_prompt": f"{seg[:60]}", "characters": [], "image": "", "tts": "",
        })
    return scenes


# ---------------------------------------------------------------- 生图

def gen_image(prompt: str, project_dir: str, style: str = "", aspect: str = "9:16",
              ref_image: str = "") -> tuple:
    """生成一张分镜图片，返回 (文件名, backend)。"""
    cfg = load_config()
    mode = cfg.get("mode", "auto")
    backend = _pick_backend(cfg["image"], local_image.is_ready(), mode)
    full_prompt = f"{prompt}，{style_prompt(style)}" if style else prompt

    if backend == "cloud":
        try:
            return _image_cloud(cfg["image"], full_prompt, project_dir, aspect, ref_image), "cloud"
        except Exception:
            if mode == "cloud" or not local_image.is_ready():
                raise
            backend = "local"

    if backend == "local":
        return _image_local(cfg.get("local", {}), full_prompt, project_dir,
                            aspect, style), "local"

    filename = "img_%s.png" % uuid.uuid4().hex[:10]
    _mock_image(full_prompt, os.path.join(project_dir, filename), aspect)
    return filename, "placeholder"


def _image_cloud(cfg, full_prompt, project_dir, aspect, ref_image):
    filename = "img_%s.jpeg" % uuid.uuid4().hex[:10]
    filepath = os.path.join(project_dir, filename)

    if aspect == "9:16":
        sizes = [cfg.get("size_portrait", "1152x2048"), "9:16", "2K"]
    else:
        sizes = [cfg.get("size_landscape", "2048x1152"), "16:9", "2K"]

    payload_base = {
        "model": cfg["model"], "prompt": full_prompt[:1000],
        "watermark": False, "response_format": "url", "output_format": "jpeg",
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
                json=attempt, timeout=300)
            if resp.status_code == 200:
                _save_image(resp.json()["data"][0], filepath)
                return filename
            last_err = f"HTTP {resp.status_code}：{_short(resp.text)}"
            if attempt is payload:
                continue
            break
    raise RuntimeError("云端生图失败：" + last_err)


def _image_local(local_cfg, full_prompt, project_dir, aspect, style=""):
    filename = "img_%s.jpeg" % uuid.uuid4().hex[:10]
    filepath = os.path.join(project_dir, filename)
    # 本地 SD1.5 只认英文：提示词不含英文时，追加英文画风关键词兜底
    if not re.search(r"[A-Za-z]", full_prompt):
        full_prompt = (full_prompt + ", " + style_prompt_en(style)).strip(", ")
    local_image.generate(
        full_prompt, filepath, aspect=aspect,
        steps=int(local_cfg.get("steps", 4)),
        guidance=float(local_cfg.get("guidance", 1.6)),
        seed=int(local_cfg.get("seed", -1)),
    )
    return filename


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
    """占位图：ffmpeg 纯色 + 提示词文字。"""
    import subprocess
    size = "768x1344" if aspect == "9:16" else "1344x768"
    safe = prompt[:28].replace(":", " ").replace("'", "").replace("\\", " ")
    font = "C\\:/Windows/Fonts/msyh.ttc"
    subprocess.run(
        [_ffmpeg_bin(), "-y", "-f", "lavfi", "-i", "color=c=0x2c3e50:s=" + size,
         "-vf", f"drawtext=text='{safe}':fontcolor=white:fontsize=44:"
                f"x=(w-tw)/2:y=(h-th)/2:fontfile='{font}'",
         "-frames:v", "1", filepath],
        check=True, capture_output=True)


# ---------------------------------------------------------------- 配音

def gen_tts(text: str, voice: str, project_dir: str) -> tuple:
    """生成配音，返回 (音频文件名, engine)。优先本地 Piper，缺失则 edge-tts。"""
    cfg = load_config()
    engine = cfg.get("tts", {}).get("engine", "auto")
    use_local = local_tts.is_ready() and engine in ("auto", "piper")
    if use_local:
        try:
            wav = local_tts.synth(text, project_dir)
            return local_tts.wav_to_mp3(os.path.join(project_dir, wav)), "piper"
        except Exception:
            if engine == "piper":
                raise
    filename = "tts_%s.mp3" % uuid.uuid4().hex[:10]
    filepath = os.path.join(project_dir, filename)
    try:
        import asyncio
        import edge_tts
        asyncio.run(edge_tts.Communicate(text, voice).save(filepath))
        return filename, "edge-tts"
    except Exception:
        import subprocess
        subprocess.run(
            [_ffmpeg_bin(), "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
             "-t", "3", "-c:a", "libmp3lame", filepath],
            check=True, capture_output=True)
        return filename, "silence"


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
