import os
from flask import Flask, render_template, jsonify
import yfinance as yf

app = Flask(__name__)

def fetch_market_index(market_type="kospi"):
    """
    [데이터 소스 조건]
    - 코스피: 키움증권 REST API (1차) / 야후 파이낸스 ^KS11 (2차 Fallback)
    - 코스닥: 키움증권 REST API (1차) / 야후 파이낸스 ^KQ11 (2차 Fallback)
    - 원/달러 환율: 야후 파이낸스 USDKRW=X
    - 나스닥 바이오(NBI): 야후 파이낸스 ^NBI
    """
    try:
        ticker_map = {
            "kospi": "^KS11",
            "kosdaq": "^KQ11",
            "usd": "USDKRW=X",
            "nbi": "^NBI"
        }
        ticker_symbol = ticker_map.get(market_type, "^KS11")
        df = yf.Ticker(ticker_symbol).history(period="2d")
        
        if not df.empty:
            current_price = float(df['Close'].iloc[-1])
            prev_price = float(df['Close'].iloc[-2]) if len(df) > 1 else current_price
            change_rate = ((current_price - prev_price) / prev_price) * 100
            return round(current_price, 2), round(change_rate, 2)
    except Exception as e:
        print(f"[{market_type.upper()} 수집 실패]: {e}")
        
    return 0.0, 0.0

def fetch_gccell_data():
    """
    [데이터 소스 조건]
    - 지씨셀(144510) 주가 및 투자자별 수급 현황
    - 1차: 키움증권 REST API (종목 시세 및 투자자별 매매동향)
    - 2차(Fallback): 야후 파이낸스 (144510.KQ) 주가 조회 및 수급 기본값 처리
    """
    try:
        # [키움증권 API 연동 구간 - 종목코드 144510]
        # kiwoom_price = kiwoom.get_stock_price("144510")
        # kiwoom_supply = kiwoom.get_investor_trend("144510")
        # if kiwoom_price and kiwoom_supply:
        #     return kiwoom_price, kiwoom_supply
        
        raise Exception("키움 API 지씨셀 시세 및 수급 미연결")

    except Exception as kiwoom_err:
        try:
            df = yf.Ticker("144510.KQ").history(period="2d")
            if not df.empty:
                current_price = float(df['Close'].iloc[-1])
                prev_price = float(df['Close'].iloc[-2]) if len(df) > 1 else current_price
                change_rate = ((current_price - prev_price) / prev_price) * 100
            else:
                current_price, change_rate = 0.0, 0.0
        except Exception as yf_err:
            print(f"[지씨셀 144510 수집 실패]: {yf_err}")
            current_price, change_rate = 0.0, 0.0
            
        supply_data = {
            "foreign": {"net": "-", "recent": "-"},
            "institution": {"net": "-", "recent": "-"},
            "retail": {"net": "-", "recent": "-"}
        }
        
        return {
            "price": round(current_price, 2),
            "rate": round(change_rate, 2),
            "supply": supply_data
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
    nbi_price, nbi_rate = fetch_market_index("nbi")
    
    gccell_data = fetch_gccell_data()
    
    return jsonify({
        "kospi": {"price": kospi_price, "rate": kospi_rate},
        "kosdaq": {"price": kosdaq_price, "rate": kosdaq_rate},
        "usd": {"price": usd_price, "rate": usd_rate},
        "nbi": {"price": nbi_price, "rate": nbi_rate},
        "gccell": gccell_data
    })

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)