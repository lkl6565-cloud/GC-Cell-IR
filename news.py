"""뉴스 수집 모듈 (FastAPI 와 무관한 순수 함수 모음)

- 지씨셀 뉴스 : 네이버 API HUB('지씨셀 OR 아티바') -> 실패 시 구글 뉴스 RSS
- NBI 뉴스    : Yahoo Finance(yfinance) -> Investing.com -> 구글 뉴스 RSS (영문 BIO 기사 중심)
- 두 목록은 서로 완전히 독립적으로 가져오고, NBI 목록에서 지씨셀 기사와 겹치는 항목은 제외한다.
- 날짜는 항상 'MM-DD'(한국시간) 문자열로 통일한다 (index.html 의 날짜 변환과 호환).
"""
import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from urllib.parse import quote, urlparse, urljoin

import requests

KST = timezone(timedelta(hours=9))
_MIN_DT = datetime.min.replace(tzinfo=KST)


def _entry(dt, title, publisher, link):
    return dt, {
        "date": dt.strftime("%m-%d") if dt else "",
        "title": title,
        "publisher": publisher,
        "linkUrl": link,
    }


def _newest(pairs):
    return sorted(pairs, key=lambda x: x[0] or _MIN_DT, reverse=True)


def _http_ok(link):
    return urlparse(link or "").scheme in ("http", "https")


def _plain(fragment):
    fragment = re.sub(r"<!--.*?-->", "", fragment, flags=re.S)
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def _norm_title(t):
    return re.sub(r"^\[[^\]]+\]\s*", "", t or "").lower().strip()


def google_news(query, limit=3, days=2):
    url = f"https://news.google.com/rss/search?q={quote(f'{query} when:{days}d')}&hl=ko&gl=KR&ceid=KR:ko"
    r = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    out = []
    for it in ET.fromstring(r.content).iter("item"):
        title, link = (it.findtext("title") or "").strip(), (it.findtext("link") or "").strip()
        publisher = (it.findtext("source") or "Google News").strip()
        if title.endswith(f" - {publisher}"):
            title = title[: -len(publisher) - 3]
        try:
            dt = parsedate_to_datetime(it.findtext("pubDate")).astimezone(KST)
        except Exception:
            dt = None
        if title and _http_ok(link):
            out.append(_entry(dt, title, publisher, link))
    return [x[1] for x in _newest(out)[:limit]]


def naver_news(query, limit=3):
    kid = os.getenv("X-NCP-APIGW-API-KEY-ID") or os.getenv("NAVER_CLIENT_ID")
    key = os.getenv("X-NCP-APIGW-API-KEY") or os.getenv("NAVER_CLIENT_SECRET")
    if not kid or not key:
        raise RuntimeError("네이버 API HUB 키 미설정")
    out, seen = [], set()
    r = requests.get(
        "https://naverapihub.apigw.ntruss.com/search/v1/news",
        headers={"X-NCP-APIGW-API-KEY-ID": kid.strip(), "X-NCP-APIGW-API-KEY": key.strip()},
        params={"query": query, "display": 15, "start": 1, "sort": "date", "format": "json"},
        timeout=8,
    )
    if r.status_code != 200:
        raise RuntimeError(f"네이버 뉴스 API 실패(HTTP {r.status_code})")
    for it in r.json().get("items", []):
        title = unescape(re.sub(r"<[^>]+>", "", it.get("title", ""))).strip()
        link = it.get("link") or it.get("originallink") or ""
        if not title or title in seen or not _http_ok(link):
            continue
        seen.add(title)
        try:
            dt = parsedate_to_datetime(it["pubDate"]).astimezone(KST)
        except Exception:
            dt = None
        host = urlparse(it.get("originallink") or link).netloc.removeprefix("www.")
        out.append(_entry(dt, title, host or "네이버뉴스", link))
    return [x[1] for x in _newest(out)[:limit]]


def company_news(limit=3):
    query = "지씨셀 OR 아티바"
    try:
        items = naver_news(query, limit)
        if items:
            return items
    except Exception as e:
        print(f"[경고] 네이버 뉴스 실패 -> 구글 뉴스로 대체: {e}")
    return google_news(query, limit)


NBI_YAHOO_SYMBOLS = "^NBI,IBB,IBBQ,AMGN,GILD,VRTX,REGN"


def _yahoo_item(raw):
    if raw.get("ad"):
        return None
    c = raw.get("content") if isinstance(raw.get("content"), dict) else raw
    title = (c.get("title") or "").strip()
    if not title:
        return None
    prov = c.get("provider")
    publisher = prov.get("displayName") if isinstance(prov, dict) else c.get("publisher")
    link = ""
    for k in ("canonicalUrl", "clickThroughUrl"):
        u = c.get(k)
        if isinstance(u, dict) and u.get("url"):
            link = u["url"]
            break
    link = link or c.get("link") or ""
    if not _http_ok(link):
        return None
    dt = None
    try:
        if c.get("pubDate"):
            dt = datetime.fromisoformat(str(c["pubDate"]).replace("Z", "+00:00")).astimezone(KST)
        elif c.get("providerPublishTime"):
            dt = datetime.fromtimestamp(int(c["providerPublishTime"]), KST)
    except (ValueError, OSError):
        dt = None
    return _entry(dt, title, publisher or "Yahoo Finance", link)


