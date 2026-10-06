from __future__ import annotations

import json
import os
import platform
from dataclasses import dataclass, asdict
from pathlib import Path

APP_NAME = "LoopGen"


def data_root() -> Path:
    override = os.getenv("LOOPGEN_DATA_DIR")
    if override:
        root = Path(override).expanduser()
    elif platform.system() == "Darwin":
        root = Path.home() / "Library" / "Application Support" / "LoopGen" / "LoopGen"
    elif platform.system() == "Windows":
        root = Path(os.getenv("APPDATA", Path.home())) / "LoopGen"
    else:
        root = Path.home() / ".local" / "share" / "LoopGen"
    root.mkdir(parents=True, exist_ok=True)
    (root / "projects").mkdir(exist_ok=True)
    return root


@dataclass
class Settings:
    gemini_key: str = ""
    gemini_model: str = "gemini-2.5-flash"
    asr_model: str = "small"
    auto_pipeline: bool = True
    ocr_fps: float = 1.0
    ocr_bottom_ignore: float = 0.80
    tts_voice: str = "vi-VN-HoaiMyNeural"
    original_audio_volume: float = 0.12
    max_visual_texts: int = 2

    @classmethod
    def load(cls) -> "Settings":
        path = data_root() / "settings.json"
        if not path.exists():
            return cls(gemini_key=os.getenv("GEMINI_API_KEY", ""))
        try:
            raw = json.loads(path.read_text("utf-8"))
            obj = cls(**{k: v for k, v in raw.items() if k in cls.__dataclass_fields__})
            if not obj.gemini_key:
                obj.gemini_key = os.getenv("GEMINI_API_KEY", "")
            return obj
        except Exception:
            return cls(gemini_key=os.getenv("GEMINI_API_KEY", ""))

    def save(self) -> None:
        (data_root() / "settings.json").write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), "utf-8")
