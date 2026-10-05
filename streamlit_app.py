"""Streamlit 배포용 엔트리포인트 — UI는 React가 전담, Streamlit은 셸만 담당.

실행: streamlit run streamlit_app.py
- React 프로덕션 빌드(frontend/dist)를 인라인하여 전체 화면으로 렌더링
- FastAPI 백엔드를 백그라운드 스레드로 함께 기동(로컬/VPS에서 localhost fetch 가능)
- Streamlit Community Cloud처럼 8501 단일 포트만 열리는 환경에서는
  secrets BACKEND_URL에 별도 백엔드 주소를 지정하면 React가 그쪽으로 fetch
- 구글 시트 ID는 backend/app/config.py에 내장된 값을 그대로 사용
"""
from __future__ import annotations

import html as html_lib
import json
import os
import socket
import threading
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

ROOT = Path(__file__).resolve().parent
DIST_DIR = ROOT / "frontend" / "dist"
DIST_INDEX = DIST_DIR / "index.html"

st.set_page_config(
    page_title="시간표·결보강 관리 — 서라벌여자중학교 2026",
    page_icon="📘",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# --- Streamlit 크롬 숨김: UI는 React가 전담 ---
st.markdown(
    """<style>
    [data-testid="stHeader"], [data-testid="stToolbar"], [data-testid="stDecoration"],
    [data-testid="stStatusWidget"], footer, #MainMenu { display: none !important; }
    section[data-testid="stSidebar"] { display: none !important; }
    .block-container { padding: 0 !important; margin: 0 !important; max-width: none !important; }
    [data-testid="stAppViewContainer"] { padding: 0 !important; }
    iframe { border: 0 !important; }
    </style>""",
    unsafe_allow_html=True,
)


def _secret(name: str, default: str = "") -> str:
    try:
        v = st.secrets.get(name, default)
        if v is not None and str(v).strip():
            return str(v).strip()
    except Exception:
        pass
    return os.getenv(name, default).strip()


def _port_free(port: int) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.5)
    try:
        s.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        try:
            s.close()
        except Exception:
            pass


@st.cache_resource(show_spinner=False)
def _ensure_backend_thread(port: int) -> str:
    """FastAPI를 데몬 스레드로 기동. 성공 시 base URL 반환, 실패 시 ''."""
    if os.getenv("DISABLE_BACKEND_THREAD", "").strip() == "1":
        return ""
    try:
        import uvicorn
        from backend.app.server import app as fastapi_app
    except Exception as exc:
        st.session_state["_backend_thread_error"] = f"백엔드 임포트 실패: {exc}"
        return ""
    if not _port_free(port):
        # 이미 떠 있음(로컬 재실행 등) → 그대로 사용
        return f"http://localhost:{port}"
    try:
        config = uvicorn.Config(fastapi_app, host="127.0.0.1", port=port, log_level="warning")
        server = uvicorn.Server(config)
        t = threading.Thread(target=server.run, daemon=True, name="fastapi-sidecar")
        t.start()
        return f"http://localhost:{port}"
    except Exception as exc:
        st.session_state["_backend_thread_error"] = f"백엔드 기동 실패: {exc}"
        return ""


def _app_meta() -> dict:
    try:
        from backend.app import config as C

        return {
            "school": {"name": C.SCHOOL_NAME, "year": C.SCHOOL_YEAR},
            "tabs": list(C.ALL_APP_TABS),
            "days": list(C.DAYS),
            "periods_per_day": dict(C.PERIODS_PER_DAY),
            "sheets": {
                "timetable": C.TIMETABLE_SHEET_ID,
                "work": C.WORK_SHEET_ID,
            },
        }
    except Exception:
        return {
            "school": {"name": "서라벌여자중학교", "year": "2026"},
            "tabs": [],
            "days": ["월", "화", "수", "목", "금"],
            "periods_per_day": {"월": 6, "화": 7, "수": 7, "목": 7, "금": 6},
            "sheets": {
                "timetable": "1jZhTHyJ8vKXn6tkoFXfY_f52-pj6eQTdVvRCo3cCmBA",
                "work": "1g1B1cyZG_tfRn3AD1NZzr30YxYNYFewJeZYdos2obpU",
            },
        }


