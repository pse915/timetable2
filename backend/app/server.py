"""단일 모듈 서버 (store + logic + neis + salary_ai + main 병합). config.py는 별도 유지."""
from __future__ import annotations

import base64
import copy
import hashlib
import html as html_lib
import io
import json
import math
import os
import re
import threading
import time
import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel

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


def _empty_df(columns=None):
    """store._empty_df(columns) + neis._empty_df() 통합. 인자 없으면 NEIS 스케줄 컬럼."""
    if not HAS_PANDAS:
        return []
    if columns is None:
        columns = ["일자", "명칭", "구분", "내용", "비수업일"]
    return pd.DataFrame(columns=list(columns))


def _now_text(fmt="%Y-%m-%d %H:%M:%S"):
    try:
        return datetime.now(KST).strftime(fmt)
    except Exception:
        return datetime.now().strftime(fmt)

# ===== store =====
EMPTY_TABLES = [
    "teachers", "timetable", "absences", "subs", "swaps", "test_swaps",
    "part_time", "cumulative", "duties", "budget", "ids", "id_requests",
    "swap_requests",
]

TIMETABLE_COLS = ["교사명", "요일", "교시", "과목", "학급", "과목군"]
TEACHER_COLS = ["교사명", "담당과목"]
ABSENCE_COLS = ["결강ID", "일자", "요일", "교시", "학급", "과목", "교사명", "사유", "상세사유", "등록시각", "입력자"]
SUB_COLS = ["결강ID", "일자", "요일", "교시", "학급", "과목", "결강교사", "보강교사", "배정방식", "우선순위", "비고", "등록시각", "입력자"]
SWAP_COLS = [
    "변경ID", "원본교사A", "실제원본일자A", "실제원본교시A",
    "원본교사B", "실제원본일자B", "실제원본교시B",
    "원본일자", "교사A", "요일A", "교시A", "학급A", "과목A",
    "목표일자", "교사B", "요일B", "교시B", "학급B", "과목B",
    "유형", "시간강사구인", "등록시각", "입력자",
]
BUDGET_COLS = ["일시", "내용", "변동금액", "잔액"]






def _get_gspread_client():
    try:
        import gspread  # type: ignore
        from google.oauth2.service_account import Credentials  # type: ignore
    except Exception as exc:
        return None, f"gspread/google-auth 미설치: {exc}"
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    json_path = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    inline = os.getenv("GOOGLE_SERVICE_ACCOUNT_INFO", "").strip()
    try:
        if json_path and os.path.exists(json_path):
            creds = Credentials.from_service_account_file(json_path, scopes=scopes)
        elif os.getenv("gcp_service_account"):
            import json as _json
            info = _json.loads(os.environ["gcp_service_account"])
            creds = Credentials.from_service_account_info(info, scopes=scopes)
        elif inline:
            import json as _json
            info = _json.loads(inline)
            creds = Credentials.from_service_account_info(info, scopes=scopes)
        else:
            # Streamlit secrets 파일 경로 호환
            for cand in ("./service-account.json", "service-account.json"):
                if os.path.exists(cand):
                    creds = Credentials.from_service_account_file(cand, scopes=scopes)
                    break
            else:
                return None, "GOOGLE_SERVICE_ACCOUNT_JSON 미설정 (시트 동기화 비활성, 인메모리 모드)"
        client = gspread.authorize(creds)
        return client, ""
    except Exception as exc:
        return None, f"구글 인증 실패: {exc}"


class Store:
    def __init__(self):
        self._lock = threading.RLock()
        self.tables: dict = {}
        for name in EMPTY_TABLES:
            self.tables[name] = _empty_df(self._cols_for(name))
        # 예산 초기 잔액 행
        if HAS_PANDAS and self.tables["budget"].empty:
            self.tables["budget"] = pd.DataFrame([{
                "일시": _now_text(), "내용": "초기 예산", "변동금액": 0, "잔액": C.BUDGET_INIT,
            }])
        self.version = 0
        self.history: list = []
        self.history_index = -1
        self._effective_cache: dict = {}
        self.last_error = ""
        self._gsheet_error = ""

    def _cols_for(self, name):
        return {
            "teachers": TEACHER_COLS,
            "timetable": TIMETABLE_COLS,
            "absences": ABSENCE_COLS,
            "subs": SUB_COLS,
            "swaps": SWAP_COLS,
            "test_swaps": SWAP_COLS,
            "duties": list(C.DUTY_COLS),
            "budget": BUDGET_COLS,
        }.get(name, [])

    # ---- basic ----
    def get(self, name):
        with self._lock:
            v = self.tables.get(name)
            if HAS_PANDAS and isinstance(v, pd.DataFrame):
                return v.copy(deep=True)
            return copy.deepcopy(v)

    def set(self, name, df):
        with self._lock:
            self.tables[name] = df
            self.bump()

    def bump(self):
        with self._lock:
            self.version += 1
            self._effective_cache.clear()

    def get_version(self):
        with self._lock:
            return self.version

    # ---- effective cache ----
    def effective_get(self, key):
        with self._lock:
            return self._effective_cache.get(key)

    def effective_set(self, key, value):
        with self._lock:
            self._effective_cache[key] = value
            if len(self._effective_cache) > 40:
                for k in list(self._effective_cache.keys())[:-40]:
                    self._effective_cache.pop(k, None)

    def invalidate(self):
        with self._lock:
            self.version += 1
            self._effective_cache.clear()

    # ---- history ----
    def snapshot(self, action="작업"):
        with self._lock:
            snap = {
                "action": action,
                "time": _now_text(),
            }
            for k in ("absences", "subs", "swaps", "test_swaps", "part_time", "duties", "budget"):
                v = self.tables.get(k)
                if HAS_PANDAS and isinstance(v, pd.DataFrame):
                    snap[k] = v.copy(deep=True)
                else:
                    snap[k] = copy.deepcopy(v)
            # 중복 스냅샷 방지(간단 비교: 길이)
            self.history = self.history[: self.history_index + 1]
            self.history.append(snap)
            self.history_index = len(self.history) - 1
            if len(self.history) > C.MAX_HISTORY:
                self.history.pop(0)
                self.history_index -= 1
            return True

    def push_history(self, action="작업"):
        return self.snapshot(action)

    def undo(self):
        with self._lock:
            if self.history_index <= 0:
                return False
            self.history_index -= 1
            self._restore(self.history[self.history_index])
            return True

    def redo(self):
        with self._lock:
            if self.history_index >= len(self.history) - 1:
                return False
            self.history_index += 1
            self._restore(self.history[self.history_index])
            return True

    def _restore(self, snap):
        for k in ("absences", "subs", "swaps", "test_swaps", "part_time", "duties", "budget"):
            v = snap.get(k)
            if HAS_PANDAS and isinstance(v, pd.DataFrame):
                self.tables[k] = v.copy(deep=True)
            else:
                self.tables[k] = copy.deepcopy(v)
        self.version += 1
        self._effective_cache.clear()

    # ---- gsheet sync ----
    def _df_from_worksheet(self, ws):
        if not HAS_PANDAS:
            return []
        try:
            values = ws.get_all_values()
        except Exception as exc:
            self._gsheet_error = str(exc)
            return pd.DataFrame()
        if not values:
            return pd.DataFrame()
        header = [str(h).strip() for h in values[0]]
        rows = values[1:]
        # 빈 행 제거
        rows = [r for r in rows if any(str(c).strip() for c in r)]
        df = pd.DataFrame(rows, columns=header) if rows else pd.DataFrame(columns=header)
        return df

    def _df_to_worksheet(self, ws, df):
        try:
            ws.clear()
            if df is None or (HAS_PANDAS and df.empty and len(getattr(df, "columns", [])) == 0):
                return True
            if HAS_PANDAS:
                data = [list(map(str, df.columns))] + df.fillna("").astype(str).values.tolist()
            else:
                data = [list(df[0].keys())] + [list(map(str, r.values())) for r in df] if df else [[]]
            ws.update(data)
            return True
        except Exception as exc:
            self.last_error = str(exc)
            return False

    def load_timetable(self):
        """시간표 시트 로드. gspread 없으면 빈 DF + 에러메시지."""
        client, err = _get_gspread_client()
        if client is None:
            self._gsheet_error = err
            return {"ok": False, "error": err}
        try:
            sh = client.open_by_key(C.TIMETABLE_SHEET_ID)
            ti = self._df_from_worksheet(sh.worksheet("교사정보"))
            tt = self._df_from_worksheet(sh.worksheet("시간표"))
            with self._lock:
                self.tables["teachers"] = ti
                self.tables["timetable"] = tt
                self.version += 1
                self._effective_cache.clear()
            return {"ok": True, "error": ""}
        except Exception as exc:
            self._gsheet_error = str(exc)
            return {"ok": False, "error": str(exc)}

    def load_work(self):
        client, err = _get_gspread_client()
        if client is None:
            self._gsheet_error = err
            return {"ok": False, "error": err}
        try:
            sh = client.open_by_key(C.WORK_SHEET_ID)
            names = ["결강", "보강", "맞교환", "시간강사", "누적보강", "복무", "예산",
                     "아이디저장함", "아이디추가요청", "수업교체신청"]
            got = {}
            for n in names:
                try:
                    got[n] = self._df_from_worksheet(sh.worksheet(n))
                except Exception:
                    got[n] = _empty_df([])
            mapping = {
                "결강": "absences", "보강": "subs", "맞교환": "swaps",
                "시간강사": "part_time", "누적보강": "cumulative", "복무": "duties",
                "예산": "budget", "아이디저장함": "ids", "아이디추가요청": "id_requests",
                "수업교체신청": "swap_requests",
            }
            with self._lock:
                for sheet_name, store_key in mapping.items():
                    self.tables[store_key] = got.get(sheet_name)
                self.version += 1
                self._effective_cache.clear()
            return {"ok": True, "error": ""}
        except Exception as exc:
            self._gsheet_error = str(exc)
            return {"ok": False, "error": str(exc)}

    def save(self, changed_sheets=None):
        client, err = _get_gspread_client()
        if client is None:
            # 인메모리만 유지, 프론트 크래시 방지
            self._gsheet_error = err
            return {"ok": True, "warn": err}
        try:
            sh = client.open_by_key(C.WORK_SHEET_ID)
            mapping = {
                "absences": "결강", "subs": "보강", "swaps": "맞교환",
                "part_time": "시간강사", "duties": "복무", "budget": "예산",
                "ids": "아이디저장함", "id_requests": "아이디추가요청",
                "swap_requests": "수업교체신청",
            }
            keys = list(mapping.keys()) if not changed_sheets else [
                k for k, v in {"결강": "absences", "보강": "subs", "맞교환": "swaps",
                             "시간강사": "part_time", "복무": "duties", "예산": "budget",
                             "아이디저장함": "ids"}.items() if k in (changed_sheets or [])
                for k in [v]
            ]
            with self._lock:
                for k in keys:
                    if k not in mapping:
                        continue
                    try:
                        ws = sh.worksheet(mapping[k])
                    except Exception:
                        ws = sh.add_worksheet(title=mapping[k], rows=100, cols=20)
                    self._df_to_worksheet(ws, self.tables.get(k))
            return {"ok": True, "error": ""}
        except Exception as exc:
            self.last_error = str(exc)
            return {"ok": False, "error": str(exc)}


store = Store()


# 모듈 레벨 헬퍼 (logic/main에서 사용)
def get_table(name):
    return store.get(name)


def set_table(name, df):
    store.set(name, df)


def get_version():
    return store.get_version()


def push_history(action="작업"):
    return store.push_history(action)


def undo():
    return store.undo()


def redo():
    return store.redo()


def load_timetable():
    return store.load_timetable()


def load_work():
    return store.load_work()


def save(changed=None):
    return store.save(changed)

# ===== logic =====
KST = ZoneInfo("Asia/Seoul")
_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# ---------------------------------------------------------------- utils

def _today_kst() -> date:
    try:
        return datetime.now(KST).date()
    except Exception:
        return date.today()




def _new_change_id(prefix="CHG"):
    return f"{prefix}-{datetime.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"


def safe_int(val, default=0):
    try:
        if HAS_PANDAS and pd.isna(val):  # type: ignore
            return default
        if val is None or str(val).strip() in ("", "nan", "None"):
            return default
        return int(float(str(val).strip()))
    except Exception:
        return default


def normalize_date_str(d_str):
    if d_str is None or (isinstance(d_str, str) and not d_str.strip()):
        return ""
    try:
        if HAS_PANDAS and pd.isna(d_str):  # type: ignore
            return ""
    except Exception:
        pass
    if isinstance(d_str, (date, datetime)):
        try:
            return d_str.strftime("%Y-%m-%d")
        except Exception:
            return ""
    text = str(d_str).strip()
    if text.lower() in ("", "nan", "none", "nat"):
        return ""
    if _ISO_RE.fullmatch(text):
        try:
            date.fromisoformat(text)
            return text
        except ValueError:
            pass
    if HAS_PANDAS:
        try:
            v = pd.to_datetime(text, errors="coerce")
            if pd.isna(v):  # type: ignore
                return text
            return v.strftime("%Y-%m-%d")
        except Exception:
            return text
    # pandas 없으면 ISO만 인정
    return text if _ISO_RE.fullmatch(text) else ""


@lru_cache(maxsize=512)
def subject_group(subject: str) -> str:
    if not isinstance(subject, str) or not subject.strip():
        return ""
    s = subject.strip()
    return C.SUBJECT_GROUP.get(s, s.rstrip("0123456789"))


@lru_cache(maxsize=512)
def grade_of(class_name: str) -> str:
    if isinstance(class_name, str) and "-" in class_name:
        return class_name.split("-", 1)[0]
    return ""


def normalized_grade(class_name: str):
    text = str(class_name or "").strip()
    m = re.match(r"^\s*([1-3])\s*[-_./ ]", text)
    if m:
        return m.group(1)
    g = grade_of(text)
    return g if g in {"1", "2", "3"} else ""


def is_grade12_thursday_7_forbidden(class_name: str, day: str, period: int) -> bool:
    return str(day or "").strip() == "목" and safe_int(period) == 7 and normalized_grade(class_name) in {"1", "2"}


def slot_allowed_for_class(class_name: str, day: str, period: int) -> bool:
    return not is_grade12_thursday_7_forbidden(class_name, day, period)


def format_periods(periods):
    normalized = [safe_int(p) for p in (periods or [])]
    uniq = sorted({p for p in normalized if p >= 0})
    if not uniq:
        return ""
    if 0 in uniq:
        return "전체"
    if len(uniq) == 1:
        return f"{uniq[0]}교시"
    ranges = []
    start = prev = uniq[0]
    for p in uniq[1:]:
        if p == prev + 1:
            prev = p
        else:
            ranges.append(f"{start}~{prev}교시" if start != prev else f"{start}교시")
            start = prev = p
    ranges.append(f"{start}~{prev}교시" if start != prev else f"{start}교시")
    return ", ".join(ranges)


def _lesson_record(teacher, day, period, subject, class_name, *, orig_teacher=None,
                   orig_date="", orig_period=0, change_type="원본", change_source="",
                   change_id="", change_detail=""):
    return {
        "교사명": str(teacher).strip(), "요일": day, "교시": safe_int(period),
        "과목": str(subject).strip(), "학급": str(class_name).strip(),
        "과목군": subject_group(str(subject).strip()),
        "원본교사": str(orig_teacher if orig_teacher is not None else teacher).strip(),
        "원본일자": normalize_date_str(orig_date), "원본교시": safe_int(orig_period or period),
        "변경유형": change_type, "변경출처": str(change_source).strip(),
        "변경ID": str(change_id).strip(), "변경상세": str(change_detail).strip(),
    }


# ------------------------------------------------- availability / duty

def _truthy_availability(value):
    if value is None:
        return False
    try:
        if HAS_PANDAS and pd.isna(value):  # type: ignore
            return False
    except Exception:
        pass
    s = str(value).strip().lower()
    return s not in {"", "nan", "none", "0", "x", "n", "no", "불가", "아니오", "×"}


def _part_time_available(prow, day, period):
    col = f"{day}{safe_int(period)}"
    try:
        if HAS_PANDAS and isinstance(prow, pd.Series):
            return col in prow.index and _truthy_availability(prow.get(col, ""))
        if isinstance(prow, dict):
            return _truthy_availability(prow.get(col, ""))
    except Exception:
        return False
    return False


_TEACHER_SLOT_COL_RE = re.compile(r"^(월|화|수|목|금)\s*(?:요일)?\s*[-_/]?\s*(\d{1,2})\s*(?:교시)?$")
_TEACHER_DAY_COL_RE = re.compile(r"^(월|화|수|목|금)(?:요일)?(?:\s|_|-|/)*(?:가능|가능시간|가능시간대|교시|시간)?$")


