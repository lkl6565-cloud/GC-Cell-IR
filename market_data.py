"""시장 데이터 수집 모듈 (키움증권 REST API 기준) - FastAPI 와 무관한 순수 함수 모음

- 키움: 지씨셀 시세(시간대 규칙: 장 시작 전=전일종가 / 장중=실시간 / 마감 후=금일종가), 투자자별 수급,
        코스피·코스닥·코스닥 제약(KQ26 = 업종코드 120)
- 코스닥 제약(KQ26): 키움 실패 시 Investing.com 으로 대체 (야후 사용 안 함)
- NBI 지수·원/달러: Yahoo Finance (NBI 는 실패 시 Investing.com)
- 분석 문구: 수집된 숫자로 만든 자동 문구, GEMINI_API_KEY 가 있으면 실제 데이터만 근거로 AI 요약
"""
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from html import unescape
from urllib.parse import urlparse

import requests

CODE, NAME = "144510", "지씨셀"
KST = timezone(timedelta(hours=9))

INVESTOR_UNIT_WON = 1_000_000

def safe(fn, default, label):
    """한 항목이 실패해도 전체 보고서는 계속 만든다."""
    try:
        return fn()
    except Exception as e:  # noqa: BLE001
        print(f"[경고] {label} 실패: {e}", file=sys.stderr)
        return default


def num(s):
    """키움 응답의 '+61300', '-2394.49', '--28837', '1,234' 같은 문자열을 float 로."""
    if s is None:
        return None
    t = str(s).replace(",", "").strip()
    if not t:
        return None
    neg = t.startswith("-")
    t = t.lstrip("+-")
    try:
        v = float(t)
    except ValueError:
        return None
    return -v if neg else v


def pct_str(v):
    return f"{v:+.2f}%"


def eok(won):
    return f"{won / 1e8:+,.1f}억"


def tone(s):
    """한국식: 상승 빨강 / 하락 파랑 / 0·없음 회색"""
    v = num(str(s or "").replace("억", "").replace("%", ""))
    if v is None or v == 0:
        return "#666"
    return "#d62728" if v > 0 else "#1f5fbf"

class Kiwoom:
    def __init__(self, appkey, secretkey, mock=False):
        self.appkey, self.secretkey = appkey, secretkey
        self.host = "https://mockapi.kiwoom.com" if mock else "https://api.kiwoom.com"
        self.token = None

    def login(self):
        r = requests.post(
            f"{self.host}/oauth2/token",
            headers={"Content-Type": "application/json;charset=UTF-8"},
            json={"grant_type": "client_credentials", "appkey": self.appkey, "secretkey": self.secretkey},
            timeout=10,
        )
        d = r.json()
        if not d.get("token") or d.get("return_code") not in (None, 0, "0"):
            raise RuntimeError(
                f"토큰 발급 실패: {d.get('return_msg')} "
                "(키움 REST API 포털 > 계좌 APP Key 관리에서 현재 PC의 IP를 등록했는지 확인)"
            )
        self.token = d["token"]

    def post(self, path, api_id, body, retries=3):
        for i in range(retries):
            r = requests.post(
                self.host + path,
                headers={
                    "Content-Type": "application/json;charset=UTF-8",
                    "api-id": api_id,
                    "authorization": f"Bearer {self.token}",
                },
                json=body,
                timeout=15,
            )
            if r.status_code == 429:  # 요청 제한: 잠시 쉬고 재시도
                time.sleep(1.5 * (i + 1))
                continue
            r.raise_for_status()
            d = r.json()
            # 업무 오류도 HTTP 200 으로 오므로 return_code 로 판별
            if d.get("return_code") not in (0, "0"):
                raise RuntimeError(f"{api_id} 오류: {d.get('return_msg')}")
            time.sleep(0.3)
            return d
        raise RuntimeError(f"{api_id}: 요청 제한(429)이 계속됨")

    def revoke(self):
        if not self.token:
            return
        try:
            requests.post(
                f"{self.host}/oauth2/revoke",
                headers={"Content-Type": "application/json;charset=UTF-8"},
                json={"appkey": self.appkey, "secretkey": self.secretkey, "token": self.token},
                timeout=10,
            )
        except Exception:  # noqa: BLE001
            pass

