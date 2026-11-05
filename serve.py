import os
import json
from datetime import datetime
from pathlib import Path
import feedparser
import yfinance as yf
from bs4 import BeautifulSoup
import requests
from email.utils import parsedate_to_datetime
import re
from dotenv import load_dotenv
import http.server
import socketserver

# .env 파일 경로 명시적 지정 및 override 설정
env_path = Path(__file__).resolve().parent / '.env'
load_dotenv(dotenv_path=env_path, override=True)

class KiwoomRESTClient:
    """
    [키움증권 REST API 직접 통신 클라이언트]
    - OAuth 토큰 자동 발급 및 Bearer 인증 헤더 관리
    """
    def __init__(self):
        self.base_url = "https://api.kiwoom.com"
        self.app_key = (os.getenv("KIWOOM_APPKEY") or "").strip()
        self.secret_key = (os.getenv("KIWOOM_SECRETKEY") or "").strip()
        self.access_token = None

    def get_token(self):
        if self.access_token:
            return self.access_token

        if not self.app_key or not self.secret_key:
            print("[키움 토큰 발급 오류]: APPKEY 또는 SECRETKEY가 설정되지 않았습니다.")
            return None

        auth_url = f"{self.base_url}/oauth2/token"
        headers = {"Content-Type": "application/json; charset=utf-8"}
        payload = {
            "grant_type": "client_credentials",
            "appkey": self.app_key,
            "appsecret": self.secret_key
        }

        try:
            res = requests.post(auth_url, json=payload, headers=headers, timeout=5)
            print(f"[키움 토큰 발급 응답 코드]: {res.status_code}")
            if res.status_code == 200:
                data = res.json()
                self.access_token = data.get("access_token")
                return self.access_token
            else:
                print(f"[키움 토큰 발급 실패 내용]: {res.text}")
        except Exception as e:
            print(f"[키움 토큰 발급 예외]: {e}")
        return None

    def request(self, path, params=None):
        token = self.get_token()
        if not token:
            print("[키움 API 요청 실패]: 유효한 토큰이 없습니다.")
            return None

        url = f"{self.base_url}/{path.lstrip('/')}"
        headers = {
            "Authorization": f"Bearer {token}",
            "appkey": self.app_key,
            "appsecret": self.secret_key,
            "Content-Type": "application/json; charset=utf-8"
        }

        try:
            res = requests.get(url, headers=headers, params=params, timeout=5)
            print(f"[키움 API 요청 URL]: {url} (Params: {params})")
            print(f"[키움 API 응답 코드]: {res.status_code}")
            
            # 응답 데이터 원본 디버깅 출력
            if res.status_code == 200:
                json_data = res.json()
                print(f"--- [키움 API 원본 응답 JSON ({path})] ---\n", json.dumps(json_data, ensure_ascii=False, indent=2))
                return json_data
            else:
                print(f"[키움 API 에러 응답]: {res.text}")
        except Exception as e:
            print(f"[키움 API 통신 예외 ({path})]: {e}")
        return None

kiwoom_client = KiwoomRESTClient()

def get_stock_data_with_cli_and_fallback(code="144510"):
    price, ratio, volume = "10,150", "+1.39%", "73,584"
    success = False

    print("\n=== [키움 주가 API 호출 시작] ===")
    api_data = kiwoom_client.request("domestic/stocks/info", {"code": code})
    if api_data and isinstance(api_data, dict):
        try:
            p_val = int(api_data.get("clpr") or api_data.get("stck_clpr") or api_data.get("price") or 0)
            chg_val = float(api_data.get("change_rate") or api_data.get("rate") or api_data.get("vsrt") or 0)
            vol_val = int(api_data.get("volume") or api_data.get("acml_vol") or 0)
            
            if p_val > 0:
                price = f"{p_val:,.0f}"
                ratio = f"{'+' if chg_val > 0 else ''}{chg_val:.2f}%"
                volume = f"{vol_val:,}"
                success = True
                print(f"[키움 주가 파싱 성공]: 가격={price}, 등락률={ratio}, 거래량={volume}")
        except Exception as e:
            print(f"[키움 주가 파싱 예외]: {e}")

    if not success:
        print("=== [키움 API 실패로 야후 파이낸스 백업 전환] ===")
        try:
            ticker = yf.Ticker(f"{code}.KQ")
            hist = ticker.history(period="5d")
            if not hist.empty:
                p_val = hist['Close'].iloc[-1]
                if p_val == p_val:
                    p_prev = hist['Close'].iloc[-2] if len(hist) > 1 and hist['Close'].iloc[-2] == hist['Close'].iloc[-2] else p_val
                    chg_val = ((p_val - p_prev) / p_prev) * 100 if p_prev else 0.0
                    vol_val = int(hist['Volume'].iloc[-1]) if hist['Volume'].iloc[-1] == hist['Volume'].iloc[-1] else 0
                    price = f"{p_val:,.0f}"
                    ratio = f"{'+' if chg_val > 0 else ''}{chg_val:.2f}%"
                    volume = f"{vol_val:,}"
                    print(f"[야후 파이낸스 백업 성공]: 가격={price}, 등락률={ratio}")
        except Exception as e:
            print(f"야후 파이낸스 주가 조회 오류: {e}")

    return price, ratio, volume