def _normalize_teacher_col(value):
    return re.sub(r"\s+", "", str(value or "").strip())


def _parse_period_tokens(text):
    result = set()
    for m in re.finditer(r"(\d{1,2})\s*(?:~|\-|–|—)\s*(\d{1,2})", str(text)):
        a, b = safe_int(m.group(1)), safe_int(m.group(2))
        if 1 <= a <= 7 and 1 <= b <= 7:
            lo, hi = sorted((a, b))
            result.update(range(lo, hi + 1))
    for m in re.finditer(r"(?<!\d)([1-7])(?!\d)", str(text)):
        result.add(safe_int(m.group(1)))
    return result


def _parse_teacher_availability_text(text):
    text = str(text or "").strip()
    if not text:
        return set()
    if text.lower() in {"전체", "모두", "전부", "매일", "전일", "all"}:
        return {(d, p) for d in C.DAYS for p in range(1, C.PERIODS_PER_DAY.get(d, C.MAX_PERIOD) + 1)}
    result = set()
    day_pattern = r"(월|화|수|목|금)(?:요일)?"
    matches = list(re.finditer(day_pattern, text))
    if matches:
        for i, m in enumerate(matches):
            day = m.group(1)
            body = text[m.end():matches[i + 1].start() if i + 1 < len(matches) else len(text)]
            for p in _parse_period_tokens(body):
                if p <= C.PERIODS_PER_DAY.get(day, C.MAX_PERIOD):
                    result.add((day, p))
        return result
    return set()


def get_teacher_availability_index(teachers_df=None):
    """{교사명: (configured, frozenset((요일,교시)))}"""
    if not HAS_PANDAS:
        return {}
    ti = teachers_df if teachers_df is not None else get_table("teachers")
    if ti is None or getattr(ti, "empty", True) or "교사명" not in getattr(ti, "columns", []):
        return {}
    columns = {_normalize_teacher_col(c): c for c in ti.columns}
    slot_cols: dict = {}
    day_cols: dict = {}
    for norm_col, original_col in columns.items():
        m = _TEACHER_SLOT_COL_RE.fullmatch(norm_col)
        if m:
            day, p = m.group(1), safe_int(m.group(2))
            if 1 <= p <= C.MAX_PERIOD:
                slot_cols[(day, p)] = original_col
            continue
        m = _TEACHER_DAY_COL_RE.fullmatch(norm_col)
        if m and norm_col[:1] in C.DAYS:
            day_cols[m.group(1)] = original_col
    text_keys = ("가능시간", "가용시간")
    text_cols = []
    for original_col in ti.columns:
        nc = _normalize_teacher_col(original_col)
        if any(k in nc for k in text_keys) and original_col not in text_cols:
            text_cols.append(original_col)
    index: dict = {}
    try:
        records = ti.to_dict("records")
    except Exception:
        records = []
    for row in records:
        teacher = str(row.get("교사명", "")).strip()
        if not teacher:
            continue
        configured = False
        allowed: set = set()
        if slot_cols:
            configured = True
            for slot, col in slot_cols.items():
                if _truthy_availability(row.get(col, "")):
                    allowed.add(slot)
        else:
            for day, col in day_cols.items():
                raw = row.get(col, "")
                if str(raw).strip():
                    configured = True
                    for p in _parse_period_tokens(raw):
                        if p <= C.PERIODS_PER_DAY.get(day, C.MAX_PERIOD):
                            allowed.add((day, p))
            for col in text_cols:
                raw = row.get(col, "")
                if str(raw).strip():
                    configured = True
                    allowed.update(_parse_teacher_availability_text(raw))
        index[teacher] = (configured, frozenset(allowed))
    return index


def teacher_slot_is_available(teacher: str, day: str, period: int, teachers_df=None, availability_index=None):
    teacher = str(teacher or "").strip()
    day = str(day or "").strip()
    p = safe_int(period)
    if not teacher or day not in C.DAYS or p <= 0:
        return False
    idx = availability_index if availability_index is not None else get_teacher_availability_index(teachers_df)
    item = idx.get(teacher)
    if item is None:
        return True
    configured, allowed = item
    return (day, p) in allowed if configured else True


def _duty_index(duties_df=None):
    if not HAS_PANDAS:
        return {}
    duties = duties_df if duties_df is not None else get_table("duties")
    index: dict = defaultdict(set)
    if duties is None or getattr(duties, "empty", True):
        return {}
    cols = {"교사명", "일자", "교시"}
    if not cols.issubset(set(getattr(duties, "columns", []))):
        return {}
    try:
        for r in duties.itertuples(index=False):
            teacher = str(getattr(r, "교사명", "")).strip()
            if not teacher:
                continue
            day = normalize_date_str(getattr(r, "일자", ""))
            pp = safe_int(getattr(r, "교시", 0))
            if day:
                index[teacher].add((day, 0 if pp <= 0 else pp))
    except Exception:
        return {}
    return dict(index)


def has_duty(teacher: str, on_date: str, period: int | None = None, duties_df=None) -> bool:
    norm = normalize_date_str(on_date)
    slots = _duty_index(duties_df).get(str(teacher).strip(), set())
    if not slots or not norm:
        return False
    if period is None:
        return any(d == norm for d, _ in slots)
    p = safe_int(period)
    return (norm, 0) in slots or (norm, p) in slots


def is_free(teacher: str, day: str, period: int, on_date: str | None = None,
            e_tt=None, class_name: str | None = None, duties_df=None) -> bool:
    p = safe_int(period)
    norm = normalize_date_str(on_date) if on_date else ""
    if class_name is not None and not slot_allowed_for_class(class_name, day, p):
        return False
    if norm and has_duty(teacher, norm, p, duties_df):
        return False
    if e_tt is None and norm:
        e_tt = get_effective_timetable_for_date(norm)
    if HAS_PANDAS and e_tt is not None and not getattr(e_tt, "empty", True):
        try:
            if ((e_tt["교사명"] == teacher) & (e_tt["교시"] == p)).any():
                return False
        except Exception:
            pass
    return True


# ------------------------------------------------- stats

def cumulative_sub_count(subs_df=None, teachers_df=None, start_date=None, end_date=None):
    if not HAS_PANDAS:
        return {}
    s = subs_df if subs_df is not None else get_table("subs")
    t = teachers_df if teachers_df is not None else get_table("teachers")
    base: dict = {}
    try:
        if t is not None and not t.empty and "교사명" in t.columns:
            base = {str(x).strip(): 0 for x in t["교사명"].tolist() if str(x).strip()}
    except Exception:
        base = {}
    if s is None or getattr(s, "empty", True) or "보강교사" not in getattr(s, "columns", []):
        return base
    try:
        if start_date and end_date:
            s = s[(s["일자"] >= normalize_date_str(start_date)) & (s["일자"] <= normalize_date_str(end_date))]
        counts = s["보강교사"].value_counts()
        for k, v in counts.items():
            k = str(k).strip()
            if k in base:
                base[k] = int(v)
            else:
                base[k] = int(v)
    except Exception:
        pass
    return base


def weekly_load(timetable_df=None):
    if not HAS_PANDAS:
        return {}
    tt = timetable_df if timetable_df is not None else get_table("timetable")
    if tt is None or getattr(tt, "empty", True):
        return {}
    try:
        return tt["교사명"].value_counts().to_dict()
    except Exception:
        return {}


def get_teacher_subject(teacher_name: str, teachers_df=None) -> str:
    if not HAS_PANDAS:
        return ""
    ti = teachers_df if teachers_df is not None else get_table("teachers")
    try:
        if ti is None or ti.empty:
            return ""
        m = ti[ti["교사명"].astype(str).str.strip() == str(teacher_name).strip()]
        if m.empty:
            return ""
        for col in ("담당과목", "과목", "교과"):
            if col in m.columns:
                return str(m.iloc[0].get(col, "")).strip()
    except Exception:
        return ""
    return ""


def get_all_teacher_names(teachers_df=None, timetable_df=None):
    if not HAS_PANDAS:
        return []
    ti = teachers_df if teachers_df is not None else get_table("teachers")
    tt = timetable_df if timetable_df is not None else get_table("timetable")
    names: set = set()
    try:
        if ti is not None and not ti.empty and "교사명" in ti.columns:
            names.update(str(x).strip() for x in ti["교사명"].tolist() if str(x).strip())
        if tt is not None and not tt.empty and "교사명" in tt.columns:
            names.update(str(x).strip() for x in tt["교사명"].tolist() if str(x).strip())
    except Exception:
        pass
    return sorted(names)


# ------------------------------------------------- effective timetable

def _neis_blocked_dates() -> set:
    """NEIS 비수업일 집합 (키 없으면 빈 집합)."""
    try:
        df = get_table("neis_cache") if "neis_cache" in store.tables else None
        if df is not None and HAS_PANDAS and not df.empty:
            try:
                return set(df[df["비수업일"] == True]["일자"].astype(str).tolist())  # noqa: E712
            except Exception:
                return set()
    except Exception:
        pass
    return set()


def _is_neis_blocked(norm: str, extra: set | None = None) -> bool:
    if extra and norm in extra:
        return True
    try:
        blocked = _neis_blocked_dates()
        return norm in blocked
    except Exception:
        return False


def _build_effective_timetable_for_date(on_date: str, timetable_df=None, swaps_df=None,
                                        test_swaps_df=None, subs_df=None, part_time_df=None,
                                        use_test: bool = False, neis_blocked: set | None = None):
    """원본→맞교환→테스트→보강→시간강사. NEIS휴업일이면 빈DF."""
    if not HAS_PANDAS:
        return []
    norm = normalize_date_str(on_date)
    cols = list(C.EFFECTIVE_COLUMNS)
    if not norm:
        return pd.DataFrame(columns=cols)
    if _is_neis_blocked(norm, neis_blocked):
        return pd.DataFrame(columns=cols)
    try:
        day = C.WEEKDAY_KR[datetime.strptime(norm, "%Y-%m-%d").weekday()]
    except Exception:
        return pd.DataFrame(columns=cols)
    tt = timetable_df if timetable_df is not None else get_table("timetable")
    if tt is None or getattr(tt, "empty", True):
        return pd.DataFrame(columns=cols)
    current: dict = {}
    try:
        base = tt[tt["요일"] == day]
        for r in base.itertuples(index=False):
            p = safe_int(getattr(r, "교시", 0))
            t = str(getattr(r, "교사명", "")).strip()
            if not t or p <= 0:
                continue
            current[(t, p)] = _lesson_record(t, day, p, getattr(r, "과목", ""), getattr(r, "학급", ""),
                                             orig_teacher=t, orig_date=norm, orig_period=p, change_type="원본")
    except Exception:
        pass

    def _is_direct(typ: str) -> bool:
        return str(typ).strip() in ["1:1 맞교환", "1:1맞교환", "직접1:1"]

    def apply_swap_table(swaps, is_test_table=False):
        if swaps is None or getattr(swaps, "empty", True):
            return
        need = {"원본일자", "목표일자"}
        if not need.issubset(set(getattr(swaps, "columns", []))):
            return
        try:
            mask = (swaps["원본일자"] == norm) | (swaps["목표일자"] == norm)
        except Exception:
            return
        try:
            for sw in swaps[mask].itertuples(index=False):
                ta = str(getattr(sw, "교사A", "")).strip()
                tb = str(getattr(sw, "교사B", "")).strip()
                da = normalize_date_str(getattr(sw, "원본일자", ""))
                db = normalize_date_str(getattr(sw, "목표일자", ""))
                pa = safe_int(getattr(sw, "교시A", 0))
                pb = safe_int(getattr(sw, "교시B", 0))
                typ = str(getattr(sw, "유형", "")).strip()
                cid = str(getattr(sw, "변경ID", "")).strip() or ""
                sa = str(getattr(sw, "과목A", "")).strip()
                ca = str(getattr(sw, "학급A", "")).strip()
                sb = str(getattr(sw, "과목B", "")).strip()
                cb = str(getattr(sw, "학급B", "")).strip()
                ctype = "테스트교환" if is_test_table else "교환"
                if _is_direct(typ):
                    if da == db and pa == pb and da == norm:
                        current.pop((ta, pa), None)
                        current.pop((tb, pb), None)
                        current[(tb, pa)] = _lesson_record(tb, day, pa, sa, ca,
                            orig_teacher=str(getattr(sw, "원본교사A", ta)).strip() or ta,
                            orig_date=normalize_date_str(getattr(sw, "실제원본일자A", da)) or da,
                            orig_period=safe_int(getattr(sw, "실제원본교시A", pa)) or pa,
                            change_type=ctype, change_source=f"{ta} ↔ {tb}", change_id=cid,
                            change_detail=f"{da} {pa}교시의 {ta} 수업을 {tb}가 담당")
                        current[(ta, pb)] = _lesson_record(ta, day, pb, sb, cb,
                            orig_teacher=str(getattr(sw, "원본교사B", tb)).strip() or tb,
                            orig_date=normalize_date_str(getattr(sw, "실제원본일자B", db)) or db,
                            orig_period=safe_int(getattr(sw, "실제원본교시B", pb)) or pb,
                            change_type=ctype, change_source=f"{ta} ↔ {tb}", change_id=cid,
                            change_detail=f"{db} {pb}교시의 {tb} 수업을 {ta}가 담당")
                    else:
                        if da == norm:
                            current.pop((ta, pa), None)
                            if tb:
                                current[(tb, pa)] = _lesson_record(tb, day, pa, sa, ca,
                                    orig_teacher=str(getattr(sw, "원본교사A", ta)).strip() or ta,
                                    orig_date=normalize_date_str(getattr(sw, "실제원본일자A", da)) or da,
                                    orig_period=safe_int(getattr(sw, "실제원본교시A", pa)) or pa,
                                    change_type=ctype, change_source=f"{ta} ↔ {tb}", change_id=cid,
                                    change_detail=f"{da} {pa}교시의 {ta} 수업을 {tb}가 담당")
                        if db == norm:
                            current.pop((tb, pb), None)
                            if ta:
                                current[(ta, pb)] = _lesson_record(ta, day, pb, sb, cb,
                                    orig_teacher=str(getattr(sw, "원본교사B", tb)).strip() or tb,
                                    orig_date=normalize_date_str(getattr(sw, "실제원본일자B", db)) or db,
                                    orig_period=safe_int(getattr(sw, "실제원본교시B", pb)) or pb,
                                    change_type=ctype, change_source=f"{ta} ↔ {tb}", change_id=cid,
                                    change_detail=f"{db} {pb}교시의 {tb} 수업을 {ta}가 담당")
                elif "연계" in typ and db == norm and ta:
                    current.pop((tb, pb), None)
                    current[(ta, pb)] = _lesson_record(ta, day, pb, sb, cb,
                        orig_teacher=ta, orig_date=da, orig_period=pa,
                        change_type=ctype, change_source=f"{ta} → {tb}", change_id=cid,
                        change_detail=f"{da} {pa}교시 수업의 연계 이동")
                    if da == norm:
                        current.pop((ta, pa), None)
        except Exception:
            return

    _swaps = swaps_df if swaps_df is not None else get_table("swaps")
    apply_swap_table(_swaps, False)
    if use_test:
        _test = test_swaps_df if test_swaps_df is not None else get_table("test_swaps")
        apply_swap_table(_test, True)

    _subs = subs_df if subs_df is not None else get_table("subs")
    if _subs is not None and not getattr(_subs, "empty", True):
        try:
            for r in _subs[_subs["일자"] == norm].itertuples(index=False):
                p = safe_int(getattr(r, "교시", 0))
                abs_t = str(getattr(r, "결강교사", "")).strip()
                sub_t = str(getattr(r, "보강교사", "")).strip()
                if p <= 0 or not sub_t:
                    continue
                current.pop((abs_t, p), None)
                current.pop((sub_t, p), None)
                current[(sub_t, p)] = _lesson_record(sub_t, day, p, getattr(r, "과목", ""), getattr(r, "학급", ""),
                    orig_teacher=abs_t, orig_date=norm, orig_period=p, change_type="보강",
                    change_source=f"{abs_t} 결강 → {sub_t} 보강",
                    change_id=str(getattr(r, "결강ID", "")).strip() + f"-{p}",
                    change_detail=str(getattr(r, "배정방식", "")).strip())
        except Exception:
            pass

    _pt = part_time_df if part_time_df is not None else get_table("part_time")
    if _pt is not None and not getattr(_pt, "empty", True):
        try:
            for prow in _pt.itertuples(index=False):
                d = prow._asdict()
                start, end = normalize_date_str(d.get("시작일", "")), normalize_date_str(d.get("종료일", ""))
                if not (start and end and start <= norm <= end):
                    continue
                orig = str(d.get("대체교사", "")).strip()
                pt_name = str(d.get("시간강사명", "")).strip()
                if not orig or not pt_name or orig == pt_name:
                    continue
                prow_s = pd.Series(d)
                for (teacher, p), lesson in list(current.items()):
                    if teacher != orig or not _part_time_available(prow_s, day, p):
                        continue
                    current.pop((teacher, p), None)
                    lesson = dict(lesson)
                    lesson["교사명"] = pt_name
                    lesson["원본교사"] = orig
                    lesson["변경유형"] = "시간강사"
                    lesson["변경출처"] = f"{orig} → {pt_name}"
                    lesson["변경ID"] = lesson.get("변경ID") or _new_change_id("PT")
                    lesson["변경상세"] = f"{day}{p} 가능시간에 따른 대체"
                    current[(pt_name, p)] = lesson
        except Exception:
            pass

    df = pd.DataFrame(list(current.values()))
    for c in cols:
        if c not in df.columns:
            df[c] = ""
    return df[cols].reset_index(drop=True)


