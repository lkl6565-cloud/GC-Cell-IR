"""키움 REST API 조회 전용 중계 (주문·계좌 API 차단)

POST /api/kiwoom  {"group": "dostk", "category": "mrkcond", "api_id": "ka10086",
                   "body": {...}, "cont_yn": "N", "next_key": ""}
 -> {"return_code": 0, "data": {...키움 응답...}, "cont_yn": "Y|N", "next_key": "..."}

- 서버의 키움 토큰(serve._kiwoom)을 그대로 쓰므로 앱키·시크릿키는 서버 밖으로 나가지 않는다.
- 허용: ka*(국내 조회), usa*(미국 조회) API 와 아래 CATEGORIES 의 조회용 경로만.
- 차단: kt*(주문·신용·계좌 등), acnt·ordr·crdordr 경로.
- 선택: .env 에 KIWOOM_PROXY_TOKEN 을 넣으면 X-Proxy-Token 헤더가 같아야 호출된다.
- 전체 목록·경로: kiwoom_api.md
"""
import hmac
import os
import re
import threading
import time

import requests

CATEGORIES = {
    "dostk": {"stkinfo", "mrkcond", "rkinfo", "frgnistt", "shsa", "slb", "sect", "chart", "thme", "etf", "elw"},
    "us": {"stkinfo", "mrkcond", "rkinfo", "sect", "chart", "invtinfo"},
}
_ID_OK = {"dostk": re.compile(r"^ka\d{5}$"), "us": re.compile(r"^usa\d{5}$")}

_rate_lock = threading.Lock()
_last = [0.0]
MIN_GAP = 0.25  # 초당 최대 4건 (키움 TR 제한 여유)


def _throttle():
    with _rate_lock:
        wait = _last[0] + MIN_GAP - time.time()
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()


def check_token(header_value):
    want = os.getenv("KIWOOM_PROXY_TOKEN", "").strip()
    if not want:
        return True
    return hmac.compare_digest((header_value or "").encode(), want.encode())


def validate(group, category, api_id):
    if group not in CATEGORIES:
        raise ValueError(f"group 은 {sorted(CATEGORIES)} 중 하나")
    if category not in CATEGORIES[group]:
        raise ValueError(f"{group} 에서 허용된 category: {sorted(CATEGORIES[group])} (주문·계좌는 차단)")
    if not _ID_OK[group].match(api_id or ""):
        raise ValueError("조회용 api_id 만 허용 (국내 ka00000 / 미국 usa00000, kt 계열은 차단)")


def call(kw_factory, reset, group, category, api_id, body, cont_yn="N", next_key=""):
    """kw_factory(): 로그인된 market_data.Kiwoom, reset(): 토큰 폐기. 토큰 오류면 1회 재발급 후 재시도."""
    validate(group, category, api_id)
    for attempt in (1, 2):
        kw = kw_factory()
        headers = {
            "Content-Type": "application/json;charset=UTF-8",
            "api-id": api_id,
            "authorization": f"Bearer {kw.token}",
        }
        if cont_yn == "Y" and next_key:
            headers.update({"cont-yn": "Y", "next-key": next_key})
        for i in range(3):
            _throttle()
            r = requests.post(f"{kw.host}/api/{group}/{category}", headers=headers, json=body or {}, timeout=20)
            if r.status_code != 429:
                break
            time.sleep(1.5 * (i + 1))
        try:
            d = r.json()
        except ValueError:
            d = {"return_code": -1, "return_msg": r.text[:300]}
        msg = str(d.get("return_msg", ""))
        token_bad = r.status_code in (401, 403) or "토큰" in msg or "token" in msg.lower()
        if token_bad and attempt == 1:
            reset()
            continue
        return {
            "http_status": r.status_code,
            "return_code": d.get("return_code"),
            "return_msg": msg,
            "cont_yn": r.headers.get("cont-yn", "N"),
            "next_key": r.headers.get("next-key", ""),
            "data": d,
        }
