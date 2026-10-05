"""Gemini 호출 (원본 _salary_analyze_uploaded_file 이식)."""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path

try:
    import requests
    HAS_REQUESTS = True
except Exception:  # pragma: no cover
    requests = None  # type: ignore
    HAS_REQUESTS = False

from .config import SALARY_GEMINI_PROMPT

MAX_BYTES = 50 * 1024 * 1024


def get_config(explicit_key: str = "", explicit_model: str = ""):
    api_key = (explicit_key or os.getenv("GEMINI_API_KEY", "") or "").strip()
    model = (explicit_model or os.getenv("GEMINI_MODEL", "") or "gemini-2.0-flash").strip() or "gemini-2.0-flash"
    # 구 모델명 호환: 2.5-flash 요청이 와도 동작하도록 유지하되 기본은 2.0-flash
    return api_key, model


def _clean_ai_json(raw_text: str):
    text = str(raw_text or "").strip()
    # 코드블록 제거
    if text.startswith("```"):
        lines = text.splitlines()
        # 첫/마지막 fence 제거
        lines = [ln for ln in lines if not ln.strip().startswith("```")]
        text = "\n".join(lines).strip()
    # 앞뒤 잡음 제거: 첫 { ~ 마지막 } 추출
    s, e = text.find("{"), text.rfind("}")
    if s >= 0 and e > s:
        text = text[s:e + 1]
    return json.loads(text)


def analyze_file(raw: bytes, filename: str = "", mime_type: str = "",
                 api_key: str = "", model: str = "") -> dict:
    api_key, model = get_config(api_key, model)
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY가 없습니다. .env에 설정해 주세요.")
    if not raw:
        raise ValueError("업로드된 파일이 비어 있습니다.")
    if len(raw) > MAX_BYTES:
        raise ValueError("PDF/이미지 파일은 50MB 이하로 사용해 주세요.")
    if not mime_type:
        suffix = Path(filename or "").suffix.lower()
        mime_type = "application/pdf" if suffix == ".pdf" else "image/jpeg"
    if not HAS_REQUESTS:
        raise RuntimeError("requests 미설치")
    encoded = base64.b64encode(raw).decode("utf-8")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    payload = {
        "contents": [{
            "parts": [
                {"inlineData": {"mimeType": mime_type, "data": encoded}},
                {"text": SALARY_GEMINI_PROMPT},
            ]
        }],
        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.1},
    }
    resp = requests.post(url, params={"key": api_key}, json=payload, timeout=90)
    if resp.status_code >= 400:
        try:
            detail = resp.json().get("error", {}).get("message", resp.text)
        except Exception:
            detail = resp.text
        raise RuntimeError(f"Gemini API 오류 ({resp.status_code}): {detail}")
    try:
        data = resp.json()
        ai_text = data["candidates"][0]["content"]["parts"][0]["text"]
        return _clean_ai_json(ai_text)
    except Exception as exc:
        raise RuntimeError(f"Gemini 응답을 JSON으로 해석하지 못했습니다: {exc}") from exc