def get_effective_timetable_for_date(on_date: str, use_test: bool = False, neis_blocked: set | None = None,
                                     timetable_df=None, swaps_df=None, test_swaps_df=None,
                                     subs_df=None, part_time_df=None):
    if not HAS_PANDAS:
        return []
    norm = normalize_date_str(on_date)
    ver = get_version()
    key = f"{norm}:{ver}:{int(bool(use_test))}:{sorted(neis_blocked) if neis_blocked else ''}"
    hit = store.effective_get(key)
    if hit is not None:
        return hit.copy(deep=True)
    result = _build_effective_timetable_for_date(
        norm, timetable_df, swaps_df, test_swaps_df, subs_df, part_time_df,
        use_test=use_test, neis_blocked=neis_blocked)
    store.effective_set(key, result.copy(deep=True))
    return result


def get_effective_week(ref_date: date, use_test: bool = False, neis_blocked: set | None = None):
    if not HAS_PANDAS:
        return {}
    if ref_date is None:
        ref_date = _today_kst()
    if isinstance(ref_date, str):
        try:
            ref_date = date.fromisoformat(normalize_date_str(ref_date))
        except Exception:
            ref_date = _today_kst()
    monday = ref_date - timedelta(days=ref_date.weekday())
    data = {}
    for i, day in enumerate(C.DAYS):
        ds = (monday + timedelta(days=i)).isoformat()
        data[day] = get_effective_timetable_for_date(ds, use_test=use_test, neis_blocked=neis_blocked)
    return data


# ------------------------------------------------- validate

def _direct_swap_affected(swaps_df=None) -> set:
    if not HAS_PANDAS:
        return set()
    swaps = swaps_df if swaps_df is not None else get_table("swaps")
    affected: set = set()
    if swaps is None or getattr(swaps, "empty", True):
        return affected
    try:
        for sw in swaps.itertuples(index=False):
            typ = str(getattr(sw, "유형", "")).strip()
            if typ not in ["1:1 맞교환", "1:1맞교환", "직접1:1"]:
                continue
            da = normalize_date_str(getattr(sw, "원본일자", ""))
            db = normalize_date_str(getattr(sw, "목표일자", ""))
            ta = str(getattr(sw, "교사A", "")).strip()
            tb = str(getattr(sw, "교사B", "")).strip()
            pa = safe_int(getattr(sw, "교시A", 0))
            pb = safe_int(getattr(sw, "교시B", 0))
            if da and ta and pa > 0:
                affected.add((da, ta, pa))
            if db and tb and pb > 0:
                affected.add((db, tb, pb))
            if da == db and pa == pb and da:
                if da and tb and pa > 0:
                    affected.add((da, tb, pa))
                if db and ta and pb > 0:
                    affected.add((db, ta, pb))
    except Exception:
        pass
    return affected


def _test_affected(test_swaps_df=None) -> set:
    if not HAS_PANDAS:
        return set()
    ts = test_swaps_df if test_swaps_df is not None else get_table("test_swaps")
    affected: set = set()
    if ts is None or getattr(ts, "empty", True):
        return affected
    try:
        for sw in ts.itertuples(index=False):
            da = normalize_date_str(getattr(sw, "원본일자", ""))
            db = normalize_date_str(getattr(sw, "목표일자", ""))
            ta = str(getattr(sw, "교사A", "")).strip()
            tb = str(getattr(sw, "교사B", "")).strip()
            pa = safe_int(getattr(sw, "교시A", 0))
            pb = safe_int(getattr(sw, "교시B", 0))
            if da and ta and pa > 0:
                affected.add((da, ta, pa))
            if db and tb and pb > 0:
                affected.add((db, tb, pb))
    except Exception:
        pass
    return affected


def validate_swap(a, b, date_a, date_b, *, is_test=False, e_a=None, e_b=None,
                  swaps_df=None, test_swaps_df=None, teachers_df=None, duties_df=None,
                  neis_blocked: set | None = None):
    da, db = normalize_date_str(date_a), normalize_date_str(date_b)
    ta, tb = str(a.get("교사명", "")).strip(), str(b.get("교사명", "")).strip()
    pa, pb = safe_int(a.get("교시", 0)), safe_int(b.get("교시", 0))
    if not da or not db or not ta or not tb or pa <= 0 or pb <= 0:
        return False, "교사·일자·교시 정보가 올바르지 않습니다."
    try:
        day_a = C.WEEKDAY_KR[datetime.strptime(da, "%Y-%m-%d").weekday()]
        day_b = C.WEEKDAY_KR[datetime.strptime(db, "%Y-%m-%d").weekday()]
    except Exception:
        return False, "날짜 형식이 올바르지 않습니다."
    if is_grade12_thursday_7_forbidden(str(a.get("학급", "")), day_b, pb):
        return False, "1·2학년 수업은 목요일 7교시에 배치할 수 없습니다."
    if is_grade12_thursday_7_forbidden(str(b.get("학급", "")), day_a, pa):
        return False, "1·2학년 수업은 목요일 7교시에 배치할 수 없습니다."
    if ta == tb and da == db and pa == pb:
        return False, "동일한 교사·일자·교시는 교환할 수 없습니다."
    if _is_neis_blocked(da, neis_blocked) or _is_neis_blocked(db, neis_blocked):
        return False, "NEIS 학사일정상 공휴일·휴업일 등 수업이 없는 날은 맞교환할 수 없습니다."
    if not HAS_PANDAS:
        return True, ""
    if e_a is None:
        e_a = get_effective_timetable_for_date(da, use_test=is_test, neis_blocked=neis_blocked)
    if e_b is None:
        e_b = get_effective_timetable_for_date(db, use_test=is_test, neis_blocked=neis_blocked)
    try:
        ma = e_a[(e_a["교사명"] == ta) & (e_a["교시"].apply(safe_int) == pa)] if not e_a.empty else pd.DataFrame()
        mb = e_b[(e_b["교사명"] == tb) & (e_b["교시"].apply(safe_int) == pb)] if not e_b.empty else pd.DataFrame()
    except Exception:
        return False, "시간표 조회 실패"
    if ma.empty:
        return False, f"현재 적용 시간표에서 {ta}의 {da} {pa}교시 수업을 찾을 수 없습니다."
    if mb.empty:
        return False, f"현재 적용 시간표에서 {tb}의 {db} {pb}교시 수업을 찾을 수 없습니다."
    for label, info, m in [("A", a, ma), ("B", b, mb)]:
        cls, subj = str(info.get("학급", "")).strip(), str(info.get("과목", "")).strip()
        if cls and str(m.iloc[0]["학급"]).strip() != cls:
            return False, f"{label} 수업의 학급이 현재 시간표와 달라졌습니다. 다시 검색하세요."
        if subj and str(m.iloc[0]["과목"]).strip() != subj:
            return False, f"{label} 수업의 과목이 현재 시간표와 달라졌습니다. 다시 검색하세요."
    if db != da or pb != pa:
        try:
            a_at = e_b[(e_b["교사명"] == ta) & (e_b["교시"].apply(safe_int) == pb)] if not e_b.empty else pd.DataFrame()
            b_at = e_a[(e_a["교사명"] == tb) & (e_a["교시"].apply(safe_int) == pa)] if not e_a.empty else pd.DataFrame()
            if not a_at.empty:
                return False, f"A 교사의 목표 슬롯 {db} {pb}교시에 이미 수업이 있습니다."
            if not b_at.empty:
                return False, f"B 교사의 목표 슬롯 {da} {pa}교시에 이미 수업이 있습니다."
        except Exception:
            pass
    if not is_test:
        used = _direct_swap_affected(swaps_df)
        if (da, ta, pa) in used or (db, tb, pb) in used:
            return False, "이미 다른 맞교환에 사용된 슬롯입니다."
    else:
        used = _test_affected(test_swaps_df)
        if (da, ta, pa) in used or (db, tb, pb) in used:
            return False, "테스트에서 이미 사용된 슬롯입니다."
    avail = get_teacher_availability_index(teachers_df)
    ta_day_ok = (ta in avail and avail[ta][0] and (day_b, pb) in avail[ta][1]) if (ta in avail and avail[ta][0]) else True
    tb_day_ok = (tb in avail and avail[tb][0] and (day_a, pa) in avail[tb][1]) if (tb in avail and avail[tb][0]) else True
    # teacher_slot_is_available 래퍼와 동일 판정
    if ta in avail and avail[ta][0] and (day_b, pb) not in avail[ta][1]:
        return False, f"{ta} 교사는 {day_b}{pb}교시를 가능 시간으로 등록하지 않았습니다."
    if tb in avail and avail[tb][0] and (day_a, pa) not in avail[tb][1]:
        return False, f"{tb} 교사는 {day_a}{pa}교시를 가능 시간으로 등록하지 않았습니다."
    if has_duty(ta, da, pa, duties_df) or has_duty(tb, db, pb, duties_df):
        return False, "복무가 등록된 슬롯은 맞교환할 수 없습니다."
    return True, ""


def _class_slot_teachers(e_tt, class_name, period):
    if not HAS_PANDAS or e_tt is None or getattr(e_tt, "empty", True):
        return []
    try:
        m = e_tt[(e_tt["학급"].astype(str).str.strip() == str(class_name).strip()) & (e_tt["교시"].apply(safe_int) == safe_int(period))]
        return [str(x).strip() for x in m["교사명"].tolist()]
    except Exception:
        return []


def validate_substitute(cid, on_date, period, class_name, subject, absent_teacher, sub_teacher,
                        *, e_tt=None, subs_df=None, timetable_df=None, duties_df=None,
                        neis_blocked: set | None = None):
    norm = normalize_date_str(on_date)
    p = safe_int(period)
    absent_teacher, sub_teacher = str(absent_teacher).strip(), str(sub_teacher).strip()
    if not norm or p <= 0 or not absent_teacher or not sub_teacher:
        return False, "보강에 필요한 정보가 부족합니다."
    if absent_teacher == sub_teacher:
        return False, "결강교사와 보강교사가 같을 수 없습니다."
    if _is_neis_blocked(norm, neis_blocked):
        return False, "NEIS 비수업일에는 보강을 배정할 수 없습니다."
    if not HAS_PANDAS:
        return True, ""
    if e_tt is None:
        e_tt = get_effective_timetable_for_date(norm, neis_blocked=neis_blocked)
    try:
        source = e_tt[(e_tt["교사명"] == absent_teacher) & (e_tt["교시"].apply(safe_int) == p)] if not e_tt.empty else pd.DataFrame()
    except Exception:
        source = pd.DataFrame()
    if source.empty:
        base = timetable_df if timetable_df is not None else get_table("timetable")
        try:
            wd = C.WEEKDAY_KR[datetime.strptime(norm, "%Y-%m-%d").weekday()]
            source = base[(base["교사명"] == absent_teacher) & (base["요일"] == wd) & (base["교시"].apply(safe_int) == p)] if not base.empty else pd.DataFrame()
        except Exception:
            source = pd.DataFrame()
    if source.empty:
        return False, f"{absent_teacher}의 해당 교시 원본 수업을 찾을 수 없습니다."
    try:
        if str(source.iloc[0].get("학급", "")).strip() != str(class_name).strip() or str(source.iloc[0].get("과목", "")).strip() != str(subject).strip():
            return False, "결강 수업 정보가 현재 시간표와 일치하지 않습니다."
    except Exception:
        pass
    try:
        day = C.WEEKDAY_KR[datetime.strptime(norm, "%Y-%m-%d").weekday()]
    except Exception:
        day = ""
    if not is_free(sub_teacher, day, p, norm, e_tt, duties_df=duties_df):
        return False, f"{sub_teacher} 교사는 {day}{p}교시에 공강이 아닙니다."
    others = [t for t in _class_slot_teachers(e_tt, class_name, p) if t != absent_teacher]
    if others:
        return False, f"{class_name}은 {p}교시에 이미 다른 교사({', '.join(others)})가 담당하고 있습니다."
    subs = subs_df if subs_df is not None else get_table("subs")
    if subs is not None and not getattr(subs, "empty", True):
        try:
            same = subs[(subs["일자"].map(normalize_date_str) == norm) & (subs["교시"].apply(safe_int) == p)]
            same = same[(same["결강교사"].astype(str).str.strip() == absent_teacher) | (same["보강교사"].astype(str).str.strip() == sub_teacher)]
            if not same.empty:
                return False, "같은 시간대에 중복 보강 배정이 있습니다."
        except Exception:
            pass
    return True, ""


# ------------------------------------------------- recommend

def recommend_substitutes(day, period, subject, class_name, absent_teacher, on_date,
                          top_n=20, include_part_time=False, e_tt=None,
                          teachers_df=None, timetable_df=None, subs_df=None,
                          part_time_df=None, duties_df=None, neis_blocked: set | None = None):
    if not HAS_PANDAS:
        return []
    teachers = teachers_df if teachers_df is not None else get_table("teachers")
    norm = normalize_date_str(on_date)
    if e_tt is None:
        e_tt = get_effective_timetable_for_date(norm, neis_blocked=neis_blocked)
    grp, grade = subject_group(subject), grade_of(class_name)
    cum = cumulative_sub_count(subs_df, teachers)
    load = weekly_load(timetable_df)
    max_cum = max(cum.values()) if cum else 0
    rows = []
    occupied = set()
    try:
        if e_tt is not None and not e_tt.empty:
            occupied = {(str(r.교사명).strip(), safe_int(r.교시)) for r in e_tt.itertuples(index=False)}
    except Exception:
        occupied = set()
    duty_set = set()
    try:
        duties_df_eff = duties_df if duties_df is not None else get_table("duties")
        if duties_df_eff is not None and not duties_df_eff.empty:
            duty_set = {(str(r.교사명).strip(), safe_int(r.교시)) for r in
                        duties_df_eff[duties_df_eff["일자"].astype(str).map(normalize_date_str) == norm].itertuples(index=False)}
    except Exception:
        duty_set = set()
    teacher_groups: dict = defaultdict(set)
    teacher_grades: dict = defaultdict(set)
    if e_tt is not None and not getattr(e_tt, "empty", True):
        try:
            for rr in e_tt.itertuples(index=False):
                tn = str(rr.교사명).strip()
                if not tn:
                    continue
                teacher_groups[tn].add(str(getattr(rr, "과목군", "")).strip() or subject_group(getattr(rr, "과목", "")))
                teacher_grades[tn].add(grade_of(getattr(rr, "학급", "")))
        except Exception:
            pass
    teacher_subject = {}
    try:
        if teachers is not None and not teachers.empty and "교사명" in teachers.columns:
            for rr in teachers.itertuples(index=False):
                tn = str(getattr(rr, "교사명", "")).strip()
                if tn:
                    teacher_subject[tn] = str(getattr(rr, "담당과목", "")).strip()
    except Exception:
        pass
    names = []
    try:
        if teachers is not None and not teachers.empty and "교사명" in teachers.columns:
            names = teachers["교사명"].astype(str).str.strip().tolist()
    except Exception:
        names = []
    for t in names:
        t = str(t).strip()
        if not t or t == absent_teacher or (t, safe_int(period)) in occupied or (t, safe_int(period)) in duty_set:
            continue
        groups = teacher_groups.get(t, set())
        grades = teacher_grades.get(t, set())
        if grp in groups and grade in grades:
            prio, label, score = 1, "1순위 · 동일 과목 & 동일 학년", 100
        elif grp in groups:
            prio, label, score = 2, "2순위 · 동일 과목", 70
        elif grade in grades:
            prio, label, score = 3, "3순위 · 동일 학년", 45
        else:
            prio, label, score = 4, "4순위 · 전체 공강", 20
        score += (max_cum - cum.get(t, 0)) * 2 + max(0, 22 - load.get(t, 0)) * 0.3
        rows.append({"보강교사": t, "유형": "정규교사", "우선순위": label, "_prio": prio,
                     "담당과목": teacher_subject.get(t, ""), "주당시수": load.get(t, 0),
                     "누적보강": cum.get(t, 0), "추천점수": round(score, 1)})
    if include_part_time:
        pt = part_time_df if part_time_df is not None else get_table("part_time")
        try:
            if pt is not None and not pt.empty:
                for _, prow in pt.iterrows():
                    t = str(prow.get("시간강사명", "")).strip()
                    if not t or t == absent_teacher or not _part_time_available(prow, day, period):
                        continue
                    if not is_free(t, day, period, norm, e_tt, duties_df=duties_df):
                        continue
                    pgrp = subject_group(str(prow.get("담당과목", "")).strip() or str(prow.get("과목군", "")).strip())
                    prio = 1 if pgrp and pgrp == grp else 2 if pgrp else 4
                    label = "1순위 · 시간강사 동일 과목" if prio == 1 else "2순위 · 시간강사" if prio == 2 else "4순위 · 시간강사 공강"
                    score = 90 if prio == 1 else 60 if prio == 2 else 15
                    rows.append({"보강교사": t, "유형": "시간강사", "우선순위": label, "_prio": prio,
                                 "담당과목": prow.get("담당과목", ""), "주당시수": 0, "누적보강": 0, "추천점수": round(score, 1)})
        except Exception:
            pass
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values(["_prio", "추천점수"], ascending=[True, False]).drop(columns=["_prio"]).head(top_n).reset_index(drop=True)


