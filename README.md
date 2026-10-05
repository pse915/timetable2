# 시간표·결보강 관리 — React + FastAPI 리빌드

원본 `timetable_app2.py` (Streamlit 7069줄) → React 18 + FastAPI로 1:1 이식.
모든 기능 유지, UI만 Apple-style로 재설계.

## 구조
```
backend/  FastAPI (원본 로직 이식, 39개 /api) — 파일 축소판 (config + server 2개)
  app/config.py   학교/시트/권한/과목군/NEIS/예산 상수 (시트ID 내장)
  app/server.py   store+logic+neis+salary_ai+main 병합 (섹션 주석 구분)
  original_timetable_app2.py  원본 참조용
frontend/ React+Vite+TS+Tailwind (12개 화면, 파일 축소판)
  src/api.ts  fetch 래퍼 + 36개 라우트 함수
  src/components/ui.tsx + pickers.tsx
  src/pages/Core.tsx(조회/결보강/맞교환/테스트/변경교사) + Ops.tsx(시간강사/통계/복무/다중조정)
    + Admin.tsx(ID/탭권한) + Salary.tsx + Login.tsx
```

## 구글 시트 (내장됨)
- 시간표DB: `1jZhTHyJ8vKXn6tkoFXfY_f52-pj6eQTdVvRCo3cCmBA` (교사정보, 시간표)
- 업무DB: `1g1B1cyZG_tfRn3AD1NZzr30YxYNYFewJeZYdos2obpU` (결강/보강/맞교환/시간강사/누적보강/복무/예산/아이디저장함/아이디추가요청/수업교체신청)
- 사용 전 두 스프레드시트를 서비스계정에 **편집자 공유** 필요.

## 실행

### A. Streamlit으로 배포 (요청 방식 — UI는 React가 전담)
```bash
pip install -r requirements.txt   # 루트 requirements (streamlit 포함)
cd frontend; npm install; npm run build; cd ..
streamlit run streamlit_app.py    # http://localhost:8501
```
- `streamlit_app.py`는 Streamlit 크롬(헤더/사이드바/푸터)을 전부 숨기고
  `frontend/dist`를 인라인하여 React만 풀스크린으로 보여준다.
- FastAPI는 같은 프로세스에서 백그라운드 스레드(기본 8000)로 자동 기동되며,
  React는 `window.__API_BASE__`로 주입된 주소로 fetch한다.
- Streamlit Community Cloud(단일 8501 포트)에서는 브라우저가 `localhost:8000`에
  닿지 않으므로, 백엔드를 Render/Fly 등에 올린 뒤 App Secrets에 아래를 지정:
```toml
BACKEND_URL = "https://<backend-host>"
NEIS_API_KEY = "..."
GEMINI_API_KEY = "..."
GOOGLE_SERVICE_ACCOUNT_INFO = "{...}"
```
- `.streamlit/secrets.example.toml` 참고. 프론트를 Vercel 등에 따로 올렸다면
  `FRONTEND_URL` 지정 시 iframe 모드로 전환된다.

### B. 분리 실행 (Docker/로컬 개발)
# 1) 백엔드
pip install -r requirements.txt   # 루트 requirements 단일화
copy backend\.env.example .env   # GOOGLE_SERVICE_ACCOUNT_JSON, NEIS_API_KEY, GEMINI_API_KEY 입력
uvicorn app.server:app --app-dir backend --reload --port 8000

# 2) 프론트
cd frontend
npm install
npm run dev      # http://localhost:5173 ( /api → 8000 프록시 )
npm run build    # 배포용 dist/
```

## 검증 (3회 디버깅 완료)
- `python -m py_compile` 7파일 통과
- `pytest backend/tests/test_logic.py` 7 passed
- `tsc --noEmit` 통과, `vite build` 성공 (422 modules)
- 백엔드/프론트 API 규격 일치 (effective-day/week, subs, swaps, salary 파일업로드, budget {change,reason} 등)
