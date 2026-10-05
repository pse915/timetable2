import clsx from 'clsx';
import { format } from 'date-fns';
import { useMemo, useState } from 'react';
import type { EffectiveRow } from '../api';
import { EmptyState } from './ui';

/* ---------- CalendarPicker (ex components/CalendarPicker.tsx) ---------- */

interface CalendarPickerProps {
  value: string;
  onChange: (date: string) => void;
}

export function CalendarPicker({ value, onChange }: CalendarPickerProps) {
  const [cursor, setCursor] = useState(() => value.slice(0, 7));
  const cells = useMemo(() => {
    const [y, m] = cursor.split('-').map(Number);
    const first = new Date(y, (m as number) - 1, 1);
    const startDay = first.getDay();
    const daysInMonth = new Date(y, m as number, 0).getDate();
    const out: (string | null)[] = [];
    for (let i = 0; i < startDay; i++) out.push(null);
    for (let d = 1; d <= daysInMonth; d++) {
      out.push(`${y}-${String(m).padStart(2, '0')}-${String(d).padStart(2, '0')}`);
    }
    return out;
  }, [cursor]);

  const move = (delta: number) => {
    const [y, m] = cursor.split('-').map(Number);
    const d = new Date(y as number, (m as number) - 1 + delta, 1);
    setCursor(format(d, 'yyyy-MM'));
  };

  return (
    <div className="picker-card">
      <div className="picker-head">
        <button className="btn-pill" onClick={() => move(-1)}>‹</button>
        <strong>{cursor}</strong>
        <button className="btn-pill" onClick={() => move(1)}>›</button>
      </div>
      <div className="cal-grid">
        {['일', '월', '화', '수', '목', '금', '토'].map((w) => (
          <span key={w} className="cal-dow">{w}</span>
        ))}
        {cells.map((d, i) =>
          d ? (
            <button
              key={i}
              className={`cal-day${d === value ? ' active' : ''}`}
              onClick={() => onChange(d)}
            >
              {Number(d.slice(8))}
            </button>
          ) : (
            <span key={i} />
          ),
        )}
      </div>
    </div>
  );
}

/* ---------- WeekPicker (ex components/WeekPicker.tsx) ---------- */

interface WeekPickerProps {
  value: string; // 주 시작일(월요일) YYYY-MM-DD
  onChange: (monday: string) => void;
}

export function mondayOf(dateStr: string): string {
  const d = new Date(`${dateStr}T00:00:00`);
  const dow = (d.getDay() + 6) % 7;
  d.setDate(d.getDate() - dow);
  const m = `${d.getMonth() + 1}`.padStart(2, '0');
  const day = `${d.getDate()}`.padStart(2, '0');
  return `${d.getFullYear()}-${m}-${day}`;
}

function shift(monday: string, delta: number): string {
  const d = new Date(`${monday}T00:00:00`);
  d.setDate(d.getDate() + delta);
  const m = `${d.getMonth() + 1}`.padStart(2, '0');
  const day = `${d.getDate()}`.padStart(2, '0');
  return `${d.getFullYear()}-${m}-${day}`;
}

function fridayOf(monday: string): string {
  return shift(monday, 4);
}

export function WeekPicker({ value, onChange }: WeekPickerProps) {
  const mon = mondayOf(value);
  return (
    <div className="picker-card picker-inline">
      <button className="btn-pill" onClick={() => onChange(shift(mon, -7))}>‹ 이전주</button>
      <strong>{mon} ~ {fridayOf(mon)} (월~금)</strong>
      <button className="btn-pill" onClick={() => onChange(shift(mon, 7))}>다음주 ›</button>
    </div>
  );
}

/* ---------- RangePicker (ex components/RangePicker.tsx) ---------- */

interface RangePickerProps {
  start: string;
  end: string;
  onChange: (start: string, end: string) => void;
}

export function RangePicker({ start, end, onChange }: RangePickerProps) {
  return (
    <div className="picker-card picker-inline">
      <label>
        시작 <input type="date" className="input" value={start} onChange={(e) => onChange(e.target.value, end)} />
      </label>
      <span>~</span>
      <label>
        종료 <input type="date" className="input" value={end} onChange={(e) => onChange(start, e.target.value)} />
      </label>
    </div>
  );
}

/* ---------- PeriodPicker (ex components/PeriodPicker.tsx) ---------- */

interface PeriodPickerProps {
  selected: Set<string>; // "월|3"
  onToggle: (key: string) => void;
  onClear: () => void;
  onSelectAll: () => void;
  multi?: boolean;
}