def get_target_time_recommendations(teacher_a, date_a_str, period_a, class_a, subject_a,
                                    date_b_str, period_b, budget_factor=1.0,
                                    teachers_df=None, timetable_df=None, subs_df=None,
                                    duties_df=None, neis_blocked: set | None = None):
    if not HAS_PANDAS:
        return ([], [], "")
    norm_a, norm_b = normalize_date_str(date_a_str), normalize_date_str(date_b_str)
    ti = teachers_df if teachers_df is not None else get_table("teachers")
    e_a = get_effective_timetable_for_date(norm_a, neis_blocked=neis_blocked)
    e_b = get_effective_timetable_for_date(norm_b, neis_blocked=neis_blocked)
    if ti is None or getattr(ti, "empty", True) or e_a.empty or e_b.empty:
        return pd.DataFrame(), [], ""
    p_a, p_b = safe_int(period_a), safe_int(period_b)
    try:
        day_a = C.WEEKDAY_KR[date.fromisoformat(norm_a).weekday()]
        day_b = C.WEEKDAY_KR[date.fromisoformat(norm_b).weekday()]
    except Exception:
        return pd.DataFrame(), [], "날짜 오류"
    if _is_neis_blocked(norm_a, neis_blocked) or _is_neis_blocked(norm_b, neis_blocked):
        return pd.DataFrame(), [], "NEIS 학사일정상 수업이 없는 날입니다."
    if is_grade12_thursday_7_forbidden(class_a, day_a, p_a) or is_grade12_thursday_7_forbidden(class_a, day_b, p_b):
        return pd.DataFrame(), [], "1·2학년 수업은 목요일 7교시에 배치할 수 없습니다."
    my_class = str(class_a).strip()
    my_grade = grade_of(my_class)
    my_group = subject_group(subject_a)
    cum = cumulative_sub_count(subs_df, ti)
    avail = get_teacher_availability_index(ti)
    duties = _duty_index(duties_df)

    def avail_ok(t, d, p):
        item = avail.get(t)
        return True if item is None or not item[0] else (d, p) in item[1]
    try:
        occ_a = {(str(r.교사명).strip(), safe_int(r.교시)) for r in e_a.itertuples(index=False)}
        occ_b = {(str(r.교사명).strip(), safe_int(r.교시)) for r in e_b.itertuples(index=False)}
    except Exception:
        occ_a, occ_b = set(), set()

    def free(t, d, p, occ):
        if (t, p) in occ:
            return False
        ds = duties.get(t, set())
        return (d, 0) not in ds and (d, p) not in ds
    if not free(teacher_a, day_b, p_b, occ_b) or not avail_ok(teacher_a, day_b, p_b):
        return pd.DataFrame(), [], ""
    try:
        teacher_names = {str(x).strip() for x in ti["교사명"].dropna().tolist()}
    except Exception:
        teacher_names = set()
    b_slots: dict = defaultdict(list)
    try:
        for r in e_b.itertuples(index=False):
            if safe_int(getattr(r, "교시", 0)) == p_b:
                t = str(getattr(r, "교사명", "")).strip()
                if t in teacher_names and t:
                    b_slots[t].append(r)
    except Exception:
        pass
    swap_recs = []
    for t_b, b_lessons in b_slots.items():
        if t_b == teacher_a:
            continue
        ds = duties.get(t_b, set())
        if (norm_b, 0) in ds or (norm_b, p_b) in ds or not avail_ok(t_b, day_a, p_a) or not free(t_b, day_a, p_a, occ_a):
            continue
        for r in b_lessons:
            other_class = str(getattr(r, "학급", "")).strip()
            if other_class != my_class:
                continue
            other_subject = str(getattr(r, "과목", "")).strip()
            other_grade = grade_of(other_class)
            same_group = subject_group(other_subject) == my_group
            score = (200 + (40 if same_group else 0) + (15 if norm_a == norm_b else 0) - cum.get(t_b, 0) * 3) * budget_factor
            swap_recs.append({"유형": "1:1", "교사B": t_b, "현재 수업": f"{day_b}{p_b}교시 · {other_class} · {other_subject}",
                              "학급": other_class, "학년": other_grade, "same_class": True,
                              "same_grade": other_grade == my_grade, "점수": score,
                              "b_info": {"교사명": t_b, "일자": norm_b, "요일": day_b, "교시": p_b, "학급": other_class, "과목": other_subject}})
    df_swap = (pd.DataFrame(swap_recs).sort_values(["same_class", "same_grade", "점수"], ascending=[False, False, False]).reset_index(drop=True) if swap_recs else pd.DataFrame())
    cycles, msg = find_cycle_linked_swaps(teacher_a, norm_a, p_a, my_class, subject_a, norm_b, p_b, max_cycle=3)
    return df_swap, cycles, msg


def find_cycle_linked_swaps(teacher_a, date_a_str, period_a, class_a, subject_a,
                            date_b_str, period_b, min_cycle=2, max_cycle=3, future_days=7,
                            timetable_df=None, swaps_df=None, test_swaps_df=None,
                            teachers_df=None, duties_df=None, use_test=False,
                            neis_blocked: set | None = None):
    if not HAS_PANDAS:
        return [], "pandas 미설치"
    max_cycle = min(3, max(2, safe_int(max_cycle, 3)))
    original_slot = (normalize_date_str(date_a_str), safe_int(period_a))
    target_slot = (normalize_date_str(date_b_str), safe_int(period_b))
    if not original_slot[0] or not target_slot[0]:
        return [], "날짜 오류"
    try:
        da, db = date.fromisoformat(original_slot[0]), date.fromisoformat(target_slot[0])
    except ValueError:
        return [], "날짜 오류"
    if da.weekday() >= 5 or db.weekday() >= 5:
        return [], "날짜 오류"
    candidates = []
    cur = min(da, db) - timedelta(days=2)
    end = max(da, db) + timedelta(days=future_days)
    while cur <= end:
        if cur.weekday() < 5:
            candidates.append(cur.isoformat())
        cur += timedelta(days=1)
    weekday_cache = {d: C.WEEKDAY_KR[date.fromisoformat(d).weekday()] for d in candidates}
    e_cache = {d: get_effective_timetable_for_date(d, use_test=use_test, neis_blocked=neis_blocked) for d in candidates}
    excluded = (_test_affected(test_swaps_df) if use_test else set()) | (set() if use_test else _direct_swap_affected(swaps_df))
    class_slots: dict = {}
    teacher_occupied: dict = defaultdict(set)
    for d, e in e_cache.items():
        if e is None or getattr(e, "empty", True):
            continue
        for r in e.itertuples(index=False):
            t = str(getattr(r, "교사명", "")).strip()
            p = safe_int(getattr(r, "교시", 0))
            if not t or p <= 0:
                continue
            teacher_occupied[t].add((d, p))
            if str(getattr(r, "학급", "")).strip() == str(class_a).strip() and (d, t, p) not in excluded:
                class_slots[(d, p)] = {"teacher": t, "subject": str(getattr(r, "과목", "")).strip(), "day": weekday_cache[d]}
    if original_slot not in class_slots or class_slots[original_slot]["teacher"] != teacher_a:
        return [], "원본 슬롯/교사 불일치"
    if target_slot not in class_slots:
        return [], "목표 슬롯에 학급 수업 없음 (공강 생성 금지)"
    avail = get_teacher_availability_index(teachers_df)
    duties = _duty_index(duties_df)

    def free_at(t, d, p):
        occ = teacher_occupied.get(t, set())
        if (d, p) in occ or (d, t, p) in excluded:
            return False
        ds = duties.get(t, set())
        if (d, 0) in ds or (d, p) in ds:
            return False
        item = avail.get(t)
        if item is not None and item[0] and (weekday_cache.get(d, C.WEEKDAY_KR[date.fromisoformat(d).weekday()]), p) not in item[1]:
            return False
        return True
    if not free_at(teacher_a, target_slot[0], target_slot[1]):
        return [], "교사A 목표시간 수업 있음"
    slot_items = list(class_slots.items())
    free_moves: dict = defaultdict(list)
    for from_s, info in slot_items:
        t = info["teacher"]
        occupied = teacher_occupied.get(t, set())
        ds = duties.get(t, set())
        item = avail.get(t)
        for to_s, _ in slot_items:
            if to_s == from_s or to_s in occupied or (to_s[0], t, to_s[1]) in excluded:
                continue
            d, p = to_s
            day = weekday_cache[d]
            if (d, 0) in ds or (d, p) in ds:
                continue
            if item is not None and item[0] and (day, p) not in item[1]:
                continue
            free_moves[from_s].append(to_s)
    cycles = []
    max_found = 6

    def dfs(current, path, visited):
        if len(cycles) >= max_found or len(path) > max_cycle:
            return
        if current != original_slot and (current[0], class_slots.get(current, {}).get("teacher", ""), current[1]) in excluded:
            return
        if current == original_slot:
            if len(path) < min_cycle:
                return
            cycle_slots = [original_slot] + path[:-1]
            moves = []
            n = len(cycle_slots)
            for i, from_s in enumerate(cycle_slots):
                to_s = cycle_slots[(i + 1) % n]
                info = class_slots[from_s]
                tgt = class_slots[to_s]
                moves.append({"teacher": info["teacher"], "from_date": from_s[0], "from_period": from_s[1],
                              "to_date": to_s[0], "to_period": to_s[1], "class": class_a,
                              "subject": info["subject"], "target_subject": tgt["subject"],
                              "day_from": info["day"], "next_teacher": tgt["teacher"]})
            path_desc = " → ".join(f"{m['teacher']}({m['class']} {m['from_date'][5:]} {m['from_period']}→{m['to_date'][5:]} {m['to_period']})" for m in moves)
            cycles.append({"length": n, "moves": moves, "path_desc": path_desc, "score": 110 - n * 12})
            return
        for nxt in free_moves.get(current, ()):
            if nxt in visited:
                continue
            visited.add(nxt)
            path.append(nxt)
            dfs(nxt, path, visited)
            path.pop()
            visited.remove(nxt)
    dfs(target_slot, [target_slot], {target_slot})
    cycles.sort(key=lambda x: (x["length"], -x["score"]))
    return cycles[:max_found], f"{len(cycles)}개 순환 경로 발견" if cycles else "순환 경로 없음"


# ------------------------------------------------- mutations (store 기반)



def add_substitute(cid, on_date, day, period, class_name, subject, absent_teacher, sub_teacher,
                   method="", priority="", memo="", user="", save_sheet=True):
    if not HAS_PANDAS:
        return False, "pandas 미설치"
    norm = normalize_date_str(on_date)
    p = safe_int(period)
    e_tt = get_effective_timetable_for_date(norm)
    ok, msg = validate_substitute(cid, norm, p, class_name, subject, absent_teacher, sub_teacher, e_tt=e_tt)
    if not ok:
        return False, msg
    s = get_table("subs")
    try:
        old = s[(s["결강ID"].astype(str) == str(cid)) & (s["교시"].apply(safe_int) == p)] if not s.empty else pd.DataFrame()
    except Exception:
        old = pd.DataFrame()
    new = pd.DataFrame([{
        "결강ID": cid, "일자": norm, "요일": day, "교시": p, "학급": class_name, "과목": subject,
        "결강교사": absent_teacher, "보강교사": sub_teacher, "배정방식": method, "우선순위": priority,
        "비고": memo, "등록시각": _now_text("%Y-%m-%d %H:%M"), "입력자": user,
    }])
    try:
        working = s.drop(old.index) if not old.empty else s
        store.tables["subs"] = pd.concat([working, new], ignore_index=True)
    except Exception as exc:
        return False, str(exc)
    if save_sheet:
        res = store.save(["보강"])
        if not res.get("ok"):
            return False, res.get("error", "저장 실패")
        if old.empty:
            update_budget(-C.SUB_COST, f"보강 1건 ({sub_teacher} ← {absent_teacher})")
    store.push_history(f"보강 배정 ({sub_teacher})")
    store.invalidate()
    return True, ""


def add_substitutes_batch(assignments, user="", action_name="자동 보강"):
    if not HAS_PANDAS:
        return 0, ["pandas 미설치"]
    original = get_table("subs")
    working = original.copy(deep=True)
    added_new = 0
    accepted = 0
    errors = []
    for rec in assignments or []:
        cid, norm, p = rec.get("cid"), normalize_date_str(rec.get("on_date")), safe_int(rec.get("period"))
        # working 기준 검증: 임시로 store 교체 없이 e_tt 계산
        e_tt = _build_effective_timetable_for_date(
            norm, get_table("timetable"), get_table("swaps"), get_table("test_swaps"),
            working, get_table("part_time"))
        ok, msg = validate_substitute(cid, norm, p, rec.get("class_name"), rec.get("subject"),
                                      rec.get("absent_teacher"), rec.get("sub_teacher"),
                                      e_tt=e_tt, subs_df=working)
        if not ok:
            errors.append(f"{p}교시: {msg}")
            continue
        try:
            old = working[(working["결강ID"].astype(str) == str(cid)) & (working["교시"].apply(safe_int) == p)] if not working.empty else pd.DataFrame()
            if not old.empty:
                working = working.drop(old.index)
            else:
                added_new += 1
            working = pd.concat([working, pd.DataFrame([{
                "결강ID": cid, "일자": norm, "요일": rec.get("day"), "교시": p, "학급": rec.get("class_name"),
                "과목": rec.get("subject"), "결강교사": rec.get("absent_teacher"), "보강교사": rec.get("sub_teacher"),
                "배정방식": rec.get("method", "자동"), "우선순위": rec.get("priority", ""), "비고": rec.get("memo", ""),
                "등록시각": _now_text("%Y-%m-%d %H:%M"), "입력자": user,
            }])], ignore_index=True)
            accepted += 1
        except Exception as exc:
            errors.append(str(exc))
    store.tables["subs"] = working.reset_index(drop=True)
    if accepted:
        res = store.save(["보강"])
        if not res.get("ok"):
            store.tables["subs"] = original
            return 0, ["보강 저장 실패로 작업을 원복했습니다."]
        if added_new:
            update_budget(-(added_new * C.SUB_COST), f"{action_name} {added_new}건")
        store.push_history(action_name)
        store.invalidate()
    return accepted, errors


def cancel_substitute(cid, period):
    if not HAS_PANDAS:
        return False, "pandas 미설치"
    p = safe_int(period)
    s = get_table("subs")
    try:
        m = s[(s["결강ID"] == cid) & (s["교시"] == p)] if not s.empty else pd.DataFrame()
        # 교시 타입 불일치 대비
        if m.empty and not s.empty:
            m = s[(s["결강ID"].astype(str) == str(cid)) & (s["교시"].apply(safe_int) == p)]
    except Exception:
        return False, "조회 실패"
    if m.empty:
        return False, "대상 없음"
    before = s.copy(deep=True)
    store.tables["subs"] = s.drop(m.index).reset_index(drop=True)
    res = store.save(["보강"])
    if not res.get("ok"):
        store.tables["subs"] = before
        return False, res.get("error", "저장 실패")
    update_budget(+C.SUB_COST, f"보강 취소 복구 ({period}교시)")
    store.push_history(f"보강 취소 ({period}교시)")
    store.invalidate()
    return True, ""


