"""국가법령정보센터 Open API (law.go.kr DRF) — 법령·행정규칙 조문 조회

- 인증키: 환경변수 LAW_OC (국가법령정보센터 마이페이지 > API인증키관리의 OC 값)
- 법령(법률·시행령·시행규칙)은 target=law, 금융위 고시 등은 target=admrul
- 법령 본문은 용량이 커서(자본시장법 약 2MB) 6시간 캐시
- 코스닥시장 공시규정 등 거래소 규정은 이 API에 없음 (KRX 법규서비스 별도)
"""
import os
import re
import threading
import time

import requests

BASE = "http://www.law.go.kr/DRF"
TIMEOUT = 20
CACHE_TTL = 6 * 3600

# IR·공시 실무에서 자주 보는 법령 (화면의 빠른 선택 버튼)
PRESETS = [
    {"name": "자본시장법", "query": "자본시장과 금융투자업에 관한 법률", "target": "law"},
    {"name": "자본시장법 시행령", "query": "자본시장과 금융투자업에 관한 법률 시행령", "target": "law"},
    {"name": "자본시장법 시행규칙", "query": "자본시장과 금융투자업에 관한 법률 시행규칙", "target": "law"},
    {"name": "증권의 발행 및 공시 등에 관한 규정", "query": "증권의 발행 및 공시 등에 관한 규정", "target": "admrul"},
    {"name": "상법", "query": "상법", "target": "law"},
    {"name": "외부감사법", "query": "주식회사 등의 외부감사에 관한 법률", "target": "law"},
]

_cache = {}
_lock = threading.Lock()


def _oc():
    oc = os.getenv("LAW_OC", "").strip()
    if not oc:
        raise RuntimeError("LAW_OC 미설정 (.env 또는 Render 환경변수에 국가법령정보센터 OC 값을 넣으세요)")
    return oc


def _get(path, **params):
    params = {"OC": _oc(), "type": "JSON", **params}
    r = requests.get(f"{BASE}/{path}", params=params, timeout=TIMEOUT)
    r.raise_for_status()
    try:
        return r.json()
    except ValueError:
        raise RuntimeError(f"법령 API 응답 오류: {r.text[:200]}") from None


def _as_list(x):
    if x is None:
        return []
    return x if isinstance(x, list) else [x]


def _text(x):
    """문자열 또는 (중첩) 리스트를 줄바꿈 문자열로."""
    if x is None:
        return ""
    if isinstance(x, str):
        return x.strip()
    if isinstance(x, list):
        return "\n".join(t for t in (_text(i) for i in x) if t)
    return str(x)


# ---------------------------------------------------------------------------
# 검색
# ---------------------------------------------------------------------------
def search(query, target="law", rows=20):
    query = (query or "").strip()
    if not query:
        return []
    d = _get("lawSearch.do", target=target, query=query, display=rows)
    if target == "admrul":
        items = _as_list(d.get("AdmRulSearch", {}).get("admrul"))
        return [{
            "target": "admrul",
            "id": it.get("행정규칙일련번호") or _id_from_link(it.get("행정규칙상세링크", "")),
            "name": it.get("행정규칙명", ""),
            "kind": it.get("행정규칙종류", ""),
            "ministry": it.get("소관부처명", ""),
            "date": it.get("발령일자", ""),
            "current": it.get("현행연혁구분", "") == "현행",
        } for it in items]
    items = _as_list(d.get("LawSearch", {}).get("law"))
    return [{
        "target": "law",
        "id": it.get("법령일련번호", ""),
        "name": it.get("법령명한글", ""),
        "short": it.get("법령약칭명", ""),
        "kind": it.get("법령구분명", ""),
        "ministry": it.get("소관부처명", ""),
        "date": it.get("시행일자", ""),
        "promulgated": it.get("공포일자", ""),
        "current": it.get("현행연혁코드", "") == "현행",
    } for it in items]


def _id_from_link(link):
    m = re.search(r"[?&]ID=(\d+)", link or "")
    return m.group(1) if m else ""


def _pick(query, target):
    """검색 결과에서 이름이 정확히 같은(또는 약칭이 같은) 현행 법령을 고른다."""
    res = search(query, target, rows=100)
    if not res:
        raise LookupError(f"'{query}' 검색 결과가 없습니다")
    q = query.replace(" ", "")
    for r in res:
        if r["current"] and q in (r["name"].replace(" ", ""), (r.get("short") or "").replace(" ", "")):
            return r
    cur = [r for r in res if r["current"]]
    return (cur or res)[0]


# ---------------------------------------------------------------------------
# 본문 (캐시)
# ---------------------------------------------------------------------------
def _load(target, id_):
    key = (target, id_)
    with _lock:
        hit = _cache.get(key)
        if hit and time.time() - hit[0] < CACHE_TTL:
            return hit[1]
    if target == "admrul":
        doc = _parse_admrul(_get("lawService.do", target="admrul", ID=id_))
    else:
        doc = _parse_law(_get("lawService.do", target="law", MST=id_))
    with _lock:
        _cache[key] = (time.time(), doc)
    return doc


