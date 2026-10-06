from __future__ import annotations

import json
import mimetypes
import shutil
import threading
import webbrowser
from pathlib import Path

import uvicorn
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import __version__
from .config import Settings
from .pipeline import PipelineManager
from .store import ProjectStore
from .utils import ensure_ffmpeg

BASE = Path(__file__).resolve().parent
STATIC = BASE / "static"
store = ProjectStore()
_settings = Settings.load()
_settings_lock = threading.RLock()


def get_settings() -> Settings:
    with _settings_lock:
        return Settings(**_settings.__dict__)


manager = PipelineManager(store, get_settings)
app = FastAPI(title="LoopGen Studio", version=__version__)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


class UrlBody(BaseModel):
    url: str
    title: str = ""


class SettingsBody(BaseModel):
    gemini_key: str | None = None
    gemini_model: str | None = None
    asr_model: str | None = None
    auto_pipeline: bool | None = None
    ocr_fps: float | None = None
    tts_voice: str | None = None
    original_audio_volume: float | None = None
    max_visual_texts: int | None = None


@app.get("/")
def home():
    return FileResponse(STATIC / "index.html")


@app.get("/api/health")
def health():
    try:
        ensure_ffmpeg(); ffmpeg = True
    except Exception:
        ffmpeg = False
    return {"ok": True, "version": __version__, "ffmpeg": ffmpeg}


@app.get("/api/settings")
def settings_get():
    s = get_settings()
    return {
        "gemini_key_set": bool(s.gemini_key), "gemini_model": s.gemini_model,
        "asr_model": s.asr_model, "auto_pipeline": s.auto_pipeline,
        "ocr_fps": s.ocr_fps, "tts_voice": s.tts_voice,
        "original_audio_volume": s.original_audio_volume, "max_visual_texts": s.max_visual_texts,
    }


@app.post("/api/settings")
def settings_set(body: SettingsBody):
    global _settings
    with _settings_lock:
        data = body.model_dump(exclude_none=True)
        if "gemini_key" in data and not data["gemini_key"]:
            data.pop("gemini_key")
        for k,v in data.items():
            setattr(_settings,k,v)
        _settings.ocr_fps = max(0.5, min(2.0, float(_settings.ocr_fps)))
        _settings.original_audio_volume = max(0.0, min(1.0, float(_settings.original_audio_volume)))
        _settings.max_visual_texts = max(1, min(3, int(_settings.max_visual_texts)))
        _settings.save()
    return settings_get()


@app.get("/api/projects")
def project_list():
    return store.list()


@app.get("/api/projects/{project_id}")
def project_get(project_id: str):
    try: return store.get(project_id)
    except KeyError: raise HTTPException(404, "Project không tồn tại")


@app.post("/api/projects/upload")
def project_upload(file: UploadFile = File(...), title: str = Form(""), auto: bool = Form(True)):
    p = store.create(title or Path(file.filename or "video").stem, source_name=file.filename or "video")
    folder = Path(p["folder"])
    suffix = Path(file.filename or "source.mp4").suffix or ".mp4"
    source = folder / ("source" + suffix)
    try:
        with source.open("wb") as f:
            while True:
                chunk = file.file.read(1024 * 1024 * 4)
                if not chunk: break
                f.write(chunk)
        store.update(p["id"], source_path=str(source), source_name=file.filename or source.name, detail="Đã nhận video nguồn")
        if auto and get_settings().auto_pipeline:
            manager.enqueue(p["id"])
        return store.get(p["id"])
    except Exception:
        manager.delete(p["id"]); raise


@app.post("/api/projects/url")
def project_url(body: UrlBody):
    if not body.url.strip(): raise HTTPException(400, "Thiếu URL")
    p = store.create(body.title or "Video URL", url=body.url.strip())
    if get_settings().auto_pipeline: manager.enqueue(p["id"])
    return store.get(p["id"])


@app.post("/api/projects/{project_id}/run")
def project_run(project_id: str):
    try: store.get(project_id)
    except KeyError: raise HTTPException(404, "Project không tồn tại")
    manager.enqueue(project_id)
    return {"ok": True}


@app.post("/api/projects/{project_id}/cancel")
def project_cancel(project_id: str):
    manager.cancel(project_id); return {"ok": True}


@app.delete("/api/projects/{project_id}")
def project_delete(project_id: str):
    try: store.get(project_id)
    except KeyError: return {"ok": True}
    manager.delete(project_id); return {"ok": True}


@app.get("/api/projects/{project_id}/output")
def project_output(project_id: str):
    try: p = store.get(project_id)
    except KeyError: raise HTTPException(404, "Project không tồn tại")
    path = Path(p.get("output_path") or "")
    if not path.exists(): raise HTTPException(404, "Output chưa sẵn sàng")
    return FileResponse(path, media_type="video/mp4", filename=f"{p['title']}_vi.mp4")


@app.get("/api/projects/{project_id}/source")
def project_source(project_id: str):
    try: p = store.get(project_id)
    except KeyError: raise HTTPException(404, "Project không tồn tại")
    path = Path(p.get("source_path") or "")
    if not path.exists(): raise HTTPException(404, "Video nguồn chưa sẵn sàng")
    return FileResponse(path, media_type=mimetypes.guess_type(path.name)[0] or "video/mp4")


def main():
    host, port = "127.0.0.1", 8765
    threading.Timer(1.0, lambda: webbrowser.open(f"http://{host}:{port}")).start()
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