def do_swap(a, b, date_a, date_b, is_part_time_purpose=False, is_test=False, user=""):
    if not HAS_PANDAS:
        return False, "pandas 미설치"
    class_a = str(a.get("학급", "")).strip()
    class_b = str(b.get("학급", "")).strip()
    if class_a and class_b and class_a != class_b:
        return False, "1:1 맞교환은 동일 학급 수업끼리만 가능합니다."
    ok, msg = validate_swap(a, b, date_a, date_b, is_test=is_test)
    if not ok:
        return False, msg
    ver_e_a = get_effective_timetable_for_date(normalize_date_str(date_a), use_test=is_test)
    ver_e_b = get_effective_timetable_for_date(normalize_date_str(date_b), use_test=is_test)
    try:
        ma = ver_e_a[(ver_e_a["교사명"] == a["교사명"]) & (ver_e_a["교시"].apply(safe_int) == safe_int(a["교시"]))] if not ver_e_a.empty else pd.DataFrame()
        mb = ver_e_b[(ver_e_b["교사명"] == b["교사명"]) & (ver_e_b["교시"].apply(safe_int) == safe_int(b["교시"]))] if not ver_e_b.empty else pd.DataFrame()
    except Exception:
        ma, mb = pd.DataFrame(), pd.DataFrame()
    oa = ma.iloc[0] if not ma.empty else a
    ob = mb.iloc[0] if not mb.empty else b

    def _g(row, key, default=""):
        try:
            v = row.get(key, default) if isinstance(row, dict) else row.get(key, default)
            return v
        except Exception:
            try:
                return getattr(row, key, default)
            except Exception:
                return default
    rec = {
        "변경ID": _new_change_id("TESTSW" if is_test else "SWAP"),
        "원본교사A": str(_g(oa, "원본교사", a["교사명"])), "실제원본일자A": str(_g(oa, "원본일자", normalize_date_str(date_a))),
        "실제원본교시A": safe_int(_g(oa, "원본교시", a["교시"])),
        "원본교사B": str(_g(ob, "원본교사", b["교사명"])), "실제원본일자B": str(_g(ob, "원본일자", normalize_date_str(date_b))),
        "실제원본교시B": safe_int(_g(ob, "원본교시", b["교시"])),
        "원본일자": normalize_date_str(date_a), "교사A": a["교사명"], "요일A": a.get("요일", ""), "교시A": safe_int(a["교시"]),
        "학급A": a.get("학급", ""), "과목A": a.get("과목", ""), "목표일자": normalize_date_str(date_b),
        "교사B": b["교사명"], "요일B": b.get("요일", ""), "교시B": safe_int(b["교시"]), "학급B": b.get("학급", ""), "과목B": b.get("과목", ""),
        "유형": "1:1 맞교환", "시간강사구인": "Y" if is_part_time_purpose else "N",
        "등록시각": _now_text("%Y-%m-%d %H:%M"), "입력자": user,
    }
    if is_test:
        cur = get_table("test_swaps")
        store.tables["test_swaps"] = pd.concat([cur, pd.DataFrame([rec])], ignore_index=True)
        store.invalidate()
        return True, ""
    before = get_table("swaps")
    store.tables["swaps"] = pd.concat([before, pd.DataFrame([rec])], ignore_index=True)
    res = store.save(["맞교환"])
    if not res.get("ok"):
        store.tables["swaps"] = before
        return False, res.get("error", "저장 실패")
    store.push_history(f"맞교환 ({a['교사명']} ↔ {b['교사명']})")
    store.invalidate()
    return True, ""


def do_linked_swap(a, teacher_b, date_a, date_b, day_b, period_b,
                   is_part_time_purpose=False, is_test=False, subject_b=None, user=""):
    if not HAS_PANDAS:
        return False, "pandas 미설치"
    norm_a, norm_b = normalize_date_str(date_a), normalize_date_str(date_b)
    try:
        day_a = C.WEEKDAY_KR[datetime.strptime(norm_a, "%Y-%m-%d").weekday()] if norm_a else ""
    except Exception:
        day_a = ""
    if _is_neis_blocked(norm_a) or _is_neis_blocked(norm_b):
        return False, "NEIS 비수업일"
    e_b = get_effective_timetable_for_date(norm_b, use_test=is_test)
    if not is_free(teacher_b, day_b, period_b, norm_b, e_b):
        return False, "목표 슬롯 공강 아님"
    if not slot_allowed_for_class(str(a.get("학급", "")), day_b, period_b):
        return False, "목7 1·2학년 금지"
    rec = {
        "변경ID": _new_change_id("TESTLINK" if is_test else "LINK"),
        "원본일자": norm_a, "교사A": a["교사명"], "요일A": a.get("요일", day_a), "교시A": safe_int(a["교시"]),
        "학급A": a.get("학급", ""), "과목A": a.get("과목", ""), "목표일자": norm_b,
        "교사B": teacher_b, "요일B": day_b, "교시B": safe_int(period_b), "학급B": a.get("학급", ""),
        "과목B": subject_b if subject_b is not None else a.get("과목", ""), "유형": "연계 공강 교환",
        "시간강사구인": "Y" if is_part_time_purpose else "N", "등록시각": _now_text("%Y-%m-%d %H:%M"), "입력자": user,
    }
    if is_test:
        cur = get_table("test_swaps")
        store.tables["test_swaps"] = pd.concat([cur, pd.DataFrame([rec])], ignore_index=True)
        store.invalidate()
        return True, ""
    before = get_table("swaps")
    store.tables["swaps"] = pd.concat([before, pd.DataFrame([rec])], ignore_index=True)
    res = store.save(["맞교환"])
    if not res.get("ok"):
        store.tables["swaps"] = before
        return False, res.get("error", "저장 실패")
    store.push_history(f"연계교환 ({a['교사명']} → {teacher_b})")
    store.invalidate()
    return True, ""


def apply_cycle_swaps(moves, is_test=False, user=""):
    if not moves:
        return False, "empty"
    if not HAS_PANDAS:
        return False, "pandas 미설치"
    if is_test:
        before = get_table("test_swaps")
        try:
            for m in moves:
                a_info = {"교사명": m["teacher"],
                          "요일": m.get("day_from", C.WEEKDAY_KR[datetime.strptime(m["from_date"], "%Y-%m-%d").weekday()]),
                          "교시": m["from_period"], "학급": m["class"], "과목": m["subject"]}
                to_day = C.WEEKDAY_KR[datetime.strptime(m["to_date"], "%Y-%m-%d").weekday()]
                ok, _ = do_linked_swap(a_info, m.get("next_teacher", m["teacher"]), m["from_date"],
                                        m["to_date"], to_day, m["to_period"], is_test=True,
                                        subject_b=m.get("target_subject", m["subject"]), user=user)
                if not ok:
                    raise ValueError("순환 테스트 일부 실패")
            return True, ""
        except Exception as exc:
            store.tables["test_swaps"] = before
            store.invalidate()
            return False, str(exc)
    before = get_table("swaps")
    saved = []
    for m in moves:
        a_info = {"교사명": m["teacher"],
                  "요일": m.get("day_from", C.WEEKDAY_KR[datetime.strptime(m["from_date"], "%Y-%m-%d").weekday()]),
                  "교시": m["from_period"], "학급": m["class"], "과목": m["subject"]}
        to_day = C.WEEKDAY_KR[datetime.strptime(m["to_date"], "%Y-%m-%d").weekday()]
        # 직접 행 추가 (검증은 상위에서 수행됐다고 가정 + 기본 검증)
        rec = {
            "변경ID": _new_change_id("LINK"),
            "원본일자": m["from_date"], "교사A": m["teacher"], "요일A": a_info["요일"], "교시A": safe_int(m["from_period"]),
            "학급A": m["class"], "과목A": m["subject"], "목표일자": m["to_date"],
            "교사B": m.get("next_teacher", m["teacher"]), "요일B": to_day, "교시B": safe_int(m["to_period"]),
            "학급B": m["class"], "과목B": m.get("target_subject", m["subject"]), "유형": "연계 공강 교환",
            "시간강사구인": "N", "등록시각": _now_text("%Y-%m-%d %H:%M"), "입력자": user,
        }
        saved.append(rec)
    try:
        store.tables["swaps"] = pd.concat([before, pd.DataFrame(saved)], ignore_index=True)
    except Exception as exc:
        store.tables["swaps"] = before
        return False, str(exc)
    res = store.save(["맞교환"])
    if not res.get("ok"):
        store.tables["swaps"] = before
        return False, res.get("error", "저장 실패")
    store.push_history(f"{len(moves)}인 연계교환")
    store.invalidate()
    return True, ""


# ------------------------------------------------- budget

def get_current_budget(budget_df=None):
    if not HAS_PANDAS:
        return C.BUDGET_INIT
    df = budget_df if budget_df is not None else get_table("budget")
    try:
        if df is None or getattr(df, "empty", True):
            return C.BUDGET_INIT
        return max(0, safe_int(df.iloc[-1].get("잔액", C.BUDGET_INIT)))
    except Exception:
        return C.BUDGET_INIT


def update_budget(change_amount: int, reason: str = "보강"):
    if not HAS_PANDAS:
        return C.BUDGET_INIT
    df = get_table("budget")
    try:
        current = safe_int(df.iloc[-1].get("잔액", C.BUDGET_INIT)) if not df.empty else C.BUDGET_INIT
        new_balance = max(0, current + int(change_amount))
        new_row = pd.DataFrame([{"일시": _now_text(), "내용": reason, "변동금액": int(change_amount), "잔액": new_balance}])
        store.tables["budget"] = pd.concat([df, new_row], ignore_index=True)
        store.save(["예산"])
        store.invalidate()
        return new_balance
    except Exception:
        return None


# ------------------------------------------------- salary (360일 기준)

def _salary_safe_date(value):
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    s = str(value).strip()
    if not s or s.lower() in {"nan", "none", "nat"}:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y%m%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _salary_duration_days(start_value, end_value, include_end=True):
    start = _salary_safe_date(start_value)
    end = _salary_safe_date(end_value)
    if start is None or end is None:
        return 0
    if include_end:
        end = end + timedelta(days=1)
    y = end.year - start.year
    m = end.month - start.month
    d = end.day - start.day
    if d < 0:
        m -= 1
        first_of_month = end.replace(day=1)
        prev_last = first_of_month - timedelta(days=1)
        d += prev_last.day
    if m < 0:
        y -= 1
        m += 12
    return (y * 360) + (m * 30) + d


def _salary_ymd_from_360(days):
    days = max(0, int(days))
    return days // 360, (days % 360) // 30, days % 30


def _salary_duration_text(days):
    y, m, d = _salary_ymd_from_360(days)
    return f"{y}년 {m}월 {d}일"


def _salary_normalize_table(df, columns):
    if not HAS_PANDAS:
        return df
    if df is None or not isinstance(df, pd.DataFrame):
        return pd.DataFrame(columns=columns)
    out = df.copy()
    for c in columns:
        if c not in out.columns:
            out[c] = ""
    return out[columns].reset_index(drop=True)


def _salary_calculate(name, calc_date, org, position, writer_name, writer_pos,
                      base_value, qual_label, academic_value, academic_label, is_sabom,
                      degree_df, career_df):
    total = 0
    details = []
    degree_df = _salary_normalize_table(degree_df, ["학위 구분", "학교/전공 세부명", "입학일", "졸업일", "환산율"])
    career_df = _salary_normalize_table(career_df, ["경력 종류", "세부 근무처/직위", "시작일", "종료일", "종료일 산입", "환산율 (%)"])
    if HAS_PANDAS:
        for _, row in degree_df.iterrows():
            dtype = str(row.get("학위 구분", "")).strip()
            detail = str(row.get("학교/전공 세부명", "")).strip()
            rate = max(0, safe_int(row.get("환산율"), 0))
            raw = _salary_duration_days(row.get("입학일"), row.get("졸업일"), True)
            conv = math.floor(raw * (rate / 100.0))
            total += conv
            cy, cm, cd = _salary_ymd_from_360(conv)
            details.append({"구분": f"[학위] {dtype} ({detail})", "시작일": _salary_safe_date(row.get("입학일")),
                            "종료일": _salary_safe_date(row.get("졸업일")), "원기간": _salary_duration_text(raw),
                            "환산율": f"{rate}%", "환산년": cy, "환산월": cm, "환산일": cd, "종류": "학위"})
        for _, row in career_df.iterrows():
            ctype = str(row.get("경력 종류", "")).strip()
            detail = str(row.get("세부 근무처/직위", "")).strip()
            inc = bool(row.get("종료일 산입", True))
            rate = max(0, safe_int(row.get("환산율 (%)"), 0))
            raw = _salary_duration_days(row.get("시작일"), row.get("종료일"), inc)
            conv = math.floor(raw * (rate / 100.0))
            total += conv
            cy, cm, cd = _salary_ymd_from_360(conv)
            details.append({"구분": f"{ctype} ({detail})", "시작일": _salary_safe_date(row.get("시작일")),
                            "종료일": _salary_safe_date(row.get("종료일")), "원기간": _salary_duration_text(raw),
                            "환산율": f"{rate}%", "환산년": cy, "환산월": cm, "환산일": cd, "종류": "경력"})
    total_y, total_m, total_d = _salary_ymd_from_360(total)
    add_years = 1 if is_sabom else 0
    final_step = max(1, min(40, int(base_value) + int(academic_value) + add_years + total_y))
    return {"name": name, "calc_date": calc_date, "org": org, "position": position,
            "writer_name": writer_name, "writer_pos": writer_pos,
            "base_salary": base_value, "qual_label": qual_label,
            "academic_value": academic_value, "academic_label": academic_label,
            "add_years": add_years, "is_sabom": bool(is_sabom), "details": details,
            "total_y": total_y, "total_m": total_m, "total_d": total_d,
            "final_step": final_step, "rem_m": total_m, "rem_d": total_d}