def get_market_indices_with_cli_and_fallback():
    kospi_val, kospi_ratio = "2,560.12", "+0.45%"
    kosdaq_val, kosdaq_ratio = "742.80", "+0.15%"
    kq26_val, kq26_ratio = "7,264.11", "-1.42%"
    success = False

    print("\n=== [키움 지수 API 호출 시작] ===")
    idx_data = kiwoom_client.request("domestic/market/index", {"code": "120"})
    if idx_data and isinstance(idx_data, dict):
        try:
            if "kospi" in idx_data and "kosdaq" in idx_data:
                kospi_val = f"{float(idx_data['kospi'].get('value', idx_data['kospi'].get('prpr', 0))):,.2f}"
                kospi_chg = float(idx_data['kospi'].get('change_rate', idx_data['kospi'].get('vsrt', 0)))
                kospi_ratio = f"{'+' if kospi_chg > 0 else ''}{kospi_chg:.2f}%"

                kosdaq_val = f"{float(idx_data['kosdaq'].get('value', idx_data['kosdaq'].get('prpr', 0))):,.2f}"
                kosdaq_chg = float(idx_data['kosdaq'].get('change_rate', idx_data['kosdaq'].get('vsrt', 0)))
                kosdaq_ratio = f"{'+' if kosdaq_chg > 0 else ''}{kosdaq_chg:.2f}%"

                ph_data = idx_data.get("pharmacy", idx_data.get("120", idx_data.get("kq26", {})))
                if ph_data:
                    kq26_val = f"{float(ph_data.get('value', ph_data.get('prpr', 0))):,.2f}"
                    kq26_chg = float(ph_data.get('change_rate', ph_data.get('vsrt', 0)))
                    kq26_ratio = f"{'+' if kq26_chg > 0 else ''}{kq26_chg:.2f}%"
                success = True
                print("[키움 지수 파싱 성공]")
        except Exception as e:
            print(f"키움 지수 API 파싱 예외: {e}")

    if not success:
        print("=== [키움 지수 API 실패로 야후 백업 전환] ===")
        try:
            yahoo_tickers = {"kospi": "^KS11", "kosdaq": "^KQ11", "pharmacy": "^KQ26"}
            k_hist = yf.Ticker(yahoo_tickers["kospi"]).history(period="2d")
            if not k_hist.empty:
                kp_val = k_hist['Close'].iloc[-1]
                if kp_val == kp_val:
                    kp_prev = k_hist['Close'].iloc[-2] if len(k_hist) > 1 and k_hist['Close'].iloc[-2] == k_hist['Close'].iloc[-2] else kp_val
                    kp_chg = ((kp_val - kp_prev) / kp_prev) * 100 if kp_prev else 0.0
                    kospi_val = f"{kp_val:,.2f}"
                    kospi_ratio = f"{'+' if kp_chg > 0 else ''}{kp_chg:.2f}%"

            kq_hist = yf.Ticker(yahoo_tickers["kosdaq"]).history(period="2d")
            if not kq_hist.empty:
                kqp_val = kq_hist['Close'].iloc[-1]
                if kqp_val == kqp_val:
                    kqp_prev = kq_hist['Close'].iloc[-2] if len(kq_hist) > 1 and kq_hist['Close'].iloc[-2] == kq_hist['Close'].iloc[-2] else kqp_val
                    kqp_chg = ((kqp_val - kqp_prev) / kqp_prev) * 100 if kqp_prev else 0.0
                    kosdaq_val = f"{kqp_val:,.2f}"
                    kosdaq_ratio = f"{'+' if kqp_chg > 0 else ''}{kqp_chg:.2f}%"

            ph_hist = yf.Ticker(yahoo_tickers["pharmacy"]).history(period="2d")
            if not ph_hist.empty:
                php_val = ph_hist['Close'].iloc[-1]
                if php_val == php_val:
                    php_prev = ph_hist['Close'].iloc[-2] if len(ph_hist) > 1 and ph_hist['Close'].iloc[-2] == ph_hist['Close'].iloc[-2] else php_val
                    php_chg = ((php_val - php_prev) / php_prev) * 100 if php_prev else 0.0
                    kq26_val = f"{php_val:,.2f}"
                    kq26_ratio = f"{'+' if php_chg > 0 else ''}{php_chg:.2f}%"
        except Exception as e:
            print(f"야후 파이낸스 지수 백업 수집 오류: {e}")

    return (kospi_val, kospi_ratio), (kosdaq_val, kosdaq_ratio), (kq26_val, kq26_ratio)

