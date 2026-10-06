from __future__ import annotations

import difflib
import json
import math
import re
import shutil
import statistics
import threading
from pathlib import Path
from typing import Callable, Any

from PIL import Image

from .gemini import generate_json
from .utils import has_chinese, is_counter_or_timer, media_info, normalize_text, run

_OCR = None
_OCR_LOCK = threading.Lock()


def _ocr_engine():
    global _OCR
    with _OCR_LOCK:
        if _OCR is None:
            try:
                from rapidocr_onnxruntime import RapidOCR
            except ImportError as exc:
                raise RuntimeError("Thiếu rapidocr-onnxruntime. Chạy lại ./setup_loopgen.command") from exc
            _OCR = RapidOCR()
        return _OCR


def _bbox(poly: Any) -> tuple[float, float, float, float]:
    xs = [float(p[0]) for p in poly]
    ys = [float(p[1]) for p in poly]
    return min(xs), min(ys), max(xs), max(ys)


def _iou(a: list[float], b: list[float]) -> float:
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    aa = max(1e-9, (a[2] - a[0]) * (a[3] - a[1]))
    bb = max(1e-9, (b[2] - b[0]) * (b[3] - b[1]))
    return inter / (aa + bb - inter + 1e-9)


def _text_sim(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, normalize_text(a), normalize_text(b)).ratio()


def extract_sample_frames(source: str | Path, frame_dir: str | Path, fps: float = 1.0) -> list[Path]:
    frame_dir = Path(frame_dir)
    frame_dir.mkdir(parents=True, exist_ok=True)
    existing = sorted(frame_dir.glob("f_*.jpg"))
    if existing:
        return existing
    # scale down only for OCR speed; coordinates are normalized so output resolution does not matter.
    vf = f"fps={fps},scale='min(720,iw)':-2"
    run(["ffmpeg", "-y", "-i", str(source), "-vf", vf, "-q:v", "4", str(frame_dir / "f_%06d.jpg")])
    return sorted(frame_dir.glob("f_*.jpg"))


