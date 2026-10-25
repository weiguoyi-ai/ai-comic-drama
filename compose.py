# -*- coding: utf-8 -*-
"""视频合成管线：分镜图片 + 配音 + 字幕 → 完整 mp4

流程：
1. 每个分镜：图片 + 配音 → 一段视频（时长 = 配音时长 + 0.6s 缓冲）
2. concat 拼接所有分镜片段
3. 生成 SRT 字幕并烧录进视频
"""

import os
import subprocess

import providers


def _run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("ffmpeg 失败: " + r.stderr[-1500:])


def _make_segment(image_path: str, audio_path: str, out_path: str, duration: float):
    """单分镜片段：静态图片 + 配音，加轻微放大动画（Ken Burns）。"""
    ffmpeg = providers._ffmpeg_bin()
    if audio_path:
        _run([ffmpeg, "-y",
              "-loop", "1", "-i", image_path,
              "-i", audio_path,
              "-vf", "scale=1280:720:force_original_aspect_ratio=increase,"
                     "crop=1280:720,zoompan=z='min(zoom+0.0006,1.08)':d=%d:s=1280x720:fps=25" % int(duration * 25),
              "-t", str(duration),
              "-c:v", "libx264", "-pix_fmt", "yuv420p",
              "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
              "-shortest", out_path])
    else:
        _run([ffmpeg, "-y",
              "-loop", "1", "-i", image_path,
              "-vf", "scale=1280:720:force_original_aspect_ratio=increase,crop=1280:720",
              "-t", str(duration),
              "-c:v", "libx264", "-pix_fmt", "yuv420p", out_path])


def _build_srt(scenes, durations, srt_path: str):
    """按分镜时长生成 SRT 字幕（旁白 + 台词）。"""

    def fmt(t):
        h, rem = divmod(int(t), 3600)
        m, s = divmod(rem, 60)
        return "%02d:%02d:%02d,000" % (h, m, s)

    lines, cur = [], 0.0
    for i, (sc, dur) in enumerate(zip(scenes, durations), 1):
        text = (sc.get("narration") or "").strip()
        dlg = (sc.get("dialogue") or "").strip()
        if dlg:
            text = (text + "\n" + dlg).strip()
        if not text:
            text = sc.get("title", "")
        lines.append("%d\n%s --> %s\n%s\n" % (i, fmt(cur), fmt(cur + dur), text))
        cur += dur
    with open(srt_path, "w", encoding="utf-8-sig") as f:
        f.write("\n".join(lines))


def compose(scenes, project_dir: str) -> str:
    """合成完整视频。scenes 每项含 image/tts 文件名，返回输出视频文件名。"""
    seg_files, durations = [], []
    for i, sc in enumerate(scenes):
        img = os.path.join(project_dir, sc["image"])
        tts = os.path.join(project_dir, sc["tts"]) if sc.get("tts") else None
        dur = providers.audio_duration(tts) + 0.6 if tts else 4.0
        seg = os.path.join(project_dir, "seg_%03d.mp4" % i)
        _make_segment(img, tts, seg, dur)
        seg_files.append(seg)
        durations.append(dur)

    # 拼接
    concat_list = os.path.join(project_dir, "concat.txt")
    with open(concat_list, "w", encoding="utf-8") as f:
        for seg in seg_files:
            f.write("file '%s'\n" % seg.replace("\\", "/"))
    joined = os.path.join(project_dir, "joined.mp4")
    ffmpeg = providers._ffmpeg_bin()
    _run([ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", concat_list,
          "-c", "copy", joined])

    # 字幕
    srt = os.path.join(project_dir, "subs.srt")
    _build_srt(scenes, durations, srt)
    srt_ff = srt.replace("\\", "/").replace(":", "\\:")
    output = os.path.join(project_dir, "final.mp4")
    _run([ffmpeg, "-y", "-i", joined,
          "-vf", "subtitles='%s':force_style='FontName=Microsoft YaHei,FontSize=16,"
                 "PrimaryColour=&H00FFFFFF,OutlineColour=&H80000000,BorderStyle=1,Outline=1,MarginV=28'" % srt_ff,
          "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "copy", output])

    # 清理中间文件
    for seg in seg_files:
        try:
            os.remove(seg)
        except OSError:
            pass
    for tmp in (concat_list, joined, srt):
        try:
            os.remove(tmp)
        except OSError:
            pass
    return "final.mp4"
