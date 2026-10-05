"""FastAPI 앱."""
from __future__ import annotations

import base64
import os
import time
from datetime import date, datetime, timedelta
from typing import Any

from fastapi import FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel

from . import config as C
from . import logic as L
from . import store as S

try:
    import pandas as pd
    HAS_PANDAS = True
except Exception:  # pragma: no cover
    pd = None  # type: ignore
    HAS_PANDAS = False

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
    s = L.normalize_date_str(s)
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
        "version": S.get_version(),
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
    ids = S.get_table("ids")
    role = C.ROLE_TEACHER
    name = uid
    found = False
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
    return {"ok": True, "id": uid, "name": name, "role": role}


@app.post("/api/auth/guest")
def guest(body: GuestIn):
    return {"ok": True, "role": C.ROLE_GUEST, "name": body.name or "게스트"}


@app.post("/api/auth/request-id")
def request_id(body: IdRequestIn):
    reqs = S.get_table("ids")
    # 아이디추가요청 시트에 append (인메모리 + 시트 저장 시도)
    if HAS_PANDAS:
        try:
            cur = S.store.tables.get("id_requests")
            new = pd.DataFrame([{
                "이름": body.name, "이메일": body.email, "희망ID": body.desired_id,
                "메모": body.memo, "신청시각": L._now_text(),
            }])
            S.store.tables["id_requests"] = pd.concat([cur, new], ignore_index=True) if cur is not None and not cur.empty else new
            S.store.save(["아이디추가요청"])
        except Exception:
            pass
    return {"ok": True}


# ---------------- timetable/teachers
@app.get("/api/timetable")
def get_timetable():
    return {"records": _df_to_records(S.get_table("timetable")), "version": S.get_version()}


@app.get("/api/teachers")
def get_teachers():
    return {"records": _df_to_records(S.get_table("teachers")), "names": L.get_all_teacher_names()}


@app.get("/api/effective-day")
def effective_day(date: str = Query(""), useTest: bool = Query(False)):
    df = L.get_effective_timetable_for_date(date, use_test=bool(useTest))
    return {"date": L.normalize_date_str(date), "records": _df_to_records(df)}


@app.get("/api/effective-week")
def effective_week(refDate: str = Query(""), useTest: bool = Query(False)):
    try:
        rd = _parse_date(refDate) if refDate else date.today()
    except Exception:
        rd = date.today()
    data = L.get_effective_week(rd, use_test=bool(useTest))
    return {"refDate": rd.isoformat(), "days": {k: _df_to_records(v) for k, v in data.items()}}


@app.get("/api/teacher-week")
def teacher_week(teacher: str = Query(""), refDate: str = Query(""), useTest: bool = Query(False)):
    try:
        rd = _parse_date(refDate) if refDate else date.today()
    except Exception:
        rd = date.today()
    df, week = L.get_teacher_week_view(teacher, rd, use_test=bool(useTest))
    return {"teacher": teacher, "records": _df_to_records(df),
            "week": [d.isoformat() for d in week]}


@app.get("/api/changed-teachers")
def changed_teachers(refDate: str = Query("")):
    try:
        rd = _parse_date(refDate) if refDate else date.today()
    except Exception:
        rd = date.today()
    return {"teachers": L.get_changed_teachers_for_week(rd)}


# ---------------- absences
@app.get("/api/absences")
def list_absences():
    return {"records": _df_to_records(S.get_table("absences"))}


@app.post("/api/absences")
def create_absence(body: AbsenceIn):
    if not HAS_PANDAS:
        return JSONResponse({"ok": False, "error": "pandas 미설치"}, status_code=500)
    norm = L.normalize_date_str(body.date)
    if not norm or not body.teacher or safe_period(body.period) <= 0:
        return JSONResponse({"ok": False, "error": "필수값 누락"}, status_code=400)
    cur = S.get_table("absences")
    new = pd.DataFrame([{
        "결강ID": body.cid or L._new_change_id("ABS"), "일자": norm, "요일": body.day,
        "교시": int(body.period), "학급": body.class_name, "과목": body.subject,
        "교사명": body.teacher, "사유": body.reason, "상세사유": body.detail,
        "등록시각": L._now_text(), "입력자": body.user,
    }])
    try:
        S.store.tables["absences"] = pd.concat([cur, new], ignore_index=True) if not cur.empty else new
        S.store.save(["결강"])
        S.store.push_history("결강 등록")
        S.store.invalidate()
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
    df = L.recommend_substitutes(body.day, body.period, body.subject, body.class_name,
                                 body.absent_teacher, body.date, top_n=body.top_n,
                                 include_part_time=body.include_part_time)
    return {"records": _df_to_records(df)}