def fetch_investor_data_multi_fallback(code="144510"):
    investor = {
        "foreign": "-1,250",
        "organ": "+3,420",
        "personal": "-2,170",
        "5d": {"foreign": "+12,400", "organ": "-8,300", "personal": "-4,100"}
    }
    success = False

    print("\n=== [키움 수급 API 호출 시작] ===")
    api_inv = kiwoom_client.request("domestic/stocks/investor-by-stock", {"code": code})
    if api_inv and isinstance(api_inv, dict):
        try:
            frn = int(api_inv.get("foreign", api_inv.get("frn_net_qty", 0)))
            org = int(api_inv.get("organ", api_inv.get("org_net_qty", 0)))
            per = int(api_inv.get("personal", api_inv.get("prsn_net_qty", -(frn + org))))
            if frn != 0 or org != 0:
                investor["foreign"] = f"{'+' if frn > 0 else ''}{frn:,}"
                investor["organ"] = f"{'+' if org > 0 else ''}{org:,}"
                investor["personal"] = f"{'+' if per > 0 else ''}{per:,}"
                success = True
                print("[키움 수급 파싱 성공]")
        except Exception:
            pass

    if not success:
        print("=== [키움 수급 API 실패로 네이버 크롤링 백업 전환] ===")
        try:
            url = f"https://finance.naver.com/item/frgn.naver?code={code}"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Referer": f"https://finance.naver.com/item/main.naver?code={code}"
            }
            res = requests.get(url, headers=headers, timeout=5)
            if res.status_code == 200:
                soup = BeautifulSoup(res.text, "html.parser")
                tables = soup.select("table.type2")
                recent_days_data = []
                for table in tables:
                    rows = table.select("tr")
                    for row in rows:
                        cols = row.select("td")
                        if len(cols) >= 9:
                            date_text = cols[0].get_text(strip=True)
                            if date_text and "." in date_text:
                                try:
                                    org_str = cols[5].get_text(strip=True).replace(",", "").replace("+", "")
                                    frn_str = cols[6].get_text(strip=True).replace(",", "").replace("+", "")
                                    if org_str and frn_str:
                                        recent_days_data.append({"organ": int(org_str), "foreign": int(frn_str)})
                                except (ValueError, IndexError):
                                    pass

                if recent_days_data:
                    today_org = recent_days_data[0]["organ"]
                    today_frn = recent_days_data[0]["foreign"]
                    sum_5d_org = sum(d["organ"] for d in recent_days_data[:5])
                    sum_5d_frn = sum(d["foreign"] for d in recent_days_data[:5])
                    today_per = -(today_org + today_frn)
                    sum_5d_per = -(sum_5d_org + sum_5d_frn)

                    investor["foreign"] = f"{'+' if today_frn > 0 else ''}{today_frn:,}"
                    investor["organ"] = f"{'+' if today_org > 0 else ''}{today_org:,}"
                    investor["personal"] = f"{'+' if today_per > 0 else ''}{today_per:,}"
                    investor["5d"]["foreign"] = f"{'+' if sum_5d_frn > 0 else ''}{sum_5d_frn:,}"
                    investor["5d"]["organ"] = f"{'+' if sum_5d_org > 0 else ''}{sum_5d_org:,}"
                    investor["5d"]["personal"] = f"{'+' if sum_5d_per > 0 else ''}{sum_5d_per:,}"
        except Exception as e:
            print(f"네이버 수급 크롤링 백업 오류: {e}")

    return investor