export function PeriodPicker({ selected, onToggle, onClear, onSelectAll, multi = true }: PeriodPickerProps) {
  return (
    <div className="picker-card">
      <div className="picker-head">
        <strong>교시 선택{multi ? ' (다중)' : ' (단일)'}</strong>
        <div className="row-gap">
          <button className="btn-pill" onClick={onSelectAll}>전체선택</button>
          <button className="btn-pill" onClick={onClear}>해제</button>
        </div>
      </div>
      <div className="period-grid">
        {DEFAULT_DAYS.map((d) => (
          <div key={d} className="period-row">
            <span className="period-day">{d}</span>
            {Array.from({ length: DEFAULT_PPD[d] ?? 6 }).map((_, i) => {
              const p = i + 1;
              const key = `${d}|${p}`;
              const on = selected.has(key);
              return (
                <button
                  key={key}
                  className={`period-cell${on ? ' active' : ''}`}
                  onClick={() => onToggle(key)}
                >
                  {p}
                </button>
              );
            })}
          </div>
        ))}
      </div>
    </div>
  );
}

/* ---------- WeekMatrix (ex components/WeekMatrix.tsx) ---------- */

export interface SlotKey {
  row: string;
  day: string;
  period: number;
}

interface WeekMatrixProps {
  rows: string[];
  days?: string[];
  periodsPerDay?: Record<string, number>;
  cells: Map<string, EffectiveRow>;
  neisOff?: Map<string, string>;
  loading?: boolean;
  hidePastThisWeek?: boolean;
  onSelect?: (slot: SlotKey, cell?: EffectiveRow) => void;
  todayStr?: string;
  weekDates?: Record<string, string>;
}

export const DEFAULT_DAYS = ['월', '화', '수', '목', '금'];
export const DEFAULT_PPD: Record<string, number> = { 월: 6, 화: 7, 수: 7, 목: 7, 금: 6 };

function cellClass(cell?: EffectiveRow): string {
  if (!cell) return 'cell';
  const t = cell.변경유형 ?? '원본';
  if (t === '교환') return 'cell swap';
  if (t === '보강') return 'cell sub';
  if (t === '테스트교환') return 'cell test';
  if (t === '시간강사') return 'cell pt';
  return 'cell';
}

export function WeekMatrix({
  rows,
  days = DEFAULT_DAYS,
  periodsPerDay = DEFAULT_PPD,
  cells,
  neisOff,
  loading,
  hidePastThisWeek,
  onSelect,
  todayStr,
  weekDates,
}: WeekMatrixProps) {
  const [hidePast, setHidePast] = useState<boolean>(!!hidePastThisWeek);

  const columns = useMemo(() => {
    const cols: { day: string; period: number }[] = [];
    for (const d of days) {
      const n = periodsPerDay[d] ?? 6;
      for (let p = 1; p <= n; p++) cols.push({ day: d, period: p });
    }
    return cols;
  }, [days, periodsPerDay]);

  if (loading) {
    return (
      <div className="matrix-wrap">
        <div className="skeleton-grid" aria-label="로딩 중">
          {Array.from({ length: 24 }).map((_, i) => (
            <div key={i} className="skeleton" />
          ))}
        </div>
      </div>
    );
  }

  if (rows.length === 0) return <EmptyState message="표시할 행이 없습니다." />;

  const isPast = (day: string): boolean => {
    if (!hidePast || !todayStr || !weekDates) return false;
    const d = weekDates[day];
    return !!d && d < todayStr;
  };

  return (
    <div className="matrix-wrap">
      <label className="checkline">
        <input type="checkbox" checked={hidePast} onChange={(e) => setHidePast(e.target.checked)} />
        당주 과거 슬롯 숨기기
      </label>
      <div className="matrix-scroll">
        <table className="matrix">
          <thead>
            <tr>
              <th className="sticky-col head">구분</th>
              {columns.map((c) =>
                isPast(c.day) ? null : (
                  <th key={`${c.day}${c.period}`} className="head">
                    {c.day}{c.period}
                  </th>
                ),
              )}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r}>
                <th className="sticky-col">{r}</th>
                {columns.map((c) => {
                  if (isPast(c.day)) return null;
                  const key = `${r}|${c.day}|${c.period}`;
                  const cell = cells.get(key);
                  const offLabel = neisOff?.get(c.day);
                  return (
                    <td
                      key={key}
                      className={clsx(cellClass(cell), offLabel && 'off')}
                      onClick={() => onSelect?.({ row: r, day: c.day, period: c.period }, cell)}
                      title={offLabel ?? `${r} ${c.day}${c.period}`}
                    >
                      {offLabel ? (
                        <span className="off-label">{offLabel}</span>
                      ) : (
                        <>
                          <div className="cell-subject">{cell?.과목 ?? ''}</div>
                          <div className="cell-class">{cell?.학급 ?? ''}</div>
                        </>
                      )}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