def stock_block(kw):
    d = kw.post("/api/dostk/stkinfo", "ka10001", {"stk_cd": CODE})
    price, ratio, vol = num(d.get("cur_prc")), num(d.get("flu_rt")), num(d.get("trde_qty"))
    if price is None or ratio is None:
        raise RuntimeError(f"ka10001 응답 필드 확인 필요: {list(d)[:12]}")
    return {
        "price": f"{abs(price):,.0f}원",
        "ratio": pct_str(ratio),
        "volume": f"{abs(vol or 0):,.0f}주",
        "marketStatus": "정규장 마감",
    }


def daily_bars(kw, ymd):
    """ka10081 주식일봉차트: 종목코드 '144510'(접미사 없음) = KRX 정규장 기준 일봉. 최신순 정렬."""
    d = kw.post("/api/dostk/chart", "ka10081", {"stk_cd": CODE, "base_dt": ymd, "upd_stkpc_tp": "1"})
    rows = [r for r in (d.get("stk_dt_pole_chart_qry") or []) if r.get("dt") and num(r.get("cur_prc")) is not None]
    if not rows:
        raise RuntimeError(f"ka10081 응답에 일봉이 없음: {list(d)[:8]}")
    return sorted(rows, key=lambda r: r["dt"], reverse=True)


def _bar_quote(rows, i, status):
    """i번째 일봉의 종가·전일대비·거래량 (전일대비는 바로 앞 영업일 종가 기준)."""
    close = abs(num(rows[i]["cur_prc"]))
    prev = abs(num(rows[i + 1]["cur_prc"])) if i + 1 < len(rows) else None
    return {
        "price": f"{close:,.0f}원",
        "ratio": pct_str((close - prev) / prev * 100) if prev else "-",
        "volume": f"{abs(num(rows[i].get('trde_qty')) or 0):,.0f}주",
        "marketStatus": status,
    }


MARKET_OPEN, MARKET_CLOSE = 9 * 60, 15 * 60 + 30  # 한국시간 09:00 / 15:30 (분 단위)


def price_block(kw, now):
    """한국시간 기준 가격 규칙
      1) 00:00~09:00        : 전일 종가
      2) 09:00~15:30        : 당일 실시간 현재가
      3) 15:30~24:00        : 당일 종가 (KRX 정규장 종가, 시간외 단일가 제외)
    휴장일(오늘 일봉이 없음)에는 항상 직전 거래일 종가를 보여준다."""
    ymd = now.strftime("%Y%m%d")
    hm = now.hour * 60 + now.minute
    rows = daily_bars(kw, ymd)
    today_bar = rows[0]["dt"] == ymd

    if hm < MARKET_OPEN:
        return _bar_quote(rows, 1 if today_bar else 0, "전일 종가 (장 시작 전)")
    if hm < MARKET_CLOSE:
        if today_bar or hm < MARKET_OPEN + 5:  # 개장 직후 몇 분은 일봉 생성 전일 수 있음
            st = stock_block(kw)
            st["marketStatus"] = "장중 (실시간)"
            return st
        return _bar_quote(rows, 0, "전 거래일 종가 (휴장)")
    if today_bar:
        return _bar_quote(rows, 0, "금일 종가 (정규장 마감)")
    return _bar_quote(rows, 0, "전 거래일 종가 (휴장 또는 집계 지연)")


def investor_rows(kw, ymd):
    d = kw.post(
        "/api/dostk/stkinfo",
        "ka10059",
        {"dt": ymd, "stk_cd": CODE, "amt_qty_tp": "1", "trde_tp": "0", "unit_tp": "1000"},
    )
    rows = d.get("stk_invsr_orgn") or []
    if not rows:
        raise RuntimeError(f"ka10059 응답에 일별 데이터가 없음: {list(d)[:8]}")
    return sorted(rows, key=lambda r: r.get("dt", ""), reverse=True)


