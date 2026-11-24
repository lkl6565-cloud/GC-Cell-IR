#!/usr/bin/env bash
# 카페24 서버 배포 스크립트 — GitHub Actions(.github/workflows/deploy.yml)가 push 때마다 실행
# 수동 실행: cd /root/gc-cell-project && bash deploy.sh
set -euo pipefail

APP_DIR="${APP_DIR:-/root/gc-cell-project}"
PORT="${PORT:-8000}"
cd "$APP_DIR"

echo "[1/4] 코드 받기"
git pull --ff-only origin main

echo "[2/4] 패키지 설치"
if [ -f venv/bin/activate ]; then source venv/bin/activate;
elif [ -f .venv/bin/activate ]; then source .venv/bin/activate; fi
PY="$(command -v python3 || command -v python)"
"$PY" -m pip install -q -r requirements.txt || "$PY" -m pip install -q --break-system-packages -r requirements.txt

echo "[3/4] 환경변수 확인"
touch .env
if [ -n "${LAW_OC:-}" ] && ! grep -q '^LAW_OC=' .env; then
  echo "LAW_OC=${LAW_OC}" >> .env
  echo "  LAW_OC 추가함"
fi

echo "[4/4] 서버 재시작"
SERVICE="$(systemctl list-units --type=service --all --no-legend 2>/dev/null \
  | awk '{print $1}' | grep -i -E 'gc|cell|serve|uvicorn|dashboard' | head -n1 || true)"
if [ -n "$SERVICE" ] && systemctl cat "$SERVICE" 2>/dev/null | grep -q "$APP_DIR"; then
  systemctl restart "$SERVICE"
  echo "  systemd 서비스 재시작: $SERVICE"
else
  pkill -f "serve.py" 2>/dev/null || true
  pkill -f "uvicorn serve:app" 2>/dev/null || true
  sleep 1
  PORT="$PORT" setsid nohup "$PY" serve.py > server.log 2>&1 < /dev/null &
  echo "  serve.py 재실행 (로그: $APP_DIR/server.log)"
fi

for i in $(seq 1 15); do
  if curl -sf "http://localhost:${PORT}/healthz" > /dev/null; then
    echo "배포 완료: $(git log --oneline -1)"
    exit 0
  fi
  sleep 2
done
echo "서버 응답 없음 — server.log 확인 필요"; tail -n 30 server.log 2>/dev/null || true
exit 1
