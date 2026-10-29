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

# 可选中文音色（edge-tts）。本地 SAPI 只有一个中文音色，靠语速区分角色
VOICES = [
    {"id": "zh-CN-XiaoxiaoNeural", "label": "晓晓 · 温柔女声", "gender": "女"},
    {"id": "zh-CN-XiaoyiNeural", "label": "晓伊 · 少女音", "gender": "女"},
    {"id": "zh-CN-YunxiNeural", "label": "云希 · 少年音", "gender": "男"},
    {"id": "zh-CN-YunxiaNeural", "label": "云夏 · 稚气男声", "gender": "男"},
    {"id": "zh-CN-YunjianNeural", "label": "云健 · 沉稳男声", "gender": "男"},
    {"id": "zh-CN-liaoning-XiaobeiNeural", "label": "晓北 · 东北女声", "gender": "女"},
]

DEFAULT_VOICE_MAP = {
    "旁白": {"voice": "zh-CN-XiaoxiaoNeural", "rate": -4},
    "女主": {"voice": "zh-CN-XiaoyiNeural", "rate": 0},
    "男主": {"voice": "zh-CN-YunxiNeural", "rate": 0},
    "老人": {"voice": "zh-CN-YunjianNeural", "rate": -10},
    "小孩": {"voice": "zh-CN-YunxiaNeural", "rate": 6},
}

# 未知角色名的音色池（哈希稳定分配，保证同一角色前后一致）
CHARACTER_VOICES = [
    "zh-CN-XiaoyiNeural",
    "zh-CN-YunxiNeural",
    "zh-CN-YunxiaNeural",
    "zh-CN-YunjianNeural",
    "zh-CN-liaoning-XiaobeiNeural",
]


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
    cfg["tts"].setdefault("voice", "zh-CN-XiaoxiaoNeural")
    cfg["tts"].setdefault("voice_map", dict(DEFAULT_VOICE_MAP))
    cfg.setdefault("bgm", {"enabled": True, "path": "", "volume": 0.12})
    cfg.setdefault("local", {"steps": 4, "guidance": 1.6, "quality": "normal"})
    return cfg


def resolve_voice(speaker: str, cfg: dict = None, project_dir: str = "") -> dict:
    """按角色名解析音色与语速。

    优先级：voice_map 完全匹配 → 模糊包含 →
    项目内的角色-音色分配表（新角色自动取一个尚未占用的音色并记住）→ 默认音色。
    这样同一角色在各幕音色一致，不同角色尽量不撞车。
    """
    cfg = cfg or load_config()
    tts = cfg.get("tts", {})
    voice_map = tts.get("voice_map") or {}
    default = {"voice": tts.get("voice") or "zh-CN-XiaoxiaoNeural", "rate": 0}
    speaker = (speaker or "").strip()
    if not speaker:
        return default
    if speaker in voice_map:
        return _norm_voice(voice_map[speaker], default)
    for key, val in voice_map.items():
        if key and (key in speaker or speaker in key):
            return _norm_voice(val, default)
    if project_dir:
        assigned = _assign_character_voice(speaker, project_dir, default["voice"])
        if assigned:
            return {"voice": assigned, "rate": 0}
    return default


def _assign_character_voice(speaker: str, project_dir: str, narrator_voice: str) -> str:
    """在项目目录内维护「角色 → 音色」分配表，新角色取未被占用的音色。"""
    path = os.path.join(project_dir, "_voices.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            table = json.load(f)
    except Exception:
        table = {}
    if speaker in table:
        return table[speaker]

    pool = [v for v in CHARACTER_VOICES if v != narrator_voice]
    used = set(table.values())
    free = [v for v in pool if v not in used]
    # 音色用完之后，按最少使用次数挑一个
    if not free:
        counts = {v: 0 for v in pool}
        for v in table.values():
            counts[v] = counts.get(v, 0) + 1
        free = [min(pool, key=lambda v: counts.get(v, 0))]
    table[speaker] = free[0]
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(table, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    return table[speaker]


def _norm_voice(val, default):
    if isinstance(val, str):
        return {"voice": val, "rate": 0}
    if isinstance(val, dict):
        return {"voice": val.get("voice") or default["voice"],
                "rate": int(val.get("rate", 0) or 0)}
    return dict(default)


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
                "engine": "Piper（离线）" if tts_local else "edge-tts（在线免费）",
                "voices": VOICES,
                "voice_map": {k: v for k, v in (cfg["tts"].get("voice_map") or {}).items()}},
        "bgm": {"enabled": bool(cfg.get("bgm", {}).get("enabled", True)),
                "tracks": _bgm_tracks()},
        "local_ready": {"image": img_local, "llm": llm_local, "tts": tts_local},
    }


def _bgm_tracks() -> list:
    """可用的背景音乐文件（assets/bgm 目录下的 mp3/wav/m4a）。"""
    d = os.path.join(ROOT, "assets", "bgm")
    if not os.path.isdir(d):
        return []
    return sorted(f for f in os.listdir(d)
                  if f.lower().endswith((".mp3", ".wav", ".m4a", ".ogg")))


