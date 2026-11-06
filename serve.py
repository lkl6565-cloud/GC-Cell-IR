"""지씨셀 IR 대시보드 서버 (FastAPI)

- 시세·수급·지수: 키움증권 REST API (market_data.py)  / NBI·환율: Yahoo, KQ26 대체: Investing.com
- 뉴스: 지씨셀 = 네이버 API HUB('지씨셀'+'아티바'), NBI = Yahoo → Investing.com → Google (news_sources.py)
- 한 항목이 실패해도 전체 새로고침이 죽지 않고, 실패 사유는 응답의 "warnings" 에 담깁니다.
"""
import base64
import hmac
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response

import market_data as md
import news_sources as ns

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(dotenv_path=BASE_DIR / ".env", override=True)

KST = timezone(timedelta(hours=9))  # 서버 시간대와 무관하게 한국시간 기준
app = FastAPI()

# ---------------------------------------------------------------------------
# 접근 보호 (선택): .env 에 DASHBOARD_PASSWORD(12자 이상)를 넣으면 모든 요청에 로그인이 필요합니다.
# 주의: http:// 로 접속하면 비밀번호가 평문으로 오갑니다. Nginx + SSL(https) 뒤에서 쓰세요.
# ---------------------------------------------------------------------------
DASH_USER = os.getenv("DASHBOARD_USER", "admin")
DASH_PASS = os.getenv("DASHBOARD_PASSWORD", "")
if len(DASH_PASS) < 12:
    DASH_PASS = ""
    print("[경고] DASHBOARD_PASSWORD(12자 이상)가 없어 로그인 없이 공개됩니다. .env 에 설정하세요.")


@app.middleware("http")
async def basic_auth(request: Request, call_next):
    if not DASH_PASS:
        return await call_next(request)
    h = request.headers.get("authorization", "")
    if h.lower().startswith("basic "):
        try:
            u, _, p = base64.b64decode(h[6:].strip()).decode("utf-8").partition(":")
            if hmac.compare_digest(u.encode(), DASH_USER.encode()) and hmac.compare_digest(p.encode(), DASH_PASS.encode()):
                return await call_next(request)
        except Exception:  # noqa: BLE001
            pass
    return Response("인증이 필요합니다", status_code=401,
                    headers={"WWW-Authenticate": 'Basic realm="gccell", charset="UTF-8"'})


# ---------------------------------------------------------------------------
# 키움 연결: 토큰은 한 번 받아 재사용, 만료/오류면 새로 받아 1회 재시도, 종료 시 폐기
# ---------------------------------------------------------------------------
_kw = None
_kw_lock = threading.Lock()


def _kiwoom():
    global _kw
    with _kw_lock:
        if _kw is None:
            appkey, secret = os.getenv("KIWOOM_APPKEY", "").strip(), os.getenv("KIWOOM_SECRETKEY", "").strip()
            if not appkey or not secret:
                raise RuntimeError("KIWOOM_APPKEY / KIWOOM_SECRETKEY 미설정 (.env 확인)")
            kw = md.Kiwoom(appkey, secret, mock=os.getenv("KIWOOM_MOCK") == "1")
            kw.login()
            _kw = kw
        return _kw


def _reset_kiwoom():
    global _kw
    with _kw_lock:
        old, _kw = _kw, None
    if old is not None:
        old.revoke()


def _market(now, warnings):
    for attempt in (1, 2):
        try:
            return md.collect_market(_kiwoom(), now)
        except Exception as e:  # noqa: BLE001
            print(f"[경고] 키움 조회 실패({attempt}/2): {e}")
            warnings.append(f"키움 조회 실패: {str(e)[:160]}")
            _reset_kiwoom()
    return md.collect_market(None, now)  # 키움 없이 NBI·KQ26(Investing)·환율만이라도 채운다


def _safe(fn, default, label, warnings):
    try:
        return fn()
    except Exception as e:  # noqa: BLE001
        print(f"[경고] {label} 실패: {e}")
        warnings.append(f"{label} 실패: {str(e)[:160]}")
        return default


def build_payload():
    """시세·뉴스를 새로 수집한다. 한 항목이 실패해도 나머지는 계속 만든다."""
    now = datetime.now(KST)
    warnings = []
    market = _market(now, warnings)

    # 지씨셀 뉴스와 NBI 뉴스는 서로 다른 함수로 따로 가져오고, NBI 쪽에서 지씨셀 기사와 겹치면 제거한다
    company_news = _safe(ns.company_news, [], "지씨셀 뉴스", warnings)
    nbi_news = _safe(lambda: ns.nbi_news(3, exclude=company_news), [], "NBI 뉴스", warnings)

    market_news = _safe(ns.market_news, [], "시황 뉴스", warnings)

    data = {
        "updatedAt": now.strftime("%Y-%m-%d %H:%M:%S"),
        "tradingDate": market["tradingDate"],
        "screenTitle": f"IR 주가변동 3대 요인 [{now.strftime('%Y-%m-%d')}]",
        "stock": market["stock"],
        "companyNews": company_news,
        "nbiNews": nbi_news,
        "marketNews": market_news,
        "macroIndices": market["macroIndices"],
    }
    ai = _safe(lambda: md.ai_analysis(data), None, "AI 요약", warnings)
    data["analysis"] = {**(ai or md.analysis_block(data)), "is_ai": bool(ai)}
    data["warnings"] = warnings
    return data


# 방문할 때마다 외부 API 를 부르지 않도록 짧게 캐시
_lock = threading.Lock()
_cache = {"ts": 0.0, "data": None}
DATA_TTL = 60       # /data.json: 60초 이내 재요청은 캐시
MIN_INTERVAL = 10   # 새로고침 버튼: 10초 이내 연속 클릭은 캐시


def get_payload(force=False):
    with _lock:
        age = time.time() - _cache["ts"]
        if _cache["data"] is not None and age < (MIN_INTERVAL if force else DATA_TTL):
            return _cache["data"]
        data = build_payload()
        _cache["ts"], _cache["data"] = time.time(), data
        return data


@app.get("/api/stock")
def api_stock():
    return JSONResponse(content=get_payload()["stock"])


@app.get("/api/news")
def api_news():
    try:
        return JSONResponse(content=ns.company_news())
    except Exception as e:  # noqa: BLE001
        return JSONResponse(content={"error": str(e)[:200]}, status_code=502)


@app.get("/api/nbi-news")
def api_nbi_news():
    try:
        return JSONResponse(content=ns.nbi_news(3, exclude=_safe(ns.company_news, [], "지씨셀 뉴스", [])))
    except Exception as e:  # noqa: BLE001
        return JSONResponse(content={"error": str(e)[:200]}, status_code=502)


@app.get("/api/refresh")
@app.post("/api/refresh")
def api_refresh():
    return JSONResponse(content=get_payload(force=True))


@app.get("/data.json")
def api_data():
    return JSONResponse(content=get_payload(force=False))


@app.get("/healthz")
def healthz():
    return JSONResponse(content={"ok": True})


# 폴더 전체를 공개하던 StaticFiles(directory=".") 는 제거했습니다 (.env, serve.py 가 내려받아질 수 있었음).
# 화면 파일 하나만 명시적으로 제공합니다.
@app.get("/")
@app.get("/index.html")
def index():
    return FileResponse(BASE_DIR / "index.html")


@app.on_event("shutdown")
def _shutdown():
    _reset_kiwoom()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("serve:app", host=os.getenv("HOST", "0.0.0.0"), port=int(os.getenv("PORT", "8000")), reload=False)
