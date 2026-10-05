import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import {
  assignSubBatch,
  createDuty,
  downloadBlob,
  fetchDuties,
  fetchPartTime,
  fetchStats,
  recommendSubs,
  saveBlob,
  upsertPartTime,
  type RecommendItem,
} from '../api';
import { EmptyState, KpiCards, RecommendTable } from '../components/ui';
import { CalendarPicker, PeriodPicker, RangePicker } from '../components/pickers';
import { useAppStore } from '../store/useAppStore';

/* ---------- PartTime (ex pages/PartTime.tsx) ---------- */

export function PartTimePage() {
  const qc = useQueryClient();
  const [form, setForm] = useState({ name: '', subject: '', contact: '' });
  const [avail, setAvail] = useState<Set<string>>(new Set());
  const [msg, setMsg] = useState('');
  const ptQ = useQuery({ queryKey: ['part-time'], queryFn: fetchPartTime });

  const toggle = (key: string) => {
    const next = new Set(avail);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    setAvail(next);
  };

  const saveMut = useMutation({
    mutationFn: () => upsertPartTime({ ...form, available: [...avail] }),
    onSuccess: () => {
      setMsg('저장되었습니다.');
      setForm({ name: '', subject: '', contact: '' });
      setAvail(new Set());
      void qc.invalidateQueries({ queryKey: ['part-time'] });
    },
    onError: (e: Error) => setMsg(e.message),
  });

  const list = (ptQ.data ?? []) as Record<string, string>[];

  return (
    <div className="page">
      <h2>시간강사 관리</h2>
      <KpiCards
        items={[
          { label: '등록 강사', value: `${list.length}` },
          { label: '가능 슬롯', value: `${avail.size}` },
          { label: '상태', value: ptQ.isLoading ? '로딩' : ptQ.isError ? '오류' : '정상' },
        ]}
      />
      <div className="grid2">
        <div className="card">
          <h3>강사 등록/수정 (CRUD)</h3>
          <div className="form-grid">
            <input className="input" placeholder="이름" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
            <input className="input" placeholder="과목" value={form.subject} onChange={(e) => setForm({ ...form, subject: e.target.value })} />
            <input className="input" placeholder="연락처" value={form.contact} onChange={(e) => setForm({ ...form, contact: e.target.value })} />
          </div>
          <button className="btn-pill primary" disabled={saveMut.isPending} onClick={() => saveMut.mutate()}>저장</button>
          {msg && <p className="muted">{msg}</p>}
        </div>
        <PeriodPicker
          selected={avail}
          onToggle={toggle}
          onClear={() => setAvail(new Set())}
          onSelectAll={() => {
            const all = new Set<string>();
            for (const d of ['월', '화', '수', '목', '금']) for (let p = 1; p <= 6; p++) all.add(`${d}|${p}`);
            setAvail(all);
          }}
        />
      </div>
      <h3>강사 목록 + 가능 매트릭스 검증</h3>
      {ptQ.isLoading && <div className="skeleton-row" />}
      {ptQ.isError && <EmptyState message="시간강사 목록을 불러오지 못했습니다." />}
      {ptQ.data && list.length === 0 && <EmptyState message="등록된 시간강사가 없습니다." />}
      {list.length > 0 && (
        <div className="table-wrap">
          <table className="table">
            <thead><tr><th>이름</th><th>과목</th><th>연락처</th><th>가능</th></tr></thead>
            <tbody>
              {list.map((p, i) => (
                <tr key={i}>
                  <td>{String(p.name ?? p['이름'] ?? '')}</td>
                  <td>{String(p.subject ?? p['과목'] ?? '')}</td>
                  <td>{String(p.contact ?? p['연락처'] ?? '')}</td>
                  <td className="muted">{String((p.available as unknown) ?? p['가능'] ?? '-')}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

/* ---------- Stats (ex pages/Stats.tsx) ---------- */

export function StatsPage() {
  const [range, setRange] = useState({ start: '', end: '' });
  const statsQ = useQuery({
    queryKey: ['stats', range.start, range.end],
    queryFn: () => fetchStats({ start: range.start || undefined, end: range.end || undefined }),
  });

  const subs = statsQ.data?.subCounts ?? {};
  const hours = statsQ.data?.weeklyHours ?? {};
  const names = [...new Set([...Object.keys(subs), ...Object.keys(hours)])].sort();
  const totalSubs = Object.values(subs).reduce((a, b) => a + (Number(b) || 0), 0);

  const exportXlsx = async () => {
    const blob = await downloadBlob('/api/export/teacher-week.xlsx', { start: range.start || undefined });
    saveBlob(blob, 'stats.xlsx');
  };

  return (
    <div className="page">
      <h2>통계</h2>
      <div className="toolbar">
        <RangePicker start={range.start} end={range.end} onChange={(s, e) => setRange({ start: s, end: e })} />
        <button className="btn-pill" onClick={() => void statsQ.refetch()}>조회</button>
        <button className="btn-pill" onClick={() => void exportXlsx()}>Excel</button>
      </div>
      <KpiCards
        items={[
          { label: '누적 보강 총합', value: `${totalSubs}` },
          { label: '집계 교사', value: `${names.length}` },
          { label: '기간', value: range.start && range.end ? `${range.start}~${range.end}` : '전체' },
        ]}
      />
      {statsQ.isLoading && <div className="skeleton-row" />}
      {statsQ.isError && <EmptyState message="통계를 불러오지 못했습니다." />}
      {statsQ.data && names.length === 0 && <EmptyState message="통계 데이터가 없습니다." />}
      {names.length > 0 && (
        <div className="table-wrap">
          <table className="table">
            <thead><tr><th>교사</th><th>누적 보강</th><th>주당 시수</th></tr></thead>
            <tbody>
              {names.map((n) => (
                <tr key={n}>
                  <td>{n}</td>
                  <td>{subs[n] ?? 0}</td>
                  <td>{hours[n] ?? '-'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

/* ---------- Duty (ex pages/Duty.tsx) ---------- */

const REASONS = ['병가', '연가', '출장', '공가', '조퇴', '외출', '연수', '특별휴가', '기타'];

export function DutyPage() {
  const refDate = useAppStore((s) => s.refDate);
  const setRefDate = useAppStore((s) => s.setRefDate);
  const user = useAppStore((s) => s.user);
  const qc = useQueryClient();
  const [form, setForm] = useState({ teacher: '', period: 1, reason: '연가', detail: '' });
  const [msg, setMsg] = useState('');
  const dutyQ = useQuery({ queryKey: ['duties', refDate], queryFn: () => fetchDuties({ date: refDate }) });

  const mut = useMutation({
    mutationFn: () => createDuty({ ...form, date: refDate, user: user?.name ?? '' }),
    onSuccess: () => {
      setMsg('복무가 등록되었습니다.');
      setForm({ teacher: '', period: 1, reason: '연가', detail: '' });
      void qc.invalidateQueries({ queryKey: ['duties'] });
    },
    onError: (e: Error) => setMsg(e.message),
  });

  const list = (dutyQ.data ?? []) as Record<string, string | number>[];
  const judged = list.filter((d) => String(d['판단'] ?? d.judgment ?? '').length > 0).length;

  return (
    <div className="page">
      <h2>📋 복무 관리 &amp; 판단</h2>
      <div className="toolbar">
        <CalendarPicker value={refDate} onChange={setRefDate} />
      </div>
      <KpiCards
        items={[
          { label: '기준일', value: refDate },
          { label: '복무 건수', value: `${list.length}` },
          { label: '판단 완료', value: `${judged}` },
        ]}
      />
      <div className="card">
        <h3>복무 등록</h3>
        <div className="form-grid">
          <input className="input" placeholder="교사명" value={form.teacher} onChange={(e) => setForm({ ...form, teacher: e.target.value })} />
          <input className="input" type="number" min={1} max={7} value={form.period} onChange={(e) => setForm({ ...form, period: Number(e.target.value) })} />
          <select className="select" value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value })}>
            {REASONS.map((r) => <option key={r} value={r}>{r}</option>)}
          </select>
          <input className="input" placeholder="상세사유" value={form.detail} onChange={(e) => setForm({ ...form, detail: e.target.value })} />
        </div>
        <button className="btn-pill primary" disabled={mut.isPending} onClick={() => mut.mutate()}>등록</button>
        {msg && <p className="muted">{msg}</p>}
        <p className="muted">판단: 서버가 결강/보강 필요 여부를 자동 판단합니다 (병가·연가·출장 → 결강 처리).</p>
      </div>
      {dutyQ.isLoading && <div className="skeleton-row" />}
      {dutyQ.isError && <EmptyState message="복무 목록을 불러오지 못했습니다." />}
      {dutyQ.data && list.length === 0 && <EmptyState message="복무 내역이 없습니다." />}
      {list.length > 0 && (
        <div className="table-wrap">
          <table className="table">
            <thead><tr><th>교사</th><th>일자</th><th>교시</th><th>사유</th><th>판단</th></tr></thead>
            <tbody>
              {list.map((d, i) => (
                <tr key={i}>
                  <td>{String(d.teacher ?? d['교사명'] ?? '')}</td>
                  <td>{String(d.date ?? d['일자'] ?? '')}</td>
                  <td>{String(d.period ?? d['교시'] ?? '')}</td>
                  <td>{String(d.reason ?? d['사유'] ?? '')}</td>
                  <td>{String(d.judgment ?? d['판단'] ?? '-')}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

/* ---------- MultiAdjust (ex pages/MultiAdjust.tsx) ---------- */

export function MultiAdjustPage() {
  const user = useAppStore((s) => s.user);
  const [range, setRange] = useState({ start: '', end: '' });
  const [blocked, setBlocked] = useState('');
  const [onlyMasterEdu, setOnlyMasterEdu] = useState(true);
  const [recs, setRecs] = useState<RecommendItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [msg, setMsg] = useState('');

  const blockedList = blocked.split(',').map((s) => s.trim()).filter(Boolean);
  const role = user?.role ?? '';
  const permitted = !onlyMasterEdu || role === '마스터' || role === '교육과정부';

  const recommendAll = async () => {
    if (!permitted) {
      setMsg('마스터/교육과정부만 사용할 수 있습니다.');
      return;
    }
    setLoading(true);
    setMsg('');
    try {
      const r = await recommendSubs({
        date: range.start,
        start: range.start,
        end: range.end,
        blockedTeachers: blockedList,
      });
      setRecs(r.items ?? []);
    } catch (e) {
      setMsg(e instanceof Error ? e.message : '추천 실패');
    } finally {
      setLoading(false);
    }
  };

  const applyAll = async () => {
    if (!permitted) return;
    try {
      await assignSubBatch({
        user: user?.name ?? '',
        assignments: recs.map((r) => ({ sub_teacher: r.teacher, score: r.score, start: range.start, end: range.end })),
      });
      setMsg(`${recs.length}건 전체 조정 배정 완료`);
    } catch (e) {
      setMsg(e instanceof Error ? e.message : '배정 실패');
    }
  };

  return (
    <div className="page">
      <h2>🛠️ 다중 출장·전체 조정 추천</h2>
      <div className="toolbar">
        <RangePicker start={range.start} end={range.end} onChange={(s, e) => setRange({ start: s, end: e })} />
        <label className="checkline">
          <input type="checkbox" checked={onlyMasterEdu} onChange={(e) => setOnlyMasterEdu(e.target.checked)} />
          마스터/교육과정부만
        </label>
      </div>
      <KpiCards
        items={[
          { label: '기간', value: range.start && range.end ? `${range.start}~${range.end}` : '-' },
          { label: '불가능 교사', value: `${blockedList.length}` },
          { label: '추천 후보', value: `${recs.length}` },
        ]}
      />
      <div className="card">
        <label>
          불가능 교사 (쉼표 구분)
          <input className="input" value={blocked} onChange={(e) => setBlocked(e.target.value)} placeholder="홍길동, 김교사" />
        </label>
        <div className="row-gap">
          <button className="btn-pill primary" disabled={!permitted} onClick={() => void recommendAll()}>전체 조정 추천</button>
          <button className="btn-pill" disabled={!permitted || recs.length === 0} onClick={() => void applyAll()}>일괄 배정</button>
        </div>
        {!permitted && <p className="error">권한이 없습니다 (마스터/교육과정부).</p>}
        {msg && <p className="muted">{msg}</p>}
      </div>
      <RecommendTable items={recs} loading={loading} />
      {recs.length === 0 && !loading && <EmptyState message="추천 결과가 없습니다." />}
    </div>
  );
}