def detect_frames(frames: list[Path], *, fps: float, bottom_ignore: float, progress: Callable[[str, float], None] | None = None) -> list[dict]:
    engine = _ocr_engine()
    rows: list[dict] = []
    total = max(1, len(frames))
    for idx, path in enumerate(frames):
        with Image.open(path) as im:
            w, h = im.size
        result = engine(str(path))
        detections = result[0] if isinstance(result, tuple) else result
        for item in detections or []:
            try:
                poly, text, score = item[0], str(item[1]).strip(), float(item[2])
            except Exception:
                continue
            if score < 0.52 or not text:
                continue
            x1, y1, x2, y2 = _bbox(poly)
            box = [x1 / w, y1 / h, x2 / w, y2 / h]
            bw, bh = box[2] - box[0], box[3] - box[1]
            if bw * bh < 0.00018:
                continue
            # Dialogue subtitles at the bottom are handled by voice dubbing, not visual OCR.
            if box[1] >= bottom_ignore:
                continue
            rows.append({
                "time": idx / fps,
                "text": text,
                "score": score,
                "bbox": [round(v, 5) for v in box],
                "numeric": is_counter_or_timer(text),
                "has_zh": has_chinese(text),
            })
        if progress and (idx % max(1, total // 50) == 0 or idx + 1 == total):
            progress(f"OCR local {idx + 1}/{total} frame", 0.05 + 0.55 * (idx + 1) / total)
    return rows


def track_detections(rows: list[dict], *, fps: float) -> list[dict]:
    active: list[dict] = []
    finished: list[dict] = []
    gap = max(1.2, 1.6 / max(fps, 0.1))
    rows = sorted(rows, key=lambda x: x["time"])
    for d in rows:
        t = float(d["time"])
        stale = [tr for tr in active if t - tr["last"] > gap]
        for tr in stale:
            active.remove(tr); finished.append(tr)
        best, best_score = None, 0.0
        for tr in active:
            iou = _iou(tr["bbox_last"], d["bbox"])
            sim = _text_sim(tr["texts"][-1], d["text"])
            cx1 = (tr["bbox_last"][0] + tr["bbox_last"][2]) / 2
            cy1 = (tr["bbox_last"][1] + tr["bbox_last"][3]) / 2
            cx2 = (d["bbox"][0] + d["bbox"][2]) / 2
            cy2 = (d["bbox"][1] + d["bbox"][3]) / 2
            dist = math.hypot(cx1 - cx2, cy1 - cy2)
            score = max(iou, sim * (1.0 if dist < 0.08 else 0.4))
            if (iou >= 0.22 or (sim >= 0.62 and dist < 0.10)) and score > best_score:
                best, best_score = tr, score
        if best is None:
            active.append({"start": t, "last": t, "texts": [d["text"]], "scores": [d["score"]], "boxes": [d["bbox"]], "bbox_last": d["bbox"], "numeric": d["numeric"], "has_zh": d["has_zh"]})
        else:
            best["last"] = t
            best["texts"].append(d["text"])
            best["scores"].append(d["score"])
            best["boxes"].append(d["bbox"])
            best["bbox_last"] = d["bbox"]
            best["numeric"] = best["numeric"] and d["numeric"]
            best["has_zh"] = best["has_zh"] or d["has_zh"]
    finished.extend(active)
    tracks = []
    for idx, tr in enumerate(finished):
        texts = tr["texts"]
        # choose the text variant with highest combined confidence/frequency
        variants: dict[str, list[tuple[str, float]]] = {}
        for txt, sc in zip(texts, tr["scores"]):
            variants.setdefault(normalize_text(txt), []).append((txt, sc))
        key = max(variants, key=lambda k: (len(variants[k]), sum(x[1] for x in variants[k])))
        text = max(variants[key], key=lambda x: x[1])[0]
        boxes = tr["boxes"]
        box = [statistics.median([b[i] for b in boxes]) for i in range(4)]
        start = max(0.0, tr["start"] - 0.48 / max(fps, 0.1))
        end = tr["last"] + 0.72 / max(fps, 0.1)
        tracks.append({
            "id": idx,
            "start": round(start, 3), "end": round(end, 3),
            "text": text,
            "bbox": [round(v, 5) for v in box],
            "confidence": round(sum(tr["scores"]) / len(tr["scores"]), 3),
            "observations": len(texts),
            "numeric": bool(tr["numeric"]),
            "has_zh": bool(tr["has_zh"]),
        })
    # Remove near-duplicate consecutive tracks with same stabilized text and location.
    merged: list[dict] = []
    for tr in sorted(tracks, key=lambda x: (x["start"], x["bbox"][1])):
        if merged:
            prev = merged[-1]
            if _text_sim(prev["text"], tr["text"]) > 0.88 and _iou(prev["bbox"], tr["bbox"]) > 0.30 and tr["start"] - prev["end"] < 1.5:
                prev["end"] = max(prev["end"], tr["end"])
                prev["observations"] += tr["observations"]
                continue
        merged.append(tr)
    for i, tr in enumerate(merged): tr["id"] = i
    return merged


def classify_tracks(tracks: list[dict], *, api_key: str, model: str, progress: Callable[[str, float], None] | None = None) -> list[dict]:
    # Hard rules first: counters/timers and non-Chinese visual noise never consume Gemini quota.
    candidates = []
    for tr in tracks:
        if tr["numeric"]:
            tr.update(action="keep", vi="", reason="counter/timer")
        elif not tr["has_zh"]:
            tr.update(action="ignore", vi="", reason="non-Chinese/logo")
        else:
            candidates.append(tr)
    if not candidates:
        return tracks
    payload = [{"id": t["id"], "text": t["text"], "bbox": t["bbox"], "seconds": round(t["end"] - t["start"], 1)} for t in candidates]
    if progress:
        progress(f"Đang phân loại {len(payload)} text track trong 1 batch Gemini…", 0.68)
    prompt = """Bạn đang localize NGUYÊN VIDEO fitness Trung Quốc sang tiếng Việt. Hãy phân loại text OCR.
Trả JSON ARRAY: {id, action, vi, reason}. action chỉ một trong translate|keep|ignore.

BẮT BUỘC:
- translate: tên động tác, nhóm cơ/tác dụng, hướng dẫn tư thế/chuyển động, cảnh báo kỹ thuật, số lần/hiệp khi nằm trong một câu có nghĩa.
- keep: số thứ tự bài, timer, rep counter thuần số. (Phần lớn đã được lọc trước.)
- ignore: subtitle hội thoại, watermark, username/hashtag, logo/brand, chữ trên chai/hộp/quần áo/dụng cụ, text trang trí không liên quan bài tập.
- Không sáng tác hook/CTA. `vi` phải ngắn, tự nhiên, chỉ dịch nội dung gốc; giữ nguyên số.
- Nếu nghi ngờ logo/packaging → ignore.
Input tracks:
""" + json.dumps(payload, ensure_ascii=False)
    data = generate_json(api_key, model, prompt, timeout=180)
    by_id = {int(x.get("id")): x for x in data if isinstance(x, dict) and "id" in x}
    for tr in candidates:
        x = by_id.get(tr["id"], {})
        action = str(x.get("action", "ignore")).lower()
        if action not in {"translate", "keep", "ignore"}: action = "ignore"
        vi = str(x.get("vi", "")).strip() if action == "translate" else ""
        if action == "translate" and not vi:
            action = "ignore"
        tr.update(action=action, vi=vi, reason=str(x.get("reason", ""))[:160])
    return tracks


def localize_visual_text(source: str | Path, out_json: str | Path, *, api_key: str, model: str, fps: float = 1.0, bottom_ignore: float = 0.80, progress: Callable[[str, float], None] | None = None) -> list[dict]:
    out_json = Path(out_json)
    if out_json.exists():
        return json.loads(out_json.read_text("utf-8"))
    frame_dir = out_json.parent / "ocr_frames"
    frames = extract_sample_frames(source, frame_dir, fps=fps)
    detections = detect_frames(frames, fps=fps, bottom_ignore=bottom_ignore, progress=progress)
    tracks = track_detections(detections, fps=fps)
    if progress:
        progress(f"Đã gom {len(detections)} box → {len(tracks)} text track", 0.64)
    tracks = classify_tracks(tracks, api_key=api_key, model=model, progress=progress)
    info = media_info(source)
    for tr in tracks:
        tr["end"] = min(float(tr["end"]), info["duration"])
    out_json.write_text(json.dumps(tracks, ensure_ascii=False, indent=2), "utf-8")
    if progress:
        kept = sum(1 for t in tracks if t.get("action") == "translate")
        progress(f"Xong OCR: {kept} text cần dịch / {len(tracks)} track", 0.98)
    return tracks
