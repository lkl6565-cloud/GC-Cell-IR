import os
import requests
from flask import Flask, render_template, jsonify
import yfinance as yf
from bs4 import BeautifulSoup
import xml.etree.ElementTree as ET

app = Flask(__name__)

# Render Environment에 등록된 API 인증 정보 불러오기
KIWOOM_APP_KEY = os.environ.get("KIWOOM_APP_KEY")
KIWOOM_SECRET_KEY = os.environ.get("KIWOOM_SECRET_KEY")
KIWOOM_PASSWORD = os.environ.get("KIWOOM_PASSWORD", "")
NAVER_CLIENT_ID = os.environ.get("NAVER_CLIENT_ID")
NAVER_CLIENT_SECRET = os.environ.get("NAVER_CLIENT_SECRET")

def get_kiwoom_token():
    """키움증권 REST API 접근 토큰 발급"""
    try:
        if not KIWOOM_APP_KEY or not KIWOOM_SECRET_KEY:
            return None
        auth_url = "https://api.kiwoom.com/oauth2/token"
        payload = {
            "grant_type": "client_credentials",
            "appkey": KIWOOM_APP_KEY,
            "secretkey": KIWOOM_SECRET_KEY
        }
        res = requests.post(auth_url, json=payload, timeout=3)
        if res.status_code == 200:
            return res.json().get("access_token")
    except Exception as e:
        print(f"[키움 토큰 발급 실패]: {e}")
    return None

def fetch_nbi_news_rss():
    """나스닥 바이오(NBI) 뉴스: 구글 뉴스 RSS 연동"""
    news_list = []
    try:
        rss_url = "https://news.google.com/rss/search?q=Nasdaq+Biotechnology+Index+OR+NBI+biotech&hl=en-US&gl=US&ceid=US:en"
        res = requests.get(rss_url, timeout=3)
        if res.status_code == 200:
            root = ET.fromstring(res.content)
            items = root.findall(".//item")
            for item in items[:5]:
                title = item.find("title").text if item.find("title") is not None else ""
                link = item.find("link").text if item.find("link") is not None else ""
                pub_date = item.find("pubDate").text if item.find("pubDate") is not None else ""
                news_list.append({"title": title, "link": link, "date": pub_date})
    except Exception as e:
        print(f"[구글 RSS NBI 뉴스 수집 오류]: {e}")
    return news_list

def fetch_market_index(market_type="kospi"):
    """
    시장 지수 및 매크로 지표 수집
    - 코스피/코스닥: 1차 키움 REST API, 2차 야후 파이낸스
    - 환율: 야후 파이낸스 (USDKRW=X)
    - NBI: 야후 파이낸스(^NBI) + 구글 뉴스 RSS
    """
    if market_type == "usd":
        try:
            df = yf.Ticker("USDKRW=X").history(period="2d")
            if not df.empty:
                current_price = float(df['Close'].iloc[-1])
                prev_price = float(df['Close'].iloc[-2]) if len(df) > 1 else current_price
                change_rate = ((current_price - prev_price) / prev_price) * 100
                return round(current_price, 2), round(change_rate, 2)
        except Exception as e:
            print(f"[환율 수집 실패]: {e}")
        return 0.0, 0.0

    if market_type == "nbi":
        nbi_price, nbi_rate = 0.0, 0.0
        try:
            df = yf.Ticker("^NBI").history(period="2d")
            if not df.empty:
                nbi_price = float(df['Close'].iloc[-1])
                prev_price = float(df['Close'].iloc[-2]) if len(df) > 1 else nbi_price
                nbi_rate = ((nbi_price - prev_price) / prev_price) * 100
        except Exception as e:
            print(f"[NBI 지수 수집 실패]: {e}")
        
        nbi_news = fetch_nbi_news_rss()
        return round(nbi_price, 2), round(nbi_rate, 2), nbi_news

    # 코스피 / 코스닥 1차 키움 API 연동 시도
    try:
        token = get_kiwoom_token()
        if token:
            code_map = {"kospi": "001", "kosdaq": "301"}
            headers = {"Authorization": f"Bearer {token}", "appkey": KIWOOM_APP_KEY}
            api_url = f"https://api.kiwoom.com/v1/market/index?code={code_map.get(market_type, '001')}"
            res = requests.get(api_url, headers=headers, timeout=3)
            if res.status_code == 200:
                data = res.json()
                return float(data.get("price", 0.0)), float(data.get("rate", 0.0))
        raise Exception("키움 지수 API 연결 실패")
    except Exception as kiwoom_err:
        # 2차 Fallback: 야후 파이낸스
        ticker_symbol = "^KS11" if market_type == "kospi" else "^KQ11"
        try:
            df = yf.Ticker(ticker_symbol).history(period="2d")
            if not df.empty:
                current_price = float(df['Close'].iloc[-1])
                prev_price = float(df['Close'].iloc[-2]) if len(df) > 1 else current_price
                change_rate = ((current_price - prev_price) / prev_price) * 100
                return round(current_price, 2), round(change_rate, 2)
        except Exception as yf_err:
            print(f"[{market_type.upper()} 야후 Fallback 실패]: {yf_err}")
    return 0.0, 0.0

