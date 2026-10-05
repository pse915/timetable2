import { create } from 'zustand';
import { persist } from 'zustand/middleware';

export type ThemeMode = 'light' | 'black';
export type FontKind = 'system' | 'pretendard' | 'noto' | 'githubnoto' | 'school' | 'inter';

export interface AppUser {
  id: string;
  name: string;
  role: string;
  allowedTabs: string[];
}

interface AppState {
  user: AppUser | null;
  activeTab: string;
  appCategory: string;
  refDate: string; // YYYY-MM-DD
  theme: ThemeMode;
  font: FontKind;
  version: string;
  setUser: (u: AppUser | null) => void;
  setActiveTab: (t: string) => void;
  setAppCategory: (c: string) => void;
  setRefDate: (d: string) => void;
  setTheme: (t: ThemeMode) => void;
  setFont: (f: FontKind) => void;
  setVersion: (v: string) => void;
  canAccess: (tab: string) => boolean;
  logout: () => void;
}

function todayStr(): string {
  const d = new Date();
  const m = `${d.getMonth() + 1}`.padStart(2, '0');
  const day = `${d.getDate()}`.padStart(2, '0');
  return `${d.getFullYear()}-${m}-${day}`;
}

export const FONT_OPTIONS: { value: FontKind; label: string }[] = [
  { value: 'system', label: '시스템' },
  { value: 'pretendard', label: 'Pretendard' },
  { value: 'noto', label: 'Noto Sans KR' },
  { value: 'githubnoto', label: 'GitHub Noto' },
  { value: 'school', label: '학교안심우주체' },
  { value: 'inter', label: 'Inter' },
];

export const useAppStore = create<AppState>()(
  persist(
    (set, get) => ({
      user: null,
      activeTab: '시간표 조회',
      appCategory: '교사',
      refDate: todayStr(),
      theme: 'light',
      font: 'pretendard',
      version: '',
      setUser: (user) => set({ user }),
      setActiveTab: (activeTab) => set({ activeTab }),
      setAppCategory: (appCategory) => set({ appCategory }),
      setRefDate: (refDate) => set({ refDate }),
      setTheme: (theme) => set({ theme }),
      setFont: (font) => set({ font }),
      setVersion: (version) => set({ version }),
      canAccess: (tab) => {
        const { user } = get();
        if (!user) return false;
        if (user.role === '마스터') return true;
        return user.allowedTabs.includes(tab);
      },
      logout: () => set({ user: null }),
    }),
    { name: 'timetable-app-store', partialize: (s) => ({ ...s, user: s.user }) },
  ),
);
