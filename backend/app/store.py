"""인메모리 + 구글시트 동기화 스토어. 스레드안전."""
from __future__ import annotations

import copy
import os
import threading
from datetime import datetime
from zoneinfo import ZoneInfo

try:
    import pandas as pd
    HAS_PANDAS = True
except Exception:  # pragma: no cover
    pd = None  # type: ignore
    HAS_PANDAS = False

from . import config as C

KST = ZoneInfo("Asia/Seoul")

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


def _empty_df(columns):
    if not HAS_PANDAS:
        return []
    return pd.DataFrame(columns=list(columns))


def _now_text(fmt="%Y-%m-%d %H:%M:%S"):
    try:
        return datetime.now(KST).strftime(fmt)
    except Exception:
        return datetime.now().strftime(fmt)


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
