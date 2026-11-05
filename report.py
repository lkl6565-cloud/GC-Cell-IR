import os
import json
from pathlib import Path
from dotenv import load_dotenv
import requests

# .env 파일 경로 명시적 지정 및 override 설정
env_path = Path(__file__).resolve().parent / '.env'
load_dotenv(dotenv_path=env_path, override=True)

def load_dashboard_data():
    """
    serve.py가 생성해 둔 data.json 파일을 읽어와 최신 데이터를 반환합니다.
    """
    json_path = Path(__file__).resolve().parent / 'data.json'
    if not json_path.exists():
        raise FileNotFoundError("[오류]: data.json 파일이 존재하지 않습니다. 먼저 serve.py를 실행해 데이터를 갱신해주세요.")
    
    with open(json_path, "r", encoding="utf-8") as f:
        return json.load(f)

def send_email_report():
    """
    data.json에 저장된 최신 데이터를 기반으로 마감 리포트 이메일 발송 작업을 수행합니다.
    """
    try:
        data = load_dashboard_data()
        
        updated_at = data.get("updatedAt", "알 수 없음")
        stock_info = data.get("stock", {})
        price = stock_info.get("price", "N/A")
        ratio = stock_info.get("ratio", "N/A")
        volume = stock_info.get("volume", "N/A")
        
        print("=== [마감 리포트 이메일 발송 준비] ===")
        print(f"- 기준 시간: {updated_at}")
        print(f"- 지씨셀 종가: {price}원 ({ratio})")
        print(f"- 거래량: {volume}주")
        
        # TODO: 실제 이메일 발송 로직 구현 (SMTP 또는 외부 메일링 API 연동)
        # 예: send_smtp_mail(...) 또는 네이버/구글 메일 API 활용
        
        print("--- [마감 리포트 전송 완료] ---")
        
    except Exception as e:
        print(f"[리포트 발송 중 예외 발생]: {e}")

if __name__ == "__main__":
    send_email_report()
