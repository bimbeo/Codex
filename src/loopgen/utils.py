from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Iterable

ZH_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
NUMERIC_RE = re.compile(r"^[\s\d.:/xX×%+\-]+$")


def has_chinese(text: str) -> bool:
    return bool(ZH_RE.search(text or ""))


def is_counter_or_timer(text: str) -> bool:
    t = (text or "").strip()
    return bool(t) and bool(NUMERIC_RE.fullmatch(t))


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", "", (text or "").strip()).replace("，", ",").replace("：", ":")


def run(cmd: list[str], *, check: bool = True, capture: bool = True, cwd: str | Path | None = None) -> subprocess.CompletedProcess:
    proc = subprocess.run(cmd, cwd=cwd, text=True, capture_output=capture)
    if check and proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "")[-5000:]
        raise RuntimeError(f"Lệnh thất bại ({proc.returncode}): {' '.join(cmd[:8])}\n{tail}")
    return proc


def ffprobe(path: str | Path) -> dict[str, Any]:
    proc = run([
        "ffprobe", "-v", "error", "-show_entries",
        "format=duration:stream=index,codec_type,codec_name,width,height,r_frame_rate,sample_rate,channels",
        "-of", "json", str(path)
    ])
    return json.loads(proc.stdout)


def media_info(path: str | Path) -> dict[str, Any]:
    raw = ffprobe(path)
    video = next((s for s in raw.get("streams", []) if s.get("codec_type") == "video"), {})
    audio = next((s for s in raw.get("streams", []) if s.get("codec_type") == "audio"), {})
    dur = float(raw.get("format", {}).get("duration") or 0)
    fps = 30.0
    ratio = video.get("r_frame_rate") or "30/1"
    try:
        a, b = ratio.split("/")
        fps = float(a) / max(float(b), 1e-9)
    except Exception:
        pass
    return {
        "duration": dur,
        "width": int(video.get("width") or 0),
        "height": int(video.get("height") or 0),
        "fps": fps,
        "has_audio": bool(audio),
        "video_codec": video.get("codec_name"),
    }


def atomic_json(path: str | Path, data: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name, dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def read_json(path: str | Path, default: Any = None) -> Any:
    try:
        return json.loads(Path(path).read_text("utf-8"))
    except Exception:
        return default


def safe_rmtree(path: str | Path, root: str | Path) -> None:
    p = Path(path).resolve()
    r = Path(root).resolve()
    if p == r or r not in p.parents:
        raise ValueError("Refuse to delete outside LoopGen data root")
    shutil.rmtree(p, ignore_errors=True)


def ensure_ffmpeg() -> None:
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise RuntimeError("Không tìm thấy FFmpeg/ffprobe. Trên macOS hãy chạy: brew install ffmpeg")


def chunks(items: list[Any], size: int) -> Iterable[list[Any]]:
    for i in range(0, len(items), size):
        yield items[i:i + size]
