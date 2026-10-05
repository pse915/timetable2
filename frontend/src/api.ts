const RUNTIME_API_BASE: string =
  // Streamlit 래퍼가 주입하는 런타임 설정이 최우선 (빌드 후에도 BACKEND_URL 변경 가능)
  ((((globalThis as unknown as { __API_BASE__?: string }).__API_BASE__ ?? '').trim())
    || ((import.meta.env.VITE_API_BASE_URL as string | undefined) ?? ''));

const API_BASE: string = RUNTIME_API_BASE;

function buildUrl(path: string, query?: Record<string, string | number | boolean | undefined>): string {
  const base = API_BASE.replace(/\/$/, '');
  const url = path.startsWith('/api') ? `${base}${path}` : `${base}/api${path}`;
  if (!query) return url;
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(query)) {
    if (v !== undefined && v !== '') params.append(k, String(v));
  }
  const qs = params.toString();
  return qs ? `${url}?${qs}` : url;
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function parseBody(res: Response): Promise<unknown> {
  const ct = res.headers.get('content-type') ?? '';
  if (ct.includes('application/json')) {
    return (await res.json()) as unknown;
  }
  return (await res.text()) as unknown;
}

async function request<T>(method: string, path: string, body?: unknown, query?: Record<string, string | number | boolean | undefined>): Promise<T> {
  const res = await fetch(buildUrl(path, query), {
    method,
    headers: body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    let msg = `HTTP ${res.status}`;
    try {
      const data = await parseBody(res);
      if (typeof data === 'object' && data !== null) {
        const d = data as Record<string, unknown>;
        if (typeof d.detail === 'string') msg = d.detail;
        else if (typeof d.error === 'string') msg = d.error;
        else if (typeof d.message === 'string') msg = d.message;
      } else if (typeof data === 'string' && data) {
        msg = data.slice(0, 500);
      }
    } catch {
      /* ignore */
    }
    throw new ApiError(res.status, msg);
  }
  const ct = res.headers.get('content-type') ?? '';
  if (ct.includes('application/json')) {
    return (await res.json()) as T;
  }
  return (await res.text()) as unknown as T;
}

export async function get<T>(path: string, query?: Record<string, string | number | boolean | undefined>): Promise<T> {
  return request<T>('GET', path, undefined, query);
}

export async function post<T>(path: string, body?: unknown, query?: Record<string, string | number | boolean | undefined>): Promise<T> {
  return request<T>('POST', path, body, query);
}

export async function put<T>(path: string, body?: unknown): Promise<T> {
  return request<T>('PUT', path, body);
}

export async function del<T>(path: string, query?: Record<string, string | number | boolean | undefined>): Promise<T> {
  return request<T>('DELETE', path, undefined, query);
}

/** xlsx 등 바이너리 다운로드용 */
export async function downloadBlob(path: string, query?: Record<string, string | number | boolean | undefined>): Promise<Blob> {
  const res = await fetch(buildUrl(path, query));
  if (!res.ok) throw new ApiError(res.status, `다운로드 실패: HTTP ${res.status}`);
  return await res.blob();
}

export function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/* ---------- 공통 타입 (구/신 호환) ---------- */
export interface LoginResult {
  ok: boolean;
  id?: string;
  name?: string;
  role?: string;
  allowedTabs?: string[];
}

export interface MetaResult {
  tabs: string[];
  roles: string[];
  days: string[];
  periods_per_day: Record<string, number>;
  max_period: number;
  school: { name: string; year: string };
  version: number;
  // 구버전 별칭(읽기 전용)
  schoolName?: string;
  schoolYear?: string;
  allTabs?: string[];
}

export interface EffectiveRow {
  교사명: string;
  요일: string;
  교시: number;
  과목: string;
  학급: string;
  과목군?: string;
  원본교사?: string;
  원본일자?: string;
  원본교시?: number;
  변경유형?: string;
  변경출처?: string;
  변경ID?: string;
  변경상세?: string;
}

/** 구 RecommendTable 호환 타입 */
export interface RecommendItem {
  teacher: string;
  score: number;
  reason: string;
  free?: boolean;
  sameSubject?: boolean;
  weeklyHours?: number;
  [k: string]: unknown;
}

export interface BudgetInfo {
  balance: number;
  remaining?: number;
  used?: number;
  records?: Record<string, unknown>[];
}

type AnyRec = Record<string, unknown>;

/** 백엔드 보강추천 레코드 → RecommendItem 변환 */
function toRecommendItems(records: AnyRec[]): RecommendItem[] {
  return (records ?? []).map((r) => ({
    teacher: String(r['보강교사'] ?? r['teacher'] ?? r['교사B'] ?? ''),
    score: Number(r['추천점수'] ?? r['점수'] ?? r['score'] ?? 0),
    reason: String(r['우선순위'] ?? r['reason'] ?? r['현재 수업'] ?? ''),
    weeklyHours: Number(r['주당시수'] ?? 0),
    ...r,
  }));
}

/* ---------- 1. 헬스/메타 ---------- */
export const fetchHealth = () => get<{ ok: boolean; version: string }>('/api/health');
export const fetchMeta = () => get<MetaResult>('/api/meta');

/* ---------- 2. 인증 ---------- */
export const apiLogin = (id: string) => post<LoginResult>('/api/auth/login', { id });
export const apiGuest = (name: string) => post<LoginResult>('/api/auth/guest', { name });
export const apiRequestId = (payload: { name: string; email: string; desired_id: string; memo: string }) =>
  post<{ ok: boolean }>('/api/auth/request-id', payload);

/* ---------- 3. 시간표 조회 ---------- */
export const fetchTimetable = (_params?: AnyRec) =>
  get<{ records: AnyRec[]; version: number }>('/api/timetable');
export const fetchTeachers = () =>
  get<{ records: AnyRec[]; names: string[] }>('/api/teachers');
export const fetchEffectiveDay = (date: string, useTest = false) =>
  get<{ date: string; records: EffectiveRow[] }>('/api/effective-day', { date, useTest });
export const fetchEffectiveWeek = (startOrRef: string, useTest = false) =>
  get<{ refDate: string; days: Record<string, EffectiveRow[]> }>('/api/effective-week', { refDate: startOrRef, useTest });
export const fetchTeacherWeek = (teacher: string, startOrRef: string, useTest = false) =>
  get<{ teacher: string; records: EffectiveRow[]; week: string[]; rows?: EffectiveRow[] }>('/api/teacher-week', { teacher, refDate: startOrRef, useTest });
export const fetchChangedTeachers = (startOrRef: string) =>
  get<{ teachers: string[] }>('/api/changed-teachers', { refDate: startOrRef });

/* ---------- 4. 결강/보강 ---------- */
function unwrapRecords(data: AnyRec[] | { records: AnyRec[] } | null | undefined): AnyRec[] {
  if (Array.isArray(data)) return data as AnyRec[];
  if (data && Array.isArray((data as { records: AnyRec[] }).records)) return (data as { records: AnyRec[] }).records;
  return [] as AnyRec[];
}
export const fetchAbsences = (_params?: AnyRec): Promise<AnyRec[]> =>
  get<AnyRec[] | { records: AnyRec[] }>('/api/absences').then(unwrapRecords as (d: AnyRec[] | { records: AnyRec[] }) => AnyRec[]) as Promise<AnyRec[]>;

export const createAbsence = (payload: AnyRec) =>
  post<{ ok: boolean; cid?: string }>('/api/absences', {
    cid: payload['cid'] ?? payload['결강ID'] ?? '',
    date: String(payload['date'] ?? payload['일자'] ?? ''),
    day: String(payload['day'] ?? payload['요일'] ?? ''),
    period: Number(payload['period'] ?? payload['교시'] ?? 0),
    class_name: String(payload['class_name'] ?? payload['학급'] ?? ''),
    subject: String(payload['subject'] ?? payload['과목'] ?? ''),
    teacher: String(payload['teacher'] ?? payload['교사명'] ?? payload['결강교사'] ?? ''),
    reason: String(payload['reason'] ?? payload['사유'] ?? ''),
    detail: String(payload['detail'] ?? payload['상세사유'] ?? ''),
    user: String(payload['user'] ?? payload['입력자'] ?? ''),
  });

export const recommendSubs = (payload: AnyRec) =>
  post<{ records: AnyRec[]; items?: AnyRec[] }>('/api/subs/recommend', {
    day: String(payload['day'] ?? payload['요일'] ?? '월'),
    period: Number(payload['period'] ?? payload['교시'] ?? 1),
    subject: String(payload['subject'] ?? payload['과목'] ?? ''),
    class_name: String(payload['class_name'] ?? payload['학급'] ?? ''),
    absent_teacher: String(payload['absent_teacher'] ?? payload['teacher'] ?? payload['결강교사'] ?? ''),
    date: String(payload['date'] ?? payload['일자'] ?? ''),
    top_n: Number(payload['top_n'] ?? payload['topN'] ?? 20),
    include_part_time: Boolean(payload['include_part_time'] ?? false),
  }).then((r) => ({ ...r, items: toRecommendItems(r.records ?? []) }) as { records: AnyRec[]; items: RecommendItem[] });

export const validateSub = (payload: AnyRec) =>
  post<{ ok: boolean; message: string; reason?: string }>('/api/subs/validate', {
    cid: String(payload['cid'] ?? ''),
    date: String(payload['date'] ?? ''),
    period: Number(payload['period'] ?? 0),
    class_name: String(payload['class_name'] ?? ''),
    subject: String(payload['subject'] ?? ''),
    absent_teacher: String(payload['absent_teacher'] ?? ''),
    sub_teacher: String(payload['sub_teacher'] ?? ''),
  });

export const assignSub = (payload: AnyRec) =>
  post<{ ok: boolean }>('/api/subs', {
    cid: String(payload['cid'] ?? ''),
    date: String(payload['date'] ?? ''),
    day: String(payload['day'] ?? ''),
    period: Number(payload['period'] ?? 0),
    class_name: String(payload['class_name'] ?? ''),
    subject: String(payload['subject'] ?? ''),
    absent_teacher: String(payload['absent_teacher'] ?? ''),
    sub_teacher: String(payload['sub_teacher'] ?? ''),
    method: String(payload['method'] ?? payload['배정방식'] ?? ''),
    priority: String(payload['priority'] ?? payload['우선순위'] ?? ''),
    memo: String(payload['memo'] ?? payload['비고'] ?? ''),
    user: String(payload['user'] ?? ''),
  });

export const assignSubBatch = (payload: { assignments: AnyRec[]; user?: string }) =>
  post<{ accepted: number; errors: string[] }>('/api/subs/batch', payload);

export const cancelSub = (cid: string, period = 0) =>
  del<{ ok: boolean }>('/api/subs', { cid, period });

/* ---------- 5. 맞교환 ---------- */
function toSwapAB(p: AnyRec): { a: AnyRec; b: AnyRec; date_a: string; date_b: string } {
  if (p['a'] && p['b']) {
    return { a: p['a'] as AnyRec, b: p['b'] as AnyRec, date_a: String(p['date_a'] ?? p['dateA'] ?? ''), date_b: String(p['date_b'] ?? p['dateB'] ?? '') };
  }
  // 구버전 평탄 payload (teacherA/dayA/periodA/dateA ...)
  const a = {
    교사명: String(p['teacherA'] ?? p['teacher_a'] ?? ''),
    요일: String(p['dayA'] ?? p['day_a'] ?? ''),
    교시: Number(p['periodA'] ?? p['period_a'] ?? 0),
    학급: String(p['classA'] ?? p['class_a'] ?? ''),
    과목: String(p['subjectA'] ?? p['subject_a'] ?? ''),
  };
  const b = {
    교사명: String(p['teacherB'] ?? p['teacher_b'] ?? ''),
    요일: String(p['dayB'] ?? p['day_b'] ?? ''),
    교시: Number(p['periodB'] ?? p['period_b'] ?? 0),
    학급: String(p['classB'] ?? p['class_b'] ?? ''),
    과목: String(p['subjectB'] ?? p['subject_b'] ?? ''),
  };
  return { a, b, date_a: String(p['dateA'] ?? p['date_a'] ?? ''), date_b: String(p['dateB'] ?? p['date_b'] ?? '') };
}

export const validateSwap = (payload: AnyRec) => {
  const { a, b, date_a, date_b } = toSwapAB(payload);
  return post<{ ok: boolean; message: string; reason?: string }>('/api/swaps/validate', {
    a, b, date_a, date_b, is_test: Boolean(payload['is_test'] ?? false),
  });
};
export const applySwap = (payload: AnyRec) => {
  const { a, b, date_a, date_b } = toSwapAB(payload);
  return post<{ ok: boolean }>('/api/swaps', {
    a, b, date_a, date_b,
    is_test: Boolean(payload['is_test'] ?? false),
    is_part_time_purpose: Boolean(payload['is_part_time_purpose'] ?? false),
    user: String(payload['user'] ?? ''),
  });
};
export const applyLinkedSwap = (payload: AnyRec) => {
  const { a, date_a, date_b } = toSwapAB(payload);
  return post<{ ok: boolean }>('/api/swaps/linked', {
    a,
    teacher_b: String(payload['teacher_b'] ?? payload['teacherB'] ?? ''),
    date_a, date_b,
    day_b: String(payload['day_b'] ?? payload['dayB'] ?? ''),
    period_b: Number(payload['period_b'] ?? payload['periodB'] ?? 0),
    is_test: Boolean(payload['is_test'] ?? false),
    is_part_time_purpose: Boolean(payload['is_part_time_purpose'] ?? false),
    subject_b: payload['subject_b'] ?? payload['subjectB'] ?? null,
    user: String(payload['user'] ?? ''),
  });
};
export const applyCycleSwap = (payload: AnyRec) =>
  post<{ ok: boolean }>('/api/swaps/cycle', {
    moves: (payload['moves'] ?? []) as AnyRec[],
    is_test: Boolean(payload['is_test'] ?? false),
    user: String(payload['user'] ?? ''),
  });

export const recommendSwapTarget = (payload: AnyRec) =>
  post<{ records: AnyRec[]; cycles: unknown[]; message: string }>('/api/swaps/target-recommend', {
    teacher_a: String(payload['teacher_a'] ?? payload['teacherA'] ?? ''),
    date_a: String(payload['date_a'] ?? payload['dateA'] ?? ''),
    period_a: Number(payload['period_a'] ?? payload['periodA'] ?? 0),
    class_a: String(payload['class_a'] ?? payload['classA'] ?? ''),
    subject_a: String(payload['subject_a'] ?? payload['subjectA'] ?? ''),
    date_b: String(payload['date_b'] ?? payload['dateB'] ?? ''),
    period_b: Number(payload['period_b'] ?? payload['periodB'] ?? 0),
    budget_factor: Number(payload['budget_factor'] ?? payload['budgetFactor'] ?? 1),
  }).then((r) => ({ ...r, items: toRecommendItems(r.records ?? []) }) as { records: AnyRec[]; cycles: unknown[]; message: string; items: RecommendItem[] });

export const searchSwapCycles = (payload: AnyRec) =>
  post<{ cycles: unknown[]; message: string }>('/api/swaps/cycles-search', {
    teacher_a: String(payload['teacher_a'] ?? payload['teacherA'] ?? ''),
    date_a: String(payload['date_a'] ?? payload['dateA'] ?? ''),
    period_a: Number(payload['period_a'] ?? payload['periodA'] ?? 0),
    class_a: String(payload['class_a'] ?? payload['classA'] ?? ''),
    subject_a: String(payload['subject_a'] ?? payload['subjectA'] ?? ''),
    date_b: String(payload['date_b'] ?? payload['dateB'] ?? ''),
    period_b: Number(payload['period_b'] ?? payload['periodB'] ?? 0),
    max_cycle: Number(payload['max_cycle'] ?? 3),
    use_test: Boolean(payload['use_test'] ?? false),
  });

export const fetchWeeklySwaps = (teacherOrStart: string, refDate = '', futureDays = 0) =>
  get<{ records: AnyRec[] }>('/api/swaps/weekly-1to1', teacherOrStart && refDate
    ? { teacher: teacherOrStart, refDate, futureDays }
    : { teacher: '', refDate: teacherOrStart, futureDays });

/* ---------- 6. 시간강사 ---------- */
export const fetchPartTime = () =>
  get<{ records: AnyRec[]; valid: boolean; message: string }>('/api/part-time');
export const upsertPartTime = (payload: AnyRec, user = '') =>
  post<{ ok: boolean }>('/api/part-time', { row: payload['row'] ?? payload, user: String(payload['user'] ?? user) });

/* ---------- 7. 복무 ---------- */
export const fetchDuties = (_params?: AnyRec): Promise<AnyRec[]> =>
  get<AnyRec[] | { records: AnyRec[] }>('/api/duties').then(unwrapRecords as (d: AnyRec[] | { records: AnyRec[] }) => AnyRec[]) as Promise<AnyRec[]>;
export const createDuty = (payload: AnyRec) =>
  post<{ ok: boolean }>('/api/duties', {
    teacher: String(payload['teacher'] ?? payload['교사명'] ?? ''),
    date: String(payload['date'] ?? payload['일자'] ?? ''),
    period: Number(payload['period'] ?? payload['교시'] ?? 0),
    reason: String(payload['reason'] ?? payload['사유'] ?? ''),
    detail: String(payload['detail'] ?? payload['상세사유'] ?? ''),
    user: String(payload['user'] ?? ''),
  });

/* ---------- 8. 예산 ---------- */
export const fetchBudget = () =>
  get<{ balance: number; remaining?: number; records: AnyRec[] }>('/api/budget');
export const updateBudget = (budgetOrChange: number | AnyRec, _reason = '보강') => {
  const change = typeof budgetOrChange === 'number' ? budgetOrChange : Number((budgetOrChange as AnyRec)['change'] ?? 0);
  const reason = typeof budgetOrChange === 'number' ? _reason : String((budgetOrChange as AnyRec)['reason'] ?? '보강');
  return post<{ ok: boolean; balance: number; remaining?: number }>('/api/budget', { change, reason });
};

/* ---------- 9. 통계/NEIS ---------- */
export const fetchStats = (_params?: AnyRec) =>
  get<{ cumulative: Record<string, number>; weekly_load: Record<string, number>; budget: number; subCounts?: Record<string, number>; weeklyHours?: Record<string, number> }>('/api/stats');
export const fetchNeisWeek = (start: string) =>
  get<{ records: AnyRec[] }>('/api/neis/week', { refDate: start });
export const refreshNeis = (payload: AnyRec) =>
  post<{ ok: boolean }>('/api/neis/refresh', { refDate: String(payload['start'] ?? payload['refDate'] ?? ''), apiKey: '' });

/* ---------- 10. 엑스포트/리포트 ---------- */
export const downloadTeacherWeek = (refDate: string, useTest = false) =>
  downloadBlob('/api/export/teacher-week.xlsx', { refDate, useTest });
export const downloadClassWeek = (refDate: string, useTest = false) =>
  downloadBlob('/api/export/class-week.xlsx', { refDate, useTest });
export const dailyReportUrl = (date: string, base = '') =>
  `${base}/api/report/daily.html?date=${encodeURIComponent(date)}`;
export const personalReportUrl = (teacher: string, date: string, base = '') =>
  `${base}/api/report/personal.html?teacher=${encodeURIComponent(teacher)}&date=${encodeURIComponent(date)}`;
export const testReportUrl = (base = '') => `${base}/api/report/test.html`;

/* ---------- 11. 호봉 ---------- */
export const calcSalary = (payload: AnyRec) =>
  post<{ hobong: number; detail: string } & AnyRec>('/api/salary/calculate', payload);
export const analyzeSalaryDocs = (payload: { texts: string[] }) =>
  post<AnyRec>('/api/salary/analyze', payload);

export const analyzeSalaryFile = async (file: File, base = '') => {
  const form = new FormData();
  form.append('file', file);
  const res = await fetch(`${base}/api/salary/analyze`, { method: 'POST', body: form });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return (await res.json()) as { ok: boolean; data?: AnyRec; error?: string };
};

/* ---------- 12. 관리자/히스토리 ---------- */
export const fetchIds = (): Promise<AnyRec[]> =>
  get<AnyRec[] | { records: AnyRec[] }>('/api/admin/ids').then(unwrapRecords as (d: AnyRec[] | { records: AnyRec[] }) => AnyRec[]) as Promise<AnyRec[]>;
export const upsertId = (payload: AnyRec) =>
  post<{ ok: boolean }>('/api/admin/ids', { records: payload['records'] ?? [payload] });
export const saveIds = (records: AnyRec[]) =>
  post<{ ok: boolean }>('/api/admin/ids', { records });

export const undoHistory = () => post<{ ok: boolean }>('/api/history/undo', {});
export const redoHistory = () => post<{ ok: boolean }>('/api/history/redo', {});
