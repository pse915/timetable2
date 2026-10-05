import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useMemo, useState } from 'react';
import {
  applyCycleSwap,
  applyLinkedSwap,
  applySwap,
  assignSub,
  cancelSub,
  createAbsence,
  downloadBlob,
  fetchAbsences,
  fetchChangedTeachers,
  fetchEffectiveWeek,
  fetchNeisWeek,
  fetchTeacherWeek,
  recommendSubs,
  recommendSwapTarget,
  saveBlob,
  searchSwapCycles,
  validateSwap,
  type EffectiveRow,
  type RecommendItem,
} from '../api';
import { ActionDialog, EmptyState, KpiCards, RecommendTable } from '../components/ui';
import { CalendarPicker, WeekMatrix, WeekPicker, mondayOf, type SlotKey } from '../components/pickers';
import { useAppStore } from '../store/useAppStore';

/* ---------- TimetableView (ex pages/TimetableView.tsx) ---------- */

export function TimetableViewPage() {
  const refDate = useAppStore((s) => s.refDate);
  const setRefDate = useAppStore((s) => s.setRefDate);
  const appCategory = useAppStore((s) => s.appCategory);
  const setAppCategory = useAppStore((s) => s.setAppCategory);
  const [mode, setMode] = useState<'teacher' | 'class'>('teacher');
  const [selected, setSelected] = useState<{ slot: SlotKey; cell?: EffectiveRow } | null>(null);

  const monday = mondayOf(refDate);
  const weekQ = useQuery({
    queryKey: ['effective-week', monday],
    queryFn: () => fetchEffectiveWeek(monday),
  });
  const neisQ = useQuery({ queryKey: ['neis-week', monday], queryFn: () => fetchNeisWeek(monday), retry: false });

  const { rows, cells } = useMemo(() => {
    const days = weekQ.data?.days ?? {};
    const rowSet = new Set<string>();
    const map = new Map<string, EffectiveRow>();
    for (const [day, list] of Object.entries(days)) {
      for (const r of list as EffectiveRow[]) {
        const key = mode === 'teacher' ? r.교사명 : r.학급;
        if (!key) continue;
        rowSet.add(key);
        map.set(`${key}|${day}|${r.교시}`, r);
      }
    }
    return { rows: [...rowSet].sort(), cells: map };
  }, [weekQ.data, mode]);

  const neisOff = useMemo(() => {
    const m = new Map<string, string>();
    const recs = (neisQ.data as unknown as { records?: Record<string, unknown>[] })?.records ?? [];
    for (const r of recs) {
      const dateStr = String(r['일자'] ?? r['date'] ?? '');
      const label = String(r['명칭'] ?? r['label'] ?? '');
      if (!dateStr) continue;
      const dow = new Date(`${dateStr}T00:00:00`).getDay();
      const kr = ['일', '월', '화', '수', '목', '금', '토'][dow] ?? '';
      if (kr && label) m.set(kr, label);
    }
    return m;
  }, [neisQ.data]);

  const download = async (kind: 'teacher' | 'class') => {
    const blob = await downloadBlob(
      kind === 'teacher' ? '/api/export/teacher-week.xlsx' : '/api/export/class-week.xlsx',
      { start: monday },
    );
    saveBlob(blob, kind === 'teacher' ? 'teacher-week.xlsx' : 'class-week.xlsx');
  };

  return (
    <div className="page">
      <h2>시간표 조회</h2>
      <div className="toolbar">
        <CalendarPicker value={refDate} onChange={setRefDate} />
        <WeekPicker value={monday} onChange={setRefDate} />
        <select className="select" value={appCategory} onChange={(e) => setAppCategory(e.target.value)}>
          <option value="교사">교사</option>
          <option value="학급">학급</option>
        </select>
        <select className="select" value={mode} onChange={(e) => setMode(e.target.value as 'teacher' | 'class')}>
          <option value="teacher">교사별</option>
          <option value="class">학급별</option>
        </select>
        <button className="btn-pill" onClick={() => void download('teacher')}>교사 주간표 Excel</button>
        <button className="btn-pill" onClick={() => void download('class')}>학급 주간표 Excel</button>
      </div>
      {weekQ.isLoading && <WeekMatrix rows={[]} cells={new Map()} loading />}
      {weekQ.isError && <EmptyState message="시간표를 불러오지 못했습니다." />}
      {weekQ.data && (
        <>
          <KpiCards
            items={[
              { label: '기준주', value: `${monday} ~` },
              { label: mode === 'teacher' ? '교사 수' : '학급 수', value: `${rows.length}` },
              { label: '휴업일', value: `${neisOff.size}일` },
            ]}
          />
          <WeekMatrix
            rows={rows}
            cells={cells}
            neisOff={neisOff}
            hidePastThisWeek
            todayStr={refDate}
            onSelect={(slot, cell) => setSelected({ slot, cell })}
          />
        </>
      )}
      <ActionDialog open={!!selected} title="슬롯 상세" onClose={() => setSelected(null)}>
        {selected && (
          <div className="kv">
            <div>행: {selected.slot.row}</div>
            <div>요일/교시: {selected.slot.day} {selected.slot.period}교시</div>
            <div>과목: {selected.cell?.과목 ?? '-'}</div>
            <div>학급: {selected.cell?.학급 ?? '-'}</div>
            <div>변경유형: {selected.cell?.변경유형 ?? '원본'}</div>
          </div>
        )}
      </ActionDialog>
    </div>
  );
}

