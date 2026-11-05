import os
from flask import Flask, render_template, jsonify
import yfinance as yf

app = Flask(__name__)

def fetch_market_index(market_type="kospi"):
    """
    야후 파이낸스(yfinance)를 통해 주요 지수 및 환율 데이터를 수집합니다.
    - 코스피: ^KS11
    - 코스닥: ^KQ11
    - 원/달러 환율: USDKRW=X
    - 나스닥 바이오: ^NBI
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
    지씨셀(종목코드: 144510) 주가 및 투자자별 수급현황 수집
    - 1차: 키움증권 REST API (종목 시세 및 투자자별 매매동향 조회)
    - 2차(Fallback): 야후 파이낸스(144510.KQ) 주가 조회 및 수급 기본값 처리
    """
    try:
        # [키움증권 API 연동 구간 - 종목코드 144510]
        # kiwoom_price = kiwoom.get_stock_price("144510")
        # kiwoom_supply = kiwoom.get_investor_trend("144510")
        # if kiwoom_price and kiwoom_supply:
        #     return kiwoom_price, kiwoom_supply
        
        # 현재 키움 API 미연결 상태이므로 예외 발생 후 Fallback 유도
        raise Exception("키움 API 지씨셀 시세 및 수급 미연결")

    except Exception as kiwoom_err:
        # Fallback: 야후 파이낸스(yfinance)를 통한 지씨셀 코스닥 주가 조회
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
            
        # 키움 미연결 시 수급 데이터 기본 구조 (추후 키움 API 연동 시 대체됨)
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

@app.route('/api/data')
@app.route('/api/refresh')
@app.route('/data.json')
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