"""중앙 상수 (원본 tt.py에서 이식)."""
import os
import re

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

SCHOOL_NAME = os.getenv("SCHOOL_NAME", "서라벌여자중학교")
SCHOOL_YEAR = os.getenv("SCHOOL_YEAR", "2026")

TIMETABLE_SHEET_ID = os.getenv(
    "TIMETABLE_SHEET_ID", "1jZhTHyJ8vKXn6tkoFXfY_f52-pj6eQTdVvRCo3cCmBA"
)
WORK_SHEET_ID = os.getenv(
    "WORK_SHEET_ID", "1g1B1cyZG_tfRn3AD1NZzr30YxYNYFewJeZYdos2obpU"
)

DAYS = ["월", "화", "수", "목", "금"]
PERIODS_PER_DAY = {"월": 6, "화": 7, "수": 7, "목": 7, "금": 6}
MAX_PERIOD = 7
WEEKDAY_KR = {0: "월", 1: "화", 2: "수", 3: "목", 4: "금", 5: "토", 6: "일"}
SCHOOL_WEEKDAYS = (0, 1, 2, 3, 4)

_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

# --- Roles ---
ROLE_MASTER = "마스터"
ROLE_EDU = "교육과정부"
ROLE_OFFICE = "교무계원"
ROLE_TEACHER = "일반교사"
ROLE_GUEST = "게스트"
MASTER_ID = "pse915"
VALID_ROLES = frozenset({ROLE_MASTER, ROLE_EDU, ROLE_OFFICE, ROLE_TEACHER})

MAX_LOGIN_ATTEMPTS = 5
MAX_HISTORY = 5
MAX_ID_LENGTH = 64
MAX_NAME_LENGTH = 80
MAX_EMAIL_LENGTH = 254
MAX_MEMO_LENGTH = 1000

SUB_COST = 10000
BUDGET_INIT = 2200000

ABSENCE_REASONS = ["병가", "연가", "출장", "공가", "조퇴", "외출", "연수", "특별휴가", "기타"]

SUBJECT_GROUP = {
    "국어1": "국어", "국어2": "국어", "사회": "사회", "사회1": "사회", "사회2": "사회", "사회3": "사회",
    "역사": "역사", "도덕1": "도덕", "도덕2": "도덕", "수학": "수학", "수학1": "수학", "수학2": "수학",
    "과학": "과학", "과학1": "과학", "과학2": "과학", "기가": "기술가정",
    "체육1": "체육", "체육2": "체육", "체육3": "체육", "스포": "스포츠",
    "음악": "음악", "음악1": "음악", "음악2": "음악", "미술": "미술",
    "영어": "영어", "영어1": "영어", "영어2": "영어", "영회": "영어",
    "한문": "한문", "일본어": "일본어", "정보": "정보", "진동": "진로활동",
}

# --- NEIS ---
NEIS_API_BASE = "https://open.neis.go.kr/hub"
NEIS_SCHOOL_INFO_ENDPOINT = f"{NEIS_API_BASE}/schoolInfo"
NEIS_SCHEDULE_ENDPOINT = f"{NEIS_API_BASE}/SchoolSchedule"
NEIS_EDU_OFFICE_CODES = (
    "B10", "C10", "D10", "E10", "F10", "G10", "H10", "I10", "J10",
    "K10", "M10", "N10", "P10", "Q10", "R10", "S10", "T10",
)
NEIS_SCHOOL_CODE_FALLBACKS = {
    "서라벌여자중학교": {"ATPT_OFCDC_SC_CODE": "R10", "SD_SCHUL_CODE": "8771121"},
}
NEIS_NON_INSTRUCTIONAL_TYPES = (
    "공휴일", "휴업일", "휴일", "방학", "재량휴업일", "임시휴업일", "학교장재량휴업일",
    "개교기념일", "대체공휴일", "대체휴일", "토요휴업일", "일요일", "토요일", "선거일",
    "임시공휴일", "근로자의날",
)
NEIS_SCHEDULE_CACHE_TTL = 900
NEIS_SCHOOL_CACHE_TTL = 86400

ALL_TABS = [
    "시간표 조회",
    "결강·보강",
    "시간표 맞교환 & 변경 추천",
    "시간표 변경 테스트용",
    "변경된 교사 주간표",
    "시간강사 관리",
    "통계",
    "📋 복무 관리 & 판단",
    "🛠️ 다중 출장·전체 조정 추천",
    "🔑 아이디·권한 관리",
    "📑 회원별 탭 권한 관리",
]
OFFICE_TABS = ["교무호봉획정"]
ALL_APP_TABS = ALL_TABS + OFFICE_TABS
DEFAULT_TABS = {
    ROLE_MASTER: ALL_APP_TABS,
    ROLE_EDU: ALL_APP_TABS,
    ROLE_OFFICE: OFFICE_TABS,
    ROLE_TEACHER: [
        "시간표 조회", "시간강사 관리", "결강·보강",
        "시간표 맞교환 & 변경 추천", "통계",
        "시간표 변경 테스트용", "변경된 교사 주간표", "📋 복무 관리 & 판단",
        "교무호봉획정",
    ],
    ROLE_GUEST: [],
}

