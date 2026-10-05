import { useState } from 'react';
import { analyzeSalaryDocs, calcSalary } from '../api';
import { EmptyState, KpiCards } from '../components/ui';

interface CareerRow {
  type: string;
  detail: string;
  start: string;
  end: string;
  rate: number;
}

const CAREER_TYPES = [
  '국·공립학교 교원 (기간제 포함, 자격 일치)',
  '사립학교 교원 (관할청 보고, 자격 일치)',
  '기간제교원 자격-학교급 불일치 (예:중등→초등)',
  '유·초·중등 강사 (전일제·종일제, 1일 8시간 ↑)',
  '유·초·중등 시간제 강사 (주 12시간 ↓ 또는 시수 불명)',
  '국가·지방공무원 (현역 군복무 포함)',
  '등록 학원 강사 / 신고 교습소 교습자',
  '회사 (상법상 합명·합자·주식·유한회사) 근무',
];

const DEGREE_TYPES = [
  '동등 수준 추가 학사 학위 (2번째 대학교)',
  '석사학위 취득 수학기간',
  '박사학위 취득 수학기간',
];

export default function Salary() {
  const [base, setBase] = useState(8);
  const [qual, setQual] = useState('정교사(2급)');
  const [academic, setAcademic] = useState(0);
  const [degrees, setDegrees] = useState<{ type: string; start: string; end: string }[]>([]);
  const [careers, setCareers] = useState<CareerRow[]>([{ type: CAREER_TYPES[0] as string, detail: '', start: '', end: '', rate: 100 }]);
  const [aiText, setAiText] = useState('');
  const [result, setResult] = useState<{ hobong: number; detail: string } | null>(null);
  const [msg, setMsg] = useState('');
  const [loading, setLoading] = useState(false);

  const addDegree = () => setDegrees([...degrees, { type: DEGREE_TYPES[0] as string, start: '', end: '' }]);
  const addCareer = () =>
    setCareers([...careers, { type: CAREER_TYPES[0] as string, detail: '', start: '', end: '', rate: 100 }]);

  const calculate = async () => {
    setLoading(true);
    setMsg('');
    try {
      const r = await calcSalary({ base, qual, academic, degrees, careers });
      setResult(r);
    } catch (e) {
      setMsg(e instanceof Error ? e.message : '계산 실패');
    } finally {
      setLoading(false);
    }
  };

  const aiUpload = async () => {
    setLoading(true);
    setMsg('');
    try {
      const r = await analyzeSalaryDocs({ texts: [aiText] });
      const rec = r as Record<string, unknown>;
      if (typeof rec.baseSalary === 'number') setBase(rec.baseSalary);
      if (typeof rec.academicValue === 'string') setAcademic(Number(rec.academicValue) || 0);
      setMsg('AI 분석 결과를 반영했습니다.');
    } catch (e) {
      setMsg(e instanceof Error ? e.message : 'AI 분석 실패');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="page">
      <h2>교무호봉획정</h2>
      <KpiCards
        items={[
          { label: '기본', value: `${base}호봉` },
          { label: '자격', value: qual },
          { label: '호봉 결과', value: result ? `${result.hobong}호봉` : '-' },
        ]}
      />
      <div className="grid2">
        <div className="card">
          <h3>기본 + 인적 + 자격증 + 학력</h3>
          <div className="form-grid">
            <label>기본 호봉<input className="input" type="number" value={base} onChange={(e) => setBase(Number(e.target.value))} /></label>
            <label>자격증<input className="input" value={qual} onChange={(e) => setQual(e.target.value)} /></label>
            <label>학력 가감<input className="input" type="number" value={academic} onChange={(e) => setAcademic(Number(e.target.value))} /></label>
          </div>
          <h4>학위</h4>
          {degrees.map((d, i) => (
            <div key={i} className="row-gap">
              <select className="select" value={d.type} onChange={(e) => {
                const next = [...degrees];
                next[i] = { ...d, type: e.target.value };
                setDegrees(next);
              }}>
                {DEGREE_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
              </select>
              <input className="input" type="date" value={d.start} onChange={(e) => {
                const next = [...degrees];
                next[i] = { ...d, start: e.target.value };
                setDegrees(next);
              }} />
              <input className="input" type="date" value={d.end} onChange={(e) => {
                const next = [...degrees];
                next[i] = { ...d, end: e.target.value };
                setDegrees(next);
              }} />
            </div>
          ))}
          <button className="btn-pill" onClick={addDegree}>학위 추가</button>
        </div>
        <div className="card">
          <h3>경력 테이블</h3>
          {careers.map((c, i) => (
            <div key={i} className="row-gap wrap">
              <select className="select" value={c.type} onChange={(e) => {
                const next = [...careers];
                next[i] = { ...c, type: e.target.value };
                setCareers(next);
              }}>
                {CAREER_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
              </select>
              <input className="input" placeholder="상세" value={c.detail} onChange={(e) => {
                const next = [...careers];
                next[i] = { ...c, detail: e.target.value };
                setCareers(next);
              }} />
              <input className="input" type="date" value={c.start} onChange={(e) => {
                const next = [...careers];
                next[i] = { ...c, start: e.target.value };
                setCareers(next);
              }} />
              <input className="input" type="date" value={c.end} onChange={(e) => {
                const next = [...careers];
                next[i] = { ...c, end: e.target.value };
                setCareers(next);
              }} />
            </div>
          ))}
          <div className="row-gap">
            <button className="btn-pill" onClick={addCareer}>경력 추가</button>
            <button className="btn-pill primary" disabled={loading} onClick={() => void calculate()}>계산</button>
          </div>
        </div>
      </div>
      <div className="card">
        <h3>AI 서류 업로드 (텍스트 붙여넣기)</h3>
        <textarea className="input area" rows={4} value={aiText} onChange={(e) => setAiText(e.target.value)} placeholder="경력증명서 텍스트..." />
        <button className="btn-pill" disabled={loading} onClick={() => void aiUpload()}>AI 분석 반영</button>
      </div>
      {msg && <p className="muted">{msg}</p>}
      {result ? (
        <div className="card report">
          <h3>호봉 리포트: {result.hobong}호봉</h3>
          <pre>{result.detail}</pre>
          <button className="btn-pill" onClick={() => window.print()}>인쇄</button>
        </div>
      ) : (
        !loading && <EmptyState message="계산 결과가 없습니다." />
      )}
    </div>
  );
}
