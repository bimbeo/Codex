from __future__ import annotations

import asyncio
import math
import platform
import shutil
import subprocess
import wave
from pathlib import Path
from typing import Callable

import numpy as np

from .utils import media_info, run


def _atempo_chain(speed: float) -> str:
    speed = max(0.25, min(4.0, speed))
    parts = []
    while speed > 2.0:
        parts.append(2.0); speed /= 2.0
    while speed < 0.5:
        parts.append(0.5); speed /= 0.5
    parts.append(speed)
    return ",".join(f"atempo={x:.5f}" for x in parts)


async def _edge_save(text: str, voice: str, out_path: Path) -> None:
    import edge_tts
    communicate = edge_tts.Communicate(text, voice=voice)
    await communicate.save(str(out_path))


def _system_say(text: str, out_path: Path) -> bool:
    if platform.system() == "Darwin" and shutil.which("say"):
        voices = subprocess.run(["say", "-v", "?"], text=True, capture_output=True).stdout
        voice = ""
        for line in voices.splitlines():
            if "vi_" in line or line.lower().startswith("linh "):
                voice = line.split()[0]; break
        cmd = ["say"] + (["-v", voice] if voice else []) + ["-o", str(out_path), text]
        return subprocess.run(cmd).returncode == 0
    exe = shutil.which("espeak-ng") or shutil.which("espeak")
    if exe:
        return subprocess.run([exe, "-v", "vi", "-w", str(out_path), text]).returncode == 0
    return False


def synth_segment(text: str, slot: float, out_wav: Path, *, voice: str) -> str:
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    raw = out_wav.with_suffix(".mp3")
    provider = "edge-tts"
    try:
        asyncio.run(_edge_save(text, voice, raw))
    except Exception:
        provider = "system"
        raw = out_wav.with_suffix(".aiff" if platform.system() == "Darwin" else ".wav")
        if not _system_say(text, raw):
            raise RuntimeError("Không tạo được voice. Kiểm tra Internet (Edge TTS) hoặc voice hệ thống tiếng Việt.")
    tmp = out_wav.with_suffix(".normalized.wav")
    run(["ffmpeg", "-y", "-i", str(raw), "-ac", "1", "-ar", "48000", "-c:a", "pcm_s16le", str(tmp)])
    duration = media_info(tmp)["duration"]
    # Voice may run a little long, but must not drift into the next exercise/sentence.
    if slot > 0.35 and duration > slot * 1.06:
        speed = min(1.55, duration / max(slot * 0.98, 0.2))
        run(["ffmpeg", "-y", "-i", str(tmp), "-filter:a", _atempo_chain(speed), "-ac", "1", "-ar", "48000", "-c:a", "pcm_s16le", str(out_wav)])
        tmp.unlink(missing_ok=True)
    else:
        tmp.replace(out_wav)
    raw.unlink(missing_ok=True)
    return provider


def _load_wav(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as w:
        rate = w.getframerate(); ch = w.getnchannels(); sw = w.getsampwidth()
        if ch != 1 or sw != 2:
            raise RuntimeError(f"WAV segment không chuẩn mono/16-bit: {path}")
        data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768.0
    return data, rate


def build_voice_timeline(segments: list[dict], source: str | Path, out_wav: str | Path, *, voice: str, progress: Callable[[str, float], None] | None = None, cancelled: Callable[[], bool] | None = None) -> dict:
    out_wav = Path(out_wav)
    if out_wav.exists() and out_wav.stat().st_size > 4096:
        return {"path": str(out_wav), "provider": "cached"}
    duration = media_info(source)["duration"]
    seg_dir = out_wav.parent / "voice_segments_v09"
    seg_dir.mkdir(exist_ok=True)
    providers: dict[str, int] = {}
    made: list[tuple[dict, Path]] = []
    for idx, seg in enumerate(segments):
        if cancelled and cancelled(): raise RuntimeError("Đã hủy")
        p = seg_dir / f"{idx:04d}.wav"
        if not p.exists():
            slot = max(0.45, float(seg["end"]) - float(seg["start"]))
            provider = synth_segment(str(seg["vi"]), slot, p, voice=voice)
        else:
            provider = "cached"
        providers[provider] = providers.get(provider, 0) + 1
        made.append((seg, p))
        if progress:
            progress(f"Voice {idx + 1}/{len(segments)} · {str(seg['vi'])[:32]}", 0.05 + 0.72 * (idx + 1) / max(1, len(segments)))
    rate = 48000
    mix = np.zeros(int(math.ceil(duration * rate)) + rate, dtype=np.float32)
    if progress: progress(f"Đang ghép {len(made)} đoạn voice theo timestamp…", 0.82)
    for seg, p in made:
        audio, sr = _load_wav(p)
        if sr != rate: raise RuntimeError("Unexpected voice sample rate")
        start = max(0, int(float(seg["start"]) * rate))
        end = min(len(mix), start + len(audio))
        if end > start:
            mix[start:end] += audio[:end-start]
    mix = np.clip(mix, -0.98, 0.98)
    pcm = (mix[:int(math.ceil(duration * rate))] * 32767.0).astype(np.int16)
    with wave.open(str(out_wav), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate); w.writeframes(pcm.tobytes())
    if progress: progress("Đã tạo xong voice Việt", 0.98)
    return {"path": str(out_wav), "providers": providers}
