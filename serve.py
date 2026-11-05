import os
import json
import subprocess
import shutil
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

def run_kwcli_json(cmd_list):
    """
    [1순위 데이터 소스: 키움 공식 CLI]
    - 시스템 PATH 및 Render/로컬 표준 후보 경로에서 'kiwoomcli' 또는 'kwcli'를 자동 탐색하여 실행합니다.
    """
    if cmd_list and cmd_list[0] in ["kiwoomcli", "kwcli"]:
        binary_path = shutil.which("kiwoomcli") or shutil.which("kwcli")
        
        if not binary_path:
            candidates = [
                "/opt/render/.local/bin/kiwoomcli",
                "/opt/render/.local/bin/kwcli",
                os.path.expanduser("~/.local/bin/kiwoomcli"),
                os.path.expanduser("~/.local/bin/kwcli"),
                r"C:\Users\dhkim0521\.local\bin\kiwoomcli.exe",
                r"C:\Users\dhkim0521\.local\bin\kwcli.exe"
            ]
            for path in candidates:
                if os.path.exists(path):
                    binary_path = path
                    break
        
        if binary_path:
            cmd_list[0] = binary_path
        else:
            cmd_list[0] = "kiwoomcli"

    try:
        result = subprocess.run(cmd_list, capture_output=True, text=True, check=True, encoding='utf-8')
        if result.stdout.strip():
            return json.loads(result.stdout)
    except Exception as e:
        print(f"[키움 CLI 실행 예외]: {e}")
    return None

def get_stock_data_with_cli_and_fallback(code="144510"):
    price, ratio, volume = "10,270", "+2.60%", "15,584"
    success = False

    data = run_kwcli_json(["kwcli", "domestic", "stocks", "info", f"--code={code}"])
    if data:
        try:
            p_val = int(data.get("price", data.get("current_price", data.get("clpr", 0))))
            chg_val = float(data.get("change_rate", data.get("rate", data.get("vsrt", 0))))
            vol_val = int(data.get("volume", data.get("acml_vol", 0)))
            if p_val > 0:
                price = f"{p_val:,.0f}"
                ratio = f"{'+' if chg_val > 0 else ''}{chg_val:.2f}%"
                volume = f"{vol_val:,}"
                success = True
        except Exception:
            pass

    if not success:
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
        except Exception as e:
            print(f"야후 파이낸스 주가 조회 오류: {e}")

    return price, ratio, volume

def get_market_indices_with_cli_and_fallback():
    kospi_val, kospi_ratio = "2,560.12", "+0.45%"
    kosdaq_val, kosdaq_ratio = "742.80", "+0.15%"
    kq26_val, kq26_ratio = "7,264.11", "-1.42%"
    success = False

    idx_data = run_kwcli_json(["kwcli", "domestic", "market", "index"])
    if idx_data:
        try:
            if "kospi" in idx_data and "kosdaq" in idx_data:
                kospi_val = f"{float(idx_data['kospi'].get('value', idx_data['kospi'].get('prpr', 0))):,.2f}"
                kospi_chg = float(idx_data['kospi'].get('change_rate', idx_data['kospi'].get('vsrt', 0)))
                kospi_ratio = f"{'+' if kospi_chg > 0 else ''}{kospi_chg:.2f}%"

                kosdaq_val = f"{float(idx_data['kosdaq'].get('value', idx_data['kosdaq'].get('prpr', 0))):,.2f}"
                kosdaq_chg = float(idx_data['kosdaq'].get('change_rate', idx_data['kosdaq'].get('vsrt', 0)))
                kosdaq_ratio = f"{'+' if kosdaq_chg > 0 else ''}{kosdaq_chg:.2f}%"

                if "pharmacy" in idx_data:
                    kq26_val = f"{float(idx_data['pharmacy'].get('value', 0)):,.2f}"
                    kq26_chg = float(idx_data['pharmacy'].get('change_rate', 0))
                    kq26_ratio = f"{'+' if kq26_chg > 0 else ''}{kq26_chg:.2f}%"
                success = True
        except Exception:
            pass

    if not success:
        try:
            yahoo_tickers = {
                "kospi": "^KS11",
                "kosdaq": "^KQ11",
                "pharmacy": "^KQ26"
            }

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
        "5d": {
            "foreign": "+12,400",
            "organ": "-8,300",
            "personal": "-4,100"
        }
    }
    success = False

    cli_inv = run_kwcli_json(["kwcli", "domestic", "stocks", "investor-by-stock", f"--code={code}"])
    if cli_inv and isinstance(cli_inv, dict):
        try:
            frn = int(cli_inv.get("foreign", cli_inv.get("frn_net_qty", 0)))
            org = int(cli_inv.get("organ", cli_inv.get("org_net_qty", 0)))
            per = int(cli_inv.get("personal", cli_inv.get("prsn_net_qty", -(frn + org))))
            if frn != 0 or org != 0:
                investor["foreign"] = f"{'+' if frn > 0 else ''}{frn:,}"
                investor["organ"] = f"{'+' if org > 0 else ''}{org:,}"
                investor["personal"] = f"{'+' if per > 0 else ''}{per:,}"
                success = True
        except Exception:
            pass

    if not success:
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
                                        recent_days_data.append({
                                            "organ": int(org_str),
                                            "foreign": int(frn_str)
                                        })
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
    
    client_id = (
        os.getenv("X-NCP-APIGW-API-KEY-ID") or 
        os.getenv("NCP_API_KEY_ID") or 
        os.getenv("NAVER_CLIENT_ID")
    )
    client_secret = (
        os.getenv("X-NCP-APIGW-API-KEY") or 
        os.getenv("NCP_API_KEY") or 
        os.getenv("NAVER_CLIENT_SECRET")
    )
    
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
                    news_list.append({
                        "date": date_formatted,
                        "title": clean_title,
                        "publisher": "네이버뉴스",
                        "linkUrl": link
                    })

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
                title = parts[0]
                publisher = parts[1]

            date_formatted = now.strftime("%m/%d")
            is_recent = True
            try:
                if hasattr(entry, "published_parsed") and entry.published_parsed:
                    dt = datetime(*entry.published_parsed[:6])
                    diff_hours = (now - dt).total_seconds() / 3600
                    date_formatted = dt.strftime("%m/%d")
                    if diff_hours > 48:
                        is_recent = False
            except Exception:
                pass

            if is_recent:
                news_list.append({
                    "date": date_formatted,
                    "title": title,
                    "publisher": publisher,
                    "linkUrl": link
                })

                if len(news_list) >= display:
                    break
    except Exception as e:
        print(f"구글 뉴스 수집 예외: {e}")

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
    nbi_keyword_query = "Amgen OR Gilead OR Vertex OR Regeneron OR Moderna OR Biogen"
    nbi_news = fetch_naver_news_api(nbi_keyword_query, 3)

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

def run_server():
    PORT = int(os.environ.get("PORT", 10000))
    Handler = http.server.SimpleHTTPRequestHandler
    with socketserver.TCPServer(("", PORT), Handler) as httpd:
        print(f"Serving HTTP on port {PORT}...")
        httpd.serve_forever()

if __name__ == "__main__":
    generate_data()
    run_server()