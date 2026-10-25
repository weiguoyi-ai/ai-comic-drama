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
    image: str = ""
    tts: str = ""


class ImageReq(BaseModel):
    project_id: str
    prompt: str
    style: str = ""
    aspect: str = "16:9"


class TtsReq(BaseModel):
    project_id: str
    text: str
    voice: str = "zh-CN-YunxiNeural"


class ComposeReq(BaseModel):
    project_id: str
    scenes: list[Scene]
    aspect: str = "16:9"


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
        filename = providers.gen_image(req.prompt, project_dir, req.style, req.aspect)
        return {"image": filename}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/api/tts")
def api_tts(req: TtsReq):
    try:
        project_dir = _ensure_project(req.project_id)
        filename = providers.gen_tts(req.text, req.voice, project_dir)
        return {"tts": filename}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/api/compose")
def api_compose(req: ComposeReq):
    try:
        project_dir = _ensure_project(req.project_id)
        filename = compose.compose([s.model_dump() for s in req.scenes],
                                   project_dir, req.aspect)
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
