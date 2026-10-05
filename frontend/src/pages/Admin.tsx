import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { fetchIds, upsertId } from '../api';
import { TAB_ROUTES } from '../App';
import { EmptyState, KpiCards } from '../components/ui';

/* ---------- IdAdmin (ex pages/IdAdmin.tsx) ---------- */

export function IdAdminPage() {
  const qc = useQueryClient();
  const [form, setForm] = useState({ id: '', name: '', role: '일반교사' });
  const [msg, setMsg] = useState('');
  const idsQ = useQuery({ queryKey: ['admin-ids'], queryFn: fetchIds });

  const mut = useMutation({
    mutationFn: () => upsertId(form),
    onSuccess: () => {
      setMsg('저장되었습니다.');
      setForm({ id: '', name: '', role: '일반교사' });
      void qc.invalidateQueries({ queryKey: ['admin-ids'] });
    },
    onError: (e: Error) => setMsg(e.message),
  });

  const list = (idsQ.data ?? []) as Record<string, string>[];

  return (
    <div className="page">
      <h2>🔑 아이디·권한 관리</h2>
      <KpiCards
        items={[
          { label: '등록 ID', value: `${list.length}` },
          { label: '상태', value: idsQ.isLoading ? '로딩' : idsQ.isError ? '오류' : '정상' },
          { label: '역할', value: form.role },
        ]}
      />
      <div className="card">
        <h3>ID 등록/수정 (CRUD)</h3>
        <div className="form-grid">
          <input className="input" placeholder="ID" value={form.id} onChange={(e) => setForm({ ...form, id: e.target.value })} />
          <input className="input" placeholder="이름" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          <select className="select" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
            {['마스터', '교육과정부', '교무계원', '일반교사', '게스트'].map((r) => <option key={r} value={r}>{r}</option>)}
          </select>
        </div>
        <button className="btn-pill primary" disabled={mut.isPending} onClick={() => mut.mutate()}>저장</button>
        {msg && <p className="muted">{msg}</p>}
      </div>
      {idsQ.isLoading && <div className="skeleton-row" />}
      {idsQ.isError && <EmptyState message="ID 목록을 불러오지 못했습니다." />}
      {idsQ.data && list.length === 0 && <EmptyState message="등록된 ID가 없습니다." />}
      {list.length > 0 && (
        <div className="table-wrap">
          <table className="table">
            <thead><tr><th>ID</th><th>이름</th><th>역할</th></tr></thead>
            <tbody>
              {list.map((r, i) => (
                <tr key={i}>
                  <td>{String(r.id ?? r['ID'] ?? '')}</td>
                  <td>{String(r.name ?? r['이름'] ?? '')}</td>
                  <td>{String(r.role ?? r['역할'] ?? '')}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

/* ---------- TabPerm (ex pages/TabPerm.tsx) ---------- */

export function TabPermPage() {
  const [userId, setUserId] = useState('');
  const [tabs, setTabs] = useState<Set<string>>(new Set());
  const [msg, setMsg] = useState('');
  const idsQ = useQuery({ queryKey: ['admin-ids'], queryFn: fetchIds });
  const list = (idsQ.data ?? []) as Record<string, string>[];

  const toggle = (t: string) => {
    const next = new Set(tabs);
    if (next.has(t)) next.delete(t);
    else next.add(t);
    setTabs(next);
  };

  const save = async () => {
    if (!userId) {
      setMsg('회원을 선택하세요.');
      return;
    }
    try {
      await upsertId({ id: userId, allowedTabs: [...tabs] });
      setMsg('탭 권한이 저장되었습니다.');
    } catch (e) {
      setMsg(e instanceof Error ? e.message : '저장 실패');
    }
  };

  return (
    <div className="page">
      <h2>📑 회원별 탭 권한 관리</h2>
      <KpiCards
        items={[
          { label: '회원 수', value: `${list.length}` },
          { label: '선택 회원', value: userId || '-' },
          { label: '허용 탭', value: `${tabs.size}` },
        ]}
      />
      <div className="card">
        <select className="select" value={userId} onChange={(e) => setUserId(e.target.value)}>
          <option value="">회원 선택</option>
          {list.map((r, i) => {
            const id = String(r.id ?? r['ID'] ?? i);
            return <option key={id} value={id}>{id} ({String(r.name ?? r['이름'] ?? '')})</option>;
          })}
        </select>
        <div className="chip-row">
          {TAB_ROUTES.map((r) => (
            <label key={r.tab} className={`chip${tabs.has(r.tab) ? ' on' : ''}`}>
              <input type="checkbox" checked={tabs.has(r.tab)} onChange={() => toggle(r.tab)} />
              {r.short}
            </label>
          ))}
        </div>
        <button className="btn-pill primary" onClick={() => void save()}>권한 저장</button>
        {msg && <p className="muted">{msg}</p>}
      </div>
      {idsQ.isError && <EmptyState message="회원 목록을 불러오지 못했습니다." />}
    </div>
  );
}