def _salary_report_html(result):
    def esc(v):
        if v is None:
            return ""
        if isinstance(v, (date, datetime)):
            return v.strftime("%Y-%m-%d")
        return html_lib.escape(str(v))
    rows = []
    for item in result.get("details", []):
        rows.append("<tr>" f"<td class='left'>{esc(item['구분'])}</td>"
                    f"<td>{esc(item['시작일']) or '-'}</td>" f"<td>{esc(item['종료일']) or '-'}</td>"
                    f"<td>{esc(item['원기간'])}</td>" f"<td>{esc(item['환산율'])}</td>"
                    f"<td>{item['환산년']}</td><td>{item['환산월']}</td><td>{item['환산일']}</td>" "</tr>")
    if not rows:
        rows.append("<tr><td colspan='8'>학위 및 경력 사항이 없습니다.</td></tr>")
    calc = result.get("calc_date")
    calc_text = calc.strftime("%Y년 %m월 %d일") if isinstance(calc, date) else esc(calc)
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8">
<title>호봉 획정 조서 - {esc(result.get('name'))}</title></head><body>
<h1>호봉 획정 (재획정) 조서</h1>
<table><tr><th>성명</th><td>{esc(result.get('name'))}</td><th>최종호봉</th><td>{result['final_step']}호봉</td></tr></table>
<table><tbody>{''.join(rows)}</tbody></table>
<p>환산경력 합계: {result['total_y']}년 {result['total_m']}월 {result['total_d']}일 / 일자: {calc_text}</p>
</body></html>"""


# ------------------------------------------------- NEIS wrappers

def neis_find_school(api_key: str, school_name: str):
    return find_school(api_key, school_name)


def neis_fetch_schedule(api_key: str, school_name: str, from_ymd: str, to_ymd: str):
    return fetch_schedule(api_key, school_name, from_ymd, to_ymd)


def is_neis_non_instructional(norm_date: str, schedule_df=None) -> bool:
    if schedule_df is None:
        return _is_neis_blocked(normalize_date_str(norm_date))
    if not HAS_PANDAS or schedule_df is None or getattr(schedule_df, "empty", True):
        return False
    try:
        m = schedule_df[schedule_df["일자"] == normalize_date_str(norm_date)]
        if m.empty:
            return False
        return bool(m.iloc[0].get("비수업일", False))
    except Exception:
        return False


# ------------------------------------------------- week views

def get_teacher_week_view(teacher: str, ref_date: date, use_test=False, neis_blocked: set | None = None):
    if not HAS_PANDAS:
        return [], []
    if isinstance(ref_date, str):
        ref_date = date.fromisoformat(normalize_date_str(ref_date))
    monday = ref_date - timedelta(days=ref_date.weekday())
    week_dates = [monday + timedelta(days=i) for i in range(5)]
    grid = []
    for p in range(1, C.MAX_PERIOD + 1):
        row = {"교사명": teacher, "교시": p}
        for i, d in enumerate(C.DAYS):
            ds = week_dates[i].strftime("%Y-%m-%d")
            e = get_effective_timetable_for_date(ds, use_test=use_test, neis_blocked=neis_blocked)
            try:
                m = e[(e["교사명"] == teacher) & (e["교시"].apply(safe_int) == p)] if not e.empty else pd.DataFrame()
            except Exception:
                m = pd.DataFrame()
            if m.empty:
                row[d] = ""
                continue
            r = m.iloc[0]
            cell = f"{r['학급']} {r['과목']}".strip()
            typ = str(r.get("변경유형", "원본"))
            if typ == "교환":
                cell += f" 🔄 {r.get('변경출처', '교환')}"
            elif typ == "테스트교환":
                cell += f" 🧪 {r.get('변경출처', '테스트교환')}"
            elif typ == "보강":
                cell += f" 🟢 {r.get('변경출처', '보강')}"
            elif typ == "시간강사":
                cell += f" 🟡 {r.get('원본교사', '')}→시간강사"
            row[d] = cell
        grid.append(row)
    return pd.DataFrame(grid), week_dates


def get_changed_teachers_for_week(ref_date: date, absences_df=None, subs_df=None, swaps_df=None, part_time_df=None):
    if not HAS_PANDAS:
        return []
    if isinstance(ref_date, str):
        ref_date = date.fromisoformat(normalize_date_str(ref_date))
    monday = ref_date - timedelta(days=ref_date.weekday())
    week_dates = [(monday + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(5)]
    changed: set = set()
    absences = absences_df if absences_df is not None else get_table("absences")
    subs = subs_df if subs_df is not None else get_table("subs")
    swaps = swaps_df if swaps_df is not None else get_table("swaps")
    try:
        for df, cols in [(absences, ["교사명"]), (subs, ["결강교사", "보강교사"])]:
            if df is not None and not df.empty and "일자" in df.columns:
                mask = df["일자"].isin(week_dates)
                for c in cols:
                    if c in df.columns:
                        changed.update(df.loc[mask, c].dropna().tolist())
        if swaps is not None and not swaps.empty:
            for col in ["원본일자", "목표일자"]:
                if col in swaps.columns:
                    mask = swaps[col].isin(week_dates)
                    if "교사A" in swaps.columns:
                        changed.update(swaps.loc[mask, "교사A"].tolist())
                    if "교사B" in swaps.columns:
                        changed.update(swaps.loc[mask, "교사B"].tolist())
    except Exception:
        pass
    return sorted(t for t in (str(x).strip() for x in changed) if t)


def get_weekly_1to1_swap_table(teacher: str, ref_date: date, future_days: int = 0, neis_blocked: set | None = None):
    if not HAS_PANDAS:
        return []
    if isinstance(ref_date, str):
        ref_date = date.fromisoformat(normalize_date_str(ref_date))
    monday = ref_date - timedelta(days=ref_date.weekday())
    week_dates = [(monday + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(5)]
    search_dates = week_dates[:]
    if future_days > 0:
        last = datetime.strptime(week_dates[-1], "%Y-%m-%d").date()
        for i in range(1, future_days + 1):
            nd = last + timedelta(days=i)
            if nd.weekday() < 5:
                search_dates.append(nd.strftime("%Y-%m-%d"))
    search_dates = sorted(set(search_dates))
    results = []
    seen = set()
    for d_str in week_dates:
        try:
            day_kr = C.WEEKDAY_KR[datetime.strptime(d_str, "%Y-%m-%d").weekday()]
        except Exception:
            continue
        if _is_neis_blocked(d_str, neis_blocked):
            continue
        e_tt = get_effective_timetable_for_date(d_str, neis_blocked=neis_blocked)
        if e_tt.empty:
            continue
        try:
            my_lessons = e_tt[(e_tt["교사명"] == teacher) & (e_tt["요일"] == day_kr)].sort_values("교시")
        except Exception:
            continue
        for _, lesson in my_lessons.iterrows():
            p = safe_int(lesson["교시"])
            my_class = str(lesson["학급"]).strip()
            my_subj = str(lesson["과목"]).strip()
            my_grade = grade_of(my_class)
            my_group = subject_group(my_subj)
            for td_str in search_dates:
                if td_str == d_str:
                    continue
                try:
                    tday = C.WEEKDAY_KR[datetime.strptime(td_str, "%Y-%m-%d").weekday()]
                except Exception:
                    continue
                if _is_neis_blocked(td_str, neis_blocked):
                    continue
                e_b = get_effective_timetable_for_date(td_str, neis_blocked=neis_blocked)
                if e_b.empty:
                    continue
                try:
                    others = e_b[(e_b["교시"] == p) & (e_b["교사명"] != teacher)].drop_duplicates(subset=["교사명", "교시"])
                except Exception:
                    continue
                for _, o in others.iterrows():
                    other_teacher = str(o["교사명"]).strip()
                    if (d_str, p, td_str, other_teacher) in seen:
                        continue
                    if not is_free(teacher, tday, p, td_str, e_b):
                        continue
                    if not is_free(other_teacher, day_kr, p, d_str, e_tt):
                        continue
                    other_class = str(o["학급"]).strip()
                    if other_class != my_class:
                        continue
                    if is_grade12_thursday_7_forbidden(my_class, tday, p) or is_grade12_thursday_7_forbidden(other_class, day_kr, p):
                        continue
                    score = 200 + (40 if subject_group(str(o["과목"])) == my_group else 0) + (10 if td_str[:7] == d_str[:7] else 0)
                    seen.add((d_str, p, td_str, other_teacher))
                    results.append({"원본일자": d_str, "원본요일": day_kr, "원본교시": p, "원본학급": my_class,
                                    "원본과목": my_subj, "이동희망일": td_str, "이동요일": tday, "상대교사": other_teacher,
                                    "상대학급": other_class, "상대과목": str(o["과목"]), "상대수업": f"{other_class} {o['과목']}",
                                    "동일학급": "🏆", "점수": score})
    if not results:
        return pd.DataFrame()
    df = pd.DataFrame(results)
    return df.sort_values("점수", ascending=False).reset_index(drop=True)


# ------------------------------------------------- excel / html

def _workbook_bytes(wb):
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def to_excel_bytes(sheets: dict) -> bytes:
    if not HAS_PANDAS:
        raise RuntimeError("pandas 미설치")
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        for name, df in (sheets or {}).items():
            (df if isinstance(df, pd.DataFrame) else pd.DataFrame(df)).to_excel(w, sheet_name=str(name)[:31], index=False)
    return buf.getvalue()


def build_weekly_schedule_excel_bytes(ref_date: date, *, use_test=False, title="전체 교사 시간표",
                                      neis_blocked: set | None = None) -> bytes:
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, Alignment, Border, Side, PatternFill
        from openpyxl.utils import get_column_letter
        from openpyxl.worksheet.page import PageMargins
    except Exception as exc:
        raise RuntimeError(f"openpyxl 미설치: {exc}")
    if isinstance(ref_date, str):
        ref_date = date.fromisoformat(normalize_date_str(ref_date))
    monday = ref_date - timedelta(days=ref_date.weekday())
    tt = get_table("timetable")
    wb = Workbook()
    ws = wb.active
    ws.title = "전체 교사 시간표"
    title_font = Font(name="돋움", size=20, bold=True)
    small_font = Font(name="돋움", size=8)
    head_font = Font(name="돋움", size=9, bold=True)
    body_font = Font(name="돋움", size=8)
    thin = Side(style="hair", color="B7B7B7")
    med = Side(style="medium", color="808080")
    fill_head = PatternFill("solid", fgColor="D9EAF7")
    fill_day = [PatternFill("solid", fgColor=x) for x in ("DDEBF7", "E2F0D9", "FFF2CC", "E4DFEC", "FCE4D6")]
    days = C.DAYS
    periods = {d: list(range(1, C.PERIODS_PER_DAY.get(d, 7) + 1)) for d in days}
    col = 3
    day_ranges = {}
    for i, d in enumerate(days):
        start, end = col, col + len(periods[d]) - 1
        day_ranges[d] = (start, end)
        col = end + 1
    last_col = col - 1
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=last_col)
    ws["A1"] = title
    ws["A1"].font = title_font
    ws["A1"].alignment = Alignment(horizontal="center", vertical="center")
    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=2)
    ws["A2"] = f"{C.SCHOOL_YEAR} 학년도"
    ws["A2"].font = small_font
    ws.merge_cells(start_row=2, start_column=last_col - 4, end_row=2, end_column=last_col)
    ws.cell(2, last_col - 4).value = C.SCHOOL_NAME
    ws.cell(2, last_col - 4).font = small_font
    ws.cell(2, last_col - 4).alignment = Alignment(horizontal="right", vertical="center")
    ws["A3"] = "번호"
    ws["B3"] = "교사"
    for c in (1, 2):
        ws.cell(3, c).font = head_font
        ws.cell(3, c).alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws.cell(3, c).fill = fill_head
    ws.merge_cells("A3:A4")
    ws.merge_cells("B3:B4")
    for i, d in enumerate(days):
        start, end = day_ranges[d]
        ws.merge_cells(start_row=3, start_column=start, end_row=3, end_column=end)
        cell = ws.cell(3, start)
        cell.value = f"{d}({(monday + timedelta(days=i)):%m/%d})"
        cell.font = head_font
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.fill = fill_day[i]
        for pno in periods[d]:
            pc = ws.cell(4, start + pno - 1)
            pc.value = pno
            pc.font = head_font
            pc.alignment = Alignment(horizontal="center", vertical="center")
            pc.fill = fill_day[i]
    teachers = sorted(tt["교사명"].dropna().astype(str).str.strip().unique()) if tt is not None and not tt.empty else []
    daily = {}
    for i, d in enumerate(days):
        ds = (monday + timedelta(days=i)).strftime("%Y-%m-%d")
        e = get_effective_timetable_for_date(ds, use_test=use_test, neis_blocked=neis_blocked)
        daily[d] = {(str(r.교사명).strip(), safe_int(r.교시)): r for r in e.itertuples(index=False)} if not e.empty else {}
    row = 5
    for n, t in enumerate(teachers, 1):
        ws.merge_cells(start_row=row, start_column=1, end_row=row + 1, end_column=1)
        ws.merge_cells(start_row=row, start_column=2, end_row=row + 1, end_column=2)
        ws.cell(row, 1).value = n
        ws.cell(row, 2).value = t
        for rr in (row, row + 1):
            for cc in range(1, last_col + 1):
                c = ws.cell(rr, cc)
                c.font = body_font
                c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
                c.border = Border(left=thin, right=thin, top=thin, bottom=thin)
        for i, d in enumerate(days):
            idx = daily[d]
            for pno in periods[d]:
                cc = day_ranges[d][0] + pno - 1
                r = idx.get((t, pno))
                if r is None:
                    continue
                subj = str(getattr(r, "과목", "")).strip()
                cls = str(getattr(r, "학급", "")).strip()
                typ = str(getattr(r, "변경유형", "원본")).strip()
                ws.cell(row, cc).value = subj
                ws.cell(row + 1, cc).value = cls
                if typ == "교환":
                    fill, mark = PatternFill("solid", fgColor="F4CCCC"), "🔄"
                elif typ == "보강":
                    fill, mark = PatternFill("solid", fgColor="D9EAD3"), "🟢"
                elif typ == "테스트교환":
                    fill, mark = PatternFill("solid", fgColor="EADCF8"), "🧪"
                elif typ == "시간강사":
                    fill, mark = PatternFill("solid", fgColor="FCE5CD"), "🟡"
                else:
                    fill, mark = fill_day[i], ""
                ws.cell(row, cc).fill = fill
                ws.cell(row + 1, cc).fill = fill
                if mark:
                    ws.cell(row, cc).value = f"{subj} {mark}".strip()
        row += 2
    ws.freeze_panes = "C5"
    ws.sheet_view.showGridLines = False
    ws.page_setup.orientation = "landscape"
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_margins = PageMargins(left=0.25, right=0.25, top=0.4, bottom=0.4, header=0.2, footer=0.2)
    return _workbook_bytes(wb)


def build_weekly_class_schedule_excel_bytes(ref_date: date, *, use_test=False, title="전체 학급 시간표",
                                            neis_blocked: set | None = None) -> bytes:
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, Alignment, Border, Side, PatternFill
        from openpyxl.utils import get_column_letter
        from openpyxl.worksheet.page import PageMargins
    except Exception as exc:
        raise RuntimeError(f"openpyxl 미설치: {exc}")
    if isinstance(ref_date, str):
        ref_date = date.fromisoformat(normalize_date_str(ref_date))
    monday = ref_date - timedelta(days=ref_date.weekday())
    wb = Workbook()
    ws = wb.active
    ws.title = "전체 학급 시간표"
    title_font = Font(name="돋움", size=20, bold=True)
    small_font = Font(name="돋움", size=8)
    head_font = Font(name="돋움", size=9, bold=True)
    body_font = Font(name="돋움", size=8)
    thin = Side(style="hair", color="B7B7B7")
    fill_head = PatternFill("solid", fgColor="D9EAF7")
    fill_day = [PatternFill("solid", fgColor=x) for x in ("DDEBF7", "E2F0D9", "FFF2CC", "E4DFEC", "FCE4D6")]
    periods = {d: list(range(1, C.PERIODS_PER_DAY.get(d, 7) + 1)) for d in C.DAYS}
    col = 3
    day_ranges = {}
    for i, d in enumerate(C.DAYS):
        start, end = col, col + len(periods[d]) - 1
        day_ranges[d] = (start, end)
        col = end + 1
    last_col = col - 1
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=last_col)
    ws["A1"] = title
    ws["A1"].font = title_font
    ws["A1"].alignment = Alignment(horizontal="center", vertical="center")
    ws.merge_cells(start_row=2, start_column=1, end_row=2, end_column=2)
    ws["A2"] = f"{C.SCHOOL_YEAR} 학년도"
    ws["A2"].font = small_font
    ws.merge_cells(start_row=2, start_column=last_col - 4, end_row=2, end_column=last_col)
    ws.cell(2, last_col - 4).value = C.SCHOOL_NAME
    ws.cell(2, last_col - 4).font = small_font
    ws["A3"] = "번호"
    ws["B3"] = "학급"
    ws.merge_cells("A3:A4")
    ws.merge_cells("B3:B4")
    for i, d in enumerate(C.DAYS):
        start, end = day_ranges[d]
        ws.merge_cells(start_row=3, start_column=start, end_row=3, end_column=end)
        cell = ws.cell(3, start)
        cell.value = f"{d}({(monday + timedelta(days=i)):%m/%d})"
        cell.font = head_font
        cell.alignment = Alignment(horizontal="center", vertical="center")
        cell.fill = fill_day[i]
        for pno in periods[d]:
            pc = ws.cell(4, start + pno - 1)
            pc.value = pno
            pc.font = head_font
            pc.alignment = Alignment(horizontal="center", vertical="center")
            pc.fill = fill_day[i]
    daily = {}
    classes: set = set()
    for i, d in enumerate(C.DAYS):
        ds = (monday + timedelta(days=i)).strftime("%Y-%m-%d")
        e = get_effective_timetable_for_date(ds, use_test=use_test, neis_blocked=neis_blocked)
        daily[d] = {(str(r.학급).strip(), safe_int(r.교시)): r for r in e.itertuples(index=False) if str(getattr(r, "학급", "")).strip()} if not e.empty else {}
        classes.update(k[0] for k in daily[d])
    row = 5
    for n, cls in enumerate(sorted(classes), 1):
        ws.merge_cells(start_row=row, start_column=1, end_row=row + 1, end_column=1)
        ws.merge_cells(start_row=row, start_column=2, end_row=row + 1, end_column=2)
        ws.cell(row, 1).value = n
        ws.cell(row, 2).value = cls
        for rr in (row, row + 1):
            for cc in range(1, last_col + 1):
                c = ws.cell(rr, cc)
                c.font = body_font
                c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
                c.border = Border(left=thin, right=thin, top=thin, bottom=thin)
        for i, d in enumerate(C.DAYS):
            for pno in periods[d]:
                r = daily[d].get((cls, pno))
                cc = day_ranges[d][0] + pno - 1
                if r is None:
                    continue
                subj = str(getattr(r, "과목", "")).strip()
                teacher = str(getattr(r, "교사명", "")).strip()
                typ = str(getattr(r, "변경유형", "원본")).strip()
                ws.cell(row, cc).value = subj
                ws.cell(row + 1, cc).value = teacher
                fill, mark = fill_day[i], ""
                if typ == "교환":
                    fill, mark = PatternFill("solid", fgColor="F4CCCC"), " 🔄"
                elif typ == "보강":
                    fill, mark = PatternFill("solid", fgColor="D9EAD3"), " 🟢"
                elif typ == "테스트교환":
                    fill, mark = PatternFill("solid", fgColor="EADCF8"), " 🧪"
                elif typ == "시간강사":
                    fill, mark = PatternFill("solid", fgColor="FCE5CD"), " 🟡"
                ws.cell(row, cc).value = f"{subj}{mark}".strip()
                ws.cell(row, cc).fill = fill
                ws.cell(row + 1, cc).fill = fill
        row += 2
    ws.freeze_panes = "C5"
    return _workbook_bytes(wb)


def _esc(v):
    if v is None:
        return ""
    return html_lib.escape(str(v))


def build_report_html(norm_date: str, absences_df=None, subs_df=None, swaps_df=None) -> str:
    if not HAS_PANDAS:
        return f"<html><body>{_esc(norm_date)} 리포트 (pandas 미설치)</body></html>"
    norm = normalize_date_str(norm_date)
    try:
        day = C.WEEKDAY_KR[datetime.strptime(norm, "%Y-%m-%d").weekday()]
    except Exception:
        day = ""
    absences = absences_df if absences_df is not None else get_table("absences")
    subs = subs_df if subs_df is not None else get_table("subs")
    swaps = swaps_df if swaps_df is not None else get_table("swaps")

    def rows_abs():
        if absences is None or absences.empty:
            return "<tr><td colspan='6'>결강 없음</td></tr>"
        try:
            m = absences[absences["일자"] == norm]
        except Exception:
            return ""
        if m.empty:
            return "<tr><td colspan='6'>결강 없음</td></tr>"
        out = []
        for _, r in m.iterrows():
            out.append(f"<tr><td>{_esc(r.get('교사명'))}</td><td>{_esc(r.get('사유'))}</td><td>{safe_int(r.get('교시'))}</td>"
                       f"<td>{_esc(r.get('학급'))}</td><td>{_esc(r.get('과목'))}</td><td>{_esc(r.get('상세사유'))}</td></tr>")
        return "".join(out)

    def rows_sub():
        if subs is None or subs.empty:
            return "<tr><td colspan='7'>보강 없음</td></tr>"
        try:
            m = subs[subs["일자"] == norm]
        except Exception:
            return ""
        if m.empty:
            return "<tr><td colspan='7'>보강 없음</td></tr>"
        out = []
        for _, r in m.iterrows():
            out.append(f"<tr><td>{safe_int(r.get('교시'))}</td><td>{_esc(r.get('학급'))}</td><td>{_esc(r.get('과목'))}</td>"
                       f"<td>{_esc(r.get('결강교사'))}</td><td>{_esc(r.get('보강교사'))}</td>"
                       f"<td>{_esc(r.get('배정방식'))}</td><td>{_esc(r.get('비고'))}</td></tr>")
        return "".join(out)

    def rows_swap():
        if swaps is None or swaps.empty:
            return "<tr><td colspan='4'>맞교환 없음</td></tr>"
        try:
            m = swaps[(swaps["원본일자"] == norm) | (swaps["목표일자"] == norm)]
        except Exception:
            return ""
        if m.empty:
            return "<tr><td colspan='4'>맞교환 없음</td></tr>"
        out = []
        for _, r in m.iterrows():
            out.append(f"<tr><td>{_esc(r.get('교사A'))} {safe_int(r.get('교시A'))}</td><td>{_esc(r.get('학급A'))} {_esc(r.get('과목A'))}</td>"
                       f"<td>{_esc(r.get('교사B'))} {safe_int(r.get('교시B'))}</td><td>{_esc(r.get('유형'))}</td></tr>")
        return "".join(out)

    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>일간리포트 {norm}</title>
<style>table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #333;padding:4px;text-align:center}}</style></head><body>
<h1>일간 운영 리포트</h1>
<div style="text-align:center">{C.SCHOOL_YEAR} · {C.SCHOOL_NAME} · {norm} ({day})</div>
<h3>1. 결강 현황</h3>
<table><tr><th>교사</th><th>사유</th><th>교시</th><th>학급</th><th>과목</th><th>상세</th></tr>{rows_abs()}</table>
<h3>2. 보강 배정</h3>
<table><tr><th>교시</th><th>학급</th><th>과목</th><th>결강교사</th><th>보강교사</th><th>근거</th><th>비고</th></tr>{rows_sub()}</table>
<h3>3. 맞교환</h3>
<table><tr><th>교사A</th><th>내용</th><th>교사B</th><th>유형</th></tr>{rows_swap()}</table>
</body></html>"""


