"""NEIS API 클라이언트 (원본 tt.py 이식, streamlit 제거)."""
from __future__ import annotations

import hashlib
import os
import re
import time
from datetime import date, datetime, timedelta

try:
    import pandas as pd
    HAS_PANDAS = True
except Exception:  # pragma: no cover
    pd = None  # type: ignore
    HAS_PANDAS = False

try:
    import requests
    HAS_REQUESTS = True
except Exception:  # pragma: no cover
    requests = None  # type: ignore
    HAS_REQUESTS = False

from . import config as C

_schedule_cache: dict = {}
_school_cache: dict = {}


def get_api_key(explicit: str = "") -> str:
    if explicit and str(explicit).strip():
        return str(explicit).strip()
    return (os.getenv("NEIS_API_KEY", "") or "").strip()


def _api_get(endpoint: str, params: dict, timeout: int = 12):
    if not HAS_REQUESTS:
        raise RuntimeError("requests 미설치")
    resp = requests.get(endpoint, params=params, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    if isinstance(data, dict) and "RESULT" in data:
        result = data.get("RESULT") or {}
        code = str(result.get("CODE", "")).strip()
        if code and code != "INFO-000":
            raise RuntimeError(f"NEIS API {code}: {result.get('MESSAGE', '')}")
    return data


def _rows(data, root_key: str):
    if not isinstance(data, dict):
        return []
    blocks = data.get(root_key, [])
    if not isinstance(blocks, list):
        return []
    for block in blocks:
        if isinstance(block, dict) and isinstance(block.get("row"), list):
            return block["row"]
    return []


def _normalize_school(name: str) -> str:
    return re.sub(r"\s+", "", str(name or "").strip())


def _is_info_200(exc) -> bool:
    return "INFO-200" in str(exc or "").upper()


def find_school(api_key: str, school_name: str):
    """schoolInfo 자동검색(17교육청) + fallback."""
    api_key = str(api_key or "").strip()
    target = _normalize_school(school_name)
    if not api_key or not target:
        return None
    cache_key = hashlib.sha256(f"{api_key}:{target}".encode()).hexdigest()
    now = time.time()
    hit = _school_cache.get(cache_key)
    if hit and now - hit[0] < C.NEIS_SCHOOL_CACHE_TTL:
        return hit[1]
    fallback = C.NEIS_SCHOOL_CODE_FALLBACKS.get(str(school_name).strip())
    if fallback:
        res = {
            "ATPT_OFCDC_SC_CODE": fallback["ATPT_OFCDC_SC_CODE"],
            "SD_SCHUL_CODE": fallback["SD_SCHUL_CODE"],
            "SCHUL_NM": str(school_name).strip(),
            "ATPT_OFCDC_SC_NM": "경상북도교육청",
        }
        _school_cache[cache_key] = (now, res)
        return res
    exact = []
    for office in C.NEIS_EDU_OFFICE_CODES:
        try:
            data = _api_get(C.NEIS_SCHOOL_INFO_ENDPOINT, {
                "KEY": api_key, "Type": "json", "pIndex": 1, "pSize": 100,
                "ATPT_OFCDC_SC_CODE": office, "SCHUL_NM": school_name,
            })
            for row in _rows(data, "schoolInfo"):
                if _normalize_school(row.get("SCHUL_NM", "")) == target:
                    exact.append(row)
        except Exception:
            continue
    if not exact:
        if fallback:
            res = {
                "ATPT_OFCDC_SC_CODE": fallback["ATPT_OFCDC_SC_CODE"],
                "SD_SCHUL_CODE": fallback["SD_SCHUL_CODE"],
                "SCHUL_NM": str(school_name).strip(),
                "ATPT_OFCDC_SC_NM": "경상북도교육청",
            }
            _school_cache[cache_key] = (now, res)
            return res
        return None
    row = exact[0]
    res = {
        "ATPT_OFCDC_SC_CODE": str(row.get("ATPT_OFCDC_SC_CODE", "")).strip(),
        "SD_SCHUL_CODE": str(row.get("SD_SCHUL_CODE", "")).strip(),
        "SCHUL_NM": str(row.get("SCHUL_NM", school_name)).strip(),
        "ATPT_OFCDC_SC_NM": str(row.get("ATPT_OFCDC_SC_NM", "")).strip(),
    }
    _school_cache[cache_key] = (now, res)
    return res


def _schedule_request(api_key, school, *, ymd=None, from_ymd=None, to_ymd=None):
    params = {
        "KEY": api_key, "Type": "json", "pIndex": 1, "pSize": 100,
        "ATPT_OFCDC_SC_CODE": school["ATPT_OFCDC_SC_CODE"],
        "SD_SCHUL_CODE": school["SD_SCHUL_CODE"],
    }
    if ymd:
        params["AA_FROM_YMD"] = ymd
        params["AA_TO_YMD"] = ymd
    else:
        params["AA_FROM_YMD"] = from_ymd
        params["AA_TO_YMD"] = to_ymd
    return _api_get(C.NEIS_SCHEDULE_ENDPOINT, params)


def _empty_df():
    if not HAS_PANDAS:
        return []
    return pd.DataFrame(columns=["일자", "명칭", "구분", "내용", "비수업일"])


def _rows_to_df(raw_rows):
    if not HAS_PANDAS:
        return []
    rows = []
    for raw in raw_rows or []:
        if not isinstance(raw, dict):
            continue
        ds = str(raw.get("AA_YMD", "") or "").strip()
        # AA_YMD는 YYYYMMDD
        if len(ds) == 8 and ds.isdigit():
            ds = f"{ds[:4]}-{ds[4:6]}-{ds[6:8]}"
        if not ds:
            continue
        rows.append({
            "일자": ds,
            "명칭": _event_label(raw),
            "구분": str(raw.get("SBTR_DD_SC_NM", "") or "").strip(),
            "내용": str(raw.get("EVENT_CNTNT", "") or "").strip(),
            "비수업일": bool(_row_is_non_instructional(raw)),
        })
    if not rows:
        return _empty_df()
    df = pd.DataFrame(rows).drop_duplicates(subset=["일자", "명칭", "구분", "내용"]).sort_values(["일자", "명칭"])
    df["비수업일"] = df.groupby("일자")["비수업일"].transform("any")
    return df.reset_index(drop=True)


def _row_is_non_instructional(row: dict) -> bool:
    if not isinstance(row, dict):
        return False
    sbtr = str(row.get("SBTR_DD_SC_NM", "") or "").strip()
    event = str(row.get("EVENT_NM", "") or "").strip()
    content = str(row.get("EVENT_CNTNT", "") or "").strip()
    combined = " ".join(x for x in (sbtr, event, content) if x)
    if any(t in combined for t in C.NEIS_NON_INSTRUCTIONAL_TYPES):
        return True
    if any(t in sbtr for t in ("공휴일", "휴업", "휴일", "방학")):
        return True
    return False


def _event_label(row: dict) -> str:
    sbtr = str(row.get("SBTR_DD_SC_NM", "") or "").strip()
    event = str(row.get("EVENT_NM", "") or "").strip()
    content = str(row.get("EVENT_CNTNT", "") or "").strip()
    if event and sbtr and sbtr not in event:
        return f"{event} · {sbtr}"
    return event or sbtr or content or "학사일정"


def fetch_schedule(api_key: str, school_name: str, from_ymd: str, to_ymd: str):
    """월단위/주간 조회. INFO-200 빈결과 처리 + TTL 캐시."""
    api_key = str(api_key or "").strip()
    if not HAS_PANDAS:
        return []
    # TTL 캐시
    cache_key = f"{school_name}|{from_ymd}|{to_ymd}|{hashlib.sha256(api_key.encode()).hexdigest()[:12]}"
    now = time.time()
    hit = _schedule_cache.get(cache_key)
    if hit and now - hit[0] < C.NEIS_SCHEDULE_CACHE_TTL:
        return hit[1].copy(deep=True)
    start = str(from_ymd).replace("-", "")
    end = str(to_ymd).replace("-", "")
    if not api_key or not start or not end or start > end:
        return _empty_df()
    school = find_school(api_key, school_name)
    if not school or not school.get("ATPT_OFCDC_SC_CODE") or not school.get("SD_SCHUL_CODE"):
        return _empty_df()
    try:
        data = _schedule_request(api_key, school, from_ymd=start, to_ymd=end)
        df = _rows_to_df(_rows(data, "SchoolSchedule"))
        _schedule_cache[cache_key] = (now, df.copy(deep=True))
        return df
    except Exception as exc:
        if not _is_info_200(exc):
            raise
    # fallback: 날짜별 재조회
    try:
        sd = date(int(start[:4]), int(start[4:6]), int(start[6:8]))
        ed = date(int(end[:4]), int(end[4:6]), int(end[6:8]))
    except Exception:
        return _empty_df()
    all_rows = []
    cur = sd
    while cur <= ed:
        ymd = cur.strftime("%Y%m%d")
        try:
            data = _schedule_request(api_key, school, ymd=ymd)
            all_rows.extend(_rows(data, "SchoolSchedule"))
        except Exception as exc2:
            if _is_info_200(exc2):
                pass
            else:
                raise
        cur += timedelta(days=1)
    df = _rows_to_df(all_rows)
    _schedule_cache[cache_key] = (now, df.copy(deep=True) if HAS_PANDAS else df)
    return df


def non_instructional_dates(df) -> set:
    if not HAS_PANDAS or df is None or getattr(df, "empty", True):
        return set()
    try:
        return set(df[df["비수업일"] == True]["일자"].astype(str).tolist())  # noqa: E712
    except Exception:
        return set()
