from __future__ import annotations

import json
import queue
import shutil
import threading
import time
from pathlib import Path
from typing import Callable

from .asr import transcribe
from .config import Settings
from .render import build_overlay, render_full
from .store import ProjectStore
from .translate import translate_segments
from .tts import build_voice_timeline
from .utils import ensure_ffmpeg, read_json, run
from .vision import localize_visual_text


class ProjectDeleted(Exception):
    pass


class PipelineManager:
    """One heavy project at a time by default.

    This is deliberate: running 3 Whisper/RapidOCR/render jobs together made each
    3-minute video much slower on typical Macs. Other projects remain queued with
    an explicit queue position instead of silently fighting for CPU/RAM.
    """

    def __init__(self, store: ProjectStore, get_settings: Callable[[], Settings]) -> None:
        self.store = store
        self.get_settings = get_settings
        self.q: queue.Queue[str] = queue.Queue()
        self.cancel_events: dict[str, threading.Event] = {}
        self.deleted: set[str] = set()
        self.enqueued: set[str] = set()
        self.lock = threading.RLock()
        self.worker = threading.Thread(target=self._worker, daemon=True, name="loopgen-pipeline")
        self.worker.start()

    def enqueue(self, project_id: str) -> None:
        with self.lock:
            if project_id in self.deleted or project_id in self.enqueued:
                return
            try:
                p = self.store.get(project_id)
            except KeyError:
                return
            if p.get("status") == "running":
                return
            ev = self.cancel_events.setdefault(project_id, threading.Event())
            ev.clear()
            self.enqueued.add(project_id)
            pos = self.q.qsize() + 1
            self.store.update(project_id, status="queued", detail=f"Đang chờ lượt · vị trí {pos}", queue_position=pos, error="")
            self.q.put(project_id)

    def cancel(self, project_id: str) -> None:
        with self.lock:
            self.cancel_events.setdefault(project_id, threading.Event()).set()
            try:
                self.store.update(project_id, status="cancelling", detail="Đang hủy tác vụ…")
            except KeyError:
                pass

    def delete(self, project_id: str) -> None:
        with self.lock:
            self.deleted.add(project_id)
            self.cancel_events.setdefault(project_id, threading.Event()).set()
            self.enqueued.discard(project_id)
        self.store.delete(project_id)

    def _cancelled(self, pid: str) -> bool:
        return pid in self.deleted or self.cancel_events.setdefault(pid, threading.Event()).is_set()

    def _safe_update(self, pid: str, **kw) -> None:
        if pid in self.deleted:
            raise ProjectDeleted()
        try:
            self.store.update(pid, **kw)
        except KeyError:
            raise ProjectDeleted()

    def _progress(self, pid: str, step: int):
        def cb(detail: str, local: float) -> None:
            if self._cancelled(pid):
                raise ProjectDeleted() if pid in self.deleted else RuntimeError("Đã hủy")
            overall = ((step - 1) + max(0.0, min(1.0, local))) / 6.0
            try:
                self.store.update_step(pid, step, "running", detail=detail, progress=overall)
            except KeyError:
                raise ProjectDeleted()
        return cb

    def _ensure_source(self, pid: str) -> Path:
        p = self.store.get(pid)
        if p.get("source_path") and Path(p["source_path"]).exists():
            return Path(p["source_path"])
        url = p.get("source_url") or ""
        if not url:
            raise RuntimeError("Project chưa có video nguồn")
        if self._cancelled(pid): raise RuntimeError("Đã hủy")
        folder = Path(p["folder"])
        self._safe_update(pid, status="running", detail="Đang tải video nguồn…", progress=0.0)
        template = str(folder / "source.%(ext)s")
        proc = run(["yt-dlp", "--no-playlist", "--merge-output-format", "mp4", "-o", template, url], check=False)
        if proc.returncode != 0:
            raise RuntimeError("Không tải được URL. Hãy thử file local hoặc cập nhật yt-dlp.\n" + (proc.stderr or "")[-1500:])
        candidates = sorted(folder.glob("source.*"), key=lambda x: x.stat().st_size, reverse=True)
        if not candidates:
            raise RuntimeError("yt-dlp không tạo được video nguồn")
        source = candidates[0]
        self._safe_update(pid, source_path=str(source), source_name=source.name)
        return source

    def _worker(self) -> None:
        while True:
            pid = self.q.get()
            with self.lock:
                self.enqueued.discard(pid)
            if pid in self.deleted:
                self.q.task_done(); continue
            try:
                self._run(pid)
            except ProjectDeleted:
                pass
            except Exception as exc:
                try:
                    p = self.store.get(pid)
                    step = int(p.get("step") or 1)
                    self.store.update_step(pid, step, "error", detail=f"Lỗi bước {step}: {exc}")
                    self.store.update(pid, status="error", error=str(exc), detail=f"Lỗi bước {step}: {exc}")
                except KeyError:
                    pass
            finally:
                self.q.task_done()

    def _run(self, pid: str) -> None:
        ensure_ffmpeg()
        settings = self.get_settings()
        source = self._ensure_source(pid)
        p = self.store.get(pid); folder = Path(p["folder"])
        self._safe_update(pid, status="running", queue_position=0, error="")

        asr_path = folder / "asr_zh.json"
        tr_path = folder / "dialogue_vi.json"
        visual_path = folder / "visual_tracks.json"
        voice_path = folder / "voice_vi.wav"
        overlay_path = folder / "overlay.mov"
        output_path = folder / "loopgen_vi.mp4"

        def run_step(step: int, fn):
            if self._cancelled(pid): raise RuntimeError("Đã hủy")
            # A done step with a valid artifact is skipped by fn cache; marking it running is still useful on resume.
            started = time.time()
            self.store.update_step(pid, step, "running", detail=f"Bước {step}/6 · đang bắt đầu…", progress=(step-1)/6)
            value = fn()
            elapsed = time.time() - started
            self.store.update_step(pid, step, "done", detail=f"Bước {step}/6 hoàn tất · {elapsed:.1f}s", progress=step/6, elapsed=elapsed)
            return value

        segments = run_step(1, lambda: transcribe(source, asr_path, model_name=settings.asr_model, progress=self._progress(pid,1)))
        translated = run_step(2, lambda: translate_segments(segments, tr_path, api_key=settings.gemini_key, model=settings.gemini_model, progress=self._progress(pid,2)))
        tracks = run_step(3, lambda: localize_visual_text(source, visual_path, api_key=settings.gemini_key, model=settings.gemini_model, fps=settings.ocr_fps, bottom_ignore=settings.ocr_bottom_ignore, progress=self._progress(pid,3)))
        voice_meta = run_step(4, lambda: build_voice_timeline(translated, source, voice_path, voice=settings.tts_voice, progress=self._progress(pid,4), cancelled=lambda:self._cancelled(pid)))
        overlay_meta = run_step(5, lambda: build_overlay(source, tracks, overlay_path, limit=settings.max_visual_texts, progress=self._progress(pid,5)))
        output = run_step(6, lambda: render_full(source, voice_path, overlay_meta, output_path, original_volume=settings.original_audio_volume, progress=self._progress(pid,6)))
        self._safe_update(pid, status="done", step=6, progress=1.0, detail="✅ Hoàn tất full video", output_path=str(output), error="")