def investor_block(rows):
    cols = {"foreign": "frgnr_invsr", "organ": "orgn", "personal": "ind_invsr"}

    def total(sub, col):
        return sum((num(r.get(col)) or 0) for r in sub) * INVESTOR_UNIT_WON

    return {
        **{k: eok(total(rows[:1], c)) for k, c in cols.items()},
        "5d": {k: eok(total(rows[:5], c)) for k, c in cols.items()},
    }


def sector_index(kw, mrkt_tp, inds_cd):
    d = kw.post("/api/dostk/sect", "ka20001", {"mrkt_tp": mrkt_tp, "inds_cd": inds_cd})
    price, ratio = num(d.get("cur_prc")), num(d.get("flu_rt"))
    if price is None or ratio is None:
        raise RuntimeError(f"ka20001 응답 필드 확인 필요: {list(d)[:12]}")
    return {"value": f"{abs(price):,.2f}", "ratio": pct_str(ratio)}


def sector_names(kw, mrkt_tp):
    """ka10101(업종코드 리스트) -> {업종코드: 업종명}"""
    d = kw.post("/api/dostk/stkinfo", "ka10101", {"mrkt_tp": mrkt_tp})
    out = {}
    for v in d.values():
        if not isinstance(v, list):
            continue
        for it in v:
            if isinstance(it, dict):
                code = it.get("code") or it.get("inds_cd")
                name = str(it.get("name") or it.get("inds_nm") or "").strip()
                if code and name:
                    out[str(code)] = name
    return out


def find_sector_code(names, keyword):
    """이름이 정확히 keyword 인 업종을 우선, 없으면 keyword 가 포함된 첫 업종."""
    exact = partial = None
    for code, name in names.items():
        if keyword not in name:
            continue
        if name.replace("코스닥", "").replace("KOSDAQ", "").strip() == keyword:
            exact = exact or (code, name)
        partial = partial or (code, name)
    return exact or partial


PHARMA_CODE_DEFAULT = "120"  # 키움 지수차트의 '제약 120' = 코스닥 제약(KQ26)


def kosdaq_pharma_kiwoom(kw):
    """KQ26(코스닥 제약). KQ26 은 Investing.com 표기이고 키움에서는 업종코드 120 이다."""
    code = os.environ.get("PHARMA_CODE") or PHARMA_CODE_DEFAULT
    # 업종명 대조는 참고용: 목록 조회가 안 돼도 120 으로 그대로 조회한다
    name = safe(lambda: sector_names(kw, "1"), {}, "업종코드 목록(ka10101)").get(code)
    if name and "제약" not in name:
        print(f"[경고] 업종코드 {code} 의 업종명은 '{name}' 입니다. 코스닥 제약이 맞는지 확인하세요.", file=sys.stderr)
    else:
        print(f"코스닥 제약 업종코드: {code}" + (f" ({name})" if name else ""))
    return sector_index(kw, "1", code)

def kq26_quote(kw):
    """코스닥 제약(KQ26): 키움(업종코드 120) 우선, 실패하거나 키움 연결이 없으면 Investing.com."""
    if kw is not None:
        try:
            return kosdaq_pharma_kiwoom(kw)
        except Exception as e:  # noqa: BLE001
            print(f"[경고] 키움 KQ26 실패 -> Investing.com 으로 대체: {e}", file=sys.stderr)
    return investing_quote("kosdaq-pharmaceuticals")


def yf_pair(symbol):
    import yfinance as yf

    h = yf.Ticker(symbol).history(period="10d")["Close"].dropna()
    return float(h.iloc[-1]), float(h.iloc[-2])


def nbi_index():
    try:
        last, prev = yf_pair("^NBI")
        return {"value": f"{last:,.2f}", "ratio": pct_str((last - prev) / prev * 100)}
    except Exception as e:  # noqa: BLE001
        print(f"[경고] Yahoo ^NBI 실패 -> Investing.com 으로 대체: {e}", file=sys.stderr)
        return investing_quote("nasdaq-biotechnology")


