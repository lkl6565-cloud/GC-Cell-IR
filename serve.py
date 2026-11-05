import http.server
import socketserver
import os
import subprocess
import json
from dotenv import load_dotenv

load_dotenv()
appkey = os.getenv("KIWOOM_APPKEY")
secretkey = os.getenv("KIWOOM_SECRETKEY")

PORT = 8765

class IRDashboardHandler(http.server.SimpleHTTPRequestHandler):
    def do_POST(self):
        if self.path == '/api/refresh':
            try:
                # report.py를 실행하여 data.json 갱신
                subprocess.run(["python", "report.py"], check=True)
                
                if os.path.exists("data.json"):
                    with open("data.json", "r", encoding="utf-8") as f:
                        content = f.read()
                    self.send_response(200)
                    self.send_header("Content-type", "application/json; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(content.encode('utf-8'))
                    return
                else:
                    self.send_response(500)
                    self.send_header("Content-type", "application/json; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(json.dumps({"error": "data.json 파일 생성 실패"}).encode('utf-8'))
                    return
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"error": str(e)}).encode('utf-8'))
                return
        else:
            self.send_error(404, "Not Found")

    def do_GET(self):
        if self.path == '/' or self.path == '/index.html':
            if os.path.exists("index.html"):
                self.send_response(200)
                self.send_header("Content-type", "text/html; charset=utf-8")
                self.end_headers()
                with open("index.html", "rb") as f:
                    self.wfile.write(f.read())
                return
            else:
                self.send_error(404, "index.html 파일을 찾을 수 없습니다.")
                return
        elif self.path == '/data.json':
            if not os.path.exists("data.json"):
                try:
                    subprocess.run(["python", "report.py"], check=True)
                except Exception:
                    pass
            if os.path.exists("data.json"):
                self.send_response(200)
                self.send_header("Content-type", "application/json; charset=utf-8")
                self.end_headers()
                with open("data.json", "rb") as f:
                    self.wfile.write(f.read())
                return
        super().do_GET()

if not appkey or not secretkey:
    print("재시도(토큰 재발급): KIWOOM_APPKEY / KIWOOM_SECRETKEY 미설정 (.env 확인)")
else:
    print("키움증권 API 인증키 로드 완료")

with socketserver.TCPServer(("", PORT), IRDashboardHandler) as httpd:
    print(f"대시보드: http://127.0.0.1:{PORT}  (종료: Ctrl+C)")
    httpd.serve_forever()