def pick_bgm(path: str = "") -> str:
    """确定背景音乐文件：指定则用之，否则从 assets/bgm 随机选一首；无则返回空串。"""
    cfg = load_config().get("bgm", {})
    if not cfg.get("enabled", True):
        return ""
    if path:
        p = path if os.path.isabs(path) else os.path.join(ROOT, path)
        return p if os.path.exists(p) else ""
    tracks = _bgm_tracks()
    if not tracks:
        return ""
    import random
    return os.path.join(ROOT, "assets", "bgm", random.choice(tracks))


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
   speaker（说这句台词的角色名；没有台词时为空字符串）、
   image_prompt（画面描述，中文，60字以内，写清：人物外貌+动作表情+场景+镜头景别+光线氛围）、
   characters（该分镜出场角色名数组）；
3. 角色名要简短固定（如"林晚""老张""旁白"），同一角色在不同分镜必须用完全相同的名字，便于配音分配；
4. 只输出 JSON 数组，不要输出任何解释文字。格式：
[{{"title":"...","narration":"...","dialogue":"...","speaker":"...","image_prompt":"...","characters":["..."]}}]

画风要求：{style}

故事/剧本：
{script}
"""

LOCAL_STORYBOARD_PROMPT = """你是漫剧分镜师，把下面的故事拆成 {scene_count} 个分镜。

严格规则（必须遵守）：
1. 只输出 JSON 数组，不要任何解释、不要 markdown 代码块；
2. 每一项都必须是完整对象，四个文字字段都不许留空：
   - title：分镜小标题（6字内，各不相同）
   - narration：旁白，中文，15~30字，必须有内容，用来讲清楚剧情
   - dialogue：角色台词，中文，10~25字，写角色真正说的话；若这一幕是纯场景，写"……"之外的简短心理独白
   - speaker：说这句台词的角色名（如 林晚 / 沈书白 / 旁白），与 characters 中的名字完全一致
   - image_prompt：英文画面描述，写清人物外貌+动作+场景+光线，不超过 35 个单词
   - characters：出场角色名数组，同一角色在各分镜中用完全相同的名字
3. 画风：{style_en}

输出格式示例：
[{{"title":"雪巅相候","narration":"三百年来她守着雪山，只为等他归来。","dialogue":"你终于来了。","speaker":"林晚","image_prompt":"a white-haired woman in ice-blue silk robes standing on a snowy peak, ethereal glow, cinematic lighting, anime style","characters":["林晚"]}}]

故事：
{script}

JSON 数组：
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
        title = str(sc.get("title") or f"第{i}幕")
        narration = str(sc.get("narration") or "").strip()
        dialogue = str(sc.get("dialogue") or "").strip()
        speaker = str(sc.get("speaker") or "").strip()
        # 小模型常把旁白留空：用台词或标题兜底，保证字幕和配音有内容
        if not narration:
            narration = dialogue or title
        if not dialogue:
            speaker = ""
        out.append({
            "title": title,
            "narration": narration,
            "dialogue": dialogue,
            "speaker": speaker,
            "image_prompt": str(sc.get("image_prompt") or narration),
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
        preset=str(local_cfg.get("quality", "normal")),
        threads=int(local_cfg.get("threads", 0)),
        low_mem=bool(local_cfg.get("low_mem", False)),
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

# 本地只有一个中文声线，用固定语速偏移模拟不同角色的声音差异
LOCAL_VOICE_RATE = {
    "zh-CN-XiaoxiaoNeural": -3,
    "zh-CN-XiaoyiNeural": 5,
    "zh-CN-YunxiNeural": 0,
    "zh-CN-YunxiaNeural": 8,
    "zh-CN-YunjianNeural": -8,
    "zh-CN-liaoning-XiaobeiNeural": 3,
}


def gen_tts(text: str, voice: str, project_dir: str, rate: int = 0) -> tuple:
    """生成配音，返回 (音频文件名, engine)。优先本地离线，缺失则 edge-tts。

    rate：语速百分比（-50~+50），用于区分角色；本地 SAPI 会折算到 -10~10 档。
    """
    cfg = load_config()
    engine = cfg.get("tts", {}).get("engine", "auto")
    use_local = local_tts.is_ready() and engine in ("auto", "piper")
    if use_local:
        try:
            local_rate = rate + LOCAL_VOICE_RATE.get(voice, 0)
            wav = local_tts.synth(text, project_dir, rate=local_rate)
            wav_path = os.path.join(project_dir, wav)
            if _wav_duration_ok(wav_path):
                return local_tts.wav_to_mp3(wav_path), "local"
            # Piper 音素化失败会产出空音频（0 帧），视为失败并回退
            os.remove(wav_path)
        except Exception:
            if engine == "piper":
                raise
    filename = "tts_%s.mp3" % uuid.uuid4().hex[:10]
    filepath = os.path.join(project_dir, filename)
    try:
        import asyncio
        import edge_tts
        rate_str = "%+d%%" % int(rate) if rate else "+0%"
        asyncio.run(edge_tts.Communicate(text, voice, rate=rate_str).save(filepath))
        return filename, "edge-tts"
    except Exception:
        import subprocess
        subprocess.run(
            [_ffmpeg_bin(), "-y", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono",
             "-t", "3", "-c:a", "libmp3lame", filepath],
            check=True, capture_output=True)
        return filename, "silence"


# ---------------------------------------------------------------- 工具

def _wav_duration_ok(path: str, min_sec: float = 0.5) -> bool:
    """检查 WAV 是否包含有效语音（防止 Piper 音素化失败产出空音频）。"""
    try:
        import wave, contextlib
        with contextlib.closing(wave.open(path)) as w:
            return w.getnframes() / max(1, w.getframerate()) >= min_sec
    except Exception:
        return False


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