def build_personal_plan_html(teacher_name: str, on_date: str, absences_df=None, subs_df=None, swaps_df=None) -> str:
    norm = normalize_date_str(on_date)
    try:
        dt = datetime.strptime(norm, "%Y-%m-%d")
        day_kr = C.WEEKDAY_KR[dt.weekday()]
        date_display = f"{dt.year}년 {dt.month}월 {dt.day}일 ({day_kr})"
    except Exception:
        date_display = norm
    if not HAS_PANDAS:
        return f"<html><body>{_esc(teacher_name)} {date_display} 계획서</body></html>"
    absences = absences_df if absences_df is not None else get_table("absences")
    subs = subs_df if subs_df is not None else get_table("subs")
    swaps = swaps_df if swaps_df is not None else get_table("swaps")
    e = get_effective_timetable_for_date(norm)
    rows = ""
    try:
        mine = e[e["교사명"] == teacher_name].sort_values("교시") if not e.empty else pd.DataFrame()
        for _, r in mine.iterrows():
            rows += f"<tr><td>{safe_int(r.get('교시'))}</td><td>{_esc(r.get('학급'))}</td><td>{_esc(r.get('과목'))}</td><td>{_esc(r.get('변경유형'))}</td><td>{_esc(r.get('변경출처'))}</td></tr>"
        if not rows:
            rows = "<tr><td colspan='5'>수업 없음</td></tr>"
    except Exception:
        rows = "<tr><td colspan='5'>조회 실패</td></tr>"
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>결·보강 계획서 - {_esc(teacher_name)}</title>
<style>table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #000;padding:4px;text-align:center}}</style></head><body>
<h1 style="text-align:center">결·보강 계획서</h1>
<p>{_esc(teacher_name)} / {date_display} / {C.SCHOOL_NAME}</p>
<table><tr><th>교시</th><th>학급</th><th>과목</th><th>유형</th><th>비고</th></tr>{rows}</table>
</body></html>"""


def build_test_swaps_report_html(test_swaps_df=None) -> str:
    if not HAS_PANDAS:
        return "<html><body>테스트 리포트 (pandas 미설치)</body></html>"
    ts = test_swaps_df if test_swaps_df is not None else get_table("test_swaps")
    rows = ""
    try:
        if ts is None or ts.empty:
            rows = "<tr><td colspan='6'>테스트 교환 없음</td></tr>"
        else:
            for _, r in ts.iterrows():
                rows += f"<tr><td>{_esc(r.get('원본일자'))}</td><td>{_esc(r.get('교사A'))} {safe_int(r.get('교시A'))}</td>"
                rows += f"<td>{_esc(r.get('목표일자'))}</td><td>{_esc(r.get('교사B'))} {safe_int(r.get('교시B'))}</td>"
                rows += f"<td>{_esc(r.get('유형'))}</td><td>{_esc(r.get('변경ID'))}</td></tr>"
    except Exception:
        rows = "<tr><td colspan='6'>조회 실패</td></tr>"
    return f"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><title>테스트 교환 리포트</title>
<style>table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #333;padding:4px;text-align:center}}</style></head><body>
<h1>시간표 변경 테스트 리포트</h1>
<table><tr><th>원본일자</th><th>교사A</th><th>목표일자</th><th>교사B</th><th>유형</th><th>ID</th></tr>{rows}</table>
</body></html>"""


# ------------------------------------------------- id sheets helpers

def ensure_duty_columns(df):
    if not HAS_PANDAS:
        return df
    if df is None or not isinstance(df, pd.DataFrame):
        return pd.DataFrame(columns=list(C.DUTY_COLS))
    out = df.copy()
    for c in C.DUTY_COLS:
        if c not in out.columns:
            out[c] = 0 if c == "교시" else ""
    try:
        out["교시"] = out["교시"].apply(safe_int)
    except Exception:
        pass
    return out


def ensure_part_time_columns(df):
    if not HAS_PANDAS:
        return df
    base = ["번호", "시간강사명", "담당과목", "과목군", "비고"] + list(C.PART_TIME_EXTRA_COLS) + [f"{d}{p}" for d in C.DAYS for p in range(1, 8)]
    if df is None or not isinstance(df, pd.DataFrame):
        return pd.DataFrame(columns=base)
    out = df.copy()
    for c in base:
        if c not in out.columns:
            out[c] = ""
    for c in ["시작일", "종료일"]:
        if c in out.columns:
            try:
                out[c] = out[c].apply(normalize_date_str)
            except Exception:
                pass
    return out


def validate_part_time_table(df):
    if not HAS_PANDAS or df is None or getattr(df, "empty", True):
        return True, ""
    seen: dict = {}
    try:
        for _, r in df.iterrows():
            name = str(r.get("시간강사명", "")).strip()
            orig = str(r.get("대체교사", "")).strip()
            start, end = normalize_date_str(r.get("시작일", "")), normalize_date_str(r.get("종료일", ""))
            if not name or not orig or not start or not end:
                continue
            if start > end:
                return False, f"시간강사 {name}: 시작일이 종료일보다 늦습니다."
            for d in C.DAYS:
                for p in range(1, 8):
                    if _part_time_available(r, d, p):
                        key = (orig, d, p)
                        if key in seen:
                            return False, f"{orig}의 {d}{p}교시 시간강사 대체가 중복됩니다."
                        seen[key] = name
    except Exception as exc:
        return False, str(exc)
    return True, ""

# ===== neis =====
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

# ===== salary_ai =====
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
                {"text": C.SALARY_GEMINI_PROMPT},
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

# ===== main =====
app = FastAPI(title="Timetable Backend", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_login_failures: dict = {}
_login_lock = __import__("threading").RLock()


def _df_to_records(df):
    if not HAS_PANDAS or df is None or getattr(df, "empty", True):
        return []
    try:
        return df.fillna("").to_dict("records")
    except Exception:
        return []


def _parse_date(s: str) -> date:
    s = normalize_date_str(s)
    return date.fromisoformat(s)


# ---------------- models
class LoginIn(BaseModel):
    id: str = ""


class GuestIn(BaseModel):
    name: str = ""


class IdRequestIn(BaseModel):
    name: str = ""
    email: str = ""
    desired_id: str = ""
    memo: str = ""


class AbsenceIn(BaseModel):
    cid: str = ""
    date: str = ""
    day: str = ""
    period: int = 0
    class_name: str = ""
    subject: str = ""
    teacher: str = ""
    reason: str = ""
    detail: str = ""
    user: str = ""


class SubRecommendIn(BaseModel):
    day: str = ""
    period: int = 0
    subject: str = ""
    class_name: str = ""
    absent_teacher: str = ""
    date: str = ""
    top_n: int = 20
    include_part_time: bool = False


class SubValidateIn(BaseModel):
    cid: str = ""
    date: str = ""
    period: int = 0
    class_name: str = ""
    subject: str = ""
    absent_teacher: str = ""
    sub_teacher: str = ""


class SubIn(BaseModel):
    cid: str = ""
    date: str = ""
    day: str = ""
    period: int = 0
    class_name: str = ""
    subject: str = ""
    absent_teacher: str = ""
    sub_teacher: str = ""
    method: str = ""
    priority: str = ""
    memo: str = ""
    user: str = ""


class SubBatchIn(BaseModel):
    assignments: list[dict] = []
    user: str = ""


class SubDeleteIn(BaseModel):
    cid: str = ""
    period: int = 0


class SwapValidateIn(BaseModel):
    a: dict = {}
    b: dict = {}
    date_a: str = ""
    date_b: str = ""
    is_test: bool = False


class SwapIn(BaseModel):
    a: dict = {}
    b: dict = {}
    date_a: str = ""
    date_b: str = ""
    is_test: bool = False
    is_part_time_purpose: bool = False
    user: str = ""


class LinkedSwapIn(BaseModel):
    a: dict = {}
    teacher_b: str = ""
    date_a: str = ""
    date_b: str = ""
    day_b: str = ""
    period_b: int = 0
    is_test: bool = False
    is_part_time_purpose: bool = False
    subject_b: str | None = None
    user: str = ""


class CycleSwapIn(BaseModel):
    moves: list[dict] = []
    is_test: bool = False
    user: str = ""


class TargetRecommendIn(BaseModel):
    teacher_a: str = ""
    date_a: str = ""
    period_a: int = 0
    class_a: str = ""
    subject_a: str = ""
    date_b: str = ""
    period_b: int = 0
    budget_factor: float = 1.0


class CycleSearchIn(BaseModel):
    teacher_a: str = ""
    date_a: str = ""
    period_a: int = 0
    class_a: str = ""
    subject_a: str = ""
    date_b: str = ""
    period_b: int = 0
    max_cycle: int = 3
    use_test: bool = False


class PartTimeIn(BaseModel):
    row: dict = {}
    user: str = ""


class DutyIn(BaseModel):
    teacher: str = ""
    date: str = ""
    period: int = 0
    reason: str = ""
    detail: str = ""
    user: str = ""


class BudgetIn(BaseModel):
    change: int = 0
    reason: str = "보강"


class SalaryCalcIn(BaseModel):
    name: str = ""
    calc_date: str = ""
    org: str = ""
    position: str = "기간제교사"
    writer_name: str = ""
    writer_pos: str = ""
    base_value: int = 8
    qual_label: str = "정교사(2급)"
    academic_value: int = 0
    academic_label: str = ""
    is_sabom: bool = True
    degrees: list[dict] = []
    careers: list[dict] = []


# ---------------- startup: 시트 초기 로드 (없으면 빈 테이블 + 경고, 부팅은 보장)
@app.on_event("startup")
def _startup_load_sheets():
    try:
        load_timetable()
    except Exception:
        pass
    try:
        load_work()
    except Exception:
        pass
    try:
        push_history("시작 상태")
    except Exception:
        pass


# ---------------- health/meta
@app.get("/api/health")
def health():
    return {"ok": True, "version": "1.0.0", "has_pandas": HAS_PANDAS}


@app.get("/api/meta")
def meta():
    return {
        "tabs": C.ALL_APP_TABS,
        "roles": [C.ROLE_MASTER, C.ROLE_EDU, C.ROLE_OFFICE, C.ROLE_TEACHER, C.ROLE_GUEST],
        "days": C.DAYS,
        "periods_per_day": C.PERIODS_PER_DAY,
        "max_period": C.MAX_PERIOD,
        "school": {"name": C.SCHOOL_NAME, "year": C.SCHOOL_YEAR},
        "version": get_version(),
    }


# ---------------- auth
def _is_rate_limited(uid: str) -> bool:
    now = time.time()
    with _login_lock:
        arr = [t for t in _login_failures.get(uid, []) if now - t < 300]
        _login_failures[uid] = arr
        return len(arr) >= C.MAX_LOGIN_ATTEMPTS


@app.post("/api/auth/login")
def login(body: LoginIn, request: Request):
    uid = str(body.id or "").strip()[:C.MAX_ID_LENGTH]
    if not uid:
        return JSONResponse({"ok": False, "error": "아이디 필요"}, status_code=400)
    key = request.client.host if request.client else "anon"
    bucket = f"{key}:{uid}"
    if _is_rate_limited(bucket):
        return JSONResponse({"ok": False, "error": "잠시 후 다시 시도"}, status_code=429)
    ids = get_table("ids")
    role = C.ROLE_TEACHER
    name = uid
    found = False
    allowed_raw = ""
    if HAS_PANDAS and ids is not None and not ids.empty:
        try:
            for col in ("아이디", "id", "ID"):
                if col in ids.columns:
                    m = ids[ids[col].astype(str).str.strip() == uid]
                    if not m.empty:
                        found = True
                        r = m.iloc[0]
                        for rc in ("역할", "role", "권한"):
                            if rc in ids.columns and str(r.get(rc, "")).strip():
                                role = str(r.get(rc)).strip()
                                break
                        for nc in ("이름", "성명", "교사명", "name"):
                            if nc in ids.columns and str(r.get(nc, "")).strip():
                                name = str(r.get(nc)).strip()
                                break
                        for tc in ("허용탭", "allowed_tabs", "allowedTabs"):
                            if tc in ids.columns and str(r.get(tc, "")).strip():
                                allowed_raw = str(r.get(tc)).strip()
                                break
                        break
        except Exception:
            pass
    if uid == C.MASTER_ID:
        role, found = C.ROLE_MASTER, True
    if not found:
        with _login_lock:
            _login_failures.setdefault(bucket, []).append(time.time())
        return JSONResponse({"ok": False, "error": "등록되지 않은 아이디"}, status_code=401)
    with _login_lock:
        _login_failures.pop(bucket, None)
    tabs = [t.strip() for t in allowed_raw.split(",") if t.strip()] if allowed_raw.strip() else list(C.DEFAULT_TABS.get(role, []))
    return {"ok": True, "id": uid, "name": name, "role": role, "allowedTabs": tabs}


@app.post("/api/auth/guest")
def guest(body: GuestIn):
    return {"ok": True, "role": C.ROLE_GUEST, "name": body.name or "게스트"}


@app.post("/api/auth/request-id")
def request_id(body: IdRequestIn):
    reqs = get_table("ids")
    # 아이디추가요청 시트에 append (인메모리 + 시트 저장 시도)
    if HAS_PANDAS:
        try:
            cur = store.tables.get("id_requests")
            new = pd.DataFrame([{
                "이름": body.name, "이메일": body.email, "희망ID": body.desired_id,
                "메모": body.memo, "신청시각": _now_text(),
            }])
            store.tables["id_requests"] = pd.concat([cur, new], ignore_index=True) if cur is not None and not cur.empty else new
            store.save(["아이디추가요청"])
        except Exception:
            pass
    return {"ok": True}


# ---------------- timetable/teachers
@app.get("/api/timetable")
def get_timetable():
    return {"records": _df_to_records(get_table("timetable")), "version": get_version()}


@app.get("/api/teachers")
def get_teachers():
    return {"records": _df_to_records(get_table("teachers")), "names": get_all_teacher_names()}


@app.get("/api/effective-day")
def effective_day(date: str = Query(""), useTest: bool = Query(False)):
    df = get_effective_timetable_for_date(date, use_test=bool(useTest))
    return {"date": normalize_date_str(date), "records": _df_to_records(df)}


@app.get("/api/effective-week")
def effective_week(refDate: str = Query(""), useTest: bool = Query(False)):
    try:
        rd = _parse_date(refDate) if refDate else date.today()
    except Exception:
        rd = date.today()
    data = get_effective_week(rd, use_test=bool(useTest))
    return {"refDate": rd.isoformat(), "days": {k: _df_to_records(v) for k, v in data.items()}}


@app.get("/api/teacher-week")
def teacher_week(teacher: str = Query(""), refDate: str = Query(""), useTest: bool = Query(False)):
    try:
        rd = _parse_date(refDate) if refDate else date.today()
    except Exception:
        rd = date.today()
    df, week = get_teacher_week_view(teacher, rd, use_test=bool(useTest))
    return {"teacher": teacher, "records": _df_to_records(df),
            "week": [d.isoformat() for d in week]}


@app.get("/api/changed-teachers")
def changed_teachers(refDate: str = Query("")):
    try:
        rd = _parse_date(refDate) if refDate else date.today()
    except Exception:
        rd = date.today()
    return {"teachers": get_changed_teachers_for_week(rd)}


# ---------------- absences
@app.get("/api/absences")
def list_absences():
    return {"records": _df_to_records(get_table("absences"))}


@app.post("/api/absences")
def create_absence(body: AbsenceIn):
    if not HAS_PANDAS:
        return JSONResponse({"ok": False, "error": "pandas 미설치"}, status_code=500)
    norm = normalize_date_str(body.date)
    if not norm or not body.teacher or safe_period(body.period) <= 0:
        return JSONResponse({"ok": False, "error": "필수값 누락"}, status_code=400)
    cur = get_table("absences")
    new = pd.DataFrame([{
        "결강ID": body.cid or _new_change_id("ABS"), "일자": norm, "요일": body.day,
        "교시": int(body.period), "학급": body.class_name, "과목": body.subject,
        "교사명": body.teacher, "사유": body.reason, "상세사유": body.detail,
        "등록시각": _now_text(), "입력자": body.user,
    }])
    try:
        store.tables["absences"] = pd.concat([cur, new], ignore_index=True) if not cur.empty else new
        store.save(["결강"])
        store.push_history("결강 등록")
        store.invalidate()
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)
    return {"ok": True}


