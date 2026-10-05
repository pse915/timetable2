import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ApiError, apiGuest, apiLogin, apiRequestId, fetchHealth, getApiBase } from '../api';
import { useAppStore } from '../store/useAppStore';

const MAX_ATTEMPTS = 5;

export default function Login() {
  const navigate = useNavigate();
  const setUser = useAppStore((s) => s.setUser);
  const [id, setId] = useState('');
  const [guestName, setGuestName] = useState('');
  const [failCount, setFailCount] = useState(0);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [req, setReq] = useState({ name: '', email: '', desired_id: '', memo: '' });
  const [reqMsg, setReqMsg] = useState('');
  const [netMsg, setNetMsg] = useState('');

  const locked = failCount >= MAX_ATTEMPTS;

  const testConn = async () => {
    setNetMsg('연결 확인 중…');
    try {
      const h = await fetchHealth();
      setNetMsg(`연결 OK (서버 v${(h as unknown as { version?: string }).version ?? '?'})`);
    } catch (e) {
      setNetMsg(e instanceof ApiError ? `연결 실패: ${e.message}` : '연결 실패');
    }
  };

  const doLogin = async () => {
    if (locked || !id.trim()) return;
    setBusy(true);
    setError('');
    try {
      const r = await apiLogin(id.trim());
      setUser({ id: r.id ?? id.trim(), name: r.name ?? id.trim(), role: r.role ?? '일반교사', allowedTabs: r.allowedTabs ?? [] });
      navigate('/app/timetable');
    } catch (e) {
      const n = failCount + 1;
      setFailCount(n);
      setError(e instanceof ApiError ? e.message : '로그인 실패');
      if (n >= MAX_ATTEMPTS) setError(`5회 실패로 잠금되었습니다. 관리자에게 문의하세요.`);
    } finally {
      setBusy(false);
    }
  };

  const doGuest = async () => {
    if (!guestName.trim()) return;
    setBusy(true);
    setError('');
    try {
      const r = await apiGuest(guestName.trim());
      setUser({ id: guestName.trim(), name: r.name ?? guestName.trim(), role: r.role ?? '게스트', allowedTabs: r.allowedTabs ?? [] });
      navigate('/app/timetable');
    } catch (e) {
      setError(e instanceof ApiError ? e.message : '게스트 로그인 실패');
    } finally {
      setBusy(false);
    }
  };

  const doRequest = async () => {
    setReqMsg('');
    try {
      await apiRequestId(req);
      setReqMsg('추가 요청이 접수되었습니다.');
      setReq({ name: '', email: '', desired_id: '', memo: '' });
    } catch (e) {
      setReqMsg(e instanceof ApiError ? e.message : '요청 실패');
    }
  };

  return (
    <div className="login-wrap">
      <div className="card login-card">
        <h1>시간표·결보강 관리</h1>
        <p className="muted">서라벌여자중학교 2026</p>
        <label>
          아이디
          <input className="input" value={id} onChange={(e) => setId(e.target.value)} placeholder="아이디 입력" />
        </label>
        <button className="btn-pill primary block" disabled={locked || busy} onClick={() => void doLogin()}>
          로그인
        </button>
        {locked && <p className="error">5회 실패로 잠금되었습니다.</p>}
        {failCount > 0 && !locked && <p className="muted">실패 {failCount}/{MAX_ATTEMPTS}</p>}
        {error && <p className="error">{error}</p>}
        <p className="muted">서버: {getApiBase()}</p>
        <button className="btn-pill block" onClick={() => void testConn()}>서버 연결 테스트</button>
        {netMsg && <p className="muted">{netMsg}</p>}
        <hr />
        <label>
          게스트 이름
          <input className="input" value={guestName} onChange={(e) => setGuestName(e.target.value)} placeholder="이름" />
        </label>
        <button className="btn-pill block" disabled={busy} onClick={() => void doGuest()}>
          게스트 로그인
        </button>
        <hr />
        <h3>아이디 추가 요청</h3>
        <input className="input" placeholder="이름" value={req.name} onChange={(e) => setReq({ ...req, name: e.target.value })} />
        <input className="input" placeholder="이메일" value={req.email} onChange={(e) => setReq({ ...req, email: e.target.value })} />
        <input className="input" placeholder="희망 ID" value={req.desired_id} onChange={(e) => setReq({ ...req, desired_id: e.target.value })} />
        <input className="input" placeholder="메모" value={req.memo} onChange={(e) => setReq({ ...req, memo: e.target.value })} />
        <button className="btn-pill block" onClick={() => void doRequest()}>추가 요청</button>
        {reqMsg && <p className="muted">{reqMsg}</p>}
      </div>
    </div>
  );
}