def usd_krw():
    last, prev = yf_pair("KRW=X")
    return {"value": f"{last:,.2f}", "change": pct_str((last - prev) / prev * 100)}

INVESTING_HOSTS = ("www.investing.com", "uk.investing.com")
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
       "Chrome/126.0.0.0 Safari/537.36")


def _investing_get(path):
    hosts = [os.environ["INVESTING_HOST"]] if os.environ.get("INVESTING_HOST") else list(INVESTING_HOSTS)
    last = "알 수 없음"
    for host in hosts:
        try:
            r = requests.get(
                f"https://{host}{path}",
                headers={"User-Agent": _UA, "Accept": "text/html,application/xhtml+xml",
                         "Accept-Language": "en-US,en;q=0.9"},
                timeout=12,
            )
        except requests.RequestException as e:
            last = f"{host}: {e.__class__.__name__}"
            continue
        if r.status_code == 200 and len(r.text) > 5000:
            return host, r.text
        last = f"{host}: HTTP {r.status_code}"
    raise RuntimeError(f"Investing.com 접속 실패 ({last}) - 봇 차단일 수 있음")


def _plain(fragment):
    fragment = re.sub(r"<!--.*?-->", "", fragment, flags=re.S)
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def parse_investing_quote(html):
    """종가·등락률을 읽고, 값끼리 맞는지(전일가 대비 계산) 검증한 뒤 반환."""
    html = re.sub(r"<!--.*?-->", "", html, flags=re.S)

    def attr(name):
        m = re.search(rf'data-test="{name}"[^>]*>(.*?)</', html, re.S)
        return _plain(m.group(1)) if m else None

    last_s, chg_s, pct_s = attr("instrument-price-last"), attr("instrument-price-change"), attr("instrument-price-change-percent")
    if not (last_s and chg_s and pct_s):  # 속성 방식 실패 시: 화면 글자에서 '7,463.7 +197.3 (+2.72%)' 모양을 찾음
        m = re.search(
            r"([\d,]+(?:\.\d+)?)\s*([+\-\u2212]\s?[\d,]+(?:\.\d+)?)\s*\(\s*([+\-\u2212]?\s?[\d.]+)\s*%\s*\)",
            _plain(html),
        )
        if not m:
            raise RuntimeError("Investing.com 시세 위치를 찾지 못함 (페이지 구조 변경 가능)")
        last_s, chg_s, pct_s = m.groups()

    def clean(x):
        return str(x).replace("\u2212", "-").replace(" ", "").strip("()%")

    last, chg, pct = num(clean(last_s)), num(clean(chg_s)), num(clean(pct_s))
    if None in (last, chg, pct) or last <= 0:
        raise RuntimeError("Investing.com 시세 해석 실패")
    if chg < 0 < pct:
        pct = -pct
    prev = last - chg
    if prev <= 0 or abs(chg / prev * 100 - pct) > 0.06:
        raise RuntimeError(f"Investing.com 값 검증 실패 (현재 {last}, 변동 {chg}, 등락률 {pct}%)")
    dec = len(clean(last_s).split(".")[1]) if "." in clean(last_s) else 0
    return {"value": f"{last:,.{dec}f}", "ratio": pct_str(pct)}


def investing_quote(slug):
    host, html = _investing_get(f"/indices/{slug}")
    q = parse_investing_quote(html)
    print(f"Investing.com({host}) {slug}: {q['value']} ({q['ratio']})")
    return q