def _inline_dist(api_base: str) -> str | None:
    """frontend/dist를 단일 HTML로 인라인. 실패 시 None."""
    try:
        raw = DIST_INDEX.read_text(encoding="utf-8")
    except Exception as exc:
        st.session_state["_dist_error"] = f"frontend/dist/index.html 없음: {exc} (먼저 frontend에서 npm run build)"
        return None

    # 스크립트/스타일 인라인 (절대경로 /assets/* → 인라인)
    html_text = raw
    import re as _re
    # JS
    def _js_repl(m: _re.Match) -> str:
        url = m.group(1)
        name = Path(url).name
        cand = DIST_DIR / "assets" / name
        if not cand.exists():
            cand = DIST_DIR / name
        if not cand.exists():
            return m.group(0)
        try:
            content = cand.read_text(encoding="utf-8").replace("</script", "<\\/script")
        except Exception:
            return m.group(0)
        return f"<script type=\"module\">{content}</script>"
    html_text = _re.sub(r'<script[^>]*src="([^"]+)"[^>]*>\s*</script>', _js_repl, html_text)
    # CSS
    def _css_repl(m: _re.Match) -> str:
        url = m.group(1)
        name = Path(url).name
        cand = DIST_DIR / "assets" / name
        if not cand.exists():
            cand = DIST_DIR / name
        if not cand.exists():
            return m.group(0)
        try:
            content = cand.read_text(encoding="utf-8")
        except Exception:
            return m.group(0)
        return f"<style>{content}</style>"
    html_text = _re.sub(r'<link[^>]*rel="stylesheet"[^>]*href="([^"]+)"[^>]*/?>', _css_repl, html_text)

    boot = (
        "<script>window.__API_BASE__="
        + json.dumps(api_base)
        + ";window.__STREAMLIT_MODE__=true;window.__APP_CONFIG__="
        + json.dumps(_app_meta(), ensure_ascii=False)
        + ";</script>"
    )
    html_text = html_text.replace("</head>", boot + "</head>", 1) if "</head>" in html_text else boot + html_text
    # iframe(srcdoc) 내부 상대경로 안전장치
    if "<base" not in html_text:
        html_text = html_text.replace("<head>", "<head><base target=\"_self\">", 1)
    return html_text


def main() -> None:
    backend_port = int(os.getenv("BACKEND_PORT", "8000").strip() or "8000")
    secret_backend = _secret("BACKEND_URL", os.getenv("BACKEND_URL", ""))
    frontend_url = _secret("FRONTEND_URL", os.getenv("FRONTEND_URL", ""))

    thread_base = _ensure_backend_thread(backend_port)
    api_base = secret_backend or thread_base

    # 1) 별도 호스팅 프론트가 지정되면 iframe으로 연결 (Vercel 등 + Streamlit Cloud 조합)
    if frontend_url:
        sep = "&" if "?" in frontend_url else "?"
        src = f"{frontend_url}{sep}apiBase={html_lib.escape(api_base)}"
        components.iframe(src, height=2600, scrolling=True)
    else:
        # 2) 기본: 로컬 dist 인라인 (React가 UI 전담)
        html_text = _inline_dist(api_base)
        if html_text is None:
            st.error("React 빌드(dist)를 찾지 못했습니다. `cd frontend && npm run build` 후 다시 실행하세요.")
            with st.expander("배포 진단", expanded=True):
                st.code(f"DIST_DIR={DIST_DIR}\nBACKEND_URL={secret_backend or '(없음)'}\n스레드 백엔드={thread_base or '(미기동)'}")
                err = st.session_state.get("_dist_error", "")
                if err:
                    st.caption(err)
            return
        components.html(html_text, height=2600, scrolling=True)

    # 최소 상태바: Streamlit 요소는 접힌 진단 패널로만 유지 (React가 UI 전담)
    with st.expander("⚙️ 연결 상태 (Streamlit 셸)", expanded=False):
        st.write(f"API Base: `{api_base or '(상대경로 /api — BACKEND_URL 미설정 시 Cloud에서 실패할 수 있음)'}`")
        meta = _app_meta()
        st.write(f"학교: {meta['school']['name']} {meta['school']['year']}")
        st.write(f"시간표 시트: `{meta['sheets']['timetable']}`")
        st.write(f"업무 시트: `{meta['sheets']['work']}`")
        if st.session_state.get("_backend_thread_error"):
            st.warning(st.session_state["_backend_thread_error"])
        st.caption("Streamlit Cloud 배포 시: 백엔드를 Render/Fly 등에 올리고 Secrets에 BACKEND_URL을 지정하세요. "
                   "또는 BACKEND_URL 없이 단일 VPS에서 8501(Streamlit)+8000(FastAPI)을 함께 열어 사용하세요.")


if __name__ == "__main__":
    main()
else:
    # `streamlit run streamlit_app.py`는 모듈 임포트 후 실행되므로 main 보장
    try:
        main()
    except Exception as exc:
        st.error(f"앱 초기화 실패: {exc}")