def fetch_naver_supply():
    """네이버 금융 지씨셀(144510) 수급 수집"""
    try:
        url = "https://finance.naver.com/item/main.naver?code=144510"
        headers = {"User-Agent": "Mozilla/5.0"}
        res = requests.get(url, headers=headers, timeout=3)
        if res.status_code == 200:
            soup = BeautifulSoup(res.text, 'html.parser')
            foreign_net = soup.select_one(".foreign .value") or "-"
            institution_net = soup.select_one(".institution .value") or "-"
            
            return {
                "foreign": {"net": foreign_net.text.strip() if hasattr(foreign_net, 'text') else "-", "recent": "-"},
                "institution": {"net": institution_net.text.strip() if hasattr(institution_net, 'text') else "-", "recent": "-"},
                "retail": {"net": "-", "recent": "-"}
            }
    except Exception as e:
        print(f"[네이버 수급 수집 오류]: {e}")
    
    return {
        "foreign": {"net": "-", "recent": "-"},
        "institution": {"net": "-", "recent": "-"},
        "retail": {"net": "-", "recent": "-"}
    }

def fetch_gccell_news_naver_api():
    """지씨셀(144510) 뉴스: 네이버 오픈 API 연동"""
    news_list = []
    if not NAVER_CLIENT_ID or not NAVER_CLIENT_SECRET:
        return news_list

    try:
        url = "https://openapi.naver.com/v1/search/news.json"
        headers = {
            "X-Naver-Client-Id": NAVER_CLIENT_ID,
            "X-Naver-Client-Secret": NAVER_CLIENT_SECRET
        }
        params = {
            "query": "지씨셀",
            "display": 5,
            "sort": "date"
        }
        res = requests.get(url, headers=headers, params=params, timeout=3)
        if res.status_code == 200:
            items = res.json().get("items", [])
            for item in items:
                title = item.get("title", "").replace("<b>", "").replace("</b>", "").replace("&quot;", '"')
                link = item.get("link", "")
                pub_date = item.get("pubDate", "")
                news_list.append({"title": title, "link": link, "date": pub_date})
    except Exception as e:
        print(f"[네이버 뉴스 API 호출 실패]: {e}")
        
    return news_list

def fetch_gccell_data():
    """지씨셀 통합 데이터 반환 (주가: 키움/야후, 수급: 네이버, 뉴스: 네이버 API)"""
    current_price, change_rate = 0.0, 0.0
    try:
        token = get_kiwoom_token()
        if token:
            headers = {"Authorization": f"Bearer {token}", "appkey": KIWOOM_APP_KEY}
            api_url = "https://api.kiwoom.com/v1/stock/stock-info?code=144510"
            res = requests.get(api_url, headers=headers, timeout=3)
            if res.status_code == 200:
                data = res.json()
                current_price = float(data.get("price", 0.0))
                change_rate = float(data.get("rate", 0.0))
        if current_price == 0.0:
            raise Exception("키움 주가 미응답")
    except Exception:
        try:
            df = yf.Ticker("144510.KQ").history(period="2d")
            if not df.empty:
                current_price = float(df['Close'].iloc[-1])
                prev_price = float(df['Close'].iloc[-2]) if len(df) > 1 else current_price
                change_rate = ((current_price - prev_price) / prev_price) * 100
        except Exception as yf_err:
            print(f"[지씨셀 야후 주가 수집 실패]: {yf_err}")

    supply_data = fetch_naver_supply()
    news_data = fetch_gccell_news_naver_api()

    return {
        "price": round(current_price, 2),
        "rate": round(change_rate, 2),
        "supply": supply_data,
        "news": news_data
    }

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/data', methods=['GET', 'POST'])
@app.route('/api/refresh', methods=['GET', 'POST'])
@app.route('/data.json', methods=['GET', 'POST'])
def api_data():
    kospi_price, kospi_rate = fetch_market_index("kospi")
    kosdaq_price, kosdaq_rate = fetch_market_index("kosdaq")
    usd_price, usd_rate = fetch_market_index("usd")
    nbi_price, nbi_rate, nbi_news = fetch_market_index("nbi")
    
    gccell_data = fetch_gccell_data()
    
    return jsonify({
        "kospi": {"price": kospi_price, "rate": kospi_rate},
        "kosdaq": {"price": kosdaq_price, "rate": kosdaq_rate},
        "usd": {"price": usd_price, "rate": usd_rate},
        "nbi": {"price": nbi_price, "rate": nbi_rate, "news": nbi_news},
        "gccell": gccell_data
    })

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)