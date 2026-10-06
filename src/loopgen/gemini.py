from __future__ import annotations

import json
import re
from typing import Any

import requests


def _extract_json(text: str) -> Any:
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except Exception:
        a = text.find("[")
        b = text.rfind("]")
        if a >= 0 and b > a:
            return json.loads(text[a:b + 1])
        a = text.find("{")
        b = text.rfind("}")
        if a >= 0 and b > a:
            return json.loads(text[a:b + 1])
        raise


def generate_json(api_key: str, model: str, prompt: str, *, timeout: int = 120) -> Any:
    if not api_key:
        raise RuntimeError("Chưa có Gemini API key. Mở Cài đặt và nhập key.")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.1, "responseMimeType": "application/json"},
    }
    r = requests.post(url, json=payload, timeout=timeout)
    if r.status_code == 429:
        raise RuntimeError("Gemini đang hết quota (HTTP 429). Hãy đổi key/quota rồi bấm chạy tiếp.")
    if not r.ok:
        raise RuntimeError(f"Gemini HTTP {r.status_code}: {r.text[:800]}")
    data = r.json()
    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"]
    except Exception as exc:
        raise RuntimeError(f"Gemini response không hợp lệ: {data}") from exc
    return _extract_json(text)
