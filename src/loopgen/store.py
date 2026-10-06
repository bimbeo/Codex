from __future__ import annotations

import threading
import time
import uuid
from pathlib import Path
from typing import Any

from .config import data_root
from .utils import atomic_json, read_json, safe_rmtree

STEP_NAMES = {
    1: "ASR tiếng Trung",
    2: "Dịch lời thoại",
    3: "Localize chữ màn hình",
    4: "Tạo voice Việt",
    5: "Dựng overlay",
    6: "Render full video",
}


class ProjectStore:
    def __init__(self) -> None:
        self.root = data_root()
        self.index_path = self.root / "projects-v09.json"
        self.lock = threading.RLock()
        self.projects: dict[str, dict[str, Any]] = read_json(self.index_path, {}) or {}
        for p in self.projects.values():
            if p.get("status") in {"running", "queued", "cancelling"}:
                p["status"] = "paused"
                p["detail"] = "Phiên trước đã dừng — có thể chạy tiếp"
        self._save()

    def _save(self) -> None:
        atomic_json(self.index_path, self.projects)

    def list(self) -> list[dict[str, Any]]:
        with self.lock:
            return sorted((dict(v) for v in self.projects.values()), key=lambda x: x.get("created_at", 0), reverse=True)

    def get(self, project_id: str) -> dict[str, Any]:
        with self.lock:
            if project_id not in self.projects:
                raise KeyError(project_id)
            return dict(self.projects[project_id])

    def create(self, title: str, source_name: str = "", url: str = "") -> dict[str, Any]:
        with self.lock:
            pid = uuid.uuid4().hex[:16]
            folder = self.root / "projects" / pid
            folder.mkdir(parents=True, exist_ok=True)
            now = time.time()
            project = {
                "id": pid,
                "title": title or source_name or "LoopGen project",
                "source_name": source_name,
                "source_path": "",
                "source_url": url,
                "folder": str(folder),
                "created_at": now,
                "updated_at": now,
                "status": "new",
                "step": 0,
                "progress": 0.0,
                "detail": "Đã tạo project",
                "error": "",
                "queue_position": 0,
                "steps": {str(i): {"status": "pending", "name": STEP_NAMES[i]} for i in range(1, 7)},
                "output_path": "",
            }
            self.projects[pid] = project
            self._save()
            return dict(project)

    def update(self, project_id: str, **changes: Any) -> dict[str, Any]:
        with self.lock:
            p = self.projects[project_id]
            p.update(changes)
            p["updated_at"] = time.time()
            self._save()
            return dict(p)

    def update_step(self, project_id: str, step: int, status: str, *, detail: str = "", progress: float | None = None, elapsed: float | None = None) -> dict[str, Any]:
        with self.lock:
            p = self.projects[project_id]
            row = p["steps"][str(step)]
            row["status"] = status
            if elapsed is not None:
                row["elapsed"] = round(elapsed, 2)
            p["step"] = step
            if detail:
                p["detail"] = detail
            if progress is not None:
                p["progress"] = max(0.0, min(1.0, float(progress)))
            p["updated_at"] = time.time()
            self._save()
            return dict(p)

    def delete(self, project_id: str) -> None:
        with self.lock:
            p = self.projects.pop(project_id, None)
            self._save()
        if p:
            safe_rmtree(p["folder"], self.root / "projects")
