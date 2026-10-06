from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Callable

from .utils import run

_MODEL = None
_MODEL_NAME = None
_LOCK = threading.Lock()


def extract_audio(source: str | Path, wav_path: str | Path) -> Path:
    wav_path = Path(wav_path)
    if wav_path.exists() and wav_path.stat().st_size > 4096:
        return wav_path
    run(["ffmpeg", "-y", "-i", str(source), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(wav_path)])
    return wav_path


def _model(name: str):
    global _MODEL, _MODEL_NAME
    with _LOCK:
        if _MODEL is None or _MODEL_NAME != name:
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:
                raise RuntimeError("Thiếu faster-whisper. Chạy lại ./setup_loopgen.command") from exc
            _MODEL = WhisperModel(name, device="auto", compute_type="int8")
            _MODEL_NAME = name
        return _MODEL


def transcribe(source: str | Path, out_json: str | Path, *, model_name: str = "small", progress: Callable[[str, float], None] | None = None) -> list[dict]:
    out_json = Path(out_json)
    if out_json.exists():
        return json.loads(out_json.read_text("utf-8"))
    audio = extract_audio(source, out_json.parent / "source_16k.wav")
    if progress:
        progress("Đang nhận dạng tiếng Trung…", 0.08)
    model = _model(model_name)
    segments, info = model.transcribe(
        str(audio), language="zh", vad_filter=True, beam_size=2, best_of=2,
        condition_on_previous_text=True, word_timestamps=False,
    )
    result = []
    duration = float(getattr(info, "duration", 0) or 0)
    for idx, seg in enumerate(segments):
        text = (seg.text or "").strip()
        if not text:
            continue
        result.append({"id": len(result), "start": round(float(seg.start), 3), "end": round(float(seg.end), 3), "zh": text})
        if progress and duration:
            progress(f"ASR {seg.end:.1f}/{duration:.1f}s · {text[:28]}", min(0.98, float(seg.end) / duration))
    out_json.write_text(json.dumps(result, ensure_ascii=False, indent=2), "utf-8")
    return result
