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

# Google GenAI SDK 임포트
from google import genai
from google.genai import types

# .env 파일 경로 명시적 지정 및 override 설정
env_path = Path(__file__).resolve().parent / '.env'
load_dotenv(dotenv_path=env_path, override=True)

class KiwoomRESTClient:
    """
    키움증권 REST API 공식 가이드(https://openapi.kiwoom.com) 기준 클라이언트 클래스
    """
    def __init__(self):
        # 공식 REST API 베이스 URL 설정
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

        auth_url = f"{self.base_url}/oauth2/token"
        headers = {"Content-Type": "application/json; charset=utf-8"}
        payload = {
            "grant_type": "client_credentials",
            "appkey": self.app_key,
            "secretkey": self.secret_key
        }

        try:
            res = requests.post(auth_url, json=payload, headers=headers, timeout=5)
            if res.status_code == 200:
                data = res.json()
                self.access_token = data.get("access_token")
                return self.access_token
            else:
                print(f"[키움 토큰 발급 실패]: HTTP {res.status_code} - {res.text}")
        except Exception as e:
            print(f"[키움 토큰 발급 예외]: {e}")
        return None

    def request(self, path, params=None):
        token = self.get_token()
        if not token:
            return None

        url = f"{self.base_url}/{path.lstrip('/')}"
        headers = {
            "Authorization": f"Bearer {token}",
            "appkey": self.app_key,
            "secretkey": self.secret_key,
            "Content-Type": "application/json; charset=utf-8"
        }

        try:
            res = requests.get(url, headers=headers, params=params, timeout=5)
            if res.status_code == 200:
                return res.json()
            else:
                print(f"[키움 API 요청 실패 ({path})]: HTTP {res.status_code} - {res.text}")
        except Exception as e:
            print(f"[키움 API 통신 예외 ({path})]: {e}")
        return None

kiwoom_client = KiwoomRESTClient()

def get_safe_yf_history(ticker_symbol, period="5d", retries=3, backoff_factor=2):
    session = Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.8,en-US;q=0.5,en;q=0.3"
    })
    
    for attempt in range(retries):
        try:
            ticker = yf.Ticker(ticker_symbol, session=session)
            hist = ticker.history(period=period)
            return hist
        except Exception as e:
            print(f"[야후 파이낸스 요청 실패 ({ticker_symbol}), 시도 {attempt+1}/{retries}]: {e}")
            if "429" in str(e):
                sleep_time = backoff_factor ** (attempt + 1)
                time.sleep(sleep_time)
            else:
                time.sleep(1)
    return yf.DataFrame()

def scrape_investing_index(url_path_hint):
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept-Language": "ko-KR,ko;q=0.9"
        }
        search_url = f"https://www.investing.com/search/?q={requests.utils.quote(url_path_hint)}"
        res = requests.get(search_url, headers=headers, timeout=4)
        if res.status_code == 200:
            return None, None
    except Exception as e:
        print(f"[Investing.com 크롤링 예외 ({url_path_hint})]: {e}")
    return None, None

def get_stock_data_with_cli_and_fallback(code="144510"):
    price, ratio, volume = "0", "0.00%", "0"
    success = False

    # 1순위: 키움 REST API 호출
    api_data = kiwoom_client.request("domestic/stocks/info", {"code": code})
    if api_data and isinstance(api_data, dict):
        try:
            p_val = int(api_data.get("clpr", api_data.get("stck_clpr", 0)))
            chg_val = float(api_data.get("change_rate", api_data.get("rate", api_data.get("vsrt", 0))))
            vol_val = int(api_data.get("volume", api_data.get("acml_vol", 0)))
            if p_val > 0:
                price = f"{p_val:,.0f}"
                ratio = f"{'+' if chg_val > 0 else ''}{chg_val:.2f}%"
                volume = f"{vol_val:,}"
                success = True
                print(f"[키움 주가 수치 연동 성공]: 종가={price}, 등락률={ratio}")
        except Exception as e:
            print(f"[키움 주가 파싱 예외]: {e}")

    # 2순위: 야후 파이낸스 백업 호출
    if not success:
        try:
            hist = get_safe_yf_history(f"{code}.KQ", period="5d")
            if not hist.empty:
                p_val = hist['Close'].iloc[-1]
                if p_val == p_val:
                    p_prev = hist['Close'].iloc[-2] if len(hist) > 1 else p_val
                    chg_val = ((p_val - p_prev) / p_prev) * 100 if p_prev else 0.0
                    vol_val = int(hist['Volume'].iloc[-1]) if hist['Volume'].iloc[-1] == hist['Volume'].iloc[-1] else 0
                    price = f"{p_val:,.0f}"
                    ratio = f"{'+' if chg_val > 0 else ''}{chg_val:.2f}%"
                    volume = f"{vol_val:,}"
                    success = True
                    print(f"[야후 파이낸스 주가 수치 연동 성공]: 종가={price}, 등락률={ratio}")
        except Exception as e:
            print(f"[주가 2차 검증 예외 -