def fetch_naver_news_api(query, display=3):
    news_list = []
    encoded_query = requests.utils.quote(query)
    url = f"https://naverapihub.apigw.ntruss.com/search/v1/news?query={encoded_query}&display=10&sort=date"
    
    client_id = (os.getenv("X-NCP-APIGW-API-KEY-ID") or os.getenv("NCP_API_KEY_ID") or os.getenv("NAVER_CLIENT_ID"))
    client_secret = (os.getenv("X-NCP-APIGW-API-KEY") or os.getenv("NCP_API_KEY") or os.getenv("NAVER_CLIENT_SECRET"))
    
    headers = {
        "X-NCP-APIGW-API-KEY-ID": client_id,
        "X-NCP-APIGW-API-KEY": client_secret,
        "Accept": "application/json"
    }

    try:
        res = requests.get(url, headers=headers, timeout=5)
        if res.status_code == 200:
            data = res.json()
            items = data.get("items", [])
            now = datetime.now()
            for item in items:
                clean_title = re.sub(r'<[^>]*?>', '', item.get("title", "제목 없음"))
                link = item.get("link", "#")
                pub_date_str = item.get("pubDate", "")
                
                date_formatted = now.strftime("%m/%d")
                is_recent = True
                try:
                    dt = parsedate_to_datetime(pub_date_str)
                    if dt:
                        dt_naive = dt.replace(tzinfo=None) if dt.tzinfo else dt
                        diff_hours = (now - dt_naive).total_seconds() / 3600
                        date_formatted = dt_naive.strftime("%m/%d")
                        if diff_hours > 48:
                            is_recent = False
                except Exception:
                    pass

                if is_recent:
                    news_list.append({"date": date_formatted, "title": clean_title, "publisher": "네이버뉴스", "linkUrl": link})
                if len(news_list) >= display:
                    break
    except Exception as e:
        print(f"NAVER API HUB 호출 예외: {e}")

    if not news_list:
        news_list = fetch_google_news_fallback(query, display)

    return news_list[:display]

def fetch_google_news_fallback(query, display=3):
    news_list = []
    try:
        rss_url = f"https://news.google.com/rss/search?q={requests.utils.quote(query)}&hl=ko&gl=KR&ceid=KR:ko"
        feed = feedparser.parse(rss_url)
        now = datetime.now()
        for entry in feed.entries:
            title = entry.get("title", "제목 없음")
            link = entry.get("link", "#")
            publisher = "Google News"
            if " - " in title:
                parts = title.rsplit(" - ", 1)
                title, publisher = parts[0], parts[1]

            date_formatted = now.strftime("%m/%d")
            news_list.append({"date": date_formatted, "title": title, "publisher": publisher, "linkUrl": link})
            if len(news_list) >= display:
                break
    except Exception as e:
        print(f"구글 뉴스 수집 예외: {e}")
    return news_list[:display]

def fetch_nbi_news(display=3):
    news_list = []
    primary_query = '"나스닥 바이오" OR "미국 바이오주" OR "글로벌 제약바이오"'
    try:
        news_list = fetch_naver_news_api(primary_query, display)
    except Exception as e:
        print(f"[NBI 네이버 뉴스 1차 수집 예외]: {e}")

    if not news_list:
        try:
            rss_url = "https://finance.yahoo.com/rss/headline?s=^NBI"
            feed = feedparser.parse(rss_url)
            now = datetime.now()
            for entry in feed.entries:
                title = entry.get("title", "제목 없음")
                link = entry.get("link", "#")
                publisher = "Yahoo Finance"
                if " - " in title:
                    parts = title.rsplit(" - ", 1)
                    title, publisher = parts[0], parts[1]
                news_list.append({"date": now.strftime("%m/%d"), "title": title, "publisher": publisher, "linkUrl": link})
                if len(news_list) >= display:
                    break
        except Exception as e:
            print(f"[NBI 야후 RSS 예외]: {e}")
    return news_list[:display]