/* ---------- AbsenceSub (ex pages/AbsenceSub.tsx) ---------- */

export function AbsenceSubPage() {
  const refDate = useAppStore((s) => s.refDate);
  const setRefDate = useAppStore((s) => s.setRefDate);
  const user = useAppStore((s) => s.user);
  const qc = useQueryClient();
  const [form, setForm] = useState({ teacher: '', day: '월', period: 1, class_name: '', subject: '', reason: '병가' });
  const [recs, setRecs] = useState<RecommendItem[]>([]);
  const [recLoading, setRecLoading] = useState(false);
  const [cancelCid, setCancelCid] = useState('');
  const [msg, setMsg] = useState('');
  const [dialog, setDialog] = useState(false);

  const absQ = useQuery({ queryKey: ['absences', refDate], queryFn: () => fetchAbsences({ date: refDate }) });

  const createMut = useMutation({
    mutationFn: () =>
      createAbsence({ ...form, date: refDate, user: user?.name ?? '' }),
    onSuccess: () => {
      setMsg('결강이 등록되었습니다.');
      void qc.invalidateQueries({ queryKey: ['absences'] });
    },
    onError: (e: Error) => setMsg(e.message),
  });

  const recommend = async () => {
    setRecLoading(true);
    setMsg('');
    try {
      const r = await recommendSubs({
        day: form.day,
        period: form.period,
        subject: form.subject,
        class_name: form.class_name,
        absent_teacher: form.teacher,
        date: refDate,
        top_n: 20,
      });
      setRecs(r.items ?? []);
    } catch (e) {
      setMsg(e instanceof Error ? e.message : '추천 실패');
    } finally {
      setRecLoading(false);
    }
  };

  const apply = async (item: RecommendItem) => {
    setMsg('');
    try {
      await assignSub({
        date: refDate,
        day: form.day,
        period: form.period,
        class_name: form.class_name,
        subject: form.subject,
        absent_teacher: form.teacher,
        sub_teacher: item.teacher,
        user: user?.name ?? '',
      });
      setMsg(`${item.teacher} 배정 완료`);
      void qc.invalidateQueries({ queryKey: ['absences'] });
    } catch (e) {
      setMsg(e instanceof Error ? e.message : '배정 실패');
    }
  };

  const cancel = async () => {
    if (!cancelCid.trim()) return;
    try {
      await cancelSub(cancelCid.trim());
      setMsg('보강이 취소되었습니다.');
      setCancelCid('');
      void qc.invalidateQueries({ queryKey: ['absences'] });
    } catch (e) {
      setMsg(e instanceof Error ? e.message : '취소 실패');
    }
  };

  const list = (absQ.data ?? []) as Record<string, string>[];

  return (
    <div className="page">
      <h2>결강·보강</h2>
      <div className="toolbar">
        <CalendarPicker value={refDate} onChange={setRefDate} />
      </div>
      <KpiCards
        items={[
          { label: '기준일', value: refDate },
          { label: '결강 건수', value: `${list.length}` },
          { label: '추천 후보', value: `${recs.length}` },
        ]}
      />
      <div className="grid2">
        <div className="card">
          <h3>결강 등록</h3>
          <div className="form-grid">
            <input className="input" placeholder="결강 교사" value={form.teacher} onChange={(e) => setForm({ ...form, teacher: e.target.value })} />
            <input className="input" placeholder="학급" value={form.class_name} onChange={(e) => setForm({ ...form, class_name: e.target.value })} />
            <input className="input" placeholder="과목" value={form.subject} onChange={(e) => setForm({ ...form, subject: e.target.value })} />
            <select className="select" value={form.day} onChange={(e) => setForm({ ...form, day: e.target.value })}>
              {['월', '화', '수', '목', '금'].map((d) => <option key={d} value={d}>{d}</option>)}
            </select>
            <input className="input" type="number" min={1} max={7} value={form.period} onChange={(e) => setForm({ ...form, period: Number(e.target.value) })} />
            <select className="select" value={form.reason} onChange={(e) => setForm({ ...form, reason: e.target.value })}>
              {['병가', '연가', '출장', '공가', '조퇴', '외출', '연수', '특별휴가', '기타'].map((r) => <option key={r} value={r}>{r}</option>)}
            </select>
          </div>
          <div className="row-gap">
            <button className="btn-pill primary" disabled={createMut.isPending} onClick={() => createMut.mutate()}>
              결강 등록
            </button>
            <button className="btn-pill" onClick={() => void recommend()}>보강 추천</button>
            <button className="btn-pill" onClick={() => setDialog(true)}>셀 선택 액션</button>
          </div>
          {msg && <p className="muted">{msg}</p>}
        </div>
        <div className="card">
          <h3>보강 취소</h3>
          <input className="input" placeholder="변경ID(cid)" value={cancelCid} onChange={(e) => setCancelCid(e.target.value)} />
          <button className="btn-pill" onClick={() => void cancel()}>취소</button>
        </div>
      </div>
      <h3>보강 추천</h3>
      <RecommendTable items={recs} loading={recLoading} onApply={(it) => void apply(it)} />
      <h3>당일 결강 목록</h3>
      {absQ.isLoading && <div className="skeleton-row" />}
      {absQ.isError && <EmptyState message="결강 목록을 불러오지 못했습니다." />}
      {absQ.data && list.length === 0 && <EmptyState message="결강이 없습니다." />}
      {list.length > 0 && (
        <div className="table-wrap">
          <table className="table">
            <thead><tr><th>교사</th><th>학급</th><th>과목</th><th>교시</th></tr></thead>
            <tbody>
              {list.map((a, i) => (
                <tr key={i}>
                  <td>{a.teacher ?? a['교사명'] ?? ''}</td>
                  <td>{a.class_name ?? a['학급'] ?? ''}</td>
                  <td>{a.subject ?? a['과목'] ?? ''}</td>
                  <td>{a.period ?? a['교시'] ?? ''}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <ActionDialog open={dialog} title="결강/보강 액션" onClose={() => setDialog(false)}>
        <div className="row-gap">
          <button className="btn-pill primary" onClick={() => createMut.mutate()}>결강 등록</button>
          <button className="btn-pill" onClick={() => void recommend()}>추천 조회</button>
        </div>
      </ActionDialog>
    </div>
  );
}

/* ---------- Swap (ex pages/Swap.tsx) ---------- */

export function SwapPage() {
  const user = useAppStore((s) => s.user);
  const [form, setForm] = useState({
    teacherA: '', dayA: '월', periodA: 1, dateA: '',
    teacherB: '', dayB: '화', periodB: 1, dateB: '',
    budgetFactor: 1.0,
  });
  const [msg, setMsg] = useState('');
  const [recs, setRecs] = useState<RecommendItem[]>([]);
  const [cycles, setCycles] = useState<unknown[]>([]);
  const [loading, setLoading] = useState(false);
  const set = (k: keyof typeof form, v: string | number) => setForm({ ...form, [k]: v });

  const payload = () => ({
    teacherA: form.teacherA, dayA: form.dayA, periodA: form.periodA, dateA: form.dateA,
    teacherB: form.teacherB, dayB: form.dayB, periodB: form.periodB, dateB: form.dateB,
    user: user?.name ?? '',
  });

  const run = async (fn: (p: Record<string, unknown>) => Promise<unknown>, label: string) => {
    setMsg('');
    try {
      await fn(payload());
      setMsg(`${label} 성공`);
    } catch (e) {
      setMsg(e instanceof Error ? e.message : `${label} 실패`);
    }
  };

  const recommend = async () => {
    setLoading(true);
    try {
      const r = await recommendSwapTarget({ ...payload(), budgetFactor: form.budgetFactor });
      setRecs(r.items ?? []);
    } catch (e) {
      setMsg(e instanceof Error ? e.message : '추천 실패');
    } finally {
      setLoading(false);
    }
  };

  const searchCycles = async () => {
    setLoading(true);
    try {
      const r = await searchSwapCycles(payload());
      setCycles(r.cycles ?? []);
    } catch (e) {
      setMsg(e instanceof Error ? e.message : '순환 검색 실패');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="page">
      <h2>시간표 맞교환 &amp; 변경 추천</h2>
      <KpiCards
        items={[
          { label: '교사A', value: form.teacherA || '-' },
          { label: '교사B', value: form.teacherB || '-' },
          { label: '예산 factor', value: `${form.budgetFactor}` },
        ]}
      />
      <div className="card">
        <h3>1:1 맞교환</h3>
        <div className="form-grid">
          <input className="input" placeholder="교사A" value={form.teacherA} onChange={(e) => set('teacherA', e.target.value)} />
          <input className="input" type="date" value={form.dateA} onChange={(e) => set('dateA', e.target.value)} />
          <select className="select" value={form.dayA} onChange={(e) => set('dayA', e.target.value)}>
            {['월', '화', '수', '목', '금'].map((d) => <option key={d} value={d}>{d}</option>)}
          </select>
          <input className="input" type="number" min={1} max={7} value={form.periodA} onChange={(e) => set('periodA', Number(e.target.value))} />
          <input className="input" placeholder="교사B" value={form.teacherB} onChange={(e) => set('teacherB', e.target.value)} />
          <input className="input" type="date" value={form.dateB} onChange={(e) => set('dateB', e.target.value)} />
          <select className="select" value={form.dayB} onChange={(e) => set('dayB', e.target.value)}>
            {['월', '화', '수', '목', '금'].map((d) => <option key={d} value={d}>{d}</option>)}
          </select>
          <input className="input" type="number" min={1} max={7} value={form.periodB} onChange={(e) => set('periodB', Number(e.target.value))} />
          <input className="input" type="number" step={0.1} value={form.budgetFactor} onChange={(e) => set('budgetFactor', Number(e.target.value))} />
        </div>
        <div className="row-gap">
          <button className="btn-pill" onClick={() => void run(validateSwap, '검증')}>검증</button>
          <button className="btn-pill primary" onClick={() => void run(applySwap, '맞교환 적용')}>1:1 적용</button>
          <button className="btn-pill" onClick={() => void run(applyLinkedSwap, '연계 적용')}>연계순환 적용</button>
          <button className="btn-pill" onClick={() => void run(applyCycleSwap, '사이클 적용')}>사이클 적용</button>
          <button className="btn-pill" onClick={() => void recommend()}>목표 추천</button>
          <button className="btn-pill" onClick={() => void searchCycles()}>순환 탐색</button>
        </div>
        {msg && <p className="muted">{msg}</p>}
      </div>
      <h3>목표 추천</h3>
      <RecommendTable items={recs} loading={loading} onApply={(it) => setForm({ ...form, teacherB: it.teacher })} applyLabel="B로 지정" />
      <h3>순환 후보</h3>
      {cycles.length === 0 ? <EmptyState message="순환 후보가 없습니다." /> : (
        <div className="table-wrap">
          <table className="table">
            <tbody>
              {cycles.map((c, i) => (
                <tr key={i}><td>{JSON.stringify(c).slice(0, 200)}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

/* ---------- TestSwap (ex pages/TestSwap.tsx) ---------- */

interface SandboxItem {
  id: number;
  desc: string;
}

export function TestSwapPage() {
  const user = useAppStore((s) => s.user);
  const [items, setItems] = useState<SandboxItem[]>([]);
  const [draft, setDraft] = useState('');
  const [msg, setMsg] = useState('');

  const add = () => {
    if (!draft.trim()) return;
    setItems([...items, { id: Date.now(), desc: draft.trim() }]);
    setDraft('');
  };

  const commit = async () => {
    setMsg('');
    try {
      for (const it of items) {
        await applySwap({ memo: it.desc, user: user?.name ?? '', test: true });
      }
      setMsg(`sandbox ${items.length}건 확정 시도 완료`);
    } catch (e) {
      setMsg(e instanceof Error ? e.message : '확정 실패');
    }
  };

  const discard = () => {
    setItems([]);
    setMsg('sandbox를 파기했습니다.');
  };

  return (
    <div className="page">
      <h2>시간표 변경 테스트용 (Sandbox)</h2>
      <div className="card">
        <div className="row-gap">
          <input className="input grow" placeholder="테스트 변경 메모 (예: 월3 A↔화2 B)" value={draft} onChange={(e) => setDraft(e.target.value)} />
          <button className="btn-pill primary" onClick={add}>추가</button>
          <button className="btn-pill" onClick={() => void commit()}>확정</button>
          <button className="btn-pill danger" onClick={discard}>파기</button>
        </div>
        {msg && <p className="muted">{msg}</p>}
      </div>
      {items.length === 0 ? <EmptyState message="sandbox가 비어 있습니다." /> : (
        <div className="table-wrap">
          <table className="table">
            <thead><tr><th>#</th><th>내용</th><th /></tr></thead>
            <tbody>
              {items.map((it, i) => (
                <tr key={it.id}>
                  <td>{i + 1}</td>
                  <td>{it.desc}</td>
                  <td><button className="btn-pill" onClick={() => setItems(items.filter((x) => x.id !== it.id))}>삭제</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

/* ---------- ChangedTeachers (ex pages/ChangedTeachers.tsx) ---------- */

export function ChangedTeachersPage() {
  const refDate = useAppStore((s) => s.refDate);
  const setRefDate = useAppStore((s) => s.setRefDate);
  const monday = mondayOf(refDate);
  const [teacher, setTeacher] = useState('');

  const changedQ = useQuery({ queryKey: ['changed', monday], queryFn: () => fetchChangedTeachers(monday) });
  const weekQ = useQuery({
    queryKey: ['teacher-week', teacher, monday],
    queryFn: () => fetchTeacherWeek(teacher, monday),
    enabled: !!teacher,
  });

  const teachers: string[] = changedQ.data?.teachers ?? [];
  const cells = useMemo(() => {
    const m = new Map<string, EffectiveRow>();
    for (const r of weekQ.data?.rows ?? []) {
      m.set(`${r.교사명}|${r.요일}|${r.교시}`, r);
    }
    return m;
  }, [weekQ.data]);

  return (
    <div className="page">
      <h2>변경된 교사 주간표</h2>
      <div className="toolbar">
        <WeekPicker value={monday} onChange={setRefDate} />
        <select className="select" value={teacher} onChange={(e) => setTeacher(e.target.value)}>
          <option value="">교사 선택</option>
          {teachers.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
      </div>
      <KpiCards
        items={[
          { label: '기준주', value: monday },
          { label: '변경 교사 수', value: `${teachers.length}` },
          { label: '선택 교사', value: teacher || '-' },
        ]}
      />
      {changedQ.isLoading && <div className="skeleton-row" />}
      {changedQ.isError && <EmptyState message="변경 교사 목록을 불러오지 못했습니다." />}
      {changedQ.data && teachers.length === 0 && <EmptyState message="변경된 교사가 없습니다." />}
      {teacher ? (
        weekQ.isLoading ? <WeekMatrix rows={[]} cells={new Map()} loading /> :
        weekQ.isError ? <EmptyState message="주간표를 불러오지 못했습니다." /> :
        <WeekMatrix rows={[teacher]} cells={cells} hidePastThisWeek todayStr={refDate} />
      ) : (
        <div className="chip-row">
          {teachers.map((t) => (
            <button key={t} className="btn-pill" onClick={() => setTeacher(t)}>{t}</button>
          ))}
        </div>
      )}
    </div>
  );
}
