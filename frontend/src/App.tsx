import { useEffect } from 'react';
import { Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom';
import { TopBar } from './components/ui';
import { FONT_OPTIONS, useAppStore } from './store/useAppStore';
import Login from './pages/Login';
import Salary from './pages/Salary';
import { IdAdminPage, TabPermPage } from './pages/Admin';
import {
  AbsenceSubPage,
  ChangedTeachersPage,
  SwapPage,
  TestSwapPage,
  TimetableViewPage,
} from './pages/Core';
import { DutyPage, MultiAdjustPage, PartTimePage, StatsPage } from './pages/Ops';

export const TAB_ROUTES: { tab: string; path: string; short: string }[] = [
  { tab: '시간표 조회', path: '/app/timetable', short: '시간표' },
  { tab: '결강·보강', path: '/app/absence', short: '결보강' },
  { tab: '시간표 맞교환 & 변경 추천', path: '/app/swap', short: '맞교환' },
  { tab: '시간표 변경 테스트용', path: '/app/test-swap', short: '테스트' },
  { tab: '변경된 교사 주간표', path: '/app/changed', short: '변경교사' },
  { tab: '시간강사 관리', path: '/app/part-time', short: '시간강사' },
  { tab: '통계', path: '/app/stats', short: '통계' },
  { tab: '📋 복무 관리 & 판단', path: '/app/duty', short: '복무' },
  { tab: '🛠️ 다중 출장·전체 조정 추천', path: '/app/multi', short: '다중조정' },
  { tab: '🔑 아이디·권한 관리', path: '/app/ids', short: 'ID관리' },
  { tab: '📑 회원별 탭 권한 관리', path: '/app/tabs', short: '탭권한' },
  { tab: '교무호봉획정', path: '/app/salary', short: '호봉' },
];

export const NAV_LABELS: Record<string, string> = Object.fromEntries(
  TAB_ROUTES.map((r) => [r.tab, r.short]),
);

function PrivateRoute({ tab, children }: { tab: string; children: JSX.Element }) {
  const user = useAppStore((s) => s.user);
  const canAccess = useAppStore((s) => s.canAccess);
  if (!user) return <Navigate to="/login" replace />;
  if (!canAccess(tab)) return <Navigate to="/app/timetable" replace />;
  return children;
}

function AppShell() {
  const theme = useAppStore((s) => s.theme);
  const font = useAppStore((s) => s.font);
  const location = useLocation();
  const navigate = useNavigate();

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    const opt = FONT_OPTIONS.find((f) => f.value === font);
    document.body.style.fontFamily = opt
      ? `var(--font-${font})`
      : 'var(--font-pretendard)';
  }, [theme, font]);

  useEffect(() => {
    const hit = TAB_ROUTES.find((r) => r.path === location.pathname);
    if (hit) useAppStore.getState().setActiveTab(hit.tab);
  }, [location.pathname]);

  return (
    <div className="app-root">
      <TopBar onNavigate={(p) => navigate(p)} />
      <main className="app-main">
        <Routes>
          <Route path="/app/timetable" element={<PrivateRoute tab="시간표 조회"><TimetableViewPage /></PrivateRoute>} />
          <Route path="/app/absence" element={<PrivateRoute tab="결강·보강"><AbsenceSubPage /></PrivateRoute>} />
          <Route path="/app/swap" element={<PrivateRoute tab="시간표 맞교환 & 변경 추천"><SwapPage /></PrivateRoute>} />
          <Route path="/app/test-swap" element={<PrivateRoute tab="시간표 변경 테스트용"><TestSwapPage /></PrivateRoute>} />
          <Route path="/app/changed" element={<PrivateRoute tab="변경된 교사 주간표"><ChangedTeachersPage /></PrivateRoute>} />
          <Route path="/app/part-time" element={<PrivateRoute tab="시간강사 관리"><PartTimePage /></PrivateRoute>} />
          <Route path="/app/stats" element={<PrivateRoute tab="통계"><StatsPage /></PrivateRoute>} />
          <Route path="/app/duty" element={<PrivateRoute tab="📋 복무 관리 & 판단"><DutyPage /></PrivateRoute>} />
          <Route path="/app/multi" element={<PrivateRoute tab="🛠️ 다중 출장·전체 조정 추천"><MultiAdjustPage /></PrivateRoute>} />
          <Route path="/app/ids" element={<PrivateRoute tab="🔑 아이디·권한 관리"><IdAdminPage /></PrivateRoute>} />
          <Route path="/app/tabs" element={<PrivateRoute tab="📑 회원별 탭 권한 관리"><TabPermPage /></PrivateRoute>} />
          <Route path="/app/salary" element={<PrivateRoute tab="교무호봉획정"><Salary /></PrivateRoute>} />
          <Route path="*" element={<Navigate to="/app/timetable" replace />} />
        </Routes>
      </main>
    </div>
  );
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/app/*" element={<AppShell />} />
      <Route path="*" element={<Navigate to="/login" replace />} />
    </Routes>
  );
}