def ai_analysis(data):
    """실제 수집된 데이터만 근거로 3줄 요약. 키/라이브러리가 없으면 None (-> 숫자 기반 자동 문구)."""
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        return None
    from google import genai

    s = data["stock"]
    facts = {
        "지씨셀": {k: s.get(k) for k in ("price", "ratio", "volume", "marketStatus")},
        "수급(억원, 당일/최근5일)": s.get("investor"),
        "지수": data["macroIndices"],
        "지씨셀 기사 제목": [n["title"] for n in data["companyNews"]],
        "NBI 기사 제목": [n["title"] for n in data["nbiNews"]],
    }
    prompt = (
        "당신은 지씨셀(144510) IR 담당자입니다. 아래 JSON 데이터만 근거로 한국어 요약을 작성하세요.\n"
        "규칙: 제공된 숫자와 기사 제목에 있는 내용만 쓰고, 추측·전망·투자 권유·임상/실적 등 제공되지 않은 사실은 쓰지 마세요. "
        "데이터가 없으면 '데이터 없음'이라고 쓰세요. 각 항목은 1~2문장입니다.\n"
        '반드시 JSON 한 개로만 답하세요: {"internal": "기업 측면(주가·거래량·수급·기사)", '
        '"supply": "업계 측면(코스닥 제약 KQ26·나스닥 바이오 NBI)", "macro": "매크로 측면(코스피·코스닥·원/달러)"}\n\n'
        + json.dumps(facts, ensure_ascii=False)
    )
    try:
        client = genai.Client(api_key=key, http_options={"timeout": 30000})
    except Exception:  # noqa: BLE001
        client = genai.Client(api_key=key)
    resp = client.models.generate_content(model=os.environ.get("GEMINI_MODEL") or "gemini-flash-latest", contents=prompt)
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", (resp.text or "").strip())
    d = json.loads(text)
    out = {k: str(d.get(k, "")).strip() for k in ("internal", "supply", "macro")}
    if not all(out.values()):
        raise RuntimeError("AI 응답 형식 오류")
    return out


# ---------- 분석 문구 / HTML / 메일 ----------
def analysis_block(data):
    """숫자 기반 자동 문구 (AI 요약을 쓰지 않을 때). 해석·전망 없이 수집된 값만 나열."""
    st, inv, m = data["stock"], data["stock"].get("investor"), data["macroIndices"]

    def g(k, f="ratio"):
        return (m.get(k) or {}).get(f, "-")

    internal = f"지씨셀 {st['price']} ({st['ratio']}), 거래량 {st['volume']}."
    if inv:
        internal += f" 최근 거래일 순매수: 외국인 {inv['foreign']}, 기관 {inv['organ']}, 개인 {inv['personal']}."
    first = (data.get("companyNews") or [{}])[0].get("title")
    internal += f" 최신 기사: {first}" if first else " 최근 관련 기사 없음."
    return {
        "internal": internal,
        "supply": f"코스닥 제약(KQ26) {g('kq26')}, 나스닥 바이오(NBI) {g('nbi')}.",
        "macro": f"코스피 {g('kospi')}, 코스닥 {g('kosdaq')}, 원/달러 {g('usdKrw', 'change')}.",
    }


def collect_market(kw, now):
    """시세·수급·지수를 새로 수집. kw=None 이면 키움 항목은 건너뛰고(시세 '-'), 나머지는 계속 만든다.
    kw 가 있는데 시세 조회가 실패하면 예외를 던진다 -> 호출부가 토큰을 다시 받아 재시도."""
    ymd = now.strftime("%Y%m%d")
    st = price_block(kw, now) if kw is not None else {
        "price": "-", "ratio": "-", "volume": "-", "marketStatus": "시세 조회 실패"}
    rows = safe(lambda: investor_rows(kw, ymd), None, "수급(ka10059)") if kw is not None else None
    inv = safe(lambda: investor_block(rows), None, "수급 집계") if rows else None
    if inv:
        st["investor"] = inv

    macro = {
        "nbi": safe(nbi_index, None, "NBI"),
        "kq26": safe(lambda: kq26_quote(kw), None, "코스닥 제약(KQ26)"),
        "kospi": safe(lambda: sector_index(kw, "0", "001"), None, "코스피") if kw is not None else None,
        "kosdaq": safe(lambda: sector_index(kw, "1", "101"), None, "코스닥") if kw is not None else None,
        "usdKrw": safe(usd_krw, None, "원/달러"),
    }
    day = rows[0]["dt"] if rows else ymd
    return {
        "tradingDate": f"{day[:4]}-{day[4:6]}-{day[6:]}",
        "stock": st,
        "macroIndices": {k: v for k, v in macro.items() if v},
    }