@app.post("/api/subs/validate")
def subs_validate(body: SubValidateIn):
    ok, msg = L.validate_substitute(body.cid, body.date, body.period, body.class_name,
                                    body.subject, body.absent_teacher, body.sub_teacher)
    return {"ok": ok, "message": msg}


@app.post("/api/subs")
def subs_create(body: SubIn):
    ok, msg = L.add_substitute(body.cid or L._new_change_id("ABS"), body.date, body.day, body.period,
                               body.class_name, body.subject, body.absent_teacher, body.sub_teacher,
                               body.method, body.priority, body.memo, user=body.user)
    if not ok:
        return JSONResponse({"ok": False, "error": msg}, status_code=400)
    return {"ok": True}


@app.post("/api/subs/batch")
def subs_batch(body: SubBatchIn):
    accepted, errors = L.add_substitutes_batch(body.assignments, user=body.user)
    return {"accepted": accepted, "errors": errors}


@app.delete("/api/subs")
def subs_delete(cid: str = Query(""), period: int = Query(0)):
    ok, msg = L.cancel_substitute(cid, period)
    if not ok:
        return JSONResponse({"ok": False, "error": msg}, status_code=400)
    return {"ok": True}


# ---------------- swaps
@app.post("/api/swaps/validate")
def swaps_validate(body: SwapValidateIn):
    ok, msg = L.validate_swap(body.a, body.b, body.date_a, body.date_b, is_test=body.is_test)
    return {"ok": ok, "message": msg}


@app.post("/api/swaps")
def swaps_create(body: SwapIn):
    ok, msg = L.do_swap(body.a, body.b, body.date_a, body.date_b,
                         is_part_time_purpose=body.is_part_time_purpose,
                         is_test=body.is_test, user=body.user)
    if not ok:
        return JSONResponse({"ok": False, "error": msg}, status_code=400)
    return {"ok": True}


@app.post("/api/swaps/linked")
def swaps_linked(body: LinkedSwapIn):
    ok, msg = L.do_linked_swap(body.a, body.teacher_b, body.date_a, body.date_b,
                                body.day_b, body.period_b,
                                is_part_time_purpose=body.is_part_time_purpose,
                                is_test=body.is_test, subject_b=body.subject_b, user=body.user)
    if not ok:
        return JSONResponse({"ok": False, "error": msg}, status_code=400)
    return {"ok": True}


@app.post("/api/swaps/cycle")
def swaps_cycle(body: CycleSwapIn):
    ok, msg = L.apply_cycle_swaps(body.moves, is_test=body.is_test, user=body.user)
    if not ok:
        return JSONResponse({"ok": False, "error": msg}, status_code=400)
    return {"ok": True}


@app.post("/api/swaps/target-recommend")
def swaps_target(body: TargetRecommendIn):
    df, cycles, msg = L.get_target_time_recommendations(
        body.teacher_a, body.date_a, body.period_a, body.class_a, body.subject_a,
        body.date_b, body.period_b, budget_factor=body.budget_factor)
    return {"records": _df_to_records(df), "cycles": cycles, "message": msg}


@app.post("/api/swaps/cycles-search")
def swaps_cycles(body: CycleSearchIn):
    cycles, msg = L.find_cycle_linked_swaps(
        body.teacher_a, body.date_a, body.period_a, body.class_a, body.subject_a,
        body.date_b, body.period_b, max_cycle=body.max_cycle, use_test=body.use_test)
    return {"cycles": cycles, "message": msg}


@app.get("/api/swaps/weekly-1to1")
def swaps_weekly(teacher: str = Query(""), refDate: str = Query(""), futureDays: int = Query(0)):
    try:
        rd = _parse_date(refDate) if refDate else date.today()
    except Exception:
        rd = date.today()
    df = L.get_weekly_1to1_swap_table(teacher, rd, future_days=int(futureDays or 0))
    return {"records": _df_to_records(df)}


# ---------------- part-time / duties
@app.get("/api/part-time")
def pt_list():
    df = S.get_table("part_time")
    ok, msg = L.validate_part_time_table(df)
    return {"records": _df_to_records(df), "valid": ok, "message": msg}


@app.post("/api/part-time")
def pt_create(body: PartTimeIn):
    if not HAS_PANDAS:
        return JSONResponse({"ok": False, "error": "pandas 미설치"}, status_code=500)
    row = dict(body.row or {})
    cur = S.get_table("part_time")
    try:
        new = pd.DataFrame([row])
        S.store.tables["part_time"] = pd.concat([cur, new], ignore_index=True) if not cur.empty else new
        ok, msg = L.validate_part_time_table(S.store.tables["part_time"])
        if not ok:
            S.store.tables["part_time"] = cur
            return JSONResponse({"ok": False, "error": msg}, status_code=400)
        S.store.save(["시간강사"])
        S.store.push_history("시간강사 등록")
        S.store.invalidate()
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)
    return {"ok": True}


