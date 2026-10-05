import React from 'react';
import ReactDOM from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter, MemoryRouter } from 'react-router-dom';
import App from './App';
import './styles/globals.css';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, refetchOnWindowFocus: false, staleTime: 30_000 },
  },
});

// Streamlit components.html(srcdoc iframe, opaque origin)에서는
// @remix-run/router의 createURL(new URL(href, origin ?? href))이
// origin==="null", href==="about:srcdoc"에서 Invalid URL을 던진다.
// BrowserRouter/HashRouter 모두 이 함수를 쓰므로 임베드 모드에서는
// window.location을 전혀 건드리지 않는 MemoryRouter를 사용한다.
// 라우트 path 자체는 App.tsx와 동일하게 유지된다.
function isEmbedded(): boolean {
  try {
    return (globalThis as unknown as { __STREAMLIT_MODE__?: boolean }).__STREAMLIT_MODE__ === true;
  } catch {
    return false;
  }
}

interface BoundaryState {
  error: Error | null;
}

class ErrorBoundary extends React.Component<{ children: React.ReactNode }, BoundaryState> {
  state: BoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): BoundaryState {
    return { error };
  }

  componentDidCatch(error: Error): void {
    // eslint-disable-next-line no-console
    console.error('[timetable] render crash:', error);
  }

  private diag(): string {
    let href = '(unknown)';
    let hasConfig = false;
    try {
      href = String(window.location.href);
    } catch {
      /* ignore */
    }
    try {
      hasConfig = (globalThis as unknown as { __APP_CONFIG__?: unknown }).__APP_CONFIG__ !== undefined;
    } catch {
      /* ignore */
    }
    return `href=${href} | __APP_CONFIG__=${hasConfig ? 'ok' : 'missing'}`;
  }

  render(): React.ReactNode {
    if (this.state.error) {
      const msg = String(this.state.error?.message ?? this.state.error);
      return (
        <div style={{ padding: 24, fontFamily: 'sans-serif' }}>
          <h2>화면을 표시하지 못했습니다</h2>
          <p style={{ color: '#666' }}>아래 내용을 복사해 관리자에게 전달하세요.</p>
          <pre style={{ whiteSpace: 'pre-wrap', background: '#f5f5f7', padding: 12, borderRadius: 8 }}>{msg}</pre>
          <pre style={{ whiteSpace: 'pre-wrap', background: '#f5f5f7', padding: 12, borderRadius: 8 }}>{this.diag()}</pre>
          <button type="button" onClick={() => window.location.reload()}>다시 시도</button>
        </div>
      );
    }
    return this.props.children;
  }
}

const Router = isEmbedded() ? MemoryRouter : BrowserRouter;

try {
  document.getElementById('boot-loading')?.remove();
} catch {
  /* ignore */
}

ReactDOM.createRoot(document.getElementById('root') as HTMLElement).render(
  <React.StrictMode>
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <Router>
          <App />
        </Router>
      </QueryClientProvider>
    </ErrorBoundary>
  </React.StrictMode>,
);
