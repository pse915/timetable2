import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import type { ReactNode } from 'react';
import { fetchBudget, fetchMeta, type RecommendItem } from '../api';
import { TAB_ROUTES } from '../App';
import { FONT_OPTIONS, useAppStore } from '../store/useAppStore';

/* ---------- TopBar (ex components/TopBar.tsx) ---------- */

interface TopBarProps {
  onNavigate: (path: string) => void;
}

export function TopBar({ onNavigate }: TopBarProps) {
  const navigate = useNavigate();
  const user = useAppStore((s) => s.user);
  const activeTab = useAppStore((s) => s.activeTab);
  const theme = useAppStore((s) => s.theme);
  const font = useAppStore((s) => s.font);
  const setTheme = useAppStore((s) => s.setTheme);
  const setFont = useAppStore((s) => s.setFont);
  const logout = useAppStore((s) => s.logout);
  const setVersion = useAppStore((s) => s.setVersion);

  const { data: budget } = useQuery({
    queryKey: ['budget'],
    queryFn: fetchBudget,
    enabled: !!user,
    retry: false,
  });
  const { data: meta, refetch } = useQuery({ queryFn: fetchMeta, queryKey: ['meta'] });

  const allowed = TAB_ROUTES.filter((r) => {
    if (!user) return false;
    if (user.role === '마스터') return true;
    return user.allowedTabs.includes(r.tab);
  });

  return (
    <header className="topbar">
      <div className="topbar-row">
        <button className="logo" onClick={() => onNavigate('/app/timetable')}>
          서라벌여자중학교 <span className="logo-year">2026</span>
        </button>
        <div className="topbar-actions">
          <button className="btn-pill" onClick={() => window.location.reload()}>새로고침</button>
          <button className="btn-pill" onClick={() => void refetch()}>불러오기</button>
          <button
            className="btn-pill primary"
            onClick={() => {
              if (meta?.version !== undefined) setVersion(String(meta.version));
              alert('저장은 각 화면의 저장 버튼을 사용하세요.');
            }}
          >
            저장
          </button>
          <select
            className="select"
            value={theme}
            aria-label="테마"
            onChange={(e) => setTheme(e.target.value as 'light' | 'black')}
          >
            <option value="light">Light</option>
            <option value="black">Black</option>
          </select>
          <select
            className="select"
            value={font}
            aria-label="폰트"
            onChange={(e) => setFont(e.target.value as typeof font)}
          >
            {FONT_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
          {budget && (
            <span className="kpi-chip" title="예산 잔액">
              예산 {(budget.balance ?? 0).toLocaleString()}원
            </span>
          )}
          {user && (
            <span className="user-chip">
              {user.name}({user.role})
              <button
                className="link"
                onClick={() => {
                  logout();
                  navigate('/login');
                }}
              >
                로그아웃
              </button>
            </span>
          )}
        </div>
      </div>
      <nav className="tabnav" aria-label="탭 내비게이션">
        {allowed.map((r) => (
          <button
            key={r.path}
            className={`tabbtn${activeTab === r.tab ? ' active' : ''}`}
            onClick={() => onNavigate(r.path)}
          >
            {r.short}
          </button>
        ))}
      </nav>
    </header>
  );
}

/* ---------- ThemeToggle (ex components/ThemeToggle.tsx) ---------- */

export function ThemeToggle() {
  const theme = useAppStore((s) => s.theme);
  const setTheme = useAppStore((s) => s.setTheme);
  return (
    <button
      className="btn-pill"
      onClick={() => setTheme(theme === 'light' ? 'black' : 'light')}
      aria-label="테마 전환"
    >
      {theme === 'light' ? '🌙 Black' : '☀️ Light'}
    </button>
  );
}

/* ---------- KpiCards (ex components/KpiCards.tsx) ---------- */

export interface Kpi {
  label: string;
  value: string;
}

export function KpiCards({ items }: { items: Kpi[] }) {
  return (
    <div className="kpi-grid">
      {items.map((k) => (
        <div key={k.label} className="card kpi">
          <div className="kpi-label">{k.label}</div>
          <div className="kpi-value">{k.value}</div>
        </div>
      ))}
    </div>
  );
}

/* ---------- EmptyState (ex components/EmptyState.tsx) ---------- */

export function EmptyState({ message }: { message: string }) {
  return <div className="empty">{message}</div>;
}

/* ---------- ActionDialog (ex components/ActionDialog.tsx) ---------- */

interface ActionDialogProps {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
}

export function ActionDialog({ open, title, onClose, children }: ActionDialogProps) {
  if (!open) return null;
  return (
    <div className="dialog-backdrop" onClick={onClose}>
      <div className="dialog" role="dialog" aria-modal="true" onClick={(e) => e.stopPropagation()}>
        <div className="dialog-head">
          <strong>{title}</strong>
          <button className="btn-pill" onClick={onClose}>닫기</button>
        </div>
        <div className="dialog-body">{children}</div>
      </div>
    </div>
  );
}

/* ---------- RecommendTable (ex components/RecommendTable.tsx) ---------- */

interface RecommendTableProps {
  items: RecommendItem[];
  loading?: boolean;
  onApply?: (item: RecommendItem) => void;
  applyLabel?: string;
}

export function RecommendTable({ items, loading, onApply, applyLabel = '적용' }: RecommendTableProps) {
  if (loading) {
    return (
      <div className="card">
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="skeleton-row" />
        ))}
      </div>
    );
  }
  if (items.length === 0) return <EmptyState message="추천 결과가 없습니다." />;
  return (
    <div className="table-wrap">
      <table className="table">
        <thead>
          <tr>
            <th>교사</th>
            <th>점수</th>
            <th>사유</th>
            {onApply && <th>액션</th>}
          </tr>
        </thead>
        <tbody>
          {items.map((it) => (
            <tr key={it.teacher}>
              <td>{it.teacher}</td>
              <td>{it.score}</td>
              <td className="muted">{it.reason}</td>
              {onApply && (
                <td>
                  <button className="btn-pill primary" onClick={() => onApply(it)}>
                    {applyLabel}
                  </button>
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
