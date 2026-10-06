import shutil
import subprocess
import wave
from pathlib import Path

import numpy as np
import pytest

from loopgen.render import build_overlay, render_full
from loopgen.utils import media_info


pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg required")


def _voice(path: Path, seconds: float = 2.0):
    rate = 48000
    t = np.arange(int(rate * seconds), dtype=np.float32) / rate
    audio = (0.08 * np.sin(2 * np.pi * 440 * t) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate); w.writeframes(audio.tobytes())


def test_no_ass_overlay_and_mux(tmp_path):
    src = tmp_path / "source.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=gray:s=360x640:d=2:r=25",
        "-f", "lavfi", "-i", "sine=frequency=220:duration=2:sample_rate=48000",
        "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(src)
    ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    voice = tmp_path / "voice.wav"; _voice(voice)
    tracks = [{
        "id": 1, "start": 0.2, "end": 1.7, "action": "translate",
        "vi": "Giữ lưng thẳng", "bbox": [0.18, 0.18, 0.62, 0.25],
        "observations": 2, "confidence": 0.96,
    }]
    overlay = build_overlay(src, tracks, tmp_path / "overlay.mov", limit=2)
    assert not overlay["empty"] and overlay["states"] >= 2
    out = render_full(src, voice, overlay, tmp_path / "out.mp4", original_volume=0.1)
    info = media_info(out)
    assert out.exists() and out.stat().st_size > 1000
    assert info["width"] == 360 and info["height"] == 640
    assert info["has_audio"] is True
    assert 1.7 <= info["duration"] <= 2.2
