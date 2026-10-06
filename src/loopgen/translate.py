from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from .gemini import generate_json


def translate_segments(segments: list[dict], out_json: str | Path, *, api_key: str, model: str, progress: Callable[[str, float], None] | None = None) -> list[dict]:
    out_json = Path(out_json)
    if out_json.exists():
        return json.loads(out_json.read_text("utf-8"))
    rows = [{"id": s["id"], "start": s["start"], "end": s["end"], "zh": s["zh"], "slot_seconds": round(max(0.4, s["end"] - s["start"]), 2)} for s in segments]
    if progress:
        progress(f"Đang dịch {len(rows)} câu trong một batch…", 0.1)
    prompt = """Bạn là biên tập viên lồng tiếng video fitness Trung→Việt.
Trả về JSON ARRAY duy nhất. Mỗi object: {id, vi}.
Quy tắc:
- Dịch tự nhiên, nói được, đúng nghĩa fitness.
- Câu Việt phải NGẮN GỌN để đọc vừa slot_seconds. Không thêm giải thích.
- Giữ nguyên số lần, số giây, rep/set nếu có.
- Không thêm emoji, hook, CTA hay nội dung không có trong câu gốc.
- Không gộp/đổi id.
Input:
""" + json.dumps(rows, ensure_ascii=False)
    data = generate_json(api_key, model, prompt, timeout=180)
    if not isinstance(data, list):
        raise RuntimeError("Gemini translation không trả về array")
    by_id = {int(x.get("id")): str(x.get("vi", "")).strip() for x in data if isinstance(x, dict) and "id" in x}
    out = []
    for i, s in enumerate(segments):
        vi = by_id.get(int(s["id"]), "").strip()
        if not vi:
            raise RuntimeError(f"Thiếu bản dịch cho câu {s['id']}")
        out.append({**s, "vi": vi})
        if progress:
            progress(f"Đã dịch {i + 1}/{len(segments)} câu", 0.15 + 0.8 * (i + 1) / max(1, len(segments)))
    out_json.write_text(json.dumps(out, ensure_ascii=False, indent=2), "utf-8")
    return out