@app.get("/api/duties")
def duties_list():
    return {"records": _df_to_records(S.get_table("duties"))}


@app.post("/api/duties")
def duties_create(body: DutyIn):
    if not HAS_PANDAS:
        return JSONResponse({"ok": False, "error": "pandas 미설치"}, status_code=500)
    norm = L.normalize_date_str(body.date)
    cur = S.get_table("duties")
    try:
        new = pd.DataFrame([{
            "교사명": body.teacher, "일자": norm, "교시": int(body.period),
            "사유": body.reason, "상세사유": body.detail,
            "등록시각": L._now_text(), "입력자": body.user,
        }])
        S.store.tables["duties"] = pd.concat([cur, new], ignore_index=True) if not cur.empty else new
        S.store.save(["복무"])
        S.store.push_history("복무 등록")
        S.store.invalidate()
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)
    return {"ok": True}


# ---------------- budget/stats
@app.get("/api/budget")
def budget_get():
    df = S.get_table("budget")
    return {"balance": L.get_current_budget(df), "records": _df_to_records(df)}


@app.post("/api/budget")
def budget_post(body: BudgetIn):
    v = L.update_budget(int(body.change), body.reason)
    if v is None:
        return JSONResponse({"ok": False, "error": "예산 저장 실패"}, status_code=500)
    return {"ok": True, "balance": v}


@app.get("/api/stats")
def stats():
    return {
        "cumulative": L.cumulative_sub_count(),
        "weekly_load": L.weekly_load(),
        "budget": L.get_current_budget(),
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
        from . import neis as N
        df = N.fetch_schedule(key, C.SCHOOL_NAME, monday.isoformat(), friday.isoformat())
        # 캐시 저장 (effective 계산용)
        try:
            S.store.tables["neis_cache"] = df
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
        from . import neis as N
        # 캐시 무효화
        N._schedule_cache.clear()
        df = N.fetch_schedule(key, C.SCHOOL_NAME, monday.isoformat(), friday.isoformat())
        S.store.tables["neis_cache"] = df
        S.store.invalidate()
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
        data = L.build_weekly_schedule_excel_bytes(rd, use_test=bool(useTest))
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
        data = L.build_weekly_class_schedule_excel_bytes(rd, use_test=bool(useTest))
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)
    return Response(content=data,
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": "attachment; filename=class-week.xlsx"})


@app.get("/api/report/daily.html", response_class=HTMLResponse)
def report_daily(date: str = Query("")):
    return L.build_report_html(date)


@app.get("/api/report/personal.html", response_class=HTMLResponse)
def report_personal(teacher: str = Query(""), date: str = Query("")):
    return L.build_personal_plan_html(teacher, date)


@app.get("/api/report/test.html", response_class=HTMLResponse)
def report_test():
    return L.build_test_swaps_report_html()


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
    calc_date = L._salary_safe_date(body.calc_date) or date.today()
    res = L._salary_calculate(body.name, calc_date, body.org, body.position,
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
    out["html"] = L._salary_report_html(res)
    return out


@app.post("/api/salary/analyze")
async def salary_analyze(request: Request):
    try:
        from . import salary_ai as SA
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)
    form = await request.form()
    f = form.get("file")
    if f is None:
        return JSONResponse({"ok": False, "error": "파일 없음"}, status_code=400)
    try:
        raw = await f.read()
        data = SA.analyze_file(raw, filename=getattr(f, "filename", "") or "",
                               mime_type=getattr(f, "content_type", "") or "")
        return {"ok": True, "data": data}
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)


# ---------------- admin/history
@app.get("/api/admin/ids")
def admin_ids():
    return {"records": _df_to_records(S.get_table("ids"))}


@app.post("/api/admin/ids")
def admin_ids_save(body: dict):
    if not HAS_PANDAS:
        return JSONResponse({"ok": False, "error": "pandas 미설치"}, status_code=500)
    records = (body or {}).get("records", [])
    try:
        df = pd.DataFrame(records)
        S.store.tables["ids"] = df
        S.store.save(["아이디저장함"])
        return {"ok": True}
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=500)


@app.post("/api/history/undo")
def hist_undo():
    return {"ok": S.undo()}


@app.post("/api/history/redo")
def hist_redo():
    return {"ok": S.redo()}
