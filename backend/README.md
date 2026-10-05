# Timetable Backend (FastAPI)

원본 Streamlit 앱(`backend/original_timetable_app2.py`, 7069줄)을 FastAPI로 이식한 백엔드.

## 실행법

```bash
cd backend
pip install -r requirements.txt
uvicorn app.server:app --reload --port 8000
```

브라우저: http://localhost:8000/docs

## .env 설정

`backend/.env.example`을 복사해 `backend/.env` 생성:

```bash
copy .env.example .env   # Windows
```

| 변수 | 설명 |
|---|---|
| `GOOGLE_SERVICE_ACCOUNT_JSON` | 서비스계정 JSON 파일 경로 (없으면 인메모리 모드) |
| `NEIS_API_KEY` | NEIS Open API 키 |
| `GEMINI_API_KEY` | Gemini 키 (호봉 AI 분석) |
| `GEMINI_MODEL` | 기본 `gemini-2.0-flash` |
| `TIMETABLE_SHEET_ID` / `WORK_SHEET_ID` | 기본값 내장 |
| `SCHOOL_NAME` / `SCHOOL_YEAR` | 기본 서라벌여자중학교 / 2026 |

## 시트 공유 설정

1. GCP 서비스계정 이메일(`xxx@xxx.iam.gserviceaccount.com`)에 아래 2개 스프레드시트를 **편집자**로 공유
   - 시간표: `1jZhTHyJ8vKXn6tkoFXfY_f52-pj6eQTdVvRCo3cCmBA` (시트: 교사정보, 시간표)
   - 업무: `1g1B1cyZG_tfRn3AD1NZzr30YxYNYFewJeZYdos2obpU` (시트: 결강, 보강, 맞교환, 시간강사, 누적보강, 복무, 예산, 아이디저장함, 아이디추가요청, 수업교체신청)
2. `GOOGLE_SERVICE_ACCOUNT_JSON` 경로에 JSON 키 배치
3. 키/시트 없이도 서버는 뜬다 (빈 DF + 에러메시지 반환, 프론트 크래시 방지)

## 주요 라우트

- `GET /api/health`, `GET /api/meta`
- `POST /api/auth/login {id}`, `POST /api/auth/guest`, `POST /api/auth/request-id`
- `GET /api/timetable`, `GET /api/teachers`
- `GET /api/effective-day?date&useTest`, `GET /api/effective-week?refDate&useTest`
- `GET /api/teacher-week?teacher&refDate`, `GET /api/changed-teachers?refDate`
- `POST/GET /api/absences`, `POST /api/subs/recommend|validate`, `POST /api/subs`, `POST /api/subs/batch`, `DELETE /api/subs`
- `POST /api/swaps/validate`, `POST /api/swaps|linked|cycle|target-recommend|cycles-search`, `GET /api/swaps/weekly-1to1`
- `GET/POST /api/part-time`, `GET/POST /api/duties`
- `GET/POST /api/budget`, `GET /api/stats`
- `GET /api/neis/week`, `POST /api/neis/refresh`
- `GET /api/export/teacher-week.xlsx`, `GET /api/export/class-week.xlsx`
- `GET /api/report/daily.html`, `GET /api/report/personal.html`
- `POST /api/salary/calculate`, `POST /api/salary/analyze`
- `GET/POST /api/admin/ids`, `POST /api/history/undo|redo`

## 테스트

```bash
pip install pytest pandas
pytest tests/test_logic.py -v
```
