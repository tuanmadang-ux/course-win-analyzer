#!/usr/bin/env bash
# Cài đặt 1 lần. Chạy: bash setup.sh
set -e

echo "=== Trợ lý cắt video — cài đặt ==="

# --- 1. ffmpeg ---
if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "→ Chưa có ffmpeg, đang thử cài..."
  if command -v brew >/dev/null 2>&1;      then brew install ffmpeg
  elif command -v apt-get >/dev/null 2>&1; then sudo apt-get update && sudo apt-get install -y ffmpeg
  elif command -v dnf >/dev/null 2>&1;     then sudo dnf install -y ffmpeg
  else
    echo "  ✗ Hãy tự cài ffmpeg rồi chạy lại (Windows: winget install Gyan.FFmpeg)"
    exit 1
  fi
fi
echo "✓ ffmpeg: $(ffmpeg -version | head -1)"

# --- 2. Môi trường Python ---
if [ ! -d ".venv" ]; then
  echo "→ Tạo môi trường ảo .venv"
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

python -m pip install --upgrade pip -q
echo "→ Cài thư viện Python (lần đầu sẽ hơi lâu)..."
pip install -q -r requirements.txt

# --- 3. File .env ---
if [ ! -f ".env" ]; then
  cp .env.example .env
  echo "✓ Đã tạo file .env — mở ra điền API key khi nào bạn có."
fi

cat <<'EOF'

=== Xong! ===

Chạy phần mềm:
    source .venv/bin/activate
    python run.py

Lần đầu chạy, Whisper sẽ tự tải model (~3GB với large-v3).

Muốn bật đầy đủ tính năng AI + B-roll, mở file .env và điền:
    ANTHROPIC_API_KEY   -> https://console.anthropic.com
    PEXELS_API_KEY      -> https://www.pexels.com/api/new/   (miễn phí)
    PIXABAY_API_KEY     -> https://pixabay.com/api/docs/     (miễn phí)

EOF
