import os
from flask import Flask, render_template, jsonify
import yfinance as yf
# 키움 API 관련 모듈이나 클라이언트가 있다면 이곳에 임포트하세요.
# from kwcli import KiwoomClient 

app = Flask(__name__)

# 키움 클라이언트 초기화 (필요시 활성화)
# kiwoom = KiwoomClient()

def fetch_market_index(market_type="kospi"):
    """
    1차로 키움증권 API에서 지수를 가져오고, 
    실패하거나 데이터가 없으면 2차로 야후 파이낸스(Fallback)에서 가져옵니다.
    - 코스피: 키움 '001' / 야후 '^KS11'
    - 코스닥: 키움 '101' / 야후 '^KQ11'
    """
    # 1단계: 키움증권 API 호출 시도
    try:
        kiwoom_code = "001" if market_type == "kospi" else "101"
        
        # [키움 API 연동 구간]
        # kiwoom_res = kiwoom.get_market_index(kiwoom_code)
        # if kiwoom_res and 'price' in kiwoom_res:
        #     return float(kiwoom_res['price']), float(kiwoom_res['change_rate'])
        
        # 현재 키움 호출부 미연결 상태이므로 예외를 발생시켜 야후 Fallback으로 유도
        raise Exception("키움 API 지수 조회 미연결 또는 응답 없음")

    except Exception as kiwoom_err:
        # 2단계: 야후 파이낸스(yfinance) 호출 시도 (Fallback)
        try:
            ticker_symbol = "^KS11" if market_type == "kospi" else "^KQ11"
            df = yf.Ticker(ticker_symbol).history(period="2d")
            
            if not df.empty:
                current_price = float(df['Close'].iloc[-1])
                prev_price = float(df['Close'].iloc[-2]) if len(df) > 1 else current_price
                change_rate = ((current_price - prev_price) / prev_price) * 100
                return round(current_price, 2), round(change_rate, 2)
        except Exception as yf_err:
            print(f"[{market_type.upper()} 지수 수집 실패] 키움 및 야후 조회 모두 실패: {yf_err}")
            
    return 0.0, 0.0

@app.route('/')
def index():
    # 코스피, 코스닥 지수 데이터 수집 (키움 1차 -> 야후 2차 Fallback 적용)
    kospi_price, kospi_rate = fetch_market_index("kospi")
    kosdaq_price, kosdaq_rate = fetch_market_index("kosdaq")
    
    # 템플릿에 전달할 데이터 딕셔너리
    market_data = {
        "kospi": {"price": kospi_price, "rate": kospi_rate},
        "kosdaq": {"price": kosdaq_price, "rate": kosdaq_rate}
    }
    
    return render_template('index.html', data=market_data)

@app.route('/api/data')
def api_data():
    kospi_price, kospi_rate = fetch_market_index("kospi")
    kosdaq_price, kosdaq_rate = fetch_market_index("kosdaq")
    
    return jsonify({
        "kospi": {"price": kospi_price, "rate": kospi_rate},
        "kosdaq": {"price": kosdaq_price, "rate": kosdaq_rate}
    })

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
