# -*- coding: utf-8 -*-
"""本地模式端到端自测：分镜 → 本地生图 → 配音 → 合成视频。

用法: python test_local_e2e.py [剧本] [幕数]
"""

import json
import sys
import time

import requests

BASE = "http://127.0.0.1:8000"


def post(url, body, timeout=1800):
    r = requests.post(BASE + url, json=body, timeout=timeout)
    j = r.json()
    if r.status_code != 200:
        raise RuntimeError(j.get("error", r.text))
    return j


def main():
    script = sys.argv[1] if len(sys.argv) > 1 else (
        "深夜的城市，外卖员小李接到一个奇怪订单，地址是一栋废弃大楼。"
        "他鼓起勇气爬上顶楼，发现了一个守护城市的机器人。")
    count = int(sys.argv[2]) if len(sys.argv) > 2 else 2

    print("[1/4] 生成分镜（本地 Qwen，约 1-2 分钟）…")
    t = time.time()
    sb = post("/api/storyboard", {"script": script, "style": "仙侠玄幻·唯美写实",
                                  "scene_count": count})
    print("      backend=%s, %.0f 秒, %d 幕" % (sb["backend"], time.time() - t, len(sb["scenes"])))
    pid = sb["project_id"]
    scenes = sb["scenes"]

    for i, sc in enumerate(scenes, 1):
        print(f"[2/4] 本地生图 {i}/{len(scenes)}（每张约 3-6 分钟）…")
        t = time.time()
        img = post("/api/image", {"project_id": pid, "prompt": sc["image_prompt"],
                                  "style": "仙侠玄幻·唯美写实", "aspect": "9:16"})
        sc["image"] = img["image"]
        print("      backend=%s, %.0f 秒" % (img["backend"], time.time() - t))

    for i, sc in enumerate(scenes, 1):
        text = (sc["narration"] + " " + sc["dialogue"]).strip() or sc["title"]
        tts = post("/api/tts", {"project_id": pid, "text": text})
        sc["tts"] = tts["tts"]
        print(f"[3/4] 配音 {i}/{len(scenes)}: engine={tts['engine']}")

    print("[4/4] 合成视频…")
    v = post("/api/compose", {"project_id": pid, "scenes": scenes, "aspect": "9:16"})
    print("🎉 完成:", BASE + v["video"])


if __name__ == "__main__":
    main()