SWAP_REQUEST_COLS = [
    "신청ID", "신청자", "신청자이름", "원본일자", "교사A", "요일A", "교시A", "학급A", "과목A",
    "목표일자", "교사B", "요일B", "교시B", "학급B", "과목B", "유형", "신청시각", "상태",
]
DUTY_COLS = ["교사명", "일자", "교시", "사유", "상세사유", "등록시각", "입력자"]
PART_TIME_EXTRA_COLS = ["시작일", "종료일", "대체교사"]
CHANGE_TYPES = {"원본", "교환", "테스트교환", "보강", "시간강사"}

EFFECTIVE_COLUMNS = [
    "교사명", "요일", "교시", "과목", "학급", "과목군",
    "원본교사", "원본일자", "원본교시", "변경유형", "변경출처", "변경ID", "변경상세",
]

SALARY_BASE_OPTIONS = [
    (9, "정교사(1급)"),
    (9, "전문상담교사(1급)"),
    (9, "사서교사(1급)"),
    (9, "보건교사(1급)"),
    (9, "영양교사(1급)"),
    (9, "교장·원장·교감·원감·교육장·장학(연구)직"),
    (8, "정교사(2급)"),
    (8, "전문상담교사(2급)"),
    (8, "사서교사(2급)"),
    (8, "보건교사(2급)"),
    (8, "영양교사(2급)"),
    (5, "준교사"),
    (5, "실기교사"),
]
SALARY_ACADEMIC_OPTIONS = [
    (0, "4년제 일반대학 졸업", "학령: 16년 → 학령가감: +0년"),
    (0, "교육대학·사범대학 졸업 (4년)", "학령: 16년 → 학령가감: +0년"),
    (2, "6년제 대학 졸업 (의대 등)", "학령: 18년 → 학령가감: +2년"),
]
SALARY_DEGREE_TYPES = [
    "동등 수준 추가 학사 학위 (2번째 대학교)",
    "석사학위 취득 수학기간",
    "박사학위 취득 수학기간",
]
SALARY_CAREER_TYPES = [
    "국·공립학교 교원 (기간제 포함, 자격 일치)",
    "사립학교 교원 (관할청 보고, 자격 일치)",
    "기간제교원 자격-학교급 불일치 (예:중등→초등)",
    "유·초·중등 강사 (전일제·종일제, 1일 8시간 ↑)",
    "유·초·중등 시간제 강사 (주 12시간 ↓ 또는 시수 불명)",
    "국가·지방공무원 (현역 군복무 포함)",
    "등록 학원 강사 / 신고 교습소 교습자",
    "회사 (상법상 합명·합자·주식·유한회사) 근무",
]
SALARY_CAREER_RATE_BY_TYPE = {
    "국·공립학교 교원 (기간제 포함, 자격 일치)": 100,
    "사립학교 교원 (관할청 보고, 자격 일치)": 100,
    "기간제교원 자격-학교급 불일치 (예:중등→초등)": 80,
    "유·초·중등 강사 (전일제·종일제, 1일 8시간 ↑)": 100,
    "유·초·중등 시간제 강사 (주 12시간 ↓ 또는 시수 불명)": 30,
    "국가·지방공무원 (현역 군복무 포함)": 100,
    "등록 학원 강사 / 신고 교습소 교습자": 50,
    "회사 (상법상 합명·합자·주식·유한회사) 근무": 40,
}
SALARY_DEGREE_RATE_BY_TYPE = {
    "동등 수준 추가 학사 학위 (2번째 대학교)": 80,
    "석사학위 취득 수학기간": 100,
    "박사학위 취득 수학기간": 100,
}
SALARY_GEMINI_PROMPT = """
당신은 대한민국 교육공무원 및 기간제교원 호봉 획정 서류 분석 전문가입니다.
첨부된 문서(경력증명서, 인사기록카드, 자격증 등)를 정확히 읽고, 아래 요청하는 형식의 JSON으로만 출력해 주세요.
[출력 구조 예시]
{
  "name": "홍길동",
  "baseSalary": 8,
  "qualLabel": "정교사(2급)",
  "academicValue": "0",
  "isSabom": true,
  "degrees": [
    {
      "type": "동등 수준 추가 학사 학위 (2번째 대학교)",
      "detail": "OO대학교 국어교육과 (학사)",
      "start": "2018-03-01",
      "end": "2020-02-28",
      "rate": 80
    }
  ],
  "careers": [
    {
      "type": "국·공립학교 교원 (기간제 포함, 자격 일치)",
      "detail": "OO고등학교 기간제교사",
      "start": "2022-03-01",
      "end": "2023-02-28",
      "inc": true,
      "rate": 100
    }
  ]
}
[경력 type 매칭 옵션]
- "국·공립학교 교원 (기간제 포함, 자격 일치)" (100%)
- "사립학교 교원 (관할청 보고, 자격 일치)" (100%)
- "기간제교원 자격-학교급 불일치 (예:중등→초등)" (80%)
- "유·초·중등 강사 (전일제·종일제, 1일 8시간 ↑)" (100%)
- "유·초·중등 시간제 강사 (주 12시간 ↓ 또는 시수 불명)" (30%)
- "국가·지방공무원 (현역 군복무 포함)" (100%)
- "등록 학원 강사 / 신고 교습소 교습자" (50%)
- "회사 (상법상 합명·합자·주식·유한회사) 근무" (40%)
[주의사항]
1. 날짜는 반드시 YYYY-MM-DD 형식이어야 합니다.
2. 경력사항이 여러 개일 경우 모두 careers 배열에 넣어주세요.
3. 마크다운 코드블록이나 기타 설명 없이 pure JSON 문자열만 반환해야 합니다.
""".strip()
