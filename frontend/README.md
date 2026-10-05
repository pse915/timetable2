# 시간표·결보강 관리 — Frontend

React 18 + Vite + TypeScript + Tailwind. 백엔드(`backend/app/server.py`, `/api`)를
`VITE_API_BASE_URL`로 호출합니다. Google 시트 직접 호출 금지.

## 시작

```bash
cd frontend
npm install
cp .env.example .env   # VITE_API_BASE_URL=http://localhost:8000
npm run dev            # http://localhost:5173
npm run build
npm run preview
```

## 백엔드 연동

- `VITE_API_BASE_URL=http://localhost:8000` (`.env.example` 참조)
- 개발 모드에서는 `vite.config.ts`의 `/api → http://localhost:8000` 프록시도 사용 가능
- `src/api.ts`: fetch 래퍼 + 36개 백엔드 라우트 대응 함수 (구 client.ts/endpoints.ts 병합)

## 권한표

| 역할 | 허용 탭 |
|---|---|
| 마스터 | 전체 12개 |
| 교육과정부 | 전체 12개 |
| 교무계원 | 교무호봉획정 |
| 일반교사 | 시간표 조회, 시간강사 관리, 결강·보강, 맞교환, 통계, 테스트, 변경교사, 복무, 호봉 |
| 게스트 | 없음 (로그인 후 리다이렉트) |

권한 없는 탭 접근 시 `/app/timetable`로 리다이렉트됩니다 (`PrivateRoute`).
마스터는 `canAccess()`에서 항상 통과합니다.

## 라우트

| 경로 | 탭 |
|---|---|
| `/login` | 로그인 |
| `/app/timetable` | 시간표 조회 |
| `/app/absence` | 결강·보강 |
| `/app/swap` | 시간표 맞교환 & 변경 추천 |
| `/app/test-swap` | 시간표 변경 테스트용 |
| `/app/changed` | 변경된 교사 주간표 |
| `/app/part-time` | 시간강사 관리 |
| `/app/stats` | 통계 |
| `/app/duty` | 📋 복무 관리 & 판단 |
| `/app/multi` | 🛠️ 다중 출장·전체 조정 추천 |
| `/app/ids` | 🔑 아이디·권한 관리 |
| `/app/tabs` | 📑 회원별 탭 권한 관리 |
| `/app/salary` | 교무호봉획정 |

## UI 토큰

- Light: bg `#ffffff`, surface `#ffffff`, soft `#f5f5f7`, text `#1d1d1f`, muted `#6e6e73`, line `#d2d2d7`, accent `#0066cc`
- Black: bg `#000`, surface `#1d1d1f`, accent `#2997ff`
- radius 8/12/16, pill 버튼, 폰트 6종 (시스템/Pretendard/Noto Sans KR/GitHub Noto/학교안심우주체/Inter)