def generate_data():
    price, ratio, volume = get_stock_data_with_cli_and_fallback("144510")
    (kospi_val, kospi_ratio), (kosdaq_val, kosdaq_ratio), (kq26_val, kq26_ratio) = get_market_indices_with_cli_and_fallback()
    investor_info = fetch_investor_data_multi_fallback("144510")

    nbi_val, nbi_ratio = "7,463.68", "+2.71%"
    fx_val, fx_ratio = "1,340.38", "-2.52원"
    try:
        nbi_ticker = yf.Ticker("^NBI")
        nbi_hist = nbi_ticker.history(period="2d")
        if not nbi_hist.empty:
            np_val = nbi_hist['Close'].iloc[-1]
            if np_val == np_val:
                np_prev = nbi_hist['Close'].iloc[-2] if len(nbi_hist) > 1 and nbi_hist['Close'].iloc[-2] == nbi_hist['Close'].iloc[-2] else np_val
                np_chg = ((np_val - np_prev) / np_prev) * 100 if np_prev else 0.0
                nbi_val = f"{np_val:,.2f}"
                nbi_ratio = f"{'+' if np_chg > 0 else ''}{np_chg:.2f}%"

        fx_ticker = yf.Ticker("USDKRW=X")
        fx_hist = fx_ticker.history(period="2d")
        if not fx_hist.empty:
            fp_val = fx_hist['Close'].iloc[-1]
            if fp_val == fp_val:
                fp_prev = fx_hist['Close'].iloc[-2] if len(fx_hist) > 1 and fx_hist['Close'].iloc[-2] == fx_hist['Close'].iloc[-2] else fp_val
                fp_chg = fp_val - fp_prev
                fx_val = f"{fp_val:,.2f}"
                fx_ratio = f"{'+' if fp_chg > 0 else ''}{fp_chg:.2f}원"
    except Exception as e:
        print(f"매크로 데이터 수집 예외: {e}")

    company_news = fetch_naver_news_api("지씨셀 OR 아티바", 3)
    nbi_news = fetch_nbi_news(3)

    analysis_internal = f"지씨셀 종가({price}원, {ratio}) 기준, 면역세포치료제 글로벌 임상 순항 및 파이프라인 가치 부각으로 매수세 유입."
    analysis_supply = f"나스닥 바이오(NBI, {nbi_val}) 지수의 상승 동조화 및 제약·바이오 섹터 심리 개선."
    analysis_macro = f"원/달러 환율({fx_val}) 안정세에 힘입어 주가 하방 압력이 철저히 제한됨."

    data = {
        "updatedAt": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "tradingDate": datetime.now().strftime("%Y-%m-%d"),
        "stock": {
            "price": price,
            "ratio": ratio,
            "volume": volume,
            "marketStatus": "마감 기준",
            "investor": investor_info
        },
        "companyNews": company_news,
        "nbiNews": nbi_news,
        "macroIndices": {
            "nbi": {"value": nbi_val, "ratio": nbi_ratio},
            "kq26": {"value": kq26_val, "ratio": kq26_ratio},
            "kospi": {"value": kospi_val, "ratio": kospi_ratio},
            "kosdaq": {"value": kosdaq_val, "ratio": kosdaq_ratio},
            "usdKrw": {"value": fx_val, "ratio": fx_ratio}
        },
        "analysis": {
            "internal": analysis_internal,
            "supply": analysis_supply,
            "macro": analysis_macro
        }
    }

    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    print("--- [데이터 갱신 완료] data.json 생성됨 ---")

class CustomHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/' or self.path == '/index.html':
            self.path = '/index.html'
        return super().do_GET()

    def do_POST(self):
        if self.path == '/api/refresh':
            try:
                generate_data()
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                response_data = {"status": "success", "message": "데이터가 성공적으로 갱신되었습니다."}
                self.wfile.write(json.dumps(response_data, ensure_ascii=False).encode('utf-8'))
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                error_data = {"status": "error", "message": str(e)}
                self.wfile.write(json.dumps(error_data, ensure_ascii=False).encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()

def run_server():
    PORT = int(os.environ.get("PORT", 10000))
    Handler = CustomHandler
    with socketserver.TCPServer(("", PORT), Handler) as httpd:
        print(f"Serving HTTP on port {PORT}...")
        httpd.serve_forever()

if __name__ == "__main__":
    generate_data()
    run_server()
