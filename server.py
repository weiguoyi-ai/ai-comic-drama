# -*- coding: utf-8 -*-
"""AI 漫剧工具 - 后端服务

启动: python server.py  →  http://127.0.0.1:8000
"""

import os
import uuid

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import compose
import providers

ROOT = os.path.dirname(os.path.abspath(__file__))
app = FastAPI(title="AI 漫剧工具")


class StoryboardReq(BaseModel):
    script: str
    style: str = "日系动漫风"
    scene_count: int = 6


class Scene(BaseModel):
    title: str = ""
    narration: str = ""
    dialogue: str = ""
    speaker: str = ""
    image: str = ""
    tts: str = ""


class ImageReq(BaseModel):
    project_id: str
    prompt: str
    style: str = ""
    aspect: str = "9:16"
    ref_image: str = ""  # 参考图文件名：用于保持角色形象一致


class TtsReq(BaseModel):
    project_id: str
    text: str
    voice: str = ""       # 留空则按 speaker 自动分配
    speaker: str = ""     # 角色名，用于音色映射
    rate: int = 0         # 语速百分比 -50~50


class ComposeReq(BaseModel):
    project_id: str
    scenes: list[Scene]
    aspect: str = "9:16"
    bgm: str = ""         # 空=自动挑选，"none"=不加背景乐，或指定文件路径
    bgm_volume: float = -1


@app.get("/api/config")
def api_config():
    """告诉前端当前是否已接入真实模型。"""
    return providers.config_status()


@app.post("/api/storyboard")
def api_storyboard(req: StoryboardReq):
    try:
        project_id = uuid.uuid4().hex[:12]
        result = providers.gen_storyboard(req.script, req.style, req.scene_count)
        project_dir = _ensure_project(project_id)
        for sc in result["scenes"]:
            sc.setdefault("image", "")
            sc.setdefault("tts", "")
        return {"project_id": project_id, "project_dir": project_dir, **result}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/api/image")
def api_image(req: ImageReq):
    try:
        project_dir = _ensure_project(req.project_id)
        filename, backend = providers.gen_image(
            req.prompt, project_dir, req.style, req.aspect, req.ref_image)
        return {"image": filename, "backend": backend, "mock": backend == "placeholder"}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/api/tts")
def api_tts(req: TtsReq):
    try:
        project_dir = _ensure_project(req.project_id)
        if req.voice:
            voice, rate = req.voice, req.rate
        else:
            resolved = providers.resolve_voice(req.speaker, project_dir=project_dir)
            voice, rate = resolved["voice"], resolved["rate"]
        filename, engine = providers.gen_tts(req.text, voice, project_dir, rate)
        return {"tts": filename, "engine": engine, "voice": voice, "rate": rate}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/api/compose")
def api_compose(req: ComposeReq):
    try:
        project_dir = _ensure_project(req.project_id)
        filename = compose.compose([s.model_dump() for s in req.scenes],
                                   project_dir, req.aspect,
                                   bgm=req.bgm, bgm_volume=req.bgm_volume)
        return {"video": "/api/file/" + req.project_id + "/" + filename}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/api/file/{project_id}/{filename}")
def api_file(project_id: str, filename: str):
    # 防目录穿越
    if ".." in project_id or ".." in filename or "/" in filename or "\\" in filename:
        return JSONResponse(status_code=400, content={"error": "bad path"})
    path = os.path.join(ROOT, "projects", project_id, filename)
    if not os.path.exists(path):
        return JSONResponse(status_code=404, content={"error": "not found"})
    return FileResponse(path)


def _ensure_project(project_id: str) -> str:
    d = os.path.join(ROOT, "projects", project_id)
    os.makedirs(d, exist_ok=True)
    return d


# 前端静态页面（放在最后挂载，避免覆盖 /api 路由）
app.mount("/", StaticFiles(directory=os.path.join(ROOT, "static"), html=True),
          name="static")


if __name__ == "__main__":
    import uvicorn
    print("AI 漫剧工具已启动: http://127.0.0.1:8000")
    uvicorn.run(app, host="127.0.0.1", port=8000)
