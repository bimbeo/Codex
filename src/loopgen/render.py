from __future__ import annotations

import json
import math
import platform
import shutil
from pathlib import Path
from typing import Callable

from PIL import Image, ImageDraw, ImageFont

from .utils import media_info, run


def _font(size: int):
    candidates = [
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Supplemental/Helvetica.ttc",
        "/Library/Fonts/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            try: return ImageFont.truetype(path, size=size)
            except Exception: pass
    return ImageFont.load_default()


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> list[str]:
    words = text.split()
    if not words: return [text]
    lines, cur = [], ""
    for word in words:
        test = (cur + " " + word).strip()
        if draw.textbbox((0,0), test, font=font)[2] <= max_width or not cur:
            cur = test
        else:
            lines.append(cur); cur = word
    if cur: lines.append(cur)
    return lines[:3]


def _overlap(a: list[float], b: list[float]) -> float:
    x1, y1 = max(a[0], b[0]), max(a[1], b[1]); x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    return max(0, x2-x1) * max(0, y2-y1)


def _choose_active(tracks: list[dict], t: float, limit: int) -> list[dict]:
    active = [x for x in tracks if x.get("action") == "translate" and x.get("vi") and float(x["start"]) <= t < float(x["end"])]
    # Big stable instructional graphics win over tiny OCR fragments.
    active.sort(key=lambda x: ((x["bbox"][2]-x["bbox"][0])*(x["bbox"][3]-x["bbox"][1]), x.get("observations", 0), x.get("confidence", 0)), reverse=True)
    out = []
    for tr in active:
        if any(_overlap(tr["bbox"], o["bbox"]) > 0.002 for o in out):
            continue
        out.append(tr)
        if len(out) >= limit: break
    return out


def _draw_state(width: int, height: int, tracks: list[dict], out_png: Path) -> None:
    im = Image.new("RGBA", (width, height), (0,0,0,0)); draw = ImageDraw.Draw(im)
    for tr in tracks:
        x1,y1,x2,y2 = tr["bbox"]
        px1, py1, px2, py2 = int(x1*width), int(y1*height), int(x2*width), int(y2*height)
        bw, bh = max(60, px2-px1), max(28, py2-py1)
        pad = max(5, int(height*0.006))
        # Allow Vietnamese to grow around the original text region, but keep it local.
        target_w = min(int(width*0.82), max(bw + 2*pad, int(width*0.20)))
        font_size = max(18, min(int(height*0.034), int(bh*0.75) if bh > 30 else int(height*0.026)))
        font = _font(font_size)
        lines = _wrap(draw, str(tr["vi"]), font, target_w - 2*pad)
        line_h = int(font_size*1.23)
        target_h = max(bh + 2*pad, line_h*len(lines) + 2*pad)
        left = max(6, min(px1-pad, width-target_w-6)); top = max(6, min(py1-pad, height-target_h-6))
        right, bottom = left+target_w, top+target_h
        draw.rounded_rectangle((left,top,right,bottom), radius=max(6,int(font_size*0.28)), fill=(10,10,10,220))
        ty = top + max(pad, (target_h-line_h*len(lines))//2)
        for line in lines:
            tw = draw.textbbox((0,0), line, font=font)[2]
            tx = left + max(pad, (target_w-tw)//2)
            draw.text((tx,ty), line, font=font, fill=(255,255,255,255), stroke_width=max(1,font_size//18), stroke_fill=(0,0,0,255))
            ty += line_h
    im.save(out_png)


def build_overlay(source: str | Path, tracks: list[dict], out_mov: str | Path, *, limit: int = 2, progress: Callable[[str,float],None] | None = None) -> dict:
    out_mov = Path(out_mov); info = media_info(source); width,height = info["width"],info["height"]; duration=info["duration"]
    relevant = [t for t in tracks if t.get("action") == "translate" and t.get("vi")]
    if not relevant:
        meta = {"empty": True, "path": "", "states": 0}
        (out_mov.parent/"overlay_meta.json").write_text(json.dumps(meta,ensure_ascii=False,indent=2),"utf-8")
        return meta
    times = {0.0, duration}
    for tr in relevant:
        times.add(max(0.0,float(tr["start"]))); times.add(min(duration,float(tr["end"])))
    times = sorted(t for t in times if 0 <= t <= duration)
    state_dir = out_mov.parent / "overlay_states"; state_dir.mkdir(exist_ok=True)
    concat = out_mov.parent / "overlay_concat.txt"; lines=[]; state_count=0
    last_sig = None; last_path = None; pending_duration=0.0
    states=[]
    for i in range(len(times)-1):
        a,b=times[i],times[i+1]
        if b-a < 0.02: continue
        active=_choose_active(relevant,(a+b)/2,limit)
        sig=tuple((x["id"],x.get("vi")) for x in active)
        if sig==last_sig and states:
            states[-1]["duration"] += b-a
            continue
        p=state_dir/f"state_{state_count:04d}.png"; _draw_state(width,height,active,p)
        states.append({"path":p,"duration":b-a}); state_count+=1; last_sig=sig
    for s in states:
        escaped=str(s["path"]).replace("'","'\\''")
        lines += [f"file '{escaped}'", f"duration {s['duration']:.6f}"]
    if states:
        escaped=str(states[-1]["path"]).replace("'","'\\''"); lines.append(f"file '{escaped}'")
    concat.write_text("\n".join(lines)+"\n","utf-8")
    if progress: progress(f"Đang dựng overlay video từ {len(states)} trạng thái chữ…",0.35)
    run(["ffmpeg","-y","-f","concat","-safe","0","-i",str(concat),"-vsync","vfr","-c:v","qtrle","-pix_fmt","argb",str(out_mov)])
    meta={"empty":False,"path":str(out_mov),"states":len(states)}
    (out_mov.parent/"overlay_meta.json").write_text(json.dumps(meta,ensure_ascii=False,indent=2),"utf-8")
    if progress: progress(f"Overlay sẵn sàng · {len(states)} trạng thái",0.98)
    return meta


def _video_encoder() -> list[str]:
    encoders = run(["ffmpeg","-hide_banner","-encoders"],check=False).stdout + run(["ffmpeg","-hide_banner","-encoders"],check=False).stderr
    if platform.system()=="Darwin" and "h264_videotoolbox" in encoders:
        return ["-c:v","h264_videotoolbox","-b:v","8M","-allow_sw","1"]
    return ["-c:v","libx264","-preset","veryfast","-crf","18"]


def render_full(source: str | Path, voice_wav: str | Path, overlay_meta: dict, out_mp4: str | Path, *, original_volume: float = 0.12, progress: Callable[[str,float],None] | None = None) -> Path:
    source=Path(source); out_mp4=Path(out_mp4); folder=out_mp4.parent
    video_stage=folder/"render_video.mp4"; audio_stage=folder/"render_audio.m4a"
    if progress: progress("VIDEO 1/3 · giữ nguyên resolution/FPS nguồn",0.08)
    if overlay_meta.get("empty"):
        run(["ffmpeg","-y","-i",str(source),"-map","0:v:0","-an","-c:v","copy",str(video_stage)])
    else:
        run(["ffmpeg","-y","-i",str(source),"-i",str(overlay_meta["path"]),"-filter_complex","[0:v][1:v]overlay=0:0:shortest=1[v]","-map","[v]","-an",*_video_encoder(),"-pix_fmt","yuv420p",str(video_stage)])
    info=media_info(source)
    if progress: progress("AUDIO 2/3 · mix voice Việt + nền gốc",0.56)
    if info["has_audio"]:
        run(["ffmpeg","-y","-i",str(source),"-i",str(voice_wav),"-filter_complex",f"[0:a]volume={max(0,min(1,original_volume)):.3f}[bg];[bg][1:a]amix=inputs=2:duration=first:dropout_transition=0[a]","-map","[a]","-c:a","aac","-b:a","192k",str(audio_stage)])
    else:
        run(["ffmpeg","-y","-i",str(voice_wav),"-c:a","aac","-b:a","192k",str(audio_stage)])
    if progress: progress("MUX 3/3 · đóng gói MP4",0.88)
    run(["ffmpeg","-y","-i",str(video_stage),"-i",str(audio_stage),"-map","0:v:0","-map","1:a:0","-c","copy","-movflags","+faststart","-shortest",str(out_mp4)])
    if progress: progress("Đã render xong full video",1.0)
    return out_mp4
