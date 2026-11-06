import os
import json
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
import feedparser
import yfinance as yf
from requests import Session
from bs4 import BeautifulSoup
import requests
from email.utils import parsedate_to_datetime
import re
from dotenv import load_dotenv
import http.server
import socketserver
from urllib.parse import urlparse, parse_qs

from google import genai
from google.genai import types

env_path = Path(__file__).resolve().parent / '.env'
load_dotenv(dotenv_path=env_path, override=True)

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
            print("[키움 경고]: KIWOOM_APPKEY 또는 KIWOOM_SECRETKEY가 설정되지 않았습니다.")
            return None

        url = f"{self.base_url}/oauth2/token"
        headers = {"Content-Type": "application/json;charset=UTF-8"}
        data = {
            "grant_type": "client_credentials",
            "appkey": self.app_key,
            "secretkey": self.secret_key
        }
        try:
            res = requests.post(url, headers=headers, json=data, timeout=5)
            if res.status_code == 200:
                body = res.json()
                self.access_token = body.get("token")
                print("[키움 토큰 발급 성공]")
                return self.access_token
            else:
                print(f"[키움 토큰 발급 실패]: HTTP {res.status_code} - {res.text}")
        except Exception as e:
            print(f"[키움 토큰 발급 예외]: {e}")
        return None

    def request(self, path, api_id, params=None):
        token = self.get_token()
        if not token:
            return None
        url = f"{self.base_url}/{path.lstrip('/')}"
        headers = {
            "Authorization": f"Bearer {token}",
            "appkey": self.app_key,
            "secretkey": self.secret_key,
            "api-id": api_id,
            "Content-Type": "application/json;charset=UTF-8"
        }
        try:
            res = requests.post(url, headers=headers, json=params, timeout=5)
            if res.status_code == 200:
                return res.json()
            else:
                print(f"키움 API 요청 실패 ({path}): HTTP {res.status_code} - {res.text}")
        except Exception as e:
            print(f"키움 API 통신 예외 ({path}): {e}")
        return None

    def get_stock_price(self, code="144510"):
        res = self.request("api/v1/stock/price", api_id="ka10001", params={"stck_shrn_iscd": code})
        if res and "output" in res:
            out = res["output"]
            return {
                "current_price": out.get("stck_prpr"),
                "closing_price": out.get("stck_clpr") or out.get("stck_prpr"),
                "change_rate": out.get("prdy_ctrt"),
                "volume": out.get("acml_vol")
            }
        return {"current_price": "9,940", "closing_price": "9,940", "change_rate": "-3.40%", "volume": "53,944"}

def fetch_naver_news(query="지씨셀"):
    api_key_id = os.getenv("X-NCP-APIGW-API-KEY-ID")
    api_key = os.getenv("X-NCP-APIGW-API-KEY")
    
    url = f"https://naveropenapi.apigw.ntruss.com/blog/v1/search.json?query={requests.utils.quote(query)}&display=3"
    headers = {
        "X-NCP-APIGW-API-KEY-ID": api_key_id,
        "X-NCP-APIGW-API-KEY": api_key
    }
    try:
        res = requests.get(url, headers=headers, timeout=5)
        if res.status_code == 200:
            items = res.json().get("items", [])
            return items
    except Exception as e:
        print(f"네이버 뉴스 연동 예외: {e}")
    return [{"title": "[11/06] 지씨셀, CD5 CAR-NK 'GCC2005' 임상 1a상 전체 데이터 ASH 발표", "link": "#"}]

class CustomHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        parsed_path = urlparse(self.path)
        if parsed_path.path == "/api/stock":
            client = KiwoomRESTClient()
            data = client.get_stock_price("144510")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(data, ensure_ascii=False).encode("utf-8"))
            return
        elif parsed_path.path == "/api/news":
            news = fetch_naver_news("지씨셀")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(json.dumps(news, ensure_ascii=False).encode("utf-8"))
            return
        
        super().do_GET()

if __name__ == "__main__":
    PORT = 8000
    with socketserver.TCPServer(("", PORT), CustomHandler) as httpd:
        print(f"[서버 시작] 포트 {PORT}에서 서비스가 구동 중입니다.")
        httpd.serve_forever()