def safe_period(p):
    try:
        return int(p)
    except Exception:
        return 0


# ---------------- subs
@app.post("/api/subs/recommend")
def subs_recommend(body: SubRecommendIn):
    df = recommend_substitutes(body.day, body.period, body.subject, body.class_name,
                                 body.absent_teacher, body.date, top_n=body.top_n,
                                 include_part_time=body.include_part_time)
    return {"records": _df_to_records(df)}


@app.post("/api/subs/validate")
def subs_validate(body: SubValidateIn):
    ok, msg = validate_substitute(body.cid, body.date, body.period, body.class_name,
                                    body.subject, body.absent_teacher, body.sub_teacher)
    return {"ok": ok, "message": msg}


@app.post("/api/subs")
def subs_create(body: SubIn):
    ok, msg = add_substitute(body.cid or _new_change_id("ABS"), body.date, body.day, body.period,
                               body.class_name, body.subject, body.absent_teacher, body.sub_teacher,
                               body.method, body.priority, body.memo, user=body.user)
    if not ok:
        return JSONResponse({"ok": False, "error": msg}, status_code=400)
    return {"ok": True}


@app.post("/api/subs/batch")
def subs_batch(body: SubBatchIn):
    accepted, errors = add_substitutes_batch(body.assignments, user=body.user)
    return {"accepted": accepted, "errors": errors}


@app.delete("/api/subs")
def subs_delete(cid: str = Query(""), period: int = Query(0)):
    ok, msg = cancel_substitute(cid, period)
    if not ok:
        return JSONResponse({"ok": False, "error": msg}, status_code=400)
    return {"ok": True}


# ---------------- swaps
@app.post("/api/swaps/validate")
def swaps_validate(body: SwapValidateIn):
    ok, msg = validate_swap(body.a, body.b, body.date_a, body.date_b, is_test=body.is_test)
    return {"ok": ok, "message": msg}


@app.post("/api/swaps")
def swaps_create(body: SwapIn):
    ok, msg = do_swap(body.a, body.b, body.date_a, body.date_b,
                         is_part_time_purpose=body.is_part_time_purpose,
                         is_test=body.is_test, user=body.user)
    if not ok:
        return JSONResponse({"ok": False, "error": msg}, status_code=400)
    return {"ok": True}


@app.post("/api/swaps/linked")
def swaps_linked(body: LinkedSwapIn):
    ok, msg = do_linked_swap(body.a, body.teacher_b, body.date_a, body.date_b,
                                body.day_b, body.period_b,
                                is_part_time_purpose=body.is_part_time_purpose,
                                is_test=body.is_test, subject_b=body.subject_b, user=body.user)
    if not ok:
        return JSONResponse({"ok": False, "error": msg}, status_code=400)
    return {"ok": True}


@app.post("/api/swaps/cycle")
def swaps_cycle(body: CycleSwapIn):
    ok, msg = apply_cycle_swaps(body.moves, is_test=body.is_test, user=body.user)
    if not ok:
        return JSONResponse({"ok": False, "error": msg}, status_code=400)
    return {"ok": True}


@app.post("/api/swaps/target-recommend")
def swaps_target(body: TargetRecommendIn):
    df, cycles, msg = get_target_time_recommendations(
        body.teacher_a, body.date_a, body.period_a, body.class_a, body.subject_a,
        body.date_b, body.period_b, budget_factor=body.budget_factor)
    return {"records": _df_to_records(df), "cycles": cycles, "message": msg}


@app.post("/api/swaps/cycles-search")
def swaps_cycles(body: CycleSearchIn):
    cycles, msg = find_cycle_linked_swaps(
        body.teacher_a, body.date_a, body.period_a, body.class_a, body.subject_a,
        body.date_b, body.period_b, max_cycle=body.max_cycle, use_test=body.use_test)
    return {"cycles": cycles, "message": msg}


@app.get("/api/swaps/weekly-1to1")
def swaps_weekly(teacher: str = Query(""), refDate: str = Query(""), futureDays: int = Query(0)):
    try:
        rd = _parse_date(refDate) if refDate else date.today()
    except Exception:
        rd = date.today()
    df = get_weekly_1to1_swap_table(teacher, rd, future_days=int(futureDays or 0))
    return {"records": _df_to_records(df)}


# ---------------- part-time / duties
@app.get("/api/part-time")
def pt_list():
    df = get_table("part_time")
    ok, msg = validate_part_time_table(df)
    return {"records": _df_to_records(df), "valid": ok, "message": msg}


@app.post("/api/part-time")
def pt_create(body: PartTimeIn):
    if not HAS_PANDAS:
        return JSONResponse({"ok": False, "error": "pandas 미설치"}, status_code=500)
    row = dict(body.row or {})
    cur = get_table("part_time")
    try:
        new = pd.DataFrame([row])
        store.tables["part_time"] = pd.concat([cur, new], ignore_index=True) if not cur.empty else new
        ok, msg = validate_part_time_table(store.tables["part_time"])
        if not ok:
            store.tables["part_time"] = cur
            return JSONResponse({"ok": False, "error": msg}, status_code=400)
        store.save(["시간강사"])
        store.push_history("시간강사 등록")
        store.invalidate()
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)
    return {"ok": True}


@app.get("/api/duties")
def duties_list():
    return {"records": _df_to_records(get_table("duties"))}


@app.post("/api/duties")
def duties_create(body: DutyIn):
    if not HAS_PANDAS:
        return JSONResponse({"ok": False, "error": "pandas 미설치"}, status_code=500)
    norm = normalize_date_str(body.date)
    cur = get_table("duties")
    try:
        new = pd.DataFrame([{
            "교사명": body.teacher, "일자": norm, "교시": int(body.period),
            "사유": body.reason, "상세사유": body.detail,
            "등록시각": _now_text(), "입력자": body.user,
        }])
        store.tables["duties"] = pd.concat([cur, new], ignore_index=True) if not cur.empty else new
        store.save(["복무"])
        store.push_history("복무 등록")
        store.invalidate()
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)
    return {"ok": True}


# ---------------- budget/stats
@app.get("/api/budget")
def budget_get():
    df = get_table("budget")
    return {"balance": get_current_budget(df), "records": _df_to_records(df)}


@app.post("/api/budget")
def budget_post(body: BudgetIn):
    v = update_budget(int(body.change), body.reason)
    if v is None:
        return JSONResponse({"ok": False, "error": "예산 저장 실패"}, status_code=500)
    return {"ok": True, "balance": v}


@app.get("/api/stats")
def stats():
    return {
        "cumulative": cumulative_sub_count(),
        "weekly_load": weekly_load(),
        "budget": get_current_budget(),
    }


# ---------------- neis
@app.get("/api/neis/week")
def neis_week(refDate: str = Query("")):
    try:
        rd = _parse_date(refDate) if refDate else date.today()
    except Exception:
        rd = date.today()
    monday = rd - timedelta(days=rd.weekday())
    friday = monday + timedelta(days=4)
    key = (os.getenv("NEIS_API_KEY", "") or "").strip()
    if not key:
        return {"records": [], "error": "NEIS_API_KEY 미설정"}
    try:
        df = fetch_schedule(key, C.SCHOOL_NAME, monday.isoformat(), friday.isoformat())
        # 캐시 저장 (effective 계산용)
        try:
            store.tables["neis_cache"] = df
        except Exception:
            pass
        return {"records": _df_to_records(df)}
    except Exception as exc:
        return JSONResponse({"records": [], "error": str(exc)}, status_code=502)


@app.post("/api/neis/refresh")
def neis_refresh(body: dict = {}):
    ref = str((body or {}).get("refDate", "") or "")
    try:
        rd = _parse_date(ref) if ref else date.today()
    except Exception:
        rd = date.today()
    monday = rd - timedelta(days=rd.weekday())
    friday = monday + timedelta(days=4)
    key = str((body or {}).get("apiKey", "") or os.getenv("NEIS_API_KEY", "") or "").strip()
    if not key:
        return JSONResponse({"ok": False, "error": "NEIS_API_KEY 미설정"}, status_code=400)
    try:
        # 캐시 무효화
        _schedule_cache.clear()
        df = fetch_schedule(key, C.SCHOOL_NAME, monday.isoformat(), friday.isoformat())
        store.tables["neis_cache"] = df
        store.invalidate()
        return {"ok": True, "records": _df_to_records(df)}
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=502)


# ---------------- export/report
@app.get("/api/export/teacher-week.xlsx")
def export_teacher(refDate: str = Query(""), useTest: bool = Query(False)):
    try:
        rd = _parse_date(refDate) if refDate else date.today()
    except Exception:
        rd = date.today()
    try:
        data = build_weekly_schedule_excel_bytes(rd, use_test=bool(useTest))
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)
    return Response(content=data,
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": "attachment; filename=teacher-week.xlsx"})


@app.get("/api/export/class-week.xlsx")
def export_class(refDate: str = Query(""), useTest: bool = Query(False)):
    try:
        rd = _parse_date(refDate) if refDate else date.today()
    except Exception:
        rd = date.today()
    try:
        data = build_weekly_class_schedule_excel_bytes(rd, use_test=bool(useTest))
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)
    return Response(content=data,
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": "attachment; filename=class-week.xlsx"})


@app.get("/api/report/daily.html", response_class=HTMLResponse)
def report_daily(date: str = Query("")):
    return build_report_html(date)


@app.get("/api/report/personal.html", response_class=HTMLResponse)
def report_personal(teacher: str = Query(""), date: str = Query("")):
    return build_personal_plan_html(teacher, date)


@app.get("/api/report/test.html", response_class=HTMLResponse)
def report_test():
    return build_test_swaps_report_html()


# ---------------- salary
@app.post("/api/salary/calculate")
def salary_calc(body: SalaryCalcIn):
    if not HAS_PANDAS:
        return JSONResponse({"ok": False, "error": "pandas 미설치"}, status_code=500)
    try:
        deg = pd.DataFrame(body.degrees) if body.degrees else pd.DataFrame(columns=["학위 구분", "학교/전공 세부명", "입학일", "졸업일", "환산율"])
        car = pd.DataFrame(body.careers) if body.careers else pd.DataFrame(columns=["경력 종류", "세부 근무처/직위", "시작일", "종료일", "종료일 산입", "환산율 (%)"])
    except Exception:
        deg, car = pd.DataFrame(), pd.DataFrame()
    calc_date = _salary_safe_date(body.calc_date) or date.today()
    res = _salary_calculate(body.name, calc_date, body.org, body.position,
                              body.writer_name, body.writer_pos, body.base_value,
                              body.qual_label, body.academic_value, body.academic_label,
                              body.is_sabom, deg, car)
    # date 직렬화
    out = dict(res)
    try:
        out["calc_date"] = calc_date.isoformat()
        for d in out.get("details", []):
            for k in ("시작일", "종료일"):
                v = d.get(k)
                if isinstance(v, (date, datetime)):
                    d[k] = v.isoformat()
                elif v is None:
                    d[k] = ""
    except Exception:
        pass
    out["html"] = _salary_report_html(res)
    return out


@app.post("/api/salary/analyze")
async def salary_analyze(request: Request):
    form = await request.form()
    f = form.get("file")
    if f is None:
        return JSONResponse({"ok": False, "error": "파일 없음"}, status_code=400)
    try:
        raw = await f.read()
        data = analyze_file(raw, filename=getattr(f, "filename", "") or "",
                               mime_type=getattr(f, "content_type", "") or "")
        return {"ok": True, "data": data}
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)


# ---------------- admin/history
@app.get("/api/admin/ids")
def admin_ids():
    return {"records": _df_to_records(get_table("ids"))}


@app.post("/api/admin/ids")
def admin_ids_save(body: dict):
    if not HAS_PANDAS:
        return JSONResponse({"ok": False, "error": "pandas 미설치"}, status_code=500)
    records = (body or {}).get("records", [])
    try:
        df = pd.DataFrame(records)
        store.tables["ids"] = df
        store.save(["아이디저장함"])
        return {"ok": True}
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)


@app.post("/api/history/undo")
def hist_undo():
    return {"ok": undo()}


@app.post("/api/history/redo")
def hist_redo():
    return {"ok": redo()}
