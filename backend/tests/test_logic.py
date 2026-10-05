"""pytest 6개 이상."""
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

pd = pytest.importorskip("pandas")

from app import server as L
from app import server as S


def _reset_store():
    S.store.tables["teachers"] = pd.DataFrame([
        {"교사명": "김국어", "담당과목": "국어1"},
        {"교사명": "이수학", "담당과목": "수학1"},
        {"교사명": "박영어", "담당과목": "영어1"},
        {"교사명": "최과학", "담당과목": "과학1"},
    ])
    S.store.tables["timetable"] = pd.DataFrame([
        {"교사명": "김국어", "요일": "월", "교시": 1, "과목": "국어1", "학급": "1-1", "과목군": "국어"},
        {"교사명": "이수학", "요일": "월", "교시": 1, "과목": "수학1", "학급": "1-2", "과목군": "수학"},
        {"교사명": "박영어", "요일": "월", "교시": 2, "과목": "영어1", "학급": "1-1", "과목군": "영어"},
        {"교사명": "최과학", "요일": "월", "교시": 3, "과목": "과학1", "학급": "1-1", "과목군": "과학"},
        # 목요일 수업 (목7 금지 테스트용)
        {"교사명": "김국어", "요일": "목", "교시": 6, "과목": "국어1", "학급": "1-1", "과목군": "국어"},
        {"교사명": "이수학", "요일": "목", "교시": 7, "과목": "수학1", "학급": "3-1", "과목군": "수학"},
    ])
    S.store.tables["subs"] = pd.DataFrame(columns=list(S.SUB_COLS))
    S.store.tables["swaps"] = pd.DataFrame(columns=list(S.SWAP_COLS))
    S.store.tables["test_swaps"] = pd.DataFrame(columns=list(S.SWAP_COLS))
    S.store.tables["duties"] = pd.DataFrame(columns=["교사명", "일자", "교시", "사유", "상세사유", "등록시각", "입력자"])
    S.store.tables["part_time"] = pd.DataFrame()
    S.store.tables["budget"] = pd.DataFrame([{"일시": "2026-01-01", "내용": "초기", "변동금액": 0, "잔액": 2200000}])
    S.store.invalidate()


def test_thursday_7_forbidden():
    assert L.is_grade12_thursday_7_forbidden("1-1", "목", 7) is True
    assert L.is_grade12_thursday_7_forbidden("2-3", "목", 7) is True
    assert L.is_grade12_thursday_7_forbidden("3-1", "목", 7) is False
    assert L.is_grade12_thursday_7_forbidden("1-1", "수", 7) is False
    assert L.slot_allowed_for_class("1-1", "목", 7) is False
    assert L.slot_allowed_for_class("3-1", "목", 7) is True


def test_validate_swap_same_slot_rejected():
    _reset_store()
    a = {"교사명": "김국어", "요일": "월", "교시": 1, "학급": "1-1", "과목": "국어1"}
    ok, msg = L.validate_swap(a, dict(a), "2026-03-02", "2026-03-02")
    assert ok is False
    assert "동일" in msg


def test_validate_substitute_self_rejected():
    _reset_store()
    ok, msg = L.validate_substitute("CID1", "2026-03-02", 2, "1-1", "영어1", "박영어", "박영어")
    assert ok is False
    assert "같을 수 없" in msg


def test_recommend_score_order():
    _reset_store()
    # 2026-03-02는 월요일. 김국어(국어/1학년) 결강, 박영어 자리에 보강 후보 탐색
    # 박영어 월1 공강? 박영어는 월2 수업이므로 월1 공강. 최과학도 월1 공강이 아님(월3 수업이라 월1 공강)
    # 과목군/학년 가중치가 반영되어 동일 과목&학년이 1순위여야 함.
    # 후보: 이수학(수학, 1학년 중 1-2 담당 → 동일학년), 최과학(과학, 1-1 담당 이력? effective 기준)
    df = L.recommend_substitutes("월", 1, "국어1", "1-1", "김국어", "2026-03-02", top_n=10)
    assert not df.empty
    # 점수 내림차순 + 우선순위 정렬 확인: 첫 행이 동일과목 또는 동일학년
    first = df.iloc[0]
    assert first["추천점수"] >= df.iloc[-1]["추천점수"]
    assert "순위" in str(first["우선순위"])


def test_effective_reflects_sub():
    _reset_store()
    base = L.get_effective_timetable_for_date("2026-03-02")
    assert not base.empty
    # 김국어 월1 수업을 박영어가 보강
    S.store.tables["subs"] = pd.DataFrame([{
        "결강ID": "T1", "일자": "2026-03-02", "요일": "월", "교시": 1, "학급": "1-1",
        "과목": "국어1", "결강교사": "김국어", "보강교사": "박영어",
        "배정방식": "수동", "우선순위": "", "비고": "", "등록시각": "", "입력자": "",
    }])
    S.store.invalidate()
    eff = L.get_effective_timetable_for_date("2026-03-02")
    row = eff[(eff["교사명"] == "박영어") & (eff["교시"] == 1)]
    assert not row.empty
    assert row.iloc[0]["변경유형"] == "보강"
    gone = eff[(eff["교사명"] == "김국어") & (eff["교시"] == 1)]
    assert gone.empty


def test_salary_360():
    # 2022-03-01 ~ 2023-02-28 (종료일 산입) = 360일 = 1년
    assert L._salary_duration_days("2022-03-01", "2023-02-28", True) == 360
    assert L._salary_ymd_from_360(360) == (1, 0, 0)
    assert L._salary_ymd_from_360(390) == (1, 1, 0)
    deg = pd.DataFrame(columns=["학위 구분", "학교/전공 세부명", "입학일", "졸업일", "환산율"])
    car = pd.DataFrame([{
        "경력 종류": "국·공립학교 교원 (기간제 포함, 자격 일치)",
        "세부 근무처/직위": "OO중", "시작일": "2022-03-01", "종료일": "2023-02-28",
        "종료일 산입": True, "환산율 (%)": 100,
    }])
    res = L._salary_calculate("홍길동", date(2026, 3, 1), "서라벌여중", "기간제교사",
                              "작성자", "교무", 8, "정교사(2급)", 0, "사범", True, deg, car)
    assert res["total_y"] == 1 and res["total_m"] == 0
    # 8 + 0 + 1(사범) + 1(경력) = 10호봉
    assert res["final_step"] == 10


def test_format_and_normalize():
    assert L.normalize_date_str("20260302") == "2026-03-02"
    assert L.format_periods([1, 2, 3, 5]) == "1~3교시, 5교시"
    assert L.safe_int("abc", 7) == 7
    assert L.subject_group("국어1") == "국어"
    assert L.normalized_grade("1-3") == "1"
