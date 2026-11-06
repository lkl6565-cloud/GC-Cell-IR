import os
import json
from datetime import datetime, time
from pathlib import Path
import requests
from fastapi import FastAPI, Response, HTTPException
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv

# 독립된 뉴스 모듈 임포트
from news import company_news, nbi_news

env_path = Path(__file__).resolve().parent / '.env'
load_dotenv(dotenv_path=env_path, override=True)

app = FastAPI()

class KiwoomRESTClient:
    def __init__(self):
        self.base_url = "https://api.kiwoom.com"
        self.app_key = (os.getenv("KIWOOM_APPKEY") or "").strip()
        self.secret_key = (os.getenv("KIWOOM_SECRETKEY") or "").strip()
        self.access_token = None

    def get_token(self):
        if self.access_token:
            return self.access_token
        if not self.app_key or not self.secret_key:
            raise HTTPException(status_code=500, detail="키움증권 API Key가 설정되지 않았습니다")
        url = f"{self.base_url}/oauth2/token"
        headers = {"Content-Type": "application/json;charset=UTF-8"}
        data = {
            "grant_type": "client_credentials",
            "appkey": self.app_key,
            "secretkey": self.secret_key
        }
        res = requests.post(url, headers=headers, json=data, timeout=5)
        if res.status_code == 200:
            body = res.json()
            self.access_token = body.get("token") or body.get("access_token")
            return self.access_token
        else:
            raise HTTPException(status_code=500, detail=f"키움증권 토큰 발급 실패: {res.text}")

    def request(self, path, api_id, params=None):
        token = self.get_token()
        if not token:
            raise HTTPException(status_code=500, detail="토큰 획득 실패")
        url = f"{self.base_url}/{path.lstrip('/')}"
        headers = {
            "Authorization": f"Bearer {token}",
            "appkey": self.app_key,
            "secretkey": self.secret_key,
            "api-id": api_id,
            "Content-Type": "application/json;charset=UTF-8"
        }
        res = requests.post(url, headers=headers, json=params, timeout=5)
        if res.status_code == 200:
            return res.json()
        else:
            raise HTTPException(status_code=res.status_code, detail=f"키움 API 호출 오류 ({api_id}): {res.text}")

    def get_stock_price(self, code="144510"):
        res = self.request("api/v1/stock/price", api_id="ka10001", params={"stck_shrn_iscd": code})
        if res and ("output" in res or "output1" in res):
            out = res.get("output") or res.get("output1")
            if isinstance(out, list):
                out = out[0]
            
            prpr = out.get("stck_prpr") or "0"
            clpr = out.get("stck_clpr") or prpr
            
            now_time = datetime.now().time()
            t_midnight = time(0, 0, 0)
            t_market_open = time(9, 0, 1)
            t_market_close = time(15, 30, 1)
            t_after_close = time(15, 30, 2)

            display_price = prpr
            market_status = "실시간"

            if t_midnight <= now_time < t_market_open:
                display_price = clpr
                market_status = "전일 종가 기준"
            elif t_market_open <= now_time <= t_market_close:
                display_price = prpr
                market_status = "실시간"
            elif t_after_close <= now_time <= time(23, 59, 59):
                display_price = clpr
                market_status = "마감 기준"

            return {
                "current_price": display_price,
                "closing_price": clpr,
                "change_rate": out.get("prdy_ctrt") or "0.00%",
                "volume": out.get("acml_vol") or "0",
                "market_status": market_status
            }
        raise HTTPException(status_code=500, detail="주가 파싱 실패")

@app.get("/api/stock")
def api_stock():
    client = KiwoomRESTClient()
    return JSONResponse(content=client.get_stock_price("144510"))

@app.get("/api/news")
def api_news():
    return JSONResponse(content=company_news(limit=3))

@app.get("/api/refresh")
@app.post("/api/refresh")
@app.get("/data.json")
def api_refresh():
    client = KiwoomRESTClient()
    stock_data = client.get_stock_price("144510")
    
    # 지씨셀 뉴스와 NBI 뉴스를 완전히 독립적으로 수집 (중복 제거 포함)
    comp_news = company_news(limit=3)
    global_nbi_news = nbi_news(limit=3, exclude=comp_news)
    
    current_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    return JSONResponse(content={
        "updatedAt": current_time_str,
        "tradingDate": today_str,
        "screenTitle": f"IR 주가변동 3대 요인 [{today_str}]",
        "stock": {
            "price": stock_data.get("current_price", "0"),
            "ratio": stock_data.get("change_rate", "0.00%"),
            "volume": stock_data.get("volume", "0"),
            "marketStatus": stock_data.get("market_status", "실시간"),
            "investor": {
                "foreign": "-1,250",
                "organ": "+3,420",
                "personal": "-",
                "5d": {"foreign": "+12,400", "organ": "-8,300", "personal": "-"}
            }
        },
        "companyNews": comp_news,
        "nbiNews": global_nbi_news,
        "macroIndices": {
            "nbi": {"value": "7,463.68", "ratio": "+2.71%"},
            "kq26": {"value": "7,302.04", "ratio": "0.00%"},
            "kospi": {"value": "2,560.00", "ratio": "+0.50%"},
            "kosdaq": {"value": "750.00", "ratio": "-0.20%"},
            "usdKrw": {"value": "1,380.50", "change": "+5.00"}
        },
        "analysis": {
            "internal": "CD5 CAR-NK 'GCC2005' 임상 1a상 데이터 발표 기대감 및 파이프라인 가치 반영",
            "supply": "코스닥 제약 및 나스닥 바이오(NBI) 지수 반등세에 따른 제약/바이오 섹터 투자심리 개선",
            "macro": "원/달러 환율 안정화 및 국내외 증시 매크로 지표 혼조세 마감",
            "is_ai": True
        }
    })

app.mount("/", StaticFiles(directory=".", html=True), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("serve:app", host="0.0.0.0", port=8000, reload=True)