def _parse_law(d):
    law = d.get("법령") or {}
    info = law.get("기본정보") or {}
    arts = []
    for u in _as_list((law.get("조문") or {}).get("조문단위")):
        if u.get("조문여부") != "조문":
            continue  # 편·장·절 제목은 제외
        no = str(u.get("조문번호", "")).strip()
        branch = str(u.get("조문가지번호", "") or "").strip()
        key = f"{no}의{branch}" if branch and branch != "0" else no
        lines = [_text(u.get("조문내용"))]
        for h in _as_list(u.get("항")):
            if isinstance(h, dict):
                lines.append(_text(h.get("항내용")))
                for ho in _as_list(h.get("호")):
                    if isinstance(ho, dict):
                        lines.append("  " + _text(ho.get("호내용")))
                        for mok in _as_list(ho.get("목")):
                            if isinstance(mok, dict):
                                lines.append("    " + _text(mok.get("목내용")))
        title = lines[0]
        arts.append({
            "no": key,
            "title": title.split(")")[0] + ")" if ")" in title[:60] else title[:60],
            "text": "\n".join(l for l in lines if l.strip()),
            "effective": u.get("조문시행일자", ""),
            "changed": u.get("조문변경여부") == "Y",
        })
    return {
        "name": info.get("법령명_한글", ""),
        "short": info.get("법령명약칭", ""),
        "kind": (info.get("법종구분") or {}).get("content", "") if isinstance(info.get("법종구분"), dict) else info.get("법종구분", ""),
        "effective": info.get("시행일자", ""),
        "promulgated": info.get("공포일자", ""),
        "articles": arts,
    }


# 행정규칙은 조문내용이 한 덩어리 문자열 → "제2-12조의2(" 같은 조문 머리로 나눈다
_ADM_HEAD = re.compile(r"(제(\d+(?:-\d+)*)조(?:의(\d+))?\()")


def _parse_admrul(d):
    svc = d.get("AdmRulService") or {}
    info = svc.get("행정규칙기본정보") or {}
    body = _text(svc.get("조문내용"))
    arts = []
    heads = list(_ADM_HEAD.finditer(body))
    for i, m in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(body)
        chunk = body[m.start():end]
        # 다음 장(章) 제목이 붙어 있으면 잘라낸다
        chunk = re.split(r"제\d+장\s", chunk)[0].strip()
        no = m.group(2) + (f"의{m.group(3)}" if m.group(3) else "")
        chunk = re.sub(r"\s*(?=[②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮])", "\n", chunk)
        chunk = re.sub(r"(?<=[가-힣]\.)\s*(?=\d{1,2}\.\s)", "\n  ", chunk)
        chunk = re.sub(r"(?<=[것음함임])(?=\d{1,2}\.\s)", "\n  ", chunk)
        arts.append({
            "no": no,
            "title": chunk.split(")")[0] + ")",
            "text": chunk,
            "effective": "",
            "changed": False,
        })
    return {
        "name": info.get("행정규칙명", ""),
        "short": "",
        "kind": info.get("행정규칙종류", ""),
        "effective": info.get("발령일자", ""),
        "promulgated": info.get("발령일자", ""),
        "articles": arts,
    }


# ---------------------------------------------------------------------------
# 조문 조회
# ---------------------------------------------------------------------------
def _norm_no(jo):
    """'174', '제174조', '174조의2', '2-12의2' → '174' / '174의2' / '2-12의2'"""
    s = (jo or "").replace(" ", "").replace("제", "").replace("조", "")
    m = re.fullmatch(r"(\d+(?:-\d+)*)(?:의(\d+))?", s)
    if not m:
        raise ValueError(f"조문 번호 형식을 확인하세요: {jo}")
    return m.group(1) + (f"의{m.group(2)}" if m.group(2) else "")


def article(law, jo=None, target=None, id_=None, keyword=None):
    """법령명(또는 id)과 조문 번호/키워드로 조문을 찾는다.

    jo 가 없으면 조문 목차(번호·제목)만 돌려준다.
    """
    if not id_:
        preset = next((p for p in PRESETS if p["name"] == law), None)
        target = target or (preset["target"] if preset else "law")
        picked = _pick(preset["query"] if preset else law, target)
        id_ = picked["id"]
    target = target or "law"
    doc = _load(target, id_)
    base = {k: doc[k] for k in ("name", "short", "kind", "effective", "promulgated")}
    base.update({"target": target, "id": id_,
                 "source": f"https://www.law.go.kr/{'행정규칙' if target == 'admrul' else '법령'}/{doc['name'].replace(' ', '')}"})

    if jo:
        no = _norm_no(jo)
        hits = [a for a in doc["articles"] if a["no"] == no]
        if not hits:
            raise LookupError(f"{doc['name']}에 제{no}조가 없습니다")
        return {**base, "articles": hits}
    if keyword:
        kw = keyword.strip()
        hits = [a for a in doc["articles"] if kw in a["text"]][:30]
        return {**base, "articles": hits, "keyword": kw}
    return {**base, "toc": [{"no": a["no"], "title": a["title"]} for a in doc["articles"]]}