def yahoo_news(limit=3):
    import yfinance as yf
    symbols = [s.strip() for s in (os.getenv("NBI_NEWS_SYMBOLS") or NBI_YAHOO_SYMBOLS).split(",") if s.strip()]
    broad, named, seen = [], {}, set()
    for i, sym in enumerate(symbols):
        try:
            raw = yf.Ticker(sym).news or []
        except Exception:
            continue
        time.sleep(0.2)
        for r in raw:
            x = _yahoo_item(r)
            if not x or x[1]["linkUrl"] in seen:
                continue
            seen.add(x[1]["linkUrl"])
            if i < 3:
                broad.append(x)
            else:
                named.setdefault(sym, []).append((x[0], {**x[1], "title": f"[{sym}] {x[1]['title']}"}))
    chosen = _newest(broad)[:limit]
    if len(chosen) < limit:
        firsts = [_newest(v)[0] for v in named.values() if v]
        rest = [y for v in named.values() for y in _newest(v)[1:]]
        for pool in (firsts, rest):
            for x in _newest(pool):
                if len(chosen) < limit:
                    chosen.append(x)
    return [it for _, it in _newest(chosen)[:limit]]


INVESTING_HOSTS = ("www.investing.com", "uk.investing.com")
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
_DATE_RE = re.compile(r"(\d{1,2}\s+[A-Z][a-z]{2}\s+\d{4}|[A-Z][a-z]{2}\s+\d{1,2},\s+\d{4}|\d+\s+(?:minute|hour|day)s?\s+ago)")
_ARTICLE_RE = re.compile(r"/news/[^/]+/.+-\d{5,}$")


def _inv_date(text, now):
    for fmt in ("%d %b %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=KST)
        except ValueError:
            pass
    m = re.match(r"(\d+)\s+(minute|hour|day)s?\s+ago", text)
    if m:
        n = int(m.group(1))
        return now - {"minute": timedelta(minutes=n), "hour": timedelta(hours=n), "day": timedelta(days=n)}[m.group(2)]
    return None


def parse_investing_news(html, host="www.investing.com", now=None):
    now = now or datetime.now(KST)
    html = re.sub(r"<!--.*?-->", "", html, flags=re.S)
    anchors = [m for m in re.finditer(r'<a\b[^>]*?href="([^"]+)"[^>]*>(.*?)</a>', html, re.S)
               if _ARTICLE_RE.search(urlparse(m.group(1)).path)]
    out, seen = [], set()
    for i, m in enumerate(anchors):
        href, title = m.group(1), _plain(m.group(2))
        if len(title) < 12 or href in seen:
            continue
        seen.add(href)
        end = next((a.start() for a in anchors[i + 1:] if a.start() > m.end()), m.end() + 2500)
        dm = _DATE_RE.search(_plain(html[m.end():min(end, m.end() + 2500)]))
        out.append(_entry(_inv_date(dm.group(1), now) if dm else None, title, "Investing.com", urljoin(f"https://{host}", href)))
    return out


def investing_news(limit=3):
    hosts = [os.getenv("INVESTING_HOST")] if os.getenv("INVESTING_HOST") else list(INVESTING_HOSTS)
    for host in hosts:
        try:
            r = requests.get(f"https://{host}/indices/nasdaq-biotechnology-news", timeout=12,
                             headers={"User-Agent": _UA, "Accept": "text/html", "Accept-Language": "en-US,en;q=0.9"})
            if r.status_code == 200 and len(r.text) > 5000:
                items = parse_investing_news(r.text, host)
                if items:
                    return [x[1] for x in _newest(items)[:limit]]
        except requests.RequestException:
            continue
    raise RuntimeError("Investing.com 뉴스 실패")


def nbi_news(limit=3, exclude=None):
    ex_titles = {_norm_title(x.get("title")) for x in (exclude or [])}
    ex_links = {x.get("linkUrl") for x in (exclude or [])}
    
    sources = {
        "yahoo": ("Yahoo Finance", lambda: yahoo_news(limit + 3)),
        "investing": ("Investing.com", lambda: investing_news(limit + 3)),
        "google": ("Google News (BIO)", lambda: google_news("NASDAQ Biotechnology OR Biotech OR Biopharma", limit + 3, 3)),
    }
    order = [x.strip() for x in (os.getenv("NBI_NEWS_ORDER") or "yahoo,investing,google").split(",") if x.strip() in sources]
    out, titles = [], set()
    for key in order:
        label, fn = sources[key]
        try:
            items = fn()
        except Exception:
            continue
        for it in items:
            t = _norm_title(it["title"])
            if t in titles or t in ex_titles or it["linkUrl"] in ex_links:
                continue
            titles.add(t)
            if len(out) < limit:
                out.append(it)
        if len(out) >= limit:
            break
    return out